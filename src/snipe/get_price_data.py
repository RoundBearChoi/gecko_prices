#!/usr/bin/env python3
"""
CoinGecko Pro Hourly Price History Fetcher — FINAL VERSION (tokens_list.json)
============================================================================

✅ Uses the **proven** `/market_chart/range` + 90-day chunking method from your reference script
   → This is why we can reliably get **hourly** data (your previous simple /market_chart calls were getting 400)

Features:
- Loads your exact `tokens_list.json` (only tokens with `include_in_portfolio: true`)
- Linux-only masked API key input (shows * like your reference script)
- Configurable at the top (months back, output folder, etc.)
- High-precision CSV saving (`%.18e`) — perfect for micro-cap meme coins
- Fetches price + market cap + total volume
- Creates one clean CSV per token in `price_data/` folder
- Graceful chunking, UTC timestamps, duplicate removal, progress logging

Optimized for Linux (shebang, pathlib, termios masking).
"""

import sys
import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
import requests
import termios
import tty
from pathlib import Path
from typing import Dict, List

# ==================== CONFIG SECTION ====================
# ←←← Edit these values anytime ←←←
CONFIG = {
    "JSON_FILE": "tokens_list.json",          # Your original file
    "OUTPUT_DIR": "price_data",               # Where CSVs will be saved
    "FORCE_FRESH_DOWNLOAD": True,             # Set False to reuse existing CSVs
    "VS_CURRENCY": "usd",
    "MONTHS_BACK": 6,                         # ← Change this (e.g. 3, 12, 24)
    "CHUNK_DAYS": 90,                         # Safe max for hourly granularity on Pro
    "SLEEP_BETWEEN_CALLS": 1.2,               # Be respectful to the API
}
# =======================================================

