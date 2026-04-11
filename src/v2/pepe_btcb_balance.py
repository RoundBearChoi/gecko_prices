from web3 import Web3

# ====================== CONFIG ======================
RPC_URL = "https://bsc-dataseed.binance.org/"

# Token addresses (lowercase is fine here — we convert them automatically)
TOKENS_LOWER = {
    "BTCB": "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c",   # Binance-Peg BTCB
    "PEPE": "0x25d887ce7a35172c62febfd67a1856f20faebb00"    # PEPE on BSC
}

# Minimal ERC-20 ABI
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]
# ===================================================

def main():
    # Connect to BSC
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print("❌ Failed to connect to BSC network.")
        return

    # Convert token contracts to checksum addresses (this fixes the error)
    TOKENS = {
        symbol: w3.to_checksum_address(addr)
        for symbol, addr in TOKENS_LOWER.items()
    }

    print("✅ Connected to BSC successfully!\n")

    # Get wallet address from user
    wallet_input = input("Enter your BSC wallet address (0x...): ").strip()
    
    try:
        wallet = w3.to_checksum_address(wallet_input)
        print(f"🔍 Checking balances for: {wallet}\n")
    except Exception:
        print("❌ Invalid address format! Please enter a valid 0x... address.")
        return

    # Fetch balances
    for symbol, contract_addr in TOKENS.items():
        try:
            contract = w3.eth.contract(address=contract_addr, abi=ERC20_ABI)
            
            raw_balance = contract.functions.balanceOf(wallet).call()
            decimals = contract.functions.decimals().call()
            token_symbol = contract.functions.symbol().call()
            
            formatted_balance = raw_balance / (10 ** decimals)
            
            print(f"📌 {token_symbol} Balance")
            print(f"   Formatted : {formatted_balance:,.8f} {token_symbol}")
            print(f"   Raw       : {raw_balance:,}")
            print(f"   Contract  : {contract_addr}\n")
            
        except Exception as e:
            print(f"❌ Error fetching {symbol} balance: {e}\n")

    print("✅ Done! All balances retrieved.")

if __name__ == "__main__":
    main()
