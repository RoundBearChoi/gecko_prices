import json
from decimal import Decimal, getcontext
import requests
import csv
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
from pathlib import Path

# ==================== CONFIG SECTION ====================
CONFIG = {
    "RPC_URL": "https://api.mainnet-beta.solana.com",          # Public RPC (rate-limited). Replace with Helius/QuickNode/Ankr for production use
    "COINGECKO_BASE": "https://api.coingecko.com/api/v3",
    "TOKENS_FILE": "tokens_list.json",                         # JSON file with symbol, id, mint for each token
    "KST_TZ": "Asia/Seoul",
    "DECIMAL_PRECISION": 50,                                   # Very high precision for all calculations
    "CSV_OUTPUT_DIR": Path("wallet_data"),
    "CSV_FILENAME_TEMPLATE": "solana_meme_portfolio_{timestamp}.csv",
    "INCLUDE_MINT_IN_CSV": True,
}

# Set global Decimal precision once (affects all Decimal operations)
getcontext().prec = CONFIG["DECIMAL_PRECISION"]

# SPL Token program ID (standard for all Solana tokens)
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
# =======================================================

def load_tokens() -> list[dict]:
    """Load the list of tokens from tokens_list.json."""
    file_path = Path(CONFIG["TOKENS_FILE"])
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        
        if not isinstance(tokens, list):
            raise ValueError("JSON must be an array [] of token objects")
        
        for i, token in enumerate(tokens):
            if not all(key in token for key in ("symbol", "id", "mint")):
                raise ValueError(f"Token at index {i} missing required keys: symbol, id, mint")
            if not token["mint"]:
                raise ValueError(f"Token at index {i} has empty mint address")
        
        print(f"Loaded {len(tokens)} tokens from {CONFIG['TOKENS_FILE']}")
        return tokens
    
    except FileNotFoundError:
        print(f"Error: {CONFIG['TOKENS_FILE']} not found.")
        print("→ Please create it in the same folder as this script using the JSON I provided in the previous message.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {CONFIG['TOKENS_FILE']}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading tokens: {e}")
        sys.exit(1)


