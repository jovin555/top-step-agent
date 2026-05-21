import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

from clients.deepseek import DeepseekClient
from clients.telegram import TelegramClient
from bot.strategy import build_signal_prompt, parse_signal, format_signal_message
from bot.market_data import get_market_snapshot, get_htf_ema200
from bot.trade_logger import (
    log_signal, resolve_open_trades, get_stats,
    format_stats_message, get_signals_last_24h,
)

SYMBOLS = ["ES", "NQ", "CL", "GC", "SI", "NG", "YM", "HG", "ZN", "6E", "6J", "6B"]

# Dollar value of a 1-unit price move per contract for each instrument.
# Used to compute ATR-based position sizing (1% account risk rule).
TICK_VALUES = {
    "ES":  50.0,        # $50 per index point
    "NQ":  20.0,        # $20 per index point
    "YM":  5.0,         # $5 per index point
    "CL":  1000.0,      # $1000 per $1/barrel (1000 barrels)
    "GC":  100.0,       # $100 per $1/oz (100 troy oz)
    "SI":  5000.0,      # $5000 per $1/oz (5000 troy oz)
    "NG":  10000.0,     # $10000 per $1/MMBtu (10000 MMBtu)
    "HG":  25000.0,     # $25000 per $1/lb (25000 lbs)
    "ZN":  1000.0,      # $1000 per full point
    "6E":  125000.0,    # $125000 per $1 (125000 EUR)
    "6J":  12500000.0,  # $12.5M per $1 (12.5M JPY)
    "6B":  62500.0,     # $62500 per $1 (62500 GBP)
}

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
            icon = {"WIN": "✅", "LOSS": "❌", "OPEN": "🔓", "EXPIRED": "⏳",
                    "BREAKEVEN": "🔄"}.get(t["outcome"], "❓")
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


def get_position_size(symbol: str, atr: float, account_equity: float, risk_pct: float = 0.01) -> int:
    """
    ATR-based position sizing capped at 1% account risk.
    Stop is set at 2× ATR; we find how many contracts keep dollar risk ≤ account_equity × risk_pct.
    Returns at least 1 (minimum tradeable size).
    """
    tick_value    = TICK_VALUES.get(symbol.upper(), 100.0)
    stop_distance = atr * 2.0
    dollar_risk   = account_equity * risk_pct
    contracts     = int(dollar_risk / (stop_distance * tick_value))
    return max(1, contracts)


def check_signal_confirmation(snapshot: dict, signal: dict) -> tuple[bool, int, list]:
    """
    2-of-3 confirmation gate before a signal is accepted.

    Criteria:
      1. RSI alignment  — RSI > 45 for LONG, < 55 for SHORT
      2. EMA20 alignment — price above EMA20 for LONG, below for SHORT
      3. Volume surge   — current volume > 130% of 20-bar average

    Returns (confirmed, score, reasons).
    """
    direction = signal.get("direction", "NO_TRADE")
    score     = 0
    reasons   = []

    rsi   = snapshot["rsi_14"]
    price = snapshot["current_price"]
    ema20 = snapshot["ema_20"]

    if direction == "LONG":
        if rsi > 45:
            score += 1
            reasons.append(f"RSI bullish ({rsi:.1f} > 45)")
        if price > ema20:
            score += 1
            reasons.append(f"Price above EMA20 ({price} > {ema20})")
    elif direction == "SHORT":
        if rsi < 55:
            score += 1
            reasons.append(f"RSI bearish ({rsi:.1f} < 55)")
        if price < ema20:
            score += 1
            reasons.append(f"Price below EMA20 ({price} < {ema20})")

    if snapshot["volume_last"] > snapshot["volume_avg_20"] * 1.3:
        score += 1
        reasons.append(f"Volume surge ({snapshot['volume_last']} > 130% avg)")

    return score >= 2, score, reasons


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

    timeframe      = os.getenv("TIMEFRAME", "15m")
    account_equity = float(os.getenv("ACCOUNT_EQUITY", "50000"))

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

            # ── 1H higher-timeframe trend filter ──────────────────────────
            htf_trend = "UNKNOWN"
            try:
                htf_price, htf_ema200 = get_htf_ema200(symbol)
                htf_trend = "BULLISH" if htf_price > htf_ema200 else "BEARISH"
            except Exception as htf_err:
                print(f"  {symbol}: HTF fetch failed ({htf_err}), skipping trend filter")

            prompt   = build_signal_prompt(symbol, timeframe, snapshot, htf_trend)
            response = client.chat(prompt)
            signal   = parse_signal(response)

            if signal is None:
                print(f"  {symbol}: could not parse LLM response")
                no_trades.append(symbol)
                continue

            direction = signal.get("direction", "NO_TRADE")

            if direction == "NO_TRADE":
                print(f"  {symbol}: NO_TRADE")
                no_trades.append(symbol)
                continue

            # ── HTF counter-trend filter ───────────────────────────────────
            if htf_trend != "UNKNOWN":
                if direction == "LONG" and htf_trend == "BEARISH":
                    print(f"  {symbol}: LONG filtered — counter-trend to 1H BEARISH")
                    no_trades.append(symbol)
                    continue
                if direction == "SHORT" and htf_trend == "BULLISH":
                    print(f"  {symbol}: SHORT filtered — counter-trend to 1H BULLISH")
                    no_trades.append(symbol)
                    continue

            # ── 2-of-3 confirmation gate ───────────────────────────────────
            confirmed, conf_score, conf_reasons = check_signal_confirmation(snapshot, signal)
            if not confirmed:
                print(f"  {symbol}: {direction} filtered — only {conf_score}/3 confirmations "
                      f"({', '.join(conf_reasons) or 'none'})")
                no_trades.append(symbol)
                continue

            # ── ATR-based position sizing ──────────────────────────────────
            atr       = snapshot["atr_14"]
            contracts = get_position_size(symbol, atr, account_equity)
            signal["contracts"] = contracts

            prob = signal.get("win_probability", 0)
            print(f"  {symbol}: {direction} | prob={prob}% | conf={signal.get('confidence')} | "
                  f"contracts={contracts} | htf={htf_trend} | confirmations={conf_score}/3")
            results.append((symbol, snapshot, signal))

        except Exception as e:
            print(f"  {symbol} error: {e}")
            no_trades.append(symbol)

    # ── Resolve open trades ───────────────────────────────────────────────
    resolved = resolve_open_trades(snapshots)
    for t in resolved:
        icon = ("✅ WIN" if t["outcome"] == "WIN"
                else "❌ LOSS" if t["outcome"] == "LOSS"
                else "🔄 BREAKEVEN" if t["outcome"] == "BREAKEVEN"
                else "⏳ EXPIRED")
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
        print("\nNo actionable signals this scan (all filtered or NO_TRADE).")

    # ── 24-hour daily summary ─────────────────────────────────────────────
    if _should_send_daily_summary():
        signals_24h = get_signals_last_24h()
        stats       = get_stats()
        if stats["total_signals"] > 0 or signals_24h:
            telegram.send_message(_format_daily_summary(signals_24h, stats))
        _set_last_summary_time(datetime.now(timezone.utc))
        print("Daily summary sent.")
