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

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)

db = client["deeptracex"]
users_col = db["users"]
history_col = db["history"]
banned_col = db["banned"]

app = Flask(__name__)

# ================= CONFIG =================
SECRET_KEY = "Radha@2024"   # apna strong key rakhna
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = "5221493804"

# Initialize bot
try:
    bot = telebot.TeleBot(BOT_TOKEN)
except:
    bot = None

# ================= DATABASE HELPERS (MONGODB) =================
def verify_request(req):
    return req.headers.get("X-KEY") == SECRET_KEY

def get_users():
    """Fetch all users from MongoDB"""
    users_dict = {}
    for user in users_col.find():
        username = user.get("username")
        if username:
            user_data = dict(user)
            user_data.pop("_id", None)  # Remove MongoDB _id
            users_dict[username] = user_data
    return users_dict

def save_users(users_dict):
    """Save/update users to MongoDB"""
    for username, user_data in users_dict.items():
        users_col.update_one(
            {"username": username},
            {"$set": user_data},
            upsert=True
        )

def get_history():
    """Fetch all history from MongoDB"""
    history_list = []
    for entry in history_col.find().sort("timestamp", -1).limit(1000):
        entry_data = dict(entry)
        entry_data.pop("_id", None)
        history_list.append(entry_data)
    return list(reversed(history_list))  # Return oldest first

