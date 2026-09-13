#!/usr/bin/env python3
"""
Refresh live whale positions from Hyperliquid's public info API.

Runs frequently (every ~15 min). Reads data/whale_list.json (produced by
refresh_whale_list.py) and, for each tracked wallet, queries clearinghouseState
to get current perp positions. Aggregates long/short notional per coin across
all tracked whales (not just BTC/ETH/HYPE - the dashboard highlights those,
but every coin with open whale positions is included) and writes
data/whale_data.json for the dashboard to read.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

API_URL = "https://api.hyperliquid.xyz/info"
BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
WHALE_LIST_PATH = os.path.join(BASE_DIR, "data", "whale_list.json")
OUT_PATH = os.path.join(BASE_DIR, "data", "whale_data.json")
HISTORY_PATH = os.path.join(BASE_DIR, "data", "history.jsonl")
MAX_HISTORY_LINES = 500
MAX_WORKERS = 8
TIMEOUT = 15


def safe_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_clearinghouse_state(address):
    body = json.dumps({"type": "clearinghouseState", "user": address}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "whale-tracker/1.0 (personal dashboard)",
        },
        method="POST",
    )
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {address}: {last_err}")


def main():
    if not os.path.exists(WHALE_LIST_PATH):
        print("ERROR: whale_list.json not found - run refresh_whale_list.py first", file=sys.stderr)
        sys.exit(1)

    with open(WHALE_LIST_PATH) as f:
        whale_list = json.load(f)
    whales_meta = {w["address"]: w for w in whale_list.get("whales", [])}
    addresses = list(whales_meta.keys())
    print(f"Fetching live positions for {len(addresses)} whales ...")

    by_coin = {}  # coin -> {long_notional, short_notional, long_count, short_count}
    whale_results = []
    errors = []

    def handle(address):
        state = fetch_clearinghouse_state(address)
        return address, state

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(handle, addr): addr for addr in addresses}
        for fut in as_completed(futures):
            addr = futures[fut]
            try:
                _, state = fut.result()
            except Exception as e:
                errors.append({"address": addr, "error": str(e)})
                continue

            margin = state.get("marginSummary", {})
            account_value = safe_float(margin.get("accountValue"))
            positions_out = []
            for ap in state.get("assetPositions", []):
                pos = ap.get("position", {})
                coin = pos.get("coin")
                if not coin:
                    continue
                szi = safe_float(pos.get("szi"))
                notional = abs(safe_float(pos.get("positionValue")))
                if notional <= 0:
                    continue
                side = "long" if szi > 0 else "short"

                bucket = by_coin.setdefault(
                    coin,
                    {"long_notional": 0.0, "short_notional": 0.0, "long_count": 0, "short_count": 0},
                )
                bucket[f"{side}_notional"] += notional
                bucket[f"{side}_count"] += 1

                positions_out.append(
                    {
                        "coin": coin,
                        "side": side,
                        "notional": round(notional, 2),
                        "entry_px": safe_float(pos.get("entryPx")),
                        "unrealized_pnl": safe_float(pos.get("unrealizedPnl")),
                        "leverage": pos.get("leverage", {}).get("value"),
                    }
                )

            if positions_out:
                meta = whales_meta.get(addr, {})
                whale_results.append(
                    {
                        "address": addr,
                        "display_name": meta.get("display_name"),
                        "account_value": account_value or meta.get("account_value"),
                        "positions": sorted(positions_out, key=lambda p: p["notional"], reverse=True),
                        "total_notional": round(sum(p["notional"] for p in positions_out), 2),
                    }
                )

    whale_results.sort(key=lambda w: w["total_notional"], reverse=True)

    total_long = sum(v["long_notional"] for v in by_coin.values())
    total_short = sum(v["short_notional"] for v in by_coin.values())
    total_notional = total_long + total_short
    long_pct = round(100 * total_long / total_notional, 1) if total_notional else None
    short_pct = round(100 * total_short / total_notional, 1) if total_notional else None

    by_coin_out = {}
    for coin, v in by_coin.items():
        net = v["long_notional"] - v["short_notional"]
        by_coin_out[coin] = {
            "long_notional": round(v["long_notional"], 2),
            "short_notional": round(v["short_notional"], 2),
            "net_notional": round(net, 2),
            "long_count": v["long_count"],
            "short_count": v["short_count"],
        }
    by_coin_out = dict(
        sorted(by_coin_out.items(), key=lambda kv: kv[1]["long_notional"] + kv[1]["short_notional"], reverse=True)
    )

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = {
        "generated_at": generated_at,
        "whale_list_generated_at": whale_list.get("generated_at"),
        "whale_count": len(whale_results),
        "whale_count_attempted": len(addresses),
        "errors": len(errors),
        "aggregate": {
            "total_notional": round(total_notional, 2),
            "total_long_notional": round(total_long, 2),
            "total_short_notional": round(total_short, 2),
            "long_pct": long_pct,
            "short_pct": short_pct,
        },
        "by_coin": by_coin_out,
        "whales": whale_results,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote whale_data.json: {len(whale_results)} whales with open positions, {len(by_coin_out)} coins, {len(errors)} errors")

    snapshot = {
        "t": generated_at,
        "long_pct": long_pct,
        "short_pct": short_pct,
        "total_notional": round(total_notional, 2),
        "by_coin_net": {c: v["net_notional"] for c, v in by_coin_out.items()},
    }
    lines = []
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH) as f:
            lines = f.read().splitlines()
    lines.append(json.dumps(snapshot))
    lines = lines[-MAX_HISTORY_LINES:]
    with open(HISTORY_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
