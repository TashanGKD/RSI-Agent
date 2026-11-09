"""Exact-source article forwarding through the original official UI and queue."""
import hashlib,json,time,os,re,stat
from pathlib import Path
from .runtime import BeforeEffect

def preflight(d,j):
 from .recipes import source_label,PreparationError
 source=d._native_source(j)
 if source.get('historyLocator'):
  from .proof import xml
  card=xml(source['text'])
  if source['kind']!=49 or card.findtext('.//appmsg/type')!='5':raise PreparationError('SOURCE_NOT_LOCATABLE','History locator is only for exact article cards.')
 else:source_label(source)
 return source

def history_candidate(rows,source,box):
 """Title + source sender + native date; no similar-title or first-row fallback."""
 from .ocr import normalized
 loc=source['historyLocator'];title=normalized(loc['title']);sender=normalized(loc['senderName'])
 if not title or not sender or not loc['dateLabels']:raise ValueError('complete native source witness required')
 labels={normalized(x) for x in loc['dateLabels']};matches=[]
 for r in rows:
  if normalized(r['text']) not in labels:continue
  y=r['point'][1]
  # The link row has title above its author/date footer. Adjacent cards have
  # separate footers; constrain the exact card to the nearest preceding one.
  previous=max((v['point'][1] for v in rows if v['point'][1]<y-8 and normalized(v['text']) in labels),default=box[1])
  band=[v for v in rows if max(previous+8,y-40)<=v['point'][1]<=y+32 and v['point'][0]<box[2]-70]
  ordered=sorted(band,key=lambda v:(v['point'][1],v['point'][0]))
  text=''.join(normalized(v['text']) for v in ordered)
  prefix=loc.get('titlePrefix')
  if prefix:
   if loc.get('sameDatePrefixCount')!=1 or len(prefix)<16 or not title.startswith(prefix):raise ValueError('native date/prefix uniqueness is not proven')
   if not any(normalized(v['text']).startswith(prefix) and y-30<=v['point'][1]<y-2 for v in ordered):continue
  elif title not in text or sender not in text:continue
  title_rows=[v for v in ordered if normalized(v['text']) and normalized(v['text'])[:8] in title and v['point'][1]<y-8]
  if not title_rows:continue
  matches.append(title_rows[0]['point'])
 if len(matches)!=1:raise ValueError('exact title/sender/date source row absent or ambiguous')
 return matches[0]

def date_labels(created,now=None):
 from datetime import datetime
 from zoneinfo import ZoneInfo
 stamp=datetime.fromtimestamp(created,ZoneInfo('Asia/Shanghai'));day=stamp.date();today=datetime.fromtimestamp(time.time() if now is None else now,ZoneInfo('Asia/Shanghai')).date()
 age=(today-day).days
 result=[day.strftime('%Y/%m/%d'),day.strftime('%Y-%m-%d'),f'{day.year}/{day.month}/{day.day}',f'{day.month}/{day.day}']
 if age==0:result.extend(['Today',stamp.strftime('%H:%M')])
 elif age==1:result.append('Yesterday')
 elif 1<age<7:result.append(day.strftime('%A'))
 return result

def history_bounds(w):
 return [w['x']+20,w['y']+166,w['x']+w['width']-20,w['y']+w['height']-20]

def canonical_empty_search(image,v):
 """Positive full-field empty baseline, not an OCR/masking tolerance.
 A focused/unfocused placeholder appearance may differ from the old pixel
 snapshot. No unknown query is erased to obtain this positive empty proof.
 """
 main=v['main'];box=v['searchFieldBox']
 if (main['width'],main['height'])!=(905,667) or box!=[main['x']+78,main['y']+40,main['x']+280,main['y']+70]:return False
 if image.mode!='RGB':return False
 return hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest()=='6c8ae520a63dbbf17fb53717c0b4a2e0ad8fdb519675c96e778b79009c226b8f'

