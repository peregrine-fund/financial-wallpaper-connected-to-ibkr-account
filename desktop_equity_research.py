from datetime import datetime, timedelta
import json
import os
import subprocess
import urllib.parse
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import yfinance as yf
import feedparser

# === FILE PATHS ===
PORTFOLIO_FILE = "/home/your_username/code/innerdb/.portfolio.json"
WALLPAPER_PATH = "/home/your_username/Documents/.wallpaper/picture.jpg"
OUTPUT_PATH = "/home/your_username/Documents/.wallpaper/picture_with_feed.jpg"
WALLPAPER_PATH = OUTPUT_PATH
REPORT_PATH = "/home/your_username/Desktop/report.txt" # New path for your report

# === POSITIONING & STYLING CONFIGURATION ===
POSITION_X_RATIO = 0.235  # Horizontal position ratio
POSITION_Y_RATIO = 0.16   # Vertical position ratio
FONT_SIZE = 26            # Text font size
LINE_SPACING = 12         # Space between lines

WATCHLIST_FILE = "/home/your_username/code/innerdb/important_watchlist.txt"
EXCLUDE_SUBSTACK = ["AAPL", "MSFT", "TSLA", "AMZN", "GOOGL"]


def load_json_tickers(file_path):
    """Helper to load tickers from a JSON file (supports both list or dict formats)."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [
                        t.upper()
                        for t in data
                        if isinstance(t, str) and "." not in t
                    ]
                elif isinstance(data, dict):
                    return [
                        t.upper()
                        for t in data.keys()
                        if isinstance(t, str) and "." not in t
                    ]
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    return []

def load_txt_tickers(file_path):
    """Helper to load tickers from a text file (one ticker per line)."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return [
                    line.strip().upper()
                    for line in f
                    if line.strip() and "." not in line.strip()
                ]
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    return []

def load_combined_tickers():
    """Loads both portfolio and watchlist JSON files and merges them without duplicates."""
    portfolio_tickers = load_json_tickers(PORTFOLIO_FILE)
    watchlist_tickers = load_txt_tickers(WATCHLIST_FILE)

    combined = list(dict.fromkeys(portfolio_tickers + watchlist_tickers))
    print(f"Loaded {len(portfolio_tickers)} portfolio & {len(watchlist_tickers)} watchlist tickers.")
    return combined


def get_recent_rss_items(query, days=14):
    """Fetch and filter Google News RSS items from the last N days."""
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    print(rss_url)
    feed = feedparser.parse(rss_url)
    
    cutoff_date = datetime.now() - timedelta(days=days)
    recent_items = []
    seen_titles = set()
    
    for entry in feed.entries:
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6])
            if pub_date >= cutoff_date:
                title = entry.title.rsplit(' - ', 1)[0].strip()
                if title not in seen_titles:
                    seen_titles.add(title)
                    recent_items.append({
                        "title": title,
                        "date": pub_date.strftime("%Y-%m-%d"),
                        "link": entry.link 
                    })
    return recent_items


def fetch_rss_source_items(query, source_label, days=14, max_title_len=60):
    """Fetch and format news items for any custom search query."""
    raw_items = get_recent_rss_items(query, days=days)
    formatted = []
    for item in raw_items:
        title_trunc = (
            item["title"][:max_title_len] + "..."
            if len(item["title"]) > max_title_len
            else item["title"]
        )
        formatted.append({
            "date": item["date"],
            "wallpaper_text": f"{source_label}: {title_trunc} ({item['date']})",
            "report_name": f"{source_label}: {item['title']}",
            "link": item["link"]
        })
    return formatted


def get_jpm_rating_14d(ticker):
    """Fetch JPMorgan rating action for ticker ONLY if within the last 14 days."""
    try:
        t = yf.Ticker(ticker)
        upgrades = t.upgrades_downgrades

        if upgrades is None or upgrades.empty:
            return None

        df = upgrades.reset_index()

        firm_col = next((col for col in df.columns if col.lower() == "firm"), None)
        if not firm_col:
            return None

        jpm_df = df[
            df[firm_col]
            .astype(str)
            .str.contains(r"JPMorgan|J\.P\. Morgan|JP Morgan", case=False, na=False)
        ].copy()

        if jpm_df.empty:
            return None

        date_col = next(
            (col for col in ["GradeDate", "Date", "date", "index"] if col in jpm_df.columns),
            jpm_df.columns[0],
        )

        jpm_df[date_col] = pd.to_datetime(jpm_df[date_col])
        if jpm_df[date_col].dt.tz is not None:
            jpm_df[date_col] = jpm_df[date_col].dt.tz_localize(None)

        cutoff_date = datetime.now() - timedelta(days=14)
        jpm_df = jpm_df[jpm_df[date_col] >= cutoff_date]

        if jpm_df.empty:
            return None

        jpm_df = jpm_df.sort_values(by=date_col, ascending=False)
        latest = jpm_df.iloc[0]
        date_str = latest[date_col].strftime("%Y-%m-%d")

        action = str(latest.get("Action", latest.get("action", ""))).strip()
        to_grade = str(latest.get("ToGrade", latest.get("toGrade", ""))).strip()
        from_grade = str(latest.get("FromGrade", latest.get("fromGrade", ""))).strip()

        parts = []
        if to_grade and to_grade.lower() != "nan":
            parts.append(to_grade)
        if action and action.lower() != "nan":
            parts.append(f"({action})")
        if from_grade and from_grade.lower() != "nan" and from_grade != to_grade:
            parts.append(f"[prev: {from_grade}]")

        desc = " ".join(parts) if parts else "Updated"

        return {
            "date": date_str,
            "wallpaper_text": f"{ticker} (JPM): {desc} ({date_str})",
            "report_name": f"{ticker} JPM Rating: {desc}",
            "link": f"https://finance.yahoo.com/quote/{ticker}" 
        }
    except Exception as e:
        print(f"Error checking JPM rating for {ticker}: {e}")
        return None


