import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
import select
from typing import Dict, Tuple
from web3 import Web3
import json
from decimal import Decimal, getcontext

# ========================= HIGH-PRECISION DECIMAL SETUP =========================
getcontext().prec = 36

# ========================= BASE CONFIG =========================
BASE_CONFIG = {
    "KST_TIMEZONE": "Asia/Seoul",
    "BAR_WIDTH": 80,
    "COUNTDOWN_BAR_WIDTH": 80,
    "SHOW_HEADER_LABELS": True,
    "SHOW_50_PERCENT_MARKER": True,
    "PERCENT_PRECISION": 1,
    "REFRESH_INTERVAL": 60 * 5,
    "UPDATE_ONCE": False,
    "RATE_LIMIT_WAIT_SECONDS": 60 * 2,
    "PRICE_CACHE_SECONDS": 10,
}

# ========================= SLIPPAGE CONFIG =========================
SLIPPAGE = Decimal("0.015")  # 1.5% slippage assumption for realistic DEX swaps

ABSOLUTE_STARTS_FILE = "absolute_starts.json"

# ====================== GLOBAL PRICE CACHE ======================
PRICE_CACHE: Dict = {
    "prices": None,
    "timestamp": 0.0,
}

# ========================= PORTFOLIOS CONFIGS =========================
PORTFOLIOS = {
    "1": {  # SOL + ORCA (Solana)
        "name": "ORCA + SOL (Solana)",
        "chain": "solana",
        "rpc_url": "https://api.mainnet-beta.solana.com",
        "csv_filename": "solana_orca_balances.csv",
        "asset1": {"symbol": "SOL",   "cg_id": "solana", "balance_prec": 6, "price_prec": 2, "col_prefix": "sol"},
        "asset2": {"symbol": "ORCA",  "cg_id": "orca",   "balance_prec": 6, "price_prec": 4, "col_prefix": "orca"},
        "bar_char1": "█",
        "bar_char2": "─",
        "orca_mint": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
        "absolute_key": "sol_orca",
    },
    "2": {  # BTCB + PEPE (BSC)
        "name": "PEPE + BTCB (BSC)",
        "chain": "bsc",
        "rpc_url": "https://bsc-dataseed.binance.org/",
        "csv_filename": "btcb_pepe_balances.csv",
        "asset1": {"symbol": "BTCB",  "cg_id": "binance-bitcoin", "balance_prec": 6, "price_prec": 2, "col_prefix": "btcb"},
        "asset2": {"symbol": "PEPE",  "cg_id": "pepe", "balance_prec": 8, "price_prec": 18, "col_prefix": "pepe"},
        "bar_char1": "█",
        "bar_char2": "─",
        "btcb_contract": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",
        "pepe_contract": "0x25d887ce7a35172c62febfd67a1856f20faebb00",
        "absolute_key": "btcb_pepe",
    }
}

# ====================== HIGH-PRECISION CSV HELPER ======================
def decimal_to_csv_str(value: Decimal, decimals: int = 18) -> str:
    """Convert Decimal → fixed-point string for CSV. ZERO float() usage → full precision preserved."""
    if value.is_zero():
        return '0'
    quantizer = Decimal('1e-' + str(decimals))
    quantized = value.quantize(quantizer)
    return f"{quantized:f}"   # always clean fixed-point, no scientific notation

# ====================== COMMON HELPERS ======================
def _handle_rate_limit(error_msg: str = "") -> bool:
    if not error_msg:
        return False
    msg_lower = error_msg.lower()
    return any(term in msg_lower for term in ["rate limit", "too many requests", "429", "rate exceeded"])

def get_previous_balances(csv_filename: str, col1: str, col2: str) -> Tuple[Decimal, Decimal]:
    if not os.path.isfile(csv_filename):
        return Decimal('0'), Decimal('0')
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return Decimal('0'), Decimal('0')
            last = rows[-1]
            return Decimal(str(last.get(col1, 0))), Decimal(str(last.get(col2, 0)))
    except Exception:
        return Decimal('0'), Decimal('0')

