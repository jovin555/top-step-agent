"""
Print trade statistics to terminal and optionally send to Telegram.

Usage:
    python stats.py          # print to terminal
    python stats.py --send   # print + send to Telegram
"""
import sys
from dotenv import load_dotenv
import os

load_dotenv()

from bot.trade_logger import get_stats, format_stats_message, TRADES_FILE

stats = get_stats()

if stats["total_signals"] == 0:
    print("No trades logged yet.")
    sys.exit(0)

print(format_stats_message(stats).replace("*", "").replace("`", "").replace("_", ""))
print(f"\nTrades file: {TRADES_FILE}")

if "--send" in sys.argv:
    from clients.telegram import TelegramClient
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("TELEGRAM_CHAT_ID")
    TelegramClient(token, chat_id).send_message(format_stats_message(stats))
    print("Stats sent to Telegram.")
