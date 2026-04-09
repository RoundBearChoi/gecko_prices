import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# ==================== CONFIG SECTION ====================
CONFIG = {
    'sol_file': 'sol_price_history.csv',      # no "fetched_data/" needed
    'orca_file': 'orca_price_history.csv',    # no "fetched_data/" needed
    'output_file': 'orca_sol_price_chart.png',
    'ma_window': 24*7*4,
    'dpi': 150,
    'figsize': (16, 8),
    'title': None,                            # will be set dynamically
    'xlabel': 'Date',
    'ylabel': 'ORCA per SOL',
    'line_color': '#1f77b4',                  # blue for raw ratio
    'ma_color': '#ff7f0e',                    # orange for MA
    'alpha': 0.75,
    'grid_style': 'whitegrid',
    'start_date': None,                       # e.g. '2025-01-01' to zoom
    'end_date': None,
}

# Dynamically build title so it always matches the MA window
CONFIG['title'] = f'ORCA/SOL Price Ratio with {CONFIG["ma_window"]}-Period Moving Average (2024-2026)'
# ======================================================

# Helper: automatically add fetched_data/ prefix if missing
def ensure_fetched_data_path(filename: str) -> str:
    """Add 'fetched_data/' only if no path/folder is already specified."""
    if '/' in filename or '\\' in filename or filename.startswith('fetched_data'):
        return filename
    return f'fetched_data/{filename}'

# Load data with automatic path handling
sol_df = pd.read_csv(ensure_fetched_data_path(CONFIG['sol_file']))
orca_df = pd.read_csv(ensure_fetched_data_path(CONFIG['orca_file']))

# Parse datetimes (handles mixed microsecond formats safely)
sol_df['datetime'] = pd.to_datetime(sol_df['datetime'], format='mixed', utc=True)
orca_df['datetime'] = pd.to_datetime(orca_df['datetime'], format='mixed', utc=True)

# Set index and sort
sol_df.set_index('datetime', inplace=True)
orca_df.set_index('datetime', inplace=True)
sol_df = sol_df.sort_index()
orca_df = orca_df.sort_index()

# Optional date filtering
if CONFIG['start_date']:
    start = pd.to_datetime(CONFIG['start_date'], utc=True)
    sol_df = sol_df[sol_df.index >= start]
    orca_df = orca_df[orca_df.index >= start]
if CONFIG['end_date']:
    end = pd.to_datetime(CONFIG['end_date'], utc=True)
    sol_df = sol_df[sol_df.index <= end]
    orca_df = orca_df[orca_df.index <= end]

# Merge with nearest-timestamp alignment
df = pd.merge_asof(
    orca_df.rename(columns={'price_usd': 'price_usd_orca'}),
    sol_df.rename(columns={'price_usd': 'price_usd_sol'}),
    left_index=True,
    right_index=True,
    direction='nearest'
)

# Compute ratio + longer-term moving average
df['orca_sol'] = df['price_usd_orca'] / df['price_usd_sol']
df['ma'] = df['orca_sol'].rolling(window=CONFIG['ma_window'], min_periods=1).mean()

# Summary stats
print("\nORCA/SOL Price Summary:")
print(df['orca_sol'].describe())

# Plot
plt.figure(figsize=CONFIG['figsize'])
sns.set_style(CONFIG['grid_style'])

plt.plot(df.index, df['orca_sol'],
         label='ORCA/SOL Ratio',
         color=CONFIG['line_color'],
         linewidth=1.5,
         alpha=CONFIG['alpha'])
plt.plot(df.index, df['ma'],
         label=f'{CONFIG["ma_window"]}-Period Moving Average',
         color=CONFIG['ma_color'],
         linewidth=2.5)

plt.title(CONFIG['title'], fontsize=18, pad=20, fontweight='bold')
plt.xlabel(CONFIG['xlabel'], fontsize=14)
plt.ylabel(CONFIG['ylabel'], fontsize=14)
plt.legend(fontsize=12, loc='upper left')
plt.grid(True, alpha=0.3)
plt.gcf().autofmt_xdate()
plt.tight_layout()

plt.savefig(CONFIG['output_file'], dpi=CONFIG['dpi'], bbox_inches='tight')
plt.close()

print(f"\n✅ Chart saved as '{CONFIG['output_file']}' (DPI={CONFIG['dpi']})")
print(f"   Data points: {len(df):,}")
print(f"   Date range: {df.index.min().date()} – {df.index.max().date()}")
print(f"   Latest ratio: {df['orca_sol'].iloc[-1]:.6f}")
print(f"   MA window used: {CONFIG['ma_window']} periods (~{CONFIG['ma_window']//24} days)")
