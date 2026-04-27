from decimal import Decimal, getcontext, InvalidOperation
import csv
from pathlib import Path
import json
import urllib.request

# ==================== CONFIG SECTION ====================
# Adjust these variables here as needed. This is the only place you need to edit for basic use.
CONFIG = {
    'decimal_precision': 50,                                     # High internal precision for all calculations
    'summary_round_decimals': 8,                                 # Decimal places used ONLY when printing summary to console for readability

    # === Bar graph configuration ===
    'bar_width': 50,                                             # Maximum width of the visual bar (adjust as you like)
    'bar_char1': "█",                                            # LEFT side = Bought portion
    'bar_char2': "─",                                            # RIGHT side = Sold portion
}
# =======================================================

# Set global Decimal precision (only affects calculations, never the source data)
getcontext().prec = CONFIG['decimal_precision']


def format_d(d: Decimal, places: int | None = None) -> str:
    """Format Decimal for console display ONLY.
    Rounding happens here and nowhere else (not on calculations, not on CSV save).
    Always includes thousands separators for the entire result (as requested)."""
    if places is None:
        places = CONFIG['summary_round_decimals']
    rounded = d.quantize(Decimal('1.' + '0' * places))
    s = f"{rounded:f}"
    if '.' in s:
        integer_part, decimal_part = s.split('.')
        formatted_int = f"{int(integer_part):,}"
        return f"{formatted_int}.{decimal_part}"
    else:
        return f"{int(s):,}"


def print_bar_graph(added: Decimal, removed: Decimal, config: dict, current_price: Decimal | None = None, token_id: str = "token") -> None:
    """Print ONE single combined bar: bought (left, bar_char1) vs sold (right, bar_char2).
    Exactly 50/50 split lands in the center when volumes are equal."""
    print("\n" + "=" * 70)
    print(f"{token_id} BOUGHT vs SOLD - SINGLE BAR (50/50 at center)")
    print("=" * 70)

    if added <= 0 and removed <= 0:
        print("   → No buy/sell activity to visualize")
        print("=" * 70)
        return

    total = added + removed
    width = config.get('bar_width', 50)
    char_bought = config.get('bar_char1', '█')
    char_sold   = config.get('bar_char2', '─')

    if total > 0:
        bought_ratio = float(added / total)
        bought_len = round(bought_ratio * width)
        sold_len = width - bought_len
        # Guard against tiny values disappearing completely
        if added > 0 and bought_len == 0:
            bought_len = 1
            sold_len = width - 1
        if removed > 0 and bought_len == width:
            bought_len = width - 1
            sold_len = 1
    else:
        bought_len = sold_len = width // 2

    bar = char_bought * bought_len + char_sold * sold_len

    added_fmt = format_d(added)
    removed_fmt = format_d(removed)
    total_fmt = format_d(total)

    # Labels above the bar
    half = width // 2
    print(f"{'BOUGHT':<{half}}{'SOLD':>{half}}")
    print(bar)
    # Amounts aligned under each half
    print(f"{added_fmt:<{half}}{removed_fmt:>{half}}")
    print("=" * 70)

    # Updated total volume line with USD equivalent (based on current price)
    total_line = f"Total volume traded   : {total_fmt} {token_id}"
    if current_price is not None and total > 0:
        total_usd = total * current_price
        total_usd_fmt = format_d(total_usd)
        total_line += f" ({total_usd_fmt} USD)"
    print(total_line)

    bought_pct = round(float(added / total * 100), 1) if total > 0 else 0.0
    sold_pct   = round(float(removed / total * 100), 1) if total > 0 else 0.0
    print(f"Ratio (buy/sell)      : {bought_pct:5.1f}% / {sold_pct:5.1f}%")
    net_tokens = added - removed
    print(f"Net tokens            : {format_d(net_tokens)} {token_id}")


def get_current_price(token_id: str) -> Decimal | None:
    """Fetch current USD price from CoinGecko API using the exact token_id.
    Returns Decimal on success, None on any failure (network, API error, unknown token, etc.)."""
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={token_id}&vs_currencies=usd"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            price_str = data.get(token_id, {}).get('usd')
            if price_str is not None:
                return Decimal(str(price_str))
        return None
    except Exception as e:
        print(f"⚠️  Could not fetch current {token_id} price from CoinGecko: {e}")
        return None


