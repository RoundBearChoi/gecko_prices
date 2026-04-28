#!/usr/bin/env python3
"""
Cryptocurrency 24h Price Change Analysis Script (pandas 3.x fixed)
Dynamic portfolio loading from tokens_list.json
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os
from pathlib import Path
from scipy.stats import gaussian_kde
import matplotlib.pyplot as plt
import pytz
import json

# ====================== CONFIG SECTION ======================
CONFIG = {
    "months_back": 12,
    "bootstrap_samples": 5000,         # Number of bootstrap resamples
    "kst_target_hour": 14,             # 2 PM KST (day end)
    "data_dir": "price_data",          # Folder containing the CSV files
    "histogram_bin_width": 1.0,        # For histogram mode
    "random_seed": 42,
    "save_plots": True,                # Change to False if you don't want PNGs
    "output_dir": "analysis_results",
}
# ===========================================================

np.random.seed(CONFIG["random_seed"])


def load_portfolio_tokens() -> list[str]:
    """Load token IDs from tokens_list.json that are flagged for portfolio inclusion."""
    # Try current working directory first, then script directory
    json_paths = [
        Path("tokens_list.json"),
        Path(__file__).parent / "tokens_list.json",
    ]
    
    json_path = None
    for path in json_paths:
        if path.exists():
            json_path = path
            break
    
    if not json_path:
        raise FileNotFoundError(f"❌ tokens_list.json not found. Looked in cwd and script directory.")

    print(f"📋 Loading portfolio tokens from {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        tokens = json.load(f)
    
    portfolio_ids = [
        token["id"] for token in tokens 
        if token.get("include_in_portfolio", False) is True
    ]
    
    print(f"    ✅ Found {len(portfolio_ids)} tokens to include: {portfolio_ids}")
    if not portfolio_ids:
        print("    ⚠️  No tokens have include_in_portfolio: true")
    
    return portfolio_ids


def load_data(coin_name: str) -> pd.DataFrame:
    """Load CSV with robust ISO8601 datetime parsing."""
    file_path = Path(CONFIG["data_dir"]) / f"{coin_name}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"❌ File not found: {file_path}")

    print(f"    Loading {coin_name} data from {file_path}...")

    df = pd.read_csv(file_path)
    df["datetime_utc"] = pd.to_datetime(df["datetime"], format='ISO8601', utc=True)
    kst_tz = pytz.timezone("Asia/Seoul")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert(kst_tz)

    df = df[["datetime_kst", "price_usd", "market_cap", "total_volume"]].set_index("datetime_kst").sort_index()
    print(f"    Loaded {len(df):,} rows | {df.index.min()} → {df.index.max()}")
    return df


def get_daily_closes(df: pd.DataFrame) -> pd.DataFrame:
    """Extract daily price closest to 2 PM KST (pandas 3.x safe)."""
    df = df.copy()
    df["date"] = df.index.date

    daily_prices = []
    for date, group in df.groupby("date"):
        if group.empty:
            continue

        target_naive = datetime.combine(date, datetime.min.time().replace(hour=CONFIG["kst_target_hour"]))
        target = pytz.timezone("Asia/Seoul").localize(target_naive)

        # FIXED: Use np.abs() instead of .abs() for Timedelta compatibility
        time_diffs = np.abs(group.index - target)
        closest_idx = time_diffs.argmin()
        closest_price = group.iloc[closest_idx]["price_usd"]

        daily_prices.append({"date": pd.Timestamp(date).date(), "price_usd": closest_price})

    daily_df = pd.DataFrame(daily_prices).set_index("date").sort_index()
    print(f"    Found {len(daily_df)} daily closes (closest to {CONFIG['kst_target_hour']}:00 KST)")
    return daily_df


def analyze_returns(daily_df: pd.DataFrame) -> tuple:
    """Filter to past N months and compute 24h % changes."""
    if len(daily_df) < 2:
        raise ValueError("Insufficient daily data.")

    end_date = pd.Timestamp(daily_df.index.max())
    start_date = end_date - pd.DateOffset(months=CONFIG["months_back"])

    historical = daily_df[(daily_df.index >= start_date.date()) & 
                         (daily_df.index <= end_date.date())].copy()

    historical["pct_change_24h"] = historical["price_usd"].pct_change() * 100
    returns = historical["pct_change_24h"].dropna()

    print(f"   → Using {len(returns)} daily 24h returns from {historical.index.min()} to {historical.index.max()}")
    return returns, historical


def bootstrap_distribution(returns: pd.Series) -> dict:
    """Bootstrap resampling + KDE mode for most likely change."""
    if len(returns) < 10:
        return {"error": "Too few historical returns for bootstrap"}

    boot_samples = np.random.choice(returns.values, 
                                    size=(CONFIG["bootstrap_samples"], len(returns)), 
                                    replace=True)

    boot_means = np.mean(boot_samples, axis=1)

    # KDE mode (best estimate of "most likely" 24h change)
    kde = gaussian_kde(returns)
    x_range = np.linspace(returns.min(), returns.max(), 2000)
    kde_mode = x_range[np.argmax(kde(x_range))]

    # Histogram mode
    bins = np.arange(returns.min() - CONFIG["histogram_bin_width"],
                     returns.max() + CONFIG["histogram_bin_width"],
                     CONFIG["histogram_bin_width"])
    hist, bin_edges = np.histogram(returns, bins=bins)
    hist_mode = bin_edges[np.argmax(hist)] + CONFIG["histogram_bin_width"] / 2

    return {
        "n_observations": len(returns),
        "historical_mean_%": float(returns.mean()),
        "historical_median_%": float(returns.median()),
        "historical_std_%": float(returns.std()),
        "historical_5th_pctile_%": float(returns.quantile(0.05)),
        "historical_95th_pctile_%": float(returns.quantile(0.95)),
        "bootstrap_mean_of_means_%": float(boot_means.mean()),
        "bootstrap_95_ci_low_%": float(np.percentile(boot_means, 2.5)),
        "bootstrap_95_ci_high_%": float(np.percentile(boot_means, 97.5)),
        "most_likely_kde_mode_%": float(kde_mode),          # ← Recommended "most likely"
        "most_likely_hist_mode_%": float(hist_mode),
    }


def main():
    os.makedirs(CONFIG["output_dir"], exist_ok=True)

    print("🚀 Starting 24h price change bootstrap analysis (KST 2 PM day end)\n")
    print(f"Config → {CONFIG['months_back']} months back | {CONFIG['bootstrap_samples']} bootstraps\n")

    coins = load_portfolio_tokens()

    for coin in coins:
        print(f"\nAnalyzing {coin}...")
        try:
            df = load_data(coin)
            daily_df = get_daily_closes(df)
            returns, historical_df = analyze_returns(daily_df)

            stats = bootstrap_distribution(returns)

            if "error" in stats:
                print(f"   ❌ {stats['error']}")
                continue

            print("\n📊 RESULTS (24h % change at 2 PM KST):")
            for key, value in stats.items():
                if isinstance(value, float):
                    print(f"   {key.replace('_', ' ').title():<32}: {value:8.2f}%")
                else:
                    print(f"   {key.replace('_', ' ').title():<32}: {value}")

            # Save data
            historical_df.to_csv(Path(CONFIG["output_dir"]) / f"{coin}_daily_closes.csv")

            if CONFIG["save_plots"]:
                plt.figure(figsize=(11, 6))
                plt.hist(returns, bins=60, alpha=0.75, color='skyblue', edgecolor='black')
                plt.axvline(stats["most_likely_kde_mode_%"], color='red', linestyle='--', linewidth=2,
                            label=f'Most Likely (KDE): {stats["most_likely_kde_mode_%"]:.2f}%')
                plt.title(f"{coin} — 24h % Change Distribution\n(Past {CONFIG['months_back']} months)")
                plt.xlabel("24h Price Change (%)")
                plt.ylabel("Frequency")
                plt.legend()
                plt.grid(True, alpha=0.3)
                plot_path = Path(CONFIG["output_dir"]) / f"{coin}_24h_distribution.png"
                plt.savefig(plot_path, dpi=200, bbox_inches='tight')
                plt.close()
                print(f"\nPlot saved → {plot_path}")

            print(f"Results saved to ./{CONFIG['output_dir']}/ for {coin}")

        except Exception as e:
            print(f"   ❌ Error processing {coin}: {e}\n")

    print("\n🎉 Analysis completed for all portfolio tokens!")


if __name__ == "__main__":
    main()
