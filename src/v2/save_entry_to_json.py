import csv
import json
import os
from decimal import Decimal, getcontext

# ========================= HIGH-PRECISION DECIMAL SETUP =========================
getcontext().prec = 36

# ========================= CONFIG =========================
ABSOLUTE_STARTS_FILE = "absolute_starts.json"

PORTFOLIOS = {
    "1": {  # SOL + ORCA
        "name": "SOL + ORCA (Solana)",
        "csv_filename": "solana_orca_balances.csv",
        "json_key": "sol_orca",
        "date_field": "readable_time_kst"
    },
    "2": {  # BTCB + PEPE
        "name": "BTCB + PEPE (BSC)",
        "csv_filename": "btcb_pepe_balances.csv",
        "json_key": "btcb_pepe",
        "date_field": "readable_time_kst"
    }
}

def load_json() -> dict:
    """Load existing absolute_starts.json or return empty dict."""
    if os.path.isfile(ABSOLUTE_STARTS_FILE):
        try:
            with open(ABSOLUTE_STARTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(data: dict):
    """Save with clean formatting."""
    with open(ABSOLUTE_STARTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"\n✅ {ABSOLUTE_STARTS_FILE} updated successfully!")

def main():
    print("=== entry_to_json.py (First or Last Entry as Absolute Baseline) ===")
    print("This script sets the absolute baseline for ONE specific token at a time.\n")

    for k, v in PORTFOLIOS.items():
        print(f"[{k}] {v['name']}")

    choice = input("\nSelect pair (1 or 2): ").strip()
    if choice not in PORTFOLIOS:
        print("❌ Invalid choice.")
        return

    config = PORTFOLIOS[choice]
    csv_file = config["csv_filename"]

    if not os.path.isfile(csv_file):
        print(f"❌ CSV file not found: {csv_file}")
        print("   Run monitor_pairs.py first to generate data.")
        return

    # === Choose which token ===
    print(f"\nWhich token to set baseline for in {config['name']}?")
    print("   1) SOL" if choice == "1" else "   1) BTCB")
    print("   2) ORCA" if choice == "1" else "   2) PEPE")
    token_choice = input("\nEnter choice (1 or 2): ").strip()

    token_map = {
        "1": ("sol", "sol_equivalent") if choice == "1" else ("btcb", "btcb_equivalent"),
        "2": ("orca", "orca_equivalent") if choice == "1" else ("pepe", "pepe_equivalent")
    }

    if token_choice not in token_map:
        print("❌ Invalid token choice.")
        return

    token_name, equiv_field = token_map[token_choice]
    display_name = token_name.upper()

    # === Read CSV to show options (prompt now truly at the "end") ===
    try:
        with open(csv_file, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("❌ CSV contains no data rows.")
            return

        first_row = rows[0]
        last_row = rows[-1]

        print(f"\n📅 Available entries in {csv_file}:")
        print(f"   First entry: {first_row.get(config['date_field'], 'Unknown')}")
        print(f"   Last entry : {last_row.get(config['date_field'], 'Unknown')}")

    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    # === Prompt at the end for first or last entry ===
    print("\nWhich entry do you want to save as the absolute baseline?")
    print("   F) First entry (earliest - recommended for true baseline)")
    print("   L) Last entry  (most recent)")
    entry_choice = input("\nEnter choice (F or L): ").strip().upper()

    if entry_choice not in ['F', 'L']:
        print("❌ Invalid choice.")
        return

    if entry_choice == 'F':
        selected_row = first_row
        entry_type = "first"
    else:
        selected_row = last_row
        entry_type = "last"

    # === Process selected row ===
    try:
        equiv_value = Decimal(selected_row[equiv_field])
        date_kst = selected_row.get(config["date_field"], "Unknown date")

        entry = {
            "date_kst": date_kst,
            "equivalent": float(equiv_value)   # JSON-compatible
        }

        data = load_json()
        if config["json_key"] not in data:
            data[config["json_key"]] = {}

        data[config["json_key"]][token_name] = entry
        save_json(data)

        print(f"\n📍 New absolute baseline set for {display_name} using the {entry_type} entry")
        print(f"   Date (KST) : {date_kst}")
        print(f"   Equivalent : {equiv_value:,.8f} {display_name}")

        print("\n💡 You can now run this script again for the other token (different entry type/date is allowed).")

    except KeyError as e:
        print(f"❌ Missing column in CSV: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    main()
