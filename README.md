# DeepTraceX SaaS Platform

Professional OSINT lookup platform with user authentication, credit system, and Telegram bot administration.

## Features

### Core Features
- **User Authentication System**
  - Username-based registration
  - Device/IP fingerprinting
  - Secure token-based sessions
  - Auto-login for returning users
  - Ban system

### Credit System
- **Free Credits**: 10 credits per user per day
- **Auto-Refill**: Credits automatically refill after 24 hours
- **One Search = One Credit**
- **Buy More**: ₹30 for 50 credits, ₹60 for 120 credits

### Lookup Types
1. Mobile Number Lookup
2. Aadhaar Lookup
3. GST Lookup
4. IFSC Code Lookup
5. UPI ID Lookup
6. FAM ID Lookup
7. Vehicle Registration Lookup

### Admin Features (Telegram Bot)
- View all registered users
- Monitor search history
- Add credits to any user
- Ban users permanently
- Professional formatted responses

### Security Features
- IP + Browser fingerprinting
- One account per device/IP
- Session validation
- Anti-abuse protection
- Banned user access prevention

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Telegram Bot

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your bot token
3. Get your Telegram chat ID (use [@userinfobot](https://t.me/userinfobot))
4. Edit `api.py` and update these lines:

```python
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
ADMIN_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID_HERE"
```

### 3. Run the Server

```bash
python api.py
```

The server will start on `http://0.0.0.0:10000`

## Telegram Bot Commands

### Admin Commands (Only work for configured ADMIN_CHAT_ID)

#### `/start`
Welcome message with command list

#### `/viewuser`
Display all registered users with:
- Username
- Credit balance
- Last login time
- Last IP address

#### `/history`
Show last 20 search operations:
- Username who performed search
- Lookup type
- Query value
- Timestamp

#### `/addcredit <username>`
Add credits to a specific user:
- Shows inline buttons for 50 or 120 credits
- Instantly updates user balance
- Confirms successful addition

#### `/ban <username>`
Permanently ban a user:
- User cannot login
- All API requests blocked
- Cannot create new account with same device

## File Structure

```
deeptracex_saas/
├── api.py              # Main Flask backend
├── index.html          # Frontend HTML
├── script.js           # Frontend JavaScript
├── style.css           # Styles and animations
├── requirements.txt    # Python dependencies
├── users.json          # User database (auto-created)
├── history.json        # Search history (auto-created)
└── banned.json         # Banned users (auto-created)
```

## Database Files

### users.json
Stores user accounts:
```json
{
  "username": {
    "username": "testuser",
    "token": "hashed_token",
    "fingerprint": "device_fingerprint",
    "credits": 10,
    "created_at": "2025-01-28 10:00:00",
    "last_login": "2025-01-28 15:30:00",
    "last_ip": "192.168.1.1",
    "last_credit_refresh": "2025-01-28 00:00:00"
  }
}
```

### history.json
Tracks all searches:
```json
[
  {
    "username": "testuser",
    "type": "num",
    "query": "9876543210",
    "ip": "192.168.1.1",
    "timestamp": "2025-01-28 15:30:00"
  }
]
```

### banned.json
Lists banned users:
```json
{
  "baduser": {
    "banned_at": "2025-01-28 16:00:00",
    "banned_by": "admin"
  }
}
```

## User Flow

### First Visit
1. User opens website
2. Welcome popup appears (blurred background)
3. User enters desired username
4. System checks:
   - Username availability
   - Device fingerprint uniqueness
5. Account created with 10 free credits
6. User redirected to main panel

### Returning User
1. User opens website
2. System checks localStorage for session
3. Validates session with backend
4. Auto-login to main panel
5. Credits auto-refill if 24 hours passed

### Performing Lookup
1. User selects lookup type
2. Enters query value
3. System validates format
4. Checks credit balance
5. If credits available:
   - Deducts 1 credit
   - Performs lookup
   - Displays results
   - Updates credit display
6. If no credits:
   - Shows pricing card
   - Redirects to Telegram for purchase

### Logout
1. User clicks logout button
2. Confirmation dialog appears
3. Session cleared from localStorage
4. Redirected to login popup

## Security Implementation

### Fingerprinting
- Combines IP address + User-Agent
- SHA256 hash generates unique identifier
- Prevents multi-account abuse

### Session Management
- Token-based authentication
- Server-side validation
- Secure token generation
- Auto-logout on invalid session

### Credit Protection
- Server-side credit tracking
- Cannot be manipulated via frontend
- Atomic deduction operations
- 24-hour refresh timer

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register/login user
- `POST /api/auth/check` - Validate session
- `POST /api/auth/logout` - Logout user

### Credits
- `POST /api/credits/check` - Check credit balance

### Lookups (All require auth headers)
- `GET /api/num?q=<mobile>` - Mobile lookup
- `GET /api/aadhaar?q=<aadhaar>` - Aadhaar lookup
- `GET /api/gst?q=<gstin>` - GST lookup
- `GET /api/ifsc?q=<ifsc>` - IFSC lookup
- `GET /api/upi?q=<upi>` - UPI lookup
- `GET /api/fam?q=<fam>` - FAM lookup
- `GET /api/vehicle?q=<reg>` - Vehicle lookup

### Required Headers for Lookups
```
X-Username: <username>
X-Token: <session_token>
```

## Customization

### Change Credit Pricing
Edit `api.py` in `no_credits_html()` function to update pricing display.

### Modify Credit Amounts
Edit `api.py`:
- Initial credits: Line with `"credits": 10`
- Refill amount: Line with `user["credits"] = 10`

### Change Refill Duration
Edit `api.py`:
- Find `timedelta(hours=24)`
- Change to desired duration

### Update External API
Edit `api.py` lookup functions:
- Replace API URLs
- Update response parsing
- Modify result HTML templates

## Production Deployment

### Using Gunicorn
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:10000 api:app
```

### Using Nginx Reverse Proxy
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Environment Variables
For production, use environment variables:
```python
import os
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
```

## Support

For issues or features, contact: [@imvrct](https://t.me/imvrct)

## License

This is a personal project. All rights reserved.

## Version

**v1.0.0** - Initial Release
- User authentication system
- Credit system with auto-refill
- Telegram bot admin panel
- 7 lookup types
- Ban system
- Professional glassmorphic UI
