import requests
import csv
from datetime import datetime
from decimal import Decimal, getcontext
import sys
import os
import json
import time
from functools import wraps
from typing import Tuple, Dict
from zoneinfo import ZoneInfo

# =============================================================================
# CONFIG SECTION
# =============================================================================
USDC_MINT: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_GECKO_ID: str = "usd-coin"

# Smart relative path - automatically finds tokens_list.json next to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENS_LIST_PATH: str = os.path.join(SCRIPT_DIR, "tokens_list.json")

RPC_URL: str = "https://api.mainnet-beta.solana.com"
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"

CSV_OUTPUT_DIR: str = "."

# Assumed slippage for 50/50 rebalance calculations
SLIPPAGE_ASSUMED: Decimal = Decimal("0.01")  # 1% — change as needed

# Console display rounding (math + CSV always use full Decimal precision)
CONSOLE_BALANCE_ROUNDING: int = 6   # Token quantities 
CONSOLE_USD_ROUNDING: int = 3       # USD values, prices, total value

# Absolute maximum precision for all internal math
getcontext().prec = 50

KST_TZ = ZoneInfo("Asia/Seoul")

# Token program IDs for maximum coverage
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# RPC rate-limit handling
RPC_RETRY_DELAY_SECONDS: int = 20
RPC_DELAY_BETWEEN_CALLS_SECONDS: float = 2

# Shared fieldnames for BOTH portfolio CSV and starting_point CSV
CSV_FIELDNAMES: list[str] = [
    "timestamp_kst", "wallet_address", "token_id",
    "token_balance", "usdc_balance",
    "token_price_usd", "usdc_price_usd", "token_value_usd",
    "usdc_value_usd", "total_value_usd", "token_pct", "usdc_pct",
    "sell_token_to_50_50", "sell_usdc_to_50_50",
    "hypothetical_token_equivalent", "assumed_slippage"
]

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
        
        print(f"    Processed {accounts_found} token account(s) from {program_id[:8]} program")
        
        print(f"    Waiting {RPC_DELAY_BETWEEN_CALLS_SECONDS} seconds before next RPC call...")
        time.sleep(RPC_DELAY_BETWEEN_CALLS_SECONDS)

    return token_data


def get_raw_token_balance(token_accounts: dict, mint: str) -> Decimal:
    """Pure function: Get balance for a mint without any printing or side effects."""
    if mint not in token_accounts:
        return Decimal("0")
    
    info = token_accounts[mint]
    raw = Decimal(info.get("raw_amount", "0"))
    decimals = int(info.get("decimals", 6))
    
    balance = raw / Decimal(10 ** decimals)
    return balance


def get_specific_balance(token_accounts: dict, mint: str, token_id: str) -> Decimal:
    """Extract balance for a specific mint with console output (raw id only)."""
    if mint not in token_accounts:
        print(f"    No {token_id} accounts found.")
        return Decimal("0")
    
    info = token_accounts[mint]
    raw = Decimal(info["raw_amount"])
    decimals = info.get("decimals", 6)
    
    balance = raw / Decimal(10 ** decimals)
    print(f"    Found {token_id} balance: {console_round_balance(balance)} (decimals={decimals} from on-chain data)")
    return balance


