import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import timedelta
import os
import argparse
import json

# ==================== CONFIG SECTION ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

PLOT_RECENT_MONTHS = 12
RECENT_DAYS_FOR_SUMMARY = 30
DPI = 150
FIG_SIZE = (15, 8)

# Short MA momentum windows (easily extensible)
SHORT_MA_MOMENTUM_WINDOWS = [6, 12, 24]

# =======================================================

# Command-line argument for maximum flexibility
parser = argparse.ArgumentParser(
    description="Generate price chart(s) with Short & Long MAs. "
                "Default: all tokens where include_in_portfolio=true"
)
parser.add_argument(
    'coin',
    nargs='?',                          # optional
    default=None,
    help='Coin identifier (e.g. "fartcoin", "popcat"). Omit to process ALL portfolio tokens.'
)
parser.add_argument(
    '--csv',
    type=str,
    help='Path to the price CSV file (overrides coin argument)'
)
parser.add_argument(
    '--portfolio',
    '--all',
    action='store_true',
    help='Force processing of ALL tokens marked "include_in_portfolio": true'
)
args = parser.parse_args()


def load_tokens_list():
    """Load tokens_list.json once"""
    json_path = os.path.join(SCRIPT_DIR, 'tokens_list.json')
    if not os.path.exists(json_path):
        print(f"⚠️  tokens_list.json not found at {json_path}")
        return []
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading tokens_list.json: {e}")
        return []


def get_portfolio_tokens():
    """Return only tokens marked for portfolio"""
    tokens = load_tokens_list()
    portfolio = [t for t in tokens if t.get("include_in_portfolio") is True]
    return portfolio


def load_token_config(coin_id: str):
    """Load short_term_hours / long_term_hours from tokens_list.json"""
    json_path = os.path.join(SCRIPT_DIR, 'tokens_list.json')
    defaults = {"short_term_hours": 168, "long_term_hours": 720}

    if not os.path.exists(json_path):
        print(f"⚠️  tokens_list.json not found at {json_path}. Using defaults {defaults}.")
        return defaults

    try:
        with open(json_path, encoding="utf-8") as f:
            tokens = json.load(f)

        for token in tokens:
            if token.get("id") == coin_id:
                config = {
                    "short_term_hours": token.get("short_term_hours", 168),
                    "long_term_hours": token.get("long_term_hours", 720)
                }
                print(f"Loaded token-specific config for {coin_id}: "
                      f"short={config['short_term_hours']}h, long={config['long_term_hours']}h")
                return config
    except Exception as e:
        print(f"⚠️  Error loading tokens_list.json: {e}")

    print(f"⚠️  Token {coin_id} not found in tokens_list.json. Using defaults.")
    return defaults


