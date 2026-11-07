"""Business API: submit, review the final preview, confirm, inspect result.
No caller-supplied coordinates, UI plans, or model dependency.
"""
import time
from .api import API
from .contract import ident,validate_job,FAST_ACTIONS
from .store import Conflict
from .assets import AssetBudgetError
from . import assets as asset_limits
from .owner_prefix import OwnerPrefixError

PROGRAM_ACTIONS={'send_text','send_image','send_file','open_chat','open_message','reply','forward','join_group','save_attachment','get_group_qr','create_group','invite_members'}
class PublicError(ValueError):
 def __init__(self,code,message,details=None):
  super().__init__(message);self.code=code;self.details=details or {}
 def response(self):return {'state':'error','error':{'code':self.code,'message':str(self),'details':self.details}}

def clean(value):
 private={'path','point','box','windows','windowBounds','navigationBounds','navigationPoint','joinPoint','joinPatch','step','stepPatch','context','header','attachmentBox','attachmentContext','detail'}
 if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in private}
 if isinstance(value,list):return [clean(v) for v in value]
 return value

def outcome(j):
 state=j['state'];result=j.get('result') or {}
 if state in ('preparing','awaiting_confirmation','needs_assistance') and j.get('expires')==0:return {'status':'pending','next_action':'wait_same_request','cancellationRequested':True}
 if state in ('queued','preparing','confirmed','executing'):return {'status':'pending','next_action':'wait_same_request'}
 if state=='awaiting_confirmation' and j.get('execution_mode')=='verified_fast' and not (j.get('preview') or {}).get('reviewRequired'):return {'status':'pending','next_action':'wait_same_request'}
 if state in ('awaiting_confirmation','needs_assistance'):return {'status':'review_required','next_action':'review_preview'}
 if state=='succeeded' and result.get('state')=='accepted':return {'status':'sent' if j['action'] in ('send_text','send_image','send_file','reply','forward','mention') else 'completed','next_action':'done'}
 if state in ('failed','cancelled','expired') and result.get('noSend') is True:return {'status':'not_sent','next_action':'review_failure','noSend':True}
 return {'status':'unknown','next_action':'reconcile_same_request'}

def mechanism_review(j):
 result=j.get('result') or {};code=result.get('code');category=None
 if j.get('state')=='succeeded' and (result.get('navigationRecoveryPending') or result.get('draftRecoveryPending') or result.get('postActionPending')):category='accepted-cleanup-only'
 elif code in ('DRAFT_PROTECTED','DRAFT_RECOVERY_PENDING'):category='preserved-draft'
 elif code=='PRE_SEND_VALIDATION_FAILED':category='pre-send-validation'
 elif code=='SEND_PREPARATION_FAILED' and result.get('preparationPhase') in ('image-source','image-paste','image-copy-proof'):category='image-preparation'
 elif code in ('RECIPIENT_NOT_VISIBLE','RECIPIENT_NOT_VERIFIED','TARGET_NAME_UNAVAILABLE','UNSUPPORTED_LAYOUT','SEARCH_SELECTION_UNPROVEN','SEARCH_RESULTS_NOT_SUPPORTED','CHAT_POPOUT_NOT_OPENED','NAVIGATION_PREPARATION_FAILED','SEND_PREPARATION_FAILED','OPERATOR_REQUIRED'):category='target-or-layout'
 elif j.get('state') in ('unknown','needs_attention'):category='reconcile-original-only'
 if not category:return None
 return {'ownerThreadId':'00000000-0000-4000-8000-007cd0d4e044','client':j.get('client'),'request_id':j.get('request_id'),'peer':j.get('peer'),'category':category,'automaticReplay':False,'clearDraft':False,'workflow':'caller hands this original receipt to the existing mechanism owner; mature new business continues through the same SDK','authorizationScope':'existing-authorized-target only; mechanism diagnosis is not a new group/business authorization'}