def add_history_entry(username, lookup_type, query, ip):
    """Add history entry to MongoDB"""
    entry = {
        "username": username,
        "type": lookup_type,
        "query": query,
        "ip": ip,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    history_col.insert_one(entry)
    
    # Keep only last 1000 entries
    count = history_col.count_documents({})
    if count > 1000:
        # Delete oldest entries
        oldest = list(history_col.find().sort("timestamp", 1).limit(count - 1000))
        if oldest:
            oldest_ids = [doc["_id"] for doc in oldest]
            history_col.delete_many({"_id": {"$in": oldest_ids}})

def get_banned():
    """Fetch all banned users from MongoDB"""
    banned_dict = {}
    for banned_user in banned_col.find():
        username = banned_user.get("username")
        if username:
            banned_data = dict(banned_user)
            banned_data.pop("_id", None)
            banned_dict[username] = banned_data
    return banned_dict

def save_banned(banned_dict):
    """Save/update banned users to MongoDB"""
    for username, banned_data in banned_dict.items():
        banned_col.update_one(
            {"username": username},
            {"$set": banned_data},
            upsert=True
        )

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
        # Allow login if fingerprint is None (after reset) or matches
        user_fingerprint = user.get("fingerprint")
        if user_fingerprint is not None and user_fingerprint != fingerprint:
            return jsonify({"success": False, "error": "This username is already registered from another device"})
        
        # If fingerprint was reset (None), update it to new device
        if user_fingerprint is None:
            user["fingerprint"] = fingerprint
            user["token"] = hashlib.sha256(f"{username}:{fingerprint}:{datetime.now()}".encode()).hexdigest()
        
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
        existing_fp = user_data.get("fingerprint")
        if existing_fp is not None and existing_fp == fingerprint:
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
    
    if not username:
        return jsonify({"success": False})
    
    users = get_users()
    if username not in users:
        return jsonify({"success": False})
    
    return jsonify({
        "success": True,
        "credits": users[username].get("credits", 0)
    })

# ================= IP LOOKUP =================
@app.route("/api/lookup/ip", methods=["POST"])
def lookup_ip():
    """IP address lookup"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    ip_address = data.get("ip", "").strip()
    
    # Validate IP
    if not ip_address:
        return jsonify({"success": False, "error": "IP address required"})
    
    # Check credits
    users = get_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"})
    
    user = users[username]
    if user.get("credits", 0) < 1:
        return jsonify({"success": False, "error": "Insufficient credits"})
    
    # Deduct credit using MongoDB $inc
    users_col.update_one(
        {"username": username},
        {"$inc": {"credits": -1}}
    )
    
    # Add to history
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    add_history_entry(username, "IP Lookup", ip_address, client_ip)
    
    # Perform lookup
    try:
        response = requests.get(f"http://ip-api.com/json/{ip_address}?fields=status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query", timeout=10)
        result = response.json()
        
        if result.get("status") == "fail":
            return jsonify({"success": False, "error": result.get("message", "Lookup failed")})
        
        return jsonify({
            "success": True,
            "data": {
                "ip": result.get("query"),
                "country": result.get("country"),
                "region": result.get("regionName"),
                "city": result.get("city"),
                "zip": result.get("zip"),
                "lat": result.get("lat"),
                "lon": result.get("lon"),
                "timezone": result.get("timezone"),
                "isp": result.get("isp"),
                "org": result.get("org"),
                "as": result.get("as")
            },
            "credits": user.get("credits", 0) - 1
        })
    except Exception as e:
        # Refund credit on error
        users_col.update_one(
            {"username": username},
            {"$inc": {"credits": 1}}
        )
        return jsonify({"success": False, "error": "Lookup service unavailable"})

# ================= PHONE LOOKUP =================
@app.route("/api/lookup/phone", methods=["POST"])
def lookup_phone():
    """Phone number lookup"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    phone = data.get("phone", "").strip()
    
    # Validate phone
    if not phone:
        return jsonify({"success": False, "error": "Phone number required"})
    
    # Check credits
    users = get_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"})
    
    user = users[username]
    if user.get("credits", 0) < 1:
        return jsonify({"success": False, "error": "Insufficient credits"})
    
    # Deduct credit using MongoDB $inc
    users_col.update_one(
        {"username": username},
        {"$inc": {"credits": -1}}
    )
    
    # Add to history
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    add_history_entry(username, "Phone Lookup", phone, client_ip)
    
    # Perform lookup using numverify API
    try:
        # Remove spaces and special characters
        clean_phone = re.sub(r'[^0-9+]', '', phone)
        
        # Simple validation and mock response (replace with actual API)
        return jsonify({
            "success": True,
            "data": {
                "number": clean_phone,
                "valid": True,
                "country": "Unknown",
                "location": "Unknown",
                "carrier": "Unknown",
                "line_type": "Unknown"
            },
            "credits": user.get("credits", 0) - 1,
            "note": "Phone lookup service temporarily unavailable"
        })
    except Exception as e:
        # Refund credit on error
        users_col.update_one(
            {"username": username},
            {"$inc": {"credits": 1}}
        )
        return jsonify({"success": False, "error": "Lookup service unavailable"})

# ================= EMAIL LOOKUP =================
@app.route("/api/lookup/email", methods=["POST"])
def lookup_email():
    """Email lookup"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    email = data.get("email", "").strip()
    
    # Validate email
    if not email or not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        return jsonify({"success": False, "error": "Valid email required"})
    
    # Check credits
    users = get_users()
    if username not in users:
        return jsonify({"success": False, "error": "User not found"})
    
    user = users[username]
    if user.get("credits", 0) < 1:
        return jsonify({"success": False, "error": "Insufficient credits"})
    
    # Deduct credit using MongoDB $inc
    users_col.update_one(
        {"username": username},
        {"$inc": {"credits": -1}}
    )
    
    # Add to history
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    add_history_entry(username, "Email Lookup", email, client_ip)
    
    # Mock response (replace with actual email validation API)
    try:
        domain = email.split('@')[1]
        return jsonify({
            "success": True,
            "data": {
                "email": email,
                "valid": True,
                "domain": domain,
                "disposable": False,
                "role_account": False
            },
            "credits": user.get("credits", 0) - 1,
            "note": "Email lookup service temporarily unavailable"
        })
    except Exception as e:
        # Refund credit on error
        users_col.update_one(
            {"username": username},
            {"$inc": {"credits": 1}}
        )
        return jsonify({"success": False, "error": "Lookup service unavailable"})

# ================= USERNAME LOOKUP =================
@app.route("/api/lookup/username", methods=["POST"])
def lookup_username():
    """Username lookup across social media"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username_query = data.get("username")
    lookup_username = data.get("lookup_username", "").strip()
    
    # Validate
    if not lookup_username:
        return jsonify({"success": False, "error": "Username required"})
    
    # Check credits
    users = get_users()
    if username_query not in users:
        return jsonify({"success": False, "error": "User not found"})
    
    user = users[username_query]
    if user.get("credits", 0) < 1:
        return jsonify({"success": False, "error": "Insufficient credits"})
    
    # Deduct credit using MongoDB $inc
    users_col.update_one(
        {"username": username_query},
        {"$inc": {"credits": -1}}
    )
    
    # Add to history
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
    add_history_entry(username_query, "Username Lookup", lookup_username, client_ip)
    
    # Mock response (replace with actual social media API checks)
    platforms = {
        "Instagram": f"https://instagram.com/{lookup_username}",
        "Twitter": f"https://twitter.com/{lookup_username}",
        "GitHub": f"https://github.com/{lookup_username}",
        "TikTok": f"https://tiktok.com/@{lookup_username}",
        "Reddit": f"https://reddit.com/u/{lookup_username}"
    }
    
    return jsonify({
        "success": True,
        "data": {
            "username": lookup_username,
            "platforms": platforms,
            "found": ["Instagram", "Twitter", "GitHub"]
        },
        "credits": user.get("credits", 0) - 1,
        "note": "Username lookup service temporarily unavailable"
    })

# ================= ADMIN ENDPOINTS =================
@app.route("/api/admin/users", methods=["POST"])
def admin_users():
    """Get all users (admin only)"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    users = get_users()
    return jsonify({"success": True, "users": users})

@app.route("/api/admin/history", methods=["POST"])
def admin_history():
    """Get search history (admin only)"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    history = get_history()
    return jsonify({"success": True, "history": history})

@app.route("/api/admin/ban", methods=["POST"])
def admin_ban():
    """Ban user (admin only)"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    
    if not username:
        return jsonify({"success": False, "error": "Username required"})
    
    users = get_users()
    telegram_id = "Unknown"
    if username in users:
        telegram_id = users[username].get("telegram_id", "Not Linked")
    
    banned = get_banned()
    banned[username] = {
        "username": username,
        "banned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "banned_by": "admin",
        "telegram_id": telegram_id
    }
    save_banned(banned)
    
    return jsonify({"success": True, "message": f"User {username} banned successfully"})

@app.route("/api/admin/unban", methods=["POST"])
def admin_unban():
    """Unban user (admin only)"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    
    if not username:
        return jsonify({"success": False, "error": "Username required"})
    
    # Remove from banned collection
    banned_col.delete_one({"username": username})
    
    return jsonify({"success": True, "message": f"User {username} unbanned successfully"})

@app.route("/api/admin/addcredit", methods=["POST"])
def admin_addcredit():
    """Add credits to user (admin only)"""
    if not verify_request(request):
        return jsonify({"success": False, "error": "Invalid API key"}), 403
    
    data = request.json
    username = data.get("username")
    amount = data.get("amount", 0)
    
    if not username or amount <= 0:
        return jsonify({"success": False, "error": "Invalid parameters"})
    
    # Add credits using MongoDB $inc
    result = users_col.update_one(
        {"username": username},
        {"$inc": {"credits": amount}}
    )
    
    if result.matched_count == 0:
        return jsonify({"success": False, "error": "User not found"})
    
    users = get_users()
    new_balance = users[username].get("credits", 0)
    
    return jsonify({
        "success": True,
        "message": f"Added {amount} credits to {username}",
        "new_balance": new_balance
    })

# ================= TELEGRAM BOT =================
if bot:
    @bot.message_handler(commands=['start'])
    def bot_start(message):
        if str(message.chat.id) == ADMIN_CHAT_ID:
            welcome_msg = """
🤖 **DeepTraceX Admin Bot**

Available Commands:
/viewuser - View all registered users
/history - View recent search history
/addcredit <username> - Add credits to user
/rmcredit <username> - Remove credits from user
/ban <username> - Ban a user
/unban <username> - Unban a user
/reset <username> - Reset user device binding

Admin Controls Active ✅
"""
            bot.reply_to(message, welcome_msg, parse_mode="Markdown")
        else:
            # Regular user binding flow
            bind_code = message.text.replace('/start', '').strip()
            
            if not bind_code:
                bot.reply_to(message, "⚠️ Please use the binding code from the website.")
                return
            
            # Find user with this bind code
            users = get_users()
            found_user = None
            
            for username, user_data in users.items():
                if user_data.get("bind_code") == bind_code:
                    found_user = username
                    break
            
            if not found_user:
                bot.reply_to(message, "❌ Invalid binding code. Please copy the code from the website.")
                return
            
            # Update user with telegram verification
            user = users[found_user]
            user["telegram_id"] = str(message.chat.id)
            user["telegram_verified"] = True
            user["bind_code"] = None  # Clear the code
            save_users(users)
            
            bot.reply_to(
                message,
                f"""✅ **Account Linked Successfully!**

Username: `{found_user}`
Credits: {user.get('credits', 0)}

You can now use DeepTraceX! 🎉
""",
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
        
        # Add credits using MongoDB $inc
        result = users_col.update_one(
            {"username": username},
            {"$inc": {"credits": amount}}
        )
        
        if result.matched_count > 0:
            users = get_users()
            new_balance = users[username].get('credits', 0)
            bot.answer_callback_query(call.id, f"✅ Added {amount} credits!")
            bot.edit_message_text(
                f"✅ Successfully added {amount} credits to `{username}`\n\nNew balance: {new_balance} credits",
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

        # Update using MongoDB
        users_col.update_one(
            {"username": username},
            {"$set": {"credits": new_credits}}
        )

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
            "username": username,
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

        # Check if user is banned
        banned = get_banned()
        if username not in banned:
            bot.reply_to(message, f"ℹ️ User `{username}` is not banned.", parse_mode="Markdown")
            return

        # Remove from MongoDB
        banned_col.delete_one({"username": username})

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

    @bot.message_handler(commands=['reset'])
    def bot_reset(message):
        """Reset user device fingerprint - allows login from new device"""
        if str(message.chat.id) != ADMIN_CHAT_ID:
            bot.reply_to(message, "⛔ Unauthorized access.")
            return

        parts = message.text.split()
        if len(parts) != 2:
            bot.reply_to(message, "❌ Usage: /reset <username>")
            return

        username = parts[1]
        users = get_users()

        if username not in users:
            bot.reply_to(message, f"❌ User `{username}` not found.", parse_mode="Markdown")
            return

        # Generate new token
        new_token = hashlib.sha256(f"{username}:reset:{datetime.now()}".encode()).hexdigest()

        # Reset fingerprint and token in MongoDB
        users_col.update_one(
            {"username": username},
            {
                "$set": {
                    "fingerprint": None,
                    "token": new_token
                }
            }
        )

        bot.reply_to(
            message,
            f"""✅ **RESET SUCCESSFUL**

Username: `{username}`
Device Lock: Cleared

User can now login from a new device once.
After login, they will be locked to that device.
""",
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
