from xml.sax.saxutils import escape

TYPE19 = (19 << 32) | 49


def item(kind=1, text='合成普通文字', *, sender='合成发言人', time='2026-11-04 10:00', extra=''):
    field = 'datadesc' if kind == 1 else 'datatitle'
    return (f'<dataitem datatype="{kind}"><{field}>{escape(text)}</{field}>'
            f'<sourcename>{escape(sender)}</sourcename><sourcetime>{escape(time)}</sourcetime>'
            f'{extra}</dataitem>')


def record(items, count=None):
    attr = f' count="{len(items) if count is None else count}"'
    return '<recordinfo><datalist' + attr + '>' + ''.join(items) + '</datalist></recordinfo>'


def card(items=None, *, body=None, encoded=False, count=None, direct=False):
    body = record(items or [], count=count) if body is None else body
    container = body if direct else '<recorditem>' + (escape(body) if encoded else body) + '</recorditem>'
    return ('<msg><appmsg><type>19</type><title>外层预览不是全文</title>'
            '<des>外层摘要不是全文</des>' + container + '</appmsg></msg>')


def nested(items, *, encoded=False):
    body = record(items)
    return item(17, '嵌套预览', extra='<recordxml>' + (escape(body) if encoded else body) + '</recordxml>')
