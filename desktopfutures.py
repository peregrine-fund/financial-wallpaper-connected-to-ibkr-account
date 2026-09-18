import yfinance as yf 
import matplotlib.pyplot as plt 
from PIL import Image 
import requests 
import json 
from datetime import datetime, date, timedelta 
import re 
import pandas as pd 
import os 
from colorama import Fore, Style, init 
import sys 
import time 
import glob 

# Suppress annoying dependency warnings
import warnings
from urllib3.exceptions import NotOpenSSLWarning
warnings.filterwarnings("ignore", category=DeprecationWarning)

init(autoreset=True) 

FRED_API_KEY = os.getenv("fredapikey")
PORTFOLIO_FILE = "/home/your_username/code/innerdb/.portfolio.json"
DATA_FILE = "/home/your_username/code/wallpaper/revenue_predictions.json"
PORTFOLIO_PRICES_JSON = "/home/your_username/code/innerdb/.portfolio_prices.json"

# price alert treshold
def get_price_and_status(symbol, value, period="1y"):
    try:
        ticker = yf.Ticker(symbol)
        # Fetch price history for the requested lookback range
        df = ticker.history(period=period) 
        if df.empty:
            return None, False, None

        current_price = df["Close"].iloc[-1]
        low_range = df["Low"].min()
        high_range = df["High"].max()
        
        # Prevent division by zero in the ultra-rare event the price never moved

        if high_range <= low_range: # Logic safety
            return current_price, False, None
        # Apply your formula
        range_percentile = (current_price - low_range) / (high_range - low_range)
        
        # Trigger purple if it is in the bottom X% of its range
        is_near_bottom = range_percentile <= value
        
        return current_price, is_near_bottom, range_percentile
    except:
        return None, False, None

# ------------------- FRED DATA FUNCTIONS ------------------- 

def fetch_series(series_id): 
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
    response = requests.get(url, timeout=5) 
    response.raise_for_status() 
    data = response.json() 
    if "observations" not in data: 
        return pd.DataFrame(columns=["date", series_id]) 
    df = pd.DataFrame( 
        [{"date": obs["date"], series_id: float(obs["value"])} 
         for obs in data["observations"] if obs["value"] not in (".", None)] 
    ) 
    df["date"] = pd.to_datetime(df["date"]) 
    return df 

def fetch_and_save_data(name, formula): 
    try: 
        tokens = re.findall(r"[A-Za-z0-9_]+", formula) 
        series_ids = {t for t in tokens if not t.isdigit()} 
        dataframes = [] 
        for sid in series_ids: 
            df = fetch_series(sid) 
            if not df.empty: 
                dataframes.append(df) 
        if not dataframes: 
            return False 
        merged = dataframes[0] 
        for df in dataframes[1:]: 
            merged = pd.merge(merged, df, on="date", how="inner") 
        merged.sort_values("date", inplace=True) 
        eval_formula = formula 
        for sid in series_ids: 
            eval_formula = eval_formula.replace(sid, f"merged['{sid}']") 
        merged[name] = eval(eval_formula) 
        output = merged[["date", name]].to_dict(orient="records") 
        with open(f"{name}.json", "w", encoding="utf-8") as f: 
            json.dump(output, f, indent=2, default=str) 
        return True 
    except Exception as e: 
        print("Error:", e) 
        return False 

# ------------------- PORTFOLIO & EARNINGS ------------------- 

def load_json(path, default): 
    if not os.path.exists(path): 
        return default 
    with open(path, "r") as f: 
        return json.load(f)

def save_json(path, data): 
    with open(path, "w") as f: 
        json.dump(data, f, indent=4, default=str)

def fetch_calendar_data(ticker_symbol): 
    try: 
        ticker = yf.Ticker(ticker_symbol) 
        # Quiet the stderr during calendar fetch
        old_stderr = sys.stderr 
        sys.stderr = open(os.devnull, "w") 
        calendar = ticker.get_calendar() 
        sys.stderr.close() 
        sys.stderr = old_stderr 
        if not calendar: 
            return None 
        return { 
            "Earnings Date": ( 
                calendar.get("Earnings Date", [None])[0] 
                if isinstance(calendar.get("Earnings Date"), list) 
                else calendar.get("Earnings Date") 
            ), 
            "EPS": calendar.get("Earnings Average"), 
            "Revenue": calendar.get("Revenue Average"), 
        } 
    except Exception: 
        return None 

