#!/usr/bin/env python3
import pandas as pd
import numpy as np
import argparse
import sys
import warnings
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore")

# ==================== DEFAULT CONFIGURATION ====================
DEFAULT_CONFIG = {
    'n_boots': 5000,
    'n_months': 24,
    'horizon_hours': 24 * 7,
    'mean_block_length': 20,
    'low_percentile': 2.5,
    'high_percentile': 97.5,
    'data_dir': 'fetched_data',
    'draw_charts': True,
    'chart_dpi': 180,

    # Lag-1 autocorrelation classification thresholds
    'acf_strong_reversion_threshold': -0.05,
    'acf_momentum_threshold': 0.05,
}
# ============================================================

def load_price(token: str, data_dir: str = None) -> pd.Series:
    """Load CSV and convert to KST timezone-aware index.
    NEW: Robust handling for ultra-low prices and precision-loss zeros."""
    if data_dir is None:
        data_dir = DEFAULT_CONFIG['data_dir']
    path = f"{data_dir}/{token}_price_history.csv"
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        print(f"❌ ERROR: Could not find {path}")
        sys.exit(1)

    df['datetime'] = pd.to_datetime(df['datetime'], format='ISO8601')
    df = df.set_index('datetime')
    df.index = df.index.tz_convert('Asia/Seoul')
    
    price = df['price_usd'].sort_index()

    # ==================== NEW ROBUSTNESS PATCH ====================
    # Treat literal zeros as missing if they dominate the file (common precision bug)
    zero_ratio = (price == 0.0).mean()
    if zero_ratio > 0.3:
        print(f"⚠️  {token.upper()} CSV appears to have precision loss "
              f"({zero_ratio:.1%} zeros). Treating zeros as NaN.")
        price = price.replace(0.0, np.nan)
    
    # Safety floor for ultra-low meme-coin prices (prevents log underflow)
    price = price.clip(lower=1e-15)
    # ============================================================

    return price


def stationary_bootstrap(series: np.ndarray, n: int, mean_block: int) -> np.ndarray:
    """Stationary bootstrap resample (unchanged)."""
    T = len(series)
    if T == 0:
        return np.zeros(n)
    p = 1.0 / mean_block
    boot = np.zeros(n)
    idx = 0
    while idx < n:
        start = np.random.randint(0, T)
        L = np.random.geometric(p)
        for k in range(L):
            if idx >= n:
                break
            boot[idx] = series[(start + k) % T]
            idx += 1
    return boot


