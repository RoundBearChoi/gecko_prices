#!/usr/bin/env python3
"""
fetch_subjective_top_tokens_price_history.py
NOW USING HIGH-PRECISION SAVING FROM THE UPDATED FETCHER
"""

import os
import sys
import fetch_gecko_price_history as gecko

# ==================== CONFIG SECTION ====================
CONFIG = {
    "subjective_tokens_file": "subjective_top_tokens_test.txt",
    "n_months": 24,
    "force_fresh_download": True,
}
# =======================================================


def load_subjective_tokens(filename: str) -> list[str]:
    """Load tokens from a plain text file (one token per line)."""
    if not os.path.exists(filename):
        print(f"❌ Error: Subjective tokens file '{filename}' not found!")
        print("   → Create the file or update CONFIG['subjective_tokens_file']")
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

    tokens = load_subjective_tokens(CONFIG["subjective_tokens_file"])
    print("Tokens:", ", ".join(t.upper() for t in tokens))

    if "force_fresh_download" in CONFIG:
        gecko.CONFIG["force_fresh_download"] = CONFIG["force_fresh_download"]
        print(f"   Force fresh download: {gecko.CONFIG['force_fresh_download']}")

    print("\n" + "=" * 60)
    api_key = gecko.get_api_key()

    print(f"\n🚀 Fetching ≈{CONFIG['n_months']} months of hourly USD prices for {len(tokens)} tokens...")
    results = gecko.fetch_price_history_for_tokens(
        token_list=tokens,
        months=CONFIG["n_months"],
        api_key=api_key
    )

    print(f"\n🎉 Batch complete! Successfully processed {len(results)}/{len(tokens)} tokens.")
    print(f"   All CSVs saved to: ./{gecko.CONFIG.get('output_dir', 'fetched_data')}/")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        CONFIG["n_months"] = int(sys.argv[1])
        print(f"⚠️  Command-line override: using {CONFIG['n_months']} months")
    main()
