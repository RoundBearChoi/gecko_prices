import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from matplotlib.ticker import FuncFormatter
from pandas.tseries.offsets import DateOffset

# ==================== CONFIG SECTION ====================
TOKEN_ID = "fartcoin"      # Change this: "fartcoin", "popcat", "solana", "neet", "troll-2", "useless-3", etc.
MONTHS = 3                 # Last N months to display
DPI = 150                  # Chart resolution (higher = sharper saved image)
DATA_DIR = "volume_data"   # Folder containing the *_daily_volume.csv files
SAVE_CHART = True          # Set False if you only want console output
# =======================================================

# Build full path (works whether volume_data is in current dir or script dir)
script_dir = os.path.dirname(os.path.abspath(__file__))
csv_file = os.path.join(script_dir, DATA_DIR, f"{TOKEN_ID}_daily_volume.csv")

# Fallback: try current directory if volume_data folder is missing
if not os.path.exists(csv_file):
    print(f"⚠️  volume_data/{TOKEN_ID}_daily_volume.csv not found. Trying current directory...")
    csv_file = os.path.join(".", f"{TOKEN_ID}_daily_volume.csv")

print(f"📂 Loading volume data for {TOKEN_ID} from: {csv_file}\n")

# ====================== DATA LOADING & CLEANING ======================
df = pd.read_csv(csv_file)

# Parse dates (your CSVs use YYYY-MM-DD format)
df['date'] = pd.to_datetime(df['date']).dt.date

# Handle duplicate dates (ALL your CSVs have two entries for 2026-04-25)
# We sum the volumes – safest approach if the second row is a partial-day update
df = df.groupby('date', as_index=False)['volume_usd'].sum()
df = df.sort_values('date')
df['date'] = pd.to_datetime(df['date'])  # back to datetime for plotting/filtering

print(f"✅ Loaded {len(df)} daily records ({df['date'].min().date()} → {df['date'].max().date()})")

# ====================== FILTER LAST N MONTHS ======================
end_date = df['date'].max()
start_date = end_date - DateOffset(months=MONTHS)
df_recent = df[df['date'] >= start_date].copy().reset_index(drop=True)

# ====================== KST TIME AWARENESS ======================
kst_tz = ZoneInfo("Asia/Seoul")
now_kst = datetime.now(kst_tz).strftime("%Y-%m-%d %H:%M:%S KST")

# ====================== CONSOLE SUMMARY ======================
print(f"\n🕒 Current time (KST): {now_kst}")
print(f"\n=== 📊 {TOKEN_ID.upper()} DAILY VOLUME ANALYSIS (LAST {MONTHS} MONTHS) ===")
print(f"📅 Date range shown: {df_recent['date'].min().date()} → {df_recent['date'].max().date()}")
print(f"📈 Records: {len(df_recent)}")
print(f"💰 Total volume: ${df_recent['volume_usd'].sum():,.0f} USD")
print(f"📊 Average daily volume: ${df_recent['volume_usd'].mean():,.0f} USD")
print(f"🚀 Peak daily volume: ${df_recent['volume_usd'].max():,.0f} on {df_recent.loc[df_recent['volume_usd'].idxmax(), 'date'].date()}")
print(f"📉 Lowest daily volume: ${df_recent['volume_usd'].min():,.0f} on {df_recent.loc[df_recent['volume_usd'].idxmin(), 'date'].date()}")

print(f"\n📋 Recent 7 days (KST):")
print(df_recent.tail(7)[['date', 'volume_usd']].to_string(index=False))

# ====================== CHART ======================
if not SAVE_CHART:
    print("\n✅ Console summary complete (chart saving disabled).")
else:
    sns.set_style("whitegrid")
    fig, ax = plt.subplots(figsize=(14, 7), dpi=DPI)

    # Bar chart for daily volume
    ax.bar(df_recent['date'], df_recent['volume_usd'], 
           color='#3498db', width=0.85, alpha=0.85, label='Daily Volume (USD)')

    # 7-day rolling average line (very useful for spotting real trends vs noise)
    df_plot = df_recent.set_index('date')
    rolling_avg = df_plot['volume_usd'].rolling(window=7, min_periods=3).mean()
    ax.plot(rolling_avg.index, rolling_avg, 
            color='#e74c3c', linewidth=3.5, label='7-day Rolling Average')

    # Title & labels (explicitly KST)
    ax.set_title(f'{TOKEN_ID.replace("-", " ").title()} Daily Trading Volume (USD)\nLast {MONTHS} Months – KST', 
                 fontsize=18, pad=20)
    ax.set_xlabel('Date (KST)', fontsize=13)
    ax.set_ylabel('Volume (USD)', fontsize=13)

    # Smart Y-axis formatter (Millions / Billions)
    def volume_formatter(x, pos):
        if x >= 1e9:
            return f'${x/1e9:.1f}B'
        return f'${x/1e6:.1f}M'
    ax.yaxis.set_major_formatter(FuncFormatter(volume_formatter))

    plt.xticks(rotation=45, ha='right')
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save chart
    chart_filename = f"{TOKEN_ID}_daily_volume_{MONTHS}m_chart.png"
    plt.savefig(chart_filename, dpi=DPI, bbox_inches='tight')
    print(f"\n✅ Beautiful chart saved as: {chart_filename}")
    print("   Open the PNG file to view the visualization!")

    # plt.show()  # Uncomment this line if you want an interactive window