def process_portfolio(input_path: Path, token_id: str) -> None:
    """
    Process a single portfolio CSV file for the given token_id.
    Handles cleaning duplicate snapshots and tracks buy/sell activity.
    """
    if not input_path.exists():
        print(f"❌ Error: '{input_path}' not found.")
        return

    # Step 1: Load the raw CSV
    with open(input_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        original_rows = list(reader)
        fieldnames = reader.fieldnames or []

    # === EXPLICIT EDGE-CASE HANDLING ===
    if not original_rows:
        print(f"✅ '{input_path.name}' contains only a header (0 data rows).")
        print("   → No cleaning needed - file left completely unchanged.")
        filtered_rows = []
    elif len(original_rows) <= 1:
        print(f"✅ Loaded {len(original_rows):,} data row(s) from {input_path.name}")
        print(f"   → Only {len(original_rows)} row(s) detected. No cleaning needed - file left completely unchanged.")
        filtered_rows = original_rows
    else:
        print(f"✅ Loaded {len(original_rows):,} total snapshot rows from {input_path.name}")

        # Step 2: Filter unchanged rows
        filtered_rows = []
        prev_token_bal: Decimal | None = None
        prev_usdc_bal: Decimal | None = None

        for row in original_rows:
            try:
                curr_token = Decimal(row['token_balance'])
                curr_usdc = Decimal(row['usdc_balance'])
            except (KeyError, InvalidOperation, ValueError):
                print(f"⚠️  Skipping malformed row (cannot parse balances): {row.get('timestamp_kst', 'unknown')}")
                continue

            if (prev_token_bal is None or
                    curr_token != prev_token_bal or
                    curr_usdc != prev_usdc_bal):
                filtered_rows.append(row)
                prev_token_bal = curr_token
                prev_usdc_bal = curr_usdc

        removed_count = len(original_rows) - len(filtered_rows)
        print(f"✅ Filtered down to {len(filtered_rows):,} meaningful rows "
              f"(removed {removed_count:,} rows with no balance change)")

        # Step 3: OVERWRITE only if we actually removed rows
        if removed_count > 0 and filtered_rows:
            with open(input_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(filtered_rows)
            print(f"✅ Original file '{input_path.name}' has been overwritten with the cleaned version")
            print("   → Only rows where token or USDC balance actually changed are kept")
        else:
            print(f"✅ No changes needed – '{input_path.name}' already contains only meaningful rows")
            filtered_rows = original_rows

    # Step 4: Track added vs removed
    total_token_added = Decimal('0')
    total_token_removed = Decimal('0')
    balance_changes = []

    for i in range(1, len(filtered_rows)):
        prev_token = Decimal(filtered_rows[i - 1]['token_balance'])
        curr_token = Decimal(filtered_rows[i]['token_balance'])
        delta = curr_token - prev_token
        timestamp = filtered_rows[i].get('timestamp_kst', 'unknown')

        if delta > 0:
            total_token_added += delta
            balance_changes.append(f"{timestamp} | +{format_d(delta)} {token_id} (bought)")
        elif delta < 0:
            removed_amount = -delta
            total_token_removed += removed_amount
            balance_changes.append(f"{timestamp} | -{format_d(removed_amount)} {token_id} (sold)")

    if filtered_rows:
        initial_token = Decimal(filtered_rows[0]['token_balance'])
        final_token = Decimal(filtered_rows[-1]['token_balance'])
        net_token = final_token - initial_token
    else:
        initial_token = final_token = net_token = Decimal('0')

    current_price = get_current_price(token_id)

    # Step 5: Rich console summary
    print("\n" + "=" * 70)
    print(f"{token_id} BALANCE FLOW SUMMARY")
    print("=" * 70)

    if current_price is not None:
        print(f"Current price ({token_id})          : {format_d(current_price)} USD")

    print(f"Initial balance                   : {format_d(initial_token)}")
    print(f"Final balance                     : {format_d(final_token)}")

    net_str = format_d(net_token)
    if current_price is not None:
        net_usd = net_token * current_price
        net_usd_str = format_d(net_usd)
        net_str += f" ({net_usd_str} USD)"
    print(f"Net change                        : {net_str}")

    print(f"Total added                       : {format_d(total_token_added)}")
    print(f"Total removed                     : {format_d(total_token_removed)}")
    print(f"Number of balance-change events   : {len(balance_changes):,}")
    print("=" * 70)

    if balance_changes:
        print("\n📋 DETAILED FLOW EVENTS:")
        for change in balance_changes:
            print(f"   {change}")
        print("=" * 70)
        print(f"   → {len(balance_changes):,} actual {token_id} flow events recorded")
    else:
        print("   → No balance changes detected (portfolio was completely static)")

    # === Single combined bar graph ===
    print_bar_graph(total_token_added, total_token_removed, CONFIG, current_price, token_id)


def main() -> None:
    """
    Discovers all solana_portfolio_*_usdc.csv files and processes each one.
    """
    portfolio_files = sorted(Path('.').glob('solana_portfolio_*_usdc.csv'))

    if not portfolio_files:
        print(f"❌ Error: No files matching pattern 'solana_portfolio_*_usdc.csv' found in the current directory.")
        print("   Make sure the CSVs are in the same folder as this script.")
        return

    print(f"✅ Found {len(portfolio_files):,} portfolio CSV files to process.")

    for file_path in portfolio_files:
        stem = file_path.stem
        parts = stem.split('_')
        
        # Expected format: solana_portfolio_{token_id}_usdc.csv
        if len(parts) >= 4 and parts[0] == 'solana' and parts[1] == 'portfolio' and parts[-1] == 'usdc':
            token_id = '_'.join(parts[2:-1])
            print(f"\n{'=' * 90}")
            print(f"🚀 PROCESSING {token_id} ({file_path.name})")
            print(f"{'=' * 90}\n")
            
            process_portfolio(file_path, token_id)
        else:
            print(f"⚠️  Skipping unrecognized file: {file_path.name}")

    print(f"\n{'=' * 90}")
    print("🎉 ALL PORTFOLIO FILES HAVE BEEN PROCESSED SUCCESSFULLY!")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    main()
