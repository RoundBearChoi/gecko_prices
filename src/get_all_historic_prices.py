#!/usr/bin/env python3
"""
fetch_subjective_top_tokens_price_history.py

Purpose:
    Reads a subjective list of tokens (one symbol or coin_id per line in a text file)
    and uses the exact same logic from fetch_gecko_price_history.py to download
    hourly USD price history for ALL of them.

Key features:
    - Dedicated CONFIG section (easy to customize file name, months, force-fresh, etc.)
    - Reuses every function and chunking/saving logic from your existing script
      → no code duplication
    - Clean token loading (skips blank lines and # comments)
    - Full error handling and helpful console output
    - Inherits all original behavior (Linux-only masked API key input, CSV mapping, rate-limit safety, UTC-aware datetimes, etc.)

Prerequisites:
    1. This file must be in the SAME folder as fetch_gecko_price_history.py
    2. top_tokens_by_market_cap.csv must exist (the mapping file used by the fetcher)
    3. Your subjective tokens file (default: subjective_top_tokens_test.txt) must exist
"""

import os
import sys
import fetch_gecko_price_history as gecko  # ← must be in same directory

# ==================== CONFIG SECTION ====================
CONFIG = {
    # ── Main settings you will most likely change ─────────────────────
    "subjective_tokens_file": "subjective_top_tokens_test.txt",
    "n_months": 24,

    # ── Inherited / override settings from the original fetcher ───────
    "force_fresh_download": True,
}
# =======================================================


def load_subjective_tokens(filename: str) -> list[str]:
    """Load tokens from a plain text file (one token per line).
    Skips empty lines and lines that start with # (comments).
    """
    if not os.path.exists(filename):
        print(f"❌ Error: Subjective tokens file '{filename}' not found!")
        print("   → Create the file or update CONFIG['subjective_tokens_file']")
        print("   Example content (one token per line):")
        print("       btc")
        print("       eth")
        print("       # this is a comment")
        sys.exit(1)

    tokens = []
    with open(filename, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                tokens.append(cleaned.lower())
            elif cleaned.startswith("#"):
                print(f"   [Line {line_no}] Ignored comment: {cleaned}")

    if not tokens:
        print("❌ Error: No valid tokens found in the file!")
        sys.exit(1)

    print(f"✅ Loaded {len(tokens)} token(s) from '{filename}'")
    return tokens


def main():
    print("=== Subjective Top Tokens – Hourly Price History Fetcher ===\n")

    # 1. Load the list of tokens you care about
    tokens = load_subjective_tokens(CONFIG["subjective_tokens_file"])
    print("Tokens:", ", ".join(t.upper() for t in tokens))

    # 2. Apply any config overrides to the original fetcher
    if "force_fresh_download" in CONFIG:
        gecko.CONFIG["force_fresh_download"] = CONFIG["force_fresh_download"]
        print(f"   Force fresh download: {gecko.CONFIG['force_fresh_download']}")

    # 3. Get CoinGecko Pro API key (reuses the exact masked-input function + header)
    print("\n" + "=" * 60)
    api_key = gecko.get_api_key()          # ← this prints the nice header and does masked input

    # 4. Fetch everything (reuses the exact batch function you already have)
    print(f"\n🚀 Fetching ≈{CONFIG['n_months']} months of hourly USD prices for {len(tokens)} tokens...")
    results = gecko.fetch_price_history_for_tokens(
        token_list=tokens,
        months=CONFIG["n_months"],
        api_key=api_key
    )

    # 5. Final summary
    print(f"\n🎉 Batch complete! Successfully processed {len(results)}/{len(tokens)} tokens.")
    print(f"   All CSVs saved to: ./{gecko.CONFIG.get('output_dir', 'fetched_data')}/")
    print("   Each file is named <token>_price_history.csv and contains hourly UTC data.")


if __name__ == "__main__":
    # Optional: let user override months from command line (e.g. python script.py 12)
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        CONFIG["n_months"] = int(sys.argv[1])
        print(f"⚠️  Command-line override: using {CONFIG['n_months']} months")
    main()
