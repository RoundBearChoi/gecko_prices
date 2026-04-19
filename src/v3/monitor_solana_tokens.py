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
    "RPC_URL": "https://api.mainnet-beta.solana.com",          # Public RPC (rate-limited). Replace with Helius/QuickNode/Ankr for production
    "COINGECKO_BASE": "https://api.coingecko.com/api/v3",
    "TOKENS_FILE": "tokens_list.json",
    "USD_STARTING_POINT_FILE": "usd_starting_point.json",      # <-- NEW: Manual overall USD starting point
    "KST_TZ": "Asia/Seoul",
    "DECIMAL_PRECISION": 50,
    "CSV_OUTPUT_DIR": Path("wallet_data"),
    "CSV_FILENAME_TEMPLATE": "solana_meme_portfolio_{timestamp}.csv",
    "INCLUDE_MINT_IN_CSV": True,
    "SLIPPAGE_PERCENT": 1.5,
}

getcontext().prec = CONFIG["DECIMAL_PRECISION"]
SLIPPAGE_PCT = Decimal(str(CONFIG["SLIPPAGE_PERCENT"]))
SLIPPAGE_FACTOR = Decimal("1") - (SLIPPAGE_PCT / Decimal("100"))
print(f"Slippage assumption loaded: {SLIPPAGE_PCT}% → effective factor {SLIPPAGE_FACTOR}")

# === MODERN STANDARD: Support both Token programs ===
TOKEN_PROGRAMS = [
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",   # Legacy SPL Token Program
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"    # Token-2022 Program (most new memes)
]
# =======================================================

def load_tokens() -> list[dict]:
    """Load tokens from tokens_list.json with include_in_portfolio support (defaults to True)."""
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

            include = token.get("include_in_portfolio", True)
            if not isinstance(include, bool):
                print(f"Warning: Token '{token.get('symbol', 'unknown')}' has invalid include_in_portfolio. Defaulting to True.")
                token["include_in_portfolio"] = True
            else:
                token["include_in_portfolio"] = include

        print(f"Loaded {len(tokens)} tokens from {CONFIG['TOKENS_FILE']}")
        return tokens

    except FileNotFoundError:
        print(f"Error: {CONFIG['TOKENS_FILE']} not found.")
        print("→ Please create it using the JSON format with 'include_in_portfolio'.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {CONFIG['TOKENS_FILE']}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error loading tokens: {e}")
        sys.exit(1)


def load_usd_starting_point() -> dict | None:
    """Load manual overall portfolio USD starting point from usd_starting_point.json.
    You update this file manually whenever you want to reset the benchmark."""
    file_path = Path(CONFIG["USD_STARTING_POINT_FILE"])
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        date = data.get("date", "N/A")
        usd_value = data.get("usd")
        if usd_value is None:
            print(f"Warning: 'usd' key missing in {CONFIG['USD_STARTING_POINT_FILE']}")
            return None

        usd = Decimal(str(usd_value))
        return {"date": date, "usd": usd}
    except Exception as e:
        print(f"Warning: Failed to load {CONFIG['USD_STARTING_POINT_FILE']}: {e}")
        return None


def get_all_token_accounts(wallet_address: str) -> dict[str, dict]:
    """Fetch ALL token accounts for the wallet from BOTH Token and Token-2022 programs."""
    token_data: dict[str, dict] = {}

    for program_id in TOKEN_PROGRAMS:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [wallet_address, {"programId": program_id}, {"encoding": "jsonParsed"}]
        }
        response = requests.post(CONFIG["RPC_URL"], json=payload, timeout=20)
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise Exception(f"Solana RPC error ({program_id}): {result['error']}")

        accounts = result.get("result", {}).get("value", [])

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
                token_data[mint] = {"raw_amount": raw_amount_str, "decimals": decimals}

    return token_data


