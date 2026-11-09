"""Pure fast-confirmation contract; no UI, sending, credentials or alternate queue."""
import re
from .contract import digest,FAST_ACTIONS

def binding_identity(cfg):
 return digest({k:cfg.get(k) for k in ('peer','displayName','paired_account','observedTitle','nativeMemberIds')})

def asset_identity(asset):
 if not isinstance(asset,dict):raise ValueError('asset identity missing')
 keys=('id','client','name','bytes','sha256','md5')
 try:value={k:asset[k] for k in keys}
 except KeyError:raise ValueError('asset identity incomplete') from None
 from .assets import descriptor
 if descriptor(value['client'],value['name'],value['bytes'],value['sha256'])!=value['id'] or not isinstance(value['md5'],str) or not re.fullmatch('[a-f0-9]{32}',value['md5']):raise ValueError('asset identity invalid')
 return value

def final_scene(j,p):
 if j.get('execution_mode')!='verified_fast' or j['action'] not in FAST_ACTIONS or j.get('method','native')!='native':raise ValueError('ineligible fast action')
 if p.get('senderRecipe') is not True or p.get('programRecipe') is not True or p.get('needs_assistance') or p.get('workflow'):raise ValueError('not a final native sender recipe')
 if not re.fullmatch('[a-f0-9]{64}',p.get('sha256','')) or not isinstance(p.get('sendWindows'),list) or (p.get('uiBinding') or {}).get('peer')!=j['peer']:raise ValueError('unproven final target/preview')
 summary=p.get('summary') or {}
 if summary.get('peer')!=j['peer'] or summary.get('action')!=j['action']:raise ValueError('preview differs from immutable job')
 if j['action']=='send_text':
  if summary.get('text')!=j['payload']['text'] or p.get('text')!=j['payload']['text']:raise ValueError('preview text differs')
 else:
  asset=asset_identity(p.get('asset'))
  if asset['id']!=j['payload']['asset']:raise ValueError('preview asset differs')
 versions=p.get('fastVersions')
 if not isinstance(versions,dict) or set(versions)!={'registeredBindingSHA256','bindingIdentitySHA256','scopeSHA256'} or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in versions.values()):raise ValueError('fresh native versions missing')
 return versions

def verify_certificate(j,p,cert):
 versions=final_scene(j,p)
 if not isinstance(cert,dict) or type(cert.get('version')) is not int or cert['version']!=1 or cert.get('eligible') is not True or cert.get('guardVerified') is not True:raise ValueError('positive native certificate required')
 if cert.get('peer')!=j['peer'] or cert.get('action')!=j['action'] or cert.get('payloadSHA256')!=digest(j['payload']) or cert.get('previewSHA256')!=p['sha256'] or cert.get('versions')!=versions:raise ValueError('certificate identity changed')
 if j['action']!='send_text' and cert.get('assetIdentitySHA256')!=digest(asset_identity(p['asset'])):raise ValueError('certified asset metadata changed')
 return cert
