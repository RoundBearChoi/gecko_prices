import json
import requests
import time
import csv
import sys
import termios
import tty
from datetime import datetime

# ========================= CONFIG =========================
USE_PRO_API = True          # True = your Pro key | False = Basic tier
VS_CURRENCY = "usd"
OUTPUT_CSV = "market_cap_and_volume.csv"
# =======================================================

def get_masked_input(prompt="API Key: "):
    """Linux-only masked input: shows * for every character while pasting/typing."""
    print(prompt, end='', flush=True)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        password = ""
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):          # Enter pressed
                print()                     # new line
                break
            elif ch in ("\x7f", "\b"):      # Backspace
                if password:
                    password = password[:-1]
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            else:
                password += ch
                sys.stdout.write("*")
                sys.stdout.flush()
        return password
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def load_tokens(filename="tokens_list.json"):
    """Load your token list."""
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

def get_current_market_data(coin_ids, headers, base_url):
    """One call for market cap + 1d volume."""
    params = {
        "vs_currency": VS_CURRENCY,
        "ids": ",".join(coin_ids),
        "order": "market_cap_desc",
        "per_page": 250,
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h"
    }
    response = requests.get(f"{base_url}/coins/markets", headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ Error fetching market data: {response.status_code} - {response.text}")
        return None
    return response.json()

def get_total_volume(coin_id, days, headers, base_url):
    """Sum total volume over the requested days."""
    params = {"vs_currency": VS_CURRENCY, "days": str(days)}
    response = requests.get(f"{base_url}/coins/{coin_id}/market_chart", headers=headers, params=params)
    if response.status_code != 200:
        print(f"❌ Error fetching {days}d chart for {coin_id}: {response.status_code}")
        return None
    data = response.json()
    volumes = data.get("total_volumes", [])
    if volumes:
        return round(sum(item[1] for item in volumes), 0)
    return None

def save_to_csv(results, filename=OUTPUT_CSV):
    """Save results to CSV with the new include_in_portfolio column."""
    fieldnames = [
        "symbol", "coin_id", "include_in_portfolio",
        "market_cap", "volume_1d_total",
        "volume_7d_total", "volume_30d_total", "volume_1d_avg_30d",
        "price", "price_change_24h_pct", "timestamp"
    ]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for coin_id, data in results.items():
            row = {
                "symbol": data["symbol"],
                "coin_id": coin_id,
                "include_in_portfolio": "Yes" if data.get("include_in_portfolio") else "No",
                "market_cap": data.get("market_cap") or "",
                "volume_1d_total": data.get("volume_1d_total") or "",
                "volume_7d_total": data.get("volume_7d_total") or "",
                "volume_30d_total": data.get("volume_30d_total") or "",
                "volume_1d_avg_30d": data.get("volume_1d_avg_30d") or "",
                "price": data.get("price") or "",
                "price_change_24h_pct": data.get("price_change_24h_pct") or "",
                "timestamp": timestamp
            }
            writer.writerow(row)
    print(f"💾 Results saved to → {filename}")

def main():
    print("🚀 CoinGecko Volume Fetcher v6 (1d / 7d / 30d totals + 1d Avg from 30d + portfolio flag)\n")
    
    # Masked input — everything appears as *
    print("🔑 Please paste your CoinGecko API key (everything will appear as *):")
    api_key = get_masked_input()
    
    if api_key:
        masked = "*" * max(24, len(api_key))
        print(f"✅ API key accepted: {masked}")
    else:
        print("⚠️  No API key provided. Continuing with public limits (may fail).")
        masked = "None"
    
    # Choose correct endpoint & header
    if USE_PRO_API:
        BASE_URL = "https://pro-api.coingecko.com/api/v3"
        headers = {"x-cg-pro-api-key": api_key} if api_key else {}
        print("🔄 Using **Pro** API endpoint")
    else:
        BASE_URL = "https://api.coingecko.com/api/v3"
        headers = {"x-cg-demo-api-key": api_key} if api_key else {}
        print("🔄 Using **Basic/Demo** API endpoint")
    
    # Load tokens
    tokens = load_tokens()
    id_to_symbol = {token["id"]: token["symbol"] for token in tokens}
    id_to_include = {token["id"]: token.get("include_in_portfolio", False) for token in tokens}
    coin_ids = list(id_to_symbol.keys())
    
    print(f"\n📡 Fetching data for {len(coin_ids)} tokens at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 1. Current market data
    print("📊 Fetching current market data...")
    market_data = get_current_market_data(coin_ids, headers, BASE_URL)
    if not market_data:
        print("❌ Failed to fetch market data. Check your key or change USE_PRO_API in the config.")
        return
    
    # Build results
    results = {}
    for coin in market_data:
        coin_id = coin["id"]
        symbol = id_to_symbol.get(coin_id, coin_id.upper())
        results[coin_id] = {
            "symbol": symbol,
            "include_in_portfolio": id_to_include.get(coin_id, False),
            "market_cap": coin.get("market_cap"),
            "volume_1d_total": coin.get("total_volume"),
            "price": coin.get("current_price"),
            "price_change_24h_pct": coin.get("price_change_percentage_24h")
        }
    
    # 2. 7d and 30d volumes + new 1d average
    print("📈 Fetching 7-day and 30-day total volumes + calculating 1d average...")
    for coin_id in coin_ids:
        if coin_id in results:
            sym = id_to_symbol.get(coin_id, coin_id)
            print(f"   → {sym}")
            vol_7d = get_total_volume(coin_id, 7, headers, BASE_URL)
            vol_30d = get_total_volume(coin_id, 30, headers, BASE_URL)
            
            results[coin_id]["volume_7d_total"] = vol_7d
            results[coin_id]["volume_30d_total"] = vol_30d
            # New column: 1d average from 30d total
            results[coin_id]["volume_1d_avg_30d"] = round(vol_30d / 30, 0) if vol_30d is not None else None
            
            time.sleep(0.6)
    
    # 3. Console output (unchanged)
    print("\n" + "="*130)
    print("CONSOLE RESULTS — ALL VOLUMES IN USD")
    print("="*130)
    for coin_id, data in results.items():
        sym = data["symbol"]
        print(f"\n🔹 {sym} ({coin_id})")
        print(f"   Price               : ${data.get('price'):,.6f}" if data.get("price") is not None else "   Price               : N/A")
        print(f"   24h Change          : {data.get('price_change_24h_pct'):+.2f}%" if data.get("price_change_24h_pct") is not None else "   24h Change          : N/A")
        print(f"   Market Cap          : ${data.get('market_cap'):,.0f}" if data.get("market_cap") is not None else "   Market Cap          : N/A")
        print(f"   Volume 1d Total     : ${data.get('volume_1d_total'):,.0f}" if data.get("volume_1d_total") is not None else "   Volume 1d Total     : N/A")
        print(f"   Volume 7d Total     : ${data.get('volume_7d_total'):,.0f}" if data.get("volume_7d_total") is not None else "   Volume 7d Total     : N/A")
        print(f"   Volume 30d Total    : ${data.get('volume_30d_total'):,.0f}" if data.get("volume_30d_total") is not None else "   Volume 30d Total    : N/A")
        print(f"   1d Avg (30d)        : ${data.get('volume_1d_avg_30d'):,.0f}" if data.get("volume_1d_avg_30d") is not None else "   1d Avg (30d)        : N/A")
    
    # 4. Save CSV
    save_to_csv(results)
    
    print(f"\n🎉 All done! Check the console above and the file: {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
