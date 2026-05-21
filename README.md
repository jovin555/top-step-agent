# Crypto Signal & Telegram Bot

This project is a starter scaffold for generating crypto trade signals and sending them to Telegram. It is NOT a fully automated crypto trade execution system.

## What this repo contains
- `main.py` — signal scanner entry point and scheduler
- `bot/` — signal prompt builder, parser, and logger
- `clients/` — Telegram and LLM client wrappers
- `bot/market_data.py` — placeholder for real market data integration
- `stats.py` — helper for signal statistics

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
- Crypto trade signals generally require manual execution or exchange-approved automation.
- Keep `.env` private and rotate any leaked API keys.
