#!/usr/bin/env python3
"""
Aerodrome msUSD/USDC Hourly Data Fetcher (Linux Edition v4)
- ✅ datetime (KST) is now placed RIGHT AFTER timestamp (exactly as you asked)
- ✅ All other features unchanged: KST conversion, clean Linux colors, getpass, etc.
- Ready to run: chmod +x get_prices.py && ./get_prices.py
"""

import requests
import time
import pandas as pd
from datetime import datetime, timedelta, UTC
import os
import getpass
from pathlib import Path
from zoneinfo import ZoneInfo

# ================== CONFIG SECTION ==================
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
# Edit these variables here
# ==================================================

POOL_ADDRESS = "0x054b67943ba17b2cd8c420544c88bde71a81ef9f".lower()
NETWORK = "base"
TIMEFRAME = "hour"
AGGREGATE = 1
LIMIT_PER_CALL = 1000
CURRENCY = "usd"
TOKEN = "base"
DAYS_TO_FETCH = 365

# Output settings
OUTPUT_CSV = "aerodrome_msusd_usdc_hourly_data.csv"
SAVE_PARQUET = False
OUTPUT_PARQUET = "aerodrome_msusd_usdc_hourly_data.parquet"

INCLUDE_EMPTY_INTERVALS = False

# Timezone settings — KOREA SPECIFIC
CONVERT_TO_KST = True
KST_TIMEZONE = "Asia/Seoul"

# Advanced
SLEEP_BETWEEN_CALLS = 0.5
MAX_RETRIES = 3

# ==================================================
# END OF CONFIG
# ==================================================

# Linux-optimized ANSI colors
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    MAGENTA = "\033[35m"

def c(text: str, color: str = Colors.RESET, bold: bool = False) -> str:
    b = Colors.BOLD if bold else ""
    return f"{b}{color}{text}{Colors.RESET}"

def get_api_key() -> str:
    print(c("\n🔑 CoinGecko Pro API Key Required", Colors.MAGENTA, bold=True))
    print("   (Key is never printed or saved to disk)")
    while True:
        api_key = getpass.getpass(c("   Enter your CoinGecko Pro API key: ", Colors.CYAN))
        if api_key.strip():
            print(c(f"   ✅ Key accepted ({len(api_key)} characters)", Colors.GREEN))
            return api_key.strip()
        print(c("   ❌ Key cannot be empty", Colors.RED))

def fetch_ohlcv(api_key: str, before_timestamp: int | None = None):
    url = f"https://pro-api.coingecko.com/api/v3/onchain/networks/{NETWORK}/pools/{POOL_ADDRESS}/ohlcv/{TIMEFRAME}"
    
    params = {
        "aggregate": AGGREGATE,
        "limit": LIMIT_PER_CALL,
        "currency": CURRENCY,
        "token": TOKEN,
        "include_empty_intervals": str(INCLUDE_EMPTY_INTERVALS).lower()
    }
    if before_timestamp is not None:
        params["before_timestamp"] = before_timestamp

    headers = {"x-cg-pro-api-key": api_key}

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            
            meta = data.get("meta", {})
            base_sym = meta.get("base", {}).get("symbol", "msUSD")
            quote_sym = meta.get("quote", {}).get("symbol", "USDC")
            
            candles = data["data"]["attributes"]["ohlcv_list"]
            print(c(f"✅ Fetched {len(candles):4d} candles", Colors.GREEN) +
                  c(f" | Base: {base_sym} / Quote: {quote_sym}", Colors.CYAN))
            return candles, meta
            
        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES - 1:
                print(c(f"❌ API request failed after {MAX_RETRIES} attempts: {e}", Colors.RED))
                raise
            print(c(f"   ⚠️  Attempt {attempt+1}/{MAX_RETRIES} failed — retrying...", Colors.YELLOW))
            time.sleep(2)
    
    return [], {}

# ================== MAIN EXECUTION ==================
print(c("🚀 Aerodrome msUSD/USDC Hourly Data Fetcher (Linux Edition v4)", Colors.BOLD + Colors.BLUE))
print(c(f"   Pool: {POOL_ADDRESS}", Colors.CYAN))
print(c(f"   Network: {NETWORK.upper()}", Colors.CYAN))
print(c(f"   Requesting last {DAYS_TO_FETCH} days of {TIMEFRAME} data...", Colors.CYAN))
if CONVERT_TO_KST:
    print(c(f"   ⏰ Converting all times to KST (Asia/Seoul)", Colors.YELLOW))

