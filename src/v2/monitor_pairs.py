import requests
import csv
import os
from datetime import datetime
import zoneinfo
import time
import sys
import select
from typing import Dict, Any, Tuple
from web3 import Web3

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
    },
    "2": {  # BTCB + PEPE (BSC)
        "name": "PEPE + BTCB (BSC)",
        "chain": "bsc",
        "rpc_url": "https://bsc-dataseed.binance.org/",
        "csv_filename": "btcb_pepe_balances.csv",
        "asset1": {"symbol": "BTCB",  "cg_id": "binance-bitcoin", "balance_prec": 6, "price_prec": 2, "col_prefix": "btcb"},
        "asset2": {"symbol": "PEPE",  "cg_id": "pepe",            "balance_prec": 2, "price_prec": 18, "col_prefix": "pepe"},
        "bar_char1": "█",
        "bar_char2": "─",
        "btcb_contract": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",
        "pepe_contract": "0x25d887ce7a35172c62febfd67a1856f20faebb00",
    }
}

# ====================== COMMON HELPERS ======================
def _handle_rate_limit(error_msg: str = "") -> bool:
    if not error_msg:
        return False
    msg_lower = error_msg.lower()
    return any(term in msg_lower for term in ["rate limit", "too many requests", "429", "rate exceeded"])

def get_previous_balances(csv_filename: str, col1: str, col2: str) -> Tuple[float, float]:
    if not os.path.isfile(csv_filename):
        return 0.0, 0.0
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return 0.0, 0.0
            last = rows[-1]
            return float(last.get(col1, 0)), float(last.get(col2, 0))
    except Exception:
        return 0.0, 0.0

def get_first_equivalents(csv_filename: str, col1: str, col2: str) -> Tuple[float, float]:
    if not os.path.isfile(csv_filename):
        return 0.0, 0.0
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if not rows:
                return 0.0, 0.0
            first = rows[0]
            return float(first.get(col1, 0)), float(first.get(col2, 0))
    except Exception:
        return 0.0, 0.0

def get_cumulative_negative_changes(csv_filename: str, chg_col1: str, chg_col2: str) -> Tuple[float, float]:
    if not os.path.isfile(csv_filename):
        return 0.0, 0.0
    cum1 = cum2 = 0.0
    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    v1 = float(row.get(chg_col1, 0) or 0)
                    v2 = float(row.get(chg_col2, 0) or 0)
                    if v1 < 0: cum1 += v1
                    if v2 < 0: cum2 += v2
                except (ValueError, TypeError):
                    continue
        return cum1, cum2
    except Exception:
        return 0.0, 0.0

