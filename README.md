# Whale Tracker (personal)

Personal Hyperliquid whale-position tracker for Darren Wu, inspired by
[bizyugoscan.com](https://bizyugoscan.com/).

## How it works

- `scripts/refresh_whale_list.py` — pulls Hyperliquid's public leaderboard
  (`stats-data.hyperliquid.xyz`), picks the top wallets by account value, and
  writes `data/whale_list.json`. Runs every 6 hours (GitHub Actions cron).
- `scripts/update_positions.py` — for every tracked wallet, queries
  Hyperliquid's public `clearinghouseState` endpoint for live perp positions,
  aggregates long/short notional per coin, and writes `data/whale_data.json`
  plus a rolling `data/history.jsonl` snapshot log. Runs every 15 minutes.
- A personal dashboard (published separately) reads `data/whale_data.json`
  to show live whale positioning across all coins, with BTC/ETH/HYPE
  highlighted.

All data comes from Hyperliquid's own public, unauthenticated API endpoints
— nothing here requires an API key or trading account.

## Manually running

```bash
python scripts/refresh_whale_list.py
python scripts/update_positions.py
```
