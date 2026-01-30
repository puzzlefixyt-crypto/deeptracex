from flask import Flask, request, send_from_directory, jsonify
import requests
from datetime import datetime, timedelta
import re
import json
import hashlib
import os
import random
from threading import Thread
import telebot
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

app = Flask(__name__)

# ================= CONFIG =================
SECRET_KEY = "Radha@2024"   # apna strong key rakhna
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = "5221493804"

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "deeptracex"

# Initialize MongoDB
try:
    mongo_client = MongoClient(MONGO_URI)
    # Test connection
    mongo_client.admin.command('ping')
    db = mongo_client[DB_NAME]
    users_collection = db["users"]
    history_collection = db["history"]
    banned_collection = db["banned"]
    print("✅ MongoDB Connected Successfully")
except Exception as e:
    print(f"❌ MongoDB Connection Failed: {e}")
    mongo_client = None
    db = None
    users_collection = None
    history_collection = None
    banned_collection = None

# Initialize bot
try:
    bot = telebot.TeleBot(BOT_TOKEN)
except:
    bot = None

# ================= DATABASE HELPERS =================
def verify_request(req):
    return req.headers.get("X-KEY") == SECRET_KEY

def load_json(filename):
    """Legacy function - not used with MongoDB"""
    return {}

def save_json(filename, data):
    """Legacy function - not used with MongoDB"""
    pass

def get_users():
    """Get all users from MongoDB as dict with username as key"""
    if users_collection is None:
        return {}
    try:
        users = {}
        for user in users_collection.find():
            username = user.get("username")
            if username:
                # Remove MongoDB _id from user data
                user.pop("_id", None)
                users[username] = user
        return users
    except:
        return {}

def save_users(data):
    """Save users dict to MongoDB"""
    if users_collection is None:
        return
    try:
        # Clear existing and insert new
        for username, user_data in data.items():
            users_collection.update_one(
                {"username": username},
                {"$set": user_data},
                upsert=True
            )
    except Exception as e:
        print(f"Error saving users: {e}")

def get_history():
    """Get history from MongoDB as list"""
    if history_collection is None:
        return []
    try:
        history = list(history_collection.find().sort("timestamp", -1).limit(1000))
        # Remove MongoDB _id from entries
        for entry in history:
            entry.pop("_id", None)
        return history
    except:
        return []

def save_history(data):
    """Save history list to MongoDB"""
    if history_collection is None:
        return
    try:
        # Clear and insert all
        history_collection.delete_many({})
        if data:
            history_collection.insert_many(data)
    except Exception as e:
        print(f"Error saving history: {e}")

def get_banned():
    """Get banned users from MongoDB as dict with username as key"""
    if banned_collection is None:
        return {}
    try:
        banned = {}
        for entry in banned_collection.find():
            username = entry.get("username")
            if username:
                entry.pop("_id", None)
                banned[username] = entry
        return banned
    except:
        return {}

def save_banned(data):
    """Save banned dict to MongoDB"""
    if banned_collection is None:
        return
    try:
        for username, ban_data in data.items():
            ban_data["username"] = username
            banned_collection.update_one(
                {"username": username},
                {"$set": ban_data},
                upsert=True
            )
    except Exception as e:
        print(f"Error saving banned: {e}")

