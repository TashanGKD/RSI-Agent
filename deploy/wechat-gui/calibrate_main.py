"""Return a freshly started official main window to the sender's 905x667 layout.

WeChat 4.1.13.26 usually opens its main window at 880x640, but after a restart it
can also reopen at a size close to the calibrated one (for example 903x667). Only
the official main window at the default size, or within a small margin of the
calibrated size, is resized; the login window and chat pop-outs are left alone.

After a restart the resized main window may never receive focus. The sender
requires an active official window, so every send then stops before input with
UNSUPPORTED_LAYOUT. When no window holds focus, the unique calibrated main
window is activated; a focused chat pop-out or dialog is never taken over.
"""
import re
import shutil
import subprocess
import time

DEFAULT = (880, 640)
CALIBRATED = (905, 667)
NEAR = 40
PATTERN = re.compile(r'^\s*(0x[0-9a-fA-F]+) "Weixin": \("wechat" "wechat"\)\s+(\d+)x(\d+)', re.M)
ACTIVE = re.compile(r'window id # (0x[0-9a-fA-F]+)')


def default_main_windows(tree):
    selected = []
    for window, width, height in PATTERN.findall(tree):
        size = (int(width), int(height))
        near = all(abs(a - b) <= NEAR for a, b in zip(size, CALIBRATED))
        if size == DEFAULT or (near and size != CALIBRATED):
            selected.append(window)
    return selected


def active_window(xprop_output):
    """Return the focused window id, or None when the root reports no focus."""
    match = ACTIVE.search(xprop_output)
    return match.group(1) if match and int(match.group(1), 16) else None


def main_window_to_focus(tree, active):
    if active:
        return None
    mains = [window for window, width, height in PATTERN.findall(tree)
             if (int(width), int(height)) == CALIBRATED]
    return mains[0] if len(mains) == 1 else None


def main():
    if shutil.which('xdotool') is None or shutil.which('xwininfo') is None:
        return
    can_read_focus = shutil.which('xprop') is not None
    while True:
        tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True).stdout
        for window in default_main_windows(tree):
            subprocess.run(['xdotool', 'windowsize', window, str(CALIBRATED[0]), str(CALIBRATED[1])])
        if can_read_focus:
            focus = subprocess.run(['xprop', '-root', '_NET_ACTIVE_WINDOW'], capture_output=True, text=True).stdout
            window = main_window_to_focus(tree, active_window(focus))
            if window:
                subprocess.run(['xdotool', 'windowactivate', window])
        time.sleep(3)


if __name__ == '__main__':
    main()
