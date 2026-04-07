#!/usr/bin/env python3
import pandas as pd
import numpy as np
from itertools import combinations
import sys
import time

try:
    from sb_tokens import load_price, DEFAULT_CONFIG
except ImportError:
    print("❌ ERROR: sb_tokens.py not found in the current directory.")
    sys.exit(1)

# ==================== CONFIGURATION ====================
CONFIG = {
    'tokens_file': 'subjective_top_tokens.txt',
    'output_csv': 'lag1_acf_analysis.csv',
    'n_months': 9,
    'data_dir': 'fetched_data',
    'allow_duplicates': False,
    'start_from_bottom': True,
    'skip_missing_data': True,
}
# ======================================================

def load_tokens(filename: str) -> list[str]:
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            tokens = [line.strip().lower() for line in f if line.strip()]
        print(f"✅ Loaded {len(tokens)} tokens from {filename}")
        return tokens
    except FileNotFoundError:
        print(f"❌ ERROR: Could not find {filename}")
        sys.exit(1)


def generate_pairs(tokens: list[str], allow_duplicates: bool, start_from_bottom: bool):
    token_index = {token: idx for idx, token in enumerate(tokens)}
    
    if allow_duplicates:
        pairs = [(t0, t1) for t0 in tokens for t1 in tokens if t0 != t1]
    else:
        pairs = []
        for t_a, t_b in combinations(tokens, 2):
            if token_index[t_a] > token_index[t_b]:
                token0, token1 = t_a, t_b
            else:
                token0, token1 = t_b, t_a
            pairs.append((token0, token1))
    
    if start_from_bottom:
        pairs.sort(key=lambda p: token_index[p[0]], reverse=True)
    
    return pairs


def compute_lag1_stats(token0: str, token1: str, n_months: int = None, data_dir: str = None) -> dict:
    """Lightweight version: only lag-1 ACF + slope + classification (no bootstrap)."""
    if n_months is None:
        n_months = CONFIG['n_months']
    if data_dir is None:
        data_dir = CONFIG['data_dir']

    token0 = token0.lower()
    token1 = token1.lower()

    try:
        price0 = load_price(token0, data_dir)
        price1 = load_price(token1, data_dir)

        combined = pd.DataFrame({'price0': price0, 'price1': price1}).sort_index()
        combined = combined.resample('h').last()

        total_overlapping_hours = len(combined.dropna(how='any'))

        combined = combined.ffill()
        pair_price = combined['price1'] / combined['price0']

        end_date = pair_price.index.max()
        start_date = end_date - pd.DateOffset(months=n_months)
        historical = pair_price.loc[start_date:].dropna()

        current_price = float(historical.iloc[-1]) if len(historical) > 0 else np.nan
        lag1_acf = np.nan
        lag1_slope = np.nan
        classification = "INSUFFICIENT DATA"
        num_obs = len(historical)

        if num_obs < 48:
            classification = f"WARNING: Only {num_obs} observations"
        else:
            if (historical <= 0).any() or historical.std() < 1e-12:
                classification = "INVALID DATA"
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
                            except:
                                pass

                    # Classification (exactly matches your sb_tokens.py logic)
                    cfg = DEFAULT_CONFIG
                    if np.isnan(lag1_acf):
                        classification = "INVALID DATA"
                    elif lag1_acf < cfg['acf_strong_reversion_threshold']:
                        classification = "STRONG REVERSION"
                    elif lag1_acf < 0:
                        classification = "MILD REVERSION"
                    elif lag1_acf > cfg['acf_momentum_threshold']:
                        classification = "MOMENTUM"
                    else:
                        classification = "NEAR RANDOM WALK"

        return {
            'token0': token0.upper(),
            'token1': token1.upper(),
            'current_price': round(current_price, 8) if not np.isnan(current_price) else np.nan,
            'lag1_acf': round(lag1_acf, 6) if not np.isnan(lag1_acf) else np.nan,
            'lag1_slope': round(lag1_slope, 6) if not np.isnan(lag1_slope) else np.nan,
            'classification': classification,
            'num_observations': int(num_obs),
            'total_overlapping_hours': int(total_overlapping_hours),
        }

    except Exception as e:
        err = str(e)[:80]
        return {
            'token0': token0.upper(),
            'token1': token1.upper(),
            'current_price': np.nan,
            'lag1_acf': np.nan,
            'lag1_slope': np.nan,
            'classification': f"ERROR: {err}",
            'num_observations': 0,
            'total_overlapping_hours': 0,
        }


def main():
    tokens = load_tokens(CONFIG['tokens_file'])
    pairs = generate_pairs(
        tokens,
        CONFIG['allow_duplicates'],
        CONFIG['start_from_bottom']
    )
    
    print(f"\n🚀 Starting lightweight lag-1 ACF analysis of {len(pairs):,} pairs")
    print(f"   (n_months = {CONFIG['n_months']}, sorted by strongest reversion first)\n")
    
    results = []
    total = len(pairs)
    
    for idx, (token0, token1) in enumerate(pairs, 1):
        print(f"[{idx:3d}/{total}] {token0.upper():>8} / {token1.upper():<8} ", end="")
        
        res = compute_lag1_stats(token0, token1)
        results.append(res)
        
        if idx % 20 == 0 or idx == total:
            df = pd.DataFrame(results)
            df = df.sort_values(by='lag1_acf', ascending=True, na_position='last')
            df.to_csv(CONFIG['output_csv'], index=False)
            print(f"→ saved ({len(results)} rows)")
        else:
            print("✓")
    
    # Final save
    final_df = pd.DataFrame(results)
    final_df = final_df.sort_values(by='lag1_acf', ascending=True, na_position='last')
    final_df.to_csv(CONFIG['output_csv'], index=False)
    
    print(f"\n🎉 DONE! Full results saved to → {CONFIG['output_csv']}")
    print(f"   Total pairs analyzed: {len(results):,} / {total:,}")
    print(f"   Sorted by lag1_acf (STRONG REVERSION at the very top)")


if __name__ == "__main__":
    main()