def get_sb_analysis(
    token0: str,
    token1: str,
    n_months: int = None,
    horizon_hours: int = None,
    n_boots: int = None,
    mean_block_length: int = None,
    low_percentile: float = None,
    high_percentile: float = None,
    data_dir: str = None,
    draw_charts: bool = False,
    seed: int = 42,
) -> dict:
    """
    Reusable core function with full data-quality protection for tiny prices.
    """
    # Merge defaults with overrides
    config = DEFAULT_CONFIG.copy()
    if n_months is not None: config['n_months'] = n_months
    if horizon_hours is not None: config['horizon_hours'] = horizon_hours
    if n_boots is not None: config['n_boots'] = n_boots
    if mean_block_length is not None: config['mean_block_length'] = mean_block_length
    if low_percentile is not None: config['low_percentile'] = low_percentile
    if high_percentile is not None: config['high_percentile'] = high_percentile
    if data_dir is not None: config['data_dir'] = data_dir
    config['draw_charts'] = draw_charts

    token0 = token0.lower()
    token1 = token1.lower()
    horizon = config['horizon_hours']

    # --- Load & align data ---
    price0 = load_price(token0, config['data_dir'])
    price1 = load_price(token1, config['data_dir'])

    combined = pd.DataFrame({'price0': price0, 'price1': price1}).sort_index()
    combined = combined.resample('h').last()

    total_overlapping_hours = len(combined.dropna(how='any'))

    combined = combined.ffill()
    pair_price = combined['price1'] / combined['price0']

    end_date = pair_price.index.max()
    start_date = end_date - pd.DateOffset(months=config['n_months'])
    historical = pair_price.loc[start_date:].dropna()

    if len(historical) < 48:
        print(f"⚠️  WARNING: Only {len(historical):,} hourly observations available — results may be unreliable.")

    # ==================== NEW: DATA QUALITY GUARD (prevents SVD crash) ====================
    lag1_acf = np.nan
    lag1_slope = np.nan
    log_returns = np.array([])

    if (historical <= 0).any() or historical.std() < 1e-12:
        print(f"❌ CRITICAL: Invalid price data for {token0.upper()}/{token1.upper()} "
              f"(non-positive or near-constant). Skipping lag-1 stats.")
    else:
        log_returns = np.log(historical).diff().dropna().values
        if len(log_returns) > 1:
            lag1_acf = np.corrcoef(log_returns[:-1], log_returns[1:])[0, 1]
            if len(log_returns) > 10:
                x = log_returns[:-1]
                y = log_returns[1:]
                if np.std(x) > 1e-12 and np.isfinite(x).all() and np.isfinite(y).all():
                    try:
                        slope, _ = np.polyfit(x, y, deg=1)
                        lag1_slope = float(slope)
                    except Exception as e:
                        print(f"⚠️  polyfit failed for {token0.upper()}/{token1.upper()}: {e}")
                        lag1_slope = np.nan
                else:
                    lag1_slope = np.nan
    # ===================================================================================

    # --- Stationary Bootstrap ---
    np.random.seed(seed)
    sim_mins = []
    sim_maxs = []
    for _ in range(config['n_boots']):
        boot_r = stationary_bootstrap(log_returns, n=horizon, mean_block=config['mean_block_length'])
        path = np.exp(np.cumsum(boot_r))
        path = np.insert(path, 0, 1.0)
        sim_mins.append(path.min())
        sim_maxs.append(path.max())

    # === BOTH RANGES ===
    lower_mult = np.percentile(sim_mins, config['low_percentile'])
    upper_mult = np.percentile(sim_maxs, config['high_percentile'])

    median_lower = np.median(sim_mins)
    median_upper = np.median(sim_maxs)
    median_dev = np.median([max(1 - m, M - 1) for m, M in zip(sim_mins, sim_maxs)])

    actual_coverage = np.mean(
        (np.array(sim_mins) >= lower_mult) & (np.array(sim_maxs) <= upper_mult)
    ) * 100

    current_price = historical.iloc[-1] if len(historical) > 0 else np.nan

    results = {
        'token0': token0,
        'token1': token1,
        'current_price': float(current_price),
        'high_conf_lower': float(lower_mult),
        'high_conf_upper': float(upper_mult),
        'typical_lower': float(median_lower),
        'typical_upper': float(median_upper),
        'median_max_dev': float(median_dev),
        'lag1_acf': float(lag1_acf),
        'lag1_slope': float(lag1_slope),
        'num_observations': int(len(historical)),
        'total_overlapping_hours': int(total_overlapping_hours),
        'horizon_hours': int(horizon),
        'n_boots': int(config['n_boots']),
        'actual_coverage': float(actual_coverage),
        'sim_mins': np.array(sim_mins),
        'sim_maxs': np.array(sim_maxs),
        'log_returns': log_returns,
        'config': config
    }

    if config['draw_charts']:
        _generate_charts(results)

    return results


