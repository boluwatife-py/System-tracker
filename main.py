import sqlite3
import psutil
import pygetwindow as gw
import time
import os
import platform
import subprocess
import pystray
from PIL import Image
import threading
import webbrowser

# Hardcoded settings
SETTINGS = {
    "icon_path": "default_icon.ico",  # Provide your own .ico file
    "closure_delay": 120  # 2 minutes in seconds
}

# Known executable mappings (update paths as needed)
APP_EXECUTABLES = {
    "Notepad": "notepad.exe",
    "Visual Studio Code": "C:\\Users\\BOLUWATIFE\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    "Calculator": "calc.exe",
    "Settings": "ms-settings:",
    "Google Chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
}

# Database setup
def setup_database():
    conn = sqlite3.connect('system_state.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS windows 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, app_name TEXT, title TEXT, 
                 exe_path TEXT, x INTEGER, y INTEGER, width INTEGER, height INTEGER, closed_time REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chrome_tabs 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT)''')
    conn.commit()
    return conn

# Get executable path from window
def get_exe_from_window(win):
    try:
        hwnd = win._hWnd  # Use window handle directly
        for proc in psutil.process_iter(['pid', 'exe', 'name']):
            if proc.pid == hwnd:  # Note: This might need adjustment; see below
                exe = proc.info['exe']
                if exe and os.path.exists(exe):
                    return exe
    except Exception as e:
        print(f"Error getting exe for {win.title}: {e}")
    return None

# Save current state to database
def save_state(conn):
    c = conn.cursor()
    
    current_windows = gw.getAllWindows()
    print(f"Detected {len(current_windows)} windows")
    
    current_titles = {win.title for win in current_windows if win.title}
    
    c.execute("SELECT id, title, closed_time FROM windows")
    db_windows = {row[1]: (row[0], row[2]) for row in c.fetchall()}
    
    # Mark closed windows
    for title, (db_id, closed_time) in db_windows.items():
        if title not in current_titles and closed_time is None:
            print(f"Marking {title} as closed at {time.time()}")
            c.execute("UPDATE windows SET closed_time = ? WHERE id = ?", (time.time(), db_id))
    
    # Add or update open windows
    for win in current_windows:
        if win.title and win.visible:
            exe_path = get_exe_from_window(win)
            app_name = win.title.split('-')[-1].strip() if '-' in win.title else win.title
            # Only save if we have a valid executable or a known mapping
            if exe_path or app_name in APP_EXECUTABLES:
                exe_path = exe_path or APP_EXECUTABLES.get(app_name)
                if win.title in db_windows:
                    c.execute("UPDATE windows SET app_name = ?, exe_path = ?, x = ?, y = ?, width = ?, height = ?, closed_time = NULL WHERE title = ?",
                             (app_name, exe_path, win.left, win.top, win.width, win.height, win.title))
                else:
                    c.execute("INSERT INTO windows (app_name, title, exe_path, x, y, width, height) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (app_name, win.title, exe_path, win.left, win.top, win.width, win.height))
                    print(f"Saved new window: {win.title} with exe: {exe_path}")
    
    # Remove windows closed for more than 2 minutes
    delay = SETTINGS["closure_delay"]
    c.execute("DELETE FROM windows WHERE closed_time IS NOT NULL AND ? - closed_time > ?", (time.time(), delay))
    
    # Save Chrome tabs (basic detection)
    chrome_windows = [w for w in current_windows if "Google Chrome" in w.title]
    if chrome_windows and not c.execute("SELECT COUNT(*) FROM chrome_tabs").fetchone()[0]:
        sample_urls = ["https://google.com", "https://example.com"]
        for url in sample_urls:
            c.execute("INSERT INTO chrome_tabs (url) VALUES (?)", (url,))
        print(f"Added sample Chrome tabs: {sample_urls}")
    
    conn.commit()
    c.execute("SELECT COUNT(*) FROM windows")
    print(f"Windows in DB after save: {c.fetchone()[0]}")
    c.execute("SELECT COUNT(*) FROM chrome_tabs")
    print(f"Tabs in DB after save: {c.fetchone()[0]}")

# Restore state from database
def restore_state(conn):
    c = conn.cursor()
    
    c.execute("SELECT app_name, title, exe_path, x, y, width, height FROM windows WHERE closed_time IS NULL")
    windows = c.fetchall()
    print(f"Found {len(windows)} windows to restore")
    
    for app_name, title, exe_path, x, y, width, height in windows:
        try:
            if "Chrome" in app_name:
                continue
            exe = APP_EXECUTABLES.get(app_name, exe_path)
            if not exe or not (os.path.exists(exe) or exe.startswith("ms-settings:")):
                print(f"Skipping {app_name}: Invalid or missing executable {exe}")
                continue
            print(f"Restoring {app_name} with title {title} using {exe}")
            if exe.startswith("ms-settings:"):
                os.system(f"start {exe}")
            else:
                subprocess.Popen(exe)
            time.sleep(1)
            win = gw.getWindowsWithTitle(title)
            if win:
                win[0].moveTo(x, y)
                win[0].resizeTo(width, height)
            else:
                print(f"Could not find window with title {title} after launch")
        except Exception as e:
            print(f"Error restoring {app_name}: {e}")
    
    c.execute("SELECT url FROM chrome_tabs")
    tabs = c.fetchall()
    print(f"Found {len(tabs)} tabs to restore")
    
    if tabs:
        try:
            chrome_exe = APP_EXECUTABLES.get("Google Chrome")
            if not chrome_exe or not os.path.exists(chrome_exe):
                chrome_exe = "chrome"
            for tab in tabs:
                url = tab[0]  # Fixed: Correct tuple unpacking
                print(f"Opening tab: {url}")
                subprocess.Popen([chrome_exe, url])
            time.sleep(2)
            chrome_win = gw.getWindowsWithTitle("Chrome")
            if chrome_win:
                first_chrome = c.execute("SELECT x, y, width, height FROM windows WHERE app_name LIKE '%Chrome%' AND closed_time IS NULL").fetchone()
                if first_chrome:
                    chrome_win[0].moveTo(first_chrome[0], first_chrome[1])
                    chrome_win[0].resizeTo(first_chrome[2], first_chrome[3])
            else:
                print("No Chrome window found after restoration")
        except Exception as e:
            print(f"Error restoring Chrome tabs: {e}")

# System tray icon
def setup_tray_icon(stop_event):
    try:
        image = Image.open(SETTINGS["icon_path"])
    except:
        image = Image.new('RGB', (64, 64), color='blue')
    icon = pystray.Icon("WorkspaceSaver", image, "Workspace Saver")
    
    def on_quit():
        stop_event.set()
        icon.stop()
    
    icon.menu = pystray.Menu(pystray.MenuItem("Quit", on_quit))
    icon.run()

# Main monitoring loop
def monitor_and_save(conn, stop_event):
    restore_done = False
    while not stop_event.is_set():
        if not restore_done and os.path.exists('system_state.db'):
            print("Restoring previous workspace...")
            restore_state(conn)
            restore_done = True
        
        save_state(conn)
        time.sleep(5)

def main():
    conn = setup_database()
    stop_event = threading.Event()

    tray_thread = threading.Thread(target=setup_tray_icon, args=(stop_event,), daemon=True)
    tray_thread.start()

    monitor_and_save(conn, stop_event)
    
    conn.close()

if __name__ == "__main__":
    main()