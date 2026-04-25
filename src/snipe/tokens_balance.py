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
# CONFIG SECTION
# =============================================================================
FARTCOIN_MINT: str = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"
USDC_MINT: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

FARTCOIN_GECKO_ID: str = "fartcoin"
USDC_GECKO_ID: str = "usd-coin"

RPC_URL: str = "https://api.mainnet-beta.solana.com"
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"

CSV_OUTPUT_DIR: str = "."
CSV_FILENAME: str = "solana_portfolio_fart_usdc.csv"

# Assumed slippage for 50/50 rebalance calculations
SLIPPAGE_ASSUMED: Decimal = Decimal("0.01")  # 1% — change as needed

# Console display rounding (math + CSV always use full Decimal precision)
CONSOLE_BALANCE_ROUNDING: int = 6   # Token quantities (FARTCOIN, USDC, sell amounts, hypothetical)
CONSOLE_USD_ROUNDING: int = 3       # USD values, prices, total value

# Absolute maximum precision for all internal math
getcontext().prec = 50

KST_TZ = ZoneInfo("Asia/Seoul")

# Token program IDs for maximum coverage
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# RPC rate-limit handling
RPC_RETRY_DELAY_SECONDS: int = 20
RPC_DELAY_BETWEEN_CALLS_SECONDS: float = 1.5

# =============================================================================
# CONSOLE ROUNDING HELPERS (display only)
# =============================================================================
def console_round_balance(value: Decimal) -> Decimal:
    """Round token balance quantities for console display ONLY."""
    return value.quantize(Decimal('1.' + '0' * CONSOLE_BALANCE_ROUNDING))


def console_round_usd(value: Decimal) -> Decimal:
    """Round USD values/prices for console display ONLY."""
    return value.quantize(Decimal('1.' + '0' * CONSOLE_USD_ROUNDING))


# =============================================================================
# RETRY DECORATOR
# =============================================================================
def retry(max_retries: int = 5, delay: int = RPC_RETRY_DELAY_SECONDS):
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
                    print(f"⚠️  Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

# =============================================================================
# BULK TOKEN BALANCE FETCH (Only 2 RPC calls total)
# =============================================================================

@retry()
def get_all_token_accounts(wallet_address: str) -> dict[str, dict]:
    """Fetch ALL token accounts from BOTH programs in ONLY 2 RPC calls."""
    token_data: dict[str, dict] = {}
    programs = [SPL_TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID]
    
    for program_id in programs:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"programId": program_id},
                {"encoding": "jsonParsed"}
            ]
        }
        
        response = requests.post(RPC_URL, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()

        accounts_found = 0
        if "result" in data and data["result"].get("value"):
            for account in data["result"]["value"]:
                try:
                    parsed = account["account"]["data"]["parsed"]["info"]
                    mint = parsed["mint"]
                    raw_amount = parsed["tokenAmount"]["amount"]
                    decimals = parsed["tokenAmount"]["decimals"]

                    if mint in token_data:
                        current_raw = int(token_data[mint]["raw_amount"])
                        new_raw = int(raw_amount)
                        token_data[mint]["raw_amount"] = str(current_raw + new_raw)
                    else:
                        token_data[mint] = {
                            "raw_amount": raw_amount,
                            "decimals": decimals
                        }
                    accounts_found += 1
                except (KeyError, TypeError, IndexError):
                    continue
        
        print(f"    Processed {accounts_found} token account(s) from {program_id[:8]}... program")
        
        print(f"    Waiting {RPC_DELAY_BETWEEN_CALLS_SECONDS} seconds before next RPC call...")
        time.sleep(RPC_DELAY_BETWEEN_CALLS_SECONDS)

    return token_data


def get_specific_balance(token_accounts: dict, mint: str, token_name: str) -> Decimal:
    """Extract balance for a specific mint. Decimals come from on-chain data."""
    if mint not in token_accounts:
        print(f"    No {token_name} accounts found.")
        return Decimal("0")
    
    info = token_accounts[mint]
    raw = Decimal(info["raw_amount"])
    decimals = info.get("decimals", 6)
    
    balance = raw / Decimal(10 ** decimals)
    print(f"    Found {token_name} balance: {console_round_balance(balance)} (decimals={decimals} from on-chain data)")
    return balance


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

@retry()
def get_current_prices() -> Tuple[Decimal, Decimal]:
    """CoinGecko with precision=full + direct Decimal parsing."""
    ids = f"{FARTCOIN_GECKO_ID},{USDC_GECKO_ID}"
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "precision": "full",
        "include_last_updated_at": "true"
    }

    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()
    data = json.loads(response.text, parse_float=Decimal)

    fart_data = data.get(FARTCOIN_GECKO_ID, {})
    usdc_data = data.get(USDC_GECKO_ID, {})

    fart_price: Decimal = fart_data.get("usd", Decimal("0"))
    usdc_price: Decimal = usdc_data.get("usd", Decimal("1"))

    print(f"\n✅ CoinGecko prices (full precision) → FARTCOIN: ${console_round_usd(fart_price)} | USDC: ${console_round_usd(usdc_price)}")
    if "last_updated_at" in fart_data:
        ts = datetime.fromtimestamp(fart_data['last_updated_at'], tz=KST_TZ)
        print(f"   Last updated: {ts.strftime('%Y-%m-%d %H:%M:%S KST')}")
    return fart_price, usdc_price


