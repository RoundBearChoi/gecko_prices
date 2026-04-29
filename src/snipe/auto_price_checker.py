import os
import glob
import csv
import time
import sys
import requests
import getpass
import subprocess
from datetime import datetime
from decimal import Decimal, getcontext

# ==================== CONFIG SECTION ====================
UPDATE_INTERVAL_MINUTES = 4
BAR_WIDTH = 50
CLEAR_SCREEN_ON_UPDATE = True        # Linux-optimized: clears terminal for a clean dashboard each cycle
USE_COLORS = True                    # Enable ANSI colors (for Linux terminals)

# Sound alert configuration
PRICE_CHANGE_THRESHOLD_PERCENT = 2.0  # absolute %
SOUND_FILE = "kim_dust.mp3"           # Sound file located in the same folder as this script

# Telegram Bot configuration (loaded from environment variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# =======================================================

# ANSI color codes (Linux terminals love these)
COLORS = {
    'green': '\033[92m',
    'red': '\033[91m',
    'yellow': '\033[93m',
    'blue': '\033[94m',
    'reset': '\033[0m',
    'bold': '\033[1m'
}

# Set high precision once for all Decimal operations
getcontext().prec = 50

def get_csv_files():
    """Auto-discover all files matching the exact pattern solana_portfolio_{tokenid}_usdc.csv"""
    return glob.glob("solana_portfolio_*_usdc.csv")

def extract_token_id(filename):
    """Extract token_id EXACTLY as it appears in the filename (no case changes)."""
    base = os.path.basename(filename)
    prefix = "solana_portfolio_"
    suffix = "_usdc.csv"
    if base.startswith(prefix) and base.endswith(suffix):
        return base[len(prefix):-len(suffix)]
    return None

def get_latest_token_price(filename):
    """Read ONLY the very last row of the CSV and return token_price_usd as Decimal (exact)."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            last_row = None
            for row in reader:
                last_row = row
            if last_row and 'token_price_usd' in last_row:
                price_str = last_row['token_price_usd'].strip()
                if price_str:
                    return Decimal(price_str)
    except Exception as e:
        print(f"⚠️  Error reading last price from {filename}: {e}")
    return None

def fetch_current_prices(token_ids, api_key):
    """Fetch current USD prices with maximum precision — returns Decimal values."""
    if not token_ids:
        return {}
    
    base_url = "https://pro-api.coingecko.com/api/v3" if api_key else "https://api.coingecko.com/api/v3"
    ids_str = ','.join(token_ids)
    url = f"{base_url}/simple/price"
    params = {'ids': ids_str, 'vs_currencies': 'usd', 'precision': 'full'}
    
    headers = {}
    if api_key:
        headers["x-cg-pro-api-key"] = api_key
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json(parse_float=Decimal)
        prices = {}
        for tid in token_ids:
            usd_price = data.get(tid, {}).get('usd')
            prices[tid] = usd_price if usd_price is not None else None
        print(f"   🔍 Fetched {sum(1 for p in prices.values() if p is not None)}/{len(token_ids)} current prices")
        return prices
    except Exception as e:
        print(f"⚠️  CoinGecko error: {e}")
        return {}

def send_telegram_message(text):
    """Send any message to Telegram (used for startup and alerts)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("   📨 Telegram message sent successfully")
            return True
        else:
            print(f"   ⚠️  Telegram API error: {response.status_code}")
            return False
    except Exception as e:
        print(f"   ⚠️  Failed to send Telegram message: {e}")
        return False

