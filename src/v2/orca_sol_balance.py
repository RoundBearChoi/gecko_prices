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


def main() -> None:
    print("🔍 Solana + ORCA Balance & Price Checker (KST)")
    print("=" * 80)
    
    address = input("\nEnter your Solana wallet address (base58): ").strip()
    if not address:
        print("❌ No address entered. Exiting.")
        return

    print(f"\n📍 Wallet: {address}")
    print("⏳ Fetching data...\n")

    try:
        sol_balance = get_sol_balance(CONFIG["RPC_URL"], address)
        orca_balance = get_orca_balance(CONFIG["RPC_URL"], address, CONFIG["ORCA_MINT"])
        prices = get_prices()

        # Calculate USD values first (USD is used as the common base)
        sol_value_usd = sol_balance * prices["sol"]
        orca_value_usd = orca_balance * prices["orca"]
        total_value_usd = sol_value_usd + orca_value_usd

        # Hypothetical equivalents using USD as the intermediate base (most accurate method)
        # This avoids directional bias from using only sol_per_orca or orca_per_sol
        sol_equivalent = sol_balance + (orca_value_usd / prices["sol"]) if prices["sol"] > 0 else sol_balance
        orca_equivalent = orca_balance + (sol_value_usd / prices["orca"]) if prices["orca"] > 0 else orca_balance

        # Price ratios for display only
        sol_per_orca = prices["sol"] / prices["orca"] if prices["orca"] > 0 else 0.0   # Large number
        orca_per_sol = prices["orca"] / prices["sol"] if prices["sol"] > 0 else 0.0   # Small number

        # Portfolio allocation ratios
        portfolio_orca_ratio = orca_value_usd / total_value_usd if total_value_usd > 0 else 0.0
        portfolio_sol_ratio = sol_value_usd / total_value_usd if total_value_usd > 0 else 0.0

        # KST timestamp
        kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
        now_kst = datetime.now(kst_tz)
        timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")
        timestamp_iso = now_kst.isoformat()

        # CSV row (no wallet address)
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
        
        print("\n📊 Balances:")
        print(f"   SOL   : {sol_balance:,.6f} SOL  (${sol_value_usd:,.2f})")
        print(f"   ORCA  : {orca_balance:,.6f} ORCA (${orca_value_usd:,.2f})")
        print(f"   TOTAL : ${total_value_usd:,.2f}")

        print("\n🔄 Hypothetical Equivalents (using USD as common base):")
        print(f"   SOL equivalent   : {sol_equivalent:,.6f} SOL")
        print(f"   ORCA equivalent  : {orca_equivalent:,.6f} ORCA")

        print("\n📈 Price Ratios:")
        print(f"   1 SOL  = {sol_per_orca:,.2f} ORCA")
        print(f"   1 ORCA = {orca_per_sol:,.6f} SOL")

        print("\n📊 Portfolio Allocation:")
        print(f"   ORCA share : {portfolio_orca_ratio:,.4f} ({portfolio_orca_ratio*100:,.2f}%)")
        print(f"   SOL share  : {portfolio_sol_ratio:,.4f} ({portfolio_sol_ratio*100:,.2f}%)")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