def path(d,j):
 if not re.fullmatch('[a-f0-9]{32}',j.get('id','')):raise ValueError('exact internal forward job ID required')
 return d.root/(j['id']+'-forward-phase.json')
def write(d,j,v):
 from .contract import digest
 value=dict(v,jobId=j['id'],peer=j['peer'],payloadHash=digest(j['payload']))
 p=path(d,j);tmp=p.with_suffix('.tmp')
 if p.is_symlink() or tmp.exists():raise ValueError('forward journal collision')
 fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p);return value
def read(d,j):
 from .contract import digest
 p=path(d,j)
 if p.is_symlink():raise ValueError('forward journal symlink')
 if not p.exists():return None
 s=p.stat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_size>30000 or s.st_mode&0o077:raise ValueError('private bounded forward journal required')
 v=json.loads(p.read_text())
 if (v['jobId'],v['peer'],v['payloadHash'])!=(j['id'],j['peer'],digest(j['payload'])):raise ValueError('forward journal identity mismatch')
 return v

def source_job(j):return dict(j,peer=j['payload']['source_peer'])

def require_window_focus(c,w):
 # Controls.one uses the legacy quote-blind parser. Exact window identity and
 # focus, already guarded by this recipe, must not inherit that parser bug.
 import ctypes
 focus=ctypes.c_ulong();revert=ctypes.c_int();c.x.XGetInputFocus(c.d,ctypes.byref(focus),ctypes.byref(revert))
 if focus.value!=int(w['id'],16):raise BeforeEffect('exact owned history window lost focus')

def close_history(d,j):
 from .windows import window_identity
 from .recipes import controls,activate
 v=read(d,j);own=v.get('history') if v else None
 if not own:return True
 windows=d.app_windows()
 if own not in windows:return not any(w['id']==own['id'] for w in windows)
 if window_identity(own)!=v['historyIdentity']:return False
 c=controls(d)
 try:
  activate(c,own);require_window_focus(c,own);c.click(own['x']+own['width']-16,own['y']+14);c.wait(200)
 finally:c.close()
 after=d.app_windows()
 return after==[w for w in windows if w!=own]

