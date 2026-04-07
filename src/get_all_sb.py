#!/usr/bin/env python3
import pandas as pd
import numpy as np
from itertools import combinations
import sys
import time
from pathlib import Path

try:
    from sb_tokens import get_sb_analysis
except ImportError:
    print("❌ ERROR: sb_tokens.py not found in the current directory.")
    sys.exit(1)

# ==================== CONFIGURATION ====================
CONFIG = {
    'tokens_file': 'subjective_top_tokens.txt',
    'output_csv': 'sb_pair_analysis.csv',
    'allow_duplicates': False,
    'start_from_bottom': True,
    'n_months': 18,
    'horizon_hours': None,
    'n_boots': 5000,
    'data_dir': 'fetched_data',
    'seed': 42,
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

def main():
    tokens = load_tokens(CONFIG['tokens_file'])
    pairs = generate_pairs(
        tokens,
        CONFIG['allow_duplicates'],
        CONFIG['start_from_bottom']
    )
    
    print(f"\n🚀 Starting analysis of {len(pairs):,} pairs "
          f"(direction: {'both' if CONFIG['allow_duplicates'] else 'unique'})")
    print(f"Processing order: starting from bottom of list → working upwards")
    print(f"CSV will be sorted by lag1_acf (ascending) on every save\n")
    
    results = []
    total = len(pairs)
    
    for idx, (token0, token1) in enumerate(pairs, 1):
        print(f"[{idx:3d}/{total}] {token0.upper():>8} / {token1.upper():<8} ", end="")
        start_time = time.time()
        
        try:
            res = get_sb_analysis(
                token0=token0,
                token1=token1,
                n_months=CONFIG['n_months'],
                horizon_hours=CONFIG['horizon_hours'],
                n_boots=CONFIG['n_boots'],
                draw_charts=False,
                data_dir=CONFIG['data_dir'],
                seed=CONFIG['seed'],
            )
            
            row = {
                'token0': token0.upper(),
                'token1': token1.upper(),
                'current_price': round(res['current_price'], 8) if not np.isnan(res['current_price']) else np.nan,
                'high_conf_lower': round(res['high_conf_lower'], 6),
                'high_conf_upper': round(res['high_conf_upper'], 6),
                'typical_lower': round(res['typical_lower'], 6),
                'typical_upper': round(res['typical_upper'], 6),
                'median_max_dev': round(res['median_max_dev'], 6),
                'lag1_acf': round(res['lag1_acf'], 6) if not np.isnan(res['lag1_acf']) else np.nan,
                'lag1_slope': round(res['lag1_slope'], 6) if not np.isnan(res['lag1_slope']) else np.nan,
                'num_observations': res['num_observations'],
                'total_overlapping_hours': res.get('total_overlapping_hours', 0),
                'horizon_hours': res['horizon_hours'],
                'n_boots': res['n_boots'],
                'actual_coverage_pct': round(res['actual_coverage'], 1),
            }
            results.append(row)
            
            if idx % 10 == 0 or idx == total:
                df = pd.DataFrame(results)
                df = df.sort_values(by='lag1_acf', ascending=True, na_position='last')
                df.to_csv(CONFIG['output_csv'], index=False)
                print(f"→ saved ({len(results)} rows, sorted by lag1_acf)")
            else:
                print("✓")
                
        # ==================== NEW: ROBUST EXCEPTION HANDLING ====================
        except Exception as e:
            err_str = str(e)
            if CONFIG['skip_missing_data'] and (
                "FileNotFoundError" in str(type(e).__name__) or
                "SVD did not converge" in err_str or
                "LinAlgError" in err_str or
                "invalid price data" in err_str.lower()
            ):
                print("⚠️  skipped (missing or bad price data)")
            else:
                print(f"❌ ERROR: {e}")
        # =====================================================================
    
    final_df = pd.DataFrame(results)
    final_df = final_df.sort_values(by='lag1_acf', ascending=True, na_position='last')
    final_df.to_csv(CONFIG['output_csv'], index=False)
    
    print(f"\n🎉 DONE! Full results saved to → {CONFIG['output_csv']}")
    print(f"   Total pairs analyzed: {len(results):,} / {total:,}")
    print(f"   Sorted by lag1_acf (strongest reversion at the top)")

if __name__ == "__main__":
    main()
