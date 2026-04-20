import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import timedelta
import os

# ==================== CONFIG SECTION ====================
# Change these settings as needed
TIME_WINDOW = '14d'           # Options: 'all', '7d', '30d', '90d', '180d', '360d'
SAVE_DIR = '.'               # Folder to save PNGs (use '.' for current folder)
DPI = 180
SHOW_PLOTS = False           # Set True only if you want to see them interactively too
# =======================================================

# Load and clean data
df = pd.read_csv('aerodrome_msusd_usdc_hourly_data.csv')
df = df.drop_duplicates(subset=['timestamp'])
df['datetime_utc'] = pd.to_datetime(df['datetime_utc'])
df = df.sort_values('datetime_utc').reset_index(drop=True)

# Apply time filter
if TIME_WINDOW != 'all':
    days = int(TIME_WINDOW.replace('d', ''))
    end_date = df['datetime_utc'].max()
    start_date = end_date - timedelta(days=days)
    df_plot = df[df['datetime_utc'] >= start_date].copy()
    print(f"Using last {days} days of data ({len(df_plot)} rows)")
else:
    df_plot = df.copy()
    print(f"Using all data ({len(df_plot)} rows)")

print(f"Plotting from {df_plot['datetime_utc'].min()} to {df_plot['datetime_utc'].max()}")

# Styling
sns.set_style("whitegrid")
plt.rcParams.update({'figure.figsize': (16, 10), 'font.size': 12})

# Calculate moving averages on the filtered data
df_plot['MA_7'] = df_plot['close'].rolling(7).mean()
df_plot['MA_24'] = df_plot['close'].rolling(24).mean()
df_plot['MA_168'] = df_plot['close'].rolling(168).mean()

os.makedirs(SAVE_DIR, exist_ok=True)
suffix = f"_{TIME_WINDOW}" if TIME_WINDOW != 'all' else "_full"

# Chart 1: Price + MAs + Volume
fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
ax1.plot(df_plot['datetime_utc'], df_plot['close'], label='Close', color='#1f77b4', linewidth=2)
ax1.plot(df_plot['datetime_utc'], df_plot['MA_7'], label='7h MA', color='#ff7f0e')
ax1.plot(df_plot['datetime_utc'], df_plot['MA_24'], label='24h MA', color='#d62728')
ax1.plot(df_plot['datetime_utc'], df_plot['MA_168'], label='168h MA (~1wk)', color='#2ca02c')
ax1.set_title(f'MSUSD/USDC Hourly Price History {TIME_WINDOW.upper()}')
ax1.set_ylabel('Price (USDC)')
ax1.legend()
ax2.bar(df_plot['datetime_utc'], df_plot['volume'], color='#2ca02c', alpha=0.7)
ax2.set_ylabel('Volume')
ax2.set_xlabel('Date (UTC)')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f'{SAVE_DIR}/msusd_usdc_price_volume{suffix}.png', dpi=DPI, bbox_inches='tight')
if SHOW_PLOTS:
    plt.show()
plt.close()

# Chart 2: Price Ranges
fig2, ax3 = plt.subplots(figsize=(16, 8))
ax3.plot(df_plot['datetime_utc'], df_plot['high'], color='green', alpha=0.4, label='High')
ax3.plot(df_plot['datetime_utc'], df_plot['low'], color='red', alpha=0.4, label='Low')
ax3.plot(df_plot['datetime_utc'], df_plot['close'], color='#1f77b4', linewidth=1.8, label='Close')
ax3.set_title(f'MSUSD/USDC Price Ranges {TIME_WINDOW.upper()}')
ax3.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f'{SAVE_DIR}/msusd_usdc_price_ranges{suffix}.png', dpi=DPI, bbox_inches='tight')
if SHOW_PLOTS:
    plt.show()
plt.close()

# Chart 3: Peg Deviation
df_plot['deviation'] = df_plot['close'] - 1.0
fig3, ax4 = plt.subplots(figsize=(16, 8))
ax4.plot(df_plot['datetime_utc'], df_plot['deviation'], color='#9467bd', linewidth=2)
ax4.fill_between(df_plot['datetime_utc'], df_plot['deviation'], 0, 
                 where=(df_plot['deviation'] > 0), color='green', alpha=0.25)
ax4.fill_between(df_plot['datetime_utc'], df_plot['deviation'], 0, 
                 where=(df_plot['deviation'] < 0), color='red', alpha=0.25)
ax4.axhline(0, color='black', linestyle='--', linewidth=1)
ax4.set_title(f'MSUSD/USDC Deviation from $1 Peg {TIME_WINDOW.upper()}')
ax4.set_ylabel('Deviation')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(f'{SAVE_DIR}/msusd_usdc_peg_deviation{suffix}.png', dpi=DPI, bbox_inches='tight')
if SHOW_PLOTS:
    plt.show()
plt.close()

print("✅ All charts successfully saved as PNG files!")
