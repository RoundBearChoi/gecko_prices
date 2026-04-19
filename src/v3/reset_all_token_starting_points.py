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


def main():
    print("=== Reset All Token Starting Points ===\n")
    print("This script reads the LATEST CSV from wallet_data/")
    print("and sets the current portfolio snapshot as the new")
    print("starting point for EVERY token (including excluded ones).\n")
    print("• If a {gecko_id}_starting_points.csv does not exist → it is created")
    print("• If it already exists → the new snapshot is APPENDED")
    print("  (the LAST row always becomes the active starting point)\n")

    latest_csv_path = get_latest_portfolio_csv()

    # Read the entire latest portfolio CSV
    try:
        with open(latest_csv_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        sys.exit(1)

    if not reader:
        print("❌ Latest CSV appears to be empty.")
        sys.exit(1)

    # Extract fieldnames from the first row (all CSVs have identical structure)
    fieldnames = list(reader[0].keys())

    processed = 0
    for row in reader:
        gecko_id = row.get("gecko_id", "").strip()
        if gecko_id == "TOTAL" or not gecko_id:
            continue

        symbol = row.get("symbol", "unknown")
        starting_file = Path(f"{gecko_id}_starting_points.csv")

        # Decide write mode
        file_exists = starting_file.exists()
        mode = "a" if file_exists else "w"

        try:
            with open(starting_file, mode, newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if mode == "w":
                    writer.writeheader()
                writer.writerow(row)

            status = "✅ Appended to" if file_exists else "✅ Created"
            print(f"{status} {starting_file.name}  ←  {symbol} ({gecko_id})")
            processed += 1

        except Exception as e:
            print(f"❌ Failed to update {gecko_id}: {e}")

    print(f"\n🎉 Reset complete!")
    print(f"   Processed {processed} tokens.")
    print(f"   All {gecko_id}_starting_points.csv files now use the current portfolio")
    print(f"   as their new baseline (last row = active starting point).")
    print("\nYou can now run monitor_solana_tokens.py again.")
    print("The 'Starting Equivalent Tokens Comparison' and 'Price Performance'")
    print("sections will immediately reflect the new starting point.")


if __name__ == "__main__":
    main()
