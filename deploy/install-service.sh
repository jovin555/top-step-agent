#!/bin/bash
# Install crypto-signals-bot as a system-wide service (requires sudo).
# Usage: sudo bash deploy/install-service.sh

set -e

cat > /etc/systemd/system/crypto-signals-bot.service << 'EOF'
[Unit]
Description=Crypto Signal Scanner Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=eva
WorkingDirectory=/home/eva/workspace/crypto_agent
ExecStart=/usr/bin/python3 /home/eva/workspace/crypto_agent/main.py 15
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=crypto-signals-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable crypto-signals-bot
systemctl restart crypto-signals-bot
systemctl status crypto-signals-bot --no-pager

echo ""
echo "Done. Commands:"
echo "  systemctl status crypto-signals-bot"
echo "  systemctl restart crypto-signals-bot"
echo "  journalctl -u crypto-signals-bot -f"
