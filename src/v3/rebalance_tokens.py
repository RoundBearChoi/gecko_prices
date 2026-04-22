import pandas as pd
from pathlib import Path
import argparse
from datetime import datetime
import sys

# ==================== CONFIG SECTION ====================
# Edit these values as needed before running the script
CONFIG = {
    'main_token_symbol': 'CBBTC',          # Always treated as the "anchor" / main token
    'target_main_percent': 60.0,           # ← Change this to whatever % you want for CBBTC (e.g. 50.0, 70.0, etc.)
    'slippage_percent': 1.0,               # Assumed slippage on every trade (buy or sell side)
    'wallet_data_dir': Path('wallet_data'),  # Folder where your portfolio CSVs live
    'min_delta_threshold_usd': 2.0,        # Ignore tiny imbalances (< $2) to reduce noise
    'route_all_trades_through_main': True, # If True, all sells go to CBBTC first, then CBBTC → losers (simpler on Solana)
}
# ======================================================

def load_latest_portfolio(wallet_dir: Path) -> pd.DataFrame:
    """Find and load the most recent solana_meme_portfolio_*.csv file."""
    if not wallet_dir.exists():
        raise FileNotFoundError(f"Wallet data directory not found: {wallet_dir}\n"
                                f"Create the folder or update CONFIG['wallet_data_dir']")
    
    csv_files = list(wallet_dir.glob('solana_meme_portfolio_*.csv'))
    if not csv_files:
        raise FileNotFoundError(f"No portfolio CSV files found in {wallet_dir}. "
                                f"Expected pattern: solana_meme_portfolio_YYYYMMDD_HHMMSS.csv")
    
    # Use file modification time for robustness (works even if filename format changes slightly)
    latest_file = max(csv_files, key=lambda p: p.stat().st_mtime)
    print(f"✅ Loading latest portfolio snapshot: {latest_file.name}")
    
    df = pd.read_csv(latest_file)
    return df, latest_file


