"""Bound native metadata only; never select a chat, read its body or send."""
from pathlib import Path


def observe(owner):
    from linux_tool import native, ACCOUNT
    from operations.windows import visible, window_identity
    checks = {'account': False, 'client': False, 'layout': False}
    try:
        with native('contact/contact.db') as (db, receipt):
            checks['account'] = (ACCOUNT == owner['account'] and receipt.get('consistency') == 'committed'
                and not receipt.get('gap') and db.execute('SELECT 1 FROM contact WHERE username=?', (ACCOUNT,)).fetchone() is not None)
        windows = visible()
        mains = [w for w in windows if w['title'] == 'Weixin']
        if len(mains) == 1:
            identity = window_identity(mains[0])
            checks['client'] = (identity['class'] == ['wechat', 'wechat']
                and Path('/proc', str(identity['pid']), 'exe').resolve() == Path('/opt/wechat/wechat')
                and 'TracerPid:\t0\n' in Path('/proc', str(identity['pid']), 'status').read_text())
            checks['layout'] = (mains[0]['width'], mains[0]['height']) == (905, 667)
    except (OSError, ValueError, KeyError):
        pass
    return {'checks': checks}