def get_masked_input(prompt: str = "Enter your CoinGecko Pro API key: ") -> str:
    """Linux-only masked input — shows * for every character (copied from your reference script)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        print(prompt, end='', flush=True)
        password = ""
        while True:
            ch = sys.stdin.read(1)
            if ch in ('\n', '\r'):
                print()
                break
            elif ch == '\x7f':               # Backspace
                if password:
                    password = password[:-1]
                    print('\b \b', end='', flush=True)
            elif ch == '\x03':               # Ctrl+C
                raise KeyboardInterrupt
            else:
                password += ch
                print('*', end='', flush=True)
        return password.strip()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def load_tokens(json_path: str) -> List[Dict]:
    """Load tokens_list.json and return only portfolio tokens."""
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(
            f"❌ Tokens file not found: {path}\n"
            f"   Put your tokens_list.json in the same folder as this script."
        )
    with open(path, encoding="utf-8") as f:
        tokens = json.load(f)
    portfolio_tokens = [t for t in tokens if t.get("include_in_portfolio", False)]
    print(f"✅ Loaded {len(portfolio_tokens)} portfolio tokens from {path}")
    return portfolio_tokens


def _fetch_chunk(coin_id: str, from_ts: int, to_ts: int, api_key: str) -> Dict:
    """Fetch one chunk using the exact working endpoint from your reference script."""
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": CONFIG["VS_CURRENCY"],
        "from": from_ts,
        "to": to_ts,
        "interval": "hourly",
    }
    headers = {"x-cg-pro-api-key": api_key}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  ⚠️  HTTP {response.status_code}: {response.text[:300]}")
            if response.status_code == 429:
                print("   Rate limit — waiting 10s...")
                time.sleep(10)
            return {}
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        return {}


def fetch_price_history_for_token(token: Dict, api_key: str) -> pd.DataFrame:
    """Fetch full hourly history (price + market cap + volume) for one token."""
    symbol = token.get("symbol", "unknown").upper()
    coin_id = token.get("id")
    if not coin_id:
        print(f"⚠️  Skipping {symbol} — no coin_id in JSON")
        return pd.DataFrame()

    os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
    output_file = Path(CONFIG["OUTPUT_DIR"]) / f"{symbol}.csv"

    if output_file.exists() and not CONFIG["FORCE_FRESH_DOWNLOAD"]:
        print(f"✅ {output_file.name} already exists (set FORCE_FRESH_DOWNLOAD=True to override)")
        return pd.read_csv(output_file, parse_dates=["datetime"])

    print(f"\n📡 Fetching ≈{CONFIG['MONTHS_BACK']} months of **hourly** data for {symbol} ({coin_id})")

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=int(CONFIG["MONTHS_BACK"] * 30.44))

    print(f"   Range (UTC): {start_date.date()} → {end_date.date()}")

    # Collect data from all chunks
    all_prices = []
    all_market_caps = []
    all_volumes = []

    current_start = start_date
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=CONFIG["CHUNK_DAYS"]), end_date)
        from_ts = int(current_start.timestamp())
        to_ts = int(current_end.timestamp())

        print(f"  → Chunk: {current_start.date()} to {current_end.date()}")
        data = _fetch_chunk(coin_id, from_ts, to_ts, api_key)

        all_prices.extend(data.get("prices", []))
        all_market_caps.extend(data.get("market_caps", []))
        all_volumes.extend(data.get("total_volumes", []))

        current_start = current_end
        time.sleep(CONFIG["SLEEP_BETWEEN_CALLS"])

    if not all_prices:
        print(f"❌ No data received for {symbol}")
        return pd.DataFrame()

    # Build clean DataFrame
    df = pd.DataFrame(all_prices, columns=["timestamp_ms", "price_usd"])
    df["datetime"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"]).set_index("datetime")

    # Add market cap if available
    if all_market_caps:
        mc_df = pd.DataFrame(all_market_caps, columns=["timestamp_ms", "market_cap"])
        mc_df["datetime"] = pd.to_datetime(mc_df["timestamp_ms"], unit="ms", utc=True)
        mc_df = mc_df.drop(columns=["timestamp_ms"]).set_index("datetime")
        df = df.join(mc_df, how="left")

    # Add total volume if available
    if all_volumes:
        vol_df = pd.DataFrame(all_volumes, columns=["timestamp_ms", "total_volume"])
        vol_df["datetime"] = pd.to_datetime(vol_df["timestamp_ms"], unit="ms", utc=True)
        vol_df = vol_df.drop(columns=["timestamp_ms"]).set_index("datetime")
        df = df.join(vol_df, how="left")

    df = df.drop_duplicates().sort_index().reset_index()

    # High-precision save for tiny meme-coin prices
    print(f"   Saving with full double-precision (%.18e) — ultra-low prices preserved")
    if (df["price_usd"] < 1e-8).any():
        print(f"   ⚠️  Detected micro-cap prices (< 1e-8) — scientific notation used")

    df.to_csv(output_file, index=False, float_format='%.18e')

    print(f"🎉 SUCCESS! Saved {len(df):,} hourly records → {output_file.name}")
    print(f"   Date range: {df['datetime'].min().date()} → {df['datetime'].max().date()}")
    print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB\n")

    return df


def main():
    print("=" * 70)
    print("🚀 CoinGecko Pro Hourly Price Fetcher (tokens_list.json + chunked hourly)")
    print("=" * 70)

    # Secure masked API key (Linux only)
    api_key = get_masked_input("🔑 Enter your CoinGecko Pro API key: ")
    if not api_key:
        print("❌ API key required.")
        sys.exit(1)

    # Load portfolio tokens
    try:
        tokens = load_tokens(CONFIG["JSON_FILE"])
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    success = 0
    for token in tokens:
        try:
            df = fetch_price_history_for_token(token, api_key)
            if not df.empty:
                success += 1
        except KeyboardInterrupt:
            print("\n⛔ Stopped by user.")
            break
        except Exception as e:
            print(f"❌ Error processing {token.get('symbol', 'unknown')}: {e}")

    print("=" * 70)
    print(f"🎉 FINISHED! {success}/{len(tokens)} tokens saved successfully.")
    print(f"📁 Check the '{CONFIG['OUTPUT_DIR']}' folder for your CSVs.")
    print(f"Current time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n💡 Tip: Open any CSV in pandas/Excel — prices are preserved with full precision!")


if __name__ == "__main__":
    main()
