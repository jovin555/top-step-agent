import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

from clients.deepseek import DeepseekClient
from clients.telegram import TelegramClient
from bot.strategy import build_signal_prompt, parse_signal, format_signal_message
from bot.market_data import get_market_snapshot
from bot.trade_logger import log_signal, resolve_open_trades, get_stats, format_stats_message

SYMBOLS = ["ES", "NQ", "CL", "GC"]
STATS_EVERY_N_SCANS = 10

_COUNTER_FILE = __file__.replace("scanner.py", "") + "../../data/.scan_count"


def _read_scan_count() -> int:
    try:
        return int(open(_COUNTER_FILE).read().strip())
    except Exception:
        return 0


def _write_scan_count(n: int):
    try:
        open(_COUNTER_FILE, "w").write(str(n))
    except Exception:
        pass


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

    # ── Scan summary ─────────────────────────────────────────────────────
    summary = [f"🔍 *TopStep Market Scan* — `{timestamp}`\n"]

    if results:
        sorted_results = sorted(results, key=lambda x: x[2].get("win_probability", 0), reverse=True)
        for sym, snap, sig in sorted_results:
            emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
            summary.append(f"{emoji} *{sym}*: {sig['direction']} | {sig.get('win_probability','?')}% | {sig.get('confidence','?')}")

    for sym in no_trades:
        summary.append(f"⚪ *{sym}*: NO_TRADE")

    if results:
        best_symbol, best_snapshot, best_signal = sorted_results[0]
        summary.append(f"\n🏆 *Best setup: {best_symbol}* ({best_signal.get('win_probability','?')}% win probability)")
    else:
        summary.append("\n_No actionable setups found — waiting for better conditions._")

    telegram.send_message("\n".join(summary))

    # ── Best signal card + log ────────────────────────────────────────────
    if results:
        best_symbol, best_snapshot, best_signal = sorted_results[0]
        telegram.send_message(
            format_signal_message(best_symbol, timeframe, best_signal, best_snapshot["current_price"])
        )
        trade_id = log_signal(best_symbol, timeframe, best_signal, best_snapshot["current_price"])
        print(f"\nSignal sent & logged: {best_symbol} {best_signal['direction']} "
              f"({best_signal.get('win_probability')}%) — ID: {trade_id}")
    else:
        print("\nNo actionable signals found.")

    # ── Periodic stats ────────────────────────────────────────────────────
    scan_count = _read_scan_count() + 1
    _write_scan_count(scan_count)
    if scan_count % STATS_EVERY_N_SCANS == 0:
        stats = get_stats()
        if stats["total_signals"] > 0:
            telegram.send_message(format_stats_message(stats))
            print(f"Stats report sent (scan #{scan_count}).")
