"""import os
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

socketio = SocketIO(app, cors_allowed_origins="*")



# ---------------- Zerodha Credentials ----------------
API_KEY = "bi2z9m2ympdrgkig"
API_SECRET = "1c021e83lqngtuma0p5yk6son4051euc"
ACCESS_TOKEN_FILE = "access_token.json"

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Set KITE_API_KEY and KITE_API_SECRET in environment variables!")

# ---------------- Instrument Tokens ----------------
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
        threading.Thread(target=start_kite_ws, daemon=True).start()
        return "✅ Login successful. WebSocket started. You can now close this page."
    except Exception as e:
        return f"❌ Error: {e}"

# ---------------- Kite WebSocket ----------------
def on_connect(ws, response):
    print("✅ Zerodha WebSocket Connected")
    ws.subscribe(list(TOKENS.keys()))
    ws.set_mode(ws.MODE_LTP, list(TOKENS.keys()))

def on_ticks(ws, ticks):
    for t in ticks:
        token = t["instrument_token"]
        symbol = TOKENS.get(token)

        payload = {
            "symbol": symbol,
            "ltp": t.get("last_price", 0),
            "open": t.get("ohlc", {}).get("open", 0),
            "high": t.get("ohlc", {}).get("high", 0),
            "low": t.get("ohlc", {}).get("low", 0),
            "volume": t.get("volume", 0)
        }

        socketio.emit("stock_update", payload)

def on_close(ws, code, reason):
    print("⚠️ WebSocket closed:", reason)

def on_error(ws, code, reason):
    print("❌ WebSocket error:", reason)

def start_kite_ws():
    print("🚀 start_kite_ws() called")

    access_token = load_access_token()
    print("🔐 Access Token:", "FOUND" if access_token else "NOT FOUND")

    if not access_token:
        print("❌ No access token, aborting WS")
        return

    kite.set_access_token(access_token)
    kws = KiteTicker(API_KEY, access_token)

    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_close = on_close
    kws.on_error = on_error

    print("📡 Connecting to Zerodha WebSocket...")
    try:
        kws.connect(threaded=True)
    except TokenException:
        print("❌ Access token expired. Visit /login to generate a new one.")

    # ----------------- Market closed fallback -----------------
    import time
    from datetime import datetime

    # Simple loop to check market hours (NSE: 09:15 to 15:30)
    while True:
        now = datetime.now()
        if now.weekday() >= 5:  # Sat/Sun
            is_market_open = False
        else:
            is_market_open = now.time() >= datetime.strptime("09:15", "%H:%M").time() and \
                             now.time() <= datetime.strptime("15:30", "%H:%M").time()

        if not is_market_open:
            # Market closed: fetch last available prices
            for token, symbol in TOKENS.items():
                try:
                    # get LTP from kite.ltp (dictionary format)
                    ltp_data = kite.ltp(f"NSE:{symbol}")
                    last_price = ltp_data[f"NSE:{symbol}"]["last_price"]
                    payload = {
                        "symbol": symbol,
                        "ltp": last_price
                    }
                    socketio.emit("stock_update", payload)
                except Exception as e:
                    print(f"❌ Error fetching {symbol} LTP:", e)
            time.sleep(5)  # update every 5 seconds when market closed
        else:
            break  # market open, live WS will take over

# ---------------- Main ----------------
if __name__ == "__main__":
    print("🌐 Starting Flask App on http://0.0.0.0:8080")
    access_token = load_access_token()

    if access_token:
        threading.Thread(target=start_kite_ws, daemon=True).start()
        print("🚀 WebSocket started automatically using saved token")
    else:
        print("⚠️ No access token found. Opening browser to login...")
        # Automatically open default browser to login
        webbrowser.open("http://127.0.0.1:8080/login")

    socketio.run(app, host="0.0.0.0", port=8080, debug=False)


"""
import os
import json
import threading
from datetime import datetime
from flask import Flask, render_template, redirect, request
from flask_socketio import SocketIO
from kiteconnect import KiteConnect, KiteTicker
from kiteconnect.exceptions import TokenException

# ---------------- Flask Setup ----------------
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------------- Zerodha Credentials ----------------
API_KEY = "bi2z9m2ympdrgkig"
API_SECRET = "1c021e83lqngtuma0p5yk6son4051euc"
ACCESS_TOKEN_FILE = "access_token.json"

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ Set KITE_API_KEY and KITE_API_SECRET!")

# ---------------- Instrument Tokens ----------------
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

# ---------------- Kite Setup ----------------
kite = KiteConnect(api_key=API_KEY)
kws = None

# ---------------- Token Helpers ----------------
def load_access_token():
    """Load access token from env variable first, fallback to file"""
    token = os.getenv("KITE_ACCESS_TOKEN")
    if token:
        return token

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
    """Save access token only if env variable not set"""
    if os.getenv("KITE_ACCESS_TOKEN"):
        return
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
        threading.Thread(target=start_kite_ws, daemon=True).start()
        return "✅ Login successful. WebSocket started. You can now close this page."
    except Exception as e:
        return f"❌ Error: {e}"

# ---------------- Kite WebSocket ----------------
def on_connect(ws, response):
    print("✅ Zerodha WebSocket Connected")
    ws.subscribe(list(TOKENS.keys()))
    ws.set_mode(ws.MODE_LTP, list(TOKENS.keys()))

def on_ticks(ws, ticks):
    for t in ticks:
        token = t["instrument_token"]
        symbol = TOKENS.get(token)
        payload = {
            "symbol": symbol,
            "ltp": t.get("last_price", 0),
            "open": t.get("ohlc", {}).get("open", 0),
            "high": t.get("ohlc", {}).get("high", 0),
            "low": t.get("ohlc", {}).get("low", 0),
            "volume": t.get("volume", 0)
        }
        socketio.emit("stock_update", payload)

def on_close(ws, code, reason):
    print("⚠️ WebSocket closed:", reason)

def on_error(ws, code, reason):
    print("❌ WebSocket error:", reason)

def start_kite_ws():
    print("🚀 start_kite_ws() called")
    access_token = load_access_token()
    print("🔐 Access Token:", "FOUND" if access_token else "NOT FOUND")
    if not access_token:
        print("❌ No access token, aborting WS")
        return

    kite.set_access_token(access_token)
    kws = KiteTicker(API_KEY, access_token)
    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_close = on_close
    kws.on_error = on_error

    print("📡 Connecting to Zerodha WebSocket...")
    try:
        kws.connect(threaded=True)
    except TokenException:
        print("❌ Access token expired. Visit /login to generate a new one.")

# ---------------- Main ----------------
if __name__ == "__main__":
    print("🌐 Starting Flask App on http://0.0.0.0:8080")
    access_token = load_access_token()
    if access_token:
        threading.Thread(target=start_kite_ws, daemon=True).start()
        print("🚀 WebSocket started automatically using saved token")
    else:
        print("⚠️ No access token found. Please visit /login from your browser to generate one.")

    socketio.run(app, host="0.0.0.0", port=8080, debug=False)
