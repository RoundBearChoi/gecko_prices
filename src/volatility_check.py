# === FULL UPDATED volatility_check.py (copy-paste this entire file) ===
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import sys
from pandas.tseries.offsets import DateOffset

# ==================== CONFIG SECTION ====================
# Default values (used when you run the script with no arguments)
TOKEN1 = 'eth'      # numerator  (top of the ratio)
TOKEN0 = 'btc'      # denominator (bottom of the ratio)
N_MONTHS = 24       # how many months back from the latest data point
# =======================================================

# === CLI override (e.g. python volatility_check.py eth btc 24) ===
if len(sys.argv) > 1:
    TOKEN1 = sys.argv[1].lower().strip()
if len(sys.argv) > 2:
    TOKEN0 = sys.argv[2].lower().strip()
if len(sys.argv) > 3:
    try:
        N_MONTHS = int(sys.argv[3])
    except ValueError:
        print(f"⚠️  Invalid N_MONTHS argument, falling back to config default ({N_MONTHS})")

print(f"🔍 Analyzing {TOKEN1.upper()}/{TOKEN0.upper()} ratio volatility "
      f"(last ~{N_MONTHS} months, KST)")

# === Load data ===
token1_df = pd.read_csv(f'fetched_data/{TOKEN1}_price_history.csv')
token0_df = pd.read_csv(f'fetched_data/{TOKEN0}_price_history.csv')

# Parse datetimes
for df in [token1_df, token0_df]:
    df['datetime'] = pd.to_datetime(df['datetime'], format='mixed', utc=True)

# === Filter to most recent N_MONTHS (from global latest date) ===
if not token1_df.empty and not token0_df.empty:
    latest_date = max(token1_df['datetime'].max(), token0_df['datetime'].max())
    cutoff_date = latest_date - DateOffset(months=N_MONTHS)
    
    token1_df = token1_df[token1_df['datetime'] >= cutoff_date].copy()
    token0_df = token0_df[token0_df['datetime'] >= cutoff_date].copy()
    
    print(f"📅 Data period used: {cutoff_date.date()} → {latest_date.date()} "
          f"({len(token1_df)} rows for {TOKEN1}, {len(token0_df)} rows for {TOKEN0})")

# Set index and rename price column
token1 = token1_df.set_index('datetime').rename(columns={'price_usd': TOKEN1}).sort_index()
token0 = token0_df.set_index('datetime').rename(columns={'price_usd': TOKEN0}).sort_index()

# === Align prices (same 30-min tolerance as before) ===
combined = pd.merge_asof(
    token1, token0,
    left_index=True,
    right_index=True,
    direction='nearest',
    tolerance=pd.Timedelta('30min')
)
combined = combined.dropna()

# === Convert to KST + compute ratio volatility ===
combined.index = combined.index.tz_convert('Asia/Seoul')
combined['ratio'] = combined[TOKEN1] / combined[TOKEN0]
combined['log_ret'] = np.log(combined['ratio']).diff()
combined['hour'] = combined.index.hour

# === RESULTS ===
vol = combined.groupby('hour')['log_ret'].std().sort_values()
print("\nVolatility (std of log returns) by KST hour (lowest → highest):\n", vol.round(6))

stats = combined.groupby('hour')['log_ret'].agg(
    mean='mean', std='std', count='count', min='min', max='max'
).sort_values('std')
print("\nFull stats table (sorted by lowest volatility):\n", stats.round(6))

# === CHART: exported to PNG only (no interactive window) ===
plt.figure(figsize=(14, 8))

bars = plt.bar(vol.index, vol.values, color='skyblue', edgecolor='navy', alpha=0.85, linewidth=1.2)

# Highlight the 3 calmest hours in gold
calmest_hours = vol.head(3).index.tolist()
for hour in calmest_hours:
    idx = list(vol.index).index(hour)
    bars[idx].set_color('gold')
    bars[idx].set_edgecolor('darkorange')
    bars[idx].set_linewidth(2.5)

plt.title(f'{TOKEN1.upper()}/{TOKEN0.upper()} Price Ratio Volatility by Hour (KST)\n'
          f'Last ~{N_MONTHS} months — Lower bar = calmer hour for the ratio',
          fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Hour of Day in KST (0 = midnight, 23 = 11 PM)', fontsize=13)
plt.ylabel('Volatility (Standard Deviation of Log Returns)', fontsize=13)
plt.xticks(range(0, 24), fontsize=11)
plt.yticks(fontsize=11)
plt.grid(axis='y', linestyle='--', alpha=0.4)

# Add exact volatility values on top of every bar
for bar in bars:
    height = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2., height + 0.00005,
             f'{height:.5f}', ha='center', va='bottom', fontsize=9, rotation=90)

# Optional calm window annotation (still useful for any pair)
plt.axvspan(13.5, 20.5, alpha=0.1, color='green', label='Afternoon–Evening calm window (2–8 PM KST)')
plt.legend(loc='upper right')

plt.tight_layout()
filename = f'{TOKEN1.lower()}_{TOKEN0.lower()}_kst_volatility.png'
plt.savefig(filename, dpi=160, bbox_inches='tight')

print(f"\n✅ Chart exported as '{filename}' (DPI 160) in your current folder!")
