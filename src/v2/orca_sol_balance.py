import requests
import csv
import os
from datetime import datetime
import zoneinfo
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
    "BAR_WIDTH": 80,                    # Total width of the bar (recommended: 50-80)
    "BAR_CHAR_SOL": "█",                # Character for SOL portion (left side)
    "BAR_CHAR_ORCA": "─",               # Character for ORCA portion (right side)
    "BAR_BG": "─",                      # Background character for empty space
    "BAR_SOL_COLOR": "",                # Leave empty for no color (or use ANSI if desired later)
    "BAR_ORCA_COLOR": "",               # Leave empty for no color
    
    # Label settings
    "SHOW_HEADER_LABELS": True,         # Show "SOL" and "ORCA" above the bar
    "SHOW_50_PERCENT_MARKER": True,     # Show centered 50% line
    "PERCENT_PRECISION": 1,             # Decimal places for percentages (0 or 1 recommended)
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


def print_portfolio_bar(orca_ratio: float):
    """Print a clean, professional portfolio allocation bar with full config support."""
    sol_ratio = 1.0 - orca_ratio
    width = CONFIG["BAR_WIDTH"]
    
    # Calculate number of blocks for each side
    sol_blocks = int(round(sol_ratio * width))
    orca_blocks = width - sol_blocks
    
    # Build the bar
    bar = (
        CONFIG["BAR_CHAR_SOL"] * sol_blocks +
        CONFIG["BAR_BG"] * 0 +                    # No middle gap for clean look
        CONFIG["BAR_CHAR_ORCA"] * orca_blocks
    )
    
    # Format percentages
    precision = CONFIG["PERCENT_PRECISION"]
    sol_percent = f"{sol_ratio*100:.{precision}f}% SOL"
    orca_percent = f"{orca_ratio*100:.{precision}f}% ORCA"
    
    print("\n📊 Portfolio Allocation Visual:")
    
    # Header labels (SOL ........ ORCA)
    if CONFIG["SHOW_HEADER_LABELS"]:
        header_padding = " " * (width - 10)
        print(f"   SOL{header_padding}ORCA")
    
    # The actual bar
    print(f"   {bar}")
    
    # Percentage labels with smart spacing
    total_label_len = len(sol_percent) + len(orca_percent)
    spacing = width - total_label_len + 6   # +6 gives nice breathing room
    label_line = f"   {sol_percent}{' ' * spacing}{orca_percent}"
    print(label_line)
    
    # Centered 50% marker
    if CONFIG["SHOW_50_PERCENT_MARKER"]:
        print(f"   {'50%':^{width}}")


def main() -> None:
    print("🔍 Solana + ORCA Balance & Price Checker (KST)")
    print("=" * 85)
    
    address = input("\nEnter your Solana wallet address (base58): ").strip()
    if not address:
        print("❌ No address entered. Exiting.")
        return

    print(f"\n📍 Wallet: {address}")
    print("⏳ Fetching data from Solana RPC and CoinGecko...\n")

    try:
        sol_balance = get_sol_balance(CONFIG["RPC_URL"], address)
        orca_balance = get_orca_balance(CONFIG["RPC_URL"], address, CONFIG["ORCA_MINT"])
        prices = get_prices()

        sol_value_usd = sol_balance * prices["sol"]
        orca_value_usd = orca_balance * prices["orca"]
        total_value_usd = sol_value_usd + orca_value_usd

        # Equivalents using USD as the common base
        sol_equivalent = sol_balance + (orca_value_usd / prices["sol"]) if prices["sol"] > 0 else sol_balance
        orca_equivalent = orca_balance + (sol_value_usd / prices["orca"]) if prices["orca"] > 0 else orca_balance

        # Price ratios
        sol_per_orca = prices["sol"] / prices["orca"] if prices["orca"] > 0 else 0.0
        orca_per_sol = prices["orca"] / prices["sol"] if prices["sol"] > 0 else 0.0

        # Portfolio ratios
        portfolio_orca_ratio = orca_value_usd / total_value_usd if total_value_usd > 0 else 0.0
        portfolio_sol_ratio = sol_value_usd / total_value_usd if total_value_usd > 0 else 0.0

        # KST timestamp
        kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
        now_kst = datetime.now(kst_tz)
        timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")
        timestamp_iso = now_kst.isoformat()

        # CSV row (wallet address omitted for privacy)
        row = {
            "timestamp_kst": timestamp_iso,
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
            "portfolio_sol_ratio": round(portfolio_sol_ratio, 6),
        }

        # Save to CSV
        fieldnames = list(row.keys())
        file_exists = os.path.isfile(CONFIG["CSV_FILENAME"])
        with open(CONFIG["CSV_FILENAME"], "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                print(f"📄 Created new CSV file: {CONFIG['CSV_FILENAME']}")
            else:
                print(f"📄 Appended to: {CONFIG['CSV_FILENAME']}")
            writer.writerow(row)

        # Console output
        print("✅ SUCCESS!")
        print(f"   📄 Data saved to: {CONFIG['CSV_FILENAME']}")
        print(f"\n🕒 Time (KST): {timestamp_str}")
        
        print("\n📊 Current Balances:")
        print(f"   SOL   : {sol_balance:,.6f} SOL  (${sol_value_usd:,.2f})")
        print(f"   ORCA  : {orca_balance:,.6f} ORCA (${orca_value_usd:,.2f})")
        print(f"   TOTAL : ${total_value_usd:,.2f}")

        # Visual portfolio bar (now fully configurable)
        print_portfolio_bar(portfolio_orca_ratio)

        print("\n🔄 Hypothetical Equivalents (USD as common base):")
        print(f"   SOL equivalent   : {sol_equivalent:,.6f} SOL")
        print(f"   ORCA equivalent  : {orca_equivalent:,.6f} ORCA")

        print("\n📈 Price Ratios:")
        print(f"   1 SOL  = {sol_per_orca:,.2f} ORCA")
        print(f"   1 ORCA = {orca_per_sol:,.6f} SOL")

        print("\n💰 Current Prices:")
        print(f"   SOL  = ${prices['sol']:,.2f}")
        print(f"   ORCA = ${prices['orca']:,.4f}")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
