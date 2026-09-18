#for yf desktop table
import os
import json
import glob
import yfinance as yf

def update_cinnamon_desklet():
    """
    Combines portfolio and watchlist tickers with specific formatting:
    - Portfolio: Bold weight
    - Watchlist: Gray color (#818589)
    - Order: Portfolio first, then Watchlist
    """
    
    # 1. Define paths
    base_dir = os.path.expanduser("~")
    portfolio_path = os.path.join(base_dir, "code/innerdb/.portfolio.json")
    watchlist_path = os.path.join(base_dir, "code/innerdb/important_watchlist.txt")
    # Path to Cinnamon desklet config
    cinnamon_config_dir = os.path.expanduser("~/.config/cinnamon/spices/yfquotes@thegli/")
    
    formatted_tickers = []
    seen_tickers = set()

    def get_valid_json_tickers(file_path):
        """Helper to load JSON and return a list of symbols."""
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                return json.load(f)
        return []


    def get_valid_txt_tickers(file_path):
        """Helper to load a text file and return a list of symbols."""
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        return []
    print("🔍 Validating and formatting tickers...")

    # 2. Process Portfolio Tickers (Bold)
    portfolio_symbols = get_valid_json_tickers(portfolio_path)
    for symbol in portfolio_symbols:
        if symbol not in seen_tickers:
            try:
                # Basic validation check
                t = yf.Ticker(symbol)
                if t.fast_info['currency']:
                    formatted_tickers.append(f"{symbol};weight=bold")
                    seen_tickers.add(symbol)
            except Exception:
                print(f"Skipping {symbol}: Market data not found.")

    # 3. Process Watchlist Tickers (Gray: #818589)
    watchlist_symbols = get_valid_txt_tickers(watchlist_path)
    for symbol in watchlist_symbols:
        if symbol not in seen_tickers:
            try:
                t = yf.Ticker(symbol)
                if t.fast_info['currency']:
                    formatted_tickers.append(f"{symbol};color=#818589")
                    seen_tickers.add(symbol)
            except Exception:
                print(f"Skipping {symbol}: Market data not found.")

    # 4. Update the Cinnamon Desklet JSON configuration
    json_files = glob.glob(os.path.join(cinnamon_config_dir, "*.json"))
    if not json_files:
        print("❌ Error: Could not find Cinnamon desklet config file in the spice directory.")
        return

    for config_path in json_files:
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
            
            # Join all formatted tickers with newlines
            config_data["quoteSymbols"]["value"] = "\n".join(formatted_tickers)
            
            with open(config_path, "w") as f:
                json.dump(config_data, f, indent=4)
            
            print(f"✅ Success! Updated {os.path.basename(config_path)}")
            print(f"📊 Total tickers: {len(formatted_tickers)} ({len(portfolio_symbols)} Portfolio / {len(watchlist_symbols)} Watchlist)")
        
        except Exception as e:
            print(f"❌ Failed to update {config_path}: {e}")

if __name__ == "__main__":
    update_cinnamon_desklet()