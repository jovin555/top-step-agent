import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

from clients.deepseek import DeepseekClient
from clients.telegram import TelegramClient
from bot.strategy import build_signal_prompt, parse_signal, format_signal_message
from bot.market_data import get_market_snapshot
from bot.trade_logger import (
    log_signal, resolve_open_trades, get_stats,
    format_stats_message, get_signals_last_24h,
)

SYMBOLS = ["ES", "NQ", "CL", "GC", "SI", "NG", "YM", "HG", "ZN", "6E", "6J", "6B"]

_DATA_DIR          = Path(__file__).parent.parent / "data"
_LAST_SUMMARY_FILE = _DATA_DIR / ".last_daily_summary"


def _get_last_summary_time():
    try:
        return datetime.fromisoformat(_LAST_SUMMARY_FILE.read_text().strip())
    except Exception:
        return None


def _set_last_summary_time(dt: datetime):
    try:
        _DATA_DIR.mkdir(exist_ok=True)
        _LAST_SUMMARY_FILE.write_text(dt.isoformat())
    except Exception:
        pass


def _should_send_daily_summary() -> bool:
    last = _get_last_summary_time()
    if last is None:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() >= 86400


def _format_daily_summary(signals_24h: list, stats: dict) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📅 *TopStep Daily Summary* — `{timestamp}`\n"]

    if signals_24h:
        lines.append("*Signals in the last 24h:*")
        for t in signals_24h:
            icon = {"WIN": "✅", "LOSS": "❌", "OPEN": "🔓", "EXPIRED": "⏳"}.get(t["outcome"], "❓")
            emoji = "🟢" if t["direction"] == "LONG" else "🔴"
            pnl_str = (
                f" | {'+' if (t['pnl_points'] or 0) >= 0 else ''}{t['pnl_points']} pts"
                if t["pnl_points"] is not None else ""
            )
            lines.append(
                f"  {icon}{emoji} *{t['symbol']}* {t['direction']} @ `{t['entry']}` "
                f"({t['win_probability']}%){pnl_str}"
            )
    else:
        lines.append("_No signals generated in the last 24 hours._")

    lines.append("")
    lines.append("*Overall Stats:*")
    win_emoji = "🟢" if stats["win_rate"] >= 60 else "🟡" if stats["win_rate"] >= 50 else "🔴"
    pnl_emoji = "📈" if stats["total_pnl_pts"] >= 0 else "📉"
    lines.append(f"  {win_emoji} Win Rate : `{stats['win_rate']}%` ({stats['wins']}W / {stats['losses']}L)")
    lines.append(f"  {pnl_emoji} Total P&L: `{stats['total_pnl_pts']} pts`")
    lines.append(f"  📋 Total Signals: `{stats['total_signals']}`")

    return "\n".join(lines)


def run():
    load_dotenv()

    telegram_token   = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHANNEL_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not telegram_token or not telegram_chat_id:
        print("Missing Telegram settings in .env", file=sys.stderr)
        sys.exit(1)

    llm_api_key = os.getenv("LLM_API_KEY")
    if not llm_api_key:
        print("Missing LLM_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    timeframe = os.getenv("TIMEFRAME", "15m")

    client = DeepseekClient(
        provider        = os.getenv("LLM_PROVIDER", "deepseek"),
        api_key         = llm_api_key,
        model           = os.getenv("LLM_MODEL", "deepseek-chat"),
        backup_provider = os.getenv("LLM_BACKUP_PROVIDER"),
        backup_api_key  = os.getenv("LLM_BACKUP_API_KEY"),
        backup_model    = os.getenv("LLM_BACKUP_MODEL"),
    )
    telegram  = TelegramClient(telegram_token, telegram_chat_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n=== TopStep Signal Scanner | {timestamp} ===")

    snapshots = {}
    results   = []
    no_trades = []

    for symbol in SYMBOLS:
        try:
            print(f"Analyzing {symbol}...")
            snapshot          = get_market_snapshot(symbol, timeframe)
            snapshots[symbol] = snapshot["current_price"]
            prompt            = build_signal_prompt(symbol, timeframe, snapshot)
            response          = client.chat(prompt)
            signal            = parse_signal(response)

            if signal is None:
                print(f"  {symbol}: could not parse LLM response")
                no_trades.append(symbol)
                continue

            if signal.get("direction") == "NO_TRADE":
                print(f"  {symbol}: NO_TRADE")
                no_trades.append(symbol)
            else:
                prob = signal.get("win_probability", 0)
                print(f"  {symbol}: {signal['direction']} | prob={prob}% | conf={signal.get('confidence')}")
                results.append((symbol, snapshot, signal))

        except Exception as e:
            print(f"  {symbol} error: {e}")
            no_trades.append(symbol)

    # ── Resolve open trades ───────────────────────────────────────────────
    resolved = resolve_open_trades(snapshots)
    for t in resolved:
        icon = "✅ WIN" if t["outcome"] == "WIN" else "❌ LOSS" if t["outcome"] == "LOSS" else "⏳ EXPIRED"
        pnl  = (
            f" ({'+' if (t['pnl_points'] or 0) >= 0 else ''}{t['pnl_points']} pts)"
            if t["pnl_points"] is not None else ""
        )
        telegram.send_message(
            f"{icon} — *{t['symbol']} {t['direction']}*{pnl}\n"
            f"Entry: `{t['entry']}` → Close: `{t['close_price']}`\n"
            f"TP: `{t['take_profit']}` | SL: `{t['stop_loss']}`"
        )
        print(f"  Resolved: {t['symbol']} {t['direction']} → {t['outcome']}{pnl}")

    # ── Send signal card only when a signal exists ────────────────────────
    if results:
        sorted_results = sorted(results, key=lambda x: x[2].get("win_probability", 0), reverse=True)
        best_symbol, best_snapshot, best_signal = sorted_results[0]
        telegram.send_message(
            format_signal_message(best_symbol, timeframe, best_signal, best_snapshot["current_price"])
        )
        trade_id = log_signal(best_symbol, timeframe, best_signal, best_snapshot["current_price"])
        print(f"\nSignal sent & logged: {best_symbol} {best_signal['direction']} "
              f"({best_signal.get('win_probability')}%) — ID: {trade_id}")
    else:
        print("\nNo actionable signals found — no Telegram message sent.")

    # ── 24-hour daily summary ─────────────────────────────────────────────
    if _should_send_daily_summary():
        signals_24h = get_signals_last_24h()
        stats       = get_stats()
        if stats["total_signals"] > 0 or signals_24h:
            telegram.send_message(_format_daily_summary(signals_24h, stats))
        _set_last_summary_time(datetime.now(timezone.utc))
        print("Daily summary sent.")