API_KEY = get_api_key()

start_timestamp = int((datetime.now(UTC) - timedelta(days=DAYS_TO_FETCH)).timestamp())

all_candles = []
current_before = start_timestamp
batch_count = 0

print(c("\n📡 Starting pagination fetch...", Colors.MAGENTA, bold=True))

while True:
    batch_count += 1
    candles, meta = fetch_ohlcv(API_KEY, current_before if batch_count > 1 else None)
    
    if not candles:
        print(c("   No more data — ending fetch.", Colors.YELLOW))
        break
    
    all_candles.extend(candles)
    
    earliest_ts = candles[-1][0]
    if len(candles) < LIMIT_PER_CALL or earliest_ts >= current_before:
        print(c("   ✅ Reached end of historical data.", Colors.GREEN))
        break
    
    current_before = earliest_ts - 1
    print(c(f"   ... total so far: {len(all_candles):,} candles", Colors.CYAN))
    time.sleep(SLEEP_BETWEEN_CALLS)

# ================== PROCESS & SAVE (with requested column order) ==================
if not all_candles:
    print(c("❌ No data fetched. Check your API key / pool address.", Colors.RED, bold=True))
else:
    print(c(f"\n✅ Total candles fetched: {len(all_candles):,}", Colors.GREEN, bold=True))
    
    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    
    df["datetime_utc"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    
    if CONVERT_TO_KST:
        kst_zone = ZoneInfo(KST_TIMEZONE)
        df["datetime"] = df["datetime_utc"].dt.tz_convert(kst_zone)
        print(c("   ⏰ All timestamps converted to KST (Asia/Seoul)", Colors.YELLOW))
    else:
        df["datetime"] = df["datetime_utc"]
    
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    # QUICK SUMMARY (KST)
    print(c("\n📊 Quick Summary (KST)", Colors.BOLD + Colors.BLUE))
    print(c(f"   Date range (KST): {df['datetime'].min()} → {df['datetime'].max()}", Colors.CYAN))
    print(c(f"   Price (close)    : {df['close'].min():.6f} – {df['close'].max():.6f}", Colors.CYAN))
    print(c(f"   Mean price       : {df['close'].mean():.6f}", Colors.CYAN))
    print(c(f"   Total volume     : {df['volume'].sum():,.2f}", Colors.CYAN))
    
    # NEW COLUMN ORDER: timestamp → datetime (KST) → price data → datetime_utc
    final_columns = ["timestamp", "datetime", "open", "high", "low", "close", "volume", "datetime_utc"]
    df = df[final_columns]
    
    # Export CSV
    csv_path = Path(OUTPUT_CSV)
    df.to_csv(csv_path, index=False)
    print(c(f"\n💾 Exported to {csv_path.resolve()}", Colors.GREEN))
    print(c(f"   Size: {csv_path.stat().st_size / (1024*1024):.2f} MB", Colors.CYAN))
    print(c("   Column order: timestamp, datetime (KST), open, high, low, close, volume, datetime_utc", Colors.YELLOW))
    
    if SAVE_PARQUET:
        parquet_path = Path(OUTPUT_PARQUET)
        try:
            df.to_parquet(parquet_path, index=False)
            print(c(f"   Bonus Parquet: {parquet_path.resolve()}", Colors.GREEN))
        except ImportError:
            print(c("   ⚠️  Parquet skipped — pyarrow not installed", Colors.YELLOW))

print(c("\n🎉 Done! CSV now has datetime (KST) right after timestamp exactly as requested.", Colors.BOLD + Colors.MAGENTA))
print(c("   Next step ideas:"))
print(c("     • Add percentile-based range suggestions + volatility stats"))
print(c("     • Full LP backtester (simulate IL + fees for different range widths)"))
print(c("     • Matplotlib price + volume chart (with KST x-axis)"))
print(c("   Just paste what you want next and I'll drop v5 instantly! 🚀"))
