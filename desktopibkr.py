from datetime import datetime, timedelta, date
import xml.etree.ElementTree as ET
import requests
import time
import yfinance as yf
import json
import matplotlib.pyplot as plt
from PIL import Image
import os
import holidays
import csv 
import os
import sqlite3
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path="/home/your_username/code/portfolio/.env")

# Match the exact variable names defined in your .env
TOKEN = os.getenv("IBKR_TOKEN")
FLEX_QUERY_ID = os.getenv("FLEX_QUERY_ID")
YAHOO_CSV_PATH = '/home/your_username/code/innerdb/yahoo_portfolio.csv'
COLORS_JSON = '/home/your_username/code/wallpaper/pie_colors.json'
# Cache for symbol resolution

search_cache = {}
EXCHANGE_MAP = {
    "LSE": ".L",
    "FWB": ".F",
    "IBIS": ".DE",
    "AEB": ".AS",
    "EBS": ".SW",
    "VSE": ".VI",
    "PAR": ".PA",
    "MIL": ".MI",
    "BM": ".MC",
    "TSE": ".TO",
    "SBF": ".PA",
    "CSE": ".CO",
    "BURSAMY": ".KL",
    "TPEX": ".TWO"
}
DIVIDENDS_JSON = '/home/your_username/code/innerdb/dividend_database.json'
PORTFOLIO_DB_PATH = '/home/your_username/code/portfolio/portfolio.db' # <--- ADD THIS (adjust path if needed)
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "ISLAND"}

QUERY_ID_FILE = '/home/your_username/code/innerdb/.last_query_id.txt'
PORTFOLIO_JSON = '/home/your_username/code/innerdb/.portfolio.json'
PORTFOLIO_PRICES_JSON = '/home/your_username/code/innerdb/.portfolio_prices.json'
ORIGINAL_WALLPAPER = "/home/your_username/Documents/.wallpaper/picture.jpg"
OUTPUT_WALLPAPER = "/home/your_username/Documents/.wallpaper/picture_with_feed.jpg"
ROW_PATH = "/home/your_username/Documents/.wallpaper/row.txt"

XML_OUTPUT_PATH = '/home/your_username/code/innerdb/daily_ibkr_statement.xml'

def get_consistent_colors(fund_data):
    """Assigns and persists consistent colors for active portfolio positions."""
    # Get all currently held symbols across both funds
    current_symbols = set()
    for data in fund_data.values():
        current_symbols.update(data['positions'].keys())
    
    # Load existing color mapping
    try:
        with open(COLORS_JSON, 'r') as f:
            color_map = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        color_map = {}
        
    # Prune sold stocks to recycle their colors
    color_map = {sym: color for sym, color in color_map.items() if sym in current_symbols}
    
    # Matplotlib Tab20 palette (you can customize these hex codes)
    # 30 Technical & Dashboard Tones (Teals, Slate, Blues, Emeralds, Amber, Rust)
    palette = [
    # Interleaved for maximum adjacent contrast in pie charts
    "#1E3A8A",  # Deep Navy Blue
    "#B45309",  # Industrial Amber
    "#14532D",  # Dark Forest Green
    "#9F4A1F",  # Muted Terracotta
    "#334155",  # Slate Gray
    "#0F766E",  # Deep Teal
    "#854D0E",  # Raw Umber / Olive Gold
    "#312E81",  # Deep Muted Indigo
    "#3F6212",  # Dark Moss Green
    "#7C2D12",  # Burnt Rust
    "#155E75",  # Ocean Cyan
    "#B7791F",  # Muted Ochre
    "#2D6A4F",  # Dark Sage
    "#8D4925",  # Copper Brown
    "#1E293B",  # Dark Charcoal Slate
    "#166534",  # Deep Pine Green
    "#A16207",  # Muted Mustard
    "#2B529A",  # Muted Royal Blue
    "#3B316A",  # Dark Slate Plum
    "#115E59",  # Cold Spruce Teal
    "#9A3412",  # Deep Burnt Orange
    "#5B3A29",  # Warm Walnut Brown
    "#556B2F",  # Dark Olive Drab
    "#1B4F72",  # Industrial Steel Blue
    "#6A3805",  # Deep Bronze Brown
    "#134E4A",  # Dark Seagrass
    "#52525B",  # Cool Industrial Gray
    "#78350F",  # Dark Clay Amber
    "#0F172A",  # Midnight Navy
    "#4D7C0F",  # Muted Olive Green
]
    
    used_colors = set(color_map.values())
    available_colors = [c for c in palette if c not in used_colors]
    
    # Assign colors to newly purchased symbols
    for sym in current_symbols:
        if sym not in color_map:
            color_map[sym] = available_colors.pop(0) if available_colors else "#333333"
                
    # Save active state back to innerdb
    with open(COLORS_JSON, 'w') as f:
        json.dump(color_map, f, indent=2)
        
    return color_map
