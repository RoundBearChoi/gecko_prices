import os
import csv
import glob

def get_balance_files():
    """Find every *_balances.csv in the current directory."""
    return glob.glob("*_balances.csv")

def detect_asset_prefixes(fieldnames):
    """Automatically find the two asset prefixes (e.g. 'sol', 'orca' or 'btcb', 'pepe')."""
    change_cols = [col for col in fieldnames 
                   if col.endswith('_balance_change') and not col.endswith('_change_usd')]
    if len(change_cols) != 2:
        return None, None
    prefix1 = change_cols[0].replace('_balance_change', '')
    prefix2 = change_cols[1].replace('_balance_change', '')
    return prefix1, prefix2

def symbol_from_prefix(prefix: str) -> str:
    """Nice human-readable symbol (easy to extend)."""
    mapping = {
        'sol': 'SOL', 'orca': 'ORCA',
        'btcb': 'BTCB', 'pepe': 'PEPE',
    }
    return mapping.get(prefix.lower(), prefix.upper())

def process_file(input_csv: str):
    base_name = input_csv.replace('_balances.csv', '')
    output_csv = f"{base_name}_net_delta_log.csv"
    
    print(f"📂 Processing: {input_csv}")
    
    # Read all rows
    with open(input_csv, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    
    if not rows:
        print("   ⚠️  Empty file — skipping")
        return
    
    # Detect the two assets from the first row's headers
    prefix1, prefix2 = detect_asset_prefixes(rows[0].keys())
    if not prefix1 or not prefix2:
        print("   ⚠️  Could not detect exactly two assets — skipping")
        return
    
    symbol1 = symbol_from_prefix(prefix1)
    symbol2 = symbol_from_prefix(prefix2)
    print(f"   ✅ Assets: {symbol1} + {symbol2}")
    
    output_rows = []
    cumulative_net_delta = 0.0
    event_count = 0
    
    for row in rows:
        try:
            chg1 = float(row.get(f"{prefix1}_balance_change", 0))
            chg2 = float(row.get(f"{prefix2}_balance_change", 0))
            usd1 = float(row.get(f"{prefix1}_balance_change_usd", 0))
            usd2 = float(row.get(f"{prefix2}_balance_change_usd", 0))
        except (ValueError, TypeError):
            continue
        
        # Only keep rows with actual balance changes
        if abs(chg1) > 1e-8 or abs(chg2) > 1e-8:
            net_delta_this_event = usd1 + usd2
            cumulative_net_delta += net_delta_this_event
            event_count += 1
            
            output_rows.append({
                "timestamp_kst": row["timestamp_kst"],
                "readable_time_kst": row.get("readable_time_kst", ""),
                f"{symbol1}_change": round(chg1, 8),
                f"{symbol1}_change_usd": round(usd1, 2),
                f"{symbol2}_change": round(chg2, 8),
                f"{symbol2}_change_usd": round(usd2, 2),
                "net_delta_usd": round(net_delta_this_event, 4),
                "cumulative_net_delta_usd": round(cumulative_net_delta, 4),
                "total_value_usd": row.get("total_value_usd", ""),
            })
    
    if output_rows:
        fieldnames = [
            "timestamp_kst", "readable_time_kst",
            f"{symbol1}_change", f"{symbol1}_change_usd",
            f"{symbol2}_change", f"{symbol2}_change_usd",
            "net_delta_usd", "cumulative_net_delta_usd",
            "total_value_usd"
        ]
        
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(output_rows)
        
        print(f"   ✅ Created {output_csv}")
        print(f"      📊 {event_count} balance-change events logged")
        print(f"      Final cumulative net delta: ${cumulative_net_delta:,.2f}")
    else:
        print("   No balance changes found.")

def main():
    print("=== Portfolio Net Delta Log Generator ===\n")
    files = get_balance_files()
    
    if not files:
        print("❌ No *_balances.csv files found in the current directory.")
        return
    
    print(f"Found {len(files)} balance history file(s):\n")
    
    for csv_file in files:
        process_file(csv_file)
        print("-" * 70)
    
    print("\n🎉 All net-delta logs generated successfully!")
    print("You can now open the new *_net_delta_log.csv files to see the full history.")

if __name__ == "__main__":
    main()
