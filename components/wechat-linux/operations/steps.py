"""Bounded, screenshot-confirmed fallback steps; no arbitrary commands or keys."""
import hashlib
def validate_step(s,bounds,fields):
 if not isinstance(s,dict) or s.get('kind') not in ('click','right_click','double_click','paste','scroll','finish','check_target','commit','commit_forward','commit_friend_request','export_image'):raise ValueError('unsupported assistance step')
 allowed={'kind','point'}|({'field'} if s['kind']=='paste' else set())|({'amount'} if s['kind']=='scroll' else set())
 if set(s)-allowed:raise ValueError('unknown step fields')
 if s['kind'] in ('finish','check_target','commit'):
  if set(s)!={'kind'}:raise ValueError('no coordinates for acknowledgement')
  return s
 p=s.get('point')
 if not isinstance(p,list) or len(p)!=2 or any(type(x) is not int for x in p) or not bounds[0]<p[0]<bounds[2] or not bounds[1]<p[1]<bounds[3]:raise ValueError('step must remain in the visible official-client window')
 if s['kind']=='paste' and s.get('field') not in fields:raise ValueError('paste only a frozen field from this request')
 if s['kind']=='scroll' and (type(s.get('amount')) is not int or not -5<=s['amount']<=5 or not s['amount']):raise ValueError('bounded scroll amount required')
 return s
def step_patch(image,step,bounds):
 if step['kind']=='commit_friend_request':box=bounds
 elif step['kind']=='commit_forward':box=[bounds[0]+420,bounds[1]+90,bounds[2]-90,bounds[3]-90]
 elif step['kind']=='commit':box=[bounds[0]+315,bounds[1]+34,bounds[2]-30,bounds[1]+82]
 elif step['kind'] in ('finish','check_target'):box=bounds
 else:
  x,y=step['point'];box=[max(bounds[0],x-65),max(bounds[1],y-24),min(bounds[2],x+65),min(bounds[3],y+24)]
 return {'box':box,'sha256':hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest()}