class PublicAPI(API):
 def __init__(self,root,config,contacts=None):super().__init__(root,config);self.contacts=contacts or self._contacts
 def _contacts(self,peers):
  import sys
  from .driver import NATIVE
  if str(NATIVE) not in sys.path:sys.path.insert(0,str(NATIVE))
  from linux_tool import native
  if peers is not None and not peers:return []
  with native('contact/contact.db') as (db,r):
   if r.get('consistency')!='committed':raise PublicError('SOURCE_UNAVAILABLE','Contact snapshot is not committed.')
   if peers is None:rows=db.execute('SELECT username,remark,nick_name,alias FROM contact WHERE delete_flag=0').fetchall()
   else:rows=db.execute('SELECT username,remark,nick_name,alias FROM contact WHERE username IN ('+','.join('?' for _ in peers)+')',peers).fetchall()
   return [{'peer':x['username'],'name':x['remark'] or x['nick_name'] or x['username'],'alias':x['alias'] or ''} for x in rows]
 def client_scope(self,client):
  from .contract import ACTIONS
  ident(client)
  return {'peers':None,'actions':list(ACTIONS)}
 @staticmethod
 def recipient_query(query):
  if not isinstance(query,str) or not query.strip() or len(query)>120 or any(x in query for x in ['\0','\n','\r']):raise PublicError('INVALID_RECIPIENT','Provide an exact name, WeChat ID, or native peer.')
 def resolve(self,client,query):
  scope=self.client_scope(client);self.recipient_query(query)
  return self.resolved_rows(scope,query,self.contacts(scope['peers']))
 def resolved_rows(self,scope,query,rows):
  self.recipient_query(query)
  matches=[x for x in rows if query in [x['peer'],x.get('name'),x.get('alias')]]
  distinct={x['peer']:x for x in matches}
  if len(distinct)>1:raise PublicError('AMBIGUOUS_RECIPIENT','Choose one exact recipient before submitting.',{'candidates':list(distinct.values())})
  if not distinct:raise PublicError('RECIPIENT_NOT_FOUND','Recipient is not present in the current native directory.')
  return dict(next(iter(distinct.values())),state='resolved')
 def view(self,j):
  if j is None:return None
  p=j.get('preview') or {};final=bool(p and not p.get('needs_assistance') and (not p.get('workflow') or p.get('programRecipe')))
  summary=p.get('summary') or {'peer':j['peer'],'action':j['action'],'text':j['payload'].get('text')}
  asset=p.get('asset')
  if asset:summary=dict(summary,asset={k:asset.get(k) for k in ['id','name','bytes','sha256','md5']})
  cancelling=j.get('expires')==0 and j['state'] in ('preparing','awaiting_confirmation','needs_assistance')
  pending_fast=j['state']=='awaiting_confirmation' and j.get('execution_mode')=='verified_fast' and not p.get('reviewRequired')
  preview={'available':final,'sha256':p.get('sha256') if final else None,'expires':j.get('expires'),'summary':clean(summary),'review_required':j['state']=='awaiting_confirmation' and not pending_fast and not cancelling,'fast_verification':clean(p.get('fastVerification'))} if p else None
  result=clean(j.get('result'))
  if j['state'] in ('needs_attention','needs_assistance'):
   result=dict(result or {},code='OPERATOR_REQUIRED',message='The program could not complete preparation or prove cleanup. No coordinate input is requested; preserve this request for maintenance.')
  hint=mechanism_review(dict(j,result=result))
  return {k:j.get(k) for k in ['id','client','request_id','peer','action','payload','state','created','updated']}|{'execution_mode':j.get('execution_mode','manual'),'confirmation_source':p.get('confirmationSource'),'outcome':outcome(j),'preview':preview,'confirmation_token':j.get('confirmation_token') if final and not pending_fast and not cancelling else None,'result':result}|({'dispatch':clean(j['dispatch'])} if 'dispatch' in j else {})|({'readOnlyReconciliation':clean(j['readOnlyReconciliation'])} if 'readOnlyReconciliation' in j else {})|({'mechanismReview':hint} if hint else {})
 def dispatch_summary(self,client,limit=20):
  from .dispatch import spec,waiting,artifact_barrier
  rows=self.s.c.execute('SELECT * FROM jobs WHERE client=? ORDER BY seq DESC LIMIT ?',(client,limit+1)).fetchall();cache={};items=[];counts={'ready':0,'waiting':0,'active':0,'terminal':0}
  barrier=artifact_barrier(self.s)
  if self.s.active():barrier='PROTECTED_ACTIVE'
  for row in rows[:limit]:
   j=self.s.decoded(row);m=spec(self.s,j);reason=waiting(self.s,j,m,cache) if j['state']=='queued' else None
   if j['state']=='queued':
    if barrier:reason=barrier
    counts['waiting' if reason else 'ready']+=1
   elif j['state'] in ('succeeded','failed','cancelled','expired'):counts['terminal']+=1
   else:counts['active']+=1
   items.append({'request_id':j['request_id'],'peer':j['peer'],'action':j['action'],'state':j['state'],'kind':m['kind'],'waitingReason':reason,'outcome':outcome(j)})
  return {'items':items,'counts':counts,'truncated':len(rows)>limit,'countsScope':'returned_items','modelRequired':False}
 def capabilities(self):
  from .owner_prefix import capability
  prefix=capability(self.s.root) if self is not None else {'enabled':False,'runtimeConfigRequired':True,'isAuthorization':False}
  return {'ownerDMPrefix':prefix,'apiVersion':2,'sendingRelease':'2026-10-31-three-action-verified-fast','modelRequired':False,'callerCoordinatesRequired':False,'dispatch':{'version':1,'batchAdmission':True,'sdkInput':'ready-jobs-with-uploaded-asset-ids','sdkUploadsAfterAdmission':False,'maxBatch':20,'maxMultiGet':50,'priorityHints':['reply','delivery','maintenance'],'priorityIsAuthority':False,'atomicMultiMessageSend':False,'nonInterleavedUnitMax':4,'nativeAuditMaxPeers':20,'defaultExecutionMode':'manual','readOnlyEligibilityIsLease':False},'callerWorkflow':'submit -> get/preview -> confirm -> get','transport':'authenticated SSH JSON or local CLI',
   'callerWorkflows':{'manual':{'default':True,'flow':'submit -> get/preview -> confirm -> get'},'verified_fast':{'default':False,'selection':'execution_mode=verified_fast','flow':'submit -> program verification/confirmation -> execute once/native proof -> get','exception':'review_required -> caller preview/confirm or cancel; unknown -> reconcile same request'}},
   'verifiedFast':{'field':'execution_mode','value':'verified_fast','default':'manual','eligibleActions':sorted(FAST_ACTIONS),'requiresPositiveNativeCertification':True,'fallback':'review_required final preview; no blind automatic confirmation','liveAcceptance':'implementation; controlled benchmark tracked separately; not an all-layout reliability claim'},
   'actions':{a:{'programmatic':a in PROGRAM_ACTIONS,'liveAcceptance':('v2-live-native-receipt; controlled owner and science-group samples; not an all-layout reliability rate' if a in {'send_text','send_image','send_file'} else 'v2-native-receipt-verified; controlled single-owner samples' if a in {'reply','forward'} else 'v1-assisted-only; new v2 membership needs a fresh invitation' if a=='join_group' else 'not-supported-through-public-api' if a not in PROGRAM_ACTIONS else 'implemented; see delivery documentation for actual acceptance')} for a in __import__('operations.contract',fromlist=['ACTIONS']).ACTIONS},
   'imageRead':{'action':'save_attachment','method':'programmatic-official-client-save-as','callerCoordinatesRequired':False,'requiredContext':'unique immediate same-sender text neighbors, both visible with one complete image','formats':None,'formatPolicy':'actual installed decoder; official UI support verified per file','maxBytes':None,'crossRequestCache':True,'receiptRequired':True,'verifiedSourceFileReuse':{'explicitVisiblePayload':{'representation':'visible'},'defaultRepresentation':'original','identity':'live exact peer/source/sender/time/localId/nativeMD5/resource plus private official-filename evidence and client asset hash','continuousImages':'source-qualified files can be reused without single-image text anchors; not generic fresh gallery automation','UIInputForReuse':False,'arbitraryCallerPathsAllowed':False,'visibleVariantIsOriginal':False}},
   # Distinguish an implemented action from its supported native-message kinds.
   # This is capability metadata only; no unsupported terminal recipe is enabled.
   'messageMethods':{
    'emojiText':{'action':'send_text','nativeType':1,'programmatic':True},
    'nativeSticker':{'nativeType':47,'programmatic':False,'imageIsEquivalent':False,'reason':'NO_VERIFIED_PROGRAMMATIC_STICKER_SELECTION_RECIPE','manualOfficialSearch':{'verified':True,'sourceMD5MatchedNativeReceipt':True,'requiresOperatorFinalPreview':True,'publicActionEnabled':False,'acceptance':'controlled owner sample via official caption search; one terminal click; exact native47 MD5 receipt'}},
    'reply':{'action':'reply','programmaticSourceKinds':[1,49],'nativeReceiptType':49,'nativeReceiptAppmsgType':57,'exactSourceServerIdRequired':True},
    'forward':{'action':'forward','programmaticSourceKinds':[1,49],'appmsgTypes':[5,6],'allCardsOrMedia':False,'articleSourceLocator':'exact native source id/title/url; unique label or source-day-unique exact title prefix plus official history date/time','forwardJournalVersion':1,'manualConfirmationRequired':True,'liveAcceptance':'controlled text forward and one original native app5 business receipt accepted; source-specific preparation and new-source positioning remain distinct; not an all-layout claim'},
    'friendOperations':{'programmatic':False,'contactDirectoryProvesFriendship':False,'freshControlledIdentityRequiredForLiveAcceptance':True,'manualOfficialGroupMemberRequest':{'verified':True,'state':'request-sent-pending-verification','mutualFriendshipVerified':False,'requiresExactAuthorisedMember':True,'privacyUsed':'Chats Only'}},'groupQRCode':{'action':'get_group_qr','publicActionEnabled':True,'manualConfirmationRequired':True,'manualOfficialExportVerified':True,'programmaticExport':'implemented; live acceptance tracked separately','codePixelsMatchRequired':True,'decodeInServer':False,'scope':'exact configured current group and native self membership','joinVerified':False,'invitationPayloadPrivate':True}},
   'unsupportedActions':['mention','request_friend','accept_friend'],'previewTTLSeconds':180,'constraints':{'singleAssetBytes':asset_limits.SINGLE_BYTES,'inlineAssetBytes':None,'preferredInlineUploadBytes':10000000,'imageAssetBytes':None,'totalAssetBytes':asset_limits.TOTAL_BYTES,'minimumDiskReserveBytes':asset_limits.RESERVE_BYTES,'diskReserveEnforced':True,'streamUploadSeconds':None,'streamIdleSeconds':20,'assetAdmission':'actual disk headroom; no configured file-size or cache-total ceiling','sharedOwnerSSH':True,'clientLabelsAreSecurityTenants':False},
   'navigation':{'version':1,'actions':['send_text','send_image','send_file'],'recipientIdentity':'exact official chat system title plus unique native identity/account/group relation; frozen payload still verified','namedSearchRecipientOCRRequired':False,'nativeSearchSectionProofStillRequired':True,'baseline':'original main geometry/focus; no owned search or empty temporary chat; preexisting windows/drafts preserved','cleanupJournal':'same original job, no new queue','cleanupFailure':'accepted stays accepted; pending cleanup is not permission to resend','automaticFaultMessageSent':False,'exceptionOwnerThreadId':'00000000-0000-4000-8000-007cd0d4e044'},
   'guiDependency':'Official WeChat on the AUP virtual desktop; programmatic GTK/X11 and offline control-section OCR, no private network-send API.'}
 def call(self,r):
  try:return self._call(r)
  except PublicError:raise
  except OwnerPrefixError as e:raise PublicError(e.code,str(e),e.details) from None
  except AssetBudgetError as e:raise PublicError(e.code,str(e),e.details) from None
  except PermissionError:raise PublicError('OUTSIDE_SCOPE','Action, recipient, source, or asset is outside the configured scope.') from None
  except Conflict:raise PublicError('REQUEST_CONFLICT','This request ID already exists with different content or recipient.') from None
  except KeyError:raise PublicError('REQUEST_NOT_FOUND','No matching request or field.') from None
  except (ValueError,TypeError):raise PublicError('INVALID_REQUEST','Invalid fields, payload, confirmation token, or request state.') from None
 def _call(self,r):
  if not isinstance(r,dict):raise PublicError('INVALID_REQUEST','JSON object required.')
  fields={'capabilities':set(),'status':set(),'resolve':{'client','query'},'submit':{'job'},'get':{'client','request_id'},'list':{'client'},'events':{'client','request_id'},'preview':{'client','request_id'},'confirm':{'client','request_id','token'},'cancel':{'client','request_id'},'reconcile':{'client','request_id'},'upload':{'client','name','sha256','data'},'download':{'client','asset'}}
  fields.update({'admit':{'client','batch_id','items'},'get_many':{'client','request_ids'},'dispatch_summary':{'client'},'maintenance_eligibility':{'client'},'audit_many':{'client','request_ids'}})
  op=r.get('op');optional={'ordered','wait_seconds','audit'} if op=='admit' else {'wait_seconds','audit'} if op=='get_many' else {'limit'} if op=='dispatch_summary' else {'wait_seconds'} if op=='get' else set()
  if op not in fields or set(r)-fields[op]-optional-{'op'} or fields[op]-set(r):raise PublicError('INVALID_REQUEST','Unsupported public operation or fields; UI steps are internal.')
  if op in ('admit','get_many','dispatch_summary','maintenance_eligibility','audit_many'):
   self.client_scope(r['client'])
   from .dispatch import identifiers,waiting,spec,MAX_BATCH,MAX_GET
   if op=='maintenance_eligibility':
    with self.s.tx():return self.s.maintenance_eligibility()
   if op=='dispatch_summary':
    limit=r.get('limit',20)
    if type(limit) is not int or not 1<=limit<=20:raise PublicError('INVALID_REQUEST','summary limit must be 1..20')
    return self.dispatch_summary(r['client'],limit)
   if op in ('get_many','audit_many'):
    ids=identifiers(r['request_ids'],MAX_GET if op=='get_many' else MAX_BATCH)
    if not ids:raise PublicError('INVALID_REQUEST','nonempty request IDs required')
   if op=='audit_many':
    for rid in ids:
     try:self.policy.check(self.s.get(r['client'],rid))
     except KeyError:pass
    from .audit import audit_many
    return audit_many(self.s,r['client'],ids,account=self.policy.cfg['account'])
   wait=r.get('wait_seconds',0)
   if type(wait) not in (int,float) or not 0<=wait<=20:raise PublicError('INVALID_REQUEST','wait_seconds must be 0..20')
   audit=r.get('audit',False)
   if type(audit) is not bool:raise PublicError('INVALID_REQUEST','audit must be boolean')
   if op=='admit':
    if not isinstance(r['items'],list) or not 1<=len(r['items'])<=MAX_BATCH:raise PublicError('INVALID_REQUEST','batch requires 1..20 items')
    items=[];contact_rows=None
    for entry in r['items']:
     if not isinstance(entry,dict) or set(entry)-{'job','dispatch'} or 'job' not in entry:raise PublicError('INVALID_REQUEST','invalid batch item')
     j=entry['job']
     if not isinstance(j,dict) or set(j)-{'client','request_id','peer','to','action','payload','execution_mode'} or ('peer' in j)==('to' in j):raise PublicError('INVALID_REQUEST','invalid public batch job')
     if j.get('action') not in PROGRAM_ACTIONS:raise PublicError('UNSUPPORTED_ACTION','No supported public recipe for this action')
     if j.get('client')!=r['client']:raise PublicError('INVALID_REQUEST','Preserve one attribution client per batch.')
     if 'to' in j:
      self.recipient_query(j['to'])
      if contact_rows is None:contact_rows=self.contacts(self.client_scope(r['client'])['peers'])
      j=dict(j,peer=self.resolved_rows(self.client_scope(r['client']),j['to'],contact_rows)['peer']);j.pop('to')
     items.append(dict(entry,job=j))
    admitted=self.s.admit(r['client'],r['batch_id'],items,self.policy.check,r.get('ordered',False));ids=[j['request_id'] for j in admitted]
   end=time.monotonic()+wait
   while True:
    jobs=[]
    for rid in ids:
     try:jobs.append(self.view(self.s.get(r['client'],rid)))
     except KeyError:jobs.append({'request_id':rid,'state':'not_found','error':{'code':'REQUEST_NOT_FOUND'}})
    if time.monotonic()>=end or any(j.get('outcome',{}).get('status') in ('review_required','unknown') for j in jobs) or not any(j.get('outcome',{}).get('status')=='pending' for j in jobs):break
    time.sleep(.15)
   result={'jobs':jobs,'dispatch':self.dispatch_summary(r['client'])}
   present=[j for j in jobs if j.get('id')];timeline={}
   if present:
    rows=self.s.c.execute('SELECT job_id,state,min(at) AS first,max(at) AS last FROM events WHERE job_id IN ('+','.join('?' for _ in present)+') GROUP BY job_id,state',[j['id'] for j in present]).fetchall()
    for event in rows:timeline.setdefault(event['job_id'],{})[event['state']]=(event['first'],event['last'])
   result['lifecycle']=[]
   for job in present:
    events=timeline.get(job['id'],{});first=lambda state:events.get(state,(None,None))[0]
    terminals=[events[state][1] for state in ('succeeded','failed','cancelled','expired') if state in events]
    result['lifecycle'].append({'request_id':job['request_id'],'createdAt':job['created'],'queuedAt':first('queued'),'firstPrepareAt':first('preparing'),'confirmationAt':first('confirmed'),'executionClaimAt':first('executing'),'terminalAt':max(terminals) if terminals else None})
   from .dispatch import asset_state
   asset_cache={};result['asset_status']=[]
   for rid in ids:
    try:raw=self.s.get(r['client'],rid)
    except KeyError:continue
    if 'asset' in raw['payload']:result['asset_status'].append({'request_id':rid,'id':raw['payload']['asset'],'ready':asset_state(self.s,raw,spec(self.s,raw),asset_cache) is None})
   if audit:
    for rid in ids:
     try:self.policy.check(self.s.get(r['client'],rid))
     except KeyError:pass
    from .audit import audit_many
    result['audit']=audit_many(self.s,r['client'],ids,account=self.policy.cfg['account']) if len(ids)<=MAX_BATCH else {'allVerified':False,'items':[],'reason':'AUDIT_REQUEST_BUDGET','nativeSnapshotReads':0,'stateWrites':0}
   return result
  if op=='capabilities':return self.capabilities()
  if op=='status':
   v=super().call(r);active=v['active'];v['active']={k:active.get(k) for k in ['id','client','request_id','action','state','created','updated']} if active else None;v['apiVersion']=2;return v
  if op=='resolve':return self.resolve(r['client'],r['query'])
  if op=='submit':
   j=r['job']
   if not isinstance(j,dict) or set(j)-{'client','request_id','peer','to','action','payload','execution_mode'} or ('peer' in j)==('to' in j):raise PublicError('INVALID_REQUEST','Provide client, request_id, peer OR to, action, payload and optional execution_mode. No UI fields.')
   self.client_scope(j.get('client'))
   if j.get('action') not in PROGRAM_ACTIONS:raise PublicError('UNSUPPORTED_ACTION','This action has no supported model-free public recipe yet.')
   if 'to' in j:
    target=self.resolve(j['client'],j['to']);j=dict(j,peer=target['peer']);j.pop('to')
   j=validate_job(j);self.policy.check(j)
   return self.view(super().call({'op':'submit','job':j}))
  if op=='get':
   wait=r.get('wait_seconds',0)
   if type(wait) not in (int,float) or not 0<=wait<=20:raise PublicError('INVALID_REQUEST','wait_seconds must be 0..20.')
   self.client_scope(r['client']);end=time.monotonic()+wait
   while True:
    j=self.s.get(r['client'],r['request_id'])
    if (j['state'] not in ('queued','preparing','confirmed','executing') and outcome(j)['status']!='pending') or time.monotonic()>=end:return self.view(j)
    time.sleep(.15)
  if op=='confirm':
   j=self.s.get(r['client'],r['request_id']);p=j.get('preview') or {}
   if j.get('execution_mode')=='verified_fast' and j['state']=='awaiting_confirmation' and not p.get('reviewRequired'):raise PublicError('FAST_VERIFICATION_PENDING','Native programmatic verification is still pending; wait on the same request.')
   if p.get('needs_assistance') or (p.get('workflow') and not p.get('programRecipe')):raise PublicError('NOT_A_FINAL_PREVIEW','A legacy UI-step preview cannot be confirmed through the public API.')
  v=super().call(r)
  if op in ('confirm','cancel','reconcile'):return self.view(v)
  if op=='list':return {'jobs':[self.view(x) for x in v['jobs']]}
  if op=='events':
   # The public journal records lifecycle and results, not internal pointer plans.
   import json
   rows=[]
   for row in v['events']:
    item={k:row.get(k) for k in ['seq','at','state']}
    if row['state']=='confirmed':
     source=json.loads(row.get('detail') or '{}').get('source')
     if source in ('manual','programmatic'):item['confirmation_source']=source
    rows.append(item)
   return dict(v,events=rows)
  if op=='preview':
   j=self.s.get(r['client'],r['request_id'])
   if not (self.view(j).get('preview') or {}).get('available'):raise PublicError('PREVIEW_NOT_READY','No final business preview is available yet.')
  return v