def get_minutes_since_last_balance_change(csv_filename: str, chg_col1: str, chg_col2: str) -> str:
    if not os.path.isfile(csv_filename):
        return "No CSV yet"
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if len(rows) <= 1:
                return "No previous change recorded"

            kst_tz = zoneinfo.ZoneInfo(BASE_CONFIG["KST_TIMEZONE"])
            now_kst = datetime.now(kst_tz)

            for row in reversed(rows):
                try:
                    chg1 = Decimal(str(row.get(chg_col1, 0) or 0))
                    chg2 = Decimal(str(row.get(chg_col2, 0) or 0))
                    if abs(chg1) > Decimal('1e-9') or abs(chg2) > Decimal('1e-9'):
                        ts_str = row["timestamp_kst"]
                        last_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=kst_tz)
                        delta_min = (now_kst - last_dt).total_seconds() / 60
                        return f"{delta_min:.1f} minutes ago"
                except (ValueError, TypeError, KeyError):
                    continue
        return "No balance changes in history"
    except Exception:
        return "Error checking history"

def get_start_info(csv_filename: str, current_kst: datetime) -> tuple[str, str]:
    if not os.path.isfile(csv_filename):
        return "Not started yet (first run)", "0.00 days (0 hours)"
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return "Not started yet (first run)", "0.00 days (0 hours)"
            first = rows[0]
            start_str = first.get("readable_time_kst") or first.get("timestamp_kst", "Unknown date")
            start_iso = first.get("timestamp_kst")
            if not start_iso:
                return start_str, "N/A"
            try:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=current_kst.tzinfo)
            except Exception:
                return start_str, "N/A (parse error)"
            delta = current_kst - start_dt
            days_elapsed = delta.total_seconds() / 86400
            hours_elapsed = delta.total_seconds() / 3600
            elapsed_str = f"{days_elapsed:.2f} days ({hours_elapsed:.0f} hours)"
            return start_str, elapsed_str
    except Exception:
        return "N/A (error reading CSV)", "N/A"

def load_absolute_starts() -> Dict:
    if not os.path.isfile(ABSOLUTE_STARTS_FILE):
        print(f"\n   {ABSOLUTE_STARTS_FILE} not found — skipping absolute baseline")
        return {}
    try:
        with open(ABSOLUTE_STARTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"\n   Could not load {ABSOLUTE_STARTS_FILE}: {e}")
        return {}