def article_history(d,j,source,c):
 from .recipes import main_window,rows,screen,activate,context_menu,PreparationError
 from .selectors import unique_line
 from .windows import window_identity
 from .ocr import normalized
 from .contract import digest
 v=read(d,j);chat=main_window(d);before=d.app_windows();native=d.tool().resolve(j['payload']['source_peer'])
 sidebar=[chat['x']+chat['width']-320,chat['y']+75,chat['x']+chat['width']-8,chat['y']+chat['height']-15]
 panel_labels={'groupname','myaliasingroup','groupqrcode','searchchathistory','displaymembersnicknames'}
 if len({normalized(r['text']) for r in rows(d,sidebar,lang='eng')}&panel_labels)>=2:raise PreparationError('SOURCE_SIDE_PANEL_PROTECTED','Existing source group information is preserved.')
 v.update(sourceChat=chat,phase='sidebar-intent',sidebarBox=sidebar);write(d,j,v)
 # This button only opens group information. No composer input or terminal.
 c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(180)
 point=None
 for _ in range(5):
  matches=[r['point'] for r in rows(d,sidebar,lang='eng') if normalized(r['text'])=='searchchathistory']
  if len(matches)>1:raise PreparationError('HISTORY_CONTROL_AMBIGUOUS','Multiple chat-history controls.',clean=False)
  if matches:
   point=matches[0];v.update(sidebarOpened=True);write(d,j,v);break
  c.t.XTestFakeMotionEvent(c.d,-1,sidebar[0]+150,sidebar[3]-60,0)
  for _ in range(4):
   for down in (1,0):c.t.XTestFakeButtonEvent(c.d,5,down,0)
   c.x.XFlush(c.d);c.wait(80)
  c.x.XFlush(c.d);c.wait(150)
 if point is None:raise PreparationError('HISTORY_CONTROL_NOT_VISIBLE','Official source chat-history control not found.',clean=False)
 # Qt's sidebar can keep moving after the last wheel event. Never click the
 # first OCR coordinate while scrolling is still settling.
 observations=[point];stable=False
 for _ in range(6):
  c.wait(180)
  matches=[r['point'] for r in rows(d,sidebar,lang='eng') if normalized(r['text'])=='searchchathistory']
  if len(matches)!=1:break
  current=matches[0];observations.append(current)
  if current==point:stable=True;break
  point=current
 v.update(historyControlObservations=observations);write(d,j,v)
 if not stable:raise PreparationError('HISTORY_CONTROL_NOT_STABLE','Source history control has not stabilized; no click.',clean=False)
 c.require_focus(chat)
 v.update(historyControlPoint=point);write(d,j,v)
 c.click(*point)
 after=[];added=[]
 for pause in (150,250,400,800):
  c.wait(pause);after=d.app_windows();added=[w for w in after if w['id'] not in {x['id'] for x in before}]
  if added:break
 v.update(historyObserved=added);write(d,j,v)
 expected=re.compile('Chat history of "'+re.escape(native['displayName'])+'"(?:\\([0-9]+\\))?')
 if len(added)!=1 or (added[0]['width'],added[0]['height'])!=(584,750) or not expected.fullmatch(added[0]['title']):raise PreparationError('HISTORY_WINDOW_NOT_VERIFIED','Exact source chat-history window is not proven.',clean=False)
 history=added[0];identity=window_identity(history);host=window_identity(v['main'])
 if identity['class']!=host['class'] or identity['pid']!=host['pid'] or identity['leader']!=host['leader']:raise PreparationError('HISTORY_WINDOW_NOT_VERIFIED','History does not belong to the pinned official client.',clean=False)
 v.update(history=history,historyIdentity=identity,phase='history-open');write(d,j,v)
 activate(c,history);require_window_focus(c,history)
 tab=unique_line(rows(d,[history['x']+25,history['y']+85,history['x']+history['width']-20,history['y']+145],lang='eng'),'Links')
 c.click(*tab);c.wait(200)
 box=history_bounds(history)
 # Separate tiny grey English date captions from Chinese link text; no model,
 # OCR substitutions, or same-title first-result fallback.
 date_rows=rows(d,[history['x']+498,history['y']+171,history['x']+566,history['y']+721],psm=6,lang='eng')
 title_rows=rows(d,[history['x']+75,history['y']+166,history['x']+495,history['y']+721],contrast=160,psm=6)
 try:point=history_candidate(date_rows+title_rows,source,box)
 except ValueError:raise PreparationError('SOURCE_HISTORY_NOT_VISIBLE','Exact article sender/date/title is not uniquely visible in source history.',clean=False) from None
 v.update(phase='source-qualified',sourceWitnessSHA256=digest(source['historyLocator']));write(d,j,v)
 context_menu(d,c,point,'Forward...')

