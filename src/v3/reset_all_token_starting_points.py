import csv
from pathlib import Path
import sys

# ==================== CONFIG SECTION ====================
CONFIG = {
    "CSV_OUTPUT_DIR": Path("wallet_data"),
}


def get_latest_portfolio_csv() -> Path:
    """Find the most recent portfolio CSV file in wallet_data/."""
    csv_dir = CONFIG["CSV_OUTPUT_DIR"]
    if not csv_dir.exists():
        print(f"❌ Error: Directory '{csv_dir}' not found.")
        print("   → Please run monitor_solana_tokens.py first to generate wallet data CSVs.")
        sys.exit(1)

    csv_files = list(csv_dir.glob("solana_meme_portfolio_*.csv"))
    if not csv_files:
        print("❌ Error: No portfolio CSV files found in wallet_data/.")
        print("   → Run the main monitor script at least once.")
        sys.exit(1)

    # Filenames contain timestamp (YYYYMMDD_HHMMSS) → string sort works perfectly
    latest = max(csv_files, key=lambda p: p.name)
    print(f"✅ Using latest portfolio snapshot: {latest.name}")
    return latest


def update_starting_file(starting_file: Path, row: dict, portfolio_fieldnames: list[str]):
    """Write or append row to starting_points.csv, handling schema evolution (new columns like monero_*) gracefully."""
    row_to_write = row.copy()
    file_exists = starting_file.exists()

    if file_exists:
        # Read existing rows to preserve full history
        with open(starting_file, "r", encoding="utf-8") as f:
            existing_rows = list(csv.DictReader(f))

        # Merge fieldnames (union of old header + current portfolio columns)
        existing_fieldnames = set(existing_rows[0].keys()) if existing_rows else set()
        new_fieldnames = set(portfolio_fieldnames)
        all_fieldnames = sorted(list(existing_fieldnames | new_fieldnames))

        # Overwrite file with updated schema
        with open(starting_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames)
            writer.writeheader()

            # Write existing rows, filling any missing new fields
            for old_row in existing_rows:
                for fn in all_fieldnames:
                    if fn not in old_row:
                        old_row[fn] = ""
                writer.writerow(old_row)

            # Write the new snapshot row, filling any missing fields
            for fn in all_fieldnames:
                if fn not in row_to_write:
                    row_to_write[fn] = ""
            writer.writerow(row_to_write)

        print(f"✅ Updated (schema migrated) {starting_file.name}  ←  {row.get('symbol', 'unknown')} ({row.get('gecko_id', '')})")
    else:
        # Create brand-new file
        with open(starting_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=portfolio_fieldnames)
            writer.writeheader()
            writer.writerow(row_to_write)
        print(f"✅ Created {starting_file.name}  ←  {row.get('symbol', 'unknown')} ({row.get('gecko_id', '')})")


def main():
    print("=== Reset All Token Starting Points (Monero Equivalents Supported) ===\n")
    print("This script reads the LATEST CSV from wallet_data/")
    print("and sets the current portfolio snapshot as the new")
    print("starting point for EVERY token (including excluded ones).\n")
    print("• Now includes new columns: monero_price_usd, monero_equivalent")
    print("• If a {gecko_id}_starting_points.csv does not exist → it is created")
    print("• If it already exists → the new snapshot is APPENDED + old data is migrated")
    print("  (the LAST row always becomes the active starting point for monitor.py)")
    print("• Fully handles CSV schema evolution when new columns are added\n")

    latest_csv_path = get_latest_portfolio_csv()

    # Read the entire latest portfolio CSV (now contains Monero columns)
    try:
        with open(latest_csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        sys.exit(1)

    if not reader:
        print("❌ Latest CSV appears to be empty.")
        sys.exit(1)

    # Extract fieldnames from the first row (includes monero_* columns)
    portfolio_fieldnames = list(reader[0].keys())

    processed = 0
    for row in reader:
        gecko_id = row.get("gecko_id", "").strip()
        if gecko_id == "TOTAL" or not gecko_id:
            continue

        symbol = row.get("symbol", "unknown")
        starting_file = Path(f"{gecko_id}_starting_points.csv")

        try:
            update_starting_file(starting_file, row, portfolio_fieldnames)
            processed += 1
        except Exception as e:
            print(f"❌ Failed to update {gecko_id}: {e}")

    print(f"\n🎉 Reset complete!")
    print(f"   Processed {processed} tokens.")
    print(f"   All {gecko_id}_starting_points.csv files now use the current portfolio")
    print(f"   as their new baseline (last row = active starting point).")
    print(f"   Monero equivalent data has been safely included in every snapshot.")
    print("\nYou can now run monitor_solana_tokens.py again.")
    print("The 'Starting Equivalent Tokens Comparison' and 'Price Performance'")
    print("sections will immediately reflect the new starting point (and Monero data is preserved).")


if __name__ == "__main__":
    main()
