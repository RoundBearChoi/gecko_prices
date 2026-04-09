import requests
import csv
import os
from datetime import datetime
import zoneinfo
from typing import Dict, Any

# ========================= CONFIG SECTION =========================
# Edit these values easily without touching the rest of the code
CONFIG = {
    "RPC_URL": "https://api.mainnet-beta.solana.com",  
    # Recommended: Use a faster RPC (Helius, QuickNode, Alchemy) if you run this often
    
    "CSV_FILENAME": "solana_orca_balances.csv",  
    
    "ORCA_MINT": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",  
    
    "COINGECKO_IDS": "solana,orca",  
    "VS_CURRENCY": "usd",  
    
    "KST_TIMEZONE": "Asia/Seoul",
}
# ================================================================

def get_sol_balance(rpc_url: str, pubkey: str) -> float:
    """Fetch native SOL balance in SOL units."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [pubkey]
    }
    response = requests.post(rpc_url, json=payload, timeout=20)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    
    if "error" in data:
        raise Exception(f"RPC Error (getBalance): {data['error']}")
    
    lamports = data["result"]["value"]
    return lamports / 1_000_000_000.0


def get_orca_balance(rpc_url: str, pubkey: str, orca_mint: str) -> float:
    """Fetch ORCA token balance. Returns 0.0 if no token account exists."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            pubkey,
            {"mint": orca_mint},
            {"encoding": "jsonParsed"}
        ]
    }
    response = requests.post(rpc_url, json=payload, timeout=20)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    
    if "error" in data:
        raise Exception(f"RPC Error (getTokenAccountsByOwner): {data['error']}")
    
    accounts = data.get("result", {}).get("value", [])
    if not accounts:
        return 0.0
    
    token_info = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
    amount = int(token_info["amount"])
    decimals = int(token_info["decimals"])
    return amount / (10 ** decimals)


def get_prices() -> Dict[str, float]:
    """Fetch current prices from CoinGecko simple price API."""
    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={CONFIG['COINGECKO_IDS']}"
        f"&vs_currencies={CONFIG['VS_CURRENCY']}"
    )
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data: Dict[str, Any] = response.json()
    
    return {
        "sol": data.get("solana", {}).get(CONFIG["VS_CURRENCY"], 0.0),
        "orca": data.get("orca", {}).get(CONFIG["VS_CURRENCY"], 0.0),
    }


