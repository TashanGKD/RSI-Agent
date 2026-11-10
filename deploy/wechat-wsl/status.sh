#!/bin/bash
set -euo pipefail

wait_seconds=${1:-0}
[[ $wait_seconds =~ ^[0-9]+$ ]] && (( wait_seconds <= 600 ))
export DISPLAY=${DISPLAY:-:0}
user=wechat-gui

status() {
    if ! id "$user" >/dev/null 2>&1; then
        echo 'login=not_installed'
        return
    fi
    mapfile -t pids < <(pgrep -u "$user" -x wechat || true)
    if (( ${#pids[@]} == 0 )); then
        echo 'login=client_stopped'
        return
    fi
    if (( ${#pids[@]} != 1 )) || [[ $(readlink "/proc/${pids[0]}/exe") != /opt/wechat/wechat ]]; then
        echo 'login=process_unrecognized'
        return
    fi
    local profile_count windows wid details shape main_seen=0
    profile_count=$(runuser -u "$user" -- find /home/wechat-gui/xwechat_files -maxdepth 2 -type d -name db_storage -printf x 2>/dev/null | wc -c || true)
    windows=$(xwininfo -root -tree 2>/dev/null | awk '/"Weixin":/ {print $1}' || true)
    for wid in $windows; do
        xprop -id "$wid" _NET_WM_PID 2>/dev/null | grep -Eq " = ${pids[0]}$" || continue
        details=$(xwininfo -id "$wid" 2>/dev/null) || continue
        grep -q 'Map State: IsViewable' <<<"$details" || continue
        shape=$(awk '/Width:/{w=$2} /Height:/{h=$2} END{print w "x" h}' <<<"$details")
        if [[ $shape == 280x380 ]]; then
            echo 'login=required'
            return
        fi
        if [[ $shape == 878x640 || $shape == 880x640 || $shape == 905x667 ]]; then
            main_seen=1
        fi
    done
    if (( main_seen && profile_count > 0 )); then
        printf 'login=desktop_open native_profile_count=%s\n' "$profile_count"
    else
        echo 'login=window_unrecognized'
    fi
}

deadline=$((SECONDS + wait_seconds))
while :; do
    result=$(status)
    case "$result" in
        login=desktop_open*|login=not_installed|login=process_unrecognized) break ;;
    esac
    (( SECONDS < deadline )) || break
    sleep 1
done
printf '%s\n' "$result"
