from decimal import Decimal, getcontext, InvalidOperation
import csv
from pathlib import Path

# ==================== CONFIG SECTION ====================
# Adjust these variables here as needed. This is the only place you need to edit for basic use.
CONFIG = {
    'input_file': 'solana_portfolio_fartcoin_usdc.csv',          # Will be overwritten with filtered version
    'decimal_precision': 50,                                     # High internal precision for all calculations
    'summary_round_decimals': 8,                                 # Decimal places used ONLY when printing summary to console for readability
    'token_name': 'fartcoin',                                    # For readable output
    'stable_name': 'usdc',                                       # For readable output
    # Future extensions you can add here:
    # 'minimum_change_threshold': Decimal('0.000001'),  # optional filter for tiny noise
}
# =======================================================

# Set global Decimal precision (only affects calculations, never the source data)
getcontext().prec = CONFIG['decimal_precision']


def format_d(d: Decimal, places: int | None = None) -> str:
    """Format Decimal for console display ONLY.
    Rounding happens here and nowhere else (not on calculations, not on CSV save)."""
    if places is None:
        places = CONFIG['summary_round_decimals']
    # quantize rounds cleanly to the requested decimal places (banker's rounding)
    rounded = d.quantize(Decimal('1.' + '0' * places))
    return str(rounded)


def main() -> None:
    """
    Main processing function.
    Reads the CSV, filters unchanged balance rows, tracks FARTCOIN inflows/outflows,
    OVERWRITES the original CSV with the cleaned version (exact original strings preserved),
    and prints a rich summary (rounded for readability only).
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
    # This removes "noise" rows where the script polled prices but no trade occurred.
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

        # Keep the row if it's the first one OR at least one balance changed
        if (prev_token_bal is None or
                curr_token != prev_token_bal or
                curr_usdc != prev_usdc_bal):
            filtered_rows.append(row)  # store original dict → exact string values preserved
            prev_token_bal = curr_token
            prev_usdc_bal = curr_usdc

    removed_count = len(original_rows) - len(filtered_rows)
    print(f"✅ Filtered down to {len(filtered_rows):,} meaningful rows "
          f"(removed {removed_count:,} rows with no balance change)")

    # Step 3: OVERWRITE the original CSV with the filtered data
    # IMPORTANT: We write the original row dicts exactly as read → full original precision is guaranteed.
    # No Decimal conversion or rounding is applied to any column when saving.
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
    # We use the *filtered* rows so we capture the true net effect of each trade/rebalance.
    total_fart_added = Decimal('0')
    total_fart_removed = Decimal('0')
    balance_changes = []  # list of human-readable change descriptions

    for i in range(1, len(filtered_rows)):
        prev_token = Decimal(filtered_rows[i - 1]['token_balance'])
        curr_token = Decimal(filtered_rows[i]['token_balance'])
        delta = curr_token - prev_token
        timestamp = filtered_rows[i].get('timestamp_kst', 'unknown')

        if delta > 0:
            total_fart_added += delta
            balance_changes.append(f"{timestamp} | +{format_d(delta)} {CONFIG['token_name'].upper()} (bought)")
        elif delta < 0:
            removed_amount = -delta
            total_fart_removed += removed_amount
            balance_changes.append(f"{timestamp} | -{format_d(removed_amount)} {CONFIG['token_name'].upper()} (sold)")

    # Final calculations (still using full Decimal precision)
    if filtered_rows:
        initial_fart = Decimal(filtered_rows[0]['token_balance'])
        final_fart = Decimal(filtered_rows[-1]['token_balance'])
        net_fart = final_fart - initial_fart
    else:
        initial_fart = final_fart = net_fart = Decimal('0')

    # Verification: net should equal added - removed
    verification = total_fart_added - total_fart_removed

    # Step 5: Rich console summary (rounded ONLY for readability)
    print("\n" + "=" * 70)
    print("FARTCOIN BALANCE FLOW SUMMARY")
    print("=" * 70)
    print(f"Initial {CONFIG['token_name'].upper():<12} balance : {format_d(initial_fart)}")
    print(f"Final   {CONFIG['token_name'].upper():<12} balance : {format_d(final_fart)}")
    print(f"Net change                     : {format_d(net_fart)}")
    print(f"Total {CONFIG['token_name'].upper():<12} added      : {format_d(total_fart_added)}")
    print(f"Total {CONFIG['token_name'].upper():<12} removed/left: {format_d(total_fart_removed)}")
    print(f"Verification (added - removed) : {format_d(verification)}")
    print(f"Number of balance-change events: {len(balance_changes):,}")
    print("=" * 70)

    # Optional detailed changes (also using rounded display)
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
