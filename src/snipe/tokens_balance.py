import requests
import csv
from datetime import datetime
from decimal import Decimal, getcontext, InvalidOperation
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKENS_LIST_PATH: str = os.path.join(SCRIPT_DIR, "tokens_list.json")

RPC_URL: str = "https://api.mainnet-beta.solana.com"
COINGECKO_BASE: str = "https://api.coingecko.com/api/v3"

CSV_OUTPUT_DIR: str = "."

SLIPPAGE_ASSUMED: Decimal = Decimal("0.01")

CONSOLE_BALANCE_ROUNDING: int = 6
CONSOLE_USD_ROUNDING: int = 3

getcontext().prec = 50

KST_TZ = ZoneInfo("Asia/Seoul")

SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# =============================================================================
# Token Program Selection
# =============================================================================
USE_TOKEN_2022_PROGRAM: bool = False   # ← Set to False to skip Token-2022 (TokenzQd...) entirely.
                                      #    SPL Token (Tokenkeg...) is ALWAYS checked by default.
                                      #    This saves one RPC call and ~2 seconds when disabled.

RPC_RETRY_DELAY_SECONDS: int = 20
RPC_DELAY_BETWEEN_CALLS_SECONDS: float = 2

CSV_FIELDNAMES: list[str] = [
    "timestamp_kst", "wallet_address", "token_id",
    "token_balance", "usdc_balance",
    "token_price_usd", "usdc_price_usd", "token_value_usd",
    "usdc_value_usd", "total_value_usd", "token_pct", "usdc_pct",
    "hypothetical_token_equivalent", "assumed_slippage"
]

def console_round_balance(value: Decimal) -> Decimal:
    return value.quantize(Decimal('1.' + '0' * CONSOLE_BALANCE_ROUNDING))

def console_round_usd(value: Decimal) -> Decimal:
    return value.quantize(Decimal('1.' + '0' * CONSOLE_USD_ROUNDING))

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

@retry()
def get_all_token_accounts(wallet_address: str) -> dict[str, dict]:
    token_data: dict[str, dict] = {}
    
    # Always include standard SPL Token program; optionally add Token-2022
    programs = [SPL_TOKEN_PROGRAM_ID]
    if USE_TOKEN_2022_PROGRAM:
        programs.append(TOKEN_2022_PROGRAM_ID)
    else:
        print("    Token-2022 program support disabled in config (USE_TOKEN_2022_PROGRAM=False)")
    
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
    if mint not in token_accounts:
        return Decimal("0")
    info = token_accounts[mint]
    raw = Decimal(info.get("raw_amount", "0"))
    decimals = int(info.get("decimals", 6))
    return raw / Decimal(10 ** decimals)

def get_specific_balance(token_accounts: dict, mint: str, token_id: str) -> Decimal:
    if mint not in token_accounts:
        print(f"    No {token_id} accounts found.")
        return Decimal("0")
    info = token_accounts[mint]
    raw = Decimal(info["raw_amount"])
    decimals = info.get("decimals", 6)
    return raw / Decimal(10 ** decimals)

@retry()
def get_prices(gecko_ids: list[str]) -> Dict[str, Decimal]:
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
    return prices

def load_tokens_config() -> list[dict]:
    print(f"Looking for tokens_list.json at: {TOKENS_LIST_PATH}")
    if not os.path.exists(TOKENS_LIST_PATH):
        print(f"⚠️  Tokens list not found at {TOKENS_LIST_PATH}")
        print("   → Please create tokens_list.json in the same folder as this script")
        sys.exit(1)
    with open(TOKENS_LIST_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"Loaded {len(data)} tokens from tokens_list.json")
        return data

def calculate_rebalance(
    token_balance: Decimal, usdc_balance: Decimal,
    token_price: Decimal, usdc_price: Decimal,
    slippage: Decimal
) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
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
    usdc_value = usdc_balance * usdc_price
    additional_token = usdc_value / token_price if token_price > 0 else Decimal("0")
    return token_balance + additional_token

