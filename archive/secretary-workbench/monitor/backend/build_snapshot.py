"""Derive the observer's static view only. Does not modify monitored sources."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, datetime, json, re, hashlib
from pathlib import Path
from collect import ROOT, PRIVATE, IDS, bj, sha
OUT = ROOT / 'web/public'
CLOSED = ['已完成', '已交付', '已办好', '不做了']
PAUSED = ['暂缓', '先放放']

def load(name):
    return json.loads((PRIVATE / name).read_text())

def field(head, name):
    m = re.search('^- \\*\\*' + re.escape(name) + '\\*\\*[：:]\\s*(.*)', head, re.M)
    return m.group(1).strip() if m else ''

def plain(s):
    return re.sub('\\[([^\\]]+)\\]\\([^)]+\\)', '\\1', s)

def short(s, n=190):
    return s if len(s) <= n else s[:n] + '…'

def task(id, employee, title, state, pending, next_, source, goal='', origin='', thought='', time='', trajectory=None, kind='workstream', confidence='工作记录支持', who='本员工'):
    return {'id': id, 'employee': employee, 'title': title, 'state': state, 'pending': pending, 'next': next_, 'goal': goal, 'origin': origin, 'thought': thought, 'time': time, 'confidence': confidence, 'evidence': [{'id': source, 'quote': short(goal or pending or next_)}], 'trajectory': trajectory or [], 'kind': kind, 'who_owes': who}

def main():
    print('Legacy instance seed omitted; use examples/seed_monitor.py with synthetic data or configure live_update explicitly.')
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.execute:
        main()
    else:
        p.print_help()