def calculate_rebalance(
    fart_balance: Decimal, usdc_balance: Decimal,
    fart_price: Decimal, usdc_price: Decimal,
    slippage: Decimal
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """Calculates sell amounts to reach 50/50 AFTER slippage."""
    fart_value = fart_balance * fart_price
    usdc_value = usdc_balance * usdc_price
    total_value = fart_value + usdc_value
    if total_value == 0:
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    
    if fart_value > usdc_value:
        diff = fart_value - usdc_value
        sell_value = diff / (Decimal("2") - slippage)
        sell_fart = sell_value / fart_price if fart_price > 0 else Decimal("0")
        sell_usdc = Decimal("0")
    elif usdc_value > fart_value:
        diff = usdc_value - fart_value
        sell_value = diff / (Decimal("2") - slippage)
        sell_fart = Decimal("0")
        sell_usdc = sell_value / usdc_price if usdc_price > 0 else Decimal("0")
    else:
        sell_fart = sell_usdc = Decimal("0")
    return sell_fart, sell_usdc, fart_value, usdc_value


def calculate_hypothetical_all_in_fart(
    fart_balance: Decimal, usdc_balance: Decimal, usdc_price: Decimal, fart_price: Decimal
) -> Decimal:
    usdc_value = usdc_balance * usdc_price
    additional_fart = usdc_value / fart_price if fart_price > 0 else Decimal("0")
    return fart_balance + additional_fart


# =============================================================================
# MAIN SCRIPT
# =============================================================================
def main():
    print("=" * 80)
    print("🚀 Solana FARTCOIN + USDC Portfolio Analyzer")
    print("    Dual Token/Token-2022 • Slippage-aware 50/50 rebalance")
    print(f"    Using {SLIPPAGE_ASSUMED*100:.1f}% assumed slippage")
    print(f"    Console rounding → Balances: {CONSOLE_BALANCE_ROUNDING} decimals | USD: {CONSOLE_USD_ROUNDING} decimals")
    print("=" * 80)

    # Wallet input
    if len(sys.argv) > 1:
        wallet = sys.argv[1].strip()
    else:
        while True:
            wallet = input("\nEnter your Solana wallet address (or 'exit'): ").strip()
            if wallet.lower() == "exit":
                sys.exit(0)
            if 32 <= len(wallet) <= 44 and wallet.isalnum():
                break
            print("❌ Invalid address (32-44 base58 chars).")

    print("\nFetching liquid token balances (Token + Token-2022 — only 2 RPC calls)...")
    
    token_accounts = get_all_token_accounts(wallet)
    
    fart_balance = get_specific_balance(token_accounts, FARTCOIN_MINT, "FARTCOIN")
    usdc_balance = get_specific_balance(token_accounts, USDC_MINT, "USDC")

    print(f"   FARTCOIN liquid balance: {console_round_balance(fart_balance)}")
    print(f"   USDC liquid balance:     {console_round_balance(usdc_balance)}")

    fart_price, usdc_price = get_current_prices()

    sell_fart, sell_usdc, fart_value, usdc_value = calculate_rebalance(
        fart_balance, usdc_balance, fart_price, usdc_price, SLIPPAGE_ASSUMED
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

    # Summary (console-rounded)
    now_kst = datetime.now(KST_TZ)
    print("\n" + "=" * 80)
    print("📊 PORTFOLIO SUMMARY")
    print("=" * 80)
    print(f"Wallet                  : {wallet}")
    print(f"Timestamp (KST)         : {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"Assumed slippage        : {SLIPPAGE_ASSUMED*100:.2f}%")
    print(f"FARTCOIN (liquid)       : {console_round_balance(fart_balance)} (${console_round_usd(fart_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"USDC (liquid)           : {console_round_balance(usdc_balance)} (${console_round_usd(usdc_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"Total liquid value      : ${console_round_usd(total_value):,.{CONSOLE_USD_ROUNDING}f} USD")
    print(f"FARTCOIN %              : {console_round_usd(fart_pct):.4f}%")   # percentages stay at 4 decimals for readability
    print(f"USDC %                  : {console_round_usd(usdc_pct):.4f}%")
    print("-" * 80)

    # REBALANCE OUTPUT
    slippage_pct_str = f"{SLIPPAGE_ASSUMED*100:.1f}%"
    if sell_fart > 0:
        sell_value = sell_fart * fart_price
        sell_pct = (sell_value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        print(f"🔄 To reach 50/50 (assuming {slippage_pct_str} slippage): Sell {console_round_balance(sell_fart)} FARTCOIN ({console_round_usd(sell_pct):.4f}% of portfolio)")
    elif sell_usdc > 0:
        sell_value = sell_usdc * usdc_price
        sell_pct = (sell_value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        print(f"🔄 To reach 50/50 (assuming {slippage_pct_str} slippage): Sell {console_round_balance(sell_usdc)} USDC ({console_round_usd(sell_pct):.4f}% of portfolio)")
    else:
        print("✅ Portfolio is already perfectly balanced at 50/50!")

    print(f"🚀 Hypothetical all-in FARTCOIN: {console_round_balance(hypothetical_fart)} FARTCOIN")
    print("=" * 80)

    if fart_price == 0:
        print("⚠️  Note: FARTCOIN price returned zero - calculations may be inaccurate.")

    # CSV export — FULL precision (unchanged)
    csv_path = os.path.join(CSV_OUTPUT_DIR, CSV_FILENAME)
    fieldnames = [
        "timestamp_kst", "wallet_address", "fartcoin_balance", "usdc_balance",
        "fartcoin_price_usd", "usdc_price_usd", "fartcoin_value_usd",
        "usdc_value_usd", "total_value_usd", "fartcoin_pct", "usdc_pct",
        "sell_fartcoin_to_50_50", "sell_usdc_to_50_50",
        "hypothetical_fartcoin_equivalent", "assumed_slippage"
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
        "hypothetical_fartcoin_equivalent": str(hypothetical_fart),
        "assumed_slippage": str(SLIPPAGE_ASSUMED)
    }

    file_exists = os.path.exists(csv_path)
    try:
        mode = "a" if file_exists else "w"
        with open(csv_path, mode=mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        print(f"Results appended to: {csv_path}")
    except Exception as e:
        print(f"❌ CSV export failed: {e}")

    print("\nScript completed successfully!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Script interrupted by user.")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
