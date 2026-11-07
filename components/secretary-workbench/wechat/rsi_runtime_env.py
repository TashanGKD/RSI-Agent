"""Installation-specific display settings shared by all native WeChat helpers."""
import os
from pathlib import Path


def display():
    return os.environ.get('WECHAT_DISPLAY', ':97')


def xauthority(root):
    return os.environ.get('WECHAT_XAUTHORITY', str(Path(root) / 'Xauthority'))