def load_pie_data_from_db():
    """Queries portfolio.db for the latest report date's positions and cash for 'gepard' and 'zelva'."""
    conn = sqlite3.connect(PORTFOLIO_DB_PATH)
    cursor = conn.cursor()
    
    # Find the latest report_date available in the table
    cursor.execute("SELECT MAX(report_date) FROM PORTFOLIOS")
    latest_date = cursor.fetchone()[0]
    
    # Structure to hold data for both funds separately
    fund_data = {
        'gepard': {'positions': {}, 'cash': 0.0},
        'zelva': {'positions': {}, 'cash': 0.0}
    }
    
    if latest_date:
        for fund in ['gepard', 'zelva']:
            # Fetch asset positions for the specific fund
            cursor.execute("""
                SELECT symbol, quantity, value_usd, currency, cost_value_usd 
                FROM PORTFOLIOS 
                WHERE report_date = ? AND asset_type = 'POSITION' AND fund_name = ?
            """, (latest_date, fund))
            
            for row in cursor.fetchall():
                symbol, qty, val_usd, curr, cost_usd = row
                fund_data[fund]['positions'][symbol] = {
                    'quantity': qty if qty is not None else 0.0,
                    'current_value': val_usd if val_usd is not None else 0.0,
                    'currency': curr if curr else 'USD',
                    'purchase_price': (cost_usd / qty) if (qty and qty != 0 and cost_usd) else 0.0
                }
                
            # Sum up cash values for the specific fund
            cursor.execute("""
                SELECT SUM(value_usd) 
                FROM PORTFOLIOS 
                WHERE report_date = ? AND asset_type = 'CASH' AND fund_name = ?
            """, (latest_date, fund))
            cash_res = cursor.fetchone()[0]
            fund_data[fund]['cash'] = float(cash_res) if cash_res else 0.0
            
    conn.close()
    return fund_data

def save_xml_to_innerdb(xml_root):
    """Serializes and saves the XML root element into the innerdb folder."""
    try:
        tree = ET.ElementTree(xml_root)
        # 'utf-8' encoding with xml_declaration ensures it writes perfectly formatted XML
        tree.write(XML_OUTPUT_PATH, encoding='utf-8', xml_declaration=True)
        print(f"Successfully saved statement XML to {XML_OUTPUT_PATH}")
    except Exception as e:
        print(f"Error saving XML file: {e}")

def trading_days_between(start: date, end: date) -> int:
    """Count trading days between two dates (exclusive of start, inclusive of end).
    Skips weekends and US public holidays."""
    us_holidays = holidays.NYSE(years=range(start.year, end.year + 1))
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in us_holidays:
            count += 1
    return count