def select_recipient(d,j,c,w):
 from .recipes import rows,paste_field,screen,PreparationError
 from .selectors import unique_line
 from .ocr import normalized
 target=d.tool().resolve(j['peer']);name=target['displayName']
 if not name or name==j['peer'] or d.name_peer(name)!=j['peer']:raise PreparationError('FORWARD_RECIPIENT_NOT_VERIFIED','Exact native target name is absent or ambiguous.',clean=False)
 # The search field is an editable recipient filter, never the attached-message
 # composer. Copy-back certifies the complete native name before selection.
 paste_field(c,[w['x']+160,w['y']+35],name);c.wait(200)
 # Match the actual name column, excluding checkbox/avatar OCR artifacts.
 box=[w['x']+90,w['y']+95,w['x']+334,w['y']+510]
 values=rows(d,box);matches=recipient_name_points(values,name)
 v=read(d,j);v['recipientResultObservation']={'nameColumn':box,'rows':values};write(d,j,v)
 native_query_review=False
 if len(matches)!=1:
  # Chinese glyph OCR is not recipient identity. For the explicitly manual
  # forward path, require the complete copied-back native-unique query AND
  # exactly one official local result checkbox. Its final Chinese recipient
  # still has to be inspected by the caller before the one terminal confirm.
  picker_image=screen(d).crop((w['x'],w['y'],w['x']+w['width'],w['y']+w['height']))
  diagnostic=d.previews/(j['id']+'-forward-picker.png');picker_image.save(diagnostic);diagnostic.chmod(0o600)
  section_rows=rows(d,[w['x']+10,w['y']+55,w['x']+334,w['y']+110],contrast=True,lang='eng',psm=6)
  section_ok=picker_section(section_rows,j['peer'].endswith('@chatroom'))
  points=single_local_result(screen(d),[w['x']+22,w['y']+95,w['x']+45,w['y']+510])
  v['recipientResultObservation'].update(sectionRows=section_rows,singleLocalControls=points);write(d,j,v)
  if len(matches)>1 or not section_ok or len(points)!=1:raise PreparationError('FORWARD_RECIPIENT_NOT_VISIBLE','No sole native filtered recipient result for the exact copied-back query.',clean=False)
  matches=points;native_query_review=True
 selected=[w['x']+345,w['y']+72,w['x']+730,w['y']+300]
 dark=lambda image,area:sum(min(px)<100 for px in image.crop(tuple(area)).convert('RGB').getdata())
 if dark(screen(d),selected)>30:raise PreparationError('FORWARD_RECIPIENT_NOT_VERIFIED','Picker already contains selected recipients; preserved.',clean=False)
 checkbox=[w['x']+18,matches[0][1]-16,w['x']+48,matches[0][1]+16]
 c.click(w['x']+33,matches[0][1]);c.wait(200)
 # Only the first selected recipient row may have glyphs. The remainder must
 # stay empty; neither messages nor extra recipients are accepted as noise.
 rest=[selected[0],w['y']+150,selected[2],w['y']+295]
 im=screen(d)
 green=sum(g>=100 and g>r+50 and g>b+25 for r,g,b in im.crop(tuple(checkbox)).convert('RGB').getdata())
 v=read(d,j);v['selectionObservation']={'checkboxGreen':green,'selectedDark':dark(im,selected),'restDark':dark(im,rest)};write(d,j,v)
 if green<15 or dark(im,selected)<=30 or dark(im,rest)>30:raise PreparationError('FORWARD_RECIPIENT_NOT_VERIFIED','Sole selected recipient is not proven.',clean=False)
 return {'peer':j['peer'],'nameSHA256':hashlib.sha256(name.encode()).hexdigest(),'querySHA256':hashlib.sha256(name.encode()).hexdigest(),'window':w,'box':selected,'sha256':hashlib.sha256(im.crop(tuple(selected)).tobytes()).hexdigest(),'selectionCount':1,'nativeName':name,'manualNameReviewRequired':native_query_review,'method':'exact-native-name-query-single-local-result'}

def recipient_name_points(values,name):
 from .ocr import normalized
 expected=normalized(name);matches=[]
 # A complete native name outranks optional rendered member-count labels.
 # Keep every exact row, so duplicate exact names remain ambiguous. Never
 # merge a different numbered name into an already exact native-name match.
 exact=[r['point'] for r in values if normalized(r['text'].strip())==expected]
 if exact:return exact
 for r in values:
  text=r['text'].strip();without_count=re.sub(r'[（(][0-9]+[）)]$','',text).strip()
  if normalized(text)==expected or normalized(without_count)==expected:matches.append(r['point'])
 return matches

def picker_section(values,is_group):
 from .ocr import normalized
 expected='groupchats' if is_group else 'contacts'
 return sum(normalized(re.sub(r'\([0-9]+\)$','',r['text']).strip())==expected for r in values)==1