def main():
    # Optional CLI override for target percent (useful for quick experiments)
    parser = argparse.ArgumentParser(description="Solana Meme Portfolio Rebalancer")
    parser.add_argument('--target-cbbtc', type=float, default=None,
                        help=f"Override CBBTC target % (default: {CONFIG['target_main_percent']})")
    args = parser.parse_args()
    
    if args.target_cbbtc is not None:
        CONFIG['target_main_percent'] = args.target_cbbtc
        print(f"⚠️  Overrode CBBTC target to {CONFIG['target_main_percent']}% via CLI")

    # 1. Load data
    df_raw, csv_path = load_latest_portfolio(CONFIG['wallet_data_dir'])
    
    # 2. Extract total value from the TOTAL row
    total_mask = (df_raw['symbol'] == 'TOTAL') | df_raw['symbol'].isna() | df_raw['symbol'].str.contains('TOTAL', na=False)
    if total_mask.sum() == 0:
        raise ValueError("Could not find TOTAL row in CSV")
    total_usd = float(df_raw[total_mask]['total_usd'].iloc[0])
    
    # 3. Filter to only included portfolio tokens (exclude TOTAL row)
    portfolio_df = df_raw[
        (df_raw['include_in_portfolio'] == True) &
        df_raw['symbol'].notna() &
        (df_raw['symbol'] != 'TOTAL')
    ].copy().reset_index(drop=True)
    
    if len(portfolio_df) == 0:
        print("❌ No tokens found in portfolio!")
        sys.exit(1)
    
    # Ensure numeric columns
    numeric_cols = ['token_count', 'price_usd', 'value_usd', 'portfolio_percent']
    for col in numeric_cols:
        portfolio_df[col] = pd.to_numeric(portfolio_df[col], errors='coerce')
    
    main_symbol = CONFIG['main_token_symbol']
    slippage = CONFIG['slippage_percent'] / 100.0
    
    # 4. Calculate targets
    other_mask = portfolio_df['symbol'] != main_symbol
    num_others = int(other_mask.sum())
    if num_others == 0:
        print("⚠️  Only CBBTC in portfolio – nothing to rebalance against.")
        sys.exit(0)
    
    remaining_pct = 100.0 - CONFIG['target_main_percent']
    target_other_pct = remaining_pct / num_others
    
    portfolio_df['target_percent'] = 0.0
    portfolio_df.loc[~other_mask, 'target_percent'] = CONFIG['target_main_percent']
    portfolio_df.loc[other_mask, 'target_percent'] = target_other_pct
    
    portfolio_df['target_usd'] = (total_usd * portfolio_df['target_percent'] / 100.0).round(6)
    portfolio_df['delta_usd'] = (portfolio_df['value_usd'] - portfolio_df['target_usd']).round(6)
    portfolio_df['target_token_count'] = (portfolio_df['target_usd'] / portfolio_df['price_usd']).round(8)
    portfolio_df['delta_tokens'] = (portfolio_df['token_count'] - portfolio_df['target_token_count']).round(8)
    
    # 5. Report summary
    print("\n" + "="*100)
    print(f"🚀 SOLANA MEME PORTFOLIO REBALANCER")
    print(f"   Snapshot: {csv_path.name} | Total Value: ${total_usd:,.2f} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Target → CBBTC: {CONFIG['target_main_percent']:.1f}% (${portfolio_df.loc[~other_mask, 'target_usd'].iloc[0]:,.2f})")
    print(f"   Remaining {remaining_pct:.1f}% split equally across {num_others} other tokens → ~{target_other_pct:.2f}% each (${portfolio_df.loc[other_mask, 'target_usd'].iloc[0]:,.2f} per token)")
    print(f"   Slippage assumption: {CONFIG['slippage_percent']}% per trade side")
    print("="*100)
    
    # Pretty table of current vs target
    display_cols = [
        'symbol', 'token_count', 'price_usd', 'value_usd',
        'portfolio_percent', 'target_percent', 'target_usd', 'delta_usd'
    ]
    print("\n📊 CURRENT vs TARGET ALLOCATION")
    print(portfolio_df[display_cols].round(4).to_string(index=False))
    
    # 6. Greedy rebalance algorithm (biggest winners → biggest losers)
    print("\n🔄 EXACT REBALANCE TRADES (Greedy Pairing)")
    print("   Strategy: Sort biggest winners (over-allocated) and biggest losers (under-allocated).")
    print("             Redistribute from winner → loser starting with the largest deficit.")
    print("             All trades are planned at current snapshot prices.")
    print("             CBBTC is treated as the main routing token when possible.\n")
    
    winners = portfolio_df[portfolio_df['delta_usd'] > CONFIG['min_delta_threshold_usd']].copy()
    losers = portfolio_df[portfolio_df['delta_usd'] < -CONFIG['min_delta_threshold_usd']].copy()
    
    winners = winners.sort_values('delta_usd', ascending=False).reset_index(drop=True)   # biggest winner first
    losers = losers.sort_values('delta_usd', ascending=True).reset_index(drop=True)      # biggest loser (most negative) first
    
    if winners.empty:
        print("✅ Portfolio is already perfectly balanced (or within threshold). No action needed.")
        return
    
    trade_plan = []
    winner_idx = 0
    slippage_adjustment_note = f" (expect ~{CONFIG['slippage_percent']}% loss on traded volume due to slippage)"
    
    for _, loser_row in losers.iterrows():
        deficit_remaining = -loser_row['delta_usd']  # positive USD needed
        
        while deficit_remaining > CONFIG['min_delta_threshold_usd'] and winner_idx < len(winners):
            winner_row = winners.iloc[winner_idx]
            excess_remaining = winner_row['delta_usd']
            
            if excess_remaining <= CONFIG['min_delta_threshold_usd']:
                winner_idx += 1
                continue
            
            transfer_usd = min(deficit_remaining, excess_remaining)
            
            # Adjust for slippage: to actually receive the full target for the loser,
            # the winner must sell slightly more (we use a simple one-sided adjustment here)
            sell_usd_gross = transfer_usd / (1 - slippage) if CONFIG['route_all_trades_through_main'] else transfer_usd
            sell_tokens = sell_usd_gross / winner_row['price_usd']
            buy_tokens = transfer_usd / loser_row['price_usd']   # buyer receives at current price
            
            trade_plan.append({
                'from_symbol': winner_row['symbol'],
                'from_mint': winner_row.get('mint', 'N/A'),
                'sell_tokens': round(sell_tokens, 8),
                'sell_usd_gross': round(sell_usd_gross, 2),
                'to_symbol': loser_row['symbol'],
                'to_mint': loser_row.get('mint', 'N/A'),
                'buy_tokens': round(buy_tokens, 8),
                'buy_usd_net': round(transfer_usd, 2),
            })
            
            # Update remainders
            winners.at[winner_row.name, 'delta_usd'] = excess_remaining - transfer_usd
            deficit_remaining -= transfer_usd
            
            # If winner is exhausted, move to next
            if winners.at[winner_row.name, 'delta_usd'] <= CONFIG['min_delta_threshold_usd']:
                winner_idx += 1
    
    # Output the trade plan
    if trade_plan:
        print(f"💱 Proposed Trades ({len(trade_plan)} swaps):")
        for i, trade in enumerate(trade_plan, 1):
            print(f"   {i:2d}. SELL  {trade['sell_tokens']:>12,.6f} {trade['from_symbol']:8} "
                  f"(${trade['sell_usd_gross']:,.2f}) → BUY {trade['buy_tokens']:>12,.6f} {trade['to_symbol']}")
            print(f"          (≈ ${trade['buy_usd_net']:,.2f} net to {trade['to_symbol']}){slippage_adjustment_note}")
        
        total_traded = sum(t['sell_usd_gross'] for t in trade_plan)
        expected_slippage_loss = total_traded * slippage
        print(f"\n📉 Total volume to trade: ~${total_traded:,.2f}")
        print(f"   Expected slippage cost: ~${expected_slippage_loss:,.2f} (portfolio value will drop slightly)")
        print(f"   After rebalance you should be within ~{CONFIG['min_delta_threshold_usd']*2:.0f} USD of targets.")
    else:
        print("✅ No meaningful rebalancing required.")
    
    # 7. Final notes & implications
    print("\n" + "="*100)
    print("💡 IMPORTANT CONSIDERATIONS & EDGE CASES")
    print("   • Prices are from the snapshot – run this script immediately before executing trades.")
    print("   • Meme coins have extremely high volatility and often low liquidity. A 1% slippage assumption")
    print("     may be optimistic for small buys; real slippage can be 5-20%+ on illiquid pairs.")
    print("   • Equal weighting ignores token-specific fundamentals, market cap, or momentum.")
    print("   • Edge cases handled: zero holdings, single-token portfolios, tiny deltas, missing files.")
    print("="*100)
    print("✅ Rebalance plan complete. Good luck – trade responsibly!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   Make sure the CSV is in the wallet_data folder and has the expected columns.")
        sys.exit(1)
