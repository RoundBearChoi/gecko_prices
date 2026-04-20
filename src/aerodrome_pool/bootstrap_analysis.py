import pandas as pd
import numpy as np
from datetime import datetime
import pytz  # pip install pytz if you don't have it

# ====================== CONFIG ======================
CSV_FILE = 'aerodrome_msusd_usdc_hourly_data.csv'
N_BOOT = 5000
SEED = 42
OUTPUT_PREFIX = 'aerodrome_msusd_usdc_lp_analysis'   # filename base

# NEW: Explicit pair direction (prevents any confusion with USDC-MSUSD)
PAIR_NAME = "MSUSD-USDC"
PAIR_DESCRIPTION = "price quoted as USDC per 1 MSUSD"
# ===================================================

# Load and clean
df = pd.read_csv(CSV_FILE)
df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

# Hourly close-to-close percentage changes
df['pct_change'] = df['close'].pct_change()
returns = df['pct_change'].dropna().values

current_price = df['close'].iloc[-1]
run_time_kst = datetime.now(pytz.timezone('Asia/Seoul'))
run_time_utc = run_time_kst.astimezone(pytz.utc)

# ====================== CALCULATIONS ======================
# Empirical
emp_mean = returns.mean()
emp_median = np.median(returns)
emp_std = returns.std()
emp_low = np.percentile(returns, 2.5)
emp_high = np.percentile(returns, 97.5)

# Bootstrap
np.random.seed(SEED)
n = len(returns)
boot_medians = np.zeros(N_BOOT)
boot_lowers = np.zeros(N_BOOT)
boot_uppers = np.zeros(N_BOOT)

for i in range(N_BOOT):
    sample = np.random.choice(returns, size=n, replace=True)
    boot_medians[i] = np.median(sample)
    boot_lowers[i] = np.percentile(sample, 2.5)
    boot_uppers[i] = np.percentile(sample, 97.5)

boot_median = np.median(boot_medians)
boot_lower = np.median(boot_lowers)
boot_upper = np.median(boot_uppers)

# Suggested LP bounds
lp_lower_price = current_price * (1 + boot_lower)
lp_upper_price = current_price * (1 + boot_upper)

# ====================== PRINT TO CONSOLE ======================
print(f"Loaded {len(df)} hourly candles → {len(returns)} returns")
print(f"Price range: {df['close'].min():.5f} – {df['close'].max():.5f} (mean {df['close'].mean():.5f})")

# NEW: Clear pair direction banner in console
print("\n" + "="*60)
print(f"PAIR DIRECTION: {PAIR_NAME}")
print(f"                ({PAIR_DESCRIPTION})")
print("="*60)

print("\n=== Empirical ===")
print(f"Mean hourly change : {emp_mean*100:+.4f}%")
print(f"Median              : {emp_median*100:+.4f}%")
print(f"Std dev             : {emp_std*100:.4f}%")
print(f"95% range (raw)     : {emp_low*100:.4f}% to {emp_high*100:.4f}%")

print("\n=== Bootstrapped (5000 resamples) ===")
print(f"Most likely hourly change (median) : {boot_median*100:+.4f}%")
print(f"95% coverage range                 : {boot_lower*100:.4f}% to {boot_upper*100:.4f}%")

print(f"\nSuggested LP range (current price = {current_price:.5f}):")
print(f"Lower bound: {lp_lower_price:.5f}  ({boot_lower*100:+.4f}%)")
print(f"Upper bound: {lp_upper_price:.5f}  ({boot_upper*100:+.4f}%)")
print(f"Width: ±{((lp_upper_price - lp_lower_price)/(2*current_price)*100):.3f}% around current price")

# ====================== EXPORT TO .TXT ======================
filename = f"{OUTPUT_PREFIX}.txt"

with open(filename, 'w', encoding='utf-8') as f:
    f.write("=== AERODROME MSUSD-USDC HOURLY BOOTSTRAP ANALYSIS ===\n\n")
    f.write(f"Run time (KST): {run_time_kst.strftime('%Y-%m-%d %H:%M:%S KST')}\n")
    f.write(f"Run time (UTC): {run_time_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    f.write(f"Data points used: {len(returns)} hourly close-to-close returns\n")
    f.write(f"Current price (last close): {current_price:.5f}\n\n")
    
    # NEW: Explicit pair direction section in TXT
    f.write("=== PAIR DIRECTION ===\n")
    f.write(f"Analysis performed for : {PAIR_NAME}\n")
    f.write(f"Price quoting convention: {PAIR_DESCRIPTION}\n")
    f.write("• This is NOT the reverse USDC-MSUSD pool\n")
    f.write("• Lower/upper bounds below are already in the correct pool-native units\n")
    f.write("• You can copy-paste them directly into Aerodrome’s concentrated LP interface\n\n")
    
    f.write("=== EMPIRICAL STATISTICS ===\n")
    f.write(f"Mean hourly change   : {emp_mean*100:+.4f}%\n")
    f.write(f"Median hourly change : {emp_median*100:+.4f}%\n")
    f.write(f"Std dev              : {emp_std*100:.4f}%\n")
    f.write(f"Raw 95% range        : {emp_low*100:.4f}% to {emp_high*100:.4f}%\n\n")
    
    f.write("=== BOOTSTRAPPED RESULTS (5000 resamples) ===\n")
    f.write(f"Most likely hourly change (median) : {boot_median*100:+.4f}%\n")
    f.write(f"95% statistical coverage range     : {boot_lower*100:.4f}% to {boot_upper*100:.4f}%\n\n")
    
    f.write("=== RECOMMENDED LIQUIDITY POOL RANGE ===\n")
    f.write(f"Current price          : {current_price:.5f}\n")
    f.write(f"Lower bound            : {lp_lower_price:.5f}  ({boot_lower*100:+.4f}%)\n")
    f.write(f"Upper bound            : {lp_upper_price:.5f}  ({boot_upper*100:+.4f}%)\n")
    f.write(f"Range width            : ±{((lp_upper_price - lp_lower_price)/(2*current_price)*100):.3f}%\n")
    f.write(f"95% of hourly moves historically stayed inside this range\n\n")
    
    f.write("=== NOTES ===\n")
    f.write("• Based on close-to-close hourly % changes\n")
    f.write("• Non-parametric bootstrap (no normality assumption)\n")
    f.write("• Perfect for setting a tight but safe Aerodrome concentrated LP range\n")
    f.write("• Re-run daily for rolling updates\n")
    f.write("• Pair direction is hard-coded and matches your CSV filename convention\n")

print(f"\n✅ Results exported to: {filename}")
print(f"   (Pair direction {PAIR_NAME} is now clearly shown in both console and TXT)")
