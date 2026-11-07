#!/usr/bin/env python3
"""Thin entry for the bounded visual AUP desktop tool, not a messaging dispatcher."""
import runpy, sys
from pathlib import Path
if __name__=='__main__':
    if 'start' in sys.argv and '--execute' in sys.argv:
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from ownership import check_from_env
        check_from_env()
    runpy.run_path(str(Path(__file__).resolve().parents[2]/'wechat/desktop_control.py'),run_name='__main__')
