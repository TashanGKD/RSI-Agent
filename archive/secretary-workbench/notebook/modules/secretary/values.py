"""Bounded public-tool value checks; no persistence or source acquisition."""
import copy
import datetime as dt
import re
from zoneinfo import ZoneInfo
from contracts import day, text, TIMEZONE, ValidationError
from contracts.source_refs import source_refs


def times(start, end):
    start = None if start == '' else start
    end = None if end == '' else end
    for value in (start, end):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value)):
            raise ValidationError('invalid schedule clock')
    if end and (not start or end <= start):
        raise ValidationError('schedule end must follow start')


def structured(fields):
    """Validate structure without converting missing or null values into text."""
    if 'work' in fields:
        from contracts.work import work_metadata
        work_metadata(fields['work'])
    if 'sourceContacts' in fields:
        source_refs(fields['sourceContacts'])
    for key in ('deadlineDate', 'planDate', 'reviewDate'):
        if key in fields:
            day(fields[key])
    f = fields.get('followup')
    if f is not None:
        if not isinstance(f, dict) or set(f) - {'date', 'at', 'condition', 'remindEvenUnchanged'}:
            raise ValidationError('invalid followup fields')
        d = day(f.get('date'))
        text(f.get('condition', ''), 'followup condition', 2000, empty=True)
        if type(f.get('remindEvenUnchanged', True)) is not bool:
            raise ValidationError('invalid followup option')
        at = f.get('at')
        if at is not None and at != '':
            if not isinstance(at, str) or len(at) > 60:
                raise ValidationError('invalid followup timestamp')
            try:
                parsed = dt.datetime.fromisoformat(at.replace('Z', '+00:00'))
                if parsed.tzinfo is None or (d and parsed.astimezone(ZoneInfo(TIMEZONE)).date().isoformat() != d):
                    raise ValueError()
            except ValueError:
                raise ValidationError('invalid followup timestamp') from None
    w = fields.get('eventWindow')
    if w is not None:
        if not isinstance(w, dict) or set(w) - {'start', 'end', 'timezone'} or w.get('timezone', TIMEZONE) != TIMEZONE:
            raise ValidationError('invalid event window')
        parsed = []
        for value in (w.get('start'), w.get('end')):
            if value in (None, '') and parsed:
                continue
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?\+08:00', value):
                raise ValidationError('invalid event window timestamp')
            parsed.append(dt.datetime.fromisoformat(value))
        if (fields.get('planDate') and parsed[0].date().isoformat() != fields['planDate']) or (len(parsed) > 1 and (parsed[1] <= parsed[0] or parsed[1].date() != parsed[0].date())):
            raise ValidationError('invalid event window range')
    r = fields.get('recurrence')
    if r is not None:
        if not isinstance(r, dict) or set(r) - {'frequency','weekdays','startDate','endDate','startTime','endTime','enabled','timezone'}:
            raise ValidationError('invalid recurrence fields')
        start, end = day(r.get('startDate')), day(r.get('endDate'))
        days = r.get('weekdays', [])
        if (r.get('frequency') not in ('daily', 'weekly') or not start or (end and end < start)
            or not isinstance(days, list) or len(days) > 7 or any(type(v) is not int or not 0 <= v <= 6 for v in days)
            or len(days) != len(set(days)) or (r['frequency'] == 'daily' and days) or (r['frequency'] == 'weekly' and not days)
            or type(r.get('enabled', True)) is not bool or r.get('timezone', TIMEZONE) != TIMEZONE):
            raise ValidationError('invalid recurrence definition')
        times(r.get('startTime'), r.get('endTime'))
    return fields


def schedule_fields(fields, create=False, current=None):
    allowed = {'date','startTime','endTime','note'} if create else {'state','startTime','endTime','note','postponeTo','followup'}
    if not isinstance(fields, dict) or set(fields) - allowed or not fields:
        raise ValidationError('invalid schedule fields')
    if 'note' in fields:
        text(fields['note'], 'schedule note', 12000, empty=True)
    if 'state' in fields and fields['state'] not in ('其他','待办','等对方','暂缓','已完成','不用管了'):
        raise ValidationError('invalid schedule state')
    base = current or {}
    times(fields.get('startTime', base.get('startTime')), fields.get('endTime', base.get('endTime')))
    if create and not day(fields.get('date')):
        raise ValidationError('schedule date required')
    structured({'followup': fields['followup']}) if 'followup' in fields else None
    if 'postponeTo' in fields:
        p = fields['postponeTo']
        if not isinstance(p, dict) or set(p) - {'date', 'startTime', 'endTime'} or not day(p.get('date')) or fields.get('state') != '暂缓':
            raise ValidationError('postpone requires explicit later date and 暂缓 state')
        times(p.get('startTime'), p.get('endTime'))
        if p['date'] <= base.get('date', '') or p['date'] < dt.datetime.now(ZoneInfo(TIMEZONE)).date().isoformat():
            raise ValidationError('postpone date must be later and not in the past')
    return copy.deepcopy(fields)
