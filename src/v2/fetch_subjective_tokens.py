import requests
import pandas as pd
import time
from typing import List, Dict
import sys

# ==================== CONFIG SECTION ====================
CONFIG = {
    'base_url': 'https://api.coingecko.com/api/v3',
    'vs_currency': 'usd',
    'locale': 'en',
    
    # Your list now contains CoinGecko IDs (one ID per line, e.g. bitcoin, ethereum, pepe)
    'subjective_list_file': 'subjective_top_tokens_id.txt',
    
    # Output filename (unchanged)
    'output_csv': 'subjective_tokens_ranked.csv',
}
# =======================================================

def load_subjective_ids(config: Dict = CONFIG) -> List[str]:
    """Load CoinGecko IDs from your subjective list (one ID per line). Supports comments (#)."""
    try:
        with open(config['subjective_list_file'], 'r', encoding='utf-8') as f:
            ids = [line.strip().lower() for line in f 
                   if line.strip() and not line.strip().startswith('#')]
        # Remove duplicates while preserving order
        ids = list(dict.fromkeys(ids))
        print(f"✅ Loaded {len(ids):,} CoinGecko IDs from {config['subjective_list_file']}")
        return ids
    except FileNotFoundError:
        print(f"❌ Subjective list file '{config['subjective_list_file']}' not found!")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error reading subjective list: {e}")
        sys.exit(1)


def fetch_coingecko_market_data(ids: List[str], config: Dict = CONFIG) -> List[Dict]:
    """Fetch market data for your specific CoinGecko IDs (free tier only)."""
    if not ids:
        return []
    
    print(f"🔍 Fetching market data for {len(ids)} tokens (free tier)...")
    
    endpoint = f"{config['base_url']}/coins/markets"
    params = {
        'vs_currency': config['vs_currency'],
        'ids': ','.join(ids),
        'locale': config['locale'],
    }
    
    try:
        response = requests.get(endpoint, params=params)
        
        if response.status_code == 429:
            print("⚠️ Rate limit hit. Waiting 60 seconds...")
            time.sleep(60)
            response = requests.get(endpoint, params=params)
        
        response.raise_for_status()
        data = response.json()
        print(f"✅ Successfully fetched market data for {len(data):,} tokens.")
        return data
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to fetch market data: {e}")
        sys.exit(1)


def to_dataframe(coins: List[Dict]) -> pd.DataFrame:
    """Convert to clean DataFrame ordered by global CoinGecko rank (no subjective rank)."""
    if not coins:
        return pd.DataFrame()
    
    df = pd.DataFrame(coins)
    
    # Select and rename exactly what you need
    df = df[[
        'market_cap_rank',      # global CoinGecko rank
        'symbol',
        'id',
        'name',                 # added for clarity
        'current_price',
        'total_volume',
        'market_cap',
        'price_change_percentage_24h'
    ]].copy()
    
    df = df.rename(columns={
        'market_cap_rank': 'global_rank',
        'current_price': 'price',
        'total_volume': '24h_volume',
        'price_change_percentage_24h': '24h_change_%'
    })
    
    # Ensure numeric types for easy Excel sorting/filtering
    numeric_cols = ['price', '24h_volume', 'market_cap', '24h_change_%', 'global_rank']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Sort by global_rank (ascending = best global rank first)
    df = df.sort_values('global_rank', ascending=True).reset_index(drop=True)
    
    return df


if __name__ == "__main__":
    print("\n=== Subjective Tokens Ordered by Global Rank (CoinGecko) ===")
    print("Reads your ID list → fetches data → sorts by global rank.\n")
    
    # 1. Load your list of CoinGecko IDs
    subjective_ids = load_subjective_ids()
    
    if not subjective_ids:
        print("❌ No IDs found in the list.")
        sys.exit(1)
    
    # 2. Fetch fresh market data
    coins_data = fetch_coingecko_market_data(subjective_ids)
    
    # 3. Create DataFrame ordered by global rank
    df = to_dataframe(coins_data)
    
    if df.empty:
        print("❌ No data returned from CoinGecko.")
        sys.exit(1)
    
    # 4. Summary report
    print(f"\n🔍 Processing complete:")
    print(f"   • IDs in your list          : {len(subjective_ids):,}")
    print(f"   • Successfully fetched      : {len(df):,}")
    
    # 5. Preview
    print("\n=== Preview — Ordered by Global Rank (first 15 rows) ===")
    print(df.head(15).to_string(index=False))
    
    # 6. Save the single output CSV
    df.to_csv(CONFIG['output_csv'], index=False)
    
    print(f"\n💾 File saved: {CONFIG['output_csv']}")
    print("\n✅ Done! Open the CSV in Excel/Google Sheets.")
    print("   The list is now sorted purely by global_rank (CoinGecko's official ranking).")
    print("   Columns include: global_rank, symbol, id, name, price, 24h_change_%, etc.")
