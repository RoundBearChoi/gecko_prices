import json
import csv
import os
from datetime import datetime
import requests
from getpass import getpass
import time

# ==================== CONFIG SECTION ====================
MONTHS_TO_FETCH = 3          # Change this to fetch more/less history (e.g. 6, 12)
VS_CURRENCY = "usd"          # Usually "usd"; could be "eur", "btc", etc.
OUTPUT_DIR = "volume_data"   # Folder where all CSVs will be saved
JSON_FILE = "tokens_list.json"  # Your attached JSON file
API_BASE_URL = "https://pro-api.coingecko.com/api/v3"
RATE_LIMIT_SLEEP = 1.5       # Seconds between requests (safe for Pro tier)
# =======================================================

def main():
    print("=== CoinGecko Daily Trading Volume Fetcher ===")
    print(f"Target period: last {MONTHS_TO_FETCH} months")
    print(f"Output folder: {OUTPUT_DIR}/\n")
    
    # Secure API key prompt (hidden input - Linux-friendly)
    api_key = getpass("Enter your CoinGecko Pro API key (input will be hidden): ").strip()
    if not api_key:
        print("❌ Error: No API key provided. Exiting.")
        return
    
    # Load tokens list
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            tokens = json.load(f)
        print(f"✅ Loaded {len(tokens)} tokens from {JSON_FILE}")
    except FileNotFoundError:
        print(f"❌ Error: {JSON_FILE} not found. Place it in the current directory.")
        return
    except json.JSONDecodeError:
        print(f"❌ Error: Invalid JSON in {JSON_FILE}.")
        return
    
    # Create output directory (Linux-friendly)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    headers = {
        "x-cg-pro-api-key": api_key,
        "accept": "application/json"
    }
    
    for token in tokens:
        if not token.get("include_in_portfolio", False):
            continue
        
        coin_id = token.get("id")
        
        if not coin_id:
            print("⚠️  Skipping token entry with no 'id' field")
            continue
        
        print(f"\n🔄 Fetching data for {coin_id}...")
        
        try:
            # Approximate days for the requested months + small buffer
            days = MONTHS_TO_FETCH * 30 + 10
            
            url = f"{API_BASE_URL}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": VS_CURRENCY,
                "days": days,
                "interval": "daily"          # Forces daily granularity when possible
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            total_volumes = data.get("total_volumes", [])
            
            if not total_volumes:
                print(f"  ⚠️  No volume data returned for {coin_id} (possibly new token or data gap).")
                continue
            
            # Prepare CSV rows (date in YYYY-MM-DD, volume rounded for readability)
            csv_rows = []
            for ts_ms, volume in total_volumes:
                date_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                csv_rows.append([date_str, round(float(volume), 2)])
            
            # Write CSV using coin_id for filename (as requested)
            csv_filename = os.path.join(OUTPUT_DIR, f"{coin_id}_daily_volume.csv")
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["date", "volume_usd"])
                writer.writerows(csv_rows)
            
            print(f"  ✅ Saved {len(csv_rows)} daily entries to {csv_filename}")
        
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                print(f"  ⏳ Rate limit hit for {coin_id}. Increase RATE_LIMIT_SLEEP if needed.")
            else:
                print(f"  ❌ HTTP Error {response.status_code} for {coin_id}: {e}")
                print(f"     Response preview: {response.text[:300]}...")
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Request error for {coin_id}: {e}")
        except Exception as e:
            print(f"  ❌ Unexpected error for {coin_id}: {e}")
        
        # Be nice to the API
        time.sleep(RATE_LIMIT_SLEEP)
    
    print("\n🎉 All done! Check the volume_data/ folder for your CSV files.")
    print("   Each file is named using the coin 'id' from your JSON (e.g. fartcoin_daily_volume.csv, solana_daily_volume.csv)")
    print("   Columns inside: date, volume_usd")

if __name__ == "__main__":
    main()