def send_startup_message(token_count):
    """Send one-time startup confirmation to Telegram."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"✅ <b>Solana Portfolio Monitor started successfully</b>\n\n"
    message += f"📊 Monitoring <b>{token_count}</b> token{'s' if token_count != 1 else ''}\n"
    message += f"🔊 Sound alerts enabled (> {PRICE_CHANGE_THRESHOLD_PERCENT}% moves)\n"
    message += f"📨 Telegram alerts enabled\n"
    message += f"🕒 Time: {timestamp} KST\n\n"
    message += "✅ Ready to send price alerts!"
    send_telegram_message(message)

def send_telegram_alert(triggered_moves, timestamp):
    """Send one Telegram message per sound alert with full details."""
    if not triggered_moves:
        return
    message = f"🚨 <b>Solana Portfolio Price Alert</b>\n\n"
    message += f"Significant price movement (> {PRICE_CHANGE_THRESHOLD_PERCENT}%) detected!\n\n"
    for tid, delta_pct in triggered_moves:
        emoji = "📈" if delta_pct >= 0 else "📉"
        message += f"{emoji} <b>{tid}</b>: {delta_pct:+.4f}%\n"
    message += f"\n🕒 <b>Time:</b> {timestamp} KST"
    send_telegram_message(message)

def play_alert_sound(triggered_moves, timestamp):
    """Play alert using native Linux audio tools + send Telegram notification."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        sound_path = os.path.join(script_dir, SOUND_FILE)
        
        # Print clear alert with token details
        print(f"\n{COLORS['yellow']}🔊  ALERT SOUND: Significant price movement (> {PRICE_CHANGE_THRESHOLD_PERCENT}%) detected!{COLORS['reset']}")
        for tid, delta_pct in triggered_moves:
            color = COLORS['green'] if delta_pct >= 0 else COLORS['red']
            print(f"   {color}• {tid:<12} {delta_pct:+.4f}%{COLORS['reset']}")
        
        # Try to play sound (non-blocking)
        if os.path.exists(sound_path):
            player_commands = [
                ['paplay', sound_path],
                ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', sound_path],
                ['mpg123', '--quiet', sound_path],
                ['mpv', '--no-terminal', '--really-quiet', sound_path],
            ]
            for cmd in player_commands:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"   🎵 Playing {SOUND_FILE} using {cmd[0]}...")
                    send_telegram_alert(triggered_moves, timestamp)
                    return
                except FileNotFoundError:
                    continue
            print("   ⚠️  No audio player found. Recommended: sudo apt install ffmpeg")
        else:
            print(f"⚠️  Sound file not found: {sound_path}")
        
        # Still send Telegram even if sound fails
        send_telegram_alert(triggered_moves, timestamp)
        
    except Exception as e:
        print(f"⚠️  Error trying to play sound: {e}")
        send_telegram_alert(triggered_moves, timestamp)

def print_status(last_prices, current_prices, token_ids, timestamp, api_key_used):
    """Clean table with fixed delta column — all math uses full-precision Decimal."""
    if CLEAR_SCREEN_ON_UPDATE:
        os.system('clear')
    
    print("\n" + "=" * 100)
    pro_status = f" {COLORS['blue']}🟣 Pro API{COLORS['reset']}" if api_key_used else " (free tier)"
    print(f"Solana Portfolio Price Monitor — {timestamp} KST{pro_status}")
    print("=" * 100)
    print(f"{'Token ID':<25} {'Last Recorded (USD)':<20} {'Current Price (USD)':<20} {'Δ %':<15}")
    print("-" * 100)
    
    triggered_moves = []
    
    for tid in sorted(token_ids):
        last_p = last_prices.get(tid)
        curr_p = current_prices.get(tid)
        
        if last_p is None:
            print(f"{tid:<25} {'(CSV read error)':<20} {'N/A':<20} {'N/A':<15}")
            continue
        if curr_p is None or curr_p <= Decimal('0'):
            print(f"{tid:<25} ${last_p:<18.8f} {'(API error)':<20} {'N/A':<15}")
            continue
        
        delta_pct = ((curr_p - last_p) / last_p) * Decimal('100')
        
        if abs(delta_pct) >= Decimal(str(PRICE_CHANGE_THRESHOLD_PERCENT)):
            triggered_moves.append((tid, delta_pct))
        
        delta_str = f"{delta_pct:+.4f}%"
        indicator = "🟢" if delta_pct >= 0 else "🔴"
        
        print(f"{tid:<25} ${last_p:<18.8f} ${curr_p:<18.8f} ", end='')
        
        if USE_COLORS:
            color = COLORS['green'] if delta_pct >= 0 else COLORS['red']
            print(f"{color}{indicator} {delta_str}{COLORS['reset']}")
        else:
            print(f"{indicator} {delta_str}")
    
    print("=" * 100)
    count = len(token_ids)
    print(f"Monitoring {count} token{'s' if count != 1 else ''} • Sound alert >{PRICE_CHANGE_THRESHOLD_PERCENT}% • Next update in {UPDATE_INTERVAL_MINUTES} minutes")
    
    # Play sound alert + Telegram (one message per alert cycle)
    if triggered_moves:
        play_alert_sound(triggered_moves, timestamp)

