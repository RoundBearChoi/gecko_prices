import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
config = {
    # Input / Output files
    'input_csv': "pair_reversion_bootstrapped_results_24months.csv",
    'output_csv': "ranked_reversion_pairs.csv",
    
    # === STABILITY FILTER (Step 1) ===
    'max_boot_cv': 0.130,          # Lower = more stable (recommended: 0.12 ~ 0.135)
    'max_ci_width': 15.0,          # Tighter CI = more reliable estimate
    'min_total_trips': 10,         # Minimum trips to be considered at all
    
    # === OUTPUT SETTINGS ===
    'output_top_n': 30,            # How many pairs to display in console
    'show_all_columns': False,     # Set to True to see every column in console
}

# ========================= LOAD DATA =========================
df = pd.read_csv(config['input_csv'])

# Ensure correct data types
df['boot_mean_trips'] = df['boot_mean_trips'].astype(float)
df['total_full_trips'] = df['total_full_trips'].astype(int)
df['boot_cv'] = df['boot_cv'].astype(float)
df['balance_ratio'] = df['balance_ratio'].astype(float)
df['avg_1sd_ratio_pct'] = df['avg_1sd_ratio_pct'].astype(float)

# ========================= PARSE CI WIDTH =========================
def parse_ci_width(ci_str: str) -> float:
    """Convert '[26.0, 44.0]' → 18.0"""
    cleaned = ci_str.strip("[] ").replace(" ", "")
    try:
        low, high = map(float, cleaned.split(","))
        return high - low
    except:
        return np.nan

df['ci_width'] = df['boot_95ci'].apply(parse_ci_width)

# ========================= COMPUTE DIFF METRICS =========================
df['diff'] = df['total_full_trips'] - df['boot_mean_trips']
df['abs_diff'] = df['diff'].abs()
df['rel_diff'] = df['diff'] / df['boot_mean_trips'].replace(0, np.nan)
df['abs_rel_diff'] = df['rel_diff'].abs()

print(f"Loaded {len(df):,} pairs from {config['input_csv']}")
print(f"CI width range: {df['ci_width'].min():.1f} – {df['ci_width'].max():.1f}")
print(f"boot_cv range: {df['boot_cv'].min():.3f} – {df['boot_cv'].max():.3f}\n")

# ========================= IDENTIFY RELIABLE vs UNRELIABLE (Step 1) =========================
reliable_mask = (
    (df['boot_cv'] <= config['max_boot_cv']) &
    (df['ci_width'] <= config['max_ci_width']) &
    (df['total_full_trips'] >= config['min_total_trips'])
)

df['reliability'] = np.where(reliable_mask, 'reliable', 'unreliable')

reliable_df = df[reliable_mask].copy()
unreliable_df = df[~reliable_mask].copy()

print(f"✅ Reliable pairs (low CV + tight CI): {len(reliable_df):,}")
print(f"   Unreliable pairs: {len(unreliable_df):,}\n")

# ========================= RANKING (Step 2) =========================
# 1. Reliable pairs: sorted by smallest |diff| (closest to bootstrap expectation), then highest trips
reliable_df = reliable_df.sort_values(
    by=['abs_diff', 'total_full_trips'],
    ascending=[True, False]
).copy()

# 2. Unreliable pairs: go to the bottom, sorted by highest total trips first, then smallest |diff|
unreliable_df = unreliable_df.sort_values(
    by=['total_full_trips', 'abs_diff'],
    ascending=[False, True]
).copy()

# Combine: reliable first, then unreliable
ranked_df = pd.concat([reliable_df, unreliable_df], ignore_index=True)

# Add overall rank
ranked_df.insert(0, 'rank', range(1, len(ranked_df) + 1))

# ========================= OUTPUT =========================
# Main columns to display
display_cols = [
    'rank', 'pair', 'reliability', 'total_full_trips', 'boot_mean_trips', 
    'diff', 'abs_diff', 'abs_rel_diff', 'boot_cv', 'ci_width',
    'balance_ratio', 'avg_1sd_ratio_pct'
]

print(f"=== TOP {config['output_top_n']} RANKED PAIRS ===\n")
print(ranked_df[display_cols].head(config['output_top_n']).round(3).to_string(index=False))

# Optional: show full table if requested
if config['show_all_columns']:
    print("\n=== FULL TABLE (first 50 rows) ===")
    print(ranked_df.head(50).to_string(index=False))

# Save full ranked results with new 'reliability' column
ranked_df.to_csv(config['output_csv'], index=False)
print(f"\n✅ Full ranked results saved to → {config['output_csv']}")
print(f"   • Reliable pairs are marked 'reliable' and appear at the top")
print(f"   • Sorted by |diff| within reliable group")
print("Done! 🎉")
