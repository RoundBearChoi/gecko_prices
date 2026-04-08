import pandas as pd
import numpy as np
from itertools import combinations
import time
import warnings
warnings.filterwarnings("ignore")

# ========================= CONFIG =========================
config = {
    'input_csv': "all_pairs_matched_hourly_prices_8_months.csv",
    'n_months': 8,
    'window_days': 60,                    # rolling window for mean/SD
    'n_boots': 5000,
    'block_size_hours': 24*7,             # 7 days – preserves temporal structure
    'sd_threshold': 1.0,                  # +-1 SD
    'reversion_hysteresis': 0.5,          # return inside |z| < 0.5 to confirm clean trip
    'min_obs_per_window': 1000,           # skip windows/pairs with too few data
    'use_log_ratio': False,               # False = price ratio A/B (your preference)
    'output_top_n': 10,                   # how many top pairs to display
    'analyze_all_pairs': True,
    'max_pairs_to_test': 5,               # safety limit when analyze_all_pairs=False
    'progress_step': 20,                  # print progress every N pairs
}

# ========================= LOAD DATA =========================
df = pd.read_csv(config['input_csv'], parse_dates=["datetime"])
df.set_index("datetime", inplace=True)
tokens = df.columns.tolist()  # 29 tokens

print(f"Data shape: {df.shape} | Tokens: {len(tokens)}")
print(f"Date range: {df.index[0]} → {df.index[-1]}")

# Calculate effective months for output filename (honors your "12 vs 8" rule)
if len(df) > 0:
    days_span = (df.index[-1] - df.index[0]).days
    actual_months = round(days_span / 30.44)
    effective_months = min(config['n_months'], actual_months)
else:
    effective_months = 0
    actual_months = 0
print(f"Data spans ~{actual_months} months | Using {effective_months} months for output naming")

# Forward-fill any remaining NaNs
df = df.ffill()

# Individual token 1-SD raw % move (hourly log-return volatility)
logrets = np.log(df / df.shift(1))
token_vol_pct = (logrets.std() * 100).round(4)
print("\n=== Token hourly % volatility (1 SD move) ===")
print(token_vol_pct.sort_values(ascending=False))

# ========================= PROGRESS HEADER =========================
pairs = list(combinations(tokens, 2))
if not config['analyze_all_pairs']:
    pairs = pairs[:config['max_pairs_to_test']]

print(f"\n🔄 Analyzing {len(pairs)} unique pairs (no duplicates, left-to-right ordering)...")
print(f"   • Bootstraps per pair: {config['n_boots']}")
print(f"   • Window: {config['window_days']} days")
print(f"   • This may take awhile depending on your machine")
start_time = time.time()

# ========================= HELPER FUNCTIONS =========================
def count_full_trips(ratio_series: pd.Series, window_size: int):
    if len(ratio_series) < window_size:
        return 0, 0, 0
    rolling_mean = ratio_series.rolling(window_size, min_periods=window_size).mean()
    rolling_std = ratio_series.rolling(window_size, min_periods=window_size).std()
    z = (ratio_series - rolling_mean) / rolling_std

    up_trips = down_trips = 0
    in_upper = False
    in_lower = False

    for val in z.dropna():
        if val > config['sd_threshold']:
            in_upper = True
        elif val < -config['sd_threshold']:
            in_lower = True

        if in_upper and val < -config['reversion_hysteresis']:
            up_trips += 1
            in_upper = in_lower = False
        elif in_lower and val > config['reversion_hysteresis']:
            down_trips += 1
            in_upper = in_lower = False

    total_trips = up_trips + down_trips
    balance = min(up_trips, down_trips) / max(up_trips, down_trips) if total_trips > 0 else 0.0
    return total_trips, balance, (up_trips, down_trips)

def block_bootstrap_series(series: pd.Series, n_boots: int, block_size: int):
    n = len(series)
    boots = []
    for _ in range(n_boots):
        starts = np.random.randint(0, n - block_size + 1, size=(n // block_size) + 1)
        blocks = [series.iloc[s:s + block_size].values for s in starts]
        boot = np.concatenate(blocks)[:n]
        boots.append(pd.Series(boot, index=series.index))
    return boots

# ========================= MAIN ANALYSIS =========================
results = []
total_pairs = len(pairs)

for i, (t1, t2) in enumerate(pairs, 1):
    ratio = df[t1] / df[t2] if not config['use_log_ratio'] else np.log(df[t1] / df[t2])
    ratio = ratio.dropna()

    if len(ratio) < config['min_obs_per_window']:
        continue

    # Real count
    total_trips, balance, (up, down) = count_full_trips(ratio, config['window_days'] * 24)

    # Bootstrapped stats
    boot_counts = []
    boot_series = block_bootstrap_series(ratio, config['n_boots'], config['block_size_hours'])
    for bs in boot_series:
        cnt, _, _ = count_full_trips(bs, config['window_days'] * 24)
        boot_counts.append(cnt)

    boot_mean = np.mean(boot_counts)
    boot_std = np.std(boot_counts)
    boot_cv = boot_std / boot_mean if boot_mean > 0 else np.nan
    boot_ci_low, boot_ci_high = np.percentile(boot_counts, [2.5, 97.5])

    # Average ±1 SD raw % for the ratio
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

    # Progress print
    if i % config['progress_step'] == 0 or i == total_pairs:
        elapsed = time.time() - start_time
        pct = i / total_pairs * 100
        eta = (elapsed / i) * (total_pairs - i) if i > 0 else 0
        print(f"   Progress: {i:3d}/{total_pairs} pairs ({pct:5.1f}%) | "
              f"Elapsed: {elapsed/60:.1f} min | ETA: {eta/60:.1f} min")

# ========================= OUTPUT =========================
res_df = pd.DataFrame(results)
res_df = res_df.sort_values(by=['total_full_trips', 'balance_ratio'], ascending=[False, False])

print(f"\n=== TOP {config['output_top_n']} PAIRS by full-trip reversions ===")
print(res_df.head(config['output_top_n'])[[
    'pair', 'total_full_trips', 'balance_ratio', 'boot_mean_trips',
    'boot_95ci', 'boot_cv', 'avg_1sd_ratio_pct'
]].to_string(index=False))

output_filename = f"pair_reversion_bootstrapped_results_{effective_months}months.csv"
res_df.to_csv(output_filename, index=False)
print(f"\n✅ Full results saved to {output_filename}")
print("Done! 🎉")
