import pandas as pd
from pathlib import Path

# ==================== CONFIG SECTION ====================
DATA_DIR = Path("fetched_data")
TOKENS_FILE = "subjective_top_tokens_symbol.txt"
N_MONTHS = 8
TIME_TOLERANCE_MINUTES = 60
REVERSE_TOKENS = True            # True = "work our way up from the bottom"
OUTPUT_FILE = f"all_pairs_matched_hourly_prices_{N_MONTHS}_months.csv"
# =======================================================

# Load tokens
with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
    tokens = [
        line.strip().upper()
        for line in f
        if line.strip() and not line.strip().startswith('#')
    ]
tokens = list(dict.fromkeys(tokens))  # remove duplicates while preserving order
if REVERSE_TOKENS:
    tokens = tokens[::-1]

print(f"Loaded {len(tokens)} unique tokens (reversed={REVERSE_TOKENS}): {tokens[:10]}...")

# Load price data
price_data = {}
for token in tokens:
    file_path = DATA_DIR / f"{token.lower()}_price_history.csv"
    if file_path.exists():
        try:
            df = pd.read_csv(file_path)
            
            # Robust ISO8601 parsing
            df['datetime'] = pd.to_datetime(
                df['datetime'], 
                format='ISO8601', 
                utc=True,
                errors='coerce'
            )
            df = df.dropna(subset=['datetime'])
            
            df = df.set_index('datetime').sort_index()['price_usd']
            
            # Filter to most recent N months
            if len(df) > 0:
                end_date = df.index.max()
                start_date = end_date - pd.DateOffset(months=N_MONTHS)
                df = df[df.index >= start_date]
                price_data[token] = df
                print(f"✓ Loaded {token}: {len(df):,} rows from {df.index.min().date()} to {df.index.max().date()}")
        except Exception as e:
            print(f"✗ Error loading {token}: {e}")
    else:
        print(f"⚠️  Missing file for {token}")

if not price_data:
    raise ValueError("No price data loaded at all!")

# Create common hourly grid (FIXED: use lowercase 'h' for pandas 3.x)
min_time = min(s.index.min() for s in price_data.values())
max_time = max(s.index.max() for s in price_data.values())
common_index = pd.date_range(
    start=min_time.floor('h'),      # ← fixed
    end=max_time.ceil('h'),         # ← fixed
    freq='h',                       # ← fixed
    tz='UTC'
)

print(f"\nCommon time range: {min_time.date()} → {max_time.date()} ({len(common_index):,} hourly slots)")

# Align every token to the common hourly grid
tolerance = pd.Timedelta(minutes=TIME_TOLERANCE_MINUTES)
aligned_prices = {}

for token, series in price_data.items():
    aligned = series.reindex(
        common_index,
        method='nearest',
        tolerance=tolerance
    )
    aligned_prices[token] = aligned
    non_nan = aligned.notna().sum()
    print(f"Aligned {token}: {non_nan:,} non-NaN hourly prices")

# Build final wide-format DataFrame
final_df = pd.DataFrame(aligned_prices, index=common_index)
final_df.index.name = 'datetime'

# Drop rows where almost no tokens have data
final_df = final_df.dropna(thresh=2)

print(f"\n✅ Final aligned dataset: {final_df.shape[0]:,} rows × {final_df.shape[1]:,} tokens")

# Save giant CSV
final_df.to_csv(OUTPUT_FILE)
print(f"\n🎉 Giant CSV saved as: {OUTPUT_FILE}")
print(f"   Size: {final_df.shape[0]:,} rows, {final_df.shape[1]:,} columns")
print("\nPreview (first 5 rows):")
print(final_df.head())
