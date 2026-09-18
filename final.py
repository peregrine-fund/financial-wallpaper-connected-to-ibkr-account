import subprocess
import time
import socket
from datetime import date
import sys  
import holidays  
import os


# --- NEW: INTERNET CHECK FUNCTION ---
def wait_for_internet(host="8.8.8.8", port=53, timeout=3):
    """
    Waits until the network is reachable.
    8.8.8.8 is Google's Public DNS.
    """
    print("Checking for internet connection...")
    while True:
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            print("Internet connected!")
            return
        except (socket.error, Exception):
            print("No connection yet. Retrying in 2 seconds...")
            time.sleep(2)

# --- SETUP PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

WEEKEND_FILE = os.path.join(BASE_DIR, ".weekendcheck.txt")
ROW_FILE = "/home/your_username/Documents/.wallpaper/row.txt"

# --- 0. CHECK FOR WEEKEND OR US HOLIDAY ---
today = date.today()
us_holidays = holidays.UnitedStates()

is_weekend = today.weekday() >= 5
is_holiday = today in us_holidays

bypass_check = len(sys.argv) > 1

# Write status to lever file
status_val = "1" if (is_weekend or is_holiday) else "0"
with open(WEEKEND_FILE, "w") as f:
    f.write(status_val)

# Read lever file
with open(WEEKEND_FILE, "r") as f:
    weekend_lever = f.read().strip()

if (is_weekend or is_holiday) and not bypass_check and weekend_lever != "0":
    print("Market closed (Weekend/Holiday). Exiting.")
    sys.exit()

# Wait for internet before proceeding to script execution
wait_for_internet()

# 1. PREPARE THE CANVAS
import shutil
shutil.copy2("/home/your_username/Documents/.wallpaper/picture.jpg", "/home/your_username/Documents/.wallpaper/picture_with_feed.jpg")

# 2. RUN SCRIPTS IN ORDER
# Run IBKR script
subprocess.run(["python3", os.path.join(BASE_DIR, "desktopibkr.py")])

# Wait for 2 seconds
time.sleep(2)

subprocess.run(["python3", os.path.join(BASE_DIR, "desktopfutures.py")])
subprocess.run(["python3", os.path.join(BASE_DIR, "desktop_equity_research.py")])
subprocess.run(["python3", os.path.join(BASE_DIR, "desktoprss.py")])

shutil.copy2("/home/your_username/Documents/.wallpaper/picture_with_feed.jpg", "/home/your_username/Documents/.wallpaper/wallpaper.jpg")

subprocess.run(["python3", os.path.join(BASE_DIR, "desktopinsider.py")])

shutil.copy2("/home/your_username/Documents/.wallpaper/picture_with_feed.jpg", "/home/your_username/Documents/.wallpaper/wallpaper.jpg")

subprocess.run(["python3", os.path.join(BASE_DIR, "desklet.py")])