def generate_price_chart(coin_id: str, csv_path: str = None):
    """Core logic for one token – extracted for clean multi-token support"""
    if csv_path is None:
        csv_path = os.path.join(SCRIPT_DIR, 'price_data', f'{coin_id}.csv')

    if not os.path.exists(csv_path):
        print(f"❌ CSV file not found: {csv_path} → skipping {coin_id}")
        return

    print(f"\n{'='*70}")
    print(f"PROCESSING: {coin_id.upper()}")
    print(f"{'='*70}")

    # Load data
    print(f"Loading data from: {csv_path}")
    df = pd.read_csv(csv_path)

    # CRITICAL FIX: Convert string prices (full Decimal precision)
    df['price_usd'] = pd.to_numeric(df['price_usd'], errors='coerce')
    for col in ['market_cap', 'total_volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Parse datetime and convert to KST
    df['datetime_utc'] = pd.to_datetime(df['datetime'], format='ISO8601')
    df['datetime_kst'] = df['datetime_utc'].dt.tz_convert('Asia/Seoul')

    # Sort
    df = df.sort_values('datetime_kst').reset_index(drop=True)

    # Token-specific MA windows
    token_config = load_token_config(coin_id)
    SHORT_MA_WINDOW = token_config["short_term_hours"]
    LONG_MA_WINDOW = token_config["long_term_hours"]

    # === Convert hours to days for legend & title (user request) ===
    short_days = SHORT_MA_WINDOW // 24
    long_days = LONG_MA_WINDOW // 24

    # Calculate moving averages on FULL dataset
    df['short_ma'] = df['price_usd'].rolling(window=SHORT_MA_WINDOW, min_periods=1).mean()
    df['long_ma'] = df['price_usd'].rolling(window=LONG_MA_WINDOW, min_periods=1).mean()

    # === Recent trend summary (always uses full recent data) ===
    recent_df = df[df['datetime_kst'] >= df['datetime_kst'].max() - timedelta(days=RECENT_DAYS_FOR_SUMMARY)]
    if len(recent_df) == 0:
        print("⚠️ No recent data.")
        return

    latest_price = recent_df['price_usd'].iloc[-1]
    latest_short_ma = recent_df['short_ma'].iloc[-1]
    latest_long_ma = recent_df['long_ma'].iloc[-1]
    latest_time_kst = recent_df['datetime_kst'].iloc[-1]

    print(f"\nLatest data point (KST): {latest_time_kst.strftime('%Y-%m-%d %H:%M')}")
    print(f"Latest {coin_id} Price: ${latest_price:.6f}")

    print(f"\nMoving Averages:")
    print(f"  Short MA ({SHORT_MA_WINDOW}h): ${latest_short_ma:.6f}  [{(latest_price / latest_short_ma - 1)*100:+.2f}%]")
    print(f"  Long MA ({LONG_MA_WINDOW}h):  ${latest_long_ma:.6f}  [{(latest_price / latest_long_ma - 1)*100:+.2f}%]")

    # Helper for % change
    def pct_change(series, periods):
        if len(series) > periods:
            return (series.iloc[-1] / series.iloc[-periods] - 1) * 100
        return float('nan')

    price_s = recent_df['price_usd']

    print("\nRecent Performance:")
    print(f"  24h change: {pct_change(price_s, 24):+6.2f}%")
    print(f"   3d change: {pct_change(price_s, 72):+6.2f}%")
    print(f"   7d change: {pct_change(price_s, 168):+6.2f}%")
    print(f"  30d change: {pct_change(price_s, 720):+6.2f}%")

    # Range info
    recent_high = recent_df['price_usd'].max()
    recent_low = recent_df['price_usd'].min()
    print(f"\n{RECENT_DAYS_FOR_SUMMARY}d Range: ${recent_low:.4f} – ${recent_high:.4f}")
    if latest_price > 0:
        print(f"   Current from {RECENT_DAYS_FOR_SUMMARY}d high: {(latest_price / recent_high - 1)*100 :+.1f}%")

    # Short MA momentum
    print("\nShort MA Momentum:")
    for hours in SHORT_MA_MOMENTUM_WINDOWS:
        if len(recent_df) > hours:
            mom = (latest_short_ma / recent_df['short_ma'].iloc[-hours] - 1) * 100
            print(f"  {hours:2d}h : {mom:+.2f}%")
        else:
            print(f"  {hours:2d}h : N/A (insufficient data)")

    # === Plotting (MA values from full data, but chart limited to recent months) ===
    plot_df = df.copy()
    if PLOT_RECENT_MONTHS is not None and PLOT_RECENT_MONTHS > 0:
        cutoff = df['datetime_kst'].max() - pd.DateOffset(months=PLOT_RECENT_MONTHS)
        plot_df = df[df['datetime_kst'] >= cutoff].copy()
        print(f"Plotting only the last {PLOT_RECENT_MONTHS} months of data")

    sns.set_style("darkgrid")
    plt.figure(figsize=FIG_SIZE)

    plt.plot(plot_df['datetime_kst'], plot_df['price_usd'],
             label='Price (USD)', color='#1f77b4', linewidth=1.8, alpha=0.95)
    plt.plot(plot_df['datetime_kst'], plot_df['short_ma'],
             label=f'Short MA ({SHORT_MA_WINDOW}h / {short_days}d)', 
             color='#ff7f0e', linewidth=2)
    plt.plot(plot_df['datetime_kst'], plot_df['long_ma'],
             label=f'Long MA ({LONG_MA_WINDOW}h / {long_days}d)', 
             color='#2ca02c', linewidth=2)

    # Updated title with both hours and days
    TITLE = (f'{coin_id.upper()} Price (USD) — '
             f'Short MA ({SHORT_MA_WINDOW}h / {short_days}d) & '
             f'Long MA ({LONG_MA_WINDOW}h / {long_days}d)')

    plt.title(TITLE, fontsize=16, pad=20)
    plt.xlabel('Date / Time (Korea Standard Time)', fontsize=12)
    plt.ylabel('Price in USD', fontsize=12)
    plt.legend(fontsize=11, loc='upper left')
    plt.xticks(rotation=45, ha='right')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # === Dynamic filename with months indicator ===
    if PLOT_RECENT_MONTHS is not None and PLOT_RECENT_MONTHS > 0:
        months_str = f"{int(PLOT_RECENT_MONTHS)}m"
    else:
        months_str = "full"
    
    OUTPUT_FILE = f'{coin_id}_price_ma_{months_str}_kst.png'

    # Save chart
    plt.savefig(OUTPUT_FILE, dpi=DPI, bbox_inches='tight')
    print(f"\nChart saved as '{OUTPUT_FILE}' (DPI = {DPI})")
    plt.close()


# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    if args.portfolio or (args.coin is None and args.csv is None):
        # PORTFOLIO MODE (default)
        portfolio = get_portfolio_tokens()
        print(f"Generating charts for {len(portfolio)} portfolio token(s)...")
        for token in portfolio:
            coin_id = token.get("id")
            if coin_id:
                generate_price_chart(coin_id)
    else:
        # SINGLE TOKEN MODE
        if args.csv:
            coin_id = os.path.splitext(os.path.basename(args.csv))[0]
            generate_price_chart(coin_id, args.csv)
        else:
            coin_id = args.coin or 'fartcoin'
            generate_price_chart(coin_id)
