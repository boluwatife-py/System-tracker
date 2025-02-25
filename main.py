import sqlite3
import psutil
import pygetwindow as gw
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import os
import platform
import subprocess
import json
import pystray
from PIL import Image
import threading
import tkinter as tk
from tkinter import filedialog

# Default settings
DEFAULT_SETTINGS = {
    "open_mode": "all_at_once",  # or "one_by_one"
    "icon_path": "default_icon.ico"  # Default icon (you'll need to provide one)
}

# Load or create settings
SETTINGS_FILE = "settings.json"
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return DEFAULT_SETTINGS

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f)

# Database setup
def setup_database():
    conn = sqlite3.connect('system_state.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS windows 
                 (id INTEGER PRIMARY KEY, app_name TEXT, title TEXT, 
                 x INTEGER, y INTEGER, width INTEGER, height INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chrome_tabs 
                 (id INTEGER PRIMARY KEY, profile TEXT, url TEXT)''')
    conn.commit()
    return conn

# Save current state
def save_state(conn):
    c = conn.cursor()
    c.execute("DELETE FROM windows")
    c.execute("DELETE FROM chrome_tabs")
    
    windows = gw.getAllWindows()
    for win in windows:
        if win.title:
            c.execute("INSERT INTO windows (app_name, title, x, y, width, height) VALUES (?, ?, ?, ?, ?, ?)",
                     (win.title.split('-')[-1].strip(), win.title, win.left, win.top, win.width, win.height))
    
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get("chrome://version/")
        profile_path = driver.find_element_by_xpath("//td[@id='profile_path']").text
        driver.execute_script("window.open('');")
        tabs = driver.window_handles
        for tab in tabs:
            driver.switch_to.window(tab)
            url = driver.current_url
            if url and url != "about:blank":
                c.execute("INSERT INTO chrome_tabs (profile, url) VALUES (?, ?)",
                         (profile_path, url))
        driver.quit()
    except Exception as e:
        print(f"Error getting Chrome tabs: {e}")
    
    conn.commit()

# Restore state
def restore_state(conn, settings):
    c = conn.cursor()
    c.execute("SELECT DISTINCT app_name, title, x, y, width, height FROM windows")
    windows = c.fetchall()
    
    def open_app(app_name, title, x, y, width, height):
        try:
            if "Chrome" in app_name:
                return
            if platform.system() == "Windows":
                subprocess.Popen(app_name)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", app_name])
            time.sleep(1)
            win = gw.getWindowsWithTitle(title)[0]
            win.moveTo(x, y)
            win.resizeTo(width, height)
        except Exception as e:
            print(f"Error restoring {app_name}: {e}")

    if settings["open_mode"] == "all_at_once":
        for app_name, title, x, y, width, height in windows:
            open_app(app_name, title, x, y, width, height)
    else:  # one_by_one
        for app_name, title, x, y, width, height in windows:
            open_app(app_name, title, x, y, width, height)
            time.sleep(2)  # Delay between apps

    c.execute("SELECT profile, url FROM chrome_tabs")
    tabs = c.fetchall()
    if tabs:
        try:
            options = webdriver.ChromeOptions()
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            for _, url in tabs:
                driver.execute_script(f"window.open('{url}');")
            chrome_win = gw.getWindowsWithTitle("Chrome")[0]
            first_chrome = c.execute("SELECT x, y, width, height FROM windows WHERE app_name LIKE '%Chrome%'").fetchone()
            if first_chrome:
                chrome_win.moveTo(first_chrome[0], first_chrome[1])
                chrome_win.resizeTo(first_chrome[2], first_chrome[3])
            time.sleep(2)
            driver.quit()
        except Exception as e:
            print(f"Error restoring Chrome: {e}")

# System tray icon
def setup_tray_icon(settings, stop_event):
    try:
        image = Image.open(settings["icon_path"])
    except:
        # Fallback to a simple default icon if none provided
        image = Image.new('RGB', (64, 64), color='blue')
    icon = pystray.Icon("SystemState", image, "System State Tracker")
    
    def on_quit():
        stop_event.set()
        icon.stop()
    
    icon.menu = pystray.Menu(pystray.MenuItem("Quit", on_quit))
    icon.run()

# Settings GUI
def settings_gui(settings):
    root = tk.Tk()
    root.title("Settings")
    root.geometry("300x200")

    tk.Label(root, text="Open Mode:").pack(pady=5)
    mode_var = tk.StringVar(value=settings["open_mode"])
    tk.Radiobutton(root, text="All at Once", variable=mode_var, value="all_at_once").pack()
    tk.Radiobutton(root, text="One by One", variable=mode_var, value="one_by_one").pack()

    tk.Label(root, text="Icon Path:").pack(pady=5)
    icon_path_var = tk.StringVar(value=settings["icon_path"])
    tk.Entry(root, textvariable=icon_path_var, width=30).pack()
    tk.Button(root, text="Browse", command=lambda: icon_path_var.set(filedialog.askopenfilename(filetypes=[("Icon files", "*.ico")]))).pack()

    def save_and_close():
        settings["open_mode"] = mode_var.get()
        settings["icon_path"] = icon_path_var.get()
        save_settings(settings)
        root.destroy()

    tk.Button(root, text="Save", command=save_and_close).pack(pady=10)
    root.mainloop()

def main():
    settings = load_settings()
    
    # Show settings GUI if settings file doesn't exist or on demand
    if not os.path.exists(SETTINGS_FILE):
        settings_gui(settings)
        settings = load_settings()

    conn = setup_database()
    stop_event = threading.Event()

    # Start tray icon in a separate thread
    tray_thread = threading.Thread(target=setup_tray_icon, args=(settings, stop_event), daemon=True)
    tray_thread.start()

    if os.path.getsize('system_state.db') > 0:
        print("Restoring previous state...")
        restore_state(conn, settings)
    else:
        print("Saving current state...")
        save_state(conn)
    
    conn.close()
    
    # Keep script running until tray icon is quit
    stop_event.wait()

if __name__ == "__main__":
    main()