def get_all_token_accounts(wallet_address: str) -> dict[str, dict]:
    """Single RPC call to fetch ALL token accounts for the wallet."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"programId": TOKEN_PROGRAM_ID},
            {"encoding": "jsonParsed"}
        ]
    }
    response = requests.post(CONFIG["RPC_URL"], json=payload, timeout=20)
    response.raise_for_status()
    result = response.json()

    if "error" in result:
        raise Exception(f"Solana RPC error: {result['error']}")

    accounts = result.get("result", {}).get("value", [])
    token_data: dict[str, dict] = {}

    for acc in accounts:
        parsed = acc.get("account", {}).get("data", {}).get("parsed", {})
        if parsed.get("type") != "account":
            continue
        info = parsed.get("info", {})
        mint = info.get("mint")
        if not mint:
            continue

        token_amount = info.get("tokenAmount", {})
        raw_amount_str = token_amount.get("amount", "0")
        decimals = token_amount.get("decimals", 0)

        if mint in token_data:
            current_raw = int(token_data[mint]["raw_amount"])
            new_raw = int(raw_amount_str)
            token_data[mint]["raw_amount"] = str(current_raw + new_raw)
        else:
            token_data[mint] = {
                "raw_amount": raw_amount_str,
                "decimals": decimals
            }

    return token_data


def get_prices(gecko_ids: list[str]) -> dict[str, Decimal]:
    """Batch fetch current USD prices from CoinGecko."""
    if not gecko_ids:
        return {}
    ids_str = ",".join(gecko_ids)
    url = f"{CONFIG['COINGECKO_BASE']}/simple/price"
    params = {
        "ids": ids_str,
        "vs_currencies": "usd"
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    prices = {}
    for gid, price_info in data.items():
        if isinstance(price_info, dict) and "usd" in price_info:
            price_str = str(price_info["usd"])
            prices[gid] = Decimal(price_str)
        else:
            prices[gid] = Decimal("0")
    return prices


def main():
    print("=== Solana Meme Coin Portfolio Tracker (CoinGecko + RPC) ===\n")
    wallet = input("Enter your Solana wallet address: ").strip()
    if not wallet:
        print("No wallet address provided. Exiting.")
        return

    # 1. Load tokens from JSON
    tokens = load_tokens()
    gecko_ids = [t["id"] for t in tokens]

    # 2. Batch price fetch
    print("\nFetching USD prices from CoinGecko (free tier)...")
    prices = get_prices(gecko_ids)

    # 3. Fetch precise token balances
    print("Fetching token balances from Solana RPC...")
    try:
        token_accounts = get_all_token_accounts(wallet)
    except Exception as e:
        print(f"RPC error: {e}")
        print("Tip: Public RPCs are rate-limited. Consider a free Helius.dev or Ankr RPC key in CONFIG.")
        return

    # 4. Build portfolio with full Decimal math
    portfolio = []
    total_usd = Decimal("0")

    for token in tokens:
        gid = token["id"]
        mint = token["mint"]
        symbol = token["symbol"]

        price = prices.get(gid, Decimal("0"))

        # Get balance (0 if not held)
        if mint in token_accounts:
            info = token_accounts[mint]
            raw = Decimal(info["raw_amount"])
            dec = info["decimals"]
            balance = raw / (Decimal(10) ** dec)
        else:
            balance = Decimal("0")

        value_usd = balance * price
        total_usd += value_usd

        portfolio.append({
            "gecko_id": gid,
            "symbol": symbol,
            "mint": mint,
            "balance": balance,
            "price_usd": price,
            "value_usd": value_usd,
        })

    # 5. Percentages and equivalent value
    if total_usd > 0:
        for item in portfolio:
            item["percent"] = (item["value_usd"] / total_usd) * Decimal("100")
            item["equivalent"] = total_usd / item["price_usd"] if item["price_usd"] > 0 else Decimal("0")
    else:
        for item in portfolio:
            item["percent"] = Decimal("0")
            item["equivalent"] = Decimal("0")

    # 6. KST timestamp
    kst_now = datetime.now(ZoneInfo(CONFIG["KST_TZ"]))
    timestamp_str = kst_now.strftime("%Y-%m-%d %H:%M:%S KST")
    filename_ts = kst_now.strftime("%Y%m%d_%H%M%S")

    # 7. CSV output (unchanged)
    csv_dir = Path(CONFIG["CSV_OUTPUT_DIR"])
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / CONFIG["CSV_FILENAME_TEMPLATE"].format(timestamp=filename_ts)

    fieldnames = [
        "timestamp_kst", "total_usd",
        "gecko_id", "symbol", "mint", "token_count",
        "price_usd", "value_usd", "portfolio_percent", "equivalent_tokens_if_all_swapped"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in portfolio:
            writer.writerow({
                "timestamp_kst": timestamp_str,
                "total_usd": str(total_usd),
                "gecko_id": item["gecko_id"],
                "symbol": item["symbol"],
                "mint": item["mint"] if CONFIG["INCLUDE_MINT_IN_CSV"] else "",
                "token_count": str(item["balance"]),
                "price_usd": str(item["price_usd"]),
                "value_usd": str(item["value_usd"]),
                "portfolio_percent": f"{item['percent']:.8f}",
                "equivalent_tokens_if_all_swapped": str(item["equivalent"])
            })

        # TOTAL row
        writer.writerow({
            "timestamp_kst": timestamp_str,
            "total_usd": str(total_usd),
            "gecko_id": "TOTAL",
            "symbol": "",
            "mint": "",
            "token_count": "",
            "price_usd": "",
            "value_usd": str(total_usd),
            "portfolio_percent": "100",
            "equivalent_tokens_if_all_swapped": ""
        })

    # ====================== NEW: CONSOLE PERCENTAGE BREAKDOWN ======================
    print("\n=== 📊 Portfolio Breakdown by USD Value ===")
    if total_usd > 0:
        # Sort by value (highest first) and show only tokens you actually hold
        sorted_portfolio = sorted(portfolio, key=lambda x: x["value_usd"], reverse=True)
        held_tokens = [item for item in sorted_portfolio if item["balance"] > 0]

        if held_tokens:
            print(f"{'Symbol':>12} | {'Balance':>18} | {'Value USD':>15} | {'Portfolio %':>10}")
            print("-" * 62)
            for item in held_tokens:
                print(f"{item['symbol']:>12} | "
                      f"{item['balance']:>18,.8f} | "
                      f"${item['value_usd']:>14,.4f} | "
                      f"{float(item['percent']):>9.4f}%")
        else:
            print("No tokens with positive balance found in the tracked list.")
    else:
        print("Portfolio value is $0.00 — nothing to break down.")

    # Final console summary (unchanged, no wallet address shown)
    print(f"\n✅ Portfolio snapshot saved to: {csv_path}")
    print(f"   Total portfolio value: ${total_usd:,.8f} USD")
    print(f"   Time (KST): {timestamp_str}")
    print(f"   Tokens tracked: {len(portfolio)} / {len(tokens)}")
    print("\nTip: Run this script anytime you want a fresh snapshot. Edit tokens_list.json to add/remove coins.")


if __name__ == "__main__":
    main()
