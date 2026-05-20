#!/bin/bash
# Install topstep-bot as a system-wide service (requires sudo).
# Usage: sudo bash deploy/install-service.sh

set -e

cat > /etc/systemd/system/topstep-bot.service << 'EOF'
[Unit]
Description=TopStep Signal Scanner Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=eva
WorkingDirectory=/home/eva/workspace/top_step_agent
ExecStart=/usr/bin/python3 /home/eva/workspace/top_step_agent/main.py 15
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=topstep-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable topstep-bot
systemctl restart topstep-bot
systemctl status topstep-bot --no-pager

echo ""
echo "Done. Commands:"
echo "  systemctl status topstep-bot"
echo "  systemctl restart topstep-bot"
echo "  journalctl -u topstep-bot -f"
