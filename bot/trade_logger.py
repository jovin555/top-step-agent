"""
Logs every signal and resolves WIN/LOSS/BREAKEVEN by checking if price hit
take_profit, partial_exit_tp, or stop_loss since the signal was issued.

Partial-exit flow:
  1. When price reaches partial_exit_tp, half the position exits and
     trailing_sl is moved to entry (breakeven).
  2. If price then hits the (now breakeven) trailing_sl → BREAKEVEN, pnl=0.
  3. If price reaches take_profit → WIN.
  4. If price hits stop_loss before partial exit → LOSS.

Trades are stored in data/trades.json. Stats are computed on demand.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR    = Path(__file__).parent.parent / "data"
TRADES_FILE = DATA_DIR / "trades.json"
OPEN_EXPIRY_HOURS = 24


def _load() -> list:
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(trades: list):
    DATA_DIR.mkdir(exist_ok=True)
    TRADES_FILE.write_text(json.dumps(trades, indent=2))


def log_signal(symbol: str, timeframe: str, signal: dict, current_price: float) -> str:
    trades   = _load()
    trade_id = f"{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    trade = {
        "id":               trade_id,
        "symbol":           symbol,
        "timeframe":        timeframe,
        "direction":        signal["direction"],
        "entry":            signal["entry"],
        "stop_loss":        signal["stop_loss"],
        "partial_exit_tp":  signal.get("partial_exit_tp"),
        "take_profit":      signal["take_profit"],
        "risk_reward":      signal.get("risk_reward", 0),
        "win_probability":  signal.get("win_probability", 0),
        "confidence":       signal.get("confidence", ""),
        "reasoning":        signal.get("reasoning", ""),
        "contracts":        signal.get("contracts", 1),
        "price_at_signal":  current_price,
        "opened_at":        datetime.now(timezone.utc).isoformat(),
        # mutable resolution fields
        "trailing_sl":      signal["stop_loss"],   # starts at original SL
        "partial_exited":   False,
        "closed_at":        None,
        "outcome":          "OPEN",
        "close_price":      None,
        "pnl_points":       None,
    }
    trades.append(trade)
    _save(trades)
    return trade_id


def resolve_open_trades(snapshots: dict) -> list:
    """
    Check each OPEN trade against latest prices.
    snapshots: {symbol: current_price}
    Returns list of newly resolved trades.
    """
    trades   = _load()
    resolved = []
    now      = datetime.now(timezone.utc)

    for t in trades:
        if t["outcome"] != "OPEN":
            continue

        price = snapshots.get(t["symbol"])
        if price is None:
            continue

        opened_at = datetime.fromisoformat(t["opened_at"])
        age_hours = (now - opened_at).total_seconds() / 3600
        direction = t["direction"]
        tp        = t["take_profit"]
        sl        = t["stop_loss"]
        partial_tp = t.get("partial_exit_tp")

        # ── Partial-exit check: move trailing_sl to breakeven ─────────────
        if partial_tp and not t.get("partial_exited"):
            hit_partial = (
                (direction == "LONG"  and price >= partial_tp) or
                (direction == "SHORT" and price <= partial_tp)
            )
            if hit_partial:
                t["partial_exited"] = True
                t["trailing_sl"]    = t["entry"]   # stop-to-breakeven

        # Use the trailing stop (breakeven after partial exit, else original SL)
        effective_sl = t.get("trailing_sl") or sl
        outcome      = None

        if direction == "LONG":
            if price >= tp:
                outcome = "WIN"
            elif price <= effective_sl:
                outcome = "BREAKEVEN" if t.get("partial_exited") else "LOSS"
        elif direction == "SHORT":
            if price <= tp:
                outcome = "WIN"
            elif price >= effective_sl:
                outcome = "BREAKEVEN" if t.get("partial_exited") else "LOSS"

        if outcome is None and age_hours >= OPEN_EXPIRY_HOURS:
            outcome = "EXPIRED"

        if outcome:
            entry = t["entry"]
            t["outcome"]     = outcome
            t["closed_at"]   = now.isoformat()
            t["close_price"] = price
            if outcome == "WIN":
                t["pnl_points"] = round(
                    price - entry if direction == "LONG" else entry - price, 4
                )
            elif outcome == "LOSS":
                t["pnl_points"] = round(
                    price - entry if direction == "LONG" else entry - price, 4
                )
            elif outcome == "BREAKEVEN":
                t["pnl_points"] = 0.0
            resolved.append(t)

    _save(trades)
    return resolved


def get_stats() -> dict:
    trades    = _load()
    closed    = [t for t in trades if t["outcome"] in ("WIN", "LOSS", "BREAKEVEN")]
    open_     = [t for t in trades if t["outcome"] == "OPEN"]
    expired   = [t for t in trades if t["outcome"] == "EXPIRED"]
    wins      = [t for t in closed if t["outcome"] == "WIN"]
    losses    = [t for t in closed if t["outcome"] == "LOSS"]
    breakevens = [t for t in closed if t["outcome"] == "BREAKEVEN"]

    total_pnl = sum(t["pnl_points"] for t in closed if t["pnl_points"] is not None)
    win_rate  = (len(wins) / len(closed) * 100) if closed else 0

    symbols = {}
    for t in closed:
        sym = t["symbol"]
        if sym not in symbols:
            symbols[sym] = {"wins": 0, "losses": 0, "breakevens": 0, "pnl": 0.0}
        symbols[sym]["pnl"] += t["pnl_points"] or 0
        if t["outcome"] == "WIN":
            symbols[sym]["wins"] += 1
        elif t["outcome"] == "LOSS":
            symbols[sym]["losses"] += 1
        else:
            symbols[sym]["breakevens"] += 1

    return {
        "total_signals": len(trades),
        "open":          len(open_),
        "closed":        len(closed),
        "wins":          len(wins),
        "losses":        len(losses),
        "breakevens":    len(breakevens),
        "expired":       len(expired),
        "win_rate":      round(win_rate, 1),
        "total_pnl_pts": round(total_pnl, 2),
        "by_symbol":     symbols,
        "recent":        sorted(trades, key=lambda x: x["opened_at"], reverse=True)[:5],
    }


def get_signals_last_24h() -> list:
    """Return trades opened in the last 24 hours, newest first."""
    from datetime import timedelta
    trades  = _load()
    cutoff  = datetime.now(timezone.utc) - timedelta(hours=24)
    recent  = [t for t in trades if datetime.fromisoformat(t["opened_at"]) >= cutoff]
    return sorted(recent, key=lambda x: x["opened_at"], reverse=True)


def format_stats_message(stats: dict) -> str:
    win_emoji = "🟢" if stats["win_rate"] >= 60 else "🟡" if stats["win_rate"] >= 50 else "🔴"
    pnl_emoji = "📈" if stats["total_pnl_pts"] >= 0 else "📉"

    lines = [
        "📊 *TopStep Signal Bot — Trade Statistics*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📋 Total Signals : `{stats['total_signals']}`",
        f"🔓 Open          : `{stats['open']}`",
        f"✅ Wins          : `{stats['wins']}`",
        f"❌ Losses        : `{stats['losses']}`",
        f"🔄 Breakevens    : `{stats['breakevens']}`",
        f"⏳ Expired       : `{stats['expired']}`",
        f"{win_emoji} Win Rate       : `{stats['win_rate']}%`",
        f"{pnl_emoji} Total P&L (pts): `{stats['total_pnl_pts']}`",
    ]

    if stats["by_symbol"]:
        lines.append("\n*By Symbol:*")
        for sym, s in stats["by_symbol"].items():
            total    = s["wins"] + s["losses"] + s.get("breakevens", 0)
            wr       = round(s["wins"] / total * 100) if total else 0
            pnl_sign = "+" if s["pnl"] >= 0 else ""
            be_str   = f" / {s['breakevens']}BE" if s.get("breakevens") else ""
            lines.append(
                f"  • *{sym}*: {s['wins']}W / {s['losses']}L{be_str} ({wr}%) | "
                f"PnL: `{pnl_sign}{round(s['pnl'],1)} pts`"
            )

    if stats["recent"]:
        lines.append("\n*Last 5 Signals:*")
        for t in stats["recent"]:
            icon    = {"WIN": "✅", "LOSS": "❌", "OPEN": "🔓",
                       "EXPIRED": "⏳", "BREAKEVEN": "🔄"}.get(t["outcome"], "❓")
            opened  = t["opened_at"][:16].replace("T", " ")
            pnl_str = (
                f" | {'+' if (t['pnl_points'] or 0) >= 0 else ''}{t['pnl_points']} pts"
                if t["pnl_points"] is not None else ""
            )
            lines.append(f"  {icon} {t['symbol']} {t['direction']} @ {t['entry']} ({opened}){pnl_str}")

    return "\n".join(lines)
