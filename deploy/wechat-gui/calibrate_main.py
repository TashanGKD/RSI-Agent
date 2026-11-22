"""Return a freshly started official main window to the sender's 905x667 layout.

WeChat 4.1.13.26 usually opens its main window at 880x640, but after a restart it
can also reopen at a size close to the calibrated one (for example 903x667). Only
the official main window at the default size, or within a small margin of the
calibrated size, is resized; the login window and chat pop-outs are left alone.
"""
import re
import shutil
import subprocess
import time

DEFAULT = (880, 640)
CALIBRATED = (905, 667)
NEAR = 40
PATTERN = re.compile(r'^\s*(0x[0-9a-fA-F]+) "Weixin": \("wechat" "wechat"\)\s+(\d+)x(\d+)', re.M)


def default_main_windows(tree):
    selected = []
    for window, width, height in PATTERN.findall(tree):
        size = (int(width), int(height))
        near = all(abs(a - b) <= NEAR for a, b in zip(size, CALIBRATED))
        if size == DEFAULT or (near and size != CALIBRATED):
            selected.append(window)
    return selected


def main():
    if shutil.which('xdotool') is None or shutil.which('xwininfo') is None:
        return
    while True:
        tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True).stdout
        for window in default_main_windows(tree):
            subprocess.run(['xdotool', 'windowsize', window, str(CALIBRATED[0]), str(CALIBRATED[1])])
        time.sleep(3)


if __name__ == '__main__':
    main()