def main() -> None:
    print("🔍 Solana + ORCA Balance & Price Checker (KST)")
    print("=" * 75)
    
    address = input("\nEnter your Solana wallet address (base58): ").strip()
    
    if not address:
        print("❌ No address entered. Exiting.")
        return
    
    if len(address) < 32 or len(address) > 44:
        print("⚠️  Warning: Address looks unusually short/long. Proceeding anyway...")
    
    print(f"\n📍 Wallet: {address}")
    print("⏳ Fetching balances from Solana RPC and prices from CoinGecko...\n")

    try:
        # Fetch balances
        sol_balance = get_sol_balance(CONFIG["RPC_URL"], address)
        orca_balance = get_orca_balance(CONFIG["RPC_URL"], address, CONFIG["ORCA_MINT"])
        
        # Fetch prices
        prices = get_prices()
        
        # Calculate USD values
        sol_value = sol_balance * prices["sol"]
        orca_value = orca_balance * prices["orca"]
        total_value = sol_value + orca_value

        # Hypothetical equivalents (cross-conversion)
        if prices["orca"] > 0:
            orca_equivalent = orca_balance + (sol_balance * prices["sol"] / prices["orca"])
        else:
            orca_equivalent = orca_balance
        
        if prices["sol"] > 0:
            sol_equivalent = sol_balance + (orca_balance * prices["orca"] / prices["sol"])
        else:
            sol_equivalent = sol_balance

        # Price ratio: ORCA in terms of SOL
        orca_sol_price_ratio = prices["orca"] / prices["sol"] if prices["sol"] > 0 else 0.0

        # Portfolio allocation ratios (as decimals 0.0 - 1.0)
        portfolio_orca_ratio = orca_value / total_value if total_value > 0 else 0.0
        portfolio_sol_ratio = sol_value / total_value if total_value > 0 else 0.0
        # Note: portfolio_sol_ratio + portfolio_orca_ratio should always equal 1.0 (within floating point precision)

        # KST timezone-aware timestamp
        kst_tz = zoneinfo.ZoneInfo(CONFIG["KST_TIMEZONE"])
        now_kst = datetime.now(kst_tz)
        timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")
        timestamp_iso = now_kst.isoformat()

        # Prepare data row (NO wallet address stored in CSV for privacy)
        row = {
            "timestamp_kst": timestamp_iso,
            "readable_time_kst": timestamp_str,
            "sol_balance": round(sol_balance, 9),
            "orca_balance": round(orca_balance, 9),
            "sol_price_usd": round(prices["sol"], 6),
            "orca_price_usd": round(prices["orca"], 6),
            "sol_value_usd": round(sol_value, 2),
            "orca_value_usd": round(orca_value, 2),
            "total_value_usd": round(total_value, 2),
            "sol_equivalent": round(sol_equivalent, 9),
            "orca_equivalent": round(orca_equivalent, 9),
            "orca_sol_price_ratio": round(orca_sol_price_ratio, 6),
            "portfolio_orca_ratio": round(portfolio_orca_ratio, 6),
            "portfolio_sol_ratio": round(portfolio_sol_ratio, 6),   # NEW
        }

        # Write/append to CSV
        fieldnames = list(row.keys())
        file_exists = os.path.isfile(CONFIG["CSV_FILENAME"])
        
        with open(CONFIG["CSV_FILENAME"], "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                print(f"📄 Created new CSV file: {CONFIG['CSV_FILENAME']}")
            else:
                print(f"📄 Appended to existing CSV: {CONFIG['CSV_FILENAME']}")
            writer.writerow(row)

        # Beautiful console output
        print("✅ SUCCESS!")
        print(f"   📄 Data appended to: {CONFIG['CSV_FILENAME']}")
        print(f"\n🕒 Time (KST): {timestamp_str}")
        
        print("\n📊 Current Balances:")
        print(f"   SOL   : {sol_balance:,.6f} SOL   (${sol_value:,.2f} USD)")
        print(f"   ORCA  : {orca_balance:,.6f} ORCA  (${orca_value:,.2f} USD)")
        print(f"   TOTAL : ${total_value:,.2f} USD")
        
        print("\n🔄 Hypothetical Equivalents:")
        print(f"   SOL equivalent  : {sol_equivalent:,.6f} SOL")
        print(f"   ORCA equivalent : {orca_equivalent:,.6f} ORCA")
        
        print("\n📈 Ratio Metrics:")
        print(f"   ORCA/SOL Price Ratio     : {orca_sol_price_ratio:,.6f}  "
              f"(1 ORCA ≈ {orca_sol_price_ratio:,.6f} SOL)")
        print(f"   Portfolio ORCA Ratio     : {portfolio_orca_ratio:,.4f}  "
              f"({portfolio_orca_ratio*100:,.2f}% ORCA)")
        print(f"   Portfolio SOL Ratio      : {portfolio_sol_ratio:,.4f}  "
              f"({portfolio_sol_ratio*100:,.2f}% SOL)")

        print("\n💰 Market Prices:")
        print(f"   SOL   = ${prices['sol']:,.4f} USD")
        print(f"   ORCA  = ${prices['orca']:,.4f} USD")

    except requests.exceptions.Timeout:
        print("❌ Timeout: RPC or CoinGecko took too long. Try again or use a faster RPC in CONFIG.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network/Connection error: {e}")
        print("💡 Tip: Public Solana RPC can be slow or rate-limited.")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   Possible causes: invalid address, RPC issues, or temporary API downtime.")


if __name__ == "__main__":
    main()