def countdown_timer(seconds):
    """Live ticking timer + progress bar."""
    for remaining in range(seconds, 0, -1):
        mins, secs = divmod(remaining, 60)
        progress = (seconds - remaining) / seconds
        filled = int(BAR_WIDTH * progress)
        bar = '█' * filled + '░' * (BAR_WIDTH - filled)
        
        timer_line = f"\rNext update in {mins:02d}:{secs:02d} [{bar}] {progress*100:3.0f}%"
        sys.stdout.write(timer_line)
        sys.stdout.flush()
        time.sleep(1)
    
    sys.stdout.write("\r" + " " * (BAR_WIDTH + 60) + "\n")
    sys.stdout.flush()
    print("🔄 Fetching latest prices from CoinGecko...")

def main():
    """Main monitoring loop."""
    print(f"{COLORS['bold']}Starting Solana Portfolio Monitor (Linux Optimized){COLORS['reset']}")
    print(f"   • Looking for files: solana_portfolio_*_usdc.csv")
    print(f"   • Update frequency: every {UPDATE_INTERVAL_MINUTES} minutes")
    print(f"   • Telegram alerts: {'ENABLED' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else 'disabled (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars)'}")
    print(f"   • Press Ctrl+C to stop\n")
    
    api_key = os.getenv("COINGECKO_PRO_API_KEY")
    if not api_key:
        try:
            print("🔑 CoinGecko Pro API Key Setup")
            api_key = getpass.getpass("   Enter your CoinGecko Pro API key (hidden): ")
            if api_key.strip():
                print(f"   ✅ Pro API key accepted")
            else:
                print("   ⚠️  No key entered → using free tier")
                api_key = None
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            sys.exit(0)
    
    api_key_used = bool(api_key)
    
    # Discover tokens first so we can send accurate startup message
    csv_files = get_csv_files()
    token_ids = [extract_token_id(f) for f in csv_files if extract_token_id(f)]
    
    # Send startup Telegram message (only once)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_startup_message(len(token_ids))
    
    while True:
        csv_files = get_csv_files()
        if not csv_files:
            print("⚠️  No matching CSV files found!")
            time.sleep(10)
            continue
        
        token_ids = []
        last_prices = {}
        for file_path in csv_files:
            tid = extract_token_id(file_path)
            if tid:
                token_ids.append(tid)
                last_p = get_latest_token_price(file_path)
                if last_p is not None:
                    last_prices[tid] = last_p
        
        if not token_ids:
            print("⚠️  No valid token_ids found.")
            time.sleep(10)
            continue
        
        current_prices = fetch_current_prices(token_ids, api_key)
        
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print_status(last_prices, current_prices, token_ids, now_str, api_key_used)
        
        update_seconds = UPDATE_INTERVAL_MINUTES * 60
        countdown_timer(update_seconds)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{COLORS['yellow']}Monitor stopped by user. Goodbye!{COLORS['reset']}")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print("Tip: pip install requests if missing")
