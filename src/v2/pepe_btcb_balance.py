import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
import select  # ← for non-blocking 'r' key check
from typing import Dict, Any
from web3 import Web3

# ========================= CONFIG SECTION =========================
CONFIG = {
    "RPC_URL": "https://bsc-dataseed.binance.org/",
    "CSV_FILENAME": "btcb_pepe_balances.csv",
    "BTCB_CONTRACT": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",
    "PEPE_CONTRACT": "0x25d887ce7a35172c62febfd67a1856f20faebb00",
    "COINGECKO_IDS": "binance-bitcoin,pepe",
    "VS_CURRENCY": "usd",
    "KST_TIMEZONE": "Asia/Seoul",
    
    # ==================== VISUAL BAR SETTINGS ====================
    "BAR_WIDTH": 80,
    "BAR_CHAR_BTCB": "█",
    "BAR_CHAR_PEPE": "─",
    "BAR_BG": "─",
    
    # Label settings
    "SHOW_HEADER_LABELS": True,
    "SHOW_50_PERCENT_MARKER": True,
    "PERCENT_PRECISION": 1,
    
    # ==================== LIVE MONITOR SETTINGS ====================
    "REFRESH_INTERVAL": 60*5,
    "UPDATE_ONCE": False,
    
    # ==================== RATE LIMIT SETTINGS ====================
    "RATE_LIMIT_WAIT_SECONDS": 180,  # 3 minutes FIXED wait on rate limit (no backoff)
}
# ================================================================

# ====================== HELPER FUNCTIONS ======================
def get_previous_balances(csv_filename: str) -> tuple[float, float]:
    """Return previous (btcb_balance, pepe_balance) from the LAST CSV row.
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
                float(last_row.get("btcb_balance", 0)),
                float(last_row.get("pepe_balance", 0))
            )
    except Exception as e:
        print(f"⚠️  Could not read previous balances for delta calculation: {e}")
        return 0.0, 0.0


def get_first_equivalents(csv_filename: str) -> tuple[float, float]:
    """Return (btcb_equivalent, pepe_equivalent) from the FIRST row in the CSV.
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
                float(first_row.get("btcb_equivalent", 0)),
                float(first_row.get("pepe_equivalent", 0))
            )
    except Exception as e:
        print(f"⚠️  Could not read first equivalents for delta calculation: {e}")
        return 0.0, 0.0
# ================================================================

def _handle_rate_limit(error_msg: str = "") -> bool:
    """Return True if the error looks like a rate limit (used by both BSC and CoinGecko)."""
    if not error_msg:
        return False
    msg_lower = error_msg.lower()
    return any(term in msg_lower for term in ["rate limit", "too many requests", "429", "rate exceeded"])


def get_token_balance(w3: Web3, address: str, token_contract: str) -> float:
    ERC20_ABI = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    ]
    wait_time = CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            contract = w3.eth.contract(address=token_contract, abi=ERC20_ABI)
            raw_balance = contract.functions.balanceOf(address).call()
            decimals = contract.functions.decimals().call()
            return raw_balance / (10 ** decimals)
        except Exception as e:
            error_str = str(e)
            if (isinstance(e, requests.exceptions.HTTPError) and e.response is not None and e.response.status_code == 429) or \
               _handle_rate_limit(error_str):
                if attempt < max_attempts - 1:
                    print(f"⚠️  BSC RPC rate limit detected (token balance). Waiting {wait_time} seconds... ({attempt+1}/{max_attempts})")
                    time.sleep(wait_time)
                    continue
            raise
    
    raise Exception("Failed to get token balance after maximum rate-limit retries")


