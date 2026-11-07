#!/usr/bin/env python3
"""Explicit isolated fixture suites. No arguments print help; no live source tests."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=['test_http','test_package_safe_defaults','test_access','test_notebook','test_local_notebook','test_source_tools','test_schedule','test_schedule_http','test_notebook_http','test_tool_http','test_foundation_review','test_foundation_quality','test_notebook_fields','test_local_sources','test_local_independence','test_tool_foundations','test_online_server','test_work','test_work_http','test_secretary_v43']
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['notebook','wechat','clawbot','node','audit','recording','reader','package','host','continuity','monitor','monitor-web']);p.add_argument('--execute',action='store_true');a=p.parse_args()
 if not a.execute or not a.suite:p.print_help();return 0
 if a.suite in ['continuity','monitor']:
  folder=ROOT/('host/continuity' if a.suite=='continuity' else 'monitor/backend')
  return subprocess.call([sys.executable,'-m','unittest','discover','-s',str(folder)],cwd=ROOT)
 if a.suite=='monitor-web':return subprocess.call(['npm','test'],cwd=ROOT/'monitor/web')
 if a.suite=='reader':return subprocess.call([sys.executable,'-m','unittest','discover','-s','reader-tests','-p','test_*.py'],cwd=ROOT/'wechat')
 if a.suite=='package':return subprocess.call([sys.executable,'-m','unittest','discover','-s','scripts/tests','-p','test_*.py'],cwd=ROOT)
 if a.suite=='host':return subprocess.call(['node','--test',str(ROOT/'host/tests/test_collaboration.mjs'),str(ROOT/'host/tests/test_queue_closeout.mjs')],cwd=ROOT)
 if a.suite=='node':return subprocess.call(['node','--test',*[str(x) for x in sorted((ROOT/'clawbot/tests').glob('*.mjs'))]],cwd=ROOT)
 if a.suite=='notebook':
  code="import sys,unittest;sys.path.insert(0,'tests');s=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in "+repr(NOTEBOOK)+");r=unittest.TextTestRunner().run(s);sys.exit(not r.wasSuccessful())";cwd=ROOT/'notebook'
 else:
  cwd=ROOT/{'wechat':'wechat','clawbot':'clawbot','audit':'skills/personal-action-audit','recording':'skills/tencent-recording-archive'}[a.suite];pattern='test_operations*.py' if a.suite=='wechat' else 'test_*.py';code="import unittest,sys;s=unittest.defaultTestLoader.discover('tests',pattern="+repr(pattern)+");r=unittest.TextTestRunner().run(s);sys.exit(not r.wasSuccessful())"
 return subprocess.call([sys.executable,'-c',code],cwd=cwd)
if __name__=='__main__':raise SystemExit(main())