# (The rest of the file — _generate_charts, print_analysis, main — is unchanged)
def _generate_charts(results: dict):
    """Internal helper — called only when draw_charts=True."""
    print(f"\nGenerating and exporting charts for {results['horizon_hours']}h horizon...")
    sns.set_style("darkgrid")
    plt.rcParams['figure.figsize'] = (14, 10)
    fig = plt.figure()

    sim_mins = results['sim_mins']
    sim_maxs = results['sim_maxs']
    log_returns = results['log_returns']
    horizon = results['horizon_hours']
    lower_mult = results['high_conf_lower']
    upper_mult = results['high_conf_upper']
    median_lower = results['typical_lower']
    median_upper = results['typical_upper']

    # 1. Simulated paths
    ax1 = plt.subplot(2, 2, 1)
    np.random.seed(42)
    sample_idx = np.random.choice(len(sim_mins), 200, replace=False)
    for i in sample_idx:
        boot_r = stationary_bootstrap(results['log_returns'], n=horizon,
                                      mean_block=results['config']['mean_block_length'])
        path = np.exp(np.cumsum(boot_r))
        path = np.insert(path, 0, 1.0)
        ax1.plot(range(horizon + 1), path, color='blue', alpha=0.05, lw=1)

    lower_pct = (lower_mult - 1) * 100
    upper_pct = (upper_mult - 1) * 100
    med_lower_pct = (median_lower - 1) * 100
    med_upper_pct = (median_upper - 1) * 100

    ax1.axhline(lower_mult, color='red', linestyle='--', lw=2,
                label=f'High-conf lower ({lower_mult:.4f} / {lower_pct:+.2f}%)')
    ax1.axhline(upper_mult, color='green', linestyle='--', lw=2,
                label=f'High-conf upper ({upper_mult:.4f} / {upper_pct:+.2f}%)')
    ax1.axhline(median_lower, color='red', linestyle=':', lw=1.5,
                label=f'Typical lower ({median_lower:.4f} / {med_lower_pct:+.2f}%)')
    ax1.axhline(median_upper, color='green', linestyle=':', lw=1.5,
                label=f'Typical upper ({median_upper:.4f} / {med_upper_pct:+.2f}%)')

    ax1.text(horizon + 0.2, lower_mult + 0.0035, f'  {lower_pct:+.2f}%',
             color='red', va='bottom', ha='left', fontsize=11, fontweight='bold')
    ax1.text(horizon + 0.2, upper_mult + 0.0035, f'  {upper_pct:+.2f}%',
             color='green', va='bottom', ha='left', fontsize=11, fontweight='bold')

    ax1.set_title(f'200 Example {horizon}h Simulated Paths\n(normalized to start = 1.0)')
    ax1.set_xlabel('Hours (KST)')
    ax1.set_ylabel('Price Multiplier')
    ax1.legend(loc='upper left')

    # 2. Histograms
    ax2 = plt.subplot(2, 2, 2)
    sns.histplot(sim_mins, kde=True, color='red', alpha=0.6, label='Simulated Mins', ax=ax2)
    sns.histplot(sim_maxs, kde=True, color='green', alpha=0.6, label='Simulated Maxs', ax=ax2)
    ax2.axvline(lower_mult, color='red', linestyle='--', lw=2)
    ax2.axvline(upper_mult, color='green', linestyle='--', lw=2)
    ax2.axvline(median_lower, color='red', linestyle=':', lw=1.5)
    ax2.axvline(median_upper, color='green', linestyle=':', lw=1.5)
    ax2.set_title(f'Distribution of {horizon}h Extremes')
    ax2.set_xlabel('Multiplier')
    ax2.legend()

    # 3. Lag-1 Reversion Visualization
    ax3 = plt.subplot(2, 2, 3)
    n_obs = len(log_returns)
    if n_obs > 1:
        x = log_returns[:-1]
        y = log_returns[1:]
        ax3.scatter(x, y, alpha=0.08, s=4, color='purple')
        if len(x) > 10:
            slope, intercept = np.polyfit(x, y, deg=1)
            x_range = np.linspace(x.min(), x.max(), 100)
            y_fit = slope * x_range + intercept
            ax3.plot(x_range, y_fit, color='red', lw=2.5, label='Regression line')
        ax3.axhline(0, color='gray', linestyle='--', alpha=0.7)
        ax3.axvline(0, color='gray', linestyle='--', alpha=0.7)
        ax3.set_xlabel('log return at t-1')
        ax3.set_ylabel('log return at t')
        ax3.set_title('Lag-1 Reversion Visualization\n(scatter of consecutive hourly log returns)')
        ax3.legend(loc='upper right')

        lag1_acf = results['lag1_acf']
        config = results['config']
        if np.isnan(lag1_acf):
            class_txt = "INVALID DATA"
        elif lag1_acf < config['acf_strong_reversion_threshold']:
            class_txt = "STRONG REVERSION"
        elif lag1_acf < 0:
            class_txt = "mild reversion"
        elif lag1_acf > config['acf_momentum_threshold']:
            class_txt = "MOMENTUM"
        else:
            class_txt = "near random-walk"
        ax3.text(0.02, 0.98, f'Lag-1 ACF = {lag1_acf:.4f}\n{class_txt}',
                 transform=ax3.transAxes, fontsize=11,
                 verticalalignment='top', horizontalalignment='left',
                 bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.9))
    else:
        ax3.text(0.5, 0.5, 'Insufficient data for Lag-1 chart', ha='center', va='center')

    # 4. Joint distribution
    ax4 = plt.subplot(2, 2, 4)
    sns.scatterplot(x=sim_mins, y=sim_maxs, alpha=0.15, s=10, color='purple', ax=ax4)
    ax4.axvline(lower_mult, color='red', linestyle='--')
    ax4.axhline(upper_mult, color='green', linestyle='--')
    ax4.axvline(median_lower, color='red', linestyle=':', lw=1.5)
    ax4.axhline(median_upper, color='green', linestyle=':', lw=1.5)
    ax4.set_title(f'Joint (Min, Max) Pairs per {horizon}h Simulation')
    ax4.set_xlabel('Simulated Minimum Multiplier')
    ax4.set_ylabel('Simulated Maximum Multiplier')

    plt.tight_layout()
    plt.subplots_adjust(top=0.87)
    plt.suptitle(
        f"{results['token0'].upper()}-{results['token1'].upper()} SB Ranges\n"
        f"High-confidence (~95%) + Typical (median) + Lag-1 Reversion • {horizon}h • "
        f"{results['config']['n_months']} months • {results['n_boots']} bootstraps",
        fontsize=14, y=0.99
    )

    filename = f"sb_range_{results['token0']}_{results['token1']}_{results['config']['n_months']}m_{horizon}h.png"
    fig.savefig(filename, dpi=results['config']['chart_dpi'], bbox_inches='tight')
    plt.close(fig)
    print(f"✅ Charts exported as: {filename}  (DPI = {results['config']['chart_dpi']})")


