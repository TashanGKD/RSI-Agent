"""Business occurrence dates and actual participants; not author or save time."""
from . import day,text,ValidationError

def names(value,label):
 if not isinstance(value,list) or len(value)>50:raise ValidationError(label+'须为最多50个名称')
 result=[text(x,label,120) for x in value]
 if len(set(result))!=len(result):raise ValidationError(label+'重复')
 return result

def work_metadata(value):
 if not isinstance(value,dict) or set(value)-{'start','end','participants','organizations'}:raise ValidationError('实际工作字段无效')
 start=day(value.get('start'),'发生日期');end=day(value.get('end',start),'结束日期')
 if bool(start)!=bool(end) or start and end<start:raise ValidationError('实际工作日期区间无效')
 return dict(start=start,end=end,participants=names(value.get('participants',[]),'实际参与人'),organizations=names(value.get('organizations',[]),'组织'))

