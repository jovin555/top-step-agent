import json
import re

SYSTEM_CONTEXT = (
    "You are an elite crypto trader and technical analyst with deep expertise in Bitcoin, Ethereum, "
    "and altcoin markets. You trade 24/7 crypto spot and derivatives markets using pure technical analysis. "
    "You account for crypto-specific dynamics: high volatility, weekend gaps, liquidity clusters, "
    "and trend momentum across multiple timeframes. "
    "You only recommend trades with a clear edge and always respond in the exact JSON format "
    "requested — no extra text, no markdown fences."
)


def build_signal_prompt(symbol: str, timeframe: str, snap: dict, bias_1h: dict | None = None) -> str:
    trend = "BULLISH" if snap["ema_20"] > snap["ema_50"] else "BEARISH"
    macro_trend = "ABOVE_200EMA" if snap["current_price"] > snap["ema_200"] else "BELOW_200EMA"

    vol_ratio = snap["volume_last"] / snap["volume_avg_20"] if snap["volume_avg_20"] else 1
    vol_tag = " [HIGH VOLUME SURGE]" if vol_ratio >= 1.5 else ""
    vol_dry = " [LOW VOLUME — weak conviction]" if vol_ratio < 1.0 else ""
    vol_pct  = f"{vol_ratio:.1f}x avg"

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

    bias_line = ""
    if bias_1h:
        b = bias_1h.get("bias_1h", "UNKNOWN")
        e = bias_1h.get("ema_200_1h")
        bias_line = f"\n1H Bias    : {b} (1H EMA200={e}) [LONG only if BULLISH | SHORT only if BEARISH]"

    return f"""{SYSTEM_CONTEXT}

Analyze this {symbol}/USDT crypto market and provide a precise trade signal or NO_TRADE.

=== MARKET SNAPSHOT ({timeframe} chart) ===
Price      : ${snap['current_price']}  (H: ${snap['current_high']}  L: ${snap['current_low']})
RSI(14)    : {snap['rsi_14']}{rsi_tag}
EMA20      : {snap['ema_20']}  |  EMA50: {snap['ema_50']}  |  EMA200: {snap['ema_200']}
Trend      : {trend} | Macro: {macro_trend}{bias_line}
MACD       : Line={snap['macd_line']}  Signal={snap['macd_signal']}  Hist={snap['macd_histogram']}{macd_cross}
ATR(14)    : {snap['atr_14']}
BB         : Upper={snap['bb_upper']}  Lower={snap['bb_lower']}  Position={price_vs_bb}
Volume     : {snap['volume_last']} ({vol_pct}){vol_tag}{vol_dry}
Support    : ${snap['support']}  |  Resistance: ${snap['resistance']}

Last 5 candles (oldest → newest):
{candle_lines}

=== CRYPTO TRADING RULES ===
- Crypto trades 24/7 — no session bias applies.
- If no high-probability setup exists, output NO_TRADE. Most scans should be NO_TRADE.
- Stop loss must be at least 1.5× ATR from entry — tighter stops get wicked out by noise.
- Risk/reward ratio must be ≥ 2.0 for any trade (crypto volatility demands wider targets).
- Entry should be at current price or a tight limit near key S/R — never chase a move.
- RSI FILTER: Do NOT go LONG if RSI(14) ≥ 70 (overbought). Do NOT go SHORT if RSI(14) ≤ 30 (oversold). Output NO_TRADE instead.
- VOLUME FILTER: Volume must be AT OR ABOVE the 20-bar average. Below-average volume = no conviction = NO_TRADE.
- 2-CANDLE CONFIRMATION: Entry must be backed by at least 2 consecutive candles closing in the trade direction. Single-candle breakouts are false signals — output NO_TRADE if confirmation is absent.
- 1H TREND BIAS: Only recommend LONG if 1H bias is BULLISH. Only recommend SHORT if 1H bias is BEARISH. If bias is UNKNOWN, require extra confluences or output NO_TRADE.
- win_probability is your honest technical edge estimate (0–100). Be conservative.
- HIGH confidence = multiple confluences aligning (trend + momentum + volume + S/R + 2-candle confirmation).

Respond with ONLY valid JSON — no extra text, no markdown:
{{
  "direction": "LONG" | "SHORT" | "NO_TRADE",
  "entry": <number>,
  "stop_loss": <number>,
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
        # Normalise direction to uppercase
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

    conf = signal.get("confidence", "LOW")
    conf_emoji = {"HIGH": "🔥", "MEDIUM": "⚡", "LOW": "💭"}.get(conf, "💭")

    entry  = signal.get('entry', 'N/A')
    sl     = signal.get('stop_loss', 'N/A')
    tp     = signal.get('take_profit', 'N/A')
    rr     = signal.get('risk_reward', 'N/A')

    def fmt(v):
        if v == 'N/A' or v == 0:
            return 'N/A'
        return f"${v:,.4f}" if float(v) < 1 else f"${v:,.2f}"

    tp_partial = signal.get("take_profit_partial")
    tp_partial_line = f"🎯 *Partial TP (50% @ 1R):* `{fmt(tp_partial)}`\n" if tp_partial else ""

    return (
        f"{dir_emoji} *{symbol}/USDT — {direction}* {conf_emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Timeframe:* `{timeframe}`\n"
        f"💰 *Current Price:* `{fmt(price)}`\n"
        f"📈 *Entry:* `{fmt(entry)}`\n"
        f"🛑 *Stop Loss:* `{fmt(sl)}`\n"
        f"{tp_partial_line}"
        f"🎯 *Full TP (50%):* `{fmt(tp)}`\n"
        f"⚖️ *Risk/Reward:* `1:{rr}`\n"
        f"🎲 *Win Probability:* `{signal.get('win_probability', 'N/A')}%`\n"
        f"🏆 *Confidence:* `{conf}`\n"
        f"\n"
        f"📝 *Analysis:*\n"
        f"_{signal.get('reasoning', '')}_\n"
        f"\n"
        f"⚠️ _Not financial advice. Trade at your own risk._"
    )
