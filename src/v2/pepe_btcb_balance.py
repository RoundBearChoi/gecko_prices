import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
from typing import Dict, Any
from web3 import Web3

# ========================= CONFIG SECTION =========================
CONFIG = {
    "RPC_URL": "https://bsc-dataseed.binance.org/",
    "CSV_FILENAME": "btcb_pepe_balances.csv",
    "BTCB_CONTRACT": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",   # lowercase is fine here
    "PEPE_CONTRACT": "0x25d887ce7a35172c62febfd67a1856f20faebb00",   # lowercase is fine here
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
    "REFRESH_INTERVAL": 60,          # seconds
    "UPDATE_ONCE": False,            # True = one-time check, False = live mode
}
# ================================================================

def get_bnb_balance(w3: Web3, address: str) -> float:
    balance_wei = w3.eth.get_balance(address)
    return balance_wei / 1_000_000_000_000_000_000

def get_token_balance(w3: Web3, address: str, token_contract: str) -> float:
    ERC20_ABI = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    ]
    contract = w3.eth.contract(address=token_contract, abi=ERC20_ABI)
    raw_balance = contract.functions.balanceOf(address).call()
    decimals = contract.functions.decimals().call()
    return raw_balance / (10 ** decimals)

def get_prices() -> Dict[str, float]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={CONFIG['COINGECKO_IDS']}&vs_currencies={CONFIG['VS_CURRENCY']}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    return {
        "btcb": data.get("binance-bitcoin", {}).get(CONFIG["VS_CURRENCY"], 0.0),
        "pepe": data.get("pepe", {}).get(CONFIG["VS_CURRENCY"], 0.0),
    }

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_portfolio_bar(btcb_ratio: float, btcb_balance: float, pepe_balance: float, 
                       btcb_price: float, pepe_price: float):
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
        pepe_value = pepe_balance * pepe_price
        excess_usd = abs(btcb_value - target_each)
        
        if abs(btcb_value - target_each) < 0.50:
            print("   ✅ Portfolio is already balanced at ~50:50")
        elif btcb_value > target_each:
            btcb_to_sell = excess_usd / btcb_price
            pepe_to_buy = excess_usd / pepe_price
            print(f"   🔄 To reach 50:50 → Sell ~{btcb_to_sell:,.6f} BTCB (~${excess_usd:,.2f} USD) to buy ~{pepe_to_buy:,.0f} PEPE")
        else:
            pepe_to_sell = excess_usd / pepe_price
            btcb_to_buy = excess_usd / btcb_price
            print(f"   🔄 To reach 50:50 → Sell ~{pepe_to_sell:,.0f} PEPE (~${excess_usd:,.2f} USD) to buy ~{btcb_to_buy:,.6f} BTCB")
    else:
        print("   ⚠️  Portfolio value too small for rebalancing suggestion")


def fetch_and_display(address: str, w3: Web3, first_run: bool = False):
    kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
    now_kst = datetime.now(kst_tz)
    timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")

    print("🔴 BTCB + PEPE Portfolio Monitor (BSC)")
    print("=" * 90)
    print(f"Wallet  : {address}")
    print(f"Updated : {timestamp_str} (KST)")
    print("=" * 90)

    bnb_balance = get_bnb_balance(w3, address)
    btcb_balance = get_token_balance(w3, address, CONFIG["BTCB_CONTRACT"])
    pepe_balance = get_token_balance(w3, address, CONFIG["PEPE_CONTRACT"])
    prices = get_prices()

    btcb_value_usd = btcb_balance * prices["btcb"]
    pepe_value_usd = pepe_balance * prices["pepe"]
    total_value_usd = btcb_value_usd + pepe_value_usd

    portfolio_btcb_ratio = btcb_value_usd / total_value_usd if total_value_usd > 0 else 0.0

    print("\n📊 Current Balances:")
    print(f"   BNB   : {bnb_balance:,.6f} BNB")
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

    print("\n💰 Current Prices:")
    print(f"   BTCB ≈ ${prices['btcb']:,.2f}")
    print(f"   PEPE  = ${prices['pepe']:,.8f}")

    if first_run:
        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            "bnb_balance": round(bnb_balance, 9),
            "btcb_balance": round(btcb_balance, 9),
            "pepe_balance": round(pepe_balance, 2),
            "btcb_price_usd": round(prices["btcb"], 6),
            "pepe_price_usd": round(prices["pepe"], 8),
            "btcb_value_usd": round(btcb_value_usd, 2),
            "pepe_value_usd": round(pepe_value_usd, 2),
            "total_value_usd": round(total_value_usd, 2),
            "portfolio_btcb_ratio": round(portfolio_btcb_ratio, 6),
        }
        fieldnames = list(row.keys())
        file_exists = os.path.isfile(CONFIG["CSV_FILENAME"])
        with open(CONFIG["CSV_FILENAME"], "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                print(f"📄 Created new CSV file: {CONFIG['CSV_FILENAME']}")
            else:
                print(f"📄 Appended data to: {CONFIG['CSV_FILENAME']}")
            writer.writerow(row)
        print("   ✅ Portfolio snapshot saved to CSV")
    else:
        print("📄 CSV already recorded (skipped)")

    return now_kst


def countdown(refresh_interval: int):
    for remaining in range(refresh_interval, 0, -1):
        print(f"⏳ Next refresh in {remaining:2d} seconds... (Ctrl+C to stop)", end="\r")
        sys.stdout.flush()
        time.sleep(1)
    print(" " * 90, end="\r")


def main() -> None:
    # Connect to BSC
    w3 = Web3(Web3.HTTPProvider(CONFIG["RPC_URL"]))
    if not w3.is_connected():
        print("❌ Failed to connect to BSC network.")
        return

    # === CRITICAL FIX: Convert contracts to checksum addresses ===
    CONFIG["BTCB_CONTRACT"] = w3.to_checksum_address(CONFIG["BTCB_CONTRACT"])
    CONFIG["PEPE_CONTRACT"] = w3.to_checksum_address(CONFIG["PEPE_CONTRACT"])
    # ============================================================

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
        fetch_and_display(address, w3, first_run=True)
    else:
        print(f"🔄 Live mode enabled — refreshing every {CONFIG['REFRESH_INTERVAL']} seconds")
        print("   Press Ctrl+C to stop\n")
        first_run = True
        try:
            while True:
                clear_screen()
                fetch_and_display(address, w3, first_run=first_run)
                first_run = False
                countdown(CONFIG["REFRESH_INTERVAL"])
        except KeyboardInterrupt:
            clear_screen()
            print("\n👋 Live monitoring stopped by user.")
            print(f"   Last data saved to: {CONFIG['CSV_FILENAME']}")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
