# TopStep Signal & Telegram Bot

This project is a starter scaffold for generating trade signals and sending them to Telegram. It is NOT a fully automated Topstep trade execution system.

## What this repo contains
- `bot.py` — main runner that builds a signal prompt, sends it to an LLM, and posts the result to Telegram
- `deepseek_client.py` — LLM client wrapper for `deepseek` (with fallback support)
- `telegram_client.py` — Telegram message sender
- `strategy.py` — simple signal prompt builder and parser
- `market_data.py` — placeholder for real market data integration

## Setup
1. Copy `.env.example` to `.env`
2. Fill in your Telegram and LLM credentials
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run:
   ```bash
   python bot.py
   ```

## Important notes
- This repo sends Telegram alerts only.
- Topstep funded accounts generally require manual or broker-approved execution.
- Keep `.env` private and rotate any leaked API keys.
