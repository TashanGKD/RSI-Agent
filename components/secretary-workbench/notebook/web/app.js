'use strict';

(() => {
  const STATES = ['待判断', '待办', '等对方', '暂缓', '已完成', '不用管了'];
  const KINDS = {action:'动作',memo:'备忘',project:'项目',goal:'目标'};
  const canonicalState = state => ({'待处理':'待办','进行中':'待办','已结束':'不用管了','交给AI处理':'待办','稍后提醒':'待办'})[state] || state;
  const taskKind = task => Object.hasOwn(KINDS, task.kind) ? task.kind : 'action';
  const actualState = task => canonicalState(task.selectedState) || '待判断';
  const isClosed = task => ['已完成','不用管了'].includes(actualState(task));
  const needsReview = task => typeof task.needsReview==='boolean' ? task.needsReview : !task.reviewedByHuman;
  const PAGE_SIZE = 30;
  const STORAGE_KEY = 'tashan-personal-actions-drafts-v2';
  const LEGACY_STORAGE_KEY = 'tashan-personal-actions-drafts-v1';
  const CREATE_STORAGE_KEY = 'tashan-personal-actions-create-draft-v1';
  let restoredCreateRelations=null,createPending=null;
  const drafts = new Map();
  const saving = new Set();
  const notified = new Set();
  const $ = id => document.getElementById(id);
  const zone = 'Asia/Shanghai';
  let tasks = [], csrfToken = '', meta = {}, page = 1, drawerId = null, drawerDetail = null, returnFocus = null, pollRunning = false;
  let restored = {};
  let renderedTaskIds = '';
  try { restored = JSON.parse(localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY) || '{}'); } catch (_) { /* Draft persistence is optional. */ }

  function node(tag, cls, text) {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }
  function clear(element) { element.replaceChildren(); return element; }
  function controlFocus(root) {
    const active=document.activeElement;
    if(!root.contains(active))return null;
    const id=active.closest('[data-editor-for]')?.dataset.editorFor || active.dataset.confirmFor;
    if(!id)return null;
    let selector;
    if(active.dataset.state)selector=`[data-state="${CSS.escape(active.dataset.state)}"]`;
    else if(active.dataset.reminderKind)selector=`[data-reminder-kind="${CSS.escape(active.dataset.reminderKind)}"]`;
    else selector=['.note','.assignee-select','.assignee-name','input[type="datetime-local"]','.add-note','[data-confirm-for]'].find(value=>active.matches(value));
    if(!selector)return null;
    return {id,selector,confirm:active.hasAttribute('data-confirm-for'),start:active.selectionStart,end:active.selectionEnd};
  }
  function restoreControlFocus(root, saved) {
    if(!saved)return;
    const editor=[...root.querySelectorAll('[data-editor-for]')].find(item=>item.dataset.editorFor===saved.id);
    const control=saved.confirm ? root.querySelector(`[data-confirm-for="${CSS.escape(saved.id)}"]`) : editor?.querySelector(saved.selector);
    if(!control || control.disabled || control.hidden)return;
    control.focus({preventScroll:true});
    if(typeof saved.start==='number' && typeof control.setSelectionRange==='function')control.setSelectionRange(saved.start,saved.end);
  }
  function taskById(id) { return tasks.find(task => task.id === id); }
  function focusReviewItem(id) {
    if(drawerId || $('view').value!=='待我确认' || !$('create-panel').hidden)return;
    const row=id ? document.querySelector(`[data-task-id="${CSS.escape(id)}"]`) : $('tasks').querySelector('.task-row');
    const control=row?.querySelector('.choice[aria-checked="true"]') || row?.querySelector('[data-confirm-for]');
    if(control){control.focus({preventScroll:true});row.scrollIntoView({block:'nearest'});}
  }
  function date(value, options) {
    if (!value) return '时间待核实';
    const calendar = typeof value === 'string' && /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    const parsed = calendar ? new Date(`${value}T00:00:00+08:00`) : new Date(value);
    return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleString('zh-CN', {...(options || {year:'numeric', month:'long', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false}),timeZone:zone});
  }
  function proposedTime(task) {
    const value=task.proposedAt;
    return typeof value==='string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : task.proposedDisplayAt || (typeof value==='string' ? value : null);
  }
  function localInput(iso) {
    const d = iso ? new Date(iso) : new Date(Date.now() + 86400000);
    if (Number.isNaN(d.valueOf())) return '';
    const fields=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(d).map(part=>[part.type,part.value]));
    return `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}`;
  }
  function originalReminder(task) {
    return task.reminder ? {kind:task.reminder.kind, at:task.reminder.at, timezone:task.reminder.timezone} : null;
  }
  function freshDraft(task) {
    const recommendation=canonicalState(task.recommendation?.state);
    const proposed=taskKind(task)==='action' && !task.reviewedByHuman && STATES.includes(recommendation) ? recommendation : actualState(task);
    const state = STATES.includes(proposed) ? proposed : STATES.includes(canonicalState(task.suggestedState)) ? canonicalState(task.suggestedState) : '待判断';
    const assignee = task.assignee || (task.selectedState === '交给AI处理' ? 'AI' : '我');
    return {state, kind:taskKind(task), baseKind:taskKind(task), assignee, note:'', revision:task.revision, baseState:state, baseAssignee:assignee, timeZone:zone, reminderEnabled:Boolean(task.reminder), reminderOriginal:originalReminder(task), reminderKind:task.reminder?.kind || null, customLocal:localInput(task.reminder?.at), reminderTouched:false, conflict:false, error:''};
  }
  function dirty(draft) { return draft.kind !== draft.baseKind || draft.state !== draft.baseState || draft.assignee !== draft.baseAssignee || Boolean(draft.note.trim()) || draft.reminderTouched; }
  function draftFor(task) {
    if (!drafts.has(task.id)) {
      const stored = restored[task.id];
      let draft = freshDraft(task);
      if (stored && typeof stored.note === 'string' && Number.isInteger(stored.revision)) {
        const legacy = Object.hasOwn(stored, 'baseNote');
        draft = {...draft, ...stored, error:''};
        if(stored.timeZone!==zone){
          if(stored.reminderTouched && stored.reminderEnabled && stored.reminderKind==='custom' && stored.customLocal){
            const previousLocal=new Date(stored.customLocal);
            if(!Number.isNaN(previousLocal.valueOf()))draft.customLocal=localInput(previousLocal.toISOString());
          }else draft.customLocal=localInput(task.reminder?.at);
          draft.timeZone=zone;
        }
        if (legacy) {
          // Previously saved notes were prefilled; only preserve actual unsaved text.
          draft.note = stored.note === stored.baseNote ? '' : stored.note;
          if (stored.state === '交给AI处理') { draft.state='待办'; draft.assignee='AI'; }
          if (stored.state === '稍后提醒') { draft.state='待办'; draft.reminderEnabled=true; draft.reminderTouched=true; }
          draft.baseState = STATES.includes(canonicalState(stored.baseState)) ? canonicalState(stored.baseState) : '待办';
          delete draft.baseNote;
        }
        draft.state=canonicalState(draft.state);draft.baseState=canonicalState(draft.baseState);
        if (!STATES.includes(draft.state)) draft.state='待判断';
        if(!Object.hasOwn(KINDS,draft.kind))draft.kind=taskKind(task);
        if(!Object.hasOwn(KINDS,draft.baseKind))draft.baseKind=taskKind(task);
      }
      if (draft.revision !== task.revision && dirty(draft)) draft.conflict = true;
      else if (draft.revision !== task.revision) draft = freshDraft(task);
      drafts.set(task.id, draft);
    }
    return drafts.get(task.id);
  }
  function persist() {
    const values = {};
    for (const [id, draft] of drafts) if (dirty(draft)) values[id] = draft;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(values)); } catch (_) { /* The current page still retains drafts. */ }
    restored = values;
    persistCreateDraft();
  }
  async function api(path, payload) {
    const options = {credentials:'same-origin', cache:'no-store'};
    if (payload !== undefined) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrfToken}, body:JSON.stringify(payload)});
    const response = await fetch(path, options);
    let body;
    try { body = await response.json(); } catch (_) { throw new Error('服务返回异常，请稍后刷新列表。'); }
    if (!response.ok) { const error = new Error(body.error || '操作未保存，请重试。'); error.status = response.status; error.code = body.code; throw error; }
    return body;
  }
  function updateTask(task) {
    const index = tasks.findIndex(item => item.id === task.id);
    if (index >= 0 && tasks[index].revision > task.revision) return false;
    if (index >= 0) tasks[index] = task; else tasks.push(task);
    if (drafts.has(task.id)) {
      const draft = drafts.get(task.id);
      if (!dirty(draft)) drafts.set(task.id, freshDraft(task));
      else if (draft.revision !== task.revision) draft.conflict = true;
    }
    return true;
  }
  function applyBootstrap(data) {
    csrfToken = data.csrfToken;
    const previousTasks = new Map(tasks.map(task=>[task.id,task]));
    tasks = (data.tasks || []).map(task=>previousTasks.get(task.id)?.revision > task.revision ? previousTasks.get(task.id) : task);
    const receivedIds=new Set(tasks.map(task=>task.id));
    for (const task of previousTasks.values()) if (!receivedIds.has(task.id)) tasks.push(task);
    meta = data.meta || {};
    for (const task of tasks) {
      const draft = draftFor(task);
      if (draft.revision !== task.revision) {
        if (dirty(draft)) draft.conflict = true;
        else drafts.set(task.id, freshDraft(task));
      }
    }
    const previous = $('person').value;
    clear($('person')).append(new Option('相关人', ''));
    const people = new Set();
    for (const task of tasks) for (const person of task.people?.length ? task.people : [task.counterparty]) if (person) people.add(person);
    [...people].sort((a,b) => a.localeCompare(b,'zh-CN')).forEach(person => $('person').append(new Option(person, person)));
    if (people.has(previous)) $('person').value = previous;
    renderCreateRelated();
    renderCoverage(data.notificationMode);
    renderList();
    if (drawerId && taskById(drawerId)) { renderDrawerContent(drawerDetail); renderDrawerEditor(); }
    persist();
  }
  function filteredTasks() {
    const search = $('search').value.trim().toLocaleLowerCase();
    const person = $('person').value;
    const selectedView=$('view').value;
    const view = ['待处理','进行中','已结束'].includes(selectedView) ? canonicalState(selectedView) : selectedView;
    const owner=$('owner').value;
    const result = tasks.filter(task => {
      if (task.active === false && view !== '全部') return false;
      const people = task.people?.length ? task.people : [task.counterparty];
      if(owner && (task.assignee || '我')!==owner)return false;
      if (person && !people.includes(person) && task.counterparty !== person) return false;
      if (search && ![task.title, task.counterparty, ...people, task.note,...(task.sourceContacts || []).flatMap(c=>[c.conversationName,c.senderName,c.replyToName])].filter(Boolean).join(' ').toLocaleLowerCase().includes(search)) return false;
      if (view === '待我确认') return taskKind(task)==='action' && needsReview(task) && !isClosed(task) && !isSnoozed(task);
      if (['备忘','项目','目标'].includes(view)) return KINDS[taskKind(task)]===view;
      if (STATES.includes(view) && taskKind(task)!=='action') return false;
      if (view === '交给AI处理') return task.assignee === 'AI';
      if (view === '分派给他人') return !['我','AI'].includes(task.assignee || '我');
      if (view === '稍后提醒') return Boolean(task.reminder) && !isClosed(task);
      if (view === '进展记录') return task.progressCount > 0;
      if (view === '到时提醒') return isDue(task);
      return view === '全部' || actualState(task) === view;
    });
    if (view === '待我确认') {
      const rank = task => {if(isDue(task))return 0;const state=needsReview(task) && !task.reviewedByHuman ? canonicalState(task.recommendation?.state) || actualState(task) : actualState(task);return {'待办':1,'等对方':2,'待判断':3,'暂缓':4}[state] ?? 5;};
      result.sort((a,b) => rank(a)-rank(b) || (a.deadlineDate || '9999').localeCompare(b.deadlineDate || '9999'));
    }
    return result;
  }
  function isDue(task) { return !isClosed(task) && task.reminder && new Date(task.reminder.at).valueOf() <= Date.now(); }
  function isSnoozed(task) { return task.reminder && new Date(task.reminder.at).valueOf() > Date.now(); }
  function compactTime(task) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(task.deadlineDate || '')) return '时间待定';
    const [, month, day] = task.deadlineDate.split('-').map(Number);
    return `${month}月${day}日${/前|截止/.test(task.timeRequirement || '') ? '前' : ''}`;
  }
  function renderList() {
    const previousOwner=$('owner').value;
    const owners=[...new Set(tasks.map(task=>task.assignee || '我'))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
    clear($('owner')).append(new Option('全部负责人',''));owners.forEach(owner=>$('owner').append(new Option(owner,owner)));if(owners.includes(previousOwner))$('owner').value=previousOwner;
    const focus=controlFocus($('tasks'));
    const filtered = filteredTasks();
    renderedTaskIds = filtered.map(task=>task.id).join(',');
    const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    page = Math.min(page, pages);
    $('result-count').textContent = `${filtered.length} 项`;
    const host = clear($('tasks'));
    for (const task of filtered.slice((page-1)*PAGE_SIZE, page*PAGE_SIZE)) host.append(renderRow(task));
    if (!filtered.length) host.append(node('p', 'empty', '这个视图暂无事项。可切换筛选条件查看。'));
    const pagination = clear($('pagination'));
    if (filtered.length) {
      const previous = node('button', '', '上一页'); previous.disabled = page <= 1;
      previous.addEventListener('click', () => {page--; renderList(); $('tasks').scrollIntoView({block:'start'});});
      const next = node('button', '', '下一页'); next.disabled = page >= pages;
      next.addEventListener('click', () => {page++; renderList(); $('tasks').scrollIntoView({block:'start'});});
      pagination.append(node('span', '', `${(page-1)*PAGE_SIZE+1}–${Math.min(page*PAGE_SIZE, filtered.length)} / ${filtered.length}`), previous, node('span', '', `${page} / ${pages}`), next);
    }
    restoreControlFocus($('tasks'),focus);
  }
  function summaryProvenance(task) {
    const details=[];
    if(task.lastKnownStateSourceTime)details.push(`来源时间：${date(task.lastKnownStateSourceTime)}`);
    if(task.lastKnownStateUpdatedAt)details.push(`整理时间：${date(task.lastKnownStateUpdatedAt)}`);
    return details;
  }
  async function copySourceName(value, button) {
    try {
      if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(value);
      else throw new Error('clipboard unavailable');
    } catch (_) {
      const field=node('textarea','clipboard-fallback');field.value=value;field.readOnly=true;document.body.append(field);field.select();
      let copied=false;try{copied=document.execCommand('copy');}catch(_){/* Keep manual selection as the fallback. */}field.remove();button.focus({preventScroll:true});
      if(!copied){toast('复制未成功，请在来源名称上选中文字复制。');return;}
    }
    toast('名称已复制。');
  }
  function renderSourceContacts(task, expanded=false) {
    const host=node('div','source-contacts');
    const identities=new Map();
    for(const contact of task.sourceContacts || []) {
      const key=JSON.stringify([contact.channel,contact.conversationName,contact.senderName,contact.replyToName || '']);
      if(!identities.has(key))identities.set(key,contact);
    }
    let unique=[...identities.values()];
    if(!expanded && unique.some(c=>c.channel!=='共同记事本'))unique=unique.filter(c=>c.channel!=='共同记事本');
    for(const contact of expanded ? unique : unique.slice(0,2)) {
      const line=node('div','source-contact');
      if(contact.channel)line.append(node('span','source-channel',contact.channel));
      for(const [key,label] of [['conversationName','会话'],['senderName','发送人'],['replyToName','回复对象']]) {
        if(!contact[key] || key==='conversationName' && contact.channel==='共同记事本')continue;
        if(key==='senderName')line.append(node('span','source-separator','·'));
        if(key==='replyToName')line.append(node('span','source-separator','→'));
        const copy=node('button','source-copy',contact[key]);copy.type='button';copy.title=`复制${label}名称`;copy.setAttribute('aria-label',`复制${label}：${contact[key]}`);
        copy.addEventListener('click',()=>copySourceName(contact[key],copy));line.append(copy);
      }
      if(contact.at)line.append(node('time','source-time',`${date(contact.at)} 北京时间`));
      host.append(line);
    }
    if(!expanded && unique.length>2){const more=node('button','source-copy',`另有${unique.length-2}个来源`);more.type='button';more.addEventListener('click',()=>openDrawer(task.id));host.append(more);}
    return host;
  }
  function renderRow(task) {
    const row = node('article', `task-row${drawerId === task.id ? ' is-open' : ''}${actualState(task)==='已完成' ? ' is-complete' : actualState(task)==='不用管了' ? ' is-ended' : ''}`); row.dataset.taskId = task.id;
    const info = node('div', 'task-info');
    const title = node('button', 'task-title', task.title); title.addEventListener('click', () => openDrawer(task.id));
    info.append(title,renderSourceContacts(task),node('div', 'person-line', task.counterparty || task.people?.join('、') || '相关人待核实'));
    const badges=node('div','task-badges');if(taskKind(task)!=='action')badges.append(node('span','kind-badge',KINDS[taskKind(task)]));
    if(taskKind(task)==='action')badges.append(node('span','actual-state',actualState(task)));
    info.append(badges);
    if (task.active === false) info.append(node('span', 'source-badge', '已从当前资料归档'));
    if (task.lastKnownState) {
      const summary = node('div','current-summary',task.lastKnownState);
      summary.title = [task.lastKnownState, ...summaryProvenance(task)].join('\n'); info.append(summary);
    }
    const time = node('div', 'task-time');
    const timePrimary = node('div', 'time-primary', compactTime(task));
    timePrimary.title = task.timeRequirement || '时间待定';
    const proposed = proposedTime(task);
    time.append(timePrimary, node('div', 'time-secondary', proposed ? `提出${date(proposed, {month:'long',day:'numeric'})}` : '提出时间待核实'));
    if (!task.deadlineDate && task.timeRequirement && !/^时间待定$/.test(task.timeRequirement)) {
      const requirement=node('div','time-requirement',task.timeRequirement); requirement.title=task.timeRequirement;time.append(requirement);
    }
    const editor = makeEditor(task, false);
    const confirm = makeConfirm(task, false);
    row.append(info, time, editor, confirm);
    row.addEventListener('click', event => {
      const interactive = event.composedPath().some(element => element instanceof Element && element.matches('button,input,select,textarea,a,.action-editor,.confirm-cell'));
      if (!interactive && !window.getSelection()?.toString()) openDrawer(task.id);
    });
    return row;
  }
  function statusText(task, draft) {
    if (saving.has(task.id)) return '正在保存…';
    if (draft.conflict) return '版本已更新，请核对后确认';
    if (dirty(draft)) return '修改待确认';
    return !needsReview(task) && task.reviewedByHuman ? '已确认 · 可修改' : '待你确认';
  }
  function makeConfirm(task, inDrawer) {
    const host = node('div', inDrawer ? 'drawer-confirm-line' : 'confirm-cell');
    const status = node('span', `confirm-state${task.reviewedByHuman && !dirty(draftFor(task)) ? ' confirmed' : ''}`, statusText(task, draftFor(task))); status.dataset.statusFor = task.id;
    const button = node('button', 'primary', draftFor(task).kind==='action' ? '确认' : '确认归类'); button.dataset.confirmFor = task.id; button.disabled = saving.has(task.id) || draftFor(task).conflict;
    button.disabled = button.disabled || task.active === false;
    button.setAttribute('aria-label', `确认：${task.title}`);
    button.setAttribute('aria-keyshortcuts', 'Enter');
    button.title = 'Enter 确认';
    button.addEventListener('click', () => confirmTask(task.id));
    host.append(...(inDrawer ? [status, button] : [button, status]));
    return host;
  }
  function makeEditor(task, inDrawer) {
    const draft = draftFor(task);
    const editor = node('div', 'action-editor'); editor.dataset.editorFor = task.id; editor.dataset.context = inDrawer ? 'drawer' : 'list';
    const group = node('div', draft.kind==='action' ? 'choice-grid' : 'classification'); group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-label', `处理选项：${task.title}`);
    if(draft.kind!=='action'){
      group.removeAttribute('role');group.removeAttribute('aria-label');
      group.append(node('span','classification-label',`${task.reviewedByHuman?'当前归类':'建议归类'}：${KINDS[draft.kind]}`));
      const convert=node('button','convert-action','改为动作');convert.type='button';
      convert.addEventListener('click',()=>{const context=editor.dataset.context;draft.kind='action';persist();renderList();if(drawerId===task.id)renderDrawerEditor();const current=editorsFor(task.id).find(item=>item.dataset.context===context);current?.querySelector('.choice[aria-checked="true"]')?.focus({preventScroll:true});});
      group.append(convert);
    }
    for (const state of draft.kind==='action' ? STATES : []) {
      const button = node('button', `choice${draft.state === state ? ' selected' : ''}`);
      button.type = 'button'; button.dataset.state = state; button.setAttribute('role', 'radio'); button.setAttribute('aria-checked', String(draft.state === state)); button.tabIndex = draft.state === state ? 0 : -1;
      if (draft.state === state) { const tick = node('span', 'tick', '✓'); tick.setAttribute('aria-hidden', 'true'); button.append(tick); }
      button.append(node('span', '', state));
      button.addEventListener('click', () => {changeState(task.id, state);button.focus({preventScroll:true});});
      button.addEventListener('keydown', event => {
        if (!['ArrowRight','ArrowLeft','ArrowUp','ArrowDown','Home','End'].includes(event.key)) return;
        event.preventDefault();
        let index = STATES.indexOf(draftFor(taskById(task.id)).state);
        index = event.key === 'Home' ? 0 : event.key === 'End' ? STATES.length-1 : (index + (['ArrowLeft','ArrowUp'].includes(event.key) ? -1 : 1) + STATES.length) % STATES.length;
        changeState(task.id, STATES[index]);
        [...group.querySelectorAll('button')].find(item => item.dataset.state === STATES[index])?.focus();
      });
      group.append(button);
    }
    const ownership = makeOwnership(task);
    const reminder = node('div', 'reminder-host');
    reminder.append(makeReminder(task));
    const note = node('textarea', 'note'); note.rows = 1; note.maxLength = 4000; note.placeholder = '写备注…'; note.value = draft.note; note.setAttribute('aria-label', `备注：${task.title}`);
    note.title = 'Enter 确认，Shift+Enter 换行';
    note.addEventListener('input', () => {
      const current = draftFor(taskById(task.id)); current.note = note.value; current.error = '';
      for (const other of editorsFor(task.id)) { const input = other.querySelector('.note'); if (input !== note) input.value = note.value; }
      syncStatus(task.id); persist();
    });
    const noteLine=node('div','note-line');
    const add=node('button','add-note','添加备注'); add.type='button'; add.dataset.noteFor=task.id; add.disabled=saving.has(task.id) || draft.conflict || !draft.note.trim() || task.active===false;
    add.addEventListener('click',()=>confirmTask(task.id,true));
    noteLine.append(note,add);
    const message = node('div', 'editor-message'); message.setAttribute('aria-live', 'polite');
    editor.append(group);
    if(task.recommendation?.state || task.recommendation?.reason){const recommended=node('div','recommendation');
      const state=canonicalState(task.recommendation.state);recommended.append(node('span','',`${draft.kind==='action' && state ? `AI建议：${state}` : `AI建议归类：${KINDS[taskKind(task)]}`}${!task.reviewedByHuman?' · 待确认':''}`));
      if(inDrawer && task.recommendation.reason){const reason=node('span','recommendation-reason',task.recommendation.reason);recommended.append(reason);}editor.append(recommended);}
    editor.append(ownership, reminder, noteLine, message);
    renderMessage(task, editor);
    return editor;
  }
  function makeOwnership(task) {
    const draft=draftFor(task), line=node('div','ownership-line');
    const label=node('label','assignee-label','负责人');
    const select=node('select','assignee-select'); select.setAttribute('aria-label',`负责人：${task.title}`);
    [['我','我'],['AI','AI'],['other','其他人…']].forEach(([value,text])=>select.append(new Option(text,value)));
    select.value=['我','AI'].includes(draft.assignee)?draft.assignee:'other';
    const name=node('input','assignee-name'); name.type='text'; name.maxLength=100; name.placeholder='姓名或角色'; name.value=['我','AI'].includes(draft.assignee)?'':draft.assignee; name.hidden=select.value!=='other'; name.setAttribute('aria-label',`指定负责人：${task.title}`);
    select.addEventListener('change',()=>{
      const current=draftFor(taskById(task.id)); current.assignee=select.value==='other'?name.value:select.value; current.error='';
      syncOwnership(task.id);syncStatus(task.id);persist();if(select.value==='other')name.focus();
    });
    name.addEventListener('input',()=>{
      const current=draftFor(taskById(task.id));current.assignee=name.value;current.error='';
      for(const other of editorsFor(task.id)){const field=other.querySelector('.assignee-name');if(field!==name)field.value=name.value;}
      syncStatus(task.id);persist();
    });
    label.append(select,name);
    line.append(label);return line;
  }
  function syncOwnership(id) {
    const draft=draftFor(taskById(id));
    for(const editor of editorsFor(id)){
      const select=editor.querySelector('.assignee-select'),name=editor.querySelector('.assignee-name');
      select.value=['我','AI'].includes(draft.assignee)?draft.assignee:'other';name.hidden=select.value!=='other';name.value=name.hidden?'':draft.assignee;
    }
  }
  function editorsFor(id) { return [...document.querySelectorAll('[data-editor-for]')].filter(element => element.dataset.editorFor === id); }
  function changeState(id, state) {
    const task = taskById(id), draft = draftFor(task);
    draft.state = state; draft.error = '';
    for (const editor of editorsFor(id)) {
      for (const button of editor.querySelectorAll('.choice')) {
        const selected = button.dataset.state === state;
        button.classList.toggle('selected', selected); button.setAttribute('aria-checked', String(selected)); button.tabIndex = selected ? 0 : -1;
        clear(button);
        if (selected) { const tick = node('span', 'tick', '✓'); tick.setAttribute('aria-hidden','true'); button.append(tick); }
        button.append(node('span', '', button.dataset.state));
      }
      const reminderHost = clear(editor.querySelector('.reminder-host'));
      reminderHost.append(makeReminder(task));
      renderMessage(task, editor);
    }
    syncStatus(id); persist();
  }
  function syncStatus(id) {
    const task = taskById(id), draft = draftFor(task);
    for (const element of document.querySelectorAll('[data-status-for]')) if (element.dataset.statusFor === id) {element.textContent = statusText(task, draft); element.classList.toggle('confirmed', task.reviewedByHuman && !dirty(draft));}
    for (const element of document.querySelectorAll('[data-confirm-for]')) if (element.dataset.confirmFor === id) element.disabled = saving.has(id) || draft.conflict || task.active === false;
    for (const element of document.querySelectorAll('[data-note-for]')) if (element.dataset.noteFor === id) element.disabled = saving.has(id) || draft.conflict || !draft.note.trim() || task.active === false;
    for (const editor of editorsFor(id)) renderMessage(task, editor);
  }
  function renderMessage(task, editor) {
    const draft = draftFor(task), host = clear(editor.querySelector('.editor-message'));
    host.classList.toggle('error', Boolean(draft.error || draft.conflict));
    if (draft.conflict) {
      host.append(node('span', '', '其他页面已保存新版本。你的修改仍保留；请在详情核对最新记录。'));
      const reconcile = node('button', 'resolve-button', '已核对，保留我的修改');
      reconcile.addEventListener('click', () => {
        const latest=taskById(task.id);
        // Keep deliberately edited fields; take the current server value for untouched fields.
        const fresh=freshDraft(latest);
        if(draft.state===draft.baseState)draft.state=fresh.state;
        if(draft.kind===draft.baseKind)draft.kind=fresh.kind;
        if(draft.assignee===draft.baseAssignee)draft.assignee=latest.assignee || '我';
        if(!draft.reminderTouched){draft.reminderEnabled=Boolean(latest.reminder);draft.reminderKind=latest.reminder?.kind || null;draft.customLocal=localInput(latest.reminder?.at);}
        draft.baseState=fresh.state;draft.baseKind=fresh.kind;draft.baseAssignee=latest.assignee || '我';draft.reminderOriginal=originalReminder(latest);
        draft.revision=latest.revision;draft.conflict=false;draft.error='';draft.pending=null;
        persist();renderList();if(drawerId===task.id)renderDrawerEditor();
      });
      host.append(reconcile);
    } else if (draft.error) host.append(node('span', '', draft.error));
    else if (draft.assignee === 'AI') host.append(node('span', '', '负责人为 AI；保存分派不会自动执行。'));
  }
  function deadlineTarget(task) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(task.deadlineDate || '')) return null;
    return new Date(new Date(`${task.deadlineDate}T09:00:00+08:00`).valueOf()-86400000);
  }
  function reminderTarget(task, draft, now = Date.now()) {
    if (!draft.reminderTouched && draft.reminderOriginal) return new Date(draft.reminderOriginal.at);
    const days={day1:1,day2:2,day3:3,day7:7}[draft.reminderKind];
    if (days) return new Date(now + days*86400000);
    if (draft.reminderKind === 'deadline') return deadlineTarget(task);
    return draft.customLocal ? new Date(`${draft.customLocal}+08:00`) : null;
  }
  function makeReminder(task) {
    const draft = draftFor(task), host = node('div', 'reminder-fields');
    const label = node('label', '', '多久后提醒 · 北京时间');
    const line = node('div', 'reminder-line');
    const choices=[['day1','1天后'],['day2','2天后'],['day3','3天后'],['day7','7天后'],['deadline','截止前一天'],['custom','自定义']];
    if (draft.reminderEnabled && !choices.some(([kind])=>kind===draft.reminderKind)) draft.reminderKind = 'custom';
    const group=node('div','reminder-choices');group.setAttribute('role','group');group.setAttribute('aria-label',`提醒时间：${task.title}`);
    for(const [kind,text] of choices){
      const button=node('button',`reminder-choice${draft.reminderEnabled && kind===draft.reminderKind?' selected':''}`,text);button.type='button';button.dataset.reminderKind=kind;button.setAttribute('aria-pressed',String(draft.reminderEnabled && kind===draft.reminderKind));
      button.disabled=['已完成','不用管了'].includes(draft.state) || kind==='deadline' && !deadlineTarget(task);
      if(kind==='deadline')button.title='截止前一天09:00';
      button.addEventListener('click',()=>{const editor=button.closest('[data-editor-for]');const current=draftFor(taskById(task.id));current.reminderEnabled=!current.reminderEnabled || current.reminderKind!==kind;current.reminderKind=current.reminderEnabled?kind:null;current.reminderTouched=true;current.error='';syncReminders(task.id);persist();editor?.querySelector(`[data-reminder-kind="${kind}"]`)?.focus({preventScroll:true});});group.append(button);
    }
    const input = node('input'); input.type = 'datetime-local'; input.value = draft.customLocal; input.hidden = !draft.reminderEnabled || draft.reminderKind !== 'custom'; input.setAttribute('aria-label', `自定义提醒日期与时间：${task.title}`);
    const target = node('div', 'reminder-target');
    function displayTarget() {
      const current = draftFor(taskById(task.id));
      if(!current.reminderEnabled){target.textContent='';return;}
      const at = reminderTarget(taskById(task.id), current), timeZone=zone;
      target.textContent = at && !Number.isNaN(at.valueOf()) ? `提醒于 ${date(at, {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,timeZone})} · 北京时间${!current.reminderTouched && current.reminderOriginal ? '（保留已保存时间）' : ['day1','day2','day3','day7'].includes(current.reminderKind) ? '（以确认时刻计算）' : ''}` : `请选择明确的提醒时间 · 北京时间`;
      if (!deadlineTarget(taskById(task.id))) target.append(node('span', '', '。截止日期尚不明确，可选自定义时间。'));
    }
    input.addEventListener('input', () => {const current = draftFor(taskById(task.id)); current.customLocal = input.value; current.reminderTouched = true; current.error = ''; displayTarget(); for (const other of editorsFor(task.id)) {const field = other.querySelector('input[type="datetime-local"]'); if (field && field !== input) {field.value = input.value; other.querySelector('.reminder-target').textContent = target.textContent;}} syncStatus(task.id); persist();});
    line.append(group,input); host.append(label,line,target); displayTarget(); return host;
  }
  function syncReminders(id) {
    for (const editor of editorsFor(id)) { const focus=controlFocus(editor);const host = clear(editor.querySelector('.reminder-host')); host.append(makeReminder(taskById(id)));restoreControlFocus(editor.parentElement,focus); }
    syncStatus(id);
  }
  function requestId() { return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
  async function confirmTask(id, noteOnly=false) {
    if (saving.has(id)) return;
    const task=taskById(id), draft=draftFor(task);
    if (draft.conflict || (noteOnly && !draft.note.trim())) return;
    const reviewIndex=!noteOnly && $('view').value==='待我确认' ? filteredTasks().findIndex(item=>item.id===id) : -1;
    const payload={expectedRevision:draft.revision};
    if (draft.note.trim()) payload.note=draft.note;
    if (!noteOnly) {
      if(draft.kind==='action')payload.state=draft.state;
      if(draft.kind!=='action' || draft.kind!==taskKind(task))payload.kind=draft.kind;
      if (draft.assignee !== draft.baseAssignee) {
        if (!draft.assignee.trim()) {draft.error='请填写负责人姓名或角色。';syncStatus(id);return;}
        payload.assignee=draft.assignee.trim();
      }
      if (draft.reminderTouched) {
        payload.reminder=null;
        if (draft.reminderEnabled && !['已完成','不用管了'].includes(draft.state)) {
          const at=reminderTarget(task,draft);
          if (!at || Number.isNaN(at.valueOf()) || at.valueOf()<=Date.now()) {draft.error='请选择未来的明确提醒日期和时间。';syncStatus(id);return;}
          payload.reminder={kind:draft.reminderKind,at:at.toISOString(),timezone:zone};
        }
      }
    }
    const signature=JSON.stringify(payload);
    if (draft.pending?.signature!==signature) draft.pending={signature,requestId:requestId()};
    payload.requestId=draft.pending.requestId;
    const snapshot={state:draft.state,kind:draft.kind,assignee:draft.assignee,note:draft.note,reminder:JSON.stringify([draft.reminderEnabled,draft.reminderKind,draft.customLocal,draft.reminderTouched])};
    saving.add(id);draft.error='';persist();syncStatus(id);
    try {
      const result=await api(`/api/tasks/${encodeURIComponent(id)}/record`,payload);
      const known=taskById(id), resultTask=known?.revision > result.task.revision ? known : result.task;
      tasks[tasks.findIndex(item=>item.id===id)]=resultTask;
      // Only clear fields that this request actually saved; preserve concurrent typing and other drafts.
      if ('note' in payload && draft.note===snapshot.note) draft.note='';
      const fresh=freshDraft(resultTask);
      if (draft.state===snapshot.state && ('state' in payload || draft.state===draft.baseState)) draft.state=fresh.state;
      if(draft.kind===snapshot.kind && ('kind' in payload || draft.kind===draft.baseKind))draft.kind=fresh.kind;
      if (draft.assignee===snapshot.assignee && ('assignee' in payload || draft.assignee===draft.baseAssignee)) draft.assignee=resultTask.assignee;
      if (('reminder' in payload || !draft.reminderTouched) && snapshot.reminder===JSON.stringify([draft.reminderEnabled,draft.reminderKind,draft.customLocal,draft.reminderTouched])) {
        draft.reminderTouched=false;draft.reminderEnabled=Boolean(resultTask.reminder);
      }
      draft.revision=resultTask.revision;draft.baseState=fresh.state;draft.baseKind=fresh.kind;draft.baseAssignee=resultTask.assignee || '我';draft.reminderOriginal=originalReminder(resultTask);draft.pending=null;
      const active=document.activeElement;
      const activeId=active.closest('[data-editor-for]')?.dataset.editorFor || active.dataset.confirmFor;
      const advance=reviewIndex>=0 && resultTask.reviewedByHuman && !dirty(draft) &&
        (active===document.body || activeId===id);
      persist();renderList();
      if (drawerId===id) {
        if(!noteOnly && $('view').value==='待我确认' && resultTask.reviewedByHuman && !dirty(draft))closeDrawer();
        else {renderDrawerEditor();await loadDetail(id);}
      }
      if(advance){const remaining=filteredTasks();focusReviewItem(remaining[Math.min(reviewIndex,remaining.length-1)]?.id);}
      toast(noteOnly?'备注已添加。':'已确认并保存。');
    } catch(error) {
      draft.error=error.message;
      if(error.status===409){
        draft.conflict=true;draft.pending=null;
        try{const latest=await api(`/api/tasks/${encodeURIComponent(id)}`);if(updateTask(latest.task) && drawerId===id){drawerDetail=latest;renderDrawerContent(latest);}}catch(_){/* Preserve all unsaved fields. */}
      }
      persist();
    } finally {saving.delete(id);syncStatus(id);}
  }
  async function openDrawer(id) {
    const task = taskById(id); if (!task) return;
    if (!drawerId) returnFocus = document.activeElement;
    drawerId = id; drawerDetail = null;
    $('drawer').hidden = false; $('drawer-scrim').hidden = false;
    $('main').inert = true; document.querySelector('.topbar').inert = true; document.body.style.overflow = 'hidden';
    renderDrawerContent(null); renderDrawerEditor();
    for (const row of document.querySelectorAll('.task-row')) row.classList.toggle('is-open', row.dataset.taskId === id);
    ($('drawer-controls').querySelector('.choice[aria-checked="true"]') || $('drawer-controls').querySelector('[data-confirm-for]'))?.focus({preventScroll:true});
    await loadDetail(id);
  }
  async function loadDetail(id) {
    try {
      const detail = await api(`/api/tasks/${encodeURIComponent(id)}`);
      if (!updateTask(detail.task)) return;
      if (drawerId !== id) return;
      drawerDetail = detail; renderDrawerContent(detail); renderDrawerEditor();
    } catch (error) { if (drawerId === id) {const host = $('drawer-content'); host.append(node('p','page-error',`原文依据暂未读取：${error.message}`));} }
  }
  function closeDrawer() {
    drawerId = null; drawerDetail = null; $('drawer').hidden = true; $('drawer-scrim').hidden = true;
    $('main').inert = false; document.querySelector('.topbar').inert = false; document.body.style.overflow = '';
    renderList();
    if (returnFocus?.isConnected) returnFocus.focus(); else document.querySelector('.task-title')?.focus();
  }
  function detailSection(title) { const section = node('section','detail-section'); section.append(node('h4','',title)); return section; }
  function historyValue(field, value) {
    if(value===null || value===undefined || value==='')return '未设置';
    if(field==='relatedRecordIds')return value.length ? value.map(id=>taskById(id)?.title || id).join('、') : '无';
    if(field==='reminder')return `${date(value.at)} · 北京时间`;
    return String(value);
  }
  function renderChangedFields(entry) {
    const fields=[['title','事项名称'],['counterparty','对谁'],['timeRequirement','交付时间'],['summary','当前进展'],['relatedRecordIds','关联事项']].filter(([field])=>Object.hasOwn(entry,field));
    if(!fields.length)return null;
    const details=node('details','timeline-changes');
    details.append(node('summary','',`查看修改：${fields.map(([,label])=>label).join('、')}`));
    const values=node('dl');
    for(const [field,label] of fields){
      const item=node('div');item.append(node('dt','',label));
      if(entry.previous && Object.hasOwn(entry.previous,field))item.append(node('dd','change-before',`修改前：${historyValue(field,entry.previous[field])}`));
      item.append(node('dd','change-after',`保存为：${historyValue(field,entry[field])}`));values.append(item);
    }
    details.append(values);return details;
  }
  function renderTimeline(detail, task) {
    const section = detailSection('进展记录');
    if (!detail) { section.append(node('p','quiet','正在读取进展记录…')); return section; }
    const entries = detail.timeline || (detail.history || []).map(entry => ({...entry, body:entry.note}));
    if (!entries.length) section.append(node('p','editor-message','暂无进展记录。确认决定和 AI 核查记录会保留在这里。'));
    for (const entry of entries) {
      const author=entry.actor?.name || entry.author || '记录人待核实';
      const ai = entry.actor?.kind === 'ai' || author === 'AI';
      const item = node('article', `timeline-item${ai ? ' timeline-ai' : ' timeline-human'}`);
      const avatar=node('span','timeline-avatar',ai?'AI':author.slice(0,1));avatar.setAttribute('aria-hidden','true');item.append(avatar);
      const header = node('div','timeline-header');
      header.append(node('span','timeline-author',author), node('time','',`记录时间：${date(entry.at)}`));
      item.append(header);
      if (entry.sourceTime) item.append(node('p','timeline-source-time',`来源时间：${date(entry.sourceTime)}`));
      if (entry.state) item.append(node('p','timeline-state',`${ai ? '已处理' : '已确认'}：${entry.state}`));
      if (entry.body || entry.note) item.append(node('p','timeline-body',entry.body || entry.note));
      if (entry.assignee) item.append(node('p','editor-message',`负责人：${entry.previous && Object.hasOwn(entry.previous,'assignee') ? `${historyValue('assignee',entry.previous.assignee)} → ` : ''}${entry.assignee}`));
      if (entry.reminder === null && Object.hasOwn(entry,'reminder')) item.append(node('p','editor-message',`提醒已取消${entry.previous?.reminder ? `（原提醒：${historyValue('reminder',entry.previous.reminder)}）` : ''}`));
      if (entry.reminder) item.append(node('p','editor-message',`提醒：${entry.previous && Object.hasOwn(entry.previous,'reminder') ? `${historyValue('reminder',entry.previous.reminder)} → ` : ''}${historyValue('reminder',entry.reminder)}`));
      const changedFields=renderChangedFields(entry);if(changedFields)item.append(changedFields);
      if (ai && entry.suggestedState) item.append(node('p','editor-message',`当时 AI 建议：${entry.suggestedState}。`));
      if (entry.sources?.length) {
        const sources = node('details','timeline-sources');
        sources.append(node('summary','source-link',`查看依据（${entry.sources.length}）`));
        for (const source of entry.sources) {
          const sourceHost = node('div','timeline-source');
          const prefix = `/api/tasks/${encodeURIComponent(task.id)}/sources/`;
          if (typeof source.url === 'string' && source.url.startsWith(prefix) && /^\d+$/.test(source.url.slice(prefix.length))) {
            const link = node('a','source-link',source.label || '查看来源');
            link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; sourceHost.append(link);
          } else sourceHost.append(node('div','timeline-source-label',source.label || '来源记录'));
          if (source.quote) sourceHost.append(node('blockquote','quote',source.quote));
          sources.append(sourceHost);
        }
        item.append(sources);
      }
      section.append(item);
    }
    return section;
  }
  function renderDrawerContent(detail) {
    const task = taskById(drawerId); if (!task) return;
    const host = clear($('drawer-content'));
    const heading = node('div','detail-heading'); heading.append(node('h3','',task.title),node('span','state-badge',taskKind(task)==='action' ? actualState(task) : KINDS[taskKind(task)])); host.append(heading,renderSourceContacts(task,true));
    const metadata = node('dl','detail-meta');
    const proposed = proposedTime(task);
    [['性质',KINDS[taskKind(task)]],['完成标志',task.completionCriterion || '待核实'],['负责人',task.assignee || '我'],['对谁',task.counterparty || task.people?.join('、') || '待核实'],['提出时间',proposed ? date(proposed,{year:'numeric',month:'long',day:'numeric'}) : '待核实'],['交付时间',task.timeRequirement || '时间待定'],['最近处理',task.stateUpdatedAt ? `${task.stateUpdatedBy || '记录人待核实'} · ${date(task.stateUpdatedAt)}` : '待处理']].forEach(([label,value]) => {const item=node('div',label==='最近处理'?'recent-handling':''); item.append(node('dt','',label),node('dd','',value)); metadata.append(item);});
    host.append(metadata);
    const progress=detailSection('当前进展'); progress.classList.add('current-progress');
    progress.append(node('p','detail-body',task.lastKnownState || '暂无经核实的最新进展。'));
    const provenance=summaryProvenance(task);if(provenance.length)progress.append(node('p','summary-provenance',provenance.join(' · ')));
    host.append(progress);
    if (detail?.relatedTasks?.length) {
      const related=detailSection('关联事项');
      for (const item of detail.relatedTasks) {
        if (!taskById(item.id)) continue;
        const link=node('button','related-task');
        link.append(node('span','',item.title),node('span','quiet',taskKind(item)==='action' ? actualState(item) : KINDS[taskKind(item)]));
        link.addEventListener('click',()=>openDrawer(item.id));related.append(link);
      }
      host.append(related);
    }
    host.append(renderTimeline(detail, task));
    const evidence = detailSection('原文依据');
    if (!detail) evidence.append(node('p','quiet','正在读取原文依据…'));
    else {
      if (detail.sourceLinks?.length) {
        const disclosure = node('details', 'source-disclosure');
        disclosure.append(node('summary', 'source-link', `查看来源（${detail.sourceLinks.length}）`));
        const links = node('div','source-links');
        detail.sourceLinks.forEach((source,index) => {const link=node('a','source-link',source.label || `查看来源 ${index+1}`); link.href=`/api/tasks/${encodeURIComponent(task.id)}/sources/${index}`; link.target='_blank'; link.rel='noopener noreferrer'; links.append(link);}); disclosure.append(links); evidence.append(disclosure);
      }
      const quotes=[],seenQuotes=new Set();
      const addEvidence=quote=>{if(!quote.text)return;const key=JSON.stringify([quote.sender || '来源记录',quote.text]);if(!seenQuotes.has(key)){seenQuotes.add(key);quotes.push(quote);}};
      for(const entry of detail.timeline || [])for(const source of entry.sources || [])if(source.quote)addEvidence({sender:source.label || entry.author || '来源记录',text:source.quote});
      for(const quote of detail.evidence || [])addEvidence(quote);
      if (!quotes.length) evidence.append(node('p','detail-body','暂无可读取的原文依据，请结合来源记录核对。'));
      const appendQuote = (host, quote) => host.append(node('div','evidence-header',quote.sender || '来源记录'),node('blockquote','quote',quote.text || ''));
      for (const quote of quotes.slice(0,5)) appendQuote(evidence,quote);
      if (quotes.length > 5) {
        const remaining = node('div'); remaining.hidden = true;
        const toggle = node('button','evidence-toggle',`展开其余依据（${quotes.length-5}）`);
        let expandedOnce = false;
        toggle.addEventListener('click', () => {
          if (!expandedOnce) {for (const quote of quotes.slice(5)) appendQuote(remaining,quote); expandedOnce = true;}
          remaining.hidden = !remaining.hidden;
          toggle.textContent = remaining.hidden ? `展开其余依据（${quotes.length-5}）` : '收起其余依据';
          toggle.setAttribute('aria-expanded',String(!remaining.hidden));
        });
        toggle.setAttribute('aria-expanded','false'); evidence.append(remaining,toggle);
      }
    }
    host.append(evidence);
  }
  function renderDrawerEditor() {
    const task=taskById(drawerId); if(!task) return;
    const focus=controlFocus($('drawer-controls'));
    const host=clear($('drawer-controls')); host.append(makeEditor(task,true),makeConfirm(task,true));
    restoreControlFocus(host,focus);
  }
  function renderCoverage(notificationMode) {
    const host=clear($('coverage-body'));
    const append=(label,value) => {if(value!==undefined && value!==null && value!=='') host.append(node('p','',`${label}：${typeof value === 'string' || typeof value === 'number' ? value : JSON.stringify(value)}`));};
    append('资料截至',meta.asOf);
    if (meta.scope && typeof meta.scope === 'object') {
      const end = String(meta.scope.through || '').match(/\d{4}-\d{2}-\d{2}/)?.[0] || '待核实';
      append('本批资料范围',`${meta.scope.from || '待核实'} 至 ${end}（仍有未读来源）`);
    }
    append('整理目的',meta.purpose); append('本批记录',meta.count ?? tasks.length); append('列表载入时间',meta.importedAt ? date(meta.importedAt) : null);
    if (meta.coverageText) {
      const report = node('details','coverage-report');
      report.append(node('summary','','展开完整阅读覆盖与缺口'),node('pre','',meta.coverageText));
      host.append(report);
    }
    host.append(node('p','','刷新列表会重新读取这批整理资料，并保留你的确认记录；它不会重新扫描微信、邮件或会议。'));
    host.append(node('p','','提醒方式：应用内提醒。页面打开时每 30 秒检查一次；关闭页面后不保证提醒。到时提醒只提示，不会改变事项状态。'));
    host.append(node('p','','负责人、状态和提醒分别保存；分派不触发自动执行。备注可单独添加，也可随确认一起保存；未保存草稿保留在本浏览器。'));
    if ('Notification' in window && window.isSecureContext) {
      const button=node('button','notification-button',Notification.permission==='granted' ? '浏览器通知已允许（页面打开时）' : Notification.permission==='denied' ? '浏览器通知已被关闭，可在浏览器设置中调整' : '允许页面打开时的浏览器通知');
      button.disabled=Notification.permission!=='default';
      button.addEventListener('click',async()=>{try{await Notification.requestPermission();renderCoverage(notificationMode);}catch(_){toast('暂时无法启用浏览器通知，应用内提醒仍可使用。');}});host.append(button);
    }
  }
  function toast(message, action, persistent=false) {
    const item=node('div','toast');item.append(node('span','',message));
    if(action){const button=node('button','',action.label);button.addEventListener('click',()=>{action.run();item.remove();});item.append(button);}
    if(persistent){const close=node('button','','关闭');close.addEventListener('click',()=>item.remove());item.append(close);}
    $('toasts').append(item);if(!persistent)setTimeout(()=>item.remove(),5000);
  }
  async function pollReminders() {
    if(pollRunning || !csrfToken)return;pollRunning=true;
    try {
      const result=await api('/api/reminders');
      for(const task of result.tasks || []) {
        if (!updateTask(task)) continue;
        const key=`${task.id}:${task.reminder?.at}`;
        if(notified.has(key))continue;
        notified.add(key);
        toast(`提醒时间到了：${task.title}`,{label:'查看',run:()=>{$('view').value='到时提醒';page=1;renderList();openDrawer(task.id);}},true);
        if('Notification' in window && Notification.permission==='granted') {try{const notification=new Notification('事项提醒',{body:task.title,tag:key});notification.onclick=()=>{window.focus();openDrawer(task.id);notification.close();};}catch(_){/* In-app toast remains visible. */}}
        try {
          const ack=await api(`/api/tasks/${encodeURIComponent(task.id)}/reminder-ack`,{});
          if(ack.task) {
            if (taskById(task.id)?.revision > ack.task.revision) continue;
            const draft=drafts.get(task.id);
            const sameDecision=ack.task.selectedState===task.selectedState && ack.task.assignee===task.assignee && ack.task.note===task.note && JSON.stringify(originalReminder(ack.task))===JSON.stringify(originalReminder(task));
            if(draft && !draft.conflict && draft.revision===task.revision && sameDecision) draft.revision=ack.task.revision;
            updateTask(ack.task);
          }
        }catch(_){notified.delete(key);}
      }
      if($('view').value==='到时提醒' || ($('view').value==='待我确认' && filteredTasks().map(task=>task.id).join(',')!==renderedTaskIds))renderList();
    } catch (_) { /* A transient poll failure does not interrupt editing. */ }
    finally{pollRunning=false;}
  }
  function createSnapshot() {
    const fields={};
    for(const id of ['create-title','create-counterparty','create-time','create-state','create-assignee','create-assignee-name','create-note'])fields[id]=$(id).value;
    fields.relatedRecordIds=[...$('create-related').selectedOptions].map(option=>option.value);return fields;
  }
  function persistCreateDraft() {
    const fields=createSnapshot();
    const hasContent=fields['create-title'] || fields['create-counterparty'] || fields['create-time'] || fields['create-note'] || fields['create-assignee-name'] || canonicalState(fields['create-state'])!=='待办' || fields['create-assignee']!=='我' || fields.relatedRecordIds.length;
    try{if(hasContent)localStorage.setItem(CREATE_STORAGE_KEY,JSON.stringify({fields,open:!$('create-panel').hidden,pending:createPending}));else localStorage.removeItem(CREATE_STORAGE_KEY);}catch(_){/* Keep the in-page draft when browser storage is unavailable. */}
  }
  function restoreCreateDraft() {
    try{
      const saved=JSON.parse(localStorage.getItem(CREATE_STORAGE_KEY)||'null');
      if(!saved || typeof saved.fields!=='object' || !saved.fields)return;
      const fields=saved.fields;
      if(typeof saved.pending?.signature==='string' && typeof saved.pending?.requestId==='string' && saved.pending.requestId.length<=120)createPending={signature:saved.pending.signature,requestId:saved.pending.requestId};
      for(const id of ['create-title','create-counterparty','create-time','create-assignee-name','create-note'])if(typeof fields[id]==='string')$(id).value=fields[id].slice(0,$(id).maxLength);
      if(STATES.includes(canonicalState(fields['create-state'])))$('create-state').value=canonicalState(fields['create-state']);
      if(['我','AI','other'].includes(fields['create-assignee']))$('create-assignee').value=fields['create-assignee'];
      restoredCreateRelations=Array.isArray(fields.relatedRecordIds)?fields.relatedRecordIds.filter(value=>typeof value==='string'):[];
      $('create-assignee-name').hidden=$('create-assignee').value!=='other';
      $('create-panel').hidden=saved.open!==true;$('create-toggle').setAttribute('aria-expanded',String(!$('create-panel').hidden));
    }catch(_){/* A malformed optional draft must not block the notebook. */}
  }
  function renderCreateRelated() {
    const select=$('create-related'),selected=restoredCreateRelations || [...select.selectedOptions].map(option=>option.value);restoredCreateRelations=null;clear(select);
    for(const task of tasks.filter(item=>item.active!==false)) {const option=new Option(`${task.id} · ${task.title}`,task.id);option.selected=selected.includes(task.id);select.append(option);}
  }
  $('create-toggle').addEventListener('click',()=>{
    const panel=$('create-panel');panel.hidden=!panel.hidden;$('create-toggle').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)$('create-title').focus();persistCreateDraft();
  });
  $('create-cancel').addEventListener('click',()=>{
    // Closing is reversible: leave this form's in-page draft intact.
    $('create-panel').hidden=true;$('create-toggle').setAttribute('aria-expanded','false');$('create-toggle').focus();persistCreateDraft();
  });
  $('create-assignee').addEventListener('change',()=>{const input=$('create-assignee-name');input.hidden=$('create-assignee').value!=='other';if(!input.hidden)input.focus();});
  restoreCreateDraft();
  $('create-form').addEventListener('input',persistCreateDraft);
  $('create-form').addEventListener('change',persistCreateDraft);
  $('create-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('create-submit');if(button.disabled)return;
    const title=$('create-title').value.trim(),assignee=$('create-assignee').value==='other'?$('create-assignee-name').value.trim():$('create-assignee').value;
    if(!title || !assignee){$('create-error').textContent='请填写事项名称和负责人。';return;}
    const payload={title,counterparty:$('create-counterparty').value.trim() || '自己',timeRequirement:$('create-time').value.trim() || '时间待定',state:$('create-state').value,assignee,relatedRecordIds:[...$('create-related').selectedOptions].map(option=>option.value)};
    if($('create-note').value.trim())payload.note=$('create-note').value;
    const signature=JSON.stringify(payload);if(createPending?.signature!==signature)createPending={signature,requestId:requestId()};payload.requestId=createPending.requestId;
    const submitted=createSnapshot(),submittedFingerprint=JSON.stringify(submitted);
    button.disabled=true;$('create-error').textContent='';persistCreateDraft();
    try{const result=await api('/api/tasks',payload);updateTask(result.task);drafts.set(result.task.id,freshDraft(result.task));createPending=null;
      const hasLaterInput=JSON.stringify(createSnapshot())!==submittedFingerprint;
      if(!hasLaterInput){$('create-form').reset();$('create-assignee-name').hidden=true;$('create-panel').hidden=true;$('create-toggle').setAttribute('aria-expanded','false');}
      else{
        // The submitted title already belongs to the saved item. Preserve later typing
        // as another draft without allowing an accidental second copy of that item.
        if($('create-title').value===submitted['create-title'])$('create-title').value='';
        $('create-panel').hidden=false;$('create-toggle').setAttribute('aria-expanded','true');
        $('create-error').textContent=`已新增「${title}」。后续输入已保留为新增草稿${$('create-title').value?'。':'，请填写新事项名称后保存。'}`;
      }
      persistCreateDraft();renderCreateRelated();$('view').value='全部';$('search').value='';$('person').value='';const position=filteredTasks().findIndex(task=>task.id===result.task.id);page=Math.floor(position/PAGE_SIZE)+1;renderList();toast(hasLaterInput?'事项已新增，后续输入已保留为草稿。':'事项已新增。');document.querySelector(`[data-task-id="${CSS.escape(result.task.id)}"]`)?.scrollIntoView({block:'center'});}
    catch(error){$('create-error').textContent=error.message;}finally{button.disabled=false;}
  });
  // Adding a person, selecting a relation or editing a date never implicitly creates a task.
  $('create-form').addEventListener('keydown',event=>{if(event.key==='Enter' && event.target.tagName!=='BUTTON')event.stopPropagation();if(event.key==='Enter' && event.target.tagName==='INPUT')event.preventDefault();});
  $('search').addEventListener('input',()=>{page=1;renderList();});
  $('owner').addEventListener('change',()=>{page=1;renderList();});
  $('person').addEventListener('change',()=>{page=1;renderList();});
  $('view').addEventListener('change',()=>{page=1;renderList();});
  $('drawer-close').addEventListener('click',closeDrawer);
  $('drawer-scrim').addEventListener('click',closeDrawer);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return;
    if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    const editor = target.closest('.action-editor');
    const confirm = target.closest('[data-confirm-for]');
    if (!editor && !confirm) return;
    if (target.closest('select,input,a,[contenteditable="true"]')) return;
    const button = target.closest('button');
    if (button && !button.matches('.choice,.reminder-choice,[data-confirm-for]')) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.repeat) return;
    const id = editor?.dataset.editorFor || confirm?.dataset.confirmFor;
    const task = taskById(id);
    if (!task || task.active === false) return;
    confirmTask(id);
  });
  document.addEventListener('keydown',event=>{
    if(!drawerId)return;
    if(event.key==='Escape'){event.preventDefault();closeDrawer();return;}
    if(event.key==='Tab'){
      const focusable=[...$('drawer').querySelectorAll('button:not(:disabled),a[href],input:not([hidden]),select,textarea,[tabindex="0"]')].filter(element=>element.getClientRects().length);
      const first=focusable[0],last=focusable[focusable.length-1];
      if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  $('refresh').addEventListener('click',async()=>{
    const button=$('refresh');button.disabled=true;$('page-error').hidden=true;
    try{const result=await api('/api/refresh',{});applyBootstrap(result);if(drawerId)await loadDetail(drawerId);toast(result.changes ? `列表已刷新：新增 ${result.changes.added || 0} 项，来源更新 ${result.changes.changed || 0} 项。` : '列表已刷新。');}
    catch(error){$('page-error').textContent=error.message;$('page-error').hidden=false;}
    finally{button.disabled=false;}
  });
  window.addEventListener('beforeunload',persist);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollReminders();});
  api('/api/bootstrap').then(data=>{applyBootstrap(data);if(document.activeElement===document.body)focusReviewItem();pollReminders();setInterval(pollReminders,30000);}).catch(error=>{$('page-error').textContent=`列表未能载入：${error.message}`;$('page-error').hidden=false;clear($('tasks')).append(node('p','empty','请确认本地服务正常运行，然后重新打开页面。'));});
})();