# ====================== UPDATED: get_prices with Decimal ======================
def get_prices(cg_ids: str) -> Dict[str, Decimal]:
    now = time.time()
    cache_age = now - PRICE_CACHE["timestamp"]
    if PRICE_CACHE["prices"] and cache_age < BASE_CONFIG["PRICE_CACHE_SECONDS"]:
        print(f"   📦 Using cached prices (age: {cache_age:.0f}s)")
        return PRICE_CACHE["prices"]

    url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_ids}&vs_currencies=usd&precision=full"
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            prices = {k: Decimal(str(v["usd"])) for k, v in data.items()}
            PRICE_CACHE["prices"] = prices
            PRICE_CACHE["timestamp"] = time.time()
            return prices
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                wait_with_progress(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"], "CoinGecko rate limit")
                continue
            raise
    raise Exception("Failed to fetch prices after retries")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# ====================== ENHANCED COUNTDOWN & WAIT ======================
def countdown(refresh_interval: int) -> bool:
    print('')
    start_time = time.time()
    total = refresh_interval
    bar_width = BASE_CONFIG["COUNTDOWN_BAR_WIDTH"]

    while True:
        elapsed = time.time() - start_time
        if elapsed >= total:
            break

        remaining = max(0, int(total - elapsed))
        progress = min(1.0, elapsed / total)
        filled = int(round(progress * bar_width))
        bar = "█" * filled + "─" * (bar_width - filled)

        msg = f"Next refresh in {remaining:3d}s  [{bar}]  (press r + Enter to refresh now, Ctrl+C to stop)"

        print(msg + " " * 40, end="\r")
        sys.stdout.flush()

        remaining_wait = total - elapsed
        if remaining_wait <= 0:
            break
        wait_time = min(1.0, remaining_wait)

        if select.select([sys.stdin], [], [], wait_time)[0]:
            line = sys.stdin.readline().strip().lower()
            if line in ("r", "refresh"):
                print("\n" + " " * (len(msg) + 60))
                print("🔄 Manual refresh triggered!")
                return True

    print(" " * 150, end="\r")
    return False

def wait_with_progress(wait_seconds: int, reason: str = "Rate limit"):
    if wait_seconds <= 0:
        return
    print('')
    start_time = time.time()
    total = wait_seconds
    bar_width = BASE_CONFIG["COUNTDOWN_BAR_WIDTH"]

    while True:
        elapsed = time.time() - start_time
        if elapsed >= total:
            break

        remaining = max(0, int(total - elapsed))
        progress = min(1.0, elapsed / total)
        filled = int(round(progress * bar_width))
        bar = "█" * filled + "─" * (bar_width - filled)

        msg = f"⚠️  {reason} - Waiting {remaining:3d}s  [{bar}]"
        print(msg + " " * 40, end="\r")
        sys.stdout.flush()
        time.sleep(0.2)

    print(" " * 180, end="\r")
    print(f"✅ {reason} cooldown finished.")

# ====================== BALANCE FETCHERS ======================
def get_sol_balance(rpc_url: str, pubkey: str) -> Decimal:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]}
    for attempt in range(5):
        try:
            r = requests.post(rpc_url, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                if _handle_rate_limit(str(data["error"])) and attempt < 4:
                    wait_with_progress(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"], "Solana RPC rate limit")
                    continue
                raise Exception(str(data["error"]))
            return Decimal(data["result"]["value"]) / Decimal('1000000000')
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                wait_with_progress(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"], "Solana RPC rate limit")
                continue
            raise
    raise Exception("SOL balance fetch failed after retries")

def get_orca_balance(rpc_url: str, pubkey: str, orca_mint: str) -> Decimal:
    """Now correctly sums ALL token accounts for the mint (critical fix)."""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [pubkey, {"mint": orca_mint}, {"encoding": "jsonParsed"}]
    }
    for attempt in range(5):
        try:
            r = requests.post(rpc_url, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data and _handle_rate_limit(str(data["error"])) and attempt < 4:
                wait_with_progress(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"], "Solana RPC rate limit")
                continue
            accounts = data.get("result", {}).get("value", [])
            total = Decimal('0')
            for acc in accounts:
                try:
                    info = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
                    amount = Decimal(info["amount"]) / Decimal(10 ** int(info["decimals"]))
                    total += amount
                except (KeyError, TypeError, ValueError):
                    continue
            return total
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                wait_with_progress(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"], "Solana RPC rate limit")
                continue
            raise
    raise Exception("ORCA balance fetch failed after retries")

def get_erc20_balance(w3: Web3, address: str, token_contract: str) -> Decimal:
    abi = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    ]
    contract = w3.eth.contract(address=token_contract, abi=abi)
    raw = contract.functions.balanceOf(address).call()
    decimals = contract.functions.decimals().call()
    return Decimal(raw) / Decimal(10 ** decimals)

# ====================== PORTFOLIO BAR (NOW WITH 1.5% SLIPPAGE) ======================
def print_portfolio_bar(asset1_sym: str, asset2_sym: str, ratio1: Decimal, bal1: Decimal, bal2: Decimal,
                        price1: Decimal, price2: Decimal, bar_char1: str, bar_char2: str):
    ratio2 = Decimal('1') - ratio1
    w = BASE_CONFIG["BAR_WIDTH"]
    # Pure Decimal calculation for bar blocks (no float)
    blocks1_decimal = (ratio1 * Decimal(w)).quantize(Decimal('1'), rounding='ROUND_HALF_EVEN')
    blocks1 = int(blocks1_decimal)
    bar = bar_char1 * blocks1 + bar_char2 * (w - blocks1)

    prec = BASE_CONFIG["PERCENT_PRECISION"]
    label1 = f"{ratio1 * Decimal('100'):.{prec}f}% {asset1_sym}"
    label2 = f"{ratio2 * Decimal('100'):.{prec}f}% {asset2_sym}"

    print("\n📊 Portfolio Allocation Visual:")
    if BASE_CONFIG["SHOW_HEADER_LABELS"]:
        padding = " " * (w - len(asset1_sym) - len(asset2_sym))
        print(f"   {asset1_sym}{padding}{asset2_sym}")
    print(f"   {bar}")
    spacing = w - len(label1) - len(label2) + 8
    print(f"   {label1}{' ' * spacing}{label2}")
    if BASE_CONFIG["SHOW_50_PERCENT_MARKER"]:
        print(f"   {'50%':^{w}}")

    total_usd = bal1 * price1 + bal2 * price2
    if total_usd > 1:
        target = total_usd / 2
        excess = (bal1 * price1) - target

        if excess >= 0:
            # Too much asset1 → sell some asset1 to buy asset2
            sell1 = excess / price1
            usd_after_slippage = excess * (Decimal('1') - SLIPPAGE)
            buy2 = usd_after_slippage / price2
            print(f"   To 50:50 → Sell ~{sell1:.6f} {asset1_sym} (~${excess:.2f} USD) "
                  f"→ buy ~{buy2:.4f} {asset2_sym} (after {SLIPPAGE*100:.1f}% slippage)")
        else:
            # Too much asset2 → sell some asset2 to buy asset1
            sell2 = abs(excess) / price2
            usd_after_slippage = abs(excess) * (Decimal('1') - SLIPPAGE)
            buy1 = usd_after_slippage / price1
            print(f"   To 50:50 → Sell ~{sell2:.4f} {asset2_sym} (~${abs(excess):.2f} USD) "
                  f"→ buy ~{buy1:.6f} {asset1_sym} (after {SLIPPAGE*100:.1f}% slippage)")
    else:
        print("   ⚠️  Portfolio value too small for rebalancing suggestion")

# ====================== MAIN FETCH & DISPLAY ======================
def fetch_and_display(portfolio: dict, address: str, w3: Web3 = None, save_to_csv: bool = False):
    kst_tz = zoneinfo.ZoneInfo(BASE_CONFIG["KST_TIMEZONE"])
    now_kst = datetime.now(kst_tz)
    timestamp_str = now_kst.strftime("%Y-%m-%d %H:%M:%S %Z")

    print(f"🔴 {portfolio['name']} Portfolio Monitor")
    print("=" * 90)
    print(f"Wallet  : {address}")

    start_date, elapsed = get_start_info(portfolio["csv_filename"], now_kst)
    print(f"Started : {start_date} (KST)   [{elapsed}]")

    print(f"Updated : {timestamp_str} (KST)")
    print("=" * 90)

    # Fetch balances (Decimal)
    if portfolio["chain"] == "solana":
        bal1 = get_sol_balance(portfolio["rpc_url"], address)
        bal2 = get_orca_balance(portfolio["rpc_url"], address, portfolio["orca_mint"])
    else:
        bal1 = get_erc20_balance(w3, address, portfolio["btcb_contract"])
        bal2 = get_erc20_balance(w3, address, portfolio["pepe_contract"])

    prices = get_prices(f"{portfolio['asset1']['cg_id']},{portfolio['asset2']['cg_id']}")
    price1 = prices[portfolio["asset1"]["cg_id"]]
    price2 = prices[portfolio["asset2"]["cg_id"]]

    val1 = bal1 * price1
    val2 = bal2 * price2
    total_usd = val1 + val2
    ratio1 = val1 / total_usd if total_usd > 0 else Decimal('0')

    equiv1 = bal1 + (val2 / price1) if price1 > 0 else bal1
    equiv2 = bal2 + (val1 / price2) if price2 > 0 else bal2

    ratio_asset2_per_asset1 = price1 / price2 if price1 > 0 and price2 > 0 else Decimal('0')
    ratio_asset1_per_asset2 = price2 / price1 if price1 > 0 and price2 > 0 else Decimal('0')

    # ====================== CSV WRITING (FULL PRECISION) ======================
    a1 = portfolio["asset1"]
    a2 = portfolio["asset2"]

    if save_to_csv:
        prev_col1 = f"{a1['col_prefix']}_balance"
        prev_col2 = f"{a2['col_prefix']}_balance"
        prev1, prev2 = get_previous_balances(portfolio["csv_filename"], prev_col1, prev_col2)

        change1 = bal1 - prev1
        change2 = bal2 - prev2
        change_usd1 = change1 * price1
        change_usd2 = change2 * price2

        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            f"{a1['col_prefix']}_balance": decimal_to_csv_str(bal1, 18),
            f"{a1['col_prefix']}_balance_change": decimal_to_csv_str(change1, 18),
            f"{a1['col_prefix']}_balance_change_usd": decimal_to_csv_str(change_usd1, 2),
            f"{a2['col_prefix']}_balance": decimal_to_csv_str(bal2, 18),
            f"{a2['col_prefix']}_balance_change": decimal_to_csv_str(change2, 18),
            f"{a2['col_prefix']}_balance_change_usd": decimal_to_csv_str(change_usd2, 2),
            f"{a1['col_prefix']}_price_usd": decimal_to_csv_str(price1, 12),
            f"{a2['col_prefix']}_price_usd": decimal_to_csv_str(price2, 24 if a2['symbol'] == "PEPE" else 12),
            f"{a1['col_prefix']}_value_usd": decimal_to_csv_str(val1, 2),
            f"{a2['col_prefix']}_value_usd": decimal_to_csv_str(val2, 2),
            "total_value_usd": decimal_to_csv_str(total_usd, 2),
            f"{a1['col_prefix']}_equivalent": decimal_to_csv_str(equiv1, 18),
            f"{a2['col_prefix']}_equivalent": decimal_to_csv_str(equiv2, 18),
            f"{a2['col_prefix']}_per_{a1['col_prefix']}": decimal_to_csv_str(ratio_asset2_per_asset1, 24),
            f"{a1['col_prefix']}_per_{a2['col_prefix']}": decimal_to_csv_str(ratio_asset1_per_asset2, 24),
            f"portfolio_{a1['col_prefix']}_ratio": decimal_to_csv_str(ratio1, 18),
            f"portfolio_{a2['col_prefix']}_ratio": decimal_to_csv_str(Decimal('1') - ratio1, 18),
        }

        fieldnames = list(row.keys())
        file_exists = os.path.isfile(portfolio["csv_filename"])
        with open(portfolio["csv_filename"], "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
                print(f"✅ Created new CSV file: {portfolio['csv_filename']}")
            else:
                print(f"✅ Appended new row to: {portfolio['csv_filename']}")
            writer.writerow(row)

    # ====================== DISPLAY SECTION (ALL DECIMAL FORMATTING) ======================
    print("\n📊 Current Balances:")
    print(f"   {a1['symbol']:4} : {bal1:,.{a1['balance_prec']}f} {a1['symbol']} (${val1:,.2f})")
    print(f"   {a2['symbol']:4} : {bal2:,.{a2['balance_prec']}f} {a2['symbol']} (${val2:,.2f})")
    print(f"   TOTAL : ${total_usd:,.2f}")

    print_portfolio_bar(a1["symbol"], a2["symbol"], ratio1, bal1, bal2, price1, price2,
                        portfolio["bar_char1"], portfolio["bar_char2"])

    chg_col1 = f"{a1['col_prefix']}_balance_change"
    chg_col2 = f"{a2['col_prefix']}_balance_change"
    last_change_info = get_minutes_since_last_balance_change(portfolio["csv_filename"], chg_col1, chg_col2)
    print(f"   Last balance change: {last_change_info}")

    # ====================== HYPOTHETICAL EQUIVALENTS (WITH 1.5% SLIPPAGE ON CROSS-ASSET) ======================
    print(f"\n🔄 Hypothetical Equivalents (USD base — after {SLIPPAGE*100:.1f}% slippage on cross-asset):")
    absolute_starts = load_absolute_starts()
    pair_key = portfolio.get("absolute_key")
    pair_data = absolute_starts.get(pair_key, {}) if pair_key else {}

    if pair_data:
        for asset in [a1, a2]:
            prefix = asset["col_prefix"]
            asset_baseline = pair_data.get(prefix)

            print(f"\n   {asset['symbol']} equivalent:")
            if isinstance(asset_baseline, dict) and "date_kst" in asset_baseline and "equivalent" in asset_baseline:
                base_date = asset_baseline["date_kst"]
                base_equiv = Decimal(str(asset_baseline["equivalent"]))

                # Current values
                if prefix == a1["col_prefix"]:
                    own_bal = bal1
                    other_val = val2
                    current_price = price1
                else:
                    own_bal = bal2
                    other_val = val1
                    current_price = price2

                # Apply slippage ONLY to the portion that would be swapped
                other_equiv_after_slip = (other_val * (Decimal('1') - SLIPPAGE)) / current_price
                current_equiv = own_bal + other_equiv_after_slip

                delta_abs = current_equiv - base_equiv
                delta_usd = delta_abs * current_price

                print(f"      Current    : {current_equiv:,.{asset['balance_prec']}f} {asset['symbol']}")
                print(f"      Baseline   : {base_equiv:,.{asset['balance_prec']}f} {asset['symbol']} ({base_date})")
                print(f"      Δ          : {delta_abs:+,.{asset['balance_prec']}f} | ${delta_usd:+,.2f}")
            else:
                print(f"      No baseline set yet for this token")
    else:
        print(f"   No absolute baselines configured for pair '{pair_key}' in {ABSOLUTE_STARTS_FILE}")

    print("\n💰 Current Prices:")
    print(f"   {a1['symbol']} = ${price1:,.{a1['price_prec']}f}")
    print(f"   {a2['symbol']} = ${price2:,.{a2['price_prec']}f}")

    if not save_to_csv:
        print("CSV skipped (automatic refresh)")

    return now_kst

# ====================== MAIN ======================
def main():
    print("=== Portfolio Monitor - Choose Pair ===")
    for k, v in PORTFOLIOS.items():
        print(f"[{k}] {v['name']}")
    choice = input("\nEnter choice (1 or 2): ").strip()

    if choice not in PORTFOLIOS:
        print("❌ Invalid choice.")
        return

    portfolio = PORTFOLIOS[choice]
    print(f"\n📍 Monitoring: {portfolio['name']}")

    address = input(f"\nEnter your {portfolio['chain'].upper()} wallet address: ").strip()
    if not address:
        print("❌ No address entered.")
        return

    w3 = None
    if portfolio["chain"] == "bsc":
        w3 = Web3(Web3.HTTPProvider(portfolio["rpc_url"]))
        if not w3.is_connected():
            print("❌ Failed to connect to BSC RPC.")
            return
        portfolio["btcb_contract"] = w3.to_checksum_address(portfolio["btcb_contract"])
        portfolio["pepe_contract"] = w3.to_checksum_address(portfolio["pepe_contract"])

    print(f"🔄 Live monitoring {portfolio['name']} — refresh every {BASE_CONFIG['REFRESH_INTERVAL']}s")
    print("   Press 'r' + Enter anytime for manual refresh + CSV save\n")

    save_next = True
    try:
        while True:
            clear_screen()
            fetch_and_display(portfolio, address, w3, save_to_csv=save_next)
            save_next = False
            if countdown(BASE_CONFIG["REFRESH_INTERVAL"]):
                save_next = True
    except KeyboardInterrupt:
        clear_screen()
        print("\n👋 Monitoring stopped.")
        print(f"   Data saved to: {portfolio['csv_filename']}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()