def compare_and_update_data(old_ticker_data, new_data): 
    """
    Saves new entry to history ONLY if values changed.
    Changes include a timestamp so they can 'expire' after 3 days.
    """
    today_str = datetime.today().strftime("%Y-%m-%d") 
    changes = [] 
    
    if old_ticker_data: 
        last_date = sorted(old_ticker_data.keys())[-1] 
        last_data = old_ticker_data[last_date] 
    else: 
        last_data = {} 

    has_changed = False
    for key in ["EPS", "Revenue"]: 
        old_val = last_data.get(key) 
        new_val = new_data.get(key) 
         
        if new_val is not None and old_val != new_val: 
            has_changed = True
            shorthand = "EPS" if key == "EPS" else "REV" 
            
            if old_val is not None and old_val != 0:
                change_pct = ((new_val - old_val) / old_val) * 100 
                color = Fore.GREEN if change_pct > 0 else Fore.RED 
                # Store text and date metadata using pipe separator
                changes.append(f"{color}{shorthand} {change_pct:+.2f}%|{today_str}") 
             
    if has_changed or not old_ticker_data: 
        old_ticker_data[today_str] = new_data 
        
    return old_ticker_data, changes 

# ------------------- YFINANCE COMMODITIES ------------------- 

tickers_config = { 
    "S&P": "ES=F", 
    "CZK/USD": "CZK=X", 
    "CZK/USD": "EURCZK=X", 
    "space": "", 
    "Crude Oil (WTI)": "CL=F", 
    "Natural Gas": "NG=F", 
    "10Y T-Note": "^TNX", 
    "3M Bill": "^IRX",  
    "Gold": "GC=F", 
} 
prices_path = "/home/your_username/code/innerdb/prices.json"

try:
    with open(prices_path, "r", encoding="utf-8") as file:
        raw_data = file.read()
        
    try:
        # 1. Try to load the JSON normally
        tickers_config = json.loads(raw_data)
    except json.JSONDecodeError:
        # 2. If it fails, strip trailing commas and try one more time
        # This regex removes commas that are followed by a closing brace } or bracket ]
        clean_data = re.sub(r',\s*([\]}])', r'\1', raw_data)
        tickers_config = json.loads(clean_data)
        print("💡 Warning: Fixed a trailing comma in your JSON file automatically.")

except FileNotFoundError:
    print(f"Error: The file at {prices_path} was not found.")
    tickers_config = {}  # Fallback to an empty dict if file missing

    
additional_config={

}
watchlist_path = "/home/your_username/code/innerdb/important_watchlist.txt"

if os.path.exists(watchlist_path):
    with open(watchlist_path, "r") as f:
        # Read lines, strip whitespace, and filter out empty lines
        watchlist_data = [line.strip() for line in f if line.strip()]
    
    # 2. Convert the list into a dictionary: {"OEC": "OEC", "LYB": "LYB", ...}
    additional_config = {ticker: ticker for ticker in watchlist_data}
else:
    print(f"Warning: {watchlist_path} not found.")
    additional_config = {}

stable_watchlist_path = "/home/your_username/code/innerdb/stable_watchlist.txt"
long_term_stable_watchlist_path = "/home/your_username/code/innerdb/long_term_stable_watchlist.txt"


if os.path.exists(stable_watchlist_path):
    with open(stable_watchlist_path, "r") as f:
        # Read lines, strip whitespace, and filter out empty lines
        tickers = [line.strip() for line in f if line.strip()]
    
    # Convert the list into the required dictionary format
    additional_stable_config = {ticker: ticker for ticker in tickers}
else:
    print(f"Warning: {stable_watchlist_path} not found.")
    additional_stable_config = {}

# Long-term stable watchlist: same idea as the stable watchlist, but checked
# against a 5-year price range instead of 1-year, with an 8% "near bottom" threshold
if os.path.exists(long_term_stable_watchlist_path):
    with open(long_term_stable_watchlist_path, "r") as f:
        long_term_tickers = [line.strip() for line in f if line.strip()]

    additional_long_term_stable_config = {ticker: ticker for ticker in long_term_tickers}
