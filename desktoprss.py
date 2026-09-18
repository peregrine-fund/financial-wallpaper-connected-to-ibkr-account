import os
import json
import requests
import feedparser
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import subprocess
import shutil
import time

# === CONFIG ===
PORTFOLIO_FILE = "/home/your_username/code/innerdb/.portfolio.json"
WALLPAPER_PATH = "/home/your_username/Documents/.wallpaper/picture.jpg"
OUTPUT_PATH = "/home/your_username/Documents/.wallpaper/picture_with_feed.jpg"
CIK_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "YOUR_NAME your_email@example.com"}
MAX_FILINGS = 5
MAX_DISPLAY = 10
row_path = '/home/your_username/Documents/.wallpaper/row.txt'

# CACHES TO KEEP BOTH SCRIPTS IN SYNC ON THE SAME WALLPAPER
CACHE_SEC = "/home/your_username/code/innerdb/.sec_cache.json"
CACHE_INSIDER = "/home/your_username/code/innerdb/.insider_cache.json"

CIK_MAPPING = {}

def load_cik_mapping():
    global CIK_MAPPING
    try:
        print("Downloading CIK mapping...")
        r = requests.get(CIK_TICKER_URL, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        CIK_MAPPING = {entry["ticker"].upper(): str(entry["cik_str"]).zfill(10) for entry in data.values()}
    except Exception as e:
        print(f"Failed to load CIK mapping: {e}")

def get_cik_from_ticker(ticker):
    return CIK_MAPPING.get(ticker.upper())

def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return []

def get_filings_for_ticker(ticker):
    cik = get_cik_from_ticker(ticker)
    if not cik:
        return []
    
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&count={MAX_FILINGS}&output=atom"
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        
        unique_filings = {} 
        
        for entry in feed.entries:
            title = entry.title.upper()
            if "13G/A" in title:
                continue
            
            form_type = title.split()[0] 
            key = f"{ticker}_{form_type}"
            
            if key not in unique_filings:
                date_str = entry.get("published", entry.get("updated", ""))
                try:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z")
                except:
                    date_obj = None
                
                unique_filings[key] = {
                    "ticker": ticker,
                    "title": entry.title,
                    "date": date_obj,
                    "date_str": date_str
                }
        
        return list(unique_filings.values())
    except Exception as e:
        print(f"Error fetching filings for {ticker}: {e}")
        return []

# === CACHE HELPERS ===
def save_cache(filepath, data):
    serialized = []
    for d in data:
        item = d.copy()
        if item.get("date"):
            item["date"] = item["date"].isoformat()
        serialized.append(item)
    with open(filepath, "w") as f:
        json.dump(serialized, f)

def load_cache(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        data = json.load(f)
    deserialized = []
    for d in data:
        item = d.copy()
        if item.get("date"):
            item["date"] = datetime.fromisoformat(item["date"])
        deserialized.append(item)
    return deserialized

# === DRAW TEXT ON IMAGE ===
def draw_text_on_wallpaper(all_filings, screen_filings):
    source_path = ""
    if os.path.exists(row_path):
        with open(row_path, "r") as f:
            mode = f.read().strip().lower()
        
        if mode == "false neni tady nic jen to nechci prepracovat":
            source_path = WALLPAPER_PATH
            img = Image.open(source_path).convert("RGB")
        else:
            source_path = OUTPUT_PATH
            base_img = Image.open(OUTPUT_PATH if os.path.exists(OUTPUT_PATH) else WALLPAPER_PATH).convert("RGB")
            original_img = Image.open(WALLPAPER_PATH).convert("RGB")
            w, h = base_img.size
            overlay_width = int(w * 0.55)
            overlay_height = int(h * 0.40)
            x1 = w - overlay_width
            y1 = h - overlay_height
            x2 = w
            y2 = h
            restored_region = original_img.crop((x1, y1, x2, y2))
            base_img.paste(restored_region, (x1, y1))
            img = base_img

        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 30)
        except:
            font = ImageFont.load_default()

        margin = 20
        line_height = font.getbbox("A")[3] + 8
        img_w, img_h = img.size
        BUFFER_FROM_DATE = 50

        # --- ALL FILINGS ---
        all_filings = sorted(all_filings, key=lambda f: f["date"] or datetime.min, reverse=True)
        all_filings = all_filings[:MAX_DISPLAY]
        retrieved_time = datetime.now().strftime("%d %b %Y %H:%M")
        header_text = f"Retrieved: {retrieved_time}"
        y_start_date_header = img_h - margin*3 - line_height * (len(all_filings) + 1)
        header_bbox = font.getbbox(header_text)
        header_w = header_bbox[2] - header_bbox[0]
        x_header = img_w - header_w - margin
        draw.text((x_header, y_start_date_header), header_text, font=font, fill=(255, 255, 0))

        y = y_start_date_header + line_height
        for f in all_filings:
            line = f"{f['ticker']}: {f['title']} ({f['date'].strftime('%Y-%m-%d') if f['date'] else f['date_str']})"
            bbox = font.getbbox(line)
            w = bbox[2] - bbox[0]
            x = img_w - w - margin
            draw.text((x, y), line, font=font, fill=(255, 255, 255))
            y += line_height

        # --- SCREEN FILINGS ---
        y_screen_end = y_start_date_header - BUFFER_FROM_DATE
        screen_filings = sorted(screen_filings, key=lambda f: f["date"] or datetime.min, reverse=True)
        num_screen_lines = len(screen_filings[:MAX_DISPLAY])
        if num_screen_lines > 0:
            total_height = (num_screen_lines + 1) * line_height
            y_screen_start = y_screen_end - total_height
            screen_header_text = "Insider Filings (Form 4)"
            y_current = y_screen_start
            draw.text((img_w - margin - font.getbbox(screen_header_text)[2], y_current),
                      screen_header_text, font=font, fill=(255, 255, 255))
            y_current += line_height
            for f in screen_filings[:MAX_DISPLAY]:
                line = f"{f['ticker']}: {f['title']} ({f['date'].strftime('%Y-%m-%d') if f['date'] else f['date_str']})"
                bbox = font.getbbox(line)
                w = bbox[2] - bbox[0]
                x = img_w - w - margin
                
                if "-" in f['title']:
                    text_color = (255, 80, 80)
                else:
                    text_color = (80, 255, 80)

                draw.text((x, y_current), line, font=font, fill=text_color)
                y_current += line_height

        img.save(OUTPUT_PATH)

def set_wallpaper():
    subprocess.run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri", f"file:///{OUTPUT_PATH}"])
    subprocess.run(["gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", f"file:///{OUTPUT_PATH}"])

def main():
    load_cik_mapping()
    portfolio = load_portfolio()
    
    all_filings = []
    
    # 1. Process Portfolio
    for ticker in portfolio:
        all_filings.extend(get_filings_for_ticker(ticker))
        time.sleep(0.1)

    # Cache SEC filings and load latest insider filings
    save_cache(CACHE_SEC, all_filings)
    screen_filings = load_cache(CACHE_INSIDER)

    # 3. Finalize Image
    draw_text_on_wallpaper(all_filings, screen_filings)
    set_wallpaper()
    
    # 4. Finalize Files
    with open(row_path, "w") as f:
        f.write("rss")
            
    print("SEC filings updated successfully.")
    shutil.copy2("/home/your_username/Documents/.wallpaper/picture_with_feed.jpg", "/home/your_username/Documents/.wallpaper/wallpaper.jpg")

if __name__ == "__main__":
    main()