#!/usr/bin/env python3
"""Thin entry for the bounded visual AUP desktop tool, not a messaging dispatcher."""
import runpy, sys
from pathlib import Path
if __name__=='__main__':
    if 'start' in sys.argv and '--execute' in sys.argv:
        sys.path.insert(0,str(Path(__file__).resolve().parent))
        from ownership import check_from_env
        check_from_env()
    source = Path(__file__).resolve().parents[4] / 'components/wechat-linux'
    sys.path.insert(0, str(source))
    runpy.run_path(str(source / 'desktop_control.py'), run_name='__main__')