# =============================================================================
# PRICE FETCHING
# =============================================================================
@retry()
def get_prices(gecko_ids: list[str]) -> Dict[str, Decimal]:
    """Fetch prices for multiple CoinGecko IDs."""
    if not gecko_ids:
        return {}
    
    ids_str = ",".join([id_ for id_ in gecko_ids])
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": ids_str,
        "vs_currencies": "usd",
        "precision": "full",
        "include_last_updated_at": "true"
    }

    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()
    data = json.loads(response.text, parse_float=Decimal)

    prices: Dict[str, Decimal] = {}
    for gid in gecko_ids:
        prices[gid] = data.get(gid, {}).get("usd", Decimal("0"))

    print("\n✅ CoinGecko prices (full precision):")
    for gid, price in prices.items():
        print(f"   {gid}: ${console_round_usd(price)}")
    
    if gecko_ids and data.get(gecko_ids[0], {}).get("last_updated_at"):
        ts = datetime.fromtimestamp(data[gecko_ids[0]]['last_updated_at'], tz=KST_TZ)
        print(f"   Last updated: {ts.strftime('%Y-%m-%d %H:%M:%S KST')}")
    
    return prices


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def load_tokens_config() -> list[dict]:
    """Load the dynamic tokens list from JSON (now using relative path)."""
    print(f"🔍 Looking for tokens_list.json at: {TOKENS_LIST_PATH}")
    
    if not os.path.exists(TOKENS_LIST_PATH):
        print(f"⚠️  Tokens list not found at {TOKENS_LIST_PATH}")
        print("   → Please create tokens_list.json in the same folder as tokens_balance.py")
        print("   → Copy the JSON content I provided earlier.")
        sys.exit(1)
    
    with open(TOKENS_LIST_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ Loaded {len(data)} tokens from tokens_list.json")
        return data


def calculate_rebalance(
    token_balance: Decimal, usdc_balance: Decimal,
    token_price: Decimal, usdc_price: Decimal,
    slippage: Decimal
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
    """Calculates sell amounts to reach 50/50 AFTER slippage. Generic for any token+USDC."""
    token_value = token_balance * token_price
    usdc_value = usdc_balance * usdc_price
    total_value = token_value + usdc_value
    if total_value == 0:
        return Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    
    if token_value > usdc_value:
        diff = token_value - usdc_value
        sell_value = diff / (Decimal("2") - slippage)
        sell_token = sell_value / token_price if token_price > 0 else Decimal("0")
        sell_usdc = Decimal("0")
    elif usdc_value > token_value:
        diff = usdc_value - token_value
        sell_value = diff / (Decimal("2") - slippage)
        sell_token = Decimal("0")
        sell_usdc = sell_value / usdc_price if usdc_price > 0 else Decimal("0")
    else:
        sell_token = sell_usdc = Decimal("0")
    return sell_token, sell_usdc, token_value, usdc_value


def calculate_hypothetical_all_in_token(
    token_balance: Decimal, usdc_balance: Decimal, usdc_price: Decimal, token_price: Decimal
) -> Decimal:
    """Calculate equivalent if all USDC converted to the main token."""
    usdc_value = usdc_balance * usdc_price
    additional_token = usdc_value / token_price if token_price > 0 else Decimal("0")
    return token_balance + additional_token


# =============================================================================
# MAIN SCRIPT
# =============================================================================
def main():
    print("=" * 80)
    print("🚀 Dynamic Solana Token + USDC Portfolio Analyzer")
    print(f"    Dual Token/Token-2022 • Slippage-aware 50/50 rebalance")
    print(f"    Using {SLIPPAGE_ASSUMED*100:.1f}% assumed slippage")
    print(f"    Console rounding → Balances: {CONSOLE_BALANCE_ROUNDING} decimals | USD: {CONSOLE_USD_ROUNDING} decimals")
    print("=" * 80)

    # Load tokens config
    tokens_config = load_tokens_config()

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
    
    # Prepare candidate IDs for price fetch
    portfolio_candidates = [t for t in tokens_config if t.get("include_in_portfolio", False)]
    candidate_ids = [t["id"] for t in portfolio_candidates if t.get("mint") != "NATIVE"]
    all_ids = list(set(candidate_ids + [USDC_GECKO_ID]))
    
    prices_dict = get_prices(all_ids)
    usdc_price = prices_dict.get(USDC_GECKO_ID, Decimal(1))

    # Select main token: first include_in_portfolio with value > $20, else fallback to FARTCOIN
    main_token_config = None
    for token in tokens_config:
        if not token.get("include_in_portfolio", False):
            continue
        mint = token.get("mint")
        if mint == "NATIVE":
            continue
        token_id = token["id"]
        balance = get_raw_token_balance(token_accounts, mint)
        price = prices_dict.get(token_id, Decimal(0))
        value_usd = balance * price
        
        print(f"   📋 Checked {token_id}: {console_round_balance(balance)} @ ${console_round_usd(price)} = ${console_round_usd(value_usd)}")
        
        if value_usd > Decimal("20"):
            main_token_config = token
            print(f"✅ Selected {token_id} as main token (>$20 USD value)")
            break

    if main_token_config is None:
        # Fallback to FARTCOIN
        for token in tokens_config:
            if token["id"] == "fartcoin":
                main_token_config = token
                print("⚠️  No token exceeded $20 USD. Falling back to fartcoin-usdc")
                break
        else:
            print("❌ Fallback token not found. Exiting.")
            sys.exit(1)

    # Finalize main token details (raw id only)
    main_token_id: str = main_token_config["id"]
    main_token_mint: str = main_token_config["mint"]

    # Get final balances with display (raw id only)
    print("\n" + "-" * 40)
    main_balance = get_specific_balance(token_accounts, main_token_mint, main_token_id)
    usdc_balance = get_specific_balance(token_accounts, USDC_MINT, USDC_GECKO_ID)

    main_price = prices_dict.get(main_token_id, Decimal(0))

    print(f"   {main_token_id} liquid balance: {console_round_balance(main_balance)}")
    print(f"   {USDC_GECKO_ID} liquid balance: {console_round_balance(usdc_balance)}")

    # Calculations (full Decimal precision)
    sell_token, sell_usdc, token_value, usdc_value = calculate_rebalance(
        main_balance, usdc_balance, main_price, usdc_price, SLIPPAGE_ASSUMED
    )
    total_value = token_value + usdc_value

    if total_value > 0:
        token_pct = (token_value / total_value) * Decimal("100")
        usdc_pct = (usdc_value / total_value) * Decimal("100")
    else:
        token_pct = usdc_pct = Decimal("0")

    hypothetical_token = calculate_hypothetical_all_in_token(
        main_balance, usdc_balance, usdc_price, main_price
    )

    # =============================================================================
    # STARTING POINT BASELINE + DELTA CALCULATION (NEW FEATURE)
    # =============================================================================
    # now_kst and row are built here so they are available for starting_point CSV
    now_kst = datetime.now(KST_TZ)

    # Build row data once (reused for portfolio CSV append + starting_point creation)
    row = {
        "timestamp_kst": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "wallet_address": wallet,
        "token_id": main_token_id,
        "token_balance": str(main_balance),
        "usdc_balance": str(usdc_balance),
        "token_price_usd": str(main_price),
        "usdc_price_usd": str(usdc_price),
        "token_value_usd": str(token_value),
        "usdc_value_usd": str(usdc_value),
        "total_value_usd": str(total_value),
        "token_pct": str(token_pct),
        "usdc_pct": str(usdc_pct),
        "sell_token_to_50_50": str(sell_token),
        "sell_usdc_to_50_50": str(sell_usdc),
        "hypothetical_token_equivalent": str(hypothetical_token),
        "assumed_slippage": str(SLIPPAGE_ASSUMED)
    }

    # Starting point CSV - one-time baseline snapshot
    starting_point_filename = f"starting_point_{main_token_id}.csv"
    starting_point_path = os.path.join(CSV_OUTPUT_DIR, starting_point_filename)
    starting_equiv = hypothetical_token
    starting_total_usd = total_value   # default to current (delta = 0 on first run)

    if os.path.exists(starting_point_path):
        try:
            with open(starting_point_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    if "hypothetical_token_equivalent" in rows[0]:
                        starting_equiv = Decimal(rows[0]["hypothetical_token_equivalent"])
                        print(f"✅ Loaded starting {main_token_id} equivalent baseline: {console_round_balance(starting_equiv)}")
                    if "total_value_usd" in rows[0]:
                        starting_total_usd = Decimal(rows[0]["total_value_usd"])
                        print(f"✅ Loaded starting USD equivalent baseline: ${console_round_usd(starting_total_usd):,.{CONSOLE_USD_ROUNDING}f}")
        except Exception as e:
            print(f"⚠️  Could not read starting_point_{main_token_id}.csv: {e}")
    else:
        print(f"📝 No starting_point_{main_token_id}.csv found - creating new baseline with current data...")
        try:
            with open(starting_point_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
                writer.writerow(row)
            print(f"✅ Created starting_point_{main_token_id}.csv baseline snapshot")
        except Exception as e:
            print(f"❌ Failed to create starting_point CSV: {e}")

    # Delta calculation
    equiv_delta = hypothetical_token - starting_equiv
    usd_delta = equiv_delta * main_price if main_price > 0 else Decimal("0")          # existing (token equiv → USD)
    usd_equiv_delta = total_value - starting_total_usd                                 # NEW: actual portfolio USD delta

    # Summary (pure raw ids only)
    print("\n" + "=" * 80)
    print(f"📊 {main_token_id} + {USDC_GECKO_ID} portfolio summary")
    print("=" * 80)
    print(f"Wallet                    : {wallet}")
    print(f"Timestamp (KST)           : {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"Main token                : {main_token_id}")
    print(f"Assumed slippage          : {SLIPPAGE_ASSUMED*100:.2f}%")
    print(f"{main_token_id}                  : {console_round_balance(main_balance)} (${console_round_usd(token_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"{USDC_GECKO_ID}                  : {console_round_balance(usdc_balance)} (${console_round_usd(usdc_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"{main_token_id} equivalent       : {console_round_balance(hypothetical_token)} {main_token_id}")
    print(f"{main_token_id} equiv delta      : {console_round_balance(equiv_delta)} {main_token_id} (${console_round_usd(usd_delta):+,.{CONSOLE_USD_ROUNDING}f})")
    print(f"USD equivalent            : ${console_round_usd(total_value):,.{CONSOLE_USD_ROUNDING}f} USD")
    print(f"USD equivalent delta      : ${console_round_usd(usd_equiv_delta):+,.{CONSOLE_USD_ROUNDING}f} USD")
    print(f"{main_token_id} %                : {console_round_usd(token_pct):.4f}%")
    print(f"{USDC_GECKO_ID} %                : {console_round_usd(usdc_pct):.4f}%")
    print("-" * 80)

    # REBALANCE OUTPUT (raw ids only) — NOW INCLUDES USD SELL VALUE
    slippage_pct_str = f"{SLIPPAGE_ASSUMED*100:.1f}%"
    if sell_token > 0:
        sell_value = sell_token * main_price
        sell_pct = (sell_value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        print(f"🔄 To reach 50/50 (assuming {slippage_pct_str} slippage): Sell {console_round_balance(sell_token)} {main_token_id} (${console_round_usd(sell_value):,.{CONSOLE_USD_ROUNDING}f}) ({console_round_usd(sell_pct):.4f}% of portfolio)")
    elif sell_usdc > 0:
        sell_value = sell_usdc * usdc_price
        sell_pct = (sell_value / total_value * Decimal("100")) if total_value > 0 else Decimal("0")
        print(f"🔄 To reach 50/50 (assuming {slippage_pct_str} slippage): Sell {console_round_balance(sell_usdc)} {USDC_GECKO_ID} (${console_round_usd(sell_value):,.{CONSOLE_USD_ROUNDING}f}) ({console_round_usd(sell_pct):.4f}% of portfolio)")
    else:
        print("✅ Portfolio is already perfectly balanced at 50/50!")

    print("=" * 80)

    if main_price == 0:
        print("⚠️  Note: Token price returned zero - calculations may be inaccurate.")

    # CSV export (portfolio history - always appends)
    csv_filename = f"solana_portfolio_{main_token_id}_usdc.csv"
    csv_path = os.path.join(CSV_OUTPUT_DIR, csv_filename)
    
    file_exists = os.path.exists(csv_path)
    try:
        mode = "a" if file_exists else "w"
        with open(csv_path, mode=mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
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
