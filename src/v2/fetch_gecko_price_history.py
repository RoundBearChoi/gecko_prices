#!/usr/bin/env python3
"""
fetch_gecko_price_history_refactored.py
Refactored + Linux-only * masking (identical to fetch_top_tokens.py)
NOW WITH HIGH-PRECISION SAVING FOR MICRO-CAP / MEME TOKENS

UPDATED: Always fetches the FULL list from subjective_tokens_ranked.csv
         No command-line arguments, no default BTC
"""

import sys
import os
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
import requests
import termios
import tty
from typing import List, Dict

# ==================== CONFIG SECTION ====================
CONFIG = {
    "output_dir": "fetched_data",
    "force_fresh_download": True,      # ← Change to False to reuse existing files
    "vs_currency": "usd",
    "chunk_days": 90,                   # Safe max for hourly data
    "top_tokens_file": "subjective_tokens_ranked.csv",
    "sleep_between_calls": 1.2,
    "default_months": 1,                # Change this if you want more/less history by default
}
# =======================================================

def get_masked_input(prompt: str = "Enter your CoinGecko Pro API key: ") -> str:
    """Linux-only masked input — shows * for every character (identical to fetch_top_tokens.py)."""
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


def load_token_mapping() -> pd.DataFrame:
    """Helper: Loads the token mapping CSV once."""
    if not os.path.exists(CONFIG["top_tokens_file"]):
        print(f"Error: {CONFIG['top_tokens_file']} not found!")
        print("   Make sure the file is in the same folder as this script.")
        sys.exit(1)
    return pd.read_csv(CONFIG["top_tokens_file"])


def resolve_coin_id(token_input: str, tokens_df: pd.DataFrame) -> str:
    """Helper: Maps symbol OR coin_id to the official CoinGecko ID."""
    token_input = token_input.lower().strip()
    token_row = tokens_df[tokens_df['symbol'].str.lower() == token_input]
    if token_row.empty:
        token_row = tokens_df[tokens_df['id'].str.lower() == token_input]
    if token_row.empty:
        print(f"Error: Token '{token_input}' not found in {CONFIG['top_tokens_file']}")
        print("   (Checked both 'symbol' and 'id' columns)")
        print("   First 20 symbols:", tokens_df['symbol'].str.lower().head(20).tolist())
        print("   First 20 IDs:   ", tokens_df['id'].str.lower().head(20).tolist())
        sys.exit(1)
    coin_id = token_row.iloc[0]['id']
    print(f"✅ Mapped input '{token_input}' → CoinGecko ID: {coin_id}")
    return coin_id


def _fetch_chunk(coin_id: str, from_ts: int, to_ts: int, api_key: str) -> list:
    """Internal helper: fetches one hourly chunk."""
    url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": CONFIG["vs_currency"],
        "from": from_ts,
        "to": to_ts,
        "interval": "hourly",
    }
    headers = {"x-cg-pro-api-key": api_key}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("prices", [])
        else:
            print(f"  ⚠️  Error {response.status_code}: {response.text[:300]}")
            if response.status_code == 429:
                print("   Rate limit hit — waiting 10s...")
                time.sleep(10)
            return []
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        return []


def fetch_price_history_for_token(token_input: str, months: int, api_key: str) -> pd.DataFrame:
    """Function #2: ONE token → hourly price history (with CSV save)."""
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    output_file = os.path.join(CONFIG["output_dir"], f"{token_input.lower()}_price_history.csv")

    if os.path.exists(output_file) and not CONFIG["force_fresh_download"]:
        print(f"✅ {output_file} already exists. (Set force_fresh_download=True to override)")
        return pd.read_csv(output_file, parse_dates=["datetime"])

    tokens_df = load_token_mapping()
    coin_id = resolve_coin_id(token_input, tokens_df)

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=int(months * 30.44))

    print(f"Fetching ≈{months} months of **hourly** USD prices for {token_input.upper()}")
    print(f"   Range (UTC): {start_date.date()} → {end_date.date()}")

    all_data = []
    current_start = start_date
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=CONFIG["chunk_days"]), end_date)
        from_ts = int(current_start.timestamp())
        to_ts = int(current_end.timestamp())

        print(f"  → Fetching chunk: {current_start.date()} to {current_end.date()} (UTC)")
        prices = _fetch_chunk(coin_id, from_ts, to_ts, api_key)

        for ts_ms, price in prices:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            all_data.append({"datetime": dt, "price_usd": price})

        current_start = current_end
        time.sleep(CONFIG["sleep_between_calls"])

    if not all_data:
        print("❌ No data received.")
        sys.exit(1)

    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["datetime"])

    # ==================== NEW: HIGH-PRECISION SAVE (Option B) ====================
    print(f"   Saving with full double-precision (%.18e) — tiny prices preserved")
    if (df["price_usd"] < 1e-8).any():
        print(f"   ⚠️  Detected ultra-low prices (< 1e-8) — using scientific notation")

    df.to_csv(output_file, index=False, float_format='%.18e')
    # ============================================================================

    print(f"\n🎉 SUCCESS! Saved {len(df):,} hourly price points")
    print(f"   File: {output_file}")
    print(f"   Date range (UTC): {df['datetime'].min().date()} → {df['datetime'].max().date()}")
    print(f"   Timezone: {df['datetime'].iloc[0].tzinfo}  ← UTC-aware!")
    print(f"   File size: {os.path.getsize(output_file) / 1024:.1f} KB")

    return df


def fetch_price_history_for_tokens(token_list: list[str], months: int, api_key: str) -> dict[str, pd.DataFrame]:
    """Function #3: Batch of tokens → hourly price history for each."""
    results = {}
    tokens_df = load_token_mapping()

    for token in token_list:
        print(f"\n{'='*60}\nProcessing token: {token.upper()}\n{'='*60}")
        try:
            df = fetch_price_history_for_token(token, months, api_key)
            results[token.lower()] = df
        except SystemExit as e:
            print(f"⚠️  Skipping {token} due to error: {e}")
            continue
        except Exception as e:
            print(f"❌ Unexpected error for {token}: {e}")
            continue

    print(f"\n🎉 Batch complete! Processed {len(results)}/{len(token_list)} tokens successfully.")
    return results


def get_api_key() -> str:
    """Function #1: Gets API key (RAM only) using Linux-only * masking."""
    print("\n=== CoinGecko Hourly Price History Fetcher (FULL LIST MODE) ===")
    api_key = get_masked_input("Enter your CoinGecko Pro API key: ")
    if not api_key:
        print("Error: API key cannot be empty.")
        sys.exit(1)
    return api_key


def main():
    """Simplified entry point — ALWAYS fetches the FULL list from subjective_tokens_ranked.csv"""
    print("🚀 Starting full bulk fetch from subjective_tokens_ranked.csv...")

    # Load the complete token list
    print(f"📋 Loading full token list from {CONFIG['top_tokens_file']}...")
    tokens_df = load_token_mapping()
    token_list = tokens_df['symbol'].str.lower().tolist()
    months = CONFIG["default_months"]

    print(f"   Found {len(token_list):,} tokens (first 5: {token_list[:5]})")
    print(f"   Fetching ≈{months} month(s) of hourly USD prices for ALL tokens")

    api_key = get_api_key()

    # Run the bulk fetcher
    fetch_price_history_for_tokens(token_list, months, api_key)


if __name__ == "__main__":
    main()