def load_cached_dividends():
    """Load previously saved dividends from the JSON cache."""
    if os.path.exists(DIVIDENDS_JSON):
        try:
            with open(DIVIDENDS_JSON, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading dividend cache: {e}")
    return []

def save_cached_dividends(dividends):
    """Save the current dividends list to the JSON cache."""
    try:
        with open(DIVIDENDS_JSON, 'w') as f:
            json.dump(dividends, f, indent=2)
    except Exception as e:
        print(f"Error saving dividend cache: {e}")
def merge_dividends(cached_divs, fresh_divs):
    """
    Merges fresh IBKR/Yahoo data with local cache using the Yahoo Finance symbol 
    (which includes the exchange suffix) as the unique identifier.
    """
    # Use yf_symbol in the key (fallback to symbol just in case)
    cache_map = {f"{d.get('yf_symbol', d['symbol'])}_{d['ex_date']}": d for d in cached_divs}
    merged_map = {}
    today = datetime.now().date()

    for fresh in fresh_divs:
        key = f"{fresh.get('yf_symbol', fresh['symbol'])}_{fresh['ex_date']}"
        cached = cache_map.get(key)

        if cached and cached['type'] == 'paid_today' and fresh['type'] in ['upcoming', 'pre_ex']:
            merged_map[key] = cached
        else:
            merged_map[key] = fresh

    for key, cached in cache_map.items():
        if key not in merged_map and cached['type'] == 'paid_today':
            try:
                report_date = datetime.strptime(cached['report_date'], '%Y-%m-%d').date()
                if (today - report_date).days <= 2:  
                    merged_map[key] = cached
            except ValueError:
                pass

    return list(merged_map.values())


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

def resolve_symbol(symbol):
    """Resolve IBKR symbol to a Yahoo Finance ticker using search."""
    if symbol in search_cache:
        return search_cache[symbol]
    try:
        res = yf.search(symbol)
        if "quotes" in res and len(res["quotes"]) > 0:
            best_match = res["quotes"][0]["symbol"]
            search_cache[symbol] = best_match
            return best_match
    except Exception:
        pass
    return symbol


def get_yahoo_info(symbol, exchange, mark_price, fxRateToBase=1.0):
    """Appends suffix for non-US stocks and fetches price."""
    yf_symbol = symbol
    try:
        if exchange and exchange not in US_EXCHANGES:
            print(f"Exchange raw: '{exchange}'")
            suffix = EXCHANGE_MAP.get(exchange)
            print(f"Mapped suffix: '{suffix}' for exchange '{exchange}'")
            if suffix:
                yf_symbol = f"{symbol}{suffix}"
                print(f"Constructed Yahoo symbol: '{yf_symbol}'")
            else:
                yf_symbol = resolve_symbol(symbol)

        stock = yf.Ticker(yf_symbol)
        if exchange == "LSE":
            price = stock.fast_info.get('last_price') / 100  # LSE prices are in pence
        else:
            price = stock.fast_info['last_price']
        currency = stock.fast_info.get("currency", "UNKNOWN")
        print(f"Fetched price for {yf_symbol}: {price} {currency}")
        return float(price) * fxRateToBase, currency, yf_symbol, float(price)
    except Exception:
        return float(mark_price) * fxRateToBase, "UNKNOWN", yf_symbol, float(mark_price)


# ---------------------------------------------------------------------------
# IBKR Flex parsing
# ---------------------------------------------------------------------------

def parse_flex_statements(xml_root):
    latest_positions = {}
    portfolio_prices = {}
    ending_cash = 0.0

    statements = xml_root.findall('.//FlexStatement')
    if not statements:
        return latest_positions, ending_cash

    last_statement = statements[-1]

    cash_report = last_statement.find('CashReport')
    if cash_report is not None:
        base = cash_report.find('CashReportCurrency[@currency="BASE_SUMMARY"]')
        if base is not None:
            ending_cash = float(base.get('endingCash', 0))

    positions = last_statement.find('OpenPositions')
    if positions is not None:
        symbols = []
        for pos in positions.findall('OpenPosition'):
            symbol = pos.attrib['symbol']
            symbol = symbol.rstrip('abcdefghijklmnopqrstuvwxyz')
            exchange = pos.attrib.get('listingExchange', pos.attrib.get('exchange'))
            fxRateToBase = float(pos.attrib['fxRateToBase'])
            qty = float(pos.attrib['position'])
            purchasePrice = float(pos.attrib['costBasisPrice'])
            price, currency, yf_symbol, original_Price = get_yahoo_info(
                symbol, exchange, float(pos.attrib['markPrice']), fxRateToBase
            )

            # Inside parse_flex_statements()
            latest_positions[symbol] = {
                'quantity': qty,
                'current_value': qty * price,
                'currency': currency,
                'yf_symbol': yf_symbol,
                'purchase_price': purchasePrice,
                'fx_rate': fxRateToBase  
            }
            portfolio_prices[symbol] = {
                "purchasePrice": purchasePrice,
                "currentPrice": original_Price
            }
    
            symbols.append(yf_symbol)
            print(f"Processed: {symbol} on {exchange} -> {yf_symbol}")

        with open(PORTFOLIO_JSON, 'w') as f:
            json.dump(symbols, f, indent=2)
        with open(PORTFOLIO_PRICES_JSON, 'w') as f:
            json.dump(portfolio_prices, f, indent=2)

    return latest_positions, ending_cash


# ---------------------------------------------------------------------------
# Dividend parsing  (IBKR accruals + Yahoo Finance future/historical)
# ---------------------------------------------------------------------------
def parse_dividends_colored(xml_root, latest_positions):
    """
    Extracts dividends with precise ex-dates, payout settlement dates, and non-annualized
    yield metrics.  Captures future corporate actions up to 100 days out by
    checking the live forward calendar.

    Priority for future dividends:
      1. ticker.calendar  – officially declared ex-date + lastDividendValue amount
      2. ticker.info      – same data via exDividendDate (Unix ts) + lastDividendValue
      3. ticker.dividends – last historical entry (fallback / awaiting-payment)
    """
    dividends = []
    today = datetime.now().date()
    hundred_days_from_now = today + timedelta(days=4)

    statements = xml_root.findall('.//FlexStatement')
    if not statements:
        return dividends
    last_statement = statements[-1]

    # Statement snapshot date fallback — completely preserved
    report_date_str = today.strftime('%Y-%m-%d')
    when_generated = last_statement.attrib.get('whenGenerated', '')
    if when_generated and ';' in when_generated:
        try:
            raw_date = when_generated.split(';')[0].replace('-', '')
            report_date_str = datetime.strptime(raw_date, '%Y%m%d').strftime('%Y-%m-%d')
        except ValueError:
            pass

    # ------------------------------------------------------------------ #
    # STEP 1 – Build ex-date and pay-date lookup from IBKR accruals      #
    # ------------------------------------------------------------------ #
    ibkr_ex_lookup = {}
    ibkr_pay_lookup = {} # Preserves IBKR internal payment tracking dates
    accruals = last_statement.find('ChangeInDividendAccruals')
    if accruals is not None:
        for acc in accruals.findall('ChangeInDividendAccrual'):
            sym    = acc.attrib.get('underlyingSymbol')
            ex_dt  = acc.attrib.get('exDate')
            pay_dt = acc.attrib.get('payDate')
            if sym and ex_dt and pay_dt:
                try:
                    formatted_ex = datetime.strptime(
                        ex_dt.replace('-', ''), '%Y%m%d'
                    ).strftime('%Y-%m-%d')
                    formatted_pay = datetime.strptime(
                        pay_dt.replace('-', ''), '%Y%m%d'
                    ).strftime('%Y-%m-%d')
                    
                    ibkr_ex_lookup[(sym, pay_dt.replace('-', ''))] = formatted_ex
                    ibkr_pay_lookup[sym] = formatted_pay
                except ValueError:
                    continue

    # ------------------------------------------------------------------ #
    # STEP 2 – Cash transactions settled today → 'paid_today'            #
    # ------------------------------------------------------------------ #
    cash_trans = last_statement.find('CashTransactions')
    print("hey")
    print(last_statement)
    if cash_trans is not None:
        print("kuba")
        for ct in cash_trans.findall('CashTransaction'):
            if ct.attrib.get('dividendType') or \
               "DIVIDEND" in ct.attrib.get('description', '').upper():

                sym        = ct.attrib.get('symbol', 'N/A')
                amt        = float(ct.attrib.get('amount', 0))
                settle_str = ct.attrib.get('settleDate', '').replace('-', '')

                if amt > 0 and settle_str:
                    try:
                        settle_date = datetime.strptime(settle_str, '%Y%m%d').date()
                    except ValueError:
                        continue
                    print("fizi drink")
                    print(settle_date)
                    print(today)
                    if trading_days_between(settle_date, today) <= 4 or settle_date == today:
                        true_ex_date = ibkr_ex_lookup.get((sym, settle_str))
                        print(true_ex_date)
                        print("hej")
                        if not true_ex_date:
                            try:
                                yf_sym = latest_positions.get(sym, {}).get('yf_symbol', sym)
                                tkr = yf.Ticker(yf_sym)
                                if not tkr.dividends.empty:
                                    past_divs = tkr.dividends[
                                        tkr.dividends.index.date <= today
                                    ]
                                    if not past_divs.empty:
                                        true_ex_date = (
                                            past_divs.index[-1].date().strftime('%Y-%m-%d')
                                        )
                            except Exception:
                                pass

                        current_val = latest_positions.get(sym, {}).get('current_value', 0.0)
                        div_yield   = (amt / current_val * 100) if current_val > 0 else 0.0

                        dividends.append({
                            'symbol':      sym,
                            'yf_symbol':   yf_sym,  # <--- ADD THIS LINE
                            'amount':      amt,
                            'ex_date':     true_ex_date if true_ex_date else "Passed",
                            'type':        'paid_today',
                            'declared':    True,
                            'rate':        amt,   
                            'source':      'ibkr',
                            'report_date': settle_date.strftime('%Y-%m-%d'),
                            'div_yield':   round(div_yield, 4),
                        })

    # ------------------------------------------------------------------ #
    # STEP 3 – Future & open positions via Yahoo Finance                  #
    # ------------------------------------------------------------------ #
    already_paid_today = {d['symbol'] for d in dividends if d['type'] == 'paid_today'}

    def get_dividend_info(yf_sym: str) -> dict:
        """
        Fetch dividend metadata for a single ticker.
        """
        result = {
            'declared_ex_date':  None,
            'declared_pay_date': None, # New payload placeholder for forward matching
            'declared_amount':   None,
            'last_ex_date':      None,
            'last_amount':       None,
            'source':            None,
        }

        try:
            ticker = yf.Ticker(yf_sym)

            divs = ticker.dividends
            if not divs.empty:
                result['last_ex_date'] = divs.index[-1].date()
                result['last_amount']  = float(divs.iloc[-1])

            info = ticker.info or {}

            # ----------------------------------------------------------
            # Priority 1 – .calendar (board has formally declared next div)
            # ----------------------------------------------------------
            cal    = ticker.calendar or {}
            cal_ex = cal.get('Ex-Dividend Date')
            cal_pay = cal.get('Dividend Date')

            if cal_ex is not None:
                if hasattr(cal_ex, 'date'):
                    cal_ex = cal_ex.date()          
                elif isinstance(cal_ex, str):
                    cal_ex = datetime.strptime(cal_ex, '%Y-%m-%d').date()

                if isinstance(cal_ex, date) and cal_ex >= today:
                    result['declared_ex_date'] = cal_ex
                    
                    # Safely convert and extract Yahoo's upcoming distribution date
                    if cal_pay is not None:
                        if hasattr(cal_pay, 'date'):
                            cal_pay = cal_pay.date()
                        elif isinstance(cal_pay, str):
                            cal_pay = datetime.strptime(cal_pay, '%Y-%m-%d').date()
                        if isinstance(cal_pay, date):
                            result['declared_pay_date'] = cal_pay.strftime('%Y-%m-%d')

                    amt = info.get('lastDividendValue') or result['last_amount']
                    result['declared_amount'] = float(amt) if amt else None
                    result['source'] = 'calendar_declared'
                    return result

            # ----------------------------------------------------------
            # Priority 2 – info['exDividendDate'] (Unix timestamp)
            # ----------------------------------------------------------
            ex_ts = info.get('exDividendDate')
            if ex_ts:
                ex_date_info = date.fromtimestamp(int(ex_ts))
                if ex_date_info >= today:
                    result['declared_ex_date'] = ex_date_info
                    
                    # Pull forward payout Unix timestamp from info if available
                    pay_ts = info.get('payoutDate')
                    if pay_ts:
                        result['declared_pay_date'] = date.fromtimestamp(int(pay_ts)).strftime('%Y-%m-%d')

                    amt = info.get('lastDividendValue') or result['last_amount']
                    result['declared_amount'] = float(amt) if amt else None
                    result['source'] = 'calendar_info'
                    return result

            # ----------------------------------------------------------
            # Priority 3 – historical only (ex-date already passed)
            # ----------------------------------------------------------
            if result['last_ex_date']:
                result['source'] = 'historical'

        except Exception as e:
            print(f"  [get_dividend_info] {yf_sym}: {e}")

        return result

    # --- Main loop over all open positions ---
    for sym, pos_info in latest_positions.items():
        if sym in already_paid_today:
            continue

        yf_sym  = pos_info.get('yf_symbol', sym)
        qty     = pos_info.get('quantity', 0)
        cur_val = pos_info.get('current_value', 0.0)

        try:
            di = get_dividend_info(yf_sym)

            # Choose ex-date and amount
            if di['declared_ex_date'] and di['declared_amount']:
                target_ex_date = di['declared_ex_date']
                rate_per_share = di['declared_amount']
                is_declared    = True
                # Cascade: Use forward calendar pay date -> fallback to IBKR file -> fallback to statement date
                final_pay_date = di['declared_pay_date'] or ibkr_pay_lookup.get(sym, report_date_str)
            elif di['last_ex_date'] and di['last_amount']:
                target_ex_date = di['last_ex_date']
                rate_per_share = di['last_amount']
                is_declared    = False
                final_pay_date = ibkr_pay_lookup.get(sym, report_date_str)
            else:
                continue  

            if rate_per_share == 0.0:
                continue

            total_payout = rate_per_share * qty
            ex_date_str  = target_ex_date.strftime('%Y-%m-%d')
            div_yield    = (total_payout / cur_val * 100) if cur_val > 0 else 0.0

            base_entry = {
                'symbol':      sym,
                'amount':      total_payout,
                'yf_symbol':   yf_sym,  # <--- ADD THIS LINE
                'ex_date':     ex_date_str,
                'declared':    is_declared,
                'rate':        rate_per_share,
                'source':      di['source'],
                'report_date': final_pay_date, # Seamlessly updates display value to Pay Date without breaking keys
                'div_yield':   round(div_yield, 4),
            }

            if today < target_ex_date and trading_days_between(today, target_ex_date) <= 4:
                dividends.append({**base_entry, 'type': 'pre_ex'})
            elif target_ex_date <= today and trading_days_between(target_ex_date, today) <= 4:
                dividends.append({**base_entry, 'type': 'upcoming'})

        except Exception as e:
            print(f"  [dividend loop] {sym}: {e}")

    return dividends
# ---------------------------------------------------------------------------
# Wallpaper rendering
# ---------------------------------------------------------------------------
def plot_portfolio_pie(fund_data, dividends_list, wallpaper_path_in, output_path):
    # Fetch global consistent color map
    color_map = get_consistent_colors(fund_data)
    
    wallpaper = Image.open(wallpaper_path_in).convert("RGBA")
    PIE_SIZE_zelva = int(wallpaper.height * 0.35) 
    PIE_SIZE_gepard = int(wallpaper.height * 0.55) 

    for fund_name, data in fund_data.items():
        positions = data['positions']
        cash = data['cash']
        
        if not positions and cash == 0:
            continue
            
        labels = list(positions.keys())
        sizes  = [info['current_value'] for info in positions.values()]

        total_portfolio = sum(sizes) + cash
        cash_pct = (cash / total_portfolio) * 100 if total_portfolio > 0 else 0

        # Sort slices by size
        if sizes:
            sorted_data   = sorted(zip(sizes, labels), key=lambda x: x[0])
            sizes, labels = zip(*sorted_data)
            
            # Map the sorted labels to their persistent hex colors
            pie_colors = [color_map.get(label, "#333333") for label in labels]

        fig, ax = plt.subplots(figsize=(12, 12), dpi=150)
        
        if sizes:
            # Inject the custom colors argument here
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=labels,
                colors=pie_colors, 
                autopct="%1.1f%%",
                textprops={'fontsize': 16, 'color': 'black'},
                startangle=90
            )

            for txt in texts:
                txt.set_bbox(dict(facecolor='white', edgecolor='none', alpha=0.7, pad=2))
            for txt in autotexts:
                txt.set_bbox(None)

        # Center text (Invested Percentage)
        plt.text(
            0, 0, f"\n{100 - cash_pct:.2f}%",
            ha='center', va='center',
            fontsize=24, fontweight='bold', color='black'
        )

        # --- DIVIDENDS OVERLAY ---
        # We only attach the dividend text to the 'gepard' fund so it stays cleanly on the right side
        if fund_name == 'gepard' and dividends_list:
            # RENAME THIS VARIABLE to prevent overwriting the outer color_map
            div_color_map = {
                'pre_ex':     '#FFD700',
                'upcoming':   '#7FFF00',
                'paid_today': '#00FF00'
            }
            priority_order = {'pre_ex': 0, 'upcoming': 1, 'paid_today': 2}
            
            dividends_list.sort(key=lambda div: priority_order.get(div['type'], 3))
            upcoming_divs     = [d for d in dividends_list if d['type'] == 'upcoming']
            total_div_amount  = sum(d['amount'] for d in upcoming_divs)

            y_pos = 0.11
            text_x_pos = 0.50  
            
            plt.figtext(
                text_x_pos, y_pos,
                f"DIVIDENDS TO RECEIVE: ${total_div_amount:.2f}",
                ha='center', va='top', fontsize=16, fontweight='bold', color='white'
            )
            y_pos -= 0.038

            max_items = 10
            for div in dividends_list[:max_items]:
                # USE THE RENAMED VARIABLE HERE
                text_color = div_color_map.get(div['type'], 'white')
                action_word = "PAID:" if div['type'] == 'paid_today' else "pay:"
                
                text_str = (
                    f"{div['symbol']} | "
                    f" ${div['amount']:.2f} | "
                    f" {div['div_yield']:.2f}% | "
                    f"Ex: {div['ex_date']} | "
                    f"{action_word} {div['report_date']}"
                )
                plt.figtext(
                    text_x_pos, y_pos, text_str,
                    ha='center', va='top', fontsize=14, color=text_color
                )
                y_pos -= 0.032

            if len(upcoming_divs) > max_items:
                plt.figtext(
                    text_x_pos, y_pos,
                    f"+ {len(upcoming_divs) - max_items} more upcoming entries hidden",
                    ha='center', va='top', fontsize=10, color='gray', fontstyle='italic'
                )
            
        pie_path = f"/tmp/pie_{fund_name}.png"
        plt.savefig(pie_path, bbox_inches="tight", transparent=True)
        plt.close(fig)

        # --- DYNAMIC SIZING FIX ---
        # Determine the correct size for the current loop iteration
        current_pie_size = PIE_SIZE_zelva if fund_name == 'zelva' else PIE_SIZE_gepard

        # Resize the output chart using the correct variable
        pie_img = Image.open(pie_path).convert("RGBA").resize((current_pie_size, current_pie_size))
        
        # --- POSITIONING LOGIC ---
        if fund_name == 'zelva':
            # Mathematically center the chart on the background image
            paste_x = (wallpaper.width - current_pie_size) // 2
            paste_y = (wallpaper.height - current_pie_size) // 2 -180
        else:
            # Place the Gepard chart on the right side
            paste_x = wallpaper.width - current_pie_size - 20
            # Kept your custom offset to push it to the bottom!
            paste_y = 10

        wallpaper.paste(pie_img, (paste_x, paste_y), pie_img)

    if output_path.lower().endswith((".jpg", ".jpeg")):
        wallpaper = wallpaper.convert("RGB")

    wallpaper.save(output_path)
    print(f"Updated wallpaper saved at {output_path}")
