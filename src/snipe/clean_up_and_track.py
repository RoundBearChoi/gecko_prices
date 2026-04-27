from decimal import Decimal, getcontext, InvalidOperation
import csv
from pathlib import Path
import json
import urllib.request

# ==================== CONFIG SECTION ====================
# Adjust these variables here as needed. This is the only place you need to edit for basic use.
CONFIG = {
    'input_file': 'solana_portfolio_fartcoin_usdc.csv',          # Will be overwritten with filtered version
    'decimal_precision': 50,                                     # High internal precision for all calculations
    'summary_round_decimals': 8,                                 # Decimal places used ONLY when printing summary to console for readability
    'token_id': 'fartcoin',                                      # CoinGecko API ID - never modify this value anywhere (no uppercasing or changes)
    'stable_name': 'usdc',                                       # For readable output
    # Future extensions you can add here:
    # 'minimum_change_threshold': Decimal('0.000001'),  # optional filter for tiny noise
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
    # quantize rounds cleanly to the requested decimal places (banker's rounding)
    rounded = d.quantize(Decimal('1.' + '0' * places))
    
    # CRITICAL FIX: force fixed-point notation (:f)
    # This turns '0E-8', '1.23E+4', etc. into clean '0.00000000' / '1234.00000000'
    # Guarantees the rest of the function never sees scientific notation.
    # This fixes the Linux/WSL difference you were seeing.
    s = f"{rounded:f}"
    
    # Add thousands separator (works correctly with negative numbers)
    if '.' in s:
        integer_part, decimal_part = s.split('.')
        formatted_int = f"{int(integer_part):,}"
        return f"{formatted_int}.{decimal_part}"
    else:
        return f"{int(s):,}"


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


def main() -> None:
    """
    Main processing function.
    Reads the CSV, filters unchanged balance rows, tracks FARTCOIN inflows/outflows,
    OVERWRITES the original CSV with the cleaned version (exact original strings preserved),
    fetches current price, and prints the updated summary.
    """
    input_path = Path(CONFIG['input_file'])
    if not input_path.exists():
        print(f"❌ Error: '{CONFIG['input_file']}' not found in the current directory.")
        print("   Make sure the CSV is in the same folder as this script.")
        return

    # Step 1: Load the raw CSV (keep original string values for filtered output)
    with open(input_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        original_rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not original_rows:
        print("❌ No data rows found in the CSV.")
        return

    print(f"✅ Loaded {len(original_rows):,} total snapshot rows from {CONFIG['input_file']}")

    # Step 2: Filter to keep only rows where FARTCOIN or USDC balance actually changed
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

    # Step 3: OVERWRITE the original CSV with the filtered data
    if removed_count > 0 and filtered_rows:
        with open(input_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(filtered_rows)
        print(f"✅ Original file '{CONFIG['input_file']}' has been overwritten with the cleaned version")
        print("   → Only rows where FARTCOIN or USDC balance actually changed are kept")
        print("   → All numeric values written exactly as they appeared in the original CSV (full precision preserved)")
    else:
        print(f"✅ No changes needed – '{CONFIG['input_file']}' already contains only meaningful rows")

    # Step 4: Track FARTCOIN added vs removed (only between filtered rows)
    total_fart_added = Decimal('0')
    total_fart_removed = Decimal('0')
    balance_changes = []

    for i in range(1, len(filtered_rows)):
        prev_token = Decimal(filtered_rows[i - 1]['token_balance'])
        curr_token = Decimal(filtered_rows[i]['token_balance'])
        delta = curr_token - prev_token
        timestamp = filtered_rows[i].get('timestamp_kst', 'unknown')

        if delta > 0:
            total_fart_added += delta
            balance_changes.append(f"{timestamp} | +{format_d(delta)} {CONFIG['token_id']} (bought)")
        elif delta < 0:
            removed_amount = -delta
            total_fart_removed += removed_amount
            balance_changes.append(f"{timestamp} | -{format_d(removed_amount)} {CONFIG['token_id']} (sold)")

    # Final calculations (still using full Decimal precision)
    if filtered_rows:
        initial_fart = Decimal(filtered_rows[0]['token_balance'])
        final_fart = Decimal(filtered_rows[-1]['token_balance'])
        net_fart = final_fart - initial_fart
    else:
        initial_fart = final_fart = net_fart = Decimal('0')

    current_price = get_current_price(CONFIG['token_id'])

    # Step 5: Rich console summary (rounded ONLY for readability)
    print("\n" + "=" * 70)
    print("FARTCOIN BALANCE FLOW SUMMARY")
    print("=" * 70)

    if current_price is not None:
        print(f"Current price ({CONFIG['token_id']})          : {format_d(current_price)} USD")

    print(f"Initial balance                   : {format_d(initial_fart)}")
    print(f"Final balance                     : {format_d(final_fart)}")

    # Net change with USD equivalent
    net_str = format_d(net_fart)
    if current_price is not None:
        net_usd = net_fart * current_price
        net_usd_str = format_d(net_usd)
        net_str += f" ({net_usd_str} USD)"
    print(f"Net change                        : {net_str}")

    print(f"Total added                       : {format_d(total_fart_added)}")
    print(f"Total removed                     : {format_d(total_fart_removed)}")
    print(f"Number of balance-change events   : {len(balance_changes):,}")
    print("=" * 70)

    # Optional detailed changes
    if balance_changes:
        print("\n📋 DETAILED FARTCOIN FLOW EVENTS:")
        for change in balance_changes:
            print(f"   {change}")
        print("=" * 70)

    if balance_changes:
        print(f"   → {len(balance_changes):,} actual FARTCOIN flow events recorded")
    else:
        print("   → No balance changes detected (portfolio was completely static)")


if __name__ == "__main__":
    main()
