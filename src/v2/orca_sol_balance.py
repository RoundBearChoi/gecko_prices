import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
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
    "REFRESH_INTERVAL": 60,          # seconds
    "UPDATE_ONCE": False,            # True = one-time run, False = live with countdown
}
# ================================================================

def get_sol_balance(rpc_url: str, pubkey: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]}
    response = requests.post(rpc_url, json=payload, timeout=20)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    if "error" in data:
        raise Exception(f"RPC Error: {data['error']}")
    return data["result"]["value"] / 1_000_000_000.0


def get_orca_balance(rpc_url: str, pubkey: str, orca_mint: str) -> float:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [pubkey, {"mint": orca_mint}, {"encoding": "jsonParsed"}]
    }
    response = requests.post(rpc_url, json=payload, timeout=20)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    if "error" in data:
        raise Exception(f"RPC Error: {data['error']}")
    
    accounts = data.get("result", {}).get("value", [])
    if not accounts:
        return 0.0
    
    token_info = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
    return int(token_info["amount"]) / (10 ** int(token_info["decimals"]))


def get_prices() -> Dict[str, float]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={CONFIG['COINGECKO_IDS']}&vs_currencies={CONFIG['VS_CURRENCY']}"
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    return {
        "sol": data.get("solana", {}).get(CONFIG["VS_CURRENCY"], 0.0),
        "orca": data.get("orca", {}).get(CONFIG["VS_CURRENCY"], 0.0),
    }


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_portfolio_bar(orca_ratio: float, sol_balance: float, orca_balance: float, 
                       sol_price: float, orca_price: float):
    """Print portfolio allocation bar + smart 50:50 rebalancing advice."""
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
        orca_value = orca_balance * orca_price
        excess_usd = abs(sol_value - target_each)
        
        if abs(sol_value - target_each) < 0.50:
            print("   ✅ Portfolio is already balanced at ~50:50")
        elif sol_value > target_each:
            sol_to_sell = excess_usd / sol_price
            orca_to_buy = excess_usd / orca_price
            print(f"   🔄 To reach 50:50 → Sell ~{sol_to_sell:,.6f} SOL (~${excess_usd:,.2f} USD) to buy ~{orca_to_buy:,.4f} ORCA")
        else:
            orca_to_sell = excess_usd / orca_price
            sol_to_buy = excess_usd / sol_price
            print(f"   🔄 To reach 50:50 → Sell ~{orca_to_sell:,.4f} ORCA (~${excess_usd:,.2f} USD) to buy ~{sol_to_buy:,.6f} SOL")
    else:
        print("   ⚠️  Portfolio value too small for rebalancing suggestion")


def fetch_and_display(address: str, first_run: bool = False):
    """Shared function to fetch data and print everything."""
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

    sol_per_orca = prices["sol"] / prices["orca"] if prices["orca"] > 0 else 0.0
    orca_per_sol = prices["orca"] / prices["sol"] if prices["sol"] > 0 else 0.0

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

    print("\n🔄 Hypothetical Equivalents (USD as common base):")
    print(f"   SOL equivalent   : {sol_equivalent:,.6f} SOL")
    print(f"   ORCA equivalent  : {orca_equivalent:,.6f} ORCA")

    print("\n📈 Price Ratios:")
    print(f"   1 SOL  = {sol_per_orca:,.2f} ORCA")
    print(f"   1 ORCA = {orca_per_sol:,.6f} SOL")

    print("\n💰 Current Prices:")
    print(f"   SOL  = ${prices['sol']:,.2f}")
    print(f"   ORCA = ${prices['orca']:,.4f}")

    # CSV — always written exactly once
    if first_run:
        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            "sol_balance": round(sol_balance, 9),
            "orca_balance": round(orca_balance, 9),
            "sol_price_usd": round(prices["sol"], 6),
            "orca_price_usd": round(prices["orca"], 6),
            "sol_value_usd": round(sol_value_usd, 2),
            "orca_value_usd": round(orca_value_usd, 2),
            "total_value_usd": round(total_value_usd, 2),
            "sol_equivalent": round(sol_equivalent, 9),
            "orca_equivalent": round(orca_equivalent, 9),
            "sol_per_orca": round(sol_per_orca, 6),
            "orca_per_sol": round(orca_per_sol, 8),
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
                print(f"📄 Appended initial data to: {CONFIG['CSV_FILENAME']}")
            writer.writerow(row)
        print("   ✅ Portfolio snapshot saved to CSV")
    else:
        print("📄 CSV already recorded (skipped)")

    return now_kst


def countdown(refresh_interval: int):
    """Live countdown that updates every second on the same line."""
    for remaining in range(refresh_interval, 0, -1):
        print(f"⏳ Next refresh in {remaining:2d} seconds... (Ctrl+C to stop)", end="\r")
        sys.stdout.flush()
        time.sleep(1)
    # Clear the countdown line when finished
    print(" " * 80, end="\r")


def main() -> None:
    address = input("\nEnter your Solana wallet address (base58): ").strip()
    if not address:
        print("❌ No address entered. Exiting.")
        return

    print(f"\n📍 Monitoring wallet: {address}")

    if CONFIG["UPDATE_ONCE"]:
        print("🔄 One-time mode enabled (UPDATE_ONCE=True)")
        print("=" * 90)
        fetch_and_display(address, first_run=True)
        print("\n✅ One-time check complete. Exiting.")
    else:
        print(f"🔄 Live mode enabled — refreshing every {CONFIG['REFRESH_INTERVAL']} seconds with countdown")
        print("   CSV will be recorded only once (first refresh)")
        print("   Press Ctrl+C to stop\n")
        print("=" * 90)

        first_run = True
        try:
            while True:
                clear_screen()                    # ← clear only happens in live mode
                fetch_and_display(address, first_run=first_run)
                first_run = False

                # Live countdown (updates in place)
                countdown(CONFIG["REFRESH_INTERVAL"])

        except KeyboardInterrupt:
            clear_screen()
            print("\n👋 Live monitoring stopped by user.")
            print(f"   Last data saved to: {CONFIG['CSV_FILENAME']}")
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    main()