# ---------------------------------------------------------------------------
# IBKR Flex fetch helpers
# ---------------------------------------------------------------------------

def fetch_xml(token, query_id):
    url = (
        f"https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/"
        f"GetStatement?t={token}&q={query_id}&v=3"
    )
    print("Final data URL:", url)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return ET.fromstring(response.text), url
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        return ET.fromstring('<Error>Network Failure</Error>'), url


def extract_query(url):
    response = requests.get(url)
    if response.status_code == 200:
        print("SendRequest raw response:", response.text)
        root = ET.fromstring(response.text)
        reference_code = root.find('ReferenceCode')
        if reference_code is not None:
            print("Reference Code:", reference_code.text)
            return reference_code.text
        print("ReferenceCode tag not found in response.")
        return None
    else:
        print(f"Request failed with status code {response.status_code}")
        return None


def load_query_id():
    try:
        with open(QUERY_ID_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def save_query_id(query_id):
    if query_id is None:
        print("ERROR: Cannot save None query_id — check SendRequest response above")
        return
    with open(QUERY_ID_FILE, 'w') as f:
        f.write(query_id)

def export_yahoo_finance_csv(latest_positions):
    """
    Generates an indexed CSV file for Yahoo Finance portfolio import.
    Scales the portfolio to an anonymous $100,000 baseline and forces 
    quantities to whole integers to prevent Yahoo CSV import errors.
    """
    # CRITICAL: Yahoo Finance requires YYYYMMDD format without hyphens
    today_str = "20100105"
    
    # Using a $100,000 baseline ensures your quantities scale up to whole numbers
    INDEX_BASELINE = 100000.0 
    
    # 1. Calculate the total original cost basis in your account's BASE currency
    total_cost_base = 0.0
    for pos in latest_positions.values():
        qty = pos.get('quantity', 0)
        local_cost = pos.get('purchase_price', 0.0)
        fx_rate = pos.get('fx_rate', 1.0)
        total_cost_base += (qty * local_cost * fx_rate)
        
    # 2. Determine the global scaling factor for our $100k baseline
    scale_factor = INDEX_BASELINE / total_cost_base if total_cost_base > 0 else 0
    
    try:
        with open(YAHOO_CSV_PATH, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Symbol', 'Trade Date', 'Purchase Price', 'Quantity'])
            
            for symbol, pos_info in latest_positions.items():
                yf_sym = pos_info.get('yf_symbol', symbol)
                local_cost = pos_info.get('purchase_price', 0.0)
                original_qty = pos_info.get('quantity', 0)
                
                # 3. Scale the quantity and force it into a whole Integer
                adjusted_qty = int(round(original_qty * scale_factor))
                
                # Guardrail: Ensure tiny positions don't round down to 0 shares
                if adjusted_qty <= 0 and original_qty > 0:
                    adjusted_qty = 1
                
                writer.writerow([yf_sym, today_str, local_cost, adjusted_qty])
                
        print(f"Successfully saved clean integer Yahoo CSV to {YAHOO_CSV_PATH}")
        print(f"Portfolio scaled to an anonymous ${INDEX_BASELINE:,} baseline.")
    except Exception as e:
        print(f"Error saving Yahoo Finance CSV: {e}")
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    QUERY_ID = load_query_id()
    xml_root, _ = fetch_xml(TOKEN, QUERY_ID)

    if xml_root.find('ErrorCode') is not None:
        send_url = (
            f"https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/"
            f"SendRequest?t={TOKEN}&q={FLEX_QUERY_ID}&v=3"
        )
        print("Need to restart token:", send_url)
        QUERY_ID = extract_query(send_url)
        save_query_id(QUERY_ID)
        time.sleep(20)
        xml_root, _ = fetch_xml(TOKEN, QUERY_ID)
    if xml_root.find('ErrorCode') is None and xml_root.tag != 'Error':
        save_xml_to_innerdb(xml_root)
    latest_positions, ending_cash = parse_flex_statements(xml_root)
    print(latest_positions)
    export_yahoo_finance_csv(latest_positions)
    # --- NEW CACHING LOGIC ---
    cached_dividends = load_cached_dividends()
    fresh_dividends = parse_dividends_colored(xml_root, latest_positions)
    
    # Merge them to prevent the day-2 rollback
    final_dividends = merge_dividends(cached_dividends, fresh_dividends)
    
    # Save the corrected state back to JSON for tomorrow
    save_cached_dividends(final_dividends)
    # -------------------------
    
    print("DIVIDENDS:", final_dividends)

    # Load the segmented fund data for 'gepard' and 'zelva'
    fund_data = load_pie_data_from_db()

    # Pass the segmented dictionary instead of the single IBKR dictionary
    plot_portfolio_pie(
        fund_data, final_dividends,
        ORIGINAL_WALLPAPER, OUTPUT_WALLPAPER
    )

    with open(ROW_PATH, "w") as f:
        f.write("ibkr")