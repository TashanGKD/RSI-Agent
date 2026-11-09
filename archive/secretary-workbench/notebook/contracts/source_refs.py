"""Portable metadata-only source locators. Raw source contents are never implicit."""
import re
from datetime import datetime
from . import text
from .errors import ValidationError

FIELDS={'sourceId','accountId','recordId','nativeId','sender','conversation','at','type',
 'precision','version','contentHash','page','paragraph','offsetMs','endOffsetMs','url'}

def source_refs(value):
 if not isinstance(value,list) or len(value)>20:raise ValidationError('来源定位须为至多20项')
 result=[]
 for ref in value:
  if not isinstance(ref,dict) or set(ref)-FIELDS or not ref.get('sourceId') or not (ref.get('recordId') or ref.get('nativeId')):raise ValidationError('来源定位缺少真实来源/记录编号或含禁止字段')
  row={}
  for k,v in ref.items():
   if k in ('page','paragraph','offsetMs','endOffsetMs'):
    if type(v) is not int or v<0 or v>10**12:raise ValidationError('来源页码/偏移无效')
   else:text(v,'来源定位',2048 if k=='url' else 1000)
   row[k]=v
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}:[A-Za-z0-9_-]{1,64}',row['sourceId']):raise ValidationError('来源身份须为平台:账号')
  if row.get('precision') and row['precision'] not in ('unknown','date','minute','second','millisecond'):raise ValidationError('来源时间精度无效')
  if 'at' in row:
   try:
    d=datetime.fromisoformat(row['at'].replace('Z','+00:00'))
    if len(row['at'])!=10 and d.tzinfo is None:raise ValueError()
   except ValueError:raise ValidationError('来源时间须带时区或只含日期') from None
  if row.get('contentHash') and not re.fullmatch(r'[a-fA-F0-9]{64}',row['contentHash']):raise ValidationError('来源哈希无效')
  if 'url' in row:
   from urllib.parse import urlsplit
   u=urlsplit(row['url'])
   if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or any(c.isspace() for c in row['url']):raise ValidationError('来源链接须为无认证参数的HTTPS链接')
   # Authentication/activation parameters have no place in a source locator.
   if any(k in u.query.lower() for k in ('token=','password=','secret=','key=')):raise ValidationError('来源链接不能含认证参数')
  if row.get('endOffsetMs',0)<row.get('offsetMs',0) and 'endOffsetMs' in row:raise ValidationError('媒体结束位置无效')
  if row not in result:result.append(row)
 return result
