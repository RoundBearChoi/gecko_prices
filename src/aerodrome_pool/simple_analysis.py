import pandas as pd
from datetime import datetime, timedelta

# ========================= CONFIG SECTION =========================
DAYS_BACK = 14
CONFIDENCE_LEVEL = 0.95
CSV_FILENAME = 'aerodrome_msusd_usdc_hourly_data.csv'
OUTPUT_TXT = 'simple_analysis_results.txt'   # <-- Change filename here if you want
# ================================================================

# Load and prepare data
df = pd.read_csv(CSV_FILENAME)
df['datetime'] = pd.to_datetime(df['datetime'])
df = df.sort_values('timestamp').reset_index(drop=True)

# Filter recent period
latest_date = df['datetime'].max()
cutoff = latest_date - timedelta(days=DAYS_BACK)
recent = df[df['datetime'] >= cutoff].copy()

# Core metrics
current_price = recent['close'].iloc[-1]
prices = recent['close']

# Most likely price change (median)
hourly_returns = prices.pct_change().dropna() * 100
median_hourly_pct = hourly_returns.median()

daily_prices = recent.set_index('datetime')['close'].resample('D').last()
daily_returns = daily_prices.pct_change().dropna() * 100
median_daily_pct = daily_returns.median()

# 95% empirical price range
lower_price = prices.quantile((1 - CONFIDENCE_LEVEL) / 2)
upper_price = prices.quantile(1 - (1 - CONFIDENCE_LEVEL) / 2)

lower_pct = (current_price - lower_price) / current_price * 100
upper_pct = (upper_price - current_price) / current_price * 100

# Max observed deviation (for safety buffer)
max_below_pct = (current_price - prices.min()) / current_price * 100
max_above_pct = (prices.max() - current_price) / current_price * 100

# Build nice output
analysis_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

output = f"""MSUSD-USDC Pool Range Analysis
================================
Analysis generated: {analysis_time}
Data period analyzed: {recent['datetime'].min().strftime('%Y-%m-%d %H:%M')} → {latest_date.strftime('%Y-%m-%d %H:%M')}
Hours included: {len(recent)}

Current Price (latest close): {current_price:.6f}

MOST LIKELY PRICE MOVES
-----------------------
Median hourly change : {median_hourly_pct:+.4f}%
Median daily change  : {median_daily_pct:+.4f}%

95% COVERAGE RANGE (empirical quantiles)
----------------------------------------
Lower bound: {lower_price:.6f}   ({lower_pct:.3f}% below current)
Upper bound: {upper_price:.6f}   ({upper_pct:.3f}% above current)

→ Recommended pool range: {lower_price:.6f} – {upper_price:.6f}

MAX OBSERVED DEVIATION
----------------------
Max below current: {max_below_pct:.3f}%
Max above current: {max_above_pct:.3f}%
Full observed range: {prices.min():.6f} – {prices.max():.6f}

Note: This range covered 95% of all hourly closes in the last {DAYS_BACK} days.
"""

print(output)

# Write to TXT file
with open(OUTPUT_TXT, 'w', encoding='utf-8') as f:
    f.write(output)

print(f"\n✅ Results successfully exported to: {OUTPUT_TXT}")
