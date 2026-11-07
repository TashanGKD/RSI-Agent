"""Pure service-unit template; installation belongs to an explicitly reviewed deployment."""
NAME='wechat-operations.service'
CODE='/opt/secretary-workbench/wechat'
STATE='/var/lib/secretary-wechat/operations-state'
def unit():
 return '''[Unit]
Description=Explicit queued official WeChat operations
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory='''+CODE+'''
ExecStart=/usr/bin/python3 -m operations.cli run --execute --root '''+STATE+''' --config '''+STATE+'''/config.json --seconds 3600
Restart=always
RestartSec=5
UMask=0077
NoNewPrivileges=yes
TimeoutStopSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
'''
if __name__=='__main__':
 print('Template only; deployment is not automatically installed. Import unit() to inspect.')