def generate_report_txt(items, filepath):
    """Writes the collected items to a text file for easy clicking."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=== NEWS & UPDATES REPORT ===\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for item in items:
                f.write(f"{item['report_name']} - {item['date']}\n")
                f.write(f"{item['link']}\n\n")
        print(f"Clickable report successfully written to {filepath}")
    except Exception as e:
        print(f"Failed to write report.txt: {e}")


def draw_text_on_wallpaper(lines_to_draw):
    """Draw white text at upper-left-center without any header."""
    if not os.path.exists(WALLPAPER_PATH):
        print(f"Base wallpaper not found: {WALLPAPER_PATH}")
        return

    img = Image.open(WALLPAPER_PATH).convert("RGB")
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size

    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    start_x = int(img_w * POSITION_X_RATIO)
    start_y = int(img_h * POSITION_Y_RATIO)
    current_y = start_y
    white_color = (255, 255, 255)

    for line_text in lines_to_draw:
        draw.text((start_x, current_y), line_text, font=font, fill=white_color)
        bbox = font.getbbox(line_text)
        line_height = bbox[3] - bbox[1]
        current_y += line_height + LINE_SPACING

    img.save(OUTPUT_PATH)
    print(f"Wallpaper saved with {len(lines_to_draw)} recent updates.")


def set_wallpaper():
    """Apply wallpaper in GNOME."""
    try:
        subprocess.run([
            "gsettings", "set", "org.gnome.desktop.background", "picture-uri",
            f"file:///{OUTPUT_PATH}"
        ], check=True)
        subprocess.run([
            "gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark",
            f"file:///{OUTPUT_PATH}"
        ], check=True)
    except Exception as e:
        print(f"Failed to set GNOME wallpaper: {e}")


def main():
    tickers = load_combined_tickers()
    collected_items = []

    # 1. Custom Feed Sources
    custom_sources = [
        {
            "query": 'site:linkedin.com "Hosking Partners"',
            "label": "Hosking (LinkedIn)",
            "days": 14,
        },
        {
            "query": 'site:linkedin.com "Marathon asset management"',
            "label": "Marathon (LinkedIn)",
            "days": 14,
        }
    ]

    for source in custom_sources:
        items = fetch_rss_source_items(
            query=source["query"],
            source_label=source["label"],
            days=source.get("days", 14),
        )
        collected_items.extend(items)
    
    # 2. Process Combined Tickers for JPM Ratings & Substack Mentions
    for ticker in tickers:
        jpm_info = get_jpm_rating_14d(ticker)
        if jpm_info:
            collected_items.append(jpm_info)
        '''
        if ticker not in EXCLUDE_SUBSTACK:
            try:
                t = yf.Ticker(ticker)
                raw_company_name = t.info.get("shortName", ticker)
                
                # Clean up common corporate suffixes so names like "Apple Inc." become "Apple"
                for suffix in [" Inc.", " Corp.", " Ltd.", " Company", " Holdings", " plc"]:
                    raw_company_name = raw_company_name.replace(suffix, "")
                clean_name = raw_company_name.strip()
                
                # Update query to specifically look for the clean name OR the exact spaced ticker
                query = f'site:substack.com ("{clean_name}" OR " {ticker} ")'
                
                items = fetch_rss_source_items(
                    query=query,
                    source_label=f"{ticker} (Substack)",
                    days=14,
                )
                
                # STRICT FILTER: Ensure the name or space-ticker-space actually exists in the article title
                valid_items = []
                target_name = clean_name.lower()
                target_ticker = f" {ticker.lower()} "
                
                for item in items:
                    title_lower = item["report_name"].lower()
                    if target_name in title_lower or target_ticker in title_lower:
                        valid_items.append(item)
                        
                collected_items.extend(valid_items)
            except Exception as e:
                print(f"Error fetching Substack news for {ticker}: {e}")
    '''
    # 3. Sort items by date (newest first)
    collected_items.sort(key=lambda x: x["date"], reverse=True)

    # 4. Generate text file for clicking URLs
    if collected_items:
        generate_report_txt(collected_items, REPORT_PATH)
    else:
        print("No new updates found to write to report.")

    # 5. Draw on wallpaper & set
    display_lines = [item["wallpaper_text"] for item in collected_items]
    if display_lines:
        draw_text_on_wallpaper(display_lines)
        set_wallpaper()
    else:
        print("No new updates in the last specified days to draw.")


if __name__ == "__main__":
    main()