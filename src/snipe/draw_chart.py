import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import timedelta
import os

# ==================== CONFIG SECTION ====================
# Path to CSV (automatically looks for price_data/ next to this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(SCRIPT_DIR, 'price_data', 'FARTCOIN.csv')

SHORT_MA_WINDOW = 24      # Short-term MA (≈ 1 day)
LONG_MA_WINDOW = 168      # Long-term MA (≈ 7 days)
RECENT_DAYS_FOR_SUMMARY = 30

DPI = 150                 # ← Image resolution (150 = fast & light, 300 = high quality)
OUTPUT_FILE = 'fartcoin_price_ma_kst.png'
TITLE = 'FARTCOIN Price (USD) with Short & Long Moving Averages (KST)'
FIG_SIZE = (15, 8)
# =======================================================

# Load data
print(f"📂 Loading data from: {CSV_PATH}")
df = pd.read_csv(CSV_PATH)

# Parse datetime and convert to KST
df['datetime_utc'] = pd.to_datetime(df['datetime'], format='ISO8601')
df['datetime_kst'] = df['datetime_utc'].dt.tz_convert('Asia/Seoul')

# Sort
df = df.sort_values('datetime_kst').reset_index(drop=True)

# Calculate moving averages
df['short_ma'] = df['price_usd'].rolling(window=SHORT_MA_WINDOW, min_periods=1).mean()
df['long_ma'] = df['price_usd'].rolling(window=LONG_MA_WINDOW, min_periods=1).mean()

# === Recent trend summary ===
recent_df = df[df['datetime_kst'] >= df['datetime_kst'].max() - timedelta(days=RECENT_DAYS_FOR_SUMMARY)]
latest_price = recent_df['price_usd'].iloc[-1]
latest_short_ma = recent_df['short_ma'].iloc[-1]
latest_long_ma = recent_df['long_ma'].iloc[-1]
latest_time_kst = recent_df['datetime_kst'].iloc[-1]

print(f"\n📅 Latest data point (KST): {latest_time_kst.strftime('%Y-%m-%d %H:%M')}")
print(f"💰 Latest Price: ${latest_price:.6f}")
print(f"📈 Short MA ({SHORT_MA_WINDOW} periods): ${latest_short_ma:.6f}")
print(f"📉 Long MA ({LONG_MA_WINDOW} periods): ${latest_long_ma:.6f}")

if latest_price > latest_short_ma > latest_long_ma:
    print("🟢 **STRONG UPTREND** – price above both MAs")
elif latest_price > latest_short_ma:
    print("🟡 Short-term bullish (price above short MA)")
elif latest_price < latest_short_ma < latest_long_ma:
    print("🔴 **STRONG DOWNTREND** – price below both MAs")
else:
    print("⚪ Mixed / sideways recently")

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
