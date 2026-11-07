import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

// Vite transforms TSX for Node without adding a test framework or DOM emulator.
const server = await createServer({server: {middlewareMode: true}, appType: 'custom', optimizeDeps: {noDiscovery: true, entries: [], include: []}});
const ui = await server.ssrLoadModule('/src/design-system/ui.tsx');
const render = (component, props) => renderToStaticMarkup(createElement(component, props));

test.after(async () => {await server.close();});
test('buttons are safe inside a form unless submission is explicitly requested', () => {
  assert.match(render(ui.Button, {children: 'Preview'}), /type="button"/);
  assert.match(render(ui.Button, {type: 'submit', children: 'Save'}), /type="submit"/);
});
test('fields connect their visible label, hint and error to the actual control', () => {
  const markup = render(ui.Field, {id: 'title', label: '标题', hint: '简短标题', error: '必填', required: true});
  assert.match(markup, /for="title"/);
  assert.match(markup, /aria-describedby="title-hint title-error"/);
  assert.match(markup, /aria-invalid="true"/);
});
test('shell uses caller navigation and account rather than fixed product entries', () => {
  const markup = render(ui.SiteShell, {brand: {label: 'Demo', href: '/'}, navigation: [{id: 'only', label: 'Only supplied link', href: '/only', current: true}], account: {label: 'Demo account', href: '/account'}, children: 'Main content'});
  assert.equal((markup.match(/Only supplied link/g) ?? []).length, 2);
  assert.match(markup, /aria-label="Demo account"/);
  assert.match(markup, /<main id="main" tabindex="-1">/);
  assert.doesNotMatch(markup, /统一认证|个人中心|项目共创/);
});
test('missing images render a readable fallback with no broken image element', () => {
  const markup = render(ui.ContentCard, {title: 'Fallback title', href: '/example'});
  assert.match(markup, /media-missing/);
  assert.match(markup, /sample-cover-title">Fallback title/);
  assert.doesNotMatch(markup, /<img/);
});
test('resource links get resource-specific accessible labels and safe external relation', () => {
  const markup = render(ui.ResourceList, {resources: [{id: 'one', title: 'Example PDF', href: 'https://example.com/file.pdf', external: true}]});
  assert.match(markup, /aria-label="查看：Example PDF"/);
  assert.match(markup, /rel="noopener noreferrer"/);
});
test('cancelled acknowledgement and delivered reviewed draft are distinct components',async()=>{
 const d=await server.ssrLoadModule('/src/work/DeliveryHealth.tsx');
 const old={id:'old',businessId:'b',businessTitle:'期刊合作邀请',employee:'secretary',status:'not_required',reasonCode:'ack_cancelled_by_ready_draft',nativeReceiptVerified:false,evidenceRefs:['s']};
 assert.equal(d.deliveryLabel(old),'旧承接已取消／不再发送');
 const html=render(d.DeliveryPanel,{health:{incidents:[old,{...old,id:'new',status:'resolved',reasonCode:'native_accepted',nativeReceiptVerified:true}],coverage:{gaps:[]}},people:[],sending:[],businessId:'b',onSource:()=>{}});
 assert.match(html,/旧承接稿/);assert.match(html,/成熟稿/);assert.match(html,/旧稿未发/);assert.doesNotMatch(html,/六项原合作/);
});
test('read-only coverage distinguishes a stale note and missing structured workbook from zero work',async()=>{
 const {WorkPage}=await server.ssrLoadModule('/src/work/WorkPage.tsx');
 const person={id:'worker',name:'员工',threadId:'thread',category:'support',channels:[],observedAt:'now',error:null,workRead:{state:'native_only',indexedNotes:0,items:0,staleItems:0,gaps:[]}};
 const work={version:1,readOnly:true,employees:[person],items:[],sending:{items:[],error:null},modes:{dimensions:[]},discovery:{source:'normal',bindings:0,unadaptedThreads:0,consistency:{checkedEmployees:1,verifiedIdentities:1,employeesWithGaps:1,employees:[{employee:'worker',gaps:['0项不代表无工作']}]}}};
 const html=render(WorkPage,{snapshot:{workOverview:work},onSource:()=>{},mode:'work',onMode:()=>{},onPerson:()=>{}});assert.match(html,/统一核对/);assert.match(html,/读取缺口/);
});
test('specific author acceptance is visibly non-exact and retains ordinary labels',async()=>{
 const d=await server.ssrLoadModule('/src/work/DeliveryHealth.tsx');
 const item={id:'explicit',businessId:'b',businessTitle:'本日晨报',employee:'secretary',status:'resolved',reasonCode:'native_author_accepted_difference',nativeReceiptVerified:true,evidenceRefs:['s']};
 assert.equal(d.deliveryLabel(item),'已送达（作者接受明确差异）');
 assert.equal(d.deliveryLabel({...item,reasonCode:'native_accepted'}),'已送达（原生已核）');
 const html=render(d.DeliveryPanel,{health:{incidents:[item],coverage:{gaps:[]}},people:[],sending:[],businessId:'b',onSource:()=>{}});
 assert.match(html,/非逐字相同/);assert.match(html,/SHA/);assert.doesNotMatch(html,/全文一致|逐字一致/);
});
