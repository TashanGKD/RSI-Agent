"""Return a freshly started official main window to the sender's 905x667 layout.

WeChat 4.1.13.26 opens its main window at 880x640 after every start and does not
remember a resize. Only that exact official main window is resized.
"""
import re
import shutil
import subprocess
import time

DEFAULT = (880, 640)
CALIBRATED = (905, 667)
PATTERN = re.compile(r'^\s*(0x[0-9a-fA-F]+) "Weixin": \("wechat" "wechat"\)\s+(\d+)x(\d+)', re.M)


def default_main_windows(tree):
    return [window for window, width, height in PATTERN.findall(tree) if (int(width), int(height)) == DEFAULT]


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
