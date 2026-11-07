#!/usr/bin/env python3
"""Preview or copy the bundled synthetic employee into a NEW demo directory only.

Uses the original workbook parser/generator and monitor projection. No employee
registration, source-account read, model, RPC, sender or scheduler is invoked.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/synthetic-employee'
sys.path.insert(0, str(ROOT / 'monitor/backend'))
from live_core import publish, atomic_json

_spec = importlib.util.spec_from_file_location('demo_original_workbook', ROOT / 'skills/digital-employee/scripts/workbook.py')
workbook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(workbook)


def read_example():
    """Read only packaged synthetic files; never an operator-selected employee."""
    return {p.relative_to(EXAMPLE).as_posix(): p.read_text(encoding='utf-8')
            for p in sorted(EXAMPLE.rglob('*')) if p.is_file()}


def _copy_example(files, employee):
    for relative, text in files.items():
        source = EXAMPLE / relative
        target = employee / relative
        # Preserve internal links; adjust links back to the package after copying.
        def link(match):
            value = match[1]
            if value.startswith('../../'):
                filename, sep, fragment = value.partition('#')
                resolved = source.parent / filename
                return '](' + os.path.relpath(resolved, target.parent) + (sep + fragment if sep else '') + ')'
            return match[0]
        text = re.sub(r'\]\(([^)]+)\)', link, text)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


def _projection(employee, rows, now):
    ident = 'fixture-worker'
    thread = '00000000-0000-4000-8000-000000000001'
    role = (employee / 'ROLE.md').read_text(encoding='utf-8')
    name = role.splitlines()[0].removeprefix('# ')
    sources = {'fixture-role': dict(id='fixture-role', label='Synthetic ROLE', path='synthetic://employee/ROLE.md',
               time=now, role='synthetic demonstration, not native evidence', text=role)}
    tasks, items = [], []
    fields = workbook.FIELDS
    for row in rows:
        sid = 'fixture-' + Path(row['file']).stem
        note = (employee / 'workbook' / row['file']).read_text(encoding='utf-8')
        sources[sid] = dict(id=sid, label='Synthetic workbook ' + row['file'], path='synthetic://employee/workbook/' + row['file'], time=now, role='synthetic note, not native receipt', text=note)
        evidence = [dict(id=sid, quote=row[fields[0]])]
        task = dict(id=sid, employee=ident, title=row[fields[0]], state=row[fields[4]],
                    pending=row[fields[5]], next=row[fields[5]], goal=row[fields[2]],
                    origin=row[fields[1]], thought=row[fields[3]], time=row[fields[6]],
                    confidence='synthetic example only', evidence=evidence, trajectory=[], kind='notebook')
        tasks.append(task)
        items.append(dict(id=sid, employee=ident, title=task['title'], origin=task['origin'], originKind='Synthetic workbook',
                          goal=task['goal'], thought=task['thought'], state=task['state'], next=task['next'], time=task['time'],
                          commitment='unknown', sourceId=sid, sourceLabel=sources[sid]['label'], recordUpdatedAt=now,
                          originalRequest=None, interpretationKind='synthetic example only', evidence=evidence))
    role_lines = role.splitlines()
    statement_lines = [s for s in role_lines if s.startswith('- ')]
    def statement(index):
        line = statement_lines[index]
        return dict(text=line[2:], evidence=[dict(id='fixture-role', quote=line)])
    relations = []
    for index, kind, types, label in [(4, 'organization', ['serves'], 'Synthetic event team'),
                                      (5, 'source', ['reads'], 'Synthetic local sources'),
                                      (6, 'collaborator', ['collaborates'], 'Optional proofreader / executor')]:
        quote = statement_lines[index]
        relations.append(dict(id='fixture-relation-' + str(index), label=label, kind=kind, types=types,
                              realId='', scope=quote[2:], evidence=[dict(id='fixture-role', quote=quote)]))
    profile = dict(employee=ident, threadId=thread, observedAt=now, roleName=name,
                   purpose=statement_lines[0][2:], identityEvidence=[dict(id='fixture-role', quote=role_lines[0])],
                   responsibilities=[statement(2)], relations=relations, boundaries=[statement(3)],
                   routines=[], resources=[], capabilities=[],
                   lifecycle=dict(state='unknown', note='Synthetic role; no real registration or wake', evidence=[]),
                   history=[], observedHistory=[], health=dict(lastSuccess=now, lastAttempt=now, error=None))
    person = dict(id=ident, threadId=thread, name=name, role=profile['purpose'], notebook='employee/workbook (synthetic)',
                  runtime='not connected (synthetic)', current='Synthetic preparation / unknown / local result; no real delivery',
                  queueCount=None, lastActivity=now, gap='No real source, role, queue, channel or wake connected', turnHours=0,
                  coverage=dict(messages=0, files=len(rows), notes=len(rows), first=now, last=now, reviewed=False))
    work_person = dict(id=ident, name=name, threadId=thread, category='business', channels=[], observedAt=now, error=None,
                       runtime=dict(state='unknown', queueCount=None, turnId=None, sampledAt=now),
                       notebooks=len(rows), coverage=dict(readThrough=None, note='Synthetic local fixture; no native reading position', source=None),
                       workRead=dict(state='structured', format='employee-work:v1 synthetic', indexedNotes=len(rows),
                                     items=len(rows), staleItems=0, gaps=['Synthetic fixture only; no live source coverage']))
    work = dict(version=1, sampledAt=now, readOnly=True, employees=[work_person], items=items,
                sending=dict(items=[], error=None), discovery=dict(source='synthetic-only', bindings=0, unadaptedThreads=0), modes=dict(dimensions=[], sourceId='fixture-role', note='Synthetic role; no sending or scheduler'))
    snapshot = dict(synthetic=True, generatedAt=now, historyCutoff=now, runtimeAt=now, employees=[person],
                    tasks=tasks, warnings=['Synthetic demonstration only; no live account, employee, native receipt, model or Send.'],
                    profiles={ident: profile}, workOverview=work)
    return snapshot, sources


def seed(destination):
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('new directory required; do not overwrite an instance')
    files = read_example()
    state = json.loads(files.get('STATE.json', '{}'))
    if state.get('example', {}).get('synthetic') is not True or state.get('channels') != {} or any(state.get('receipts', {}).get(k) != [] for k in ['system_onboarding', 'deliveries']):
        raise ValueError('bundled synthetic example required, with no live channels or native receipts')
    destination.mkdir(parents=True, exist_ok=False)
    # Resolve only after creation, so a user-selected parent alias works with the
    # existing workbook module's canonical directory contract.
    destination = destination.resolve()
    try:
        employee = destination / 'employee'
        _copy_example(files, employee)
        workbook.operate(employee, 'refresh', True)
        workbook.operate(employee, 'check', False)
        rows, _ = workbook.collect(employee)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rev = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-abcdef'
        snapshot, sources = _projection(employee, rows, now)
        publish(destination / 'live', snapshot, sources, rev)
        atomic_json(destination / 'live/status.json', dict(collectorState='synthetic-only'))
        atomic_json(destination / 'installation.example.json', dict(version=1, modules={}, identities={}, paths=dict(monitor_workspace='.')))
        return dict(destination=str(destination), synthetic=True, revision=rev, workNotes=len(rows), employeeRegistered=False, messagesSent=0)
    except BaseException:
        # The destination did not exist before this call; never remove its parent
        # or any other instance. Preserve the original exception.
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output', help='NEW synthetic output directory; no production default')
    args = parser.parse_args()
    if not args.output:
        if args.execute:
            parser.error('--output is required and must be a new directory')
        parser.print_help()
        return
    if not args.execute:
        print(json.dumps(dict(execute=False, synthetic=True, output=str(Path(args.output).expanduser().absolute()),
                              employeeRegistered=False, messagesSent=0)))
        return
    print(json.dumps(seed(args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()
