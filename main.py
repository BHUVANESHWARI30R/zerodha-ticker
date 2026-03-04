import os
import json
import threading
import webbrowser
from datetime import datetime
from flask import Flask, render_template, redirect, request
from flask_socketio import SocketIO
from kiteconnect import KiteConnect, KiteTicker
from kiteconnect.exceptions import TokenException

# ---------------- Flask Setup ----------------
app = Flask(__name__)
from flask_socketio import SocketIO

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ---------------- Save tokens file ----------------
TOKEN_FILE = "tokens.json"

def save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "tokens": tokens,
            "date": datetime.now().strftime("%Y-%m-%d")
        }, f)

def load_tokens():
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)

        if data["date"] == datetime.now().strftime("%Y-%m-%d"):
            print("✅ Using cached tokens")
            return {int(k): v for k, v in data["tokens"].items()}
    except:
        pass

    return None

# ---------------- Zerodha Credentials ----------------
API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")
ACCESS_TOKEN_FILE = "access_token.json"

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Set KITE_API_KEY and KITE_API_SECRET in environment variables!")

# ---------------- Instrument Tokens ----------------
TOKENS = {}
ws_running = False
#-----------------Tokens Loading ----------------
def get_instrument_tokens():
    """Fetch latest instrument tokens from Zerodha in alphabetical order"""
    print("📥 Fetching latest instrument tokens...")

    instruments = kite.instruments(exchange="NSE")

    required_symbols = [
        "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK","BAJAJ-AUTO",
        "BAJAJFINSV","BAJFINANCE","BPCL","BRITANNIA","CIPLA","COALINDIA",
        "DABUR","DIVISLAB","DRREDDY","EICHERMOT","GRASIM","HCLTECH",
        "HDFCBANK","HDFCLIFE","HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK",
        "INDUSINDBK","INFY","IOC","ITC","JSWSTEEL","KOTAKBANK",
        "LT","M&M","MARUTI","NESTLEIND","NTPC","ONGC",
        "PIDILITIND","POWERGRID","RELIANCE","SBIN","SBILIFE","SHREECEM",
        "SIEMENS","SUNPHARMA","TATAMOTORS","TATASTEEL","TECHM","TITAN",
        "ULTRACEMCO","UPL","WIPRO"
    ]

    # 🔹 sort alphabetically
    required_symbols.sort()

    symbol_to_token = {}

    # build lookup for faster matching
    instrument_lookup = {item["tradingsymbol"]: item["instrument_token"] for item in instruments}

    # create token mapping in sorted order
    for symbol in required_symbols:
        token = instrument_lookup.get(symbol)
        if token:
            symbol_to_token[token] = symbol

    return symbol_to_token

# ---------------- Kite Setup ----------------
kite = KiteConnect(api_key=API_KEY)
kws = None

# ---------------- Token Helpers ----------------
def load_access_token():
    """Load access token from file if not expired"""
    try:
        with open(ACCESS_TOKEN_FILE, "r") as f:
            data = json.load(f)
            token = data.get("access_token")
            expires_at = data.get("expires_at")
            if token and expires_at:
                if datetime.now().timestamp() < expires_at:
                    return token
    except:
        pass
    return None

def save_access_token(token, expires_in=24*60*60):
    """Save access token with expiry timestamp (default 24h)"""
    expires_at = datetime.now().timestamp() + expires_in
    with open(ACCESS_TOKEN_FILE, "w") as f:
        json.dump({"access_token": token, "expires_at": expires_at}, f)

def generate_access_token(request_token):
    """Generate new access token from request token"""
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    access_token = data["access_token"]
    kite.set_access_token(access_token)
    save_access_token(access_token)
    return access_token

# ---------------- Routes ----------------
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
        generate_access_token(request_token)

        # ✅ Correct way with eventlet
        socketio.start_background_task(start_kite_ws)

        return "✅ Login successful. WebSocket started. You can now close this page."
    except Exception as e:
        return f"❌ Error: {e}"
    
# ---------------- Kite WebSocket ----------------
def on_connect(ws, response):
    print("✅ Zerodha WebSocket Connected")

    tokens_list = list(map(int, TOKENS.keys()))

    print("📡 Subscribing to", len(tokens_list), "tokens")

    # small delay prevents frame corruption
    import time
    time.sleep(1)

    ws.subscribe(tokens_list)
    ws.set_mode(ws.MODE_QUOTE, tokens_list)

    print("✅ Subscription sent successfully")

def on_ticks(ws, ticks):
    print("📊 Tick received:", len(ticks))

    for t in ticks:
        token = t["instrument_token"]
        symbol = TOKENS.get(token)

        if not symbol:
            continue

        ltp = t.get("last_price", 0)
        prev_close = t.get("ohlc", {}).get("close")

        if not ltp or not prev_close:
            continue

        # ✅ Calculate absolute change
        change = ltp - prev_close

        # ✅ Calculate percentage change
        change_percent = (change / prev_close) * 100

        payload = {
            "symbol": symbol,
            "ltp": round(ltp, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2)
        }

        print("📤 Emitting:", payload)
        socketio.emit("stock_update", payload)
        
def on_close(ws, code, reason):
    global ws_running
    print("⚠️ WebSocket closed:", reason)
    ws_running = False

def on_error(ws, code, reason):
    global ws_running
    print("❌ WebSocket error:", reason)
    ws_running = False

def start_kite_ws():
    global TOKENS, kws, ws_running

    if ws_running:
        print("⚠️ WebSocket already running. Skipping restart.")
        return

    print("🚀 start_kite_ws() called")

    access_token = load_access_token()
    print("🔐 Access Token:", "FOUND" if access_token else "NOT FOUND")

    if not access_token:
        print("❌ No access token found.")
        return

    kite.set_access_token(access_token)

    # -------- Load Tokens --------
    try:
        TOKENS = load_tokens()

        if not TOKENS:
            print("📥 Fetching fresh tokens...")
            TOKENS = get_instrument_tokens()

            if not TOKENS:
                print("❌ Token fetch failed")
                return

            save_tokens(TOKENS)

        print("✅ Tokens ready:", len(TOKENS))

    except Exception as e:
        print("❌ Token loading failed:", e)
        return
    # -----------------------------

    kws = KiteTicker(API_KEY, access_token)

    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_close = on_close
    kws.on_error = on_error

    print("📡 Connecting to Zerodha WebSocket...")
    ws_running = True

    try:
        kws.connect()
    except TokenException:
        print("❌ Access token expired. Visit /login")
        ws_running = False

if __name__ == "__main__":
    print("🌐 Starting Flask App on http://127.0.0.1:8080")

    access_token = load_access_token()

    if access_token:
        threading.Thread(target=start_kite_ws, daemon=True).start()

    socketio.run(app, host="127.0.0.1", port=8080, debug=True)
