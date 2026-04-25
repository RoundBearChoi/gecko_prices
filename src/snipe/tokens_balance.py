import requests
import csv
from datetime import datetime
from decimal import Decimal, getcontext
import sys
import os
import json
import time
from functools import wraps
from typing import Tuple
from zoneinfo import ZoneInfo

# =============================================================================
# CONFIG SECTION - EDIT THESE VARIABLES AS NEEDED
# =============================================================================
FARTCOIN_MINT: str = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
USDC_MINT: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

FARTCOIN_GECKO_ID: str = "fartcoin"
USDC_GECKO_ID: str = "usd-coin"

FARTCOIN_DECIMALS: int = 6
USDC_DECIMALS: int = 6

RPC_URL: str = "https://api.mainnet-beta.solana.com"
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"

CSV_OUTPUT_DIR: str = "."
CSV_FILENAME: str = "solana_portfolio_fart_usdc.csv"

# Absolute maximum precision
getcontext().prec = 50

KST_TZ = ZoneInfo("Asia/Seoul")

# =============================================================================
# RETRY DECORATOR (simple, no extra dependencies)
# =============================================================================
def retry(max_retries: int = 3, delay: int = 1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"❌ All {max_retries} attempts failed: {e}")
                        raise
                    print(f"⚠️  Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

@retry()
def get_token_balance(wallet_address: str, mint: str, decimals: int) -> Decimal:
    """Fetch exact token balance using Solana RPC - SUMS ALL accounts for the mint (max correctness)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_address,
            {"mint": mint},
            {"encoding": "jsonParsed"}
        ]
    }

    response = requests.post(RPC_URL, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()

    total_raw = Decimal("0")
    if "result" in data and data["result"].get("value"):
        for account in data["result"]["value"]:
            try:
                token_info = account["account"]["data"]["parsed"]["info"]["tokenAmount"]
                total_raw += Decimal(token_info["amount"])
            except (KeyError, TypeError, IndexError):
                continue
    return total_raw / Decimal(10 ** decimals) if total_raw > 0 else Decimal("0")


@retry()
def get_current_prices() -> Tuple[Decimal, Decimal]:
    """Reliable CoinGecko prices with precision=full + direct Decimal parsing (absolute max precision)."""
    ids = f"{FARTCOIN_GECKO_ID},{USDC_GECKO_ID}"
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "precision": "full",          # ← Key for maximum decimal places
        "include_last_updated_at": "true"
    }

    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()

    # Parse JSON numbers directly as Decimal - no float loss whatsoever
    data = json.loads(response.text, parse_float=Decimal)

    fart_data = data.get(FARTCOIN_GECKO_ID, {})
    usdc_data = data.get(USDC_GECKO_ID, {})

    fart_price: Decimal = fart_data.get("usd", Decimal("0"))
    usdc_price: Decimal = usdc_data.get("usd", Decimal("1"))

    print(f"✅ CoinGecko prices (full precision) → FARTCOIN: ${fart_price} | USDC: ${usdc_price}")
    if "last_updated_at" in fart_data:
        print(f"   Last updated: {datetime.fromtimestamp(fart_data['last_updated_at'], tz=KST_TZ).strftime('%Y-%m-%d %H:%M:%S KST')}")

    return fart_price, usdc_price


def calculate_rebalance(
    fart_balance: Decimal,
    usdc_balance: Decimal,
    fart_price: Decimal,
    usdc_price: Decimal
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """Calculate exact amounts to sell to reach perfect 50/50 (unchanged - already perfect)."""
    fart_value = fart_balance * fart_price
    usdc_value = usdc_balance * usdc_price
    total_value = fart_value + usdc_value

    if total_value == 0:
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")

    target_value = total_value / Decimal("2")

    if fart_value > target_value:
        excess_fart_value = fart_value - target_value
        sell_fart_ui = excess_fart_value / fart_price
        sell_usdc_ui = Decimal("0")
    elif usdc_value > target_value:
        excess_usdc_value = usdc_value - target_value
        sell_usdc_ui = excess_usdc_value / usdc_price
        sell_fart_ui = Decimal("0")
    else:
        sell_fart_ui = Decimal("0")
        sell_usdc_ui = Decimal("0")

    return sell_fart_ui, sell_usdc_ui, fart_value, usdc_value


def calculate_hypothetical_all_in_fart(
    fart_balance: Decimal,
    usdc_balance: Decimal,
    usdc_price: Decimal,
    fart_price: Decimal
) -> Decimal:
    """Hypothetical: sell ALL USDC into FARTCOIN (unchanged)."""
    usdc_value = usdc_balance * usdc_price
    additional_fart = usdc_value / fart_price if fart_price > 0 else Decimal("0")
    return fart_balance + additional_fart


# =============================================================================
# MAIN SCRIPT
# =============================================================================
def main():
    print("=" * 80)
    print("🚀 Solana FARTCOIN + USDC Portfolio Analyzer - ABSOLUTE MAX PRECISION")
    print("   ✅ precision=full + Decimal parsing • Sum all token accounts • Retries • KST timestamps")
    print("   50/50 rebalance • All-in-FART hypothetical • Persistent CSV")
    print("=" * 80)

    # CLI support for automation
    if len(sys.argv) > 1:
        wallet = sys.argv[1].strip()
        if not (32 <= len(wallet) <= 44 and wallet.isalnum()):
            print("❌ Invalid Solana address from CLI.")
            sys.exit(1)
        print(f"📍 CLI wallet: {wallet}")
    else:
        while True:
            wallet = input("\n🔑 Enter your Solana wallet address (or type 'exit' to quit): ").strip()
            if wallet.lower() == "exit":
                print("👋 Exiting...")
                sys.exit(0)
            if 32 <= len(wallet) <= 44 and wallet.isalnum():
                break
            print("❌ Invalid Solana address format (32-44 base58 characters). Try again.")

    print(f"\n📍 Analyzing wallet: {wallet}")

    print("🔍 Fetching token balances from Solana RPC...")
    fart_balance = get_token_balance(wallet, FARTCOIN_MINT, FARTCOIN_DECIMALS)
    usdc_balance = get_token_balance(wallet, USDC_MINT, USDC_DECIMALS)

    print(f"   FARTCOIN balance: {fart_balance}")
    print(f"   USDC balance:     {usdc_balance}")

    fart_price, usdc_price = get_current_prices()

    sell_fart, sell_usdc, fart_value, usdc_value = calculate_rebalance(
        fart_balance, usdc_balance, fart_price, usdc_price
    )
    total_value = fart_value + usdc_value

    if total_value > 0:
        fart_pct = (fart_value / total_value) * Decimal("100")
        usdc_pct = (usdc_value / total_value) * Decimal("100")
    else:
        fart_pct = usdc_pct = Decimal("0")

    hypothetical_fart = calculate_hypothetical_all_in_fart(
        fart_balance, usdc_balance, usdc_price, fart_price
    )

    # Detailed summary
    now_kst = datetime.now(KST_TZ)
    print("\n" + "=" * 80)
    print("📊 PORTFOLIO SUMMARY")
    print("=" * 80)
    print(f"Wallet                  : {wallet}")
    print(f"Timestamp (KST)         : {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"FARTCOIN balance        : {fart_balance} (${fart_value:,.4f})")
    print(f"USDC balance            : {usdc_balance} (${usdc_value:,.4f})")
    print(f"Total portfolio value   : ${total_value:,.4f} USD")
    print(f"FARTCOIN % of portfolio : {fart_pct:.6f}%")
    print(f"USDC % of portfolio     : {usdc_pct:.6f}%")
    print("-" * 80)

    if sell_fart > 0:
        print(f"🔄 To reach 50/50: Sell {sell_fart} FARTCOIN")
    elif sell_usdc > 0:
        print(f"🔄 To reach 50/50: Sell {sell_usdc} USDC")
    else:
        print("✅ Portfolio is already perfectly balanced at 50/50!")

    print(f"🚀 Hypothetical all-in FARTCOIN: {hypothetical_fart}")
    print("=" * 80)

    if fart_price == 0:
        print("⚠️  Note: FARTCOIN price returned zero - calculations may be inaccurate.")

    # CSV export (appends to single file, full precision)
    csv_path = os.path.join(CSV_OUTPUT_DIR, CSV_FILENAME)
    fieldnames = [
        "timestamp_kst", "wallet_address", "fartcoin_balance", "usdc_balance",
        "fartcoin_price_usd", "usdc_price_usd", "fartcoin_value_usd",
        "usdc_value_usd", "total_value_usd", "fartcoin_pct", "usdc_pct",
        "sell_fartcoin_to_50_50", "sell_usdc_to_50_50",
        "hypothetical_fartcoin_equivalent"
    ]

    row = {
        "timestamp_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "wallet_address": wallet,
        "fartcoin_balance": str(fart_balance),
        "usdc_balance": str(usdc_balance),
        "fartcoin_price_usd": str(fart_price),
        "usdc_price_usd": str(usdc_price),
        "fartcoin_value_usd": str(fart_value),
        "usdc_value_usd": str(usdc_value),
        "total_value_usd": str(total_value),
        "fartcoin_pct": str(fart_pct),
        "usdc_pct": str(usdc_pct),
        "sell_fartcoin_to_50_50": str(sell_fart),
        "sell_usdc_to_50_50": str(sell_usdc),
        "hypothetical_fartcoin_equivalent": str(hypothetical_fart)
    }

    file_exists = os.path.exists(csv_path)
    try:
        mode = "a" if file_exists else "w"
        with open(csv_path, mode=mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        print(f"💾 Results appended to: {csv_path}")
    except Exception as e:
        print(f"❌ CSV export failed: {e}")

    print("\n✅ Script completed successfully!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Script interrupted by user.")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
