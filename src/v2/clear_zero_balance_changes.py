import pandas as pd
import glob
import os
from pathlib import Path
import numpy as np

# ================================================
# MAIN SCRIPT: Process all *_balances.csv files
# ================================================
# What this does:
# 1. Automatically discovers every CSV file whose name contains "_balances"
# 2. For each file, identifies every column that tracks balance *changes* (e.g. btcb_balance_change, pepe_balance_change, sol_balance_change, etc.)
# 3. Removes every row where **all** balance-change columns are zero (or extremely close to zero)
# 4. Keeps only the rows that represent actual portfolio movements (trades, swaps, deposits, withdrawals, etc.)
# 5. Saves a new filtered CSV with "_filtered" added to the original filename
# 6. Prints a clear summary so you can see exactly what changed

print("🔍 Searching for all CSV files containing '_balances' in the filename...\n")

# Find files (works with both glob and pathlib for maximum compatibility)
balance_files = glob.glob("*_balances*.csv") + [str(p) for p in Path(".").glob("*_balances*.csv")]
balance_files = list(dict.fromkeys(balance_files))  # remove possible duplicates

if not balance_files:
    print("❌ No files matching '*_balances*.csv' were found in the current directory.")
    print("   Make sure the CSVs are in the same folder as this script.")
else:
    print(f"✅ Found {len(balance_files)} balance file(s):")
    for f in balance_files:
        print(f"   • {f}")
    print("\n" + "="*80 + "\n")

for file_path in balance_files:
    print(f"📂 Processing: {file_path}")
    
    # Load the data
    df = pd.read_csv(file_path)
    original_row_count = len(df)
    
    # ------------------------------------------------------------------
    # Step 1: Automatically detect ALL balance-change columns
    #    We look for any column that ends with "_balance_change" or contains
    #    "_balance_change" anywhere (covers both of your example files)
    # ------------------------------------------------------------------
    change_cols = [col for col in df.columns if "_balance_change" in col.lower()]
    
    if not change_cols:
        print("   ⚠️  No balance-change columns detected. Skipping this file.")
        continue
    
    print(f"   🔑 Detected balance-change columns: {change_cols}")
    
    # ------------------------------------------------------------------
    # Step 2: Build a mask that is True ONLY when AT LEAST ONE change is non-zero
    #    We use a tiny tolerance (1e-8) because floating-point numbers
    #    can be something like -1.23e-16 instead of exactly 0.0
    # ------------------------------------------------------------------
    # Start with all-False mask
    non_zero_mask = pd.Series(False, index=df.index)
    
    for col in change_cols:
        # Absolute value comparison handles negative changes too
        non_zero_mask = non_zero_mask | (np.abs(df[col]) > 1e-8)
    
    # Apply the filter
    filtered_df = df[non_zero_mask].copy()
    filtered_row_count = len(filtered_df)
    
    # ------------------------------------------------------------------
    # Step 3: Report results and save the cleaned file
    # ------------------------------------------------------------------
    rows_removed = original_row_count - filtered_row_count
    print(f"   📊 Original rows : {original_row_count:>5}")
    print(f"   📊 Filtered rows : {filtered_row_count:>5}  (kept only actual balance changes)")
    print(f"   📊 Rows removed  : {rows_removed:>5}  (pure price-update rows)")
    
    # Create output filename (e.g. btcb_pepe_balances_filtered.csv)
    base_name = Path(file_path).stem
    output_path = Path(file_path).with_name(f"{base_name}_filtered.csv")
    
    filtered_df.to_csv(output_path, index=False)
    print(f"   💾 Saved filtered data → {output_path}\n")
    
    # Optional: show the actual timestamps of the kept events (very useful for quick inspection)
    if "readable_time_kst" in filtered_df.columns:
        print("   📅 Actual balance-change timestamps:")
        for ts in filtered_df["readable_time_kst"].tolist():
            print(f"       • {ts}")
        print()

print("="*80)
print("🎉 All done! Filtered versions have been created for every matching CSV.")
print("   You can now analyze only the moments when your portfolio actually moved.")
