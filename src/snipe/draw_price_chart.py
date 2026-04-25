import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import timedelta
import os
import argparse

# ==================== CONFIG SECTION ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Command-line argument for maximum flexibility
parser = argparse.ArgumentParser(
    description="Generate price chart with Short & Long MAs for any coin's CSV file."
)
parser.add_argument(
    'coin',
    nargs='?',                          # ← makes it optional
    default='fartcoin',
    help='Coin identifier (e.g. "neet", "fartcoin"). Looks for price_data/{coin}.csv (default: fartcoin)'
)
parser.add_argument(
    '--csv',
    type=str,
    help='Path to the price CSV file (overrides the coin argument)'
)
args = parser.parse_args()

# Determine CSV_PATH - this is the only changed logic
if args.csv:
    CSV_PATH = args.csv
else:
    CSV_PATH = os.path.join(SCRIPT_DIR, 'price_data', f'{args.coin}.csv')

# === Coin ID from filename (CoinGecko API ID - exactly as stored) ===
coin_id = os.path.splitext(os.path.basename(CSV_PATH))[0]

SHORT_MA_WINDOW = 24      # Short-term MA (hours)
LONG_MA_WINDOW = 24*7     # Long-term MA (hours)
RECENT_DAYS_FOR_SUMMARY = 30

# NEW: Configurable short MA momentum windows (easily extensible)
SHORT_MA_MOMENTUM_WINDOWS = [6, 12, 24]   # ← Add or remove hours here as needed

DPI = 150                 # ← Image resolution (150 = fast & light, 300 = high quality)
OUTPUT_FILE = f'{coin_id}_price_ma_kst.png'
TITLE = f'{coin_id} Price (USD) with Short & Long Moving Averages (KST)'
FIG_SIZE = (15, 8)
# =======================================================

# Load data
print(f"📂 Loading data from: {CSV_PATH} (id: {coin_id})")
df = pd.read_csv(CSV_PATH)

# Parse datetime and convert to KST
df['datetime_utc'] = pd.to_datetime(df['datetime'], format='ISO8601')
df['datetime_kst'] = df['datetime_utc'].dt.tz_convert('Asia/Seoul')

# Sort
df = df.sort_values('datetime_kst').reset_index(drop=True)

# Calculate moving averages
df['short_ma'] = df['price_usd'].rolling(window=SHORT_MA_WINDOW, min_periods=1).mean()
df['long_ma'] = df['price_usd'].rolling(window=LONG_MA_WINDOW, min_periods=1).mean()

# === Recent trend summary - IMPROVED (quantitative & neutral) ===
recent_df = df[df['datetime_kst'] >= df['datetime_kst'].max() - timedelta(days=RECENT_DAYS_FOR_SUMMARY)]
latest_price = recent_df['price_usd'].iloc[-1]
latest_short_ma = recent_df['short_ma'].iloc[-1]
latest_long_ma = recent_df['long_ma'].iloc[-1]
latest_time_kst = recent_df['datetime_kst'].iloc[-1]

print(f"\n📅 Latest data point (KST): {latest_time_kst.strftime('%Y-%m-%d %H:%M')}")
print(f"💰 Latest {coin_id} Price: ${latest_price:.6f}")

print(f"\n📈 Moving Averages:")
print(f"  Short MA ({SHORT_MA_WINDOW}h): ${latest_short_ma:.6f}  [{(latest_price / latest_short_ma - 1)*100:+.2f}%]")
print(f"  Long MA ({LONG_MA_WINDOW}h):  ${latest_long_ma:.6f}  [{(latest_price / latest_long_ma - 1)*100:+.2f}%]")

# Helper for % change
def pct_change(series, periods):
    if len(series) > periods:
        return (series.iloc[-1] / series.iloc[-periods] - 1) * 100
    return float('nan')

price_s = recent_df['price_usd']

print("\n📊 Recent Performance:")
print(f"  24h change: {pct_change(price_s, 24):+6.2f}%")
print(f"   3d change: {pct_change(price_s, 72):+6.2f}%")
print(f"   7d change: {pct_change(price_s, 168):+6.2f}%")
print(f"  30d change: {pct_change(price_s, 720):+6.2f}%")

# Range info
recent_high = recent_df['price_usd'].max()
recent_low = recent_df['price_usd'].min()
print(f"\n📍 30d Range: ${recent_low:.4f} – ${recent_high:.4f}")
if latest_price > 0:
    print(f"   Current from 30d high: {(latest_price / recent_high - 1)*100 :+.1f}%")

# === Short MA momentum (multiple short-term windows) ===
print("\n🔄 Short MA Momentum:")
for hours in SHORT_MA_MOMENTUM_WINDOWS:
    if len(recent_df) > hours:
        mom = (latest_short_ma / recent_df['short_ma'].iloc[-hours] - 1) * 100
        print(f"  {hours:2d}h : {mom:+.2f}%")
    else:
        print(f"  {hours:2d}h : N/A (insufficient data)")

# === Plot the chart ===
sns.set_style("darkgrid")
plt.figure(figsize=FIG_SIZE)

plt.plot(df['datetime_kst'], df['price_usd'], 
         label='Price (USD)', color='#1f77b4', linewidth=1.8, alpha=0.95)
plt.plot(df['datetime_kst'], df['short_ma'], 
         label=f'Short MA ({SHORT_MA_WINDOW} hrs)', color='#ff7f0e', linewidth=2)
plt.plot(df['datetime_kst'], df['long_ma'], 
         label=f'Long MA ({LONG_MA_WINDOW} hrs)', color='#2ca02c', linewidth=2)

plt.title(TITLE, fontsize=16, pad=20)
plt.xlabel('Date / Time (Korea Standard Time)', fontsize=12)
plt.ylabel('Price in USD', fontsize=12)
plt.legend(fontsize=11, loc='upper left')
plt.xticks(rotation=45, ha='right')
plt.grid(True, alpha=0.3)
plt.tight_layout()

# Save chart with configurable DPI
plt.savefig(OUTPUT_FILE, dpi=DPI, bbox_inches='tight')
print(f"\n✅ Chart saved as '{OUTPUT_FILE}' (DPI = {DPI})")

plt.close()
