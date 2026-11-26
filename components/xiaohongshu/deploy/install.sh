#!/bin/sh
# Install Google Chrome and run it for Xiaohongshu as a separate user on a private display.
# Run as root inside the WSL distribution. Re-running keeps the existing login profile.
set -e
here=$(dirname "$0")
export DEBIAN_FRONTEND=noninteractive
if ! command -v google-chrome >/dev/null; then
  curl -fsSL -o /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get update -qq
  apt-get install -y -qq /tmp/google-chrome.deb fonts-noto-cjk xvfb
fi
command -v Xvfb >/dev/null || apt-get install -y -qq xvfb
id xhs-browser >/dev/null 2>&1 || useradd -m -s /usr/sbin/nologin xhs-browser
install -m 0644 "$here/rsi-xhs-display.service" "$here/rsi-xhs-browser.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now rsi-xhs-display.service rsi-xhs-browser.service
systemctl is-active rsi-xhs-display.service rsi-xhs-browser.service