def single_local_result(image,box):
 """Bounded native picker checkbox column, excluding avatars and names."""
 im=image.crop(tuple(box)).convert('RGB');w,h=im.size
 if not 10<=w<=30 or not 50<=h<=500:raise ValueError('calibrated native result column required')
 mask=set()
 for y in range(h):
  for x in range(w):
   px=im.getpixel((x,y))
   if max(px)-min(px)<12 and 80<min(px)<235:mask.add((x,y))
 points=[]
 while mask:
  seed=mask.pop();todo=[seed];component=[seed]
  while todo:
   x,y=todo.pop()
   for dx in (-1,0,1):
    for dy in (-1,0,1):
     p=(x+dx,y+dy)
     if p in mask:mask.remove(p);todo.append(p);component.append(p)
  xs=[p[0] for p in component];ys=[p[1] for p in component];left,right=min(xs),max(xs);top,bottom=min(ys),max(ys)
  if 9<=right-left<=21 and 9<=bottom-top<=21 and abs((right-left)-(bottom-top))<=3 and len(component)>=18:points.append([box[0]+(left+right)//2,box[1]+(top+bottom)//2])
 return points

def prepare(d,j):
 from .recipes import PreparationError
 try:return _prepare(d,j)
 except Exception as e:
  v=read(d,j)
  if v:
   v['lastFailure']={'type':type(e).__name__,'code':getattr(e,'code',None),'detail':str(e)[:180],'phase':v['phase']}
   write(d,j,v)
  # This only permits cleanup to be tried. finish() must positively prove the
  # original owned scene before any failed/noSend state can be certified.
  raise PreparationError(getattr(e,'code','FORWARD_PREPARATION_FAILED'),str(e)[:150],clean=True) from None

def _prepare(d,j):
 from .recipes import main_window,screen,controls,locate_source,context_menu,remember_forward,final_step_preview,rows
 from .selectors import unique_line
 from .windows import window_identity
 from .contract import digest
 if read(d,j):raise BeforeEffect('existing original forward phase must be settled, never re-prepared')
 write(d,j,{'phase':'preflight','beforeNavigation':True})
 try:
  source=preflight(d,j)
  d.fast_versions(j);d.registered_binding(j['peer']);d.registered_binding(j['payload']['source_peer'])
 except Exception:
  write(d,j,{'phase':'preflight-rejected','beforeNavigation':True});raise
 d.active_window=None;main=main_window(d);before=d.app_windows()
 field=[main['x']+78,main['y']+40,main['x']+280,main['y']+70]
 v={'phase':'navigation','main':main,'mainIdentity':window_identity(main),'beforeWindows':before,'searchFieldBox':field,'searchFieldSHA256':hashlib.sha256(screen(d).crop(tuple(field)).tobytes()).hexdigest(),'querySHA256':hashlib.sha256(d.tool().resolve(j['payload']['source_peer'])['displayName'].encode()).hexdigest(),'sourceSHA256':digest({'kind':source['kind'],'text':source['text']})}
 write(d,j,v);d._select(source_job(j));c=controls(d)
 try:
  if source.get('historyLocator'):article_history(d,j,source,c)
  else:context_menu(d,c,locate_source(d,source_job(j),source),'Forward...')
  w=remember_forward(d,j);v=read(d,j);v.update(phase='picker-open',picker=w);write(d,j,v)
  unique_line(rows(d,[w['x']+335,w['y']+12,w['x']+730,w['y']+60]),'Send To')
  proof=select_recipient(d,j,c,w)
  send=unique_line(rows(d,[w['x']+416,w['y']+529,w['x']+531,w['y']+562],psm=6,lang='eng'),'Send')
  v.update(phase='prepared');write(d,j,v)
  return final_step_preview(d,j,{'kind':'commit_forward','point':send},ownedForward=True,recipientSelectionProof=proof,recipientManualReviewRequired=proof['manualNameReviewRequired'],recipientNativeName=proof['nativeName'],sourceSignatureSHA256=v['sourceSHA256'])
 finally:c.close()

def verify_commit(d,j,im):
 from .contract import digest
 p=j['preview'];proof=p.get('recipientSelectionProof')
 if not proof:return False # Legacy previews keep their existing verifier.
 if proof.get('manualNameReviewRequired') and p.get('confirmationSource')!='manual':raise BeforeEffect('native-query recipient mapping requires caller final Chinese preview confirmation')
 name=d.tool().resolve(j['peer'])['displayName']
 d.fast_versions(j)
 if proof['peer']!=j['peer'] or proof['selectionCount']!=1 or d.name_peer(name)!=j['peer'] or hashlib.sha256(name.encode()).hexdigest()!=proof['nameSHA256'] or proof.get('querySHA256',proof['nameSHA256'])!=proof['nameSHA256']:raise BeforeEffect('exact selected recipient identity changed')
 if proof['window'] not in d.app_windows() or hashlib.sha256(im.crop(tuple(proof['box'])).tobytes()).hexdigest()!=proof['sha256']:raise BeforeEffect('selected recipient pane changed since final preview')
 source=d._native_source(j)
 if digest({'kind':source['kind'],'text':source['text']})!=p['sourceSignatureSHA256']:raise BeforeEffect('exact original source content changed')
 return True

def finish(d,j,accepted=False):
 try:return _finish(d,j,accepted)
 except (ValueError,OSError,KeyError):return False

def finish_accepted(d,j):
 """Original guard remains held; retry only owned cleanup, never execution."""
 from .recipes import controls
 for pause in (0,100,200,400):
  if pause:
   c=controls(d)
   try:c.wait(pause)
   finally:c.close()
  if finish(d,j,accepted=True):return True
 return False

def _finish(d,j,accepted=False):
 from .recipes import cleanup_forward,controls,main_window,activate,screen
 from .navigation import restore_search
 v=read(d,j)
 if not v:return False # Do not claim old, unjournaled failures are clean.
 if v['phase']=='settled':return True
 attempt=(d.root/(j['id']+'-attempt.json')).exists()
 if attempt and not accepted:return False
 if v['phase']=='preflight-rejected':
  if attempt or (d.root/(j['id']+'-owned-forward.json')).exists():return False
  v.update(phase='settled',noNavigation=True);write(d,j,v);return True
 if 'beforeWindows' not in v:return False
 # Accepted picker should already have disappeared. Never click it again.
 if accepted:
  if v.get('picker') in d.app_windows():return False
 else:
  marker=d.root/(j['id']+'-owned-forward.json')
  if marker.exists() and not cleanup_forward(d,j):return False
 if not close_history(d,j):return False
 if v.get('sidebarOpened'):
  chat=v['sourceChat']
  if chat not in d.app_windows():return False
  c=controls(d)
  try:activate(c,chat);c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(180)
  finally:c.close()
  v.update(sidebarOpened=False);write(d,j,v)
 from .windows import window_identity
 windows=d.app_windows();before=v['beforeWindows'];extra=[w for w in windows if w not in before]
 if extra:
  # Same strict baseline predicate as ordinary navigation: parent properties
  # alone never justify dismissing an unknown official utility/modal.
  d.active_window=None;main_window(d)
 if d.app_windows()!=before or window_identity(v['main'])!=v['mainIdentity']:return False
 c=controls(d)
 try:
  d.active_window=None;main_window(d);activate(c,v['main'])
  if not restore_search(d,v,c):
   c.click(v['main']['x']+450,v['main']['y']+20);c.wait(100)
   image=screen(d)
   if hashlib.sha256(image.crop(tuple(v['searchFieldBox'])).tobytes()).hexdigest()==v['searchFieldSHA256']:
    v.update(searchBaselineOutcome='original-field-exact-after-focus',priorSearchPixelAppearanceRestored=True)
   elif canonical_empty_search(image,v):
    v.update(searchBaselineOutcome='verified-canonical-empty',priorSearchPixelAppearanceRestored=False)
   else:return False
 finally:c.close()
 if d.app_windows()!=before:return False
 v.update(phase='settled',settledAt=time.time());write(d,j,v);return True