def get_native_sol_balance(wallet_address: str) -> Decimal:
    """Fetch native SOL balance."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [wallet_address]
    }
    response = requests.post(CONFIG["RPC_URL"], json=payload, timeout=20)
    response.raise_for_status()
    result = response.json()
    if "error" in result:
        raise Exception(f"Solana RPC error (getBalance): {result['error']}")

    lamports = result.get("result", {}).get("value", 0)
    return Decimal(lamports) / Decimal("1000000000")


def get_prices(gecko_ids: list[str]) -> dict[str, Decimal]:
    """Batch fetch current USD prices from CoinGecko."""
    if not gecko_ids:
        return {}
    ids_str = ",".join(gecko_ids)
    url = f"{CONFIG['COINGECKO_BASE']}/simple/price"
    params = {"ids": ids_str, "vs_currencies": "usd"}
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    prices = {}
    for gid, price_info in data.items():
        if isinstance(price_info, dict) and "usd" in price_info:
            prices[gid] = Decimal(str(price_info["usd"]))
        else:
            prices[gid] = Decimal("0")
    return prices


def get_starting_snapshot(gecko_id: str) -> dict | None:
    """Load latest starting snapshot from {gecko_id}_starting_points.csv (unchanged)."""
    filename = f"{gecko_id}_starting_points.csv"
    path = Path(filename)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
            if not reader:
                return None
            last_row = reader[-1]
            equiv_str = last_row.get("equivalent_tokens_if_all_swapped", "0").strip() or "0"
            price_str = last_row.get("price_usd", "").strip()
            timestamp_str = last_row.get("timestamp_kst", "").strip()
            starting_date = timestamp_str.split()[0] if timestamp_str else "N/A"

            data = {"equivalent": Decimal(equiv_str), "starting_date": starting_date}
            if price_str:
                try:
                    data["starting_price"] = Decimal(price_str)
                except Exception:
                    data["starting_price"] = None
            else:
                data["starting_price"] = None
            return data
    except Exception as e:
        print(f"Warning: Failed to load starting snapshot for {gecko_id}: {e}")
        return None


def main():
    print("=== Solana Meme Coin Portfolio Tracker (CoinGecko + RPC + Equal Rebalance + Slippage + include_in_portfolio) ===\n")
    print("Now supports BOTH Token and Token-2022 programs (modern standard)")
    wallet = input("Enter your Solana wallet address: ").strip()
    if not wallet:
        print("No wallet address provided. Exiting.")
        return

    tokens = load_tokens()
    gecko_ids = [t["id"] for t in tokens]

    print("\nFetching USD prices from CoinGecko (free tier)...")
    prices = get_prices(gecko_ids)

    print("Fetching token balances from Solana RPC (Token + Token-2022)...")
    try:
        token_accounts = get_all_token_accounts(wallet)
        native_sol_balance = get_native_sol_balance(wallet)
    except Exception as e:
        print(f"RPC error: {e}")
        print("Tip: Public RPCs are rate-limited. Consider a free Helius/Ankr RPC key in CONFIG.")
        return

    # Build portfolio data for ALL tokens, but only sum included ones
    portfolio = []
    total_usd = Decimal("0")

    for token in tokens:
        gid = token["id"]
        mint = token.get("mint")
        symbol = token["symbol"]
        include_in_portfolio = token["include_in_portfolio"]

        price = prices.get(gid, Decimal("0"))

        if mint == "NATIVE":
            balance = native_sol_balance
        else:
            if mint in token_accounts:
                info = token_accounts[mint]
                raw = Decimal(info["raw_amount"])
                dec = info["decimals"]
                balance = raw / (Decimal(10) ** dec)
            else:
                balance = Decimal("0")

        value_usd = balance * price

        if include_in_portfolio:
            total_usd += value_usd

        portfolio.append({
            "gecko_id": gid,
            "symbol": symbol,
            "mint": mint if mint != "NATIVE" else "NATIVE_SOL",
            "balance": balance,
            "price_usd": price,
            "value_usd": value_usd,
            "include_in_portfolio": include_in_portfolio,
        })

    # Percentages & equivalents ONLY for included tokens
    if total_usd > 0:
        effective_total_after_slippage = total_usd * SLIPPAGE_FACTOR
        for item in portfolio:
            if item["include_in_portfolio"] and item["price_usd"] > Decimal("0"):
                item["percent"] = (item["value_usd"] / total_usd) * Decimal("100")
                item["equivalent"] = effective_total_after_slippage / item["price_usd"]
            else:
                item["percent"] = Decimal("0")
                item["equivalent"] = Decimal("0")
    else:
        for item in portfolio:
            item["percent"] = Decimal("0")
            item["equivalent"] = Decimal("0")

    # Timestamp
    kst_now = datetime.now(ZoneInfo(CONFIG["KST_TZ"]))
    timestamp_str = kst_now.strftime("%Y-%m-%d %H:%M:%S KST")
    filename_ts = kst_now.strftime("%Y%m%d_%H%M%S")

    # CSV output (unchanged)
    csv_dir = Path(CONFIG["CSV_OUTPUT_DIR"])
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / CONFIG["CSV_FILENAME_TEMPLATE"].format(timestamp=filename_ts)

    fieldnames = [
        "timestamp_kst", "total_usd", "gecko_id", "symbol", "mint", "token_count",
        "price_usd", "value_usd", "portfolio_percent", "equivalent_tokens_if_all_swapped",
        "include_in_portfolio"
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
                "portfolio_percent": f"{item.get('percent', 0):.8f}",
                "equivalent_tokens_if_all_swapped": str(item.get("equivalent", 0)),
                "include_in_portfolio": str(item["include_in_portfolio"]).lower()
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
            "equivalent_tokens_if_all_swapped": "",
            "include_in_portfolio": "true"
        })

    # ====================== Portfolio Breakdown ======================
    print("\n=== 📊 Portfolio Breakdown by USD Value ===")
    sorted_portfolio = sorted(portfolio, key=lambda x: x["value_usd"], reverse=True)
    held_included = [item for item in sorted_portfolio if item["balance"] > 0 and item["include_in_portfolio"]]

    if total_usd > 0 and held_included:
        print(f"{'Symbol':>12} | {'Balance':>18} | {'Value USD':>15} | {'Portfolio %':>10}")
        print("-" * 62)
        for item in held_included:
            print(f"{item['symbol']:>12} | "
                  f"{item['balance']:>18,.8f} | "
                  f"${item['value_usd']:>14,.4f} | "
                  f"{float(item['percent']):>9.4f}%")
    elif total_usd == 0:
        print("Portfolio value (included tokens only) is $0.00")
    else:
        print("No included tokens with positive balance found.")

    held_excluded = [item for item in sorted_portfolio if item["balance"] > 0 and not item["include_in_portfolio"]]
    if held_excluded:
        print("\n--- Monitored but EXCLUDED from portfolio calculations ---")
        print(f"{'Symbol':>12} | {'Balance':>18} | {'Value USD':>15}")
        print("-" * 55)
        for item in held_excluded:
            print(f"{item['symbol']:>12} | "
                  f"{item['balance']:>18,.8f} | "
                  f"${item['value_usd']:>14,.4f}  [EXCLUDED]")

    # ====================== Starting Equivalent Tokens Comparison (NOW SORTED BY DELTA USD) ======================
    print("\n=== 📈 Starting Equivalent Tokens Comparison ===")
    print("   (Only included tokens - slippage adjusted)")
    print(f"{'Symbol':>12} | {'Current Equiv':>22} | {'Starting Equiv':>22} | {'Delta Equiv':>22} | {'Delta USD':>19} | {'% Change':>12}")
    print("-" * 120)

    comparison_data = []

    for item in portfolio:                     # we use the full portfolio list (order doesn't matter before sorting)
        if not item["include_in_portfolio"]:
            continue
        snapshot = get_starting_snapshot(item["gecko_id"])
        if snapshot is not None:
            current = item["equivalent"]
            starting = snapshot["equivalent"]
            delta_equiv = current - starting
            delta_usd = delta_equiv * item["price_usd"]

            # Pre-format strings exactly as before
            delta_usd_str = f"${delta_usd:+,.2f}" if delta_usd != Decimal("0") else "$0.00"
            pct_str = f"{float((delta_equiv / starting) * Decimal('100')):+.2f}%" if starting > 0 else "N/A"

            comparison_data.append({
                "symbol": item["symbol"],
                "current": current,
                "starting": starting,
                "delta_equiv": delta_equiv,
                "delta_usd": delta_usd,
                "delta_usd_str": delta_usd_str,
                "pct_str": pct_str
            })

    # ── SORT BY DELTA USD ASCENDING (biggest negative/loss on top) ──
    comparison_data.sort(key=lambda x: x["delta_usd"])

    if comparison_data:
        for data in comparison_data:
            print(f"{data['symbol']:>12} | "
                  f"{data['current']:>22,.8f} | "
                  f"{data['starting']:>22,.8f} | "
                  f"{data['delta_equiv']:>22,.8f} | "
                  f"{data['delta_usd_str']:>19} | "
                  f"{data['pct_str']:>12}")
    else:
        print("No starting point CSV files found for included tokens.")

    # ====================== PRICE PERFORMANCE (UPDATED: NOW SORTED BY % CHANGE HIGH→LOW) ======================
    print("\n=== 📉 Price Performance vs Starting Point ===")

    # Collect performance data first so we can sort it cleanly
    price_performance = []
    for item in portfolio:
        if not item["include_in_portfolio"]:
            continue
        snapshot = get_starting_snapshot(item["gecko_id"])
        if snapshot and snapshot.get("starting_price") is not None and snapshot["starting_price"] > Decimal("0"):
            current_p = item["price_usd"]
            start_p = snapshot["starting_price"]
            delta_p = current_p - start_p
            pct_change = (delta_p / start_p) * Decimal("100")
            start_date = snapshot.get("starting_date", "N/A")

            price_performance.append({
                "symbol": item["symbol"],
                "current_p": current_p,
                "start_p": start_p,
                "delta_p": delta_p,
                "pct_change": pct_change,
                "start_date": start_date
            })

    if price_performance:
        # === SORT BY % CHANGE DESCENDING (highest to lowest) ===
        price_performance.sort(key=lambda x: x["pct_change"], reverse=True)

        print(f"{'Symbol':>12} | {'Current Price':>19} | {'Starting Price':>19} | {'Price Δ':>17} | {'% Change':>12} | {'Start Date':>12}")
        print("-" * 106)

        for perf in price_performance:
            current_str = f"${perf['current_p']:,.6f}"
            start_str = f"${perf['start_p']:,.6f}"
            delta_str = f"${perf['delta_p']:,.6f}"
            pct_str = f"{float(perf['pct_change']):+8.2f}%"

            print(f"{perf['symbol']:>12} | "
                  f"{current_str:>19} | "
                  f"{start_str:>19} | "
                  f"{delta_str:>17} | "
                  f"{pct_str:>12} | "
                  f"{perf['start_date']:>12}")
    else:
        print("No starting price data found in the _starting_points.csv files for included tokens.")

    # ====================== Suggested Rebalance ======================
    print("\n=== 🔄 Suggested Rebalance to Equal % Allocation ===")
    held_tokens = [item for item in portfolio if item["balance"] > Decimal("0") and item["include_in_portfolio"]]
    n_held = len(held_tokens)

    if n_held < 2 or total_usd < Decimal("10"):
        print("Need at least 2 held included tokens and >$10 total value to suggest rebalancing.")
    else:
        target_usd = total_usd / Decimal(n_held)
        target_pct = Decimal("100") / Decimal(n_held)
        effective_target_usd = target_usd * SLIPPAGE_FACTOR

        print(f"📌 Rebalancing among {n_held} included held tokens")
        print(f"   Target per token (gross): ${target_usd:,.6f} USD  ({target_pct:.2f}% each)")
        print(f"   After {SLIPPAGE_PCT}% slippage: ~${effective_target_usd:,.6f} USD deployable")

        print(f"\n{'Symbol':>12} | {'Current $':>14} | {'Current %':>9} | {'Action':>8} | {'USD Δ (gross)':>16} | {'Tokens Δ':>18}")
        print("-" * 92)

        total_sell_usd_gross = Decimal("0")
        actions = []

        for item in sorted(held_tokens, key=lambda x: x["value_usd"], reverse=True):
            delta_usd = item["value_usd"] - target_usd
            tokens_delta = delta_usd / item["price_usd"] if item["price_usd"] > Decimal("0") else Decimal("0")

            if delta_usd > Decimal("0"):
                action_str = "SELL"
                usd_str = f"-${delta_usd:,.6f}"
                token_delta_str = f"-{tokens_delta:,.8f}"
                total_sell_usd_gross += delta_usd
            elif delta_usd < Decimal("0"):
                action_str = "BUY "
                usd_str = f"+${abs(delta_usd):,.6f}"
                token_delta_str = f"+{abs(tokens_delta):,.8f}"
            else:
                action_str = " - "
                usd_str = "$0.000000"
                token_delta_str = "0.00000000"

            actions.append((item["symbol"], item["value_usd"], item["percent"], action_str, usd_str, token_delta_str))

        for sym, val, pct, act, usd_d, tok_d in actions:
            print(f"{sym:>12} | ${val:>12,.4f} | {float(pct):>8.2f}% | {act:>8} | {usd_d:>16} | {tok_d:>18}")

        print("-" * 92)
        print(f"💰 Total gross sell volume: ~${total_sell_usd_gross:,.4f} USD")
        print(f"   Expected after {SLIPPAGE_PCT}% slippage: ~${total_sell_usd_gross * SLIPPAGE_FACTOR:,.4f} USD")

    # ====================== NEW: OVERALL PORTFOLIO USD vs MANUAL STARTING POINT ======================
    print("\n=== 💵 Overall Portfolio USD Performance vs Manual Starting Point ===")
    starting_point = load_usd_starting_point()
    if starting_point:
        start_date = starting_point["date"]
        start_usd = starting_point["usd"]
        delta_usd = total_usd - start_usd

        if start_usd > 0:
            pct_change = (delta_usd / start_usd) * Decimal("100")
            pct_str = f"{float(pct_change):+.2f}%"
        else:
            pct_str = "N/A"

        print(f"Starting Date : {start_date}")
        print(f"Starting USD  : ${start_usd:,.2f}")
        print(f"Current USD   : ${total_usd:,.2f}")
        print(f"Delta         : ${delta_usd:+,.2f}")
        print(f"% Change      : {pct_str}")
        
    else:
        print("No usd_starting_point.json found (or it could not be read).")
        print("Create the file with this exact format:")
        print('{\n  "date": "2026-04-19",\n  "usd": 2450.75\n}')
        print("Then run the script again.")

    # Final summary
    included_count = sum(1 for t in portfolio if t["include_in_portfolio"])
    print(f"\n✅ Portfolio snapshot saved to: {csv_path}")
    print(f"   Total portfolio value (included tokens): ${total_usd:,.8f} USD")
    print(f"   Time (KST): {timestamp_str}")
    print(f"   Tokens tracked: {included_count} included / {len(portfolio)} total")


if __name__ == "__main__":
    main()
