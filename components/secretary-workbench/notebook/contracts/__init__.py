"""Small, shared value contracts. No persistence, SDK, or network dependencies."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .errors import ValidationError, ConflictError
STATES=('其他','待办','等对方','暂缓','已完成','不用管了')
DOMAINS=('科研','他山','示例项目项目','个人生活')
CLOSED=frozenset(('已完成','不用管了'))
KINDS=('action','project','goal','memo')
TIMEZONE='Asia/Shanghai'

def today():return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

def state(value):
    aliases={'待判断':'其他','待处理':'待办','进行中':'待办','已结束':'不用管了','交给AI处理':'待办','稍后提醒':'待办'}
    if not isinstance(value,str) or aliases.get(value,value) not in STATES:raise ValidationError('处理状态无效')
    return aliases.get(value,value)

def text(value,label='文字',limit=12000,empty=False):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or (not empty and not value.strip()):raise ValidationError(label+'无效或过长')
    return value

def day(value,label='日期'):
    if value in (None,''):return None
    if not isinstance(value,str) or len(value)!=10:raise ValidationError(label+'须为北京日期')
    try:return date.fromisoformat(value).isoformat()
    except ValueError:raise ValidationError(label+'无效')

def actor(value=None):
    value={'name':'我','kind':'human'} if value is None else value
    if not isinstance(value,dict) or set(value)!={'name','kind'} or value.get('kind') not in ('human','ai'):raise ValidationError('记录身份无效')
    return {'name':text(value['name'],'记录人',120),'kind':value['kind']}