# =============================================================================
# BALANCE CHANGE DETECTION (for main portfolio CSV only)
# =============================================================================
def has_balance_changed(csv_path: str, current_token_balance: Decimal, current_usdc_balance: Decimal) -> bool:
    """Return True if we should save: no file, empty file, or balances actually changed."""
    if not os.path.exists(csv_path):
        return True
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                return True
            
            last_row = rows[-1]
            try:
                prev_token = Decimal(last_row.get("token_balance", "0"))
                prev_usdc = Decimal(last_row.get("usdc_balance", "0"))
                
                # Exact match (on-chain token amounts are precise)
                if prev_token == current_token_balance and prev_usdc == current_usdc_balance:
                    return False
                return True
            except (KeyError, ValueError, TypeError, InvalidOperation):
                print(f"⚠️  Could not parse last CSV row balances - saving anyway")
                return True
    except Exception as e:
        print(f"⚠️  Could not read CSV for balance change detection: {e}")
        return True  # safer to save than lose data


def main():
    print("=" * 80)
    print("    Dynamic Solana Token + USDC Portfolio Analyzer")
    print(f"    Dual Token/Token-2022 • Slippage-aware 50/50 rebalance")
    print(f"    Using {SLIPPAGE_ASSUMED*100:.1f}% assumed slippage")
    print(f"    Console rounding → Balances: {CONSOLE_BALANCE_ROUNDING} decimals | USD: {CONSOLE_USD_ROUNDING} decimals")
    print("=" * 80)

    tokens_config = load_tokens_config()

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

    # Updated fetching message that reflects the config choice
    program_count = 1 + int(USE_TOKEN_2022_PROGRAM)
    print(f"\nFetching liquid token balances (SPL Token{' + Token-2022' if USE_TOKEN_2022_PROGRAM else ''} — {program_count} RPC call{'s' if program_count > 1 else ''})...")
    
    token_accounts = get_all_token_accounts(wallet)
    
    portfolio_candidates = [t for t in tokens_config if t.get("include_in_portfolio", False)]
    candidate_ids = [t["id"] for t in portfolio_candidates if t.get("mint") != "NATIVE"]
    all_ids = list(set(candidate_ids + [USDC_GECKO_ID]))
    
    prices_dict = get_prices(all_ids)
    usdc_price = prices_dict.get(USDC_GECKO_ID, Decimal(1))

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
        
        print(f"   Checked {token_id}: {console_round_balance(balance)} @ ${console_round_usd(price)} = ${console_round_usd(value_usd)}")
        
        if value_usd > Decimal("20"):
            main_token_config = token
            print(f"\n   Selected {token_id} as main token (>$20 USD value)")
            break

    if main_token_config is None:
        print("❌ No token exceeded $20 USD value.")
        print("   Exiting program (no FARTCOIN fallback as requested).")
        sys.exit(1)

    main_token_id: str = main_token_config["id"]
    main_token_mint: str = main_token_config["mint"]

    main_balance = get_specific_balance(token_accounts, main_token_mint, main_token_id)
    usdc_balance = get_specific_balance(token_accounts, USDC_MINT, USDC_GECKO_ID)

    main_price = prices_dict.get(main_token_id, Decimal(0))

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

    now_kst = datetime.now(KST_TZ)

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
        "hypothetical_token_equivalent": str(hypothetical_token),
        "assumed_slippage": str(SLIPPAGE_ASSUMED)
    }

    # === STARTING POINT CSV (completely unchanged) ===
    starting_point_filename = f"starting_point_{main_token_id}.csv"
    starting_point_path = os.path.join(CSV_OUTPUT_DIR, starting_point_filename)
    starting_equiv = hypothetical_token
    starting_total_usd = total_value
    starting_price = main_price

    if os.path.exists(starting_point_path):
        try:
            with open(starting_point_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    if "hypothetical_token_equivalent" in rows[0]:
                        starting_equiv = Decimal(rows[0]["hypothetical_token_equivalent"])
                    if "total_value_usd" in rows[0]:
                        starting_total_usd = Decimal(rows[0]["total_value_usd"])
                    if "token_price_usd" in rows[0]:
                        starting_price = Decimal(rows[0]["token_price_usd"])
        except Exception as e:
            print(f"⚠️  Could not read starting_point_{main_token_id}.csv: {e}")
    else:
        print(f"📝 No starting_point_{main_token_id}.csv found - creating new baseline...")
        try:
            with open(starting_point_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
                writer.writerow(row)
            print(f"✅ Created starting_point_{main_token_id}.csv")
        except Exception as e:
            print(f"❌ Failed to create starting_point CSV: {e}")

    # === DELTA CALCULATIONS (unchanged) ===
    equiv_delta = hypothetical_token - starting_equiv
    usd_delta = equiv_delta * main_price if main_price > 0 else Decimal("0")
    usd_equiv_delta = total_value - starting_total_usd
    usd_equiv_pct_change = (usd_equiv_delta / starting_total_usd * Decimal("100")) if starting_total_usd > 0 else Decimal("0")
    price_delta = main_price - starting_price
    price_pct_change = (price_delta / starting_price * Decimal("100")) if starting_price > 0 else Decimal("0")

    print("\n" + "=" * 80)
    print(f"📊 {main_token_id} + {USDC_GECKO_ID} portfolio summary")
    print("=" * 80)
    # ... (all the same console output as before) ...
    print(f"Wallet                    : {wallet}")
    print(f"Timestamp (KST)           : {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}")
    print(f"Main token                : {main_token_id}")
    print(f"Assumed slippage          : {SLIPPAGE_ASSUMED*100:.2f}%")
    print(f"current token balance     : {console_round_balance(main_balance)} (${console_round_usd(token_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"{USDC_GECKO_ID} balance          : {console_round_balance(usdc_balance)} (${console_round_usd(usdc_value):,.{CONSOLE_USD_ROUNDING}f})")
    print(f"token equivalent          : {console_round_balance(hypothetical_token)} {main_token_id}")
    print(f"token equiv delta         : {console_round_balance(equiv_delta)} {main_token_id} (${console_round_usd(usd_delta):+,.{CONSOLE_USD_ROUNDING}f})")
    print(f"USD equivalent            : ${console_round_usd(total_value):,.{CONSOLE_USD_ROUNDING}f} USD")
    print(f"USD equivalent delta      : ${console_round_usd(usd_equiv_delta):+,.{CONSOLE_USD_ROUNDING}f} USD ({usd_equiv_pct_change:+.4f}%)")
    
    print("-" * 80)
    print(f"Starting price            : ${console_round_usd(starting_price)}")
    print(f"Current price             : ${console_round_usd(main_price)}")
    print(f"Price change              : ${console_round_usd(price_delta):+,.{CONSOLE_USD_ROUNDING}f} ({price_pct_change:+.4f}%)")

    print(f"token %                   : {console_round_usd(token_pct):.4f}%")
    print(f"{USDC_GECKO_ID} %                : {console_round_usd(usdc_pct):.4f}%")
    print("-" * 80)

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

    print("-" * 80)

    if main_price == 0:
        print("⚠️  Note: Token price returned zero - calculations may be inaccurate.")

    # === CSV EXPORT: ONLY WHEN BALANCE CHANGES (or first run) ===
    csv_filename = f"solana_portfolio_{main_token_id}_usdc.csv"
    csv_path = os.path.join(CSV_OUTPUT_DIR, csv_filename)

    if has_balance_changed(csv_path, main_balance, usdc_balance):
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
    else:
        print(f"No balance change detected in {main_token_id} or {USDC_GECKO_ID}. "
              f"Latest data shown in console but NOT saved to CSV.")

    print("\nScript completed successfully!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Script interrupted by user.")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