def get_prices() -> Dict[str, float]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={CONFIG['COINGECKO_IDS']}&vs_currencies={CONFIG['VS_CURRENCY']}&precision=full"
    wait_time = CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data: Dict[str, Any] = response.json()
            return {
                "btcb": data.get("binance-bitcoin", {}).get(CONFIG["VS_CURRENCY"], 0.0),
                "pepe": data.get("pepe", {}).get(CONFIG["VS_CURRENCY"], 0.0),
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


def print_portfolio_bar(btcb_ratio: float, btcb_balance: float, pepe_balance: float, 
                       btcb_price: float, pepe_price: float):
    """(Unchanged from your original)"""
    pepe_ratio = 1.0 - btcb_ratio
    width = CONFIG["BAR_WIDTH"]
    
    btcb_blocks = int(round(btcb_ratio * width))
    pepe_blocks = width - btcb_blocks
    
    bar = CONFIG["BAR_CHAR_BTCB"] * btcb_blocks + CONFIG["BAR_CHAR_PEPE"] * pepe_blocks
    
    precision = CONFIG["PERCENT_PRECISION"]
    btcb_percent = f"{btcb_ratio*100:.{precision}f}% BTCB"
    pepe_percent = f"{pepe_ratio*100:.{precision}f}% PEPE"
    
    print("\n📊 Portfolio Allocation Visual:")
    
    if CONFIG["SHOW_HEADER_LABELS"]:
        header_padding = " " * (width - 12)
        print(f"   BTCB{header_padding}PEPE")
    
    print(f"   {bar}")
    
    total_label_len = len(btcb_percent) + len(pepe_percent)
    spacing = width - total_label_len + 8
    label_line = f"   {btcb_percent}{' ' * spacing}{pepe_percent}"
    print(label_line)
    
    if CONFIG["SHOW_50_PERCENT_MARKER"]:
        print(f"   {'50%':^{width}}")

    total_value_usd = btcb_balance * btcb_price + pepe_balance * pepe_price
    if total_value_usd > 1.0:
        target_each = total_value_usd / 2.0
        btcb_value = btcb_balance * btcb_price
        excess_usd = btcb_value - target_each
        
        if excess_usd >= 0:
            btcb_to_sell = excess_usd / btcb_price
            pepe_to_buy = excess_usd / pepe_price
            print(f"   🔄 To reach perfect 50:50 → Sell ~{btcb_to_sell:,.6f} BTCB (~${excess_usd:,.2f} USD) to buy ~{pepe_to_buy:,.0f} PEPE")
        else:
            pepe_to_sell = abs(excess_usd) / pepe_price
            btcb_to_buy = abs(excess_usd) / btcb_price
            print(f"   🔄 To reach perfect 50:50 → Sell ~{pepe_to_sell:,.0f} PEPE (~${abs(excess_usd):,.2f} USD) to buy ~{btcb_to_buy:,.6f} BTCB")
    else:
        print("   ⚠️  Portfolio value too small for rebalancing suggestion")


def fetch_and_display(address: str, w3: Web3, save_to_csv: bool = False):
    """Shared function to fetch data and print everything.
    CSV is written only when save_to_csv=True (first run + manual refresh)."""
    kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
    now_kst = datetime.now(kst_tz)
    timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")

    print("🔴 BTCB + PEPE Portfolio Monitor (BSC)")
    print("=" * 90)
    print(f"Wallet  : {address}")
    print(f"Updated : {timestamp_str} (KST)")
    print("=" * 90)

    btcb_balance = get_token_balance(w3, address, CONFIG["BTCB_CONTRACT"])
    pepe_balance = get_token_balance(w3, address, CONFIG["PEPE_CONTRACT"])
    prices = get_prices()

    btcb_value_usd = btcb_balance * prices["btcb"]
    pepe_value_usd = pepe_balance * prices["pepe"]
    total_value_usd = btcb_value_usd + pepe_value_usd

    portfolio_btcb_ratio = btcb_value_usd / total_value_usd if total_value_usd > 0 else 0.0

    # === CLEARER PRICE RATIOS (intuitive names) ===
    pepe_per_btcb = prices["btcb"] / prices["pepe"] if prices["pepe"] > 0 else 0.0
    btcb_per_pepe = prices["pepe"] / prices["btcb"] if prices["btcb"] > 0 else 0.0

    # === Equivalents & ratios ===
    btcb_equivalent = btcb_balance + (pepe_value_usd / prices["btcb"]) if prices["btcb"] > 0 else btcb_balance
    pepe_equivalent = pepe_balance + (btcb_value_usd / prices["pepe"]) if prices["pepe"] > 0 else pepe_balance
    portfolio_pepe_ratio = 1.0 - portfolio_btcb_ratio

    print("\n📊 Current Balances:")
    print(f"   BTCB  : {btcb_balance:,.6f} BTCB  (${btcb_value_usd:,.2f})")
    print(f"   PEPE  : {pepe_balance:,.0f} PEPE (${pepe_value_usd:,.2f})")
    print(f"   TOTAL (BTCB+PEPE): ${total_value_usd:,.2f}")

    print_portfolio_bar(
        portfolio_btcb_ratio,
        btcb_balance,
        pepe_balance,
        prices["btcb"],
        prices["pepe"]
    )

    # ====================== EQUIVALENTS WITH INITIAL BASELINE DELTAS ======================
    print("\n🔄 Hypothetical Equivalents (USD as common base):")
    if save_to_csv:
        baseline_btcb_eq, baseline_pepe_eq = get_first_equivalents(CONFIG["CSV_FILENAME"])
        btcb_equiv_change = btcb_equivalent - baseline_btcb_eq
        pepe_equiv_change = pepe_equivalent - baseline_pepe_eq
        btcb_equiv_change_usd = btcb_equiv_change * prices["btcb"]
        pepe_equiv_change_usd = pepe_equiv_change * prices["pepe"]
        
        print(f"   BTCB equivalent : {btcb_equivalent:,.6f} BTCB  (Δ {btcb_equiv_change:+,.6f} | ${btcb_equiv_change_usd:+,.2f} vs initial)")
        print(f"   PEPE equivalent : {pepe_equivalent:,.0f} PEPE   (Δ {pepe_equiv_change:+,.0f} | ${pepe_equiv_change_usd:+,.2f} vs initial)")
    else:
        print(f"   BTCB equivalent : {btcb_equivalent:,.6f} BTCB")
        print(f"   PEPE equivalent : {pepe_equivalent:,.0f} PEPE")
    # =====================================================================================================

    print("\n📈 Price Ratios:")
    print(f"   1 BTCB = {pepe_per_btcb:,.0f} PEPE")
    print(f"   1 PEPE = {btcb_per_pepe:.14e} BTCB")

    print("\n💰 Current Prices:")
    print(f"   BTCB ≈ ${prices['btcb']:,.2f}")
    print(f"   PEPE  = ${prices['pepe']:,.18f}")

    # ====================== UPDATED CSV LOGIC ======================
    if save_to_csv:
        # balance changes vs previous row (unchanged)
        prev_btcb, prev_pepe = get_previous_balances(CONFIG["CSV_FILENAME"])
        
        btcb_change = btcb_balance - prev_btcb
        pepe_change = pepe_balance - prev_pepe
        btcb_change_usd = btcb_change * prices["btcb"]
        pepe_change_usd = pepe_change * prices["pepe"]

        # equivalent changes vs FIRST row (permanent baseline)
        baseline_btcb_eq, baseline_pepe_eq = get_first_equivalents(CONFIG["CSV_FILENAME"])
        btcb_equiv_change = btcb_equivalent - baseline_btcb_eq
        pepe_equiv_change = pepe_equivalent - baseline_pepe_eq
        btcb_equiv_change_usd = btcb_equiv_change * prices["btcb"]
        pepe_equiv_change_usd = pepe_equiv_change * prices["pepe"]

        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            "btcb_balance": round(btcb_balance, 9),
            "btcb_balance_change": round(btcb_change, 9),
            "btcb_balance_change_usd": round(btcb_change_usd, 2),
            "pepe_balance": round(pepe_balance, 2),
            "pepe_balance_change": round(pepe_change, 2),
            "pepe_balance_change_usd": round(pepe_change_usd, 2),
            "btcb_price_usd": round(prices["btcb"], 6),
            "pepe_price_usd": round(prices["pepe"], 18),
            "btcb_value_usd": round(btcb_value_usd, 2),
            "pepe_value_usd": round(pepe_value_usd, 2),
            "total_value_usd": round(total_value_usd, 2),
            "btcb_equivalent": round(btcb_equivalent, 9),
            "pepe_equivalent": round(pepe_equivalent, 2),
            "btcb_equivalent_change": round(btcb_equiv_change, 9),
            "pepe_equivalent_change": round(pepe_equiv_change, 2),
            "btcb_equivalent_change_usd": round(btcb_equiv_change_usd, 2),
            "pepe_equivalent_change_usd": round(pepe_equiv_change_usd, 2),
            "pepe_per_btcb": round(pepe_per_btcb, 2),
            "btcb_per_pepe": round(btcb_per_pepe, 15),
            "portfolio_btcb_ratio": round(portfolio_btcb_ratio, 6),
            "portfolio_pepe_ratio": round(portfolio_pepe_ratio, 6),
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
    # =============================================================

    return now_kst


def countdown(refresh_interval: int) -> bool:
    """Live countdown with manual 'r' + Enter refresh trigger.
    Returns True if manual refresh was triggered, False if timer finished normally."""
    for remaining in range(refresh_interval, 0, -1):
        msg = f"⏳ Next refresh in {remaining:2d}s... (press r then Enter to refresh now, Ctrl+C to stop)"
        print(msg, end="\r")
        sys.stdout.flush()
        
        if select.select([sys.stdin], [], [], 1.0)[0]:
            line = sys.stdin.readline().strip().lower()
            if line in ("r", "refresh"):
                print("\n🔄 Manual refresh triggered!")
                return True
        
    print(" " * 100, end="\r")
    return False


def main() -> None:
    w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
    if not w3.is_connected():
        print("❌ Failed to connect to BSC network.")
        return

    CONFIG["BTCB_CONTRACT"] = w3.to_checksum_address(CONFIG["BTCB_CONTRACT"])
    CONFIG["PEPE_CONTRACT"] = w3.to_checksum_address(CONFIG["PEPE_CONTRACT"])

    address_input = input("\nEnter your BSC wallet address (0x...): ").strip()
    if not address_input:
        print("❌ No address entered. Exiting.")
        return

    try:
        address = w3.to_checksum_address(address_input)
        print(f"\n📍 Monitoring wallet: {address}")
    except Exception:
        print("❌ Invalid BSC address format!")
        return

    if CONFIG["UPDATE_ONCE"]:
        print("🔄 One-time mode enabled")
        fetch_and_display(address, w3, save_to_csv=True)
    else:
        print(f"🔄 Live mode enabled — refreshing every {CONFIG['REFRESH_INTERVAL']} seconds")
        print("   Press 'r' then Enter anytime during countdown to force refresh + save to CSV")
        print("   Ctrl+C to stop\n")
        
        save_to_csv_next = True  # first run always saves
        try:
            while True:
                clear_screen()
                fetch_and_display(address, w3, save_to_csv=save_to_csv_next)
                
                save_to_csv_next = False
                
                manual_triggered = countdown(CONFIG["REFRESH_INTERVAL"])
                if manual_triggered:
                    save_to_csv_next = True

        except KeyboardInterrupt:
            clear_screen()
            print("\n👋 Live monitoring stopped by user.")
            print(f"   Last data saved to: {CONFIG['CSV_FILENAME']}")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
