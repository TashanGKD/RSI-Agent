"""Explicit recurring-definition validation; no timers or automatic materialization."""
from datetime import date
from contracts import day,TIMEZONE
from .schedule import interval
from .legacy_store import ValidationError

def recurrence(value):
 if value is None:return None
 if not isinstance(value,dict) or set(value)-{'frequency','weekdays','startDate','endDate','startTime','endTime','enabled','timezone'}:raise ValidationError('循环定义字段无效')
 freq=value.get('frequency');start=day(value.get('startDate'));end=day(value.get('endDate'))
 if freq not in ('daily','weekly') or not start or (end and end<start):raise ValidationError('循环日期或频率无效')
 weekdays=value.get('weekdays',[])
 if not isinstance(weekdays,list) or len(weekdays)>7 or len(set(weekdays))!=len(weekdays) or any(type(v) is not int or not 0<=v<=6 for v in weekdays):raise ValidationError('星期须为0至6，周一为0')
 if freq=='weekly' and not weekdays or freq=='daily' and weekdays:raise ValidationError('每周循环需指定星期；每日循环不另填星期')
 enabled=value.get('enabled',True)
 if type(enabled) is not bool or value.get('timezone',TIMEZONE)!=TIMEZONE:raise ValidationError('循环时区/开关无效')
 st,en=interval(value.get('startTime'),value.get('endTime'))
 return dict(frequency=freq,weekdays=sorted(weekdays),startDate=start,endDate=end,startTime=st,endTime=en,enabled=enabled,timezone=TIMEZONE)

def includes(rule,d):
 return rule['enabled'] and rule['startDate']<=d and (not rule['endDate'] or d<=rule['endDate']) and (rule['frequency']=='daily' or date.fromisoformat(d).weekday() in rule['weekdays'])