# ====================== NEW HELPER: MINUTES SINCE LAST BALANCE CHANGE ======================
def get_minutes_since_last_balance_change(csv_filename: str, chg_col1: str, chg_col2: str) -> str:
    """Returns human-readable string showing minutes since the last non-zero balance change (deposit/withdrawal/swap)."""
    if not os.path.isfile(csv_filename):
        return "No CSV yet"

    try:
        with open(csv_filename, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            if len(rows) <= 1:
                return "No previous change recorded"

            kst_tz = zoneinfo.ZoneInfo(BASE_CONFIG["KST_TIMEZONE"])
            now_kst = datetime.now(kst_tz)

            # Scan backwards from newest row
            for row in reversed(rows):
                try:
                    chg1 = float(row.get(chg_col1, 0) or 0)
                    chg2 = float(row.get(chg_col2, 0) or 0)
                    if abs(chg1) > 1e-9 or abs(chg2) > 1e-9:  # tolerance for float precision
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
    """Return (readable_start_date, elapsed_str) with days (2 decimals) + hours in parentheses."""
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

def get_prices(cg_ids: str) -> Dict[str, float]:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_ids}&vs_currencies=usd&precision=full"
    wait = BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"]
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            return {k: v["usd"] for k, v in data.items()}
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                print(f"⚠️  CoinGecko rate limit. Waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise Exception("Failed to fetch prices after retries")

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# ====================== ENHANCED COUNTDOWN WITH PROGRESS BAR ======================
def countdown(refresh_interval: int) -> bool:
    """Enhanced countdown with visual progress bar (█/─ style, matching your portfolio bars)."""
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

# ====================== BALANCE FETCHERS ======================
def get_sol_balance(rpc_url: str, pubkey: str) -> float:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]}
    for attempt in range(5):
        try:
            r = requests.post(rpc_url, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                if _handle_rate_limit(str(data["error"])) and attempt < 4:
                    time.sleep(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"])
                    continue
                raise Exception(str(data["error"]))
            return data["result"]["value"] / 1_000_000_000
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                time.sleep(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"])
                continue
            raise
    raise Exception("SOL balance fetch failed after retries")

def get_orca_balance(rpc_url: str, pubkey: str, orca_mint: str) -> float:
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
                time.sleep(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"])
                continue
            accounts = data.get("result", {}).get("value", [])
            if not accounts:
                return 0.0
            info = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]
            return int(info["amount"]) / (10 ** int(info["decimals"]))
        except Exception as e:
            if _handle_rate_limit(str(e)) and attempt < 4:
                time.sleep(BASE_CONFIG["RATE_LIMIT_WAIT_SECONDS"])
                continue
            raise
    raise Exception("ORCA balance fetch failed after retries")

def get_erc20_balance(w3: Web3, address: str, token_contract: str) -> float:
    abi = [
        {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
        {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    ]
    contract = w3.eth.contract(address=token_contract, abi=abi)
    raw = contract.functions.balanceOf(address).call()
    decimals = contract.functions.decimals().call()
    return raw / (10 ** decimals)

# ====================== PORTFOLIO BAR ======================
def print_portfolio_bar(asset1_sym: str, asset2_sym: str, ratio1: float, bal1: float, bal2: float,
                        price1: float, price2: float, bar_char1: str, bar_char2: str):
    ratio2 = 1.0 - ratio1
    w = BASE_CONFIG["BAR_WIDTH"]
    blocks1 = int(round(ratio1 * w))
    bar = bar_char1 * blocks1 + bar_char2 * (w - blocks1)

    prec = BASE_CONFIG["PERCENT_PRECISION"]
    label1 = f"{ratio1*100:.{prec}f}% {asset1_sym}"
    label2 = f"{ratio2*100:.{prec}f}% {asset2_sym}"

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
    if total_usd > 1.0:
        target = total_usd / 2
        excess = (bal1 * price1) - target
        if excess >= 0:
            sell1 = excess / price1
            buy2 = excess / price2
            print(f"   To 50:50 → Sell ~{sell1:,.6f} {asset1_sym} (~${excess:,.2f} USD) to buy ~{buy2:,.4f} {asset2_sym}")
        else:
            sell2 = abs(excess) / price2
            buy1 = abs(excess) / price1
            print(f"   To 50:50 → Sell ~{sell2:,.4f} {asset2_sym} (~${abs(excess):,.2f} USD) to buy ~{buy1:,.6f} {asset1_sym}")
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

    # Fetch balances
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
    ratio1 = val1 / total_usd if total_usd > 0 else 0.0

    equiv1 = bal1 + (val2 / price1) if price1 > 0 else bal1
    equiv2 = bal2 + (val1 / price2) if price2 > 0 else bal2

    if price1 > 0 and price2 > 0:
        ratio_asset2_per_asset1 = price1 / price2
        ratio_asset1_per_asset2 = price2 / price1
    else:
        ratio_asset2_per_asset1 = 0.0
        ratio_asset1_per_asset2 = 0.0

    # ====================== CSV WRITING ======================
    if save_to_csv:
        a1 = portfolio["asset1"]
        a2 = portfolio["asset2"]

        prev_col1 = f"{a1['col_prefix']}_balance"
        prev_col2 = f"{a2['col_prefix']}_balance"
        prev1, prev2 = get_previous_balances(portfolio["csv_filename"], prev_col1, prev_col2)

        change1 = bal1 - prev1
        change2 = bal2 - prev2
        change_usd1 = change1 * price1
        change_usd2 = change2 * price2

        base_col1 = f"{a1['col_prefix']}_equivalent"
        base_col2 = f"{a2['col_prefix']}_equivalent"
        base1, base2 = get_first_equivalents(portfolio["csv_filename"], base_col1, base_col2)
        delta1 = equiv1 - base1
        delta2 = equiv2 - base2

        pepe_csv_round = 4 if a2['symbol'] == "PEPE" else 9

        row = {
            "timestamp_kst": now_kst.isoformat(),
            "readable_time_kst": timestamp_str,
            f"{a1['col_prefix']}_balance": round(bal1, 9),
            f"{a1['col_prefix']}_balance_change": round(change1, 9),
            f"{a1['col_prefix']}_balance_change_usd": round(change_usd1, 2),
            f"{a2['col_prefix']}_balance": round(bal2, pepe_csv_round),
            f"{a2['col_prefix']}_balance_change": round(change2, pepe_csv_round),
            f"{a2['col_prefix']}_balance_change_usd": round(change_usd2, 2),
            f"{a1['col_prefix']}_price_usd": round(price1, 6),
            f"{a2['col_prefix']}_price_usd": round(price2, 18 if a2['symbol'] == "PEPE" else 6),
            f"{a1['col_prefix']}_value_usd": round(val1, 2),
            f"{a2['col_prefix']}_value_usd": round(val2, 2),
            "total_value_usd": round(total_usd, 2),
            f"{a1['col_prefix']}_equivalent": round(equiv1, 9),
            f"{a2['col_prefix']}_equivalent": round(equiv2, pepe_csv_round),
            f"{a1['col_prefix']}_equivalent_change": round(delta1, 9),
            f"{a2['col_prefix']}_equivalent_change": round(delta2, pepe_csv_round),
            f"{a1['col_prefix']}_equivalent_change_usd": round(delta1 * price1, 2),
            f"{a2['col_prefix']}_equivalent_change_usd": round(delta2 * price2, 2),
            f"{a2['col_prefix']}_per_{a1['col_prefix']}": round(ratio_asset2_per_asset1, 6),
            f"{a1['col_prefix']}_per_{a2['col_prefix']}": round(ratio_asset1_per_asset2, 15),
            f"portfolio_{a1['col_prefix']}_ratio": round(ratio1, 6),
            f"portfolio_{a2['col_prefix']}_ratio": round(1 - ratio1, 6),
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

    # ====================== DISPLAY SECTION ======================
    print("\n📊 Current Balances:")
    a1 = portfolio["asset1"]
    a2 = portfolio["asset2"]
    print(f"   {a1['symbol']:4} : {bal1:,.{a1['balance_prec']}f} {a1['symbol']} (${val1:,.2f})")
    print(f"   {a2['symbol']:4} : {bal2:,.{a2['balance_prec']}f} {a2['symbol']} (${val2:,.2f})")
    print(f"   TOTAL : ${total_usd:,.2f}")

    print_portfolio_bar(a1["symbol"], a2["symbol"], ratio1, bal1, bal2, price1, price2,
                        portfolio["bar_char1"], portfolio["bar_char2"])

    # ====================== NEW: LAST BALANCE CHANGE ======================
    # (added exactly where you requested — right after the Portfolio Allocation Visual)
    chg_col1 = f"{a1['col_prefix']}_balance_change"
    chg_col2 = f"{a2['col_prefix']}_balance_change"
    last_change_info = get_minutes_since_last_balance_change(portfolio["csv_filename"], chg_col1, chg_col2)
    print(f"   Last balance change: {last_change_info}")

    # ====================== CUMULATIVE NEGATIVE USD CHANGES ======================
    chg_col1 = f"{a1['col_prefix']}_balance_change_usd"
    chg_col2 = f"{a2['col_prefix']}_balance_change_usd"
    neg1, neg2 = get_cumulative_negative_changes(portfolio["csv_filename"], chg_col1, chg_col2)

    print("\n📉 Cumulative Negative USD Changes:")
    print(f"   {a1['symbol']:4} : ${neg1:,.2f}      |      {a2['symbol']:4} : ${neg2:,.2f}")
    print(f"   Difference : ${abs(neg2 - neg1):.2f}")

    abs_neg1 = abs(neg1)
    abs_neg2 = abs(neg2)
    total_loss = abs_neg1 + abs_neg2

    if total_loss < 1e-6:
        balance_ratio = "1.00x"
        note = "(no losses recorded yet)"
    elif abs_neg2 < 1e-6:
        balance_ratio = "∞"
        note = f"(only {a1['symbol']} has losses)"
    elif abs_neg1 < 1e-6:
        balance_ratio = "0.00x"
        note = f"(only {a2['symbol']} has losses)"
    else:
        ratio = abs_neg1 / abs_neg2
        balance_ratio = f"{ratio:.2f}x"
        note = " (1.0x = perfectly balanced)"

    print(f"   Balance Ratio ({a1['symbol']}/{a2['symbol']}): {balance_ratio}{note}")

    if total_loss > 1:
        loss_ratio1 = abs_neg1 / total_loss
        skew_pct = abs(loss_ratio1 * 100 - 50)
        skew_towards = a1['symbol'] if loss_ratio1 > 0.5 else a2['symbol']
        print(f"   ⚖️ Skew: {skew_pct:.1f}% towards {skew_towards}")

    if total_loss > 1:
        loss_ratio1 = abs_neg1 / total_loss
        w = BASE_CONFIG["BAR_WIDTH"]
        blocks1 = int(round(loss_ratio1 * w))
        bar = portfolio["bar_char1"] * blocks1 + portfolio["bar_char2"] * (w - blocks1)

        prec = BASE_CONFIG["PERCENT_PRECISION"]
        label1 = f"{loss_ratio1*100:.{prec}f}% {a1['symbol']}"
        label2 = f"{(1-loss_ratio1)*100:.{prec}f}% {a2['symbol']}"

        print("\n📊 Cumulative Loss Distribution:")
        if BASE_CONFIG["SHOW_HEADER_LABELS"]:
            padding = " " * (w - len(a1['symbol']) - len(a2['symbol']))
            print(f"   {a1['symbol']}{padding}{a2['symbol']}")
        print(f"   {bar}")
        spacing = w - len(label1) - len(label2) + 8
        print(f"   {label1}{' ' * spacing}{label2}")
        if BASE_CONFIG["SHOW_50_PERCENT_MARKER"]:
            print(f"   {'50% ideal balance':^{w}}")
    else:
        print("\n📊 Cumulative Loss Distribution: (No significant losses recorded yet)")

    print("\n🔄 Hypothetical Equivalents (USD base):")
    base_col1 = f"{a1['col_prefix']}_equivalent"
    base_col2 = f"{a2['col_prefix']}_equivalent"
    base1, base2 = get_first_equivalents(portfolio["csv_filename"], base_col1, base_col2)
    delta1 = equiv1 - base1
    delta2 = equiv2 - base2
    print(f"   {a1['symbol']} equivalent : {equiv1:,.{a1['balance_prec']}f} {a1['symbol']}  (Δ {delta1:+,.{a1['balance_prec']}f} | ${delta1*price1:+,.2f})")
    print(f"   {a2['symbol']} equivalent : {equiv2:,.{a2['balance_prec']}f} {a2['symbol']}  (Δ {delta2:+,.{a2['balance_prec']}f} | ${delta2*price2:+,.2f})")

    print("\n💰 Current Prices:")
    print(f"   {a1['symbol']} ≈ ${price1:,.{a1['price_prec']}f}")
    print(f"   {a2['symbol']}  = ${price2:,.{a2['price_prec']}f}")

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
