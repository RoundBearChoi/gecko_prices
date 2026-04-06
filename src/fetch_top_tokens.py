import requests
import pandas as pd
import time
import json
from typing import List, Dict
import sys
import termios
import tty

# ==================== CONFIG SECTION ====================
CONFIG = {
    'base_url': 'https://api.coingecko.com/api/v3',  # free tier default
    'vs_currency': 'usd',
    'order': 'market_cap_desc',
    'per_page': 250,                         # max allowed by API
    'pages': 3,                              # e.g. 1 = homepage view, 10 = top 2,500 tokens
    'locale': 'en',
    # Optional filters (set to None to disable)
    'category': None,                        # e.g. 'defi', 'meme-token', 'layer-1'
    'ids': None,                             # e.g. 'bitcoin,ethereum,solana'
    
    # ==================== OUTPUT FILENAMES ====================
    'output_csv': 'top_tokens_by_market_cap.csv',           # unfiltered version (original behavior)
    'output_filtered_csv': 'top_tokens_by_market_cap_filtered.csv',  # ← new file you requested
    'blacklist_file': 'blacklisted_tokens.json',            # path to your blacklist
}
# =======================================================

def get_masked_input(prompt: str = "") -> str:
    """Linux-only masked input (now using setcbreak like your history script)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)                    # ← more stable than setraw
        print(prompt, end='', flush=True)
        password = ""
        while True:
            ch = sys.stdin.read(1)
            if ch in ('\n', '\r'):
                print()                      # ← forces clean new line (no indent)
                break
            elif ch == '\x7f':               # Backspace
                if password:
                    password = password[:-1]
                    print('\b \b', end='', flush=True)
            elif ch == '\x03':               # Ctrl+C
                raise KeyboardInterrupt
            else:
                password += ch
                print('*', end='', flush=True)
        return password.strip()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def fetch_coingecko_market_data(config: Dict = CONFIG, api_key: str = None) -> List[Dict]:
    """Fetch exactly like CoinGecko homepage — market-cap sorted.
    Uses Pro API (different base URL + header) if key is provided, otherwise free tier."""
    all_coins: List[Dict] = []
    
    if api_key:
        base_url = 'https://pro-api.coingecko.com/api/v3'
        headers = {'x-cg-pro-api-key': api_key}
        tier = "Pro"
        sleep_time = 0.3   # Pro allows faster requests
    else:
        base_url = config['base_url']
        headers = None
        tier = "Free"
        sleep_time = 1.2   # polite delay for free tier
    
    endpoint = f"{base_url}/coins/markets"
    print(f"🔑 Using {tier} tier")
    
    for page in range(1, config['pages'] + 1):
        params = {
            'vs_currency': config['vs_currency'],
            'order': config['order'],
            'per_page': config['per_page'],
            'page': page,
            'locale': config['locale']
        }
        
        if config.get('ids'):
            params['ids'] = config['ids']
        if config.get('category'):
            params['category'] = config['category']
            
        print(f"Fetching page {page}/{config['pages']}...")
        
        response = requests.get(endpoint, params=params, headers=headers)
        
        if response.status_code == 429:
            print("⚠️ Rate limit hit. Waiting 60 seconds...")
            time.sleep(60)
            continue
        response.raise_for_status()
        
        data = response.json()
        all_coins.extend(data)
        
        if page < config['pages']:
            time.sleep(sleep_time)
    
    print(f"✅ Fetched {len(all_coins):,} tokens with official ranking ({tier} tier).")
    return all_coins


def to_dataframe(coins: List[Dict]) -> pd.DataFrame:
    """Return ONLY the columns you requested, with nice names."""
    df = pd.DataFrame(coins)
    
    # Keep and rename exactly what you want
    df = df[[
        'market_cap_rank',
        'symbol',
        'id',
        'current_price',
        'total_volume',
        'market_cap'
    ]].copy()
    
    df = df.rename(columns={
        'market_cap_rank': 'ranking#',
        'current_price': 'price',
        'total_volume': '24h_volume',
        'market_cap': 'market_cap'
    })
    
    # Make numbers numeric (for easy sorting/filtering in Excel)
    numeric_cols = ['price', '24h_volume', 'market_cap']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Ensure it's still sorted by official rank
    df = df.sort_values('ranking#')
    
    return df


def load_blacklist(config: Dict = CONFIG) -> set:
    """Load blacklisted_tokens.json and return a set of IDs for fast lookup."""
    try:
        with open(config['blacklist_file'], 'r', encoding='utf-8') as f:
            blacklist = json.load(f)
        
        # Only include entries that actually have an 'id'
        blacklisted_ids = {item.get('id') for item in blacklist if item.get('id')}
        
        print(f"✅ Loaded {len(blacklisted_ids):,} blacklisted tokens from {config['blacklist_file']}")
        return blacklisted_ids
    
    except FileNotFoundError:
        print(f"⚠️  Blacklist file '{config['blacklist_file']}' not found. No filtering will be applied.")
        return set()
    except json.JSONDecodeError:
        print(f"⚠️  Could not parse {config['blacklist_file']}. No filtering will be applied.")
        return set()


if __name__ == "__main__":
    # 0. Prompt for API key FIRST (as requested) with * masking
    print("\n=== CoinGecko Top Tokens Fetcher ===")
    print("Supports Pro API for higher rate limits.\n")
    
    api_key_input = get_masked_input(
        "Enter your CoinGecko API key (or press Enter for free tier): "
    )
    
    if api_key_input:
        # Minimal, secure confirmation — only show "CG-" prefix, nothing more
        print("✅ Using API key: CG-*******************")
        api_key = api_key_input
    else:
        print("✅ No API key provided — using free tier")
        api_key = None

    # 1. Fetch fresh data from CoinGecko
    coins_data = fetch_coingecko_market_data(api_key=api_key)
    df = to_dataframe(coins_data)
    
    # 2. Load blacklist and create filtered version
    blacklisted_ids = load_blacklist()
    df_filtered = df[~df['id'].isin(blacklisted_ids)].copy()
    
    # 3. Report what happened (super useful for debugging / transparency)
    removed_count = len(df) - len(df_filtered)
    print(f"\n🔍 Filtering complete:")
    print(f"   • Original tokens : {len(df):,}")
    print(f"   • Blacklisted removed : {removed_count:,}")
    print(f"   • Remaining tokens  : {len(df_filtered):,}")
    
    # 4. Preview both versions
    print("\n=== Preview UNFILTERED (first 10 rows) ===")
    print(df.head(10).to_string(index=False))
    
    print(f"\n=== Preview FILTERED (first 10 rows) ===")
    print(df_filtered.head(10).to_string(index=False))
    
    # 5. Save both files (exactly the names from CONFIG)
    df.to_csv(CONFIG['output_csv'], index=False)
    df_filtered.to_csv(CONFIG['output_filtered_csv'], index=False)
    
    print(f"\n💾 Files saved:")
    print(f"   • {CONFIG['output_csv']}")
    print(f"   • {CONFIG['output_filtered_csv']}")
    
    print("\n✅ Done! Both CSVs are ready to open in Excel, Google Sheets, or load with pandas.")
