#!/usr/bin/env python3
"""
CoinGecko Pro Hourly Price History Fetcher — MAX PRECISION VERSION (Decimal + precision=full)
============================================================================

Now uses:
- precision="full" → API returns maximum decimal places it stores
- decimal.Decimal with parse_float → zero floating-point loss in Python
- Exact Decimal storage + string-based CSV export → absolute maximum precision preserved
- Silent API key input via getpass (no * or any characters shown)
"""

import sys
import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
import requests
from pathlib import Path
from decimal import Decimal
import getpass
from typing import Dict, List

# ==================== CONFIG SECTION ====================
CONFIG = {
    "JSON_FILE": "tokens_list.json",
    "OUTPUT_DIR": "price_data",
    "FORCE_FRESH_DOWNLOAD": True,
    "VS_CURRENCY": "usd",
    "MONTHS_BACK": 6,
    "CHUNK_DAYS": 90,
    "SLEEP_BETWEEN_CALLS": 1.2,
    "PRECISION": "full",          # ← absolute max from CoinGecko
}
# =======================================================

def get_api_key() -> str:
    """Silent API key input (no characters or * shown on screen)."""
    print("🔑 Enter your CoinGecko Pro API key (input is completely silent): ", end='', flush=True)
    return getpass.getpass("")


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
    print(f"Loaded {len(portfolio_tokens)} portfolio tokens from {path}")
    return portfolio_tokens


def _fetch_chunk(coin_id: str, from_ts: int, to_ts: int, api_key: str) -> Dict:
    """Fetch one chunk with precision=full + Decimal parsing for absolute max precision."""
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": CONFIG["VS_CURRENCY"],
        "from": from_ts,
        "to": to_ts,
        "interval": "hourly",
        "precision": CONFIG["PRECISION"],
    }
    headers = {"x-cg-pro-api-key": api_key}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            # Parse directly to Decimal → no float conversion loss whatsoever
            data = json.loads(response.text, parse_float=Decimal)
            return data
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
    """Fetch full hourly history with Decimal precision using coin_id only."""
    coin_id = token.get("id")
    if not coin_id:
        print(f"⚠️  Skipping token — no coin_id in JSON")
        return pd.DataFrame()

    os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)
    output_file = Path(CONFIG["OUTPUT_DIR"]) / f"{coin_id}.csv"

    if output_file.exists() and not CONFIG["FORCE_FRESH_DOWNLOAD"]:
        print(f"✅ {output_file.name} already exists (set FORCE_FRESH_DOWNLOAD=True to override)")
        return pd.read_csv(output_file, parse_dates=["datetime"])

    print(f"\nFetching ≈{CONFIG['MONTHS_BACK']} months of **hourly** data for {coin_id}")
    print(f"   Using precision={CONFIG['PRECISION']} + Decimal parsing")

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=int(CONFIG["MONTHS_BACK"] * 30.44))

    print(f"   Range (UTC): {start_date.date()} → {end_date.date()}")

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
        print(f"❌ No data received for {coin_id}")
        return pd.DataFrame()

    # Build DataFrame — timestamp stays int, prices stay Decimal (object dtype)
    df = pd.DataFrame(all_prices, columns=["timestamp_ms", "price_usd"])
    df["datetime"] = pd.to_datetime(df["timestamp_ms"].astype(int), unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"]).set_index("datetime")

    # Market cap + volume (also Decimal)
    if all_market_caps:
        mc_df = pd.DataFrame(all_market_caps, columns=["timestamp_ms", "market_cap"])
        mc_df["datetime"] = pd.to_datetime(mc_df["timestamp_ms"].astype(int), unit="ms", utc=True)
        mc_df = mc_df.drop(columns=["timestamp_ms"]).set_index("datetime")
        df = df.join(mc_df, how="left")

    if all_volumes:
        vol_df = pd.DataFrame(all_volumes, columns=["timestamp_ms", "total_volume"])
        vol_df["datetime"] = pd.to_datetime(vol_df["timestamp_ms"].astype(int), unit="ms", utc=True)
        vol_df = vol_df.drop(columns=["timestamp_ms"]).set_index("datetime")
        df = df.join(vol_df, how="left")

    df = df.drop_duplicates().sort_index().reset_index()

    # Save with full Decimal precision (exact string representation)
    print(f"   Saving with **Decimal** precision (exact values from API)")

    def format_decimal(x):
        if isinstance(x, Decimal):
            return f"{x:f}"          # full fixed-point, no scientific notation loss
        return x

    for col in ["price_usd", "market_cap", "total_volume"]:
        if col in df.columns:
            df[col] = df[col].apply(format_decimal)

    df.to_csv(output_file, index=False)

    print(f"🎉 SUCCESS! Saved {len(df):,} hourly records → {output_file.name}")
    print(f"   Date range: {df['datetime'].min().date()} → {df['datetime'].max().date()}")
    print(f"   File size: {output_file.stat().st_size / 1024:.1f} KB\n")

    return df


def main():
    print("=" * 70)
    print("CoinGecko Pro Hourly Price Fetcher (MAX PRECISION: Decimal + precision=full)")
    print("=" * 70)

    api_key = get_api_key()
    if not api_key.strip():
        print("❌ API key required.")
        sys.exit(1)

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
            coin_id = token.get("id", "unknown")
            print(f"❌ Error processing {coin_id}: {e}")

    print("=" * 70)
    print(f"FINISHED! {success}/{len(tokens)} tokens saved successfully.")
    print(f"Check the '{CONFIG['OUTPUT_DIR']}' folder for your CSVs.")
    print(f"Current time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
