#!/bin/bash
set -euo pipefail
umask 077
test "$(id -u)" = 0
test -f /opt/rsi-wechat-setup/owned
test "$(dpkg --print-architecture)" = amd64
case "$(grep '^VERSION_ID=' /etc/os-release)" in VERSION_ID=\"24.04\") ;; *) exit 2 ;; esac
test -S /mnt/wslg/.X11-unix/X0
if [ ! -x /usr/bin/wechat ]; then
    export DEBIAN_FRONTEND=noninteractive
    apt_options=(-o Acquire::Retries=0 -o Acquire::http::Timeout=12 -o Acquire::Languages=none)
    if ! apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update; then
        mirror=$(mktemp /run/rsi-wechat-apt.XXXXXXXX.list)
        trap 'rm -f -- "$mirror"' EXIT
        chmod 0644 "$mirror"
        for pocket in noble noble-updates noble-security; do
            printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://mirrors.tuna.tsinghua.edu.cn/ubuntu/ %s main universe\n' "$pocket"
        done >"$mirror"
        apt_options+=(-o "Dir::Etc::sourcelist=$mirror" -o Dir::Etc::sourceparts=-)
        apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
    fi
    apt-get "${apt_options[@]}" -y --no-install-recommends install \
        ca-certificates curl dbus-x11 fonts-noto-cjk x11-utils \
        libatomic1 libglib2.0-0t64 libudev1 libnss3 libxkbcommon-x11-0 \
        libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-render-util0 libxcb-xinerama0 libxcb-randr0 libxcb-shape0 \
        libxcb-xfixes0 libasound2t64 libpulse0 libegl1 libgbm1 libgl1 xdg-utils \
        libatk-bridge2.0-0t64 libxdamage1 libxfixes3 libcairo2 libpango-1.0-0 \
        libcups2t64 libwayland-egl1
    printf '%s  %s\n' a0db8caeee8d1e6cfe0aa5ce58710270f8d74a90ff4920f53a3fc22aa0956fe9 "$1" | sha256sum --check --status
    dpkg --install "$1"
    apt-get clean
fi
test "$(dpkg-query -W -f='${Version}' wechat)" = 4.1.13.26
printf '%s  %s\n' 2749535f299ba67feb8ef80cab898bb0531fa8f376b16f8a72db706811c84132 /opt/wechat/wechat | sha256sum --check --status
id wechat-gui >/dev/null 2>&1 || useradd --create-home --shell /bin/sh wechat-gui
install -d -o wechat-gui -g wechat-gui -m 0700 /run/rsi-wechat-setup
