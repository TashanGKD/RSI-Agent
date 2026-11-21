#!/bin/sh
umask 077
/usr/bin/openbox &
/usr/bin/python3 "$(dirname "$0")/calibrate_main.py" &
exec /usr/bin/wechat