else:
    print(f"Warning: {long_term_stable_watchlist_path} not found.")
    additional_long_term_stable_config = {}

def get_last_trading_price(symbol): 
    try:
        ticker = yf.Ticker(symbol) 
        data = ticker.history(period="7d") 
        if not data.empty: 
            return data["Close"].iloc[-1] 
    except:
        pass
    return None 

# ------------------- WALLPAPER PLOTTING ------------------- 
def plot_table_on_wallpaper(earnings_list, tickers_dict, wallpaper_path, output_path): 
    today_date = date.today() 
    tomorrow_date = today_date + timedelta(days=1) 
    three_days_ago = today_date - timedelta(days=3)
     
    # 1. Prepare Earnings Data
    mpl_earnings_rows = [] 
    for item in earnings_list: 
        ticker = item['ticker'] 
        earnings_dt = item['earnings_date'] 
         
        if isinstance(earnings_dt, datetime): 
            earnings_date_obj = earnings_dt.date() 
        else: 
            earnings_date_obj = earnings_dt  
             
        date_str = earnings_dt.strftime("%b %d")
        is_today_or_tomorrow = (earnings_date_obj == today_date) or (earnings_date_obj == tomorrow_date) 
        
        # --- Apply the 3-day visibility rule ---
        visible_labels = []
        raw_ansi_for_styling = []
        
        for change_blob in item['changes']:
            if "|" in change_blob:
                change_text, change_date_str = change_blob.split("|")
                c_date = datetime.strptime(change_date_str, "%Y-%m-%d").date()
                
                if c_date >= three_days_ago:
                    clean_text = re.sub(r'\x1b\[\d+m', '', change_text)
                    visible_labels.append(clean_text)
                    raw_ansi_for_styling.append(change_text)

        changes_display = " | ".join(visible_labels) 
         
        mpl_earnings_rows.append([
            ticker, 
            date_str, 
            item['eps_est'], 
            item['rev_est'], 
            changes_display, 
            raw_ansi_for_styling, 
            is_today_or_tomorrow
        ]) 
    
    # 2. Prepare Commodity Data (Excluding Stable Watchlist)
    commodity_rows = [] 
    commodity_bottom_flags = [] 

    # Start with standard tickers
    active_tickers = tickers_dict.copy()

    # Only add additional config if bottomed
    for name, symbol in additional_config.items():
        price, is_bottom, _ = get_price_and_status(symbol, 0.08)
        if is_bottom:
            active_tickers[name] = symbol

    for name, symbol in active_tickers.items(): 
        if name.lower() == "space": continue 
        
        price, is_bottom, _ = get_price_and_status(symbol, 0.2) 
        commodity_rows.append([name, f"{price:.2f}" if price else "N/A"])
        commodity_bottom_flags.append(is_bottom)

    # 3. Prepare Stable Watchlist Duo (Columns 4 & 5)
    # Combines the short-term stable watchlist (1yr range, bottom 17% -> purple)
    # with the long-term stable watchlist (5yr range, bottom 8% -> dark yellow).
    # A ticker that is bottomed in BOTH lists gets a single merged row in a
    # third color (light yellow) instead of appearing twice.
    #
    # Ordering: sorted by cheapness (range percentile, 0% = right at the low)
    # ascending, so the cheapest names sit at the top and names just barely
    # under the threshold sit at the bottom. "is_new" is kept only as a
    # tiebreaker for equal cheapness.
    json_path = "/home/your_username/code/innerdb/alreadylowstocks.json"
    already_low_stocks = set()

    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                already_low_stocks = set(json.load(f))
        except Exception as e:
            print(f"Warning: Could not read {json_path}: {e}")

    # Initialize flags and target output arrays
    stable_rows = []
    stable_bottom_flags = []      # True -> purple (short-term stable only)
    stable_longterm_flags = []    # True -> dark yellow (long-term stable only)
    stable_both_flags = []        # True -> light yellow (bottomed in BOTH lists)

    short_term_status = {}
    for name, symbol in additional_stable_config.items():
        short_term_status[name] = get_price_and_status(symbol, 0.17)

    long_term_status = {}
    for name, symbol in additional_long_term_stable_config.items():
        long_term_status[name] = get_price_and_status(symbol, 0.08, period="5y")

    processed_names = set()
    hits = []  # Temporary staging list to allow sorting before building final lists

    for name in additional_stable_config:
        if name in processed_names:
            continue
        st_price, st_bottom, st_pct = short_term_status.get(name, (None, False, None))
        lt_price, lt_bottom, lt_pct = long_term_status.get(name, (None, False, None))

        if st_bottom and lt_bottom:
            price = st_price if st_price is not None else lt_price
            pcts = [p for p in (st_pct, lt_pct) if p is not None]
            cheapness = min(pcts) if pcts else 1.0
            hits.append({
                "name": name,
                "price": f"{price:.2f}" if price else "N/A",
                "bottom": False,
                "longterm": False,
                "both": True,
                "is_new": name not in already_low_stocks,
                "cheapness": cheapness
            })
            processed_names.add(name)
        elif st_bottom:
            hits.append({
                "name": name,
                "price": f"{st_price:.2f}" if st_price else "N/A",
                "bottom": True,
                "longterm": False,
                "both": False,
                "is_new": name not in already_low_stocks,
                "cheapness": st_pct if st_pct is not None else 1.0
            })
            processed_names.add(name)

    for name in additional_long_term_stable_config:
        if name in processed_names:
            continue
        lt_price, lt_bottom, lt_pct = long_term_status.get(name, (None, False, None))
        if lt_bottom:
            hits.append({
                "name": name,
                "price": f"{lt_price:.2f}" if lt_price else "N/A",
                "bottom": False,
                "longterm": True,
                "both": False,
                "is_new": name not in already_low_stocks,
                "cheapness": lt_pct if lt_pct is not None else 1.0
            })
            processed_names.add(name)

    # Sort by cheapness ascending (0% = at the low, sits on top). Ties broken
    # by "is_new" so freshly-bottomed names still edge out old ones.
    hits.sort(key=lambda item: (item["cheapness"], not item["is_new"]))

    for hit in hits:
        stable_rows.append([hit["name"], hit["price"]])
        stable_bottom_flags.append(hit["bottom"])
        stable_longterm_flags.append(hit["longterm"])
        stable_both_flags.append(hit["both"])

    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w") as f:
        json.dump(sorted(list(processed_names)), f, indent=4)

    # 4. Prepare Portfolio Returns (Columns 0, 1, & 2)
    portfolio_rows = []
    
    # Load .wdatabase for the ratio calculation
    wdb_path = "/home/your_username/calc/.wdatabase.json"  # Adjust if your path is different
    wdb_dict = {}
    if os.path.exists(wdb_path):
        try:
            with open(wdb_path, "r") as f:
                wdb_data = json.load(f)
                # Map 'description' (ticker) to 'price' from .wdatabase
                wdb_dict = {
                    item.get("description"): item.get("price") 
                    for item in wdb_data 
                    if "description" in item and "price" in item
                }
        except Exception:
            pass

    if os.path.exists(PORTFOLIO_PRICES_JSON):
        with open(PORTFOLIO_PRICES_JSON, "r") as f:
            port_data = json.load(f)
            for t_sym, p_info in port_data.items():
                buy_p = p_info.get("purchasePrice")
                curr_p = p_info.get("currentPrice")
                if buy_p and curr_p and buy_p > 0:
                    gain = (curr_p / buy_p - 1) * 100
                    
                    # Calculate stock price / .wdatabase price ratio
                    ratio_str = ""
                    wdb_price = wdb_dict.get(t_sym)
                    if wdb_price and wdb_price > 0:
                        ratio = curr_p / wdb_price
                        ratio_str = f"{ratio:.2f}"
                        
                    # Insert the ratio as the 3rd item in the row
                    portfolio_rows.append([f"{t_sym}", f"{gain:+.1f}%", ratio_str, gain])
                    
    portfolio_rows.sort(key=lambda x: x[3], reverse=True)

    # 5. Prepare Watchlist Projections (Column 6)
    projection_rows = []
    proj_file = os.path.expanduser("~/code/wallpaper/projection_from_watchlist.json")
    if os.path.exists(proj_file):
        with open(proj_file, "r") as f:
            projections = json.load(f)
            for t_sym, proj_val in projections.items():
                curr_p = get_last_trading_price(t_sym)
                if curr_p:
                    gain = (curr_p / proj_val - 1) * 100
                    if gain > 15:
                        projection_rows.append(f"{t_sym}: +{gain:.2f}%")

    # 6. Combine Rows into 8 Columns
    combined_rows = [] 
    for row in mpl_earnings_rows: 
        # Pad Earnings rows with three empty strings at the end to match the new 8-column grid
        combined_rows.append([row[0], row[1], row[2], row[3], row[4], "", "", ""]) 
     
    for _ in range(3): 
        combined_rows.append(["", "", "", "", "", "", "", ""]) 
         
    max_bottom_rows = max(len(commodity_rows), len(portfolio_rows), len(projection_rows), len(stable_rows))
    for i in range(max_bottom_rows):
        p_sym = portfolio_rows[i][0] if i < len(portfolio_rows) else ""
        p_gain = portfolio_rows[i][1] if i < len(portfolio_rows) else ""
        p_ratio = portfolio_rows[i][2] if i < len(portfolio_rows) else ""
        c_name = commodity_rows[i][0] if i < len(commodity_rows) else ""
        c_price = commodity_rows[i][1] if i < len(commodity_rows) else ""
        s_name = stable_rows[i][0] if i < len(stable_rows) else ""
        s_price = stable_rows[i][1] if i < len(stable_rows) else ""
        proj_text = projection_rows[i] if i < len(projection_rows) else ""
        
        # Add p_ratio as the 3rd variable in the list
        combined_rows.append([p_sym, p_gain, p_ratio, c_name, c_price, s_name, s_price, proj_text])

    # --- Plotting ---
    row_height = 0.45 
    total_rows = len(combined_rows) + 1 
    fig, ax = plt.subplots(figsize=(12, total_rows * row_height), dpi=150) 
    ax.axis("off") 

    # Column Widths sum to exactly 1.00 (maintaining same total table width)
    table = ax.table( 
        cellText=combined_rows, 
        cellLoc="left", 
        colWidths=[0.10, 0.11, 0.08, 0.18, 0.10, 0.15, 0.09, 0.20], 
        loc="bottom",  
    ) 
    table.auto_set_font_size(False) 
    table.set_fontsize(15) 
    table.scale(1.0, 1.2) 
     
    earnings_data_end_idx = len(mpl_earnings_rows) 
    for i in range(len(combined_rows)): 
        for j in range(8): # Updated to 8 columns
            cell = table.get_celld()[(i, j)] 
            cell.set_linewidth(0) 
            cell.set_facecolor((1, 1, 1, 0)) 
            cell_text = cell.get_text() 
            cell_text.set_color("white") 

            if i < earnings_data_end_idx:
                if j == 4: 
                    # CRITICAL: Allow long earnings text to overflow into the empty columns
                    cell_text.set_clip_on(False)
                    
                    raw_ansi_list = mpl_earnings_rows[i][5] 
                    for color_str in raw_ansi_list: 
                        if Fore.GREEN in color_str: 
                            cell_text.set_color("green") 
                            break 
                        elif Fore.RED in color_str: 
                            cell_text.set_color("red") 
                            break 
                if j == 1 and mpl_earnings_rows[i][6]: 
                    cell_text.set_color("#9900ff") 
                    cell_text.set_weight("bold") 
            
            elif i >= earnings_data_end_idx + 3:
                comm_idx = i - (earnings_data_end_idx + 3)
                
                # Apply Purple to Commodities if bottomed (Duo 2: Columns 3 & 4)
                if comm_idx < len(commodity_bottom_flags) and commodity_bottom_flags[comm_idx]:
                    if j == 3 or j == 4: 
                        cell_text.set_color("#9900ff") 
                        cell_text.set_weight("bold")

                # Apply Purple to Stable Watchlist if bottomed (Duo 3: Columns 5 & 6)
                if comm_idx < len(stable_bottom_flags) and stable_bottom_flags[comm_idx]:
                    if j == 5 or j == 6: 
                        cell_text.set_color("#9900ff") 
                        cell_text.set_weight("bold")

                # Apply Dark Yellow to Long-Term Stable Watchlist if bottomed only there (Duo 3: Columns 5 & 6)
                if comm_idx < len(stable_longterm_flags) and stable_longterm_flags[comm_idx]:
                    if j == 5 or j == 6:
                        cell_text.set_color("#B8860B") 
                        cell_text.set_weight("bold")

                # Apply Light Yellow if bottomed in BOTH stable watchlists (Duo 3: Columns 5 & 6)
                if comm_idx < len(stable_both_flags) and stable_both_flags[comm_idx]:
                    if j == 5 or j == 6:
                        cell_text.set_color("#FFFF99")
                        cell_text.set_weight("bold")

                # Portfolio gain coloring (Duo 1: Column 1)
                if j == 1: 
                    txt = cell_text.get_text()
                    if txt.startswith('+'): cell_text.set_color("green")
                    elif txt.startswith('-'): cell_text.set_color("red")
                
                # Dimmed coloring for the new Ratio (Column 2) so it doesn't distract
                if j == 2:
                    txt = cell_text.get_text().strip()
                    if txt:
                        try:
                            val = float(txt)
                            if val < 1.0:
                                cell_text.set_color("white")
                            else:
                                cell_text.set_color("red")
                        except ValueError:
                            cell_text.set_color("white")
                
                # Projections coloring (Column 7)
                if j == 7:
                    txt = cell_text.get_text()
                    if txt:
                        cell_text.set_color("#00ccff")
                        cell_text.set_style("italic")

    table_path = "/tmp/wallpaper_table.png" 
    plt.savefig(table_path, bbox_inches="tight", transparent=True, pad_inches=0.05) 
    plt.close(fig) 

    # Overlay
    wallpaper = Image.open(wallpaper_path).convert("RGBA") 
    table_img = Image.open(table_path).convert("RGBA") 
    y_placement = wallpaper.height - table_img.height - 90 
    wallpaper.paste(table_img, (20, y_placement), table_img) 

    if output_path.lower().endswith((".jpg", ".jpeg")): 
        wallpaper = wallpaper.convert("RGB") 
    wallpaper.save(output_path)
    print("Wallpaper updated successfully.")