def print_analysis(results: dict):
    """CLI-friendly pretty print (keeps original output format)."""
    token0 = results['token0'].upper()
    token1 = results['token1'].upper()
    horizon = results['horizon_hours']
    horizon_label = f"{horizon}h"
    if horizon == 24:
        horizon_label = "24h (1 day)"
    elif horizon == 168:
        horizon_label = "168h (7 days)"
    elif horizon == 720:
        horizon_label = "720h (30 days)"

    print(f"\n{'='*80}")
    print(f"OPTIMAL LIQUIDITY POOL RANGE for {token0} per {token1}")
    print('='*80)

    lag1_acf = results['lag1_acf']
    config = results['config']
    print(f"Lag-1 autocorrelation of log returns : {lag1_acf:.4f} ", end="")
    if np.isnan(lag1_acf):
        print("(❌ invalid data)")
    elif lag1_acf < config['acf_strong_reversion_threshold']:
        print("(🔄 strong reversion tendency)")
    elif lag1_acf < 0:
        print("(🔄 mild reversion tendency)")
    elif lag1_acf > config['acf_momentum_threshold']:
        print("(📈 momentum / trending tendency)")
    else:
        print("(➡️  near random-walk behaviour)")

    # ... rest of print_analysis unchanged (omitted for brevity — copy the original version)
    lower_mult = results['high_conf_lower']
    upper_mult = results['high_conf_upper']
    lower_pct = (lower_mult - 1) * 100
    upper_pct = (upper_mult - 1) * 100
    print(f"HIGH-CONFIDENCE COVERAGE (~95% of simulated {horizon_label} paths)")
    print(f"Lower multiplier : {lower_mult:.4f}  →  lower = current × {lower_mult:.4f}  ({lower_pct:+.2f}%)")
    print(f"Upper multiplier : {upper_mult:.4f}  →  upper = current × {upper_mult:.4f}  ({upper_pct:+.2f}%)")
    print(f"Range width      : {(upper_mult / lower_mult - 1)*100:.1f}%")
    print(f"Actual paths fully covered: {results['actual_coverage']:.1f}% (joint)")

    med_lower = results['typical_lower']
    med_upper = results['typical_upper']
    med_lower_pct = (med_lower - 1) * 100
    med_upper_pct = (med_upper - 1) * 100
    print(f"\nTYPICAL / MAXIMUM-LIKELIHOOD {horizon_label.upper()} RANGE (median, asymmetric)")
    print(f"Lower multiplier : {med_lower:.4f}  →  ({med_lower_pct:+.2f}%)")
    print(f"Upper multiplier : {med_upper:.4f}  →  ({med_upper_pct:+.2f}%)")
    print(f"Range width      : {(med_upper / med_lower - 1)*100:.1f}%")
    print(f"Symmetric ±R     : ±{results['median_max_dev']*100:.2f}%   (median max-deviation)")
    print(f"Current {token0} per {token1} price: {results['current_price']:,.4f}")
    print('='*80)


def main():
    parser = argparse.ArgumentParser(description="Stationary Bootstrap optimal liquidity-pool range")
    parser.add_argument('token0', nargs='?', default=None)
    parser.add_argument('token1', nargs='?', default=None)
    parser.add_argument('n_months', nargs='?', type=int, default=None)
    args = parser.parse_args()

    token0 = args.token0 or 'eth'
    token1 = args.token1 or 'btc'
    n_months = args.n_months

    results = get_sb_analysis(
        token0=token0,
        token1=token1,
        n_months=n_months,
        draw_charts=DEFAULT_CONFIG['draw_charts']
    )
    print_analysis(results)


if __name__ == "__main__":
    main()
