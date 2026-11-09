#!/bin/sh
# First start in a fresh Linux environment with an existing X11 session.
set -eu
umask 077

client_url=https://dldir1.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb
client_sha256=a0db8caeee8d1e6cfe0aa5ce58710270f8d74a90ff4920f53a3fc22aa0956fe9

if [ "$(id -u)" != 0 ] || [ "$(dpkg --print-architecture)" != amd64 ]; then
    echo 'Run as root in the amd64 Linux runtime.' >&2
    exit 1
fi
id wechat-gui >/dev/null
: "${DISPLAY:?Start the WeChat X11 session first}"

(
    flock -x 9
    if [ "$(dpkg-query -W -f='${db:Status-Status}' wechat 2>/dev/null || true)" = installed ] &&
        [ -x /usr/bin/wechat ]; then
        exit 0
    fi

    package=${RSI_WECHAT_DEB:-}
    if [ -z "$package" ]; then
        package=$(mktemp --suffix=.deb)
        trap 'rm -f -- "$package"' EXIT
        downloader=curl
        if [ -x /mnt/c/Windows/System32/curl.exe ]; then
            downloader=/mnt/c/Windows/System32/curl.exe
        fi
        "$downloader" --proto '=https' --fail --silent --show-error --connect-timeout 15 --max-time 300 "$client_url" >"$package"
    fi
    if ! printf '%s  %s\n' "$client_sha256" "$package" | sha256sum --check --status; then
        echo 'WeChat package differs from the reviewed 4.1.13.26 amd64 release.' >&2
        exit 1
    fi
    dpkg --install "$package"
) 9>/run/rsi-official-wechat.lock

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec runuser -u wechat-gui -- dbus-run-session -- /bin/sh "$here/session.sh"