# ------------------- MAIN ------------------- 

def main(): 
    portfolio = load_json(PORTFOLIO_FILE, []) 
    history_data = load_json(DATA_FILE, {}) 

    earnings_list = [] 

    for ticker in portfolio: 
        new_data = fetch_calendar_data(ticker) 
        if not new_data or not new_data.get("Earnings Date"): 
            continue 

        old_ticker_history = history_data.get(ticker, {}) 
        # FIXED: Variable names now match definition
        updated_history, changes = compare_and_update_data(old_ticker_data=old_ticker_history, new_data=new_data) 
        history_data[ticker] = updated_history 
         
        eps_val = new_data.get("EPS")
        eps_est = f"{eps_val:.2f}" if eps_val is not None else "N/A"
        
        rev_val = new_data.get("Revenue")
        if rev_val:
            rev_est = f"{rev_val/1e9:.1f}B" if rev_val >= 1e9 else f"{rev_val/1e6:.1f}M"
        else:
            rev_est = "N/A"

        earnings_date = new_data["Earnings Date"] 
        if isinstance(earnings_date, str): 
            try: 
                earnings_date = datetime.fromisoformat(earnings_date.replace('Z', '+00:00')) 
            except ValueError: 
                 try: 
                    earnings_date = datetime.strptime(earnings_date.split('T')[0], "%Y-%m-%d") 
                 except ValueError: 
                     continue 

        earnings_list.append({ 
            "ticker": ticker, 
            "earnings_date": earnings_date, 
            "changes": changes,
            "eps_est": eps_est,
            "rev_est": rev_est
        }) 

    earnings_list.sort(key=lambda x: x["earnings_date"]) 
    save_json(DATA_FILE, history_data) 
    
    time.sleep(1) # Short pause

    wallpaper_path = "/home/your_username/Documents/.wallpaper/picture_with_feed.jpg" 
    plot_table_on_wallpaper(earnings_list, tickers_config, wallpaper_path, wallpaper_path) 

if __name__ == "__main__": 
    main()