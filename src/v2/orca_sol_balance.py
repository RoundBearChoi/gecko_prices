import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
import select  # ← for non-blocking 'r' key check
from typing import Dict, Any

# ========================= CONFIG SECTION =========================
CONFIG = {
    "RPC_URL": "https://api.mainnet-beta.solana.com",
    "CSV_FILENAME": "solana_orca_balances.csv",
    "ORCA_MINT": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "COINGECKO_IDS": "solana,orca",
    "VS_CURRENCY": "usd",
    "KST_TIMEZONE": "Asia/Seoul",
    
    # ==================== VISUAL BAR SETTINGS ====================
    "BAR_WIDTH": 80,
    "BAR_CHAR_SOL": "█",
    "BAR_CHAR_ORCA": "─",
    "BAR_BG": "─",
    
    # Label settings
    "SHOW_HEADER_LABELS": True,
    "SHOW_50_PERCENT_MARKER": True,
    "PERCENT_PRECISION": 1,
    
    # ==================== LIVE MONITOR SETTINGS ====================
    "REFRESH_INTERVAL": 60*5,
    "UPDATE_ONCE": False,            # True = one-time run, False = live with countdown
    
    # ==================== RATE LIMIT SETTINGS ====================
    "RATE_LIMIT_WAIT_SECONDS": 180,  # 3 minutes FIXED wait on rate limit (no backoff)
}
# ================================================================

# ====================== HELPER FUNCTIONS ======================
def get_previous_balances(csv_filename: str) -> tuple[float, float]:
    """Return previous (sol_balance, orca_balance) from the LAST CSV row.
    Returns (0.0, 0.0) on first run or if CSV is missing/empty."""
    if not os.path.isfile(csv_filename):
        return 0.0, 0.0
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return 0.0, 0.0
            last_row = rows[-1]
            return (
                float(last_row.get("sol_balance", 0)),
                float(last_row.get("orca_balance", 0))
            )
    except Exception as e:
        print(f"⚠️  Could not read previous balances for delta calculation: {e}")
        return 0.0, 0.0


def get_first_equivalents(csv_filename: str) -> tuple[float, float]:
    """Return (sol_equivalent, orca_equivalent) from the FIRST row in the CSV.
    This is now the permanent baseline for equivalent change calculations.
    Returns (0.0, 0.0) on first run or if CSV is missing/empty."""
    if not os.path.isfile(csv_filename):
        return 0.0, 0.0
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return 0.0, 0.0
            first_row = rows[0]
            return (
                float(first_row.get("sol_equivalent", 0)),
                float(first_row.get("orca_equivalent", 0))
            )
    except Exception as e:
        print(f"⚠️  Could not read first equivalents for delta calculation: {e}")
        return 0.0, 0.0
# ================================================================

def _handle_rate_limit(error_msg: str = "") -> bool:
    """Return True if the error looks like a rate limit (used by all three API functions)."""
    if not error_msg:
        return False
    msg_lower = error_msg.lower()
    return any(term in msg_lower for term in ["rate limit", "too many requests", "429", "rate exceeded"])


