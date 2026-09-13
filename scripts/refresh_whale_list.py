#!/usr/bin/env python3
"""
Refresh the list of tracked whale wallets from Hyperliquid's public leaderboard.

Runs infrequently (every few hours) since the source leaderboard payload is
large (tens of MB, thousands of rows). Selects the top N wallets by account
value and writes data/whale_list.json for update_positions.py to consume.
"""
import json
import os
import sys
import time
import urllib.request

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
TOP_N = 75
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "whale_list.json")


def fetch_leaderboard():
    req = urllib.request.Request(
        LEADERBOARD_URL,
        headers={"User-Agent": "whale-tracker/1.0 (personal dashboard)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(raw)


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def extract_window(window_performances, key):
    """windowPerformances is a list of [windowName, {pnl, roi, vlm}] pairs."""
    if not window_performances:
        return None
    for entry in window_performances:
        if isinstance(entry, list) and len(entry) == 2 and entry[0] == key:
            return entry[1]
    return None


def main():
    print(f"Fetching leaderboard from {LEADERBOARD_URL} ...")
    data = fetch_leaderboard()
    rows = data.get("leaderboardRows", [])
    print(f"Got {len(rows)} leaderboard rows")

    parsed = []
    for row in rows:
        addr = row.get("ethAddress")
        if not addr:
            continue
        account_value = safe_float(row.get("accountValue"))
        if account_value <= 0:
            continue
        day = extract_window(row.get("windowPerformances"), "day") or {}
        week = extract_window(row.get("windowPerformances"), "week") or {}
        parsed.append(
            {
                "address": addr,
                "account_value": account_value,
                "display_name": row.get("displayName") or None,
                "day_pnl": safe_float(day.get("pnl")) if day else None,
                "week_pnl": safe_float(week.get("pnl")) if week else None,
            }
        )

    parsed.sort(key=lambda r: r["account_value"], reverse=True)
    top = parsed[:TOP_N]

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard",
        "total_rows_seen": len(rows),
        "whale_count": len(top),
        "whales": top,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {len(top)} whales to {OUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
