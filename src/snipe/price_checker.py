import os
import glob
import csv
import time
import sys
import requests
from datetime import datetime

# ==================== CONFIG SECTION ====================
# Change these variables to customize behavior
UPDATE_INTERVAL_MINUTES = 4          # How often to fetch fresh prices from CoinGecko
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"  # CoinGecko API endpoint
BAR_WIDTH = 50                       # Width of the progress bar (characters)
SHOW_FULL_HISTORY = False            # Set True to keep all previous updates on screen (False = cleaner dashboard)
# =======================================================

def get_csv_files():
    """Auto-discover all files matching the exact pattern solana_portfolio_{tokenid}_usdc.csv"""
    return glob.glob("solana_portfolio_*_usdc.csv")

def extract_token_id(filename):
    """Extract token_id EXACTLY as it appears in the filename (no case changes, no symbol conversion).
    Example: solana_portfolio_popcat_usdc.csv → 'popcat'
    This follows your requirement to keep the ID as-is for CoinGecko consistency."""
    base = os.path.basename(filename)
    prefix = "solana_portfolio_"
    suffix = "_usdc.csv"
    if base.startswith(prefix) and base.endswith(suffix):
        return base[len(prefix):-len(suffix)]
    return None

def get_latest_token_price(filename):
    """Read ONLY the very last row of the CSV and return token_price_usd.
    Uses DictReader so column names are reliable even if CSV structure changes slightly."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            last_row = None
            for row in reader:
                last_row = row
            if last_row and 'token_price_usd' in last_row:
                return float(last_row['token_price_usd'])
    except Exception as e:
        print(f"⚠️  Error reading last price from {filename}: {e}")
    return None

def fetch_current_prices(token_ids):
    """Fetch current USD prices for ALL tokens in ONE API call (most efficient).
    CoinGecko free tier supports comma-separated IDs and has generous rate limits (~30-50 calls/min)."""
    if not token_ids:
        return {}
    ids_str = ','.join(token_ids)
    url = f"{COINGECKO_BASE_URL}/simple/price"
    params = {'ids': ids_str, 'vs_currencies': 'usd'}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # Return dict: token_id → current_price (None if missing)
        return {tid: data.get(tid, {}).get('usd') for tid in token_ids}
    except requests.exceptions.RequestException as e:
        print(f"⚠️  CoinGecko API error: {e}")
        return {}
    except Exception as e:
        print(f"⚠️  Unexpected error fetching prices: {e}")
        return {}

def print_status(last_prices, current_prices, token_ids, timestamp):
    """Display clean table with last recorded price vs current price + % delta."""
    print("\n" + "=" * 100)
    print(f"🚀 Solana Portfolio Price Monitor — {timestamp} KST")
    print("=" * 100)
    print(f"{'Token ID':<25} {'Last Recorded (USD)':<20} {'Current Price (USD)':<20} {'Δ %':<12}")
    print("-" * 100)
    
    for tid in sorted(token_ids):  # Consistent ordering
        last_p = last_prices.get(tid)
        curr_p = current_prices.get(tid)
        
        if last_p is None:
            print(f"{tid:<25} {'(CSV read error)':<20} {'N/A':<20} {'N/A':<12}")
            continue
        if curr_p is None:
            print(f"{tid:<25} ${last_p:<18.8f} {'(API error)':<20} {'N/A':<12}")
            continue
        
        delta_pct = ((curr_p - last_p) / last_p) * 100
        delta_str = f"{delta_pct:+.2f}%"
        # Visual indicator
        indicator = "🟢" if delta_pct >= 0 else "🔴"
        
        print(f"{tid:<25} ${last_p:<18.8f} ${curr_p:<18.8f} {indicator} {delta_str:<12}")
    
    print("=" * 100)
    print(f"📊 Monitoring {len(token_ids)} token{'s' if len(token_ids) != 1 else ''} • Next update in {UPDATE_INTERVAL_MINUTES} minutes")

def countdown_timer(seconds):
    """Live ticking timer + progress bar that updates every 1 second.
    Uses \r + flush so the bar overwrites itself cleanly without cluttering the console."""
    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        progress = (seconds - remaining) / seconds
        filled = int(BAR_WIDTH * progress)
        bar = '█' * filled + '░' * (BAR_WIDTH - filled)
        
        timer_line = f"\r⏳ Next update in {mins:02d}:{secs:02d} [{bar}] {progress*100:3.0f}%"
        sys.stdout.write(timer_line)
        sys.stdout.flush()
        time.sleep(1)
    
    # Clear the countdown line when finished
    sys.stdout.write("\r" + " " * (BAR_WIDTH + 60) + "\n")
    sys.stdout.flush()
    print("🔄 Fetching latest prices from CoinGecko...")

def main():
    """Main monitoring loop."""
    print("🚀 Starting Solana Portfolio Monitor")
    print(f"   • Looking for files: solana_portfolio_*_usdc.csv in current folder")
    print(f"   • Update frequency: every {UPDATE_INTERVAL_MINUTES} minutes")
    print(f"   • Token IDs kept exactly as in filename (CoinGecko compatible)")
    print("   • Press Ctrl+C to stop\n")
    
    while True:
        # 1. Discover all CSV files
        csv_files = get_csv_files()
        if not csv_files:
            print("⚠️  No matching CSV files found! Place your solana_portfolio_*.csv files in this folder.")
            time.sleep(10)
            continue
        
        # 2. Extract token_ids and last recorded prices
        token_ids = []
        last_prices = {}
        for file_path in csv_files:
            tid = extract_token_id(file_path)
            if tid:
                token_ids.append(tid)
                last_p = get_latest_token_price(file_path)
                if last_p is not None:
                    last_prices[tid] = last_p
        
        if not token_ids:
            print("⚠️  No valid token_ids could be extracted from filenames.")
            time.sleep(10)
            continue
        
        # 3. Fetch current prices (single API call)
        current_prices = fetch_current_prices(token_ids)
        
        # 4. Show current status
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print_status(last_prices, current_prices, token_ids, now_str)
        
        # 5. Live countdown with progress bar (ticks every second)
        update_seconds = UPDATE_INTERVAL_MINUTES * 60
        countdown_timer(update_seconds)
        
        # Loop repeats → new prices are fetched automatically

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Monitor stopped by user. Goodbye!")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print("Tip: Make sure 'requests' is installed (`pip install requests`)")