def get_sol_balance(rpc_url: str, pubkey: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]}
    wait_time = CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            response = requests.post(rpc_url, json=payload, timeout=20)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            
            if "error" in data:
                error = data["error"]
                if _handle_rate_limit(str(error)):
                    if attempt < max_attempts - 1:
                        print(f"⚠️  Solana RPC rate limit detected. Waiting {wait_time} seconds before retry ({attempt+1}/{max_attempts})...")
                        time.sleep(wait_time)
                        continue
                raise Exception(f"RPC Error: {error}")
            
            return data["result"]["value"] / 1_000_000_000.0
            
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < max_attempts - 1:
                    print(f"⚠️  HTTP 429 Rate Limit (Solana RPC). Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
            raise
        except Exception as e:
            if attempt < max_attempts - 1 and _handle_rate_limit(str(e)):
                print(f"⚠️  Rate limit (unexpected) detected. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            raise
    
    raise Exception("Failed to get SOL balance after maximum rate-limit retries")


def get_orca_balance(rpc_url: str, pubkey: str, orca_mint: str) -> float:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [pubkey, {"mint": orca_mint}, {"encoding": "jsonParsed"}]
    }
    wait_time = CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            response = requests.post(rpc_url, json=payload, timeout=20)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            
            if "error" in data:
                error = data["error"]
                if _handle_rate_limit(str(error)):
                    if attempt < max_attempts - 1:
                        print(f"⚠️  Solana RPC rate limit detected (ORCA balance). Waiting {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
                raise Exception(f"RPC Error: {error}")
            
            accounts = data.get("result", {}).get("value", [])
            if not accounts:
                return 0.0
            
            token_info = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
            return int(token_info["amount"]) / (10 ** int(token_info["decimals"]))
            
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < max_attempts - 1:
                    print(f"⚠️  HTTP 429 Rate Limit (Solana RPC - ORCA). Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
            raise
        except Exception as e:
            if attempt < max_attempts - 1 and _handle_rate_limit(str(e)):
                print(f"⚠️  Rate limit (unexpected) detected. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            raise
    
    raise Exception("Failed to get ORCA balance after maximum rate-limit retries")


def get_prices() -> Dict[str, float]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={CONFIG['COINGECKO_IDS']}&vs_currencies={CONFIG['VS_CURRENCY']}"
    wait_time = CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            return {
                "sol": data.get("solana", {}).get(CONFIG["VS_CURRENCY"], 0.0),
                "orca": data.get("orca", {}).get(CONFIG["VS_CURRENCY"], 0.0),
            }
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < max_attempts - 1:
                    print(f"⚠️  CoinGecko rate limit (429). Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    continue
            raise
        except Exception as e:
            if attempt < max_attempts - 1 and _handle_rate_limit(str(e)):
                print(f"⚠️  CoinGecko rate limit detected. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            raise
    
    raise Exception("Failed to fetch prices after maximum rate-limit retries")


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_portfolio_bar(orca_ratio: float, sol_balance: float, orca_balance: float, 
                       sol_price: float, orca_price: float):
    """Print portfolio allocation bar + 50:50 rebalancing advice (matches pepe_btcb_balance.py style)."""
    sol_ratio = 1.0 - orca_ratio
    width = CONFIG["BAR_WIDTH"]
    
    sol_blocks = int(round(sol_ratio * width))
    orca_blocks = width - sol_blocks
    
    bar = CONFIG["BAR_CHAR_SOL"] * sol_blocks + CONFIG["BAR_CHAR_ORCA"] * orca_blocks
    
    precision = CONFIG["PERCENT_PRECISION"]
    sol_percent = f"{sol_ratio*100:.{precision}f}% SOL"
    orca_percent = f"{orca_ratio*100:.{precision}f}% ORCA"
    
    print("\n📊 Portfolio Allocation Visual:")
    
    if CONFIG["SHOW_HEADER_LABELS"]:
        header_padding = " " * (width - 10)
        print(f"   SOL{header_padding}ORCA")
    
    print(f"   {bar}")
    
    total_label_len = len(sol_percent) + len(orca_percent)
    spacing = width - total_label_len + 6
    label_line = f"   {sol_percent}{' ' * spacing}{orca_percent}"
    print(label_line)
    
    if CONFIG["SHOW_50_PERCENT_MARKER"]:
        print(f"   {'50%':^{width}}")

    total_value_usd = sol_balance * sol_price + orca_balance * orca_price
    if total_value_usd > 1.0:
        target_each = total_value_usd / 2.0
        sol_value = sol_balance * sol_price
        excess_usd = sol_value - target_each
        
        if excess_usd >= 0:
            sol_to_sell = excess_usd / sol_price
            orca_to_buy = excess_usd / orca_price
            print(f"   🔄 To reach perfect 50:50 → Sell ~{sol_to_sell:,.6f} SOL (~${excess_usd:,.2f} USD) to buy ~{orca_to_buy:,.4f} ORCA")
        else:
            orca_to_sell = abs(excess_usd) / orca_price
            sol_to_buy = abs(excess_usd) / sol_price
            print(f"   🔄 To reach perfect 50:50 → Sell ~{orca_to_sell:,.4f} ORCA (~${abs(excess_usd):,.2f} USD) to buy ~{sol_to_buy:,.6f} SOL")
    else:
        print("   ⚠️  Portfolio value too small for rebalancing suggestion")


def fetch_and_display(address: str, save_to_csv: bool = False):
    """Shared function to fetch data and print everything.
    CSV is written only when save_to_csv=True (first run + every manual refresh)."""
    kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
    now_kst = datetime.now(kst_tz)
    timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")

    print("🔴 Solana + ORCA Portfolio Monitor")
    print("=" * 90)
    print(f"Wallet  : {address}")
    print(f"Updated : {timestamp_str} (KST)")
    print("=" * 90)

    sol_balance = get_sol_balance(CONFIG["RPC_URL"], address)
    orca_balance = get_orca_balance(CONFIG["RPC_URL"], address, CONFIG["ORCA_MINT"])
    prices = get_prices()

    sol_value_usd = sol_balance * prices["sol"]
    orca_value_usd = orca_balance * prices["orca"]
    total_value_usd = sol_value_usd + orca_value_usd

    sol_equivalent = sol_balance + (orca_value_usd / prices["sol"]) if prices["sol"] > 0 else sol_balance
    orca_equivalent = orca_balance + (sol_value_usd / prices["orca"]) if prices["orca"] > 0 else orca_balance

    orca_per_sol = prices["sol"] / prices["orca"] if prices["orca"] > 0 else 0.0
    sol_per_orca = prices["orca"] / prices["sol"] if prices["sol"] > 0 else 0.0

    portfolio_orca_ratio = orca_value_usd / total_value_usd if total_value_usd > 0 else 0.0

    print("\n📊 Current Balances:")
    print(f"   SOL   : {sol_balance:,.6f} SOL  (${sol_value_usd:,.2f})")
    print(f"   ORCA  : {orca_balance:,.6f} ORCA (${orca_value_usd:,.2f})")
    print(f"   TOTAL : ${total_value_usd:,.2f}")

    print_portfolio_bar(
        portfolio_orca_ratio,
        sol_balance,
        orca_balance,
        prices["sol"],
        prices["orca"]
    )

    # ====================== EQUIVALENTS WITH INITIAL BASELINE DELTAS ======================
    print("\n🔄 Hypothetical Equivalents (USD as common base):")
    if save_to_csv:
        baseline_sol_eq, baseline_orca_eq = get_first_equivalents(CONFIG["CSV_FILENAME"])
        sol_equiv_change = sol_equivalent - baseline_sol_eq
        orca_equiv_change = orca_equivalent - baseline_orca_eq
        sol_equiv_change_usd = sol_equiv_change * prices["sol"]
        orca_equiv_change_usd = orca_equiv_change * prices["orca"]
        
        print(f"   SOL equivalent   : {sol_equivalent:,.6f} SOL  (Δ {sol_equiv_change:+,.6f} | ${sol_equiv_change_usd:+,.2f} vs initial)")
        print(f"   ORCA equivalent  : {orca_equivalent:,.6f} ORCA (Δ {orca_equiv_change:+,.6f} | ${orca_equiv_change_usd:+,.2f} vs initial)")
    else:
        print(f"   SOL equivalent   : {sol_equivalent:,.6f} SOL")
        print(f"   ORCA equivalent  : {orca_equivalent:,.6f} ORCA")
    # =====================================================================================================

    print("\n📈 Price Ratios:")
    print(f"   1 SOL  = {orca_per_sol:,.2f} ORCA")
    print(f"   1 ORCA = {sol_per_orca:,.6f} SOL")

    print("\n💰 Current Prices:")
    print(f"   SOL  = ${prices['sol']:,.2f}")
    print(f"   ORCA = ${prices['orca']:,.4f}")

    # ====================== UPDATED CSV LOGIC WITH NEW COLUMNS ======================
    if save_to_csv:
        # balance changes vs previous row
        prev_sol, prev_orca = get_previous_balances(CONFIG["CSV_FILENAME"])
        
        sol_change = sol_balance - prev_sol
        orca_change = orca_balance - prev_orca
        sol_change_usd = sol_change * prices["sol"]
        orca_change_usd = orca_change * prices["orca"]

        # equivalent changes vs FIRST row (permanent baseline)
        baseline_sol_eq, baseline_orca_eq = get_first_equivalents(CONFIG["CSV_FILENAME"])
        sol_equiv_change = sol_equivalent - baseline_sol_eq
        orca_equiv_change = orca_equivalent - baseline_orca_eq
        sol_equiv_change_usd = sol_equiv_change * prices["sol"]
        orca_equiv_change_usd = orca_equiv_change * prices["orca"]

        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            "sol_balance": round(sol_balance, 9),
            "sol_balance_change": round(sol_change, 9),
            "sol_balance_change_usd": round(sol_change_usd, 2),
            "orca_balance": round(orca_balance, 9),
            "orca_balance_change": round(orca_change, 9),
            "orca_balance_change_usd": round(orca_change_usd, 2),
            "sol_price_usd": round(prices["sol"], 6),
            "orca_price_usd": round(prices["orca"], 6),
            "sol_value_usd": round(sol_value_usd, 2),
            "orca_value_usd": round(orca_value_usd, 2),
            "total_value_usd": round(total_value_usd, 2),
            "sol_equivalent": round(sol_equivalent, 9),
            "orca_equivalent": round(orca_equivalent, 9),
            "sol_equivalent_change": round(sol_equiv_change, 9),
            "orca_equivalent_change": round(orca_equiv_change, 9),
            "sol_equivalent_change_usd": round(sol_equiv_change_usd, 2),
            "orca_equivalent_change_usd": round(orca_equiv_change_usd, 2),
            "orca_per_sol": round(orca_per_sol, 6),
            "sol_per_orca": round(sol_per_orca, 8),
            "portfolio_orca_ratio": round(portfolio_orca_ratio, 6),
            "portfolio_sol_ratio": round(1 - portfolio_orca_ratio, 6),
        }
        fieldnames = list(row.keys())
        file_exists = os.path.isfile(CONFIG["CSV_FILENAME"])
        with open(CONFIG["CSV_FILENAME"], "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                print(f"📄 Created new CSV file: {CONFIG['CSV_FILENAME']}")
            else:
                print(f"📄 Appended manual refresh data to: {CONFIG['CSV_FILENAME']}")
            writer.writerow(row)
        print("   ✅ Portfolio snapshot saved to CSV")
    else:
        print("📄 CSV skipped (automatic refresh)")

    return now_kst


def countdown(refresh_interval: int) -> bool:
    """Live countdown with manual 'r' + Enter refresh trigger.
    Returns True if manual refresh was triggered, False if timer finished normally."""
    for remaining in range(refresh_interval, 0, -1):
        msg = f"⏳ Next refresh in {remaining:2d}s... (press r then Enter to refresh now, Ctrl+C to stop)"
        print(msg, end="\r")
        sys.stdout.flush()
        
        # Non-blocking keyboard check every second
        if select.select([sys.stdin], [], [], 1.0)[0]:
            line = sys.stdin.readline().strip().lower()
            if line in ("r", "refresh"):
                print("\n🔄 Manual refresh triggered!")
                return True  # signal main loop to save next snapshot
        
    # Timer finished normally → no manual trigger
    print(" " * 100, end="\r")
    return False


def main() -> None:
    address = input("\nEnter your Solana wallet address (base58): ").strip()
    if not address:
        print("❌ No address entered. Exiting.")
        return

    print(f"\n📍 Monitoring wallet: {address}")

    if CONFIG["UPDATE_ONCE"]:
        print("🔄 One-time mode enabled (UPDATE_ONCE=True)")
        print("=" * 90)
        fetch_and_display(address, save_to_csv=True)
        print("\n✅ One-time check complete. Exiting.")
    else:
        print(f"🔄 Live mode enabled — refreshing every {CONFIG['REFRESH_INTERVAL']} seconds")
        print("   Press 'r' then Enter anytime during countdown to force refresh + save to CSV")
        print("   Ctrl+C to stop\n")
        print("=" * 90)

        save_to_csv_next = True  # first run always saves
        try:
            while True:
                clear_screen()
                fetch_and_display(address, save_to_csv=save_to_csv_next)
                
                # Reset flag (next refresh will skip CSV unless manual trigger)
                save_to_csv_next = False
                
                # Run countdown and check if user triggered manual refresh
                manual_triggered = countdown(CONFIG["REFRESH_INTERVAL"])
                if manual_triggered:
                    save_to_csv_next = True  # next immediate refresh will save to CSV

        except KeyboardInterrupt:
            clear_screen()
            print("\n👋 Live monitoring stopped by user.")
            print(f"   Last data saved to: {CONFIG['CSV_FILENAME']}")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
