import json
import threading
import time
from datetime import date
from flask import Flask, render_template, redirect, request
from flask_socketio import SocketIO
from kiteconnect import KiteConnect, KiteTicker
from kiteconnect.exceptions import TokenException

# ---------------- Flask Setup ----------------
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ---------------- Zerodha Credentials ----------------
import os

API_KEY = os.getenv("ZERODHA_API_KEY")
API_SECRET = os.getenv("ZERODHA_API_SECRET")

ACCESS_TOKEN_FILE = "access_token.json"

# ---------------- Instrument Tokens (NSE) ----------------
TOKENS = {
    738561: "RELIANCE",
    2953217: "TCS",
    408065: "INFY",
    341249: "HDFCBANK",
    1270529: "ICICIBANK",
    779521: "SBIN",
    492033: "KOTAKBANK",
    2939649: "LT",
    1850625: "HCLTECH",
    1510401: "AXISBANK",
    2815745: "MARUTI",
    4267265: "BAJAJ-AUTO",
    969473: "WIPRO",
    424961: "ITC",
    633601: "ONGC",
    2977281: "NTPC",
    3834113: "POWERGRID",
    897537: "TITAN",
    2952193: "ULTRACEMCO",
    60417: "ASIANPAINT",
    356865: "HINDUNILVR",
    857857: "SUNPHARMA",
    225537: "DRREDDY",
    3001089: "JSWSTEEL",
    884737: "TATAMOTORS",
    6401: "ADANIENT",
    3861249: "ADANIPORTS",
    1790465: "COALINDIA",
    558337: "BPCL",
    315393: "GRASIM"
}

# ---------------- Logos Mapping ----------------
LOGOS = {symbol: f"https://logo.clearbit.com/{symbol.lower()}.com" for symbol in TOKENS.values()}

# ---------------- KiteConnect Setup ----------------
kite = KiteConnect(api_key=API_KEY)
kws = None

# ---------------- Helper Functions ----------------
def load_access_token():
    try:
        with open(ACCESS_TOKEN_FILE, "r") as f:
            data = json.load(f)
            token_date = data.get("date")
            token = data.get("access_token")
            if token_date == str(date.today()):
                return token
    except:
        pass
    return None

def save_access_token(token):
    with open(ACCESS_TOKEN_FILE, "w") as f:
        json.dump({"date": str(date.today()), "access_token": token}, f)

def get_access_token(request_token):
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)
    save_access_token(access_token)
    return access_token

# ---------------- Flask Routes ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login")
def login():
    return redirect(kite.login_url())

@app.route("/callback")
def callback():
    request_token = request.args.get("request_token")
    if not request_token:
        return "❌ Request token missing"
    try:
        get_access_token(request_token)
        threading.Thread(target=start_kite_ws, daemon=True).start()
        return "✅ Login successful. WebSocket started."
    except Exception as e:
        return f"❌ Error: {e}"

# ---------------- Kite WebSocket ----------------
def on_connect(ws, response):
    print("✅ Zerodha WebSocket Connected")
    ws.subscribe(list(TOKENS.keys()))
    ws.set_mode(ws.MODE_FULL, list(TOKENS.keys()))

def on_ticks(ws, ticks):
    for t in ticks:
        symbol = TOKENS.get(t["instrument_token"])
        filtered_data = {
            "Symbol": symbol,
            "Logo": LOGOS.get(symbol),
            "Time": t.get("last_trade_time"),
            "Open": t.get("ohlc", {}).get("close", 0),
            "High": t.get("ohlc", {}).get("high", 0),
            "Low": t.get("ohlc", {}).get("low", 0),
            "Close": t.get("last_price", 0),
            "LTP": t.get("last_price", 0),
            "TradedQty": t.get("volume", 0)
        }
        socketio.emit("stock_update", filtered_data)

def on_close(ws, code, reason):
    print("⚠️ WebSocket Closed:", reason)

def on_error(ws, code, reason):
    print("❌ WebSocket Error:", reason)

def start_kite_ws():
    global kws
    access_token = load_access_token()
    if not access_token:
        print("❌ Access token missing or expired. Go to /login first.")
        return

    kite.set_access_token(access_token)
    kws = KiteTicker(API_KEY, access_token)
    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_close = on_close
    kws.on_error = on_error
    try:
        kws.connect(threaded=True)
    except TokenException:
        print("❌ Access token expired. Visit /login to generate a new one.")

# ---------------- Main ----------------
if __name__ == "__main__":
    # Start WS if access token exists
    threading.Thread(target=start_kite_ws, daemon=True).start()
    socketio.run(app, host="0.0.0.0", port=5000)
