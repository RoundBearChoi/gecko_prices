import pandas as pd
import numpy as np
from itertools import combinations
import warnings
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
config = {
    'window_days': 60,                    # rolling window for mean/SD
    'n_boots': 1000,                      # start with 1000; 5000 for final run
    'block_size_hours': 168,              # 7 days – good compromise for hourly crypto
    'sd_threshold': 1.0,                  # +-1 SD
    'reversion_hysteresis': 0.5,          # return inside |z| < 0.5 to confirm reversion (avoids noise)
    'min_obs_per_window': 1000,           # skip windows/pairs with too few data
    'use_log_ratio': False,               # False = price ratio A/B; True = log(A/B)
    'output_top_n': 20,                   # how many top pairs to display
    'analyze_all_pairs': False,           # set True only if you have time (406 pairs)
    'max_pairs_to_test': 100,             # safety limit when analyze_all_pairs=False
}

# ========================= LOAD DATA =========================
df = pd.read_csv("all_pairs_matched_hourly_prices_8_months.csv", parse_dates=["datetime"])
df.set_index("datetime", inplace=True)
tokens = df.columns.tolist()  # 29 tokens

print(f"Data shape: {df.shape} | Tokens: {len(tokens)}")
print(f"Date range: {df.index[0]} → {df.index[-1]}")

# Forward-fill any remaining NaNs (only early rows affected)
df = df.ffill()

# Individual token 1-SD raw % move (hourly log-return volatility)
logrets = np.log(df / df.shift(1))
token_vol_pct = (logrets.std() * 100).round(4)
print("\n=== Token hourly % volatility (1 SD move) ===")
print(token_vol_pct.sort_values(ascending=False))

# ========================= HELPER FUNCTIONS =========================
def count_full_trips(ratio_series: pd.Series, window_size: int):
    """Count +-1 SD full-trip reversions using rolling z-score."""
    if len(ratio_series) < window_size:
        return 0, 0, 0  # up, down, total

    rolling_mean = ratio_series.rolling(window_size, min_periods=window_size).mean()
    rolling_std = ratio_series.rolling(window_size, min_periods=window_size).std()
    z = (ratio_series - rolling_mean) / rolling_std

    # State machine for clean full trips
    up_trips = down_trips = 0
    in_upper = False
    in_lower = False

    for val in z.dropna():
        if val > config['sd_threshold']:
            in_upper = True
        elif val < -config['sd_threshold']:
            in_lower = True

        # Confirmed reversion from upper band
        if in_upper and val < -config['reversion_hysteresis']:
            up_trips += 1
            in_upper = False
            in_lower = False
        # Confirmed reversion from lower band
        elif in_lower and val > config['reversion_hysteresis']:
            down_trips += 1
            in_upper = False
            in_lower = False

    total_trips = up_trips + down_trips
    balance = min(up_trips, down_trips) / max(up_trips, down_trips) if total_trips > 0 else 0.0
    return total_trips, balance, (up_trips, down_trips)

def block_bootstrap_series(series: pd.Series, n_boots: int, block_size: int):
    """Moving Block Bootstrap preserving temporal structure."""
    n = len(series)
    boots = []
    for _ in range(n_boots):
        # Random start indices
        starts = np.random.randint(0, n - block_size + 1, size=(n // block_size) + 1)
        blocks = [series.iloc[s:s + block_size].values for s in starts]
        boot = np.concatenate(blocks)[:n]
        boots.append(pd.Series(boot, index=series.index))
    return boots

# ========================= MAIN ANALYSIS =========================
pairs = list(combinations(tokens, 2))
if not config['analyze_all_pairs']:
    pairs = pairs[:config['max_pairs_to_test']]

results = []

for t1, t2 in pairs:
    ratio = df[t1] / df[t2] if not config['use_log_ratio'] else np.log(df[t1] / df[t2])
    ratio = ratio.dropna()

    if len(ratio) < config['min_obs_per_window']:
        continue

    # Real-world count
    total_trips, balance, (up, down) = count_full_trips(ratio, config['window_days'] * 24)

    # Bootstrapped distribution of trip count
    boot_counts = []
    boot_series = block_bootstrap_series(ratio, config['n_boots'], config['block_size_hours'])
    for bs in boot_series:
        cnt, _, _ = count_full_trips(bs, config['window_days'] * 24)
        boot_counts.append(cnt)

    boot_mean = np.mean(boot_counts)
    boot_std = np.std(boot_counts)
    boot_cv = boot_std / boot_mean if boot_mean > 0 else np.nan
    boot_ci_low, boot_ci_high = np.percentile(boot_counts, [2.5, 97.5])

    # Average ±1 SD raw % move for the *ratio* itself
    rolling_mean = ratio.rolling(config['window_days']*24).mean()
    rolling_std = ratio.rolling(config['window_days']*24).std()
    avg_ratio_1sd_pct = (rolling_std / rolling_mean * 100).mean().round(2)

    results.append({
        'pair': f"{t1}-{t2}",
        'total_full_trips': total_trips,
        'balance_ratio': round(balance, 3),
        'up_trips': up,
        'down_trips': down,
        'boot_mean_trips': round(boot_mean, 2),
        'boot_95ci': f"[{boot_ci_low:.1f}, {boot_ci_high:.1f}]",
        'boot_cv': round(boot_cv, 3),
        'avg_1sd_ratio_pct': avg_ratio_1sd_pct,
    })

# ========================= OUTPUT =========================
res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by=['total_full_trips', 'balance_ratio'], ascending=[False, False])

print(f"\n=== TOP {config['output_top_n']} PAIRS by full-trip reversions ===")
print(res_df.head(config['output_top_n'])[[
    'pair', 'total_full_trips', 'balance_ratio', 'boot_mean_trips',
    'boot_95ci', 'boot_cv', 'avg_1sd_ratio_pct'
]].to_string(index=False))

# Save full results
res_df.to_csv("pair_reversion_bootstrapped_results.csv", index=False)
print("\nFull results saved to pair_reversion_bootstrapped_results.csv")
print("Done! Adjust config['n_boots'], block_size_hours, or analyze_all_pairs=True for deeper runs.")