def add_history_entry(username, lookup_type, query, ip):
    """Add single history entry to MongoDB"""
    if history_collection is None:
        return
    try:
        entry = {
            "username": username,
            "type": lookup_type,
            "query": query,
            "ip": ip,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        history_collection.insert_one(entry)
        
        # Keep only last 1000 entries
        count = history_collection.count_documents({})
        if count > 1000:
            # Delete oldest entries
            oldest = list(history_collection.find().sort("timestamp", 1).limit(count - 1000))
            if oldest:
                history_collection.delete_many({"_id": {"$in": [doc["_id"] for doc in oldest]}})
    except Exception as e:
        print(f"Error adding history: {e}")

# ================= FINGERPRINT =================
def generate_fingerprint(ip, user_agent):
    """Generate unique fingerprint from IP and User-Agent"""
    data = f"{ip}:{user_agent}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]

# ================= TELEGRAM BINDING =================
def generate_bind_code():
    """Generate 6-digit binding code"""
    return str(random.randint(100000, 999999))

# ================= FRONTEND =================
@app.route("/")
def home():
    return send_from_directory(".", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory(".", path)

# ================= USER SYSTEM =================
@app.route("/api/auth/check", methods=["POST"])
def check_auth():
    """Check if user session is valid"""
    data = request.json
    token = data.get("token")
    username = data.get("username")
    
    if not token or not username:
        return jsonify({"success": False})
    
    users = get_users()
    if username not in users:
        return jsonify({"success": False})
    
    user = users[username]
    if user.get("token") != token:
        return jsonify({"success": False})
    
    # Check if banned
    banned = get_banned()
    if username in banned:
        return jsonify({"success": False, "banned": True})
    
    # Check Telegram verification
    if not user.get("telegram_verified", False):
        return jsonify({
            "success": False,
            "telegram_required": True,
            "bind_code": user.get("bind_code")
        })
    
    return jsonify({
        "success": True,
        "username": username,
        "credits": user.get("credits", 0)
    })

@app.route("/api/auth/register", methods=["POST"])
def register():
    """Register new user or login existing"""
    data = request.json
    username = data.get("username", "").strip()
    ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    user_agent = request.headers.get('User-Agent', '')
    fingerprint = generate_fingerprint(ip, user_agent)
    
    # Validation
    if not username or len(username) < 3:
        return jsonify({"success": False, "error": "Username must be at least 3 characters"})
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({"success": False, "error": "Username can only contain letters, numbers, and underscores"})
    
    # Check if banned
    banned = get_banned()
    if username in banned:
        return jsonify({"success": False, "error": "This account has been banned"})
    
    users = get_users()
    
    # Check if username exists
    if username in users:
        user = users[username]
        
        # Check Telegram verification first
        if not user.get("telegram_verified", False):
            return jsonify({
                "success": False,
                "telegram_required": True,
                "bind_code": user.get("bind_code"),
                "error": "Please verify your Telegram account first"
            })
        
        # User exists and verified - validate device
        if user.get("fingerprint") != fingerprint:
            return jsonify({"success": False, "error": "This username is already registered from another device"})
        
        # Valid login - refresh credits if needed
        last_refresh = user.get("last_credit_refresh")
        if last_refresh:
            last_time = datetime.strptime(last_refresh, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_time >= timedelta(hours=24):
                user["credits"] = 10
                user["last_credit_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        user["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user["last_ip"] = ip
        save_users(users)
        
        return jsonify({
            "success": True,
            "username": username,
            "credits": user.get("credits", 0),
            "token": user.get("token"),
            "is_new": False
        })
    
    # Check if this fingerprint already has an account
    for existing_user, user_data in users.items():
        if user_data.get("fingerprint") == fingerprint:
            return jsonify({"success": False, "error": "You already have an account. Please use your existing username."})
    
    # Create new user with Telegram binding requirement
    token = hashlib.sha256(f"{username}:{fingerprint}:{datetime.now()}".encode()).hexdigest()
    bind_code = generate_bind_code()
    
    users[username] = {
        "username": username,
        "token": token,
        "fingerprint": fingerprint,
        "credits": 10,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_ip": ip,
        "last_credit_refresh": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "telegram_id": None,
        "telegram_verified": False,
        "bind_code": bind_code
    }
    
    save_users(users)
    
    return jsonify({
        "success": True,
        "username": username,
        "credits": 10,
        "token": token,
        "is_new": True,
        "telegram_required": True,
        "bind_code": bind_code
    })

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    """Logout user"""
    return jsonify({"success": True})

@app.route("/api/credits/check", methods=["POST"])
def check_credits():
    """Check user credits"""
    data = request.json
    username = data.get("username")
    token = data.get("token")
    
    if not username or not token:
        return jsonify({"success": False, "error": "Invalid session"})
    
    users = get_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"})
    
    user = users[username]
    if user.get("token") != token:
        return jsonify({"success": False, "error": "Invalid session"})
    
    # Check Telegram verification
    if not user.get("telegram_verified", False):
        return jsonify({
            "success": False,
            "telegram_required": True,
            "bind_code": user.get("bind_code")
        })
    
    # Check credit refresh
    last_refresh = user.get("last_credit_refresh")
    if last_refresh:
        last_time = datetime.strptime(last_refresh, "%Y-%m-%d %H:%M:%S")
        if datetime.now() - last_time >= timedelta(hours=24):
            user["credits"] = 10
            user["last_credit_refresh"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_users(users)
    
    return jsonify({
        "success": True,
        "credits": user.get("credits", 0)
    })

def use_credit(username, token):
    """Deduct one credit from user"""
    users = get_users()
    if username not in users:
        return False
    
    user = users[username]
    if user.get("token") != token:
        return False
    
    # Check Telegram verification
    if not user.get("telegram_verified", False):
        return False
    
    if user.get("credits", 0) <= 0:
        return False
    
    user["credits"] -= 1
    save_users(users)
    return True

# ================= HELPERS =================
def today():
    return datetime.now().strftime("%d %b %Y")

def error_html(msg):
    return f'''
    <div class="error-card">
        <div class="error-icon">⚠</div>
        <div class="error-title">Request Failed</div>
        <div class="error-msg">{msg}</div>
    </div>
    '''

def no_credits_html():
    return '''
    <div class="pro-card">
        <div class="pro-icon">⭐</div>
        <div class="pro-title">Insufficient Credits</div>
        <div class="pro-msg">You do not have enough credits. Free credits will be refilled tomorrow.</div>
        <div class="pro-pricing">
            <div class="price-option">
                <div class="price-amount">₹30</div>
                <div class="price-credits">50 Credits</div>
            </div>
            <div class="price-option">
                <div class="price-amount">₹60</div>
                <div class="price-credits">120 Credits</div>
            </div>
        </div>
        <a href="https://t.me/imvrct" target="_blank" class="pro-button">Buy Credits</a>
    </div>
    '''

# ================= LOOKUP WRAPPER =================
def lookup_wrapper(lookup_func):
    """Wrapper to check credits before lookup"""
    def wrapper():
        # Get auth from headers
        username = request.headers.get('X-Username')
        token = request.headers.get('X-Token')
        
        if not username or not token:
            return error_html("Authentication required")
        
        # Check if banned
        banned = get_banned()
        if username in banned:
            return error_html("Your account has been banned")
        
        # Check and use credit
        if not use_credit(username, token):
            return no_credits_html()
        
        # Get IP for history
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        
        # Execute lookup
        result = lookup_func()
        
        # Log history if successful (not error)
        if '<div class="result-card">' in result:
            lookup_type = request.path.split('/')[-1]
            query = request.args.get("q", "")
            add_history_entry(username, lookup_type, query, ip)
        
        return result
    
    wrapper.__name__ = lookup_func.__name__
    return wrapper

# ================= MOBILE =================
@app.route("/api/num")
@lookup_wrapper
def num():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not re.fullmatch(r"[6-9]\d{9}", q):
        return error_html("Invalid input format. Please verify the mobile number and try again.")

    try:
        r = requests.get(
            f"https://api.b77bf911.workers.dev/mobile?number={q}",
            timeout=15
        ).json()
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    data = r.get("data", {}).get("results", [])
    if not data:
        return error_html("No matching records found in available databases.")
        

    d = data[0]
    
    return f'''
    <div class="result-card">
        <div class="result-header">MOBILE LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">📱</span>Mobile Number</div>
                <div class="result-value">{d.get("mobile", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👤</span>Name</div>
                <div class="result-value">{d.get("name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👨</span>Father Name</div>
                <div class="result-value">{d.get("fname", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">☎️</span>Alternate No</div>
                <div class="result-value">{d.get("alt", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🗼</span>Operator</div>
                <div class="result-value">{d.get("circle", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🆔</span>Aadhaar ID</div>
                <div class="result-value">{d.get("id", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">✉️</span>Email</div>
                <div class="result-value">{d.get("email") or "Not Available"}</div>
            </div>
            <div class="result-row full-width">
                <div class="result-label"><span class="icon">📍</span>Address</div>
                <div class="result-value">{d.get("address", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= AADHAAR =================
@app.route("/api/aadhaar")
@lookup_wrapper
def aadhaar():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not re.fullmatch(r"\d{12}", q):
        return error_html("Invalid input format. Please verify the Aadhaar number and try again.")

    try:
        r = requests.get(
            f"https://api.b77bf911.workers.dev/aadhaar?id={q}",
            timeout=15
        ).json()
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    data = r.get("data", {}).get("result", [])
    if not data:
        return error_html("No matching records found in available databases.")

    d = data[0]

    return f'''
    <div class="result-card">
        <div class="result-header">AADHAAR LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">🆔</span>Aadhaar No</div>
                <div class="result-value">{q}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👤</span>Name</div>
                <div class="result-value">{d.get("name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👨</span>Father Name</div>
                <div class="result-value">{d.get("fname", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">📱</span>Mobile</div>
                <div class="result-value">{d.get("mobile", "N/A")}</div>
            </div>
            <div class="result-row full-width">
                <div class="result-label"><span class="icon">📍</span>Address</div>
                <div class="result-value">{d.get("address", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= GST =================
@app.route("/api/gst")
@lookup_wrapper
def gst():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]", q):
        return error_html("Invalid input format. Please verify the GSTIN and try again.")

    try:
        r = requests.get(
            f"https://api.b77bf911.workers.dev/gst?number={q}",
            timeout=15
        ).json()
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    d = r.get("data", {}).get("data")
    if not d:
        return error_html("No matching records found in available databases.")

    address = ", ".join(filter(None, [
        d.get("AddrBnm"), d.get("AddrLoc"),
        d.get("AddrSt"), d.get("AddrPncd")
    ]))

    return f'''
    <div class="result-card">
        <div class="result-header">GST LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">🧾</span>GSTIN</div>
                <div class="result-value">{d.get("Gstin", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏢</span>Trade Name</div>
                <div class="result-value">{d.get("TradeName", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">📜</span>Legal Name</div>
                <div class="result-value">{d.get("LegalName", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">✅</span>Status</div>
                <div class="result-value">{d.get("Status", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">💼</span>Taxpayer Type</div>
                <div class="result-value">{d.get("TxpType", "N/A")}</div>
            </div>
            <div class="result-row full-width">
                <div class="result-label"><span class="icon">📍</span>Address</div>
                <div class="result-value">{address or "N/A"}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= IFSC =================
@app.route("/api/ifsc")
@lookup_wrapper
def ifsc():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", q):
        return error_html("Invalid input format. Please verify the IFSC code and try again.")

    try:
        d = requests.get(
            f"https://api.b77bf911.workers.dev/ifsc?code={q}",
            timeout=15
        ).json().get("data")
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    if not d:
        return error_html("No matching records found in available databases.")

    return f'''
    <div class="result-card">
        <div class="result-header">IFSC LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">🏦</span>Bank</div>
                <div class="result-value">{d.get("BANK", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏢</span>Branch</div>
                <div class="result-value">{d.get("BRANCH", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🔢</span>IFSC</div>
                <div class="result-value">{d.get("IFSC", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏙️</span>City</div>
                <div class="result-value">{d.get("CITY", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🗺️</span>State</div>
                <div class="result-value">{d.get("STATE", "N/A")}</div>
            </div>
            <div class="result-row full-width">
                <div class="result-label"><span class="icon">📍</span>Address</div>
                <div class="result-value">{d.get("ADDRESS", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= UPI =================
@app.route("/api/upi")
@lookup_wrapper
def upi():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if "@" not in q:
        return error_html("Invalid input format. Please verify the UPI ID and try again.")

    try:
        r = requests.get(
            f"https://api.b77bf911.workers.dev/upi?id={q}",
            timeout=15
        ).json()
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    arr = r.get("data", {}).get("data", {}).get("verify_chumts", [])
    if not arr:
        return error_html("No matching records found in available databases.")

    d = arr[0]

    return f'''
    <div class="result-card">
        <div class="result-header">UPI LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">💳</span>UPI ID</div>
                <div class="result-value">{d.get("vpa", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👤</span>Name</div>
                <div class="result-value">{d.get("name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏦</span>IFSC</div>
                <div class="result-value">{d.get("ifsc", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🔢</span>Account Number</div>
                <div class="result-value">{d.get("acc_no", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏪</span>Merchant</div>
                <div class="result-value">{d.get("is_merchant", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">✅</span>Merchant Verified</div>
                <div class="result-value">{d.get("is_merchant_verified", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= FAM =================
@app.route("/api/fam")
@lookup_wrapper
def fam():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not q.endswith("@fam"):
        return error_html("Invalid input format. Please verify the FAM ID and try again.")

    try:
        d = requests.get(
            f"https://api.b77bf911.workers.dev/upi2?id={q}",
            timeout=15
        ).json().get("data")
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    if not d:
        return error_html("No matching records found in available databases.")

    return f'''
    <div class="result-card">
        <div class="result-header">FAM LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">💳</span>FAM ID</div>
                <div class="result-value">{d.get("fam_id", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👤</span>Name</div>
                <div class="result-value">{d.get("name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">📱</span>Phone</div>
                <div class="result-value">{d.get("phone", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">✅</span>Status</div>
                <div class="result-value">{d.get("status", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏷️</span>Type</div>
                <div class="result-value">{d.get("type", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= VEHICLE =================
@app.route("/api/vehicle")
@lookup_wrapper
def vehicle():
    if not verify_request(request):
        return "Unauthorized", 403

    q = request.args.get("q")

    if not q:
        return error_html("Invalid input format. Please verify the vehicle number and try again.")

    try:
        r = requests.get(
            f"https://api.paanel.shop/numapi.php?action=api&key=num_wanted&test1={q}",
            timeout=15
        ).json()
    except:
        return error_html("Temporary service issue. Please retry in a moment.")

    # Parse the new API response structure
    rc_data = r.get("rc_data", {})
    data_list = rc_data.get("data", [])
    
    if not data_list:
        return error_html("No matching records found in available databases.")

    d = data_list[0]

    return f'''
    <div class="result-card">
        <div class="result-header">VEHICLE LOOKUP REPORT</div>
        <div class="result-body">
            <div class="result-row">
                <div class="result-label"><span class="icon">🚗</span>Registration No</div>
                <div class="result-value">{d.get("reg_no", q)}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👤</span>Owner Name</div>
                <div class="result-value">{d.get("owner_name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">👨</span>Father Name</div>
                <div class="result-value">{d.get("father_name", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">📱</span>Mobile No</div>
                <div class="result-value">{d.get("mobile_no", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏢</span>RTO</div>
                <div class="result-value">{d.get("rto", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">📅</span>Registration Date</div>
                <div class="result-value">{d.get("regn_dt", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🔢</span>Chassis No</div>
                <div class="result-value">{d.get("chasi_no", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">⚙️</span>Engine No</div>
                <div class="result-value">{d.get("engine_no", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🚙</span>Vehicle Model</div>
                <div class="result-value">{d.get("vehicle_model", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🏭</span>Maker</div>
                <div class="result-value">{d.get("maker", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">⛽</span>Fuel Type</div>
                <div class="result-value">{d.get("fuel_type", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🎨</span>Vehicle Color</div>
                <div class="result-value">{d.get("vehicle_color", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🛡️</span>Insurance Valid Upto</div>
                <div class="result-value">{d.get("ins_upto", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">✅</span>Fitness Valid Upto</div>
                <div class="result-value">{d.get("fitness_upto", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">💺</span>No of Seats</div>
                <div class="result-value">{d.get("no_of_seats", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">🚐</span>Body Type</div>
                <div class="result-value">{d.get("body_type_desc", "N/A")}</div>
            </div>
            <div class="result-row">
                <div class="result-label"><span class="icon">💰</span>Resale Value</div>
                <div class="result-value">{d.get("resale_value", "N/A")}</div>
            </div>
        </div>
        <div class="result-footer">Checked On: {today()}</div>
    </div>
    '''

# ================= TELEGRAM BOT =================
if bot:
    @bot.message_handler(commands=['start'])
    def handle_start(message):
        # Check if this is a binding request
        parts = message.text.split()
        
        if len(parts) == 2:
            # User sent /start CODE for binding
            code = parts[1]
            telegram_id = str(message.from_user.id)
            users = get_users()
            
            # Check if this Telegram ID is already bound
            for username, data in users.items():
                if str(data.get("telegram_id")) == telegram_id and data.get("telegram_verified"):
                    bot.reply_to(
                        message,
                        f"🔗 **ALREADY LINKED**\n\nYour Telegram account is already linked to username: `{username}`\n\nYou can now access DeepTraceX.",
                        parse_mode="Markdown"
                    )
                    return
            
            # Try to find account with this bind code
            for username, data in users.items():
                if data.get("bind_code") == code:
                    # Bind this Telegram ID to the account
                    data["telegram_id"] = telegram_id
                    data["telegram_verified"] = True
                    data["bind_code"] = None
                    save_users(users)
                    
                    bot.reply_to(
                        message,
                        f"""✅ **ACCOUNT LINKED SUCCESSFULLY**

Username: `{username}`
Telegram ID: `{telegram_id}`
Status: **Verified**

You can now access DeepTraceX with your username.
Your account is permanently secured to this Telegram account.""",
                        parse_mode="Markdown"
                    )
                    return
            
            bot.reply_to(message, "❌ Invalid or expired verification code.")
            return
        
        # Admin check for admin panel
        if str(message.chat.id) == ADMIN_CHAT_ID:
            welcome = """🔍 **DeepTraceX Admin Panel**

Welcome to the administration dashboard.

**Available Commands:**
/viewuser - View all registered users
/history - View search history
/addcredit <username> - Add credits to user
/ban <username> - Ban a user permanently
/unban <username> - Unban a user
/rmcredit <username> - Remove credits

**System Status:** ✅ Online
**Version:** 2.0.0 (Telegram Binding Enabled)
"""
            bot.reply_to(message, welcome, parse_mode="Markdown")
        else:
            # Regular user
            bot.reply_to(
                message,
                """🔍 **DeepTraceX Telegram Bot**

To link your account:
1. Register on DeepTraceX website
2. Copy your 6-digit verification code
3. Send: `/start YOUR_CODE`

Example: `/start 123456`""",
                parse_mode="Markdown"
            )
    
    @bot.message_handler(commands=['viewuser'])
    def bot_viewuser(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        users = get_users()
        if not users:
            bot.reply_to(message, "📋 No users registered yet.")
            return
        
        response = "👥 **Registered Users:**\n\n"
        for username, data in users.items():
            response += f"**Username:** `{username}`\n"
            response += f"Credits: {data.get('credits', 0)}\n"
            response += f"Telegram ID: `{data.get('telegram_id', 'Not Linked')}`\n"
            response += f"Verified: {'✅ Yes' if data.get('telegram_verified') else '❌ No'}\n"
            response += f"Last Login: {data.get('last_login', 'N/A')}\n"
            response += f"Last IP: {data.get('last_ip', 'N/A')}\n"
            response += "─" * 30 + "\n\n"
        
        # Split if too long
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                bot.send_message(message.chat.id, response[i:i+4000], parse_mode="Markdown")
        else:
            bot.reply_to(message, response, parse_mode="Markdown")
    
    @bot.message_handler(commands=['history'])
    def bot_history(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        history = get_history()
        if not history:
            bot.reply_to(message, "📋 No search history available.")
            return
        
        # Get last 20 entries
        recent = history[-20:]
        response = "🔎 **Recent Search History:**\n\n"
        
        for entry in reversed(recent):
            response += f"**User:** `{entry.get('username')}`\n"
            response += f"Type: {entry.get('type')}\n"
            response += f"Query: `{entry.get('query')}`\n"
            response += f"Time: {entry.get('timestamp')}\n"
            response += "─" * 30 + "\n\n"
        
        if len(response) > 4000:
            for i in range(0, len(response), 4000):
                bot.send_message(message.chat.id, response[i:i+4000], parse_mode="Markdown")
        else:
            bot.reply_to(message, response, parse_mode="Markdown")
    
    @bot.message_handler(commands=['addcredit'])
    def bot_addcredit(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        try:
            username = message.text.split()[1]
        except:
            bot.reply_to(message, "❌ Usage: /addcredit <username>")
            return
        
        users = get_users()
        if username not in users:
            bot.reply_to(message, f"❌ User `{username}` not found.", parse_mode="Markdown")
            return
        
        markup = telebot.types.InlineKeyboardMarkup()
        btn1 = telebot.types.InlineKeyboardButton("➕ 50 Credits", callback_data=f"credit_{username}_50")
        btn2 = telebot.types.InlineKeyboardButton("➕ 120 Credits", callback_data=f"credit_{username}_120")
        markup.add(btn1, btn2)
        
        bot.reply_to(message, f"💳 Select credit package for `{username}`:", reply_markup=markup, parse_mode="Markdown")
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith('credit_'))
    def handle_credit_callback(call):
        if str(call.message.chat.id) != ADMIN_CHAT_ID:
            return
        
        _, username, amount = call.data.split('_')
        amount = int(amount)
        
        users = get_users()
        if username in users:
            users[username]['credits'] = users[username].get('credits', 0) + amount
            save_users(users)
            bot.answer_callback_query(call.id, f"✅ Added {amount} credits!")
            bot.edit_message_text(
                f"✅ Successfully added {amount} credits to `{username}`\n\nNew balance: {users[username]['credits']} credits",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown"
            )
        else:
            bot.answer_callback_query(call.id, "❌ User not found")
            
    @bot.callback_query_handler(func=lambda call: call.data.startswith('rm_'))
    def handle_rmcredit_callback(call):
        if str(call.message.chat.id) != ADMIN_CHAT_ID:
            return

        _, action, username = call.data.split('_')
        users = get_users()

        if username not in users:
            bot.answer_callback_query(call.id, "User not found")
            return

        old_credits = users[username].get("credits", 0)

        if action == "all":
            new_credits = 0
        elif action == "half":
            new_credits = (old_credits + 1) // 2   # round up (5 -> 3)
        else:
            return

        users[username]["credits"] = new_credits
        save_users(users)

        bot.edit_message_text(
            f"""🧮 **CREDITS UPDATED**

User: `{username}`
Previous: `{old_credits}`
Now: `{new_credits}`

Action: `{action.upper()} WIPE`
""",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
    
    @bot.message_handler(commands=['ban'])
    def bot_ban(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return

        try:
            username = message.text.split()[1]
        except:
            bot.reply_to(message, "❌ Usage: /ban <username>")
            return

        users = get_users()
        telegram_id = "Unknown"
        if username in users:
            telegram_id = users[username].get("telegram_id", "Not Linked")

        banned = get_banned()
        banned[username] = {
            "banned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "banned_by": "admin",
            "telegram_id": telegram_id
        }
        save_banned(banned)

        bot.reply_to(
            message,
            f"🚫 User `{username}` has been permanently banned.\n\nTelegram ID: `{telegram_id}`",
            parse_mode="Markdown"
        )

    @bot.message_handler(commands=['unban'])
    def bot_unban(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return

        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /unban <username>")
            return

        username = parts[1]

        banned = get_banned()
        if username not in banned:
            bot.reply_to(message, f"ℹ️ User `{username}` is not banned.", parse_mode="Markdown")
            return

        # Remove from banned dict and delete from MongoDB
        banned.pop(username)
        if banned_collection is not None:
            try:
                banned_collection.delete_one({"username": username})
            except:
                pass

        bot.reply_to(
            message,
            f"""✅ USER UNBANNED SUCCESSFULLY

Username : {username}
Status   : Active
Access   : Restored
""",
            parse_mode="Markdown"
        )

    @bot.message_handler(commands=['rmcredit'])
    def bot_rmcredit(message):
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return

        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /rmcredit <username>")
            return

        username = parts[1]
        users = get_users()

        if username not in users:
            bot.reply_to(message, f"❌ User `{username}` not found.", parse_mode="Markdown")
            return

        current_credits = users[username].get("credits", 0)

        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton(
                "🗑 All Wipe", callback_data=f"rm_all_{username}"
            ),
            telebot.types.InlineKeyboardButton(
                "➗ Half Wipe", callback_data=f"rm_half_{username}"
            )
        )

        bot.reply_to(
            message,
            f"""⚠️ **Credit Removal Panel**

User: `{username}`
Current Credits: `{current_credits}`

Choose an action:
""",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    # Start bot in background
    def run_bot():
        try:
            bot.infinity_polling()
        except:
            pass

    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()


# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
