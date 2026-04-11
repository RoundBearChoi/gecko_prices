import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import warnings
from datetime import datetime
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
config = {
    # Input / Output files - now dynamic with months
    'input_csv': "pair_reversion_bootstrapped_results_8months.csv",
    'months': 8,
    
    'output_csv_template': "ranked_reversion_pairs_{months}months.csv",
    'combined_chart_template': "reliable_pairs_analysis_charts_{months}months.png",
    
    # === STABILITY FILTER (Step 1) ===
    'max_boot_cv': 0.20,          # Lower = more stable
    'max_ci_width': 15.0,          # Tighter = more reliable
    'min_total_trips': 8,
    
    # === CHART SETTINGS ===
    'dpi': 180,                    # Higher = sharper images
    'figsize': (16, 7),            # Wider figure for two side-by-side charts
    'output_top_n': 5,
}

# ========================= DYNAMIC FILENAMES =========================
def get_output_filenames(config):
    months = config['months']
    output_csv = config['output_csv_template'].format(months=months)
    combined_chart = config['combined_chart_template'].format(months=months)
    return output_csv, combined_chart

config['output_csv'], config['combined_chart_file'] = get_output_filenames(config)

print(f"📅 Analysis period: {config['months']} months")
print(f"Output CSV  → {config['output_csv']}")
print(f"Output Chart → {config['combined_chart_file']}\n")

# ========================= LOAD DATA =========================
df = pd.read_csv(config['input_csv'])

# Data type fixes
df['boot_mean_trips'] = df['boot_mean_trips'].astype(float)
df['total_full_trips'] = df['total_full_trips'].astype(int)
df['boot_cv'] = df['boot_cv'].astype(float)
df['balance_ratio'] = df['balance_ratio'].astype(float)
df['avg_1sd_ratio_pct'] = df['avg_1sd_ratio_pct'].astype(float)

# ========================= PARSE CI WIDTH =========================
def parse_ci_width(ci_str: str) -> float:
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

print(f"Loaded {len(df):,} pairs")
print(f"Reliability thresholds → CV ≤ {config['max_boot_cv']}, CI width ≤ {config['max_ci_width']}\n")

# ========================= IDENTIFY RELIABLE / UNRELIABLE =========================
reliable_mask = (
    (df['boot_cv'] <= config['max_boot_cv']) &
    (df['ci_width'] <= config['max_ci_width']) &
    (df['total_full_trips'] >= config['min_total_trips'])
)

df['reliability'] = np.where(reliable_mask, 'reliable', 'unreliable')

reliable_df = df[reliable_mask].copy()
unreliable_df = df[~reliable_mask].copy()

print(f"✅ Reliable pairs: {len(reliable_df):,}")
print(f"   Unreliable pairs: {len(unreliable_df):,}\n")

# ========================= RANKING =========================
# Reliable: smallest |diff| first, then highest trips
reliable_df = reliable_df.sort_values(
    by=['abs_diff', 'total_full_trips'],
    ascending=[True, False]
).copy()

# Unreliable: highest trips first
unreliable_df = unreliable_df.sort_values(
    by=['total_full_trips', 'abs_diff'],
    ascending=[False, True]
).copy()

ranked_df = pd.concat([reliable_df, unreliable_df], ignore_index=True)
ranked_df.insert(0, 'rank', range(1, len(ranked_df) + 1))

# ========================= CONSOLE OUTPUT =========================
display_cols = [
    'rank', 'pair', 'reliability', 'total_full_trips', 'boot_mean_trips', 
    'diff', 'abs_diff', 'abs_rel_diff', 'boot_cv', 'ci_width',
    'balance_ratio', 'avg_1sd_ratio_pct'
]

print(f"=== TOP {config['output_top_n']} RANKED PAIRS ===\n")
print(ranked_df[display_cols].head(config['output_top_n']).round(3).to_string(index=False))

# ========================= COMBINED CHART =========================
if len(reliable_df) > 0:
    print(f"\nGenerating combined chart for reliable pairs ({config['months']} months)...")
    
    fig, axs = plt.subplots(1, 2, figsize=config['figsize'], dpi=config['dpi'])
    
    # Chart 1: Ranked by Total Full Trips (descending)
    sorted_trips = reliable_df.sort_values('total_full_trips', ascending=False).reset_index(drop=True)
    
    axs[0].bar(range(len(sorted_trips)), sorted_trips['total_full_trips'], 
               color='skyblue', alpha=0.85, edgecolor='navy', linewidth=0.4)
    axs[0].set_title(f'Reliable Pairs Ranked by Total Full Trips\n({config["months"]} months)', 
                     fontsize=14, pad=12)
    axs[0].set_xlabel('Rank (Highest → Lowest Trips)', fontsize=11)
    axs[0].set_ylabel('Total Full Trips', fontsize=11)
    
    med_trips = sorted_trips['total_full_trips'].median()
    p10_trips = sorted_trips['total_full_trips'].quantile(0.10)
    p90_trips = sorted_trips['total_full_trips'].quantile(0.90)
    
    axs[0].axhline(med_trips, color='red', linestyle='--', linewidth=2, label=f'Median: {med_trips:.1f}')
    axs[0].axhline(p10_trips, color='green', linestyle=':', linewidth=1.5, label=f'10th: {p10_trips:.1f}')
    axs[0].axhline(p90_trips, color='green', linestyle=':', linewidth=1.5, label=f'90th: {p90_trips:.1f}')
    
    axs[0].legend(fontsize=10)
    axs[0].grid(axis='y', alpha=0.3)
    
    # Chart 2: Ranked by |diff| (ascending)
    sorted_diff = reliable_df.sort_values('abs_diff', ascending=True).reset_index(drop=True)
    
    axs[1].bar(range(len(sorted_diff)), sorted_diff['abs_diff'], 
               color='lightcoral', alpha=0.85, edgecolor='darkred', linewidth=0.4)
    axs[1].set_title(f'Reliable Pairs Ranked by |diff| (Closest to Bootstrap Mean)\n({config["months"]} months)', 
                     fontsize=14, pad=12)
    axs[1].set_xlabel('Rank (Smallest → Largest |diff|)', fontsize=11)
    axs[1].set_ylabel('|diff| (Observed - Bootstrap Mean)', fontsize=11)
    
    med_diff = sorted_diff['abs_diff'].median()
    p10_diff = sorted_diff['abs_diff'].quantile(0.10)
    p90_diff = sorted_diff['abs_diff'].quantile(0.90)
    
    axs[1].axhline(med_diff, color='red', linestyle='--', linewidth=2, label=f'Median: {med_diff:.2f}')
    axs[1].axhline(p10_diff, color='green', linestyle=':', linewidth=1.5, label=f'10th: {p10_diff:.2f}')
    axs[1].axhline(p90_diff, color='green', linestyle=':', linewidth=1.5, label=f'90th: {p90_diff:.2f}')
    
    axs[1].legend(fontsize=10)
    axs[1].grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    
    # Save single combined chart
    fig.savefig(config['combined_chart_file'], dpi=config['dpi'], bbox_inches='tight')
    print(f"✅ Combined chart saved → {config['combined_chart_file']}")
    print(f"   (DPI: {config['dpi']}, size: {config['figsize'][0]}x{config['figsize'][1]} inches)")
else:
    print("No reliable pairs found for charting.")

# ========================= SAVE RANKED DATA =========================
ranked_df.to_csv(config['output_csv'], index=False)
print(f"\n✅ Full ranked results saved to → {config['output_csv']}")
print("   • 'reliability' column added (reliable / unreliable)")
print("Done! 🎉")
