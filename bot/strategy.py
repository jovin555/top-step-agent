import json
import re

SYSTEM_CONTEXT = (
    "You are an elite futures trader with 20+ years of experience covering ES, NQ, YM, CL, GC, SI, NG, HG, ZN, 6E, 6J, and 6B. "
    "You apply technical analysis strictly and only recommend trades with a clear edge. "
    "Stop loss must be placed exactly 2× ATR from entry. "
    "Partial take-profit (partial_exit_tp) must be placed at 1.5× ATR from entry. "
    "Full take-profit must be placed at 3× ATR from entry. "
    "You always respond in the exact JSON format requested — no extra text, no markdown fences."
)


def build_signal_prompt(symbol: str, timeframe: str, snap: dict, htf_trend: str = "UNKNOWN") -> str:
    trend       = "BULLISH" if snap["ema_20"] > snap["ema_50"] else "BEARISH"
    macro_trend = "ABOVE_200EMA" if snap["current_price"] > snap["ema_200"] else "BELOW_200EMA"

    vol_ratio = snap["volume_last"] / snap["volume_avg_20"] if snap["volume_avg_20"] else 1
    vol_tag   = " [HIGH VOLUME SURGE]" if vol_ratio >= 1.5 else ""
    vol_dry   = " [LOW VOLUME — weak conviction]" if vol_ratio < 1.0 else ""
    vol_pct   = f"{vol_ratio:.1f}x avg"

    price_vs_bb = (
        "NEAR_UPPER_BAND" if snap["current_price"] >= snap["bb_upper"] * 0.998
        else "NEAR_LOWER_BAND" if snap["current_price"] <= snap["bb_lower"] * 1.002
        else "MID_BAND"
    )

    rsi_tag = (
        " [OVERBOUGHT — LONG forbidden]" if snap["rsi_14"] >= 70
        else " [OVERSOLD — SHORT forbidden]" if snap["rsi_14"] <= 30
        else ""
    )

    macd_cross = (
        " [BULLISH CROSS]" if snap["macd_line"] > snap["macd_signal"] and snap["macd_histogram"] > 0
        else " [BEARISH CROSS]" if snap["macd_line"] < snap["macd_signal"] and snap["macd_histogram"] < 0
        else ""
    )

    candle_lines = "\n".join(
        f"  [{i+1}] O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}"
        for i, c in enumerate(snap["candles_last_5"])
    )

    htf_line = (
        f"\n1H Trend   : {htf_trend} [LONG only if BULLISH | SHORT only if BEARISH]"
        if htf_trend != "UNKNOWN" else ""
    )

    return f"""{SYSTEM_CONTEXT}

Analyze this {symbol} futures market and provide a precise trade signal or NO_TRADE.

=== MARKET SNAPSHOT ({timeframe} chart) ===
Price      : {snap['current_price']}  (H: {snap['current_high']}  L: {snap['current_low']})
RSI(14)    : {snap['rsi_14']}{rsi_tag}
EMA20      : {snap['ema_20']}  |  EMA50: {snap['ema_50']}  |  EMA200: {snap['ema_200']}
Trend (15m): {trend} | Macro: {macro_trend}{htf_line}
MACD       : Line={snap['macd_line']}  Signal={snap['macd_signal']}  Hist={snap['macd_histogram']}{macd_cross}
ATR(14)    : {snap['atr_14']}
BB         : Upper={snap['bb_upper']}  Lower={snap['bb_lower']}  Position={price_vs_bb}
Volume     : {snap['volume_last']} ({vol_pct}){vol_tag}{vol_dry}
S/R        : Support={snap['support']}  Resistance={snap['resistance']}

Last 5 candles (oldest → newest):
{candle_lines}

=== INSTRUCTIONS ===
- If no high-probability setup exists, output NO_TRADE. Most scans should be NO_TRADE.
- Prefer trades that align with the 1H trend direction; counter-trend trades require exceptional confluence.
- RSI FILTER: Do NOT go LONG if RSI(14) >= 70. Do NOT go SHORT if RSI(14) <= 30. Output NO_TRADE instead.
- VOLUME FILTER: Do not enter on below-average volume — weak conviction.
- stop_loss       : exactly 2.0 x ATR({snap['atr_14']}) from entry.
- partial_exit_tp : exactly 1.5 x ATR from entry (50% position exits here; stop then moves to breakeven).
- take_profit     : exactly 3.0 x ATR from entry (remaining 50% exits here).
- risk_reward     : calculate as (take_profit distance) / (stop_loss distance).
- win_probability : your honest estimate (0-100) based on technicals. Be conservative.
- HIGH confidence = trend + momentum + volume + S/R all aligned.

Respond with ONLY valid JSON -- no extra text, no markdown:
{{
  "direction": "LONG" | "SHORT" | "NO_TRADE",
  "entry": <number>,
  "stop_loss": <number>,
  "partial_exit_tp": <number>,
  "take_profit": <number>,
  "risk_reward": <float>,
  "win_probability": <integer 0-100>,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "reasoning": "<2-3 sentences: key confluences, why this setup, what invalidates it>"
}}"""


def parse_signal(response_text: str) -> dict | None:
    match = re.search(r'\{[\s\S]*\}', response_text)
    if not match:
        return None
    try:
        data = json.loads(match.group())
        if "direction" in data:
            data["direction"] = str(data["direction"]).upper()
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def format_signal_message(symbol: str, timeframe: str, signal: dict, price: float) -> str:
    direction = signal.get("direction", "NO_TRADE")
    if direction == "LONG":
        dir_emoji = "🟢"
    elif direction == "SHORT":
        dir_emoji = "🔴"
    else:
        dir_emoji = "⚪"

    conf       = signal.get("confidence", "LOW")
    conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💭"}.get(conf, "💭")
    contracts  = signal.get("contracts")
    size_str   = (
        f"\n📦 *Position Size:* `{contracts} contract{'s' if contracts != 1 else ''}`"
        if contracts else ""
    )

    return (
        f"{dir_emoji} *{symbol} — {direction}* {conf_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Timeframe:* `{timeframe}`\n"
        f"💰 *Current Price:* `{price}`\n"
        f"📈 *Entry:* `{signal.get('entry', 'N/A')}`\n"
        f"🛑 *Stop Loss (2xATR):* `{signal.get('stop_loss', 'N/A')}`\n"
        f"🔶 *Partial Exit (1.5xATR):* `{signal.get('partial_exit_tp', 'N/A')}` _(50% off)_\n"
        f"🎯 *Full Take Profit (3xATR):* `{signal.get('take_profit', 'N/A')}`\n"
        f"⚖️ *Risk/Reward:* `1:{signal.get('risk_reward', 'N/A')}`\n"
        f"🎲 *Win Probability:* `{signal.get('win_probability', 'N/A')}%`\n"
        f"🏆 *Confidence:* `{conf}`"
        f"{size_str}\n"
        f"\n"
        f"📝 *Analysis:*\n"
        f"_{signal.get('reasoning', '')}_\n"
        f"\n"
        f"⚠️ _Not financial advice. Trade at your own risk._"
    )
