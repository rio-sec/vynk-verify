from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import requests
import uuid
import threading

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'vynk-secret-key-2024')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Discord Bot Token
discord_bot_token = os.getenv('DISCORD_TOKEN')

# Discord OAuth Configuration
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback')
DISCORD_API_BASE_URL = 'https://discord.com/api/v10'

# Abstract API Configuration
ABSTRACT_API_KEY = os.getenv('ABSTRACT_API_KEY')
ABSTRACT_API_URL = "https://ipgeolocation.abstractapi.com/v1/"

class DashboardDB:
    def __init__(self):
        self.conn = sqlite3.connect('vynk.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Server settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS server_settings (
                guild_id TEXT PRIMARY KEY,
                verification_channel TEXT,
                verified_role TEXT,
                log_channel TEXT,
                method TEXT DEFAULT 'button'
            )
        ''')
        
        # Verification logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT,
                user_id TEXT,
                user_name TEXT,
                method TEXT,
                status TEXT,
                timestamp TEXT
            )
        ''')
        
        # Verification sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_sessions (
                session_id TEXT PRIMARY KEY,
                discord_user_id TEXT,
                discord_guild_id TEXT,
                status TEXT DEFAULT 'pending',
                ip_address TEXT,
                geolocation_data TEXT,
                created_at TEXT,
                completed_at TEXT
            )
        ''')
        
        # User sessions table for OAuth
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id TEXT PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                expires_at TEXT,
                user_data TEXT
            )
        ''')
        
        self.conn.commit()
    
    def save_user_session(self, user_id, access_token, refresh_token, expires_in, user_data):
        cursor = self.conn.cursor()
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        cursor.execute('''
            INSERT OR REPLACE INTO user_sessions 
            (user_id, access_token, refresh_token, expires_at, user_data)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, access_token, refresh_token, expires_at.isoformat(), json.dumps(user_data)))
        self.conn.commit()
    
    def get_user_session(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM user_sessions WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def create_verification_session(self, session_id, discord_user_id, discord_guild_id, ip_address):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO verification_sessions 
            (session_id, discord_user_id, discord_guild_id, ip_address, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (session_id, discord_user_id, discord_guild_id, ip_address, datetime.now().isoformat()))
        self.conn.commit()
    
    def update_verification_session(self, session_id, status, geolocation_data=None):
        cursor = self.conn.cursor()
        if geolocation_data:
            cursor.execute('''
                UPDATE verification_sessions 
                SET status = ?, geolocation_data = ?, completed_at = ?
                WHERE session_id = ?
            ''', (status, json.dumps(geolocation_data), datetime.now().isoformat(), session_id))
        else:
            cursor.execute('''
                UPDATE verification_sessions 
                SET status = ?, completed_at = ?
                WHERE session_id = ?
            ''', (status, datetime.now().isoformat(), session_id))
        self.conn.commit()
    
    def get_server_stats(self, guild_id):
        cursor = self.conn.cursor()
        
        try:
            # Total verifications
            cursor.execute('SELECT COUNT(*) as total FROM verification_logs WHERE guild_id = ?', (guild_id,))
            total_result = cursor.fetchone()
            total_verifications = total_result[0] if total_result else 0
            
            # Successful verifications
            cursor.execute('SELECT COUNT(*) as success FROM verification_logs WHERE guild_id = ? AND status = "success"', (guild_id,))
            success_result = cursor.fetchone()
            success_verifications = success_result[0] if success_result else 0
            
            # Failed verifications
            cursor.execute('SELECT COUNT(*) as failed FROM verification_logs WHERE guild_id = ? AND status = "failed"', (guild_id,))
            failed_result = cursor.fetchone()
            failed_verifications = failed_result[0] if failed_result else 0
            
            # Recent verifications (last 24 hours)
            cursor.execute('''
                SELECT COUNT(*) as recent FROM verification_logs 
                WHERE guild_id = ? AND timestamp > datetime('now', '-1 day')
            ''', (guild_id,))
            recent_result = cursor.fetchone()
            recent_verifications = recent_result[0] if recent_result else 0
            
            success_rate = round((success_verifications / total_verifications * 100) if total_verifications > 0 else 0, 1)
            
            return {
                'total_verifications': total_verifications,
                'success_verifications': success_verifications,
                'failed_verifications': failed_verifications,
                'recent_verifications': recent_verifications,
                'success_rate': success_rate
            }
        except Exception as e:
            print(f"Error getting server stats: {e}")
            return {
                'total_verifications': 0,
                'success_verifications': 0,
                'failed_verifications': 0,
                'recent_verifications': 0,
                'success_rate': 0
            }
    
    def get_recent_verifications(self, guild_id, limit=10):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                SELECT user_name, method, status, timestamp 
                FROM verification_logs 
                WHERE guild_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (guild_id, limit))
            return cursor.fetchall()
        except Exception as e:
            print(f"Error getting recent verifications: {e}")
            return []
    
    def get_server_settings(self, guild_id):
        cursor = self.conn.cursor()
        try:
            cursor.execute('SELECT * FROM server_settings WHERE guild_id = ?', (guild_id,))
            return cursor.fetchone()
        except Exception as e:
            print(f"Error getting server settings: {e}")
            return None

# Import the main database for logging verifications
try:
    from database import db as main_db
    print("✅ Main database imported successfully for verification logging")
except ImportError as e:
    print(f"❌ Error importing main database: {e}")
    # Create a fallback database class
    class FallbackDB:
        def log_verification(self, guild_id, user_id, user_name, method, status):
            print(f"📝 [FALLBACK] Logging verification: {guild_id}, {user_id}, {method}, {status}")
    main_db = FallbackDB()

# Discord OAuth Helper
class DiscordOAuth:
    @staticmethod
    def get_auth_url():
        return (f"https://discord.com/oauth2/authorize"
                f"?client_id={DISCORD_CLIENT_ID}"
                f"&redirect_uri={DISCORD_REDIRECT_URI}"
                f"&response_type=code"
                f"&scope=identify%20guilds")
    
    @staticmethod
    def exchange_code(code):
        data = {
            'client_id': DISCORD_CLIENT_ID,
            'client_secret': DISCORD_CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': DISCORD_REDIRECT_URI
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(f'{DISCORD_API_BASE_URL}/oauth2/token', data=data, headers=headers)
        return response.json() if response.status_code == 200 else None
    
    @staticmethod
    def get_user_info(access_token):
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        response = requests.get(f'{DISCORD_API_BASE_URL}/users/@me', headers=headers)
        return response.json() if response.status_code == 200 else None
    
    @staticmethod
    def get_user_guilds(access_token):
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        response = requests.get(f'{DISCORD_API_BASE_URL}/users/@me/guilds', headers=headers)
        return response.json() if response.status_code == 200 else None

# Geolocation service using Abstract API
class GeolocationService:
    @staticmethod
    def get_geolocation_data(ip_address):
        if not ABSTRACT_API_KEY:
            print("⚠️ Abstract API key not set - using mock data")
            return {
                "ip_address": ip_address,
                "country": "Unknown",
                "region": "Unknown", 
                "city": "Unknown",
                "isp": "Unknown",
                "vpn_detected": False,
                "connection_type": "Unknown"
            }
        
        try:
            response = requests.get(
                ABSTRACT_API_URL,
                params={
                    'api_key': ABSTRACT_API_KEY,
                    'ip_address': ip_address,
                    'fields': 'country,region,city,isp,security,connection'
                },
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "ip_address": ip_address,
                    "country": data.get('country', 'Unknown'),
                    "region": data.get('region', 'Unknown'),
                    "city": data.get('city', 'Unknown'),
                    "isp": data.get('isp', 'Unknown'),
                    "vpn_detected": data.get('security', {}).get('is_vpn', False),
                    "connection_type": data.get('connection', {}).get('connection_type', 'Unknown')
                }
            else:
                print(f"❌ Abstract API error: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Geolocation error: {e}")
            return {
                "ip_address": ip_address,
                "country": "Error",
                "region": "Error", 
                "city": "Error",
                "isp": "Error",
                "vpn_detected": False,
                "connection_type": "Error"
            }

db = DashboardDB()
discord_oauth = DiscordOAuth()
geolocation_service = GeolocationService()

# Authentication decorator
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return redirect(discord_oauth.get_auth_url())

@app.route('/auth/callback')
def auth_callback():
    code = request.args.get('code')
    if not code:
        return "Authentication failed: No code provided", 400
    
    # Exchange code for access token
    token_data = discord_oauth.exchange_code(code)
    if not token_data:
        return "Authentication failed: Invalid code", 400
    
    # Get user info
    user_info = discord_oauth.get_user_info(token_data['access_token'])
    if not user_info:
        return "Authentication failed: Cannot get user info", 400
    
    # Save user session
    db.save_user_session(
        user_info['id'],
        token_data['access_token'],
        token_data['refresh_token'],
        token_data['expires_in'],
        user_info
    )
    
    # Set session
    session['user_id'] = user_info['id']
    session['username'] = user_info['username']
    session['avatar'] = user_info.get('avatar')
    
    return redirect('/dashboard')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Get user's guilds
        user_session = db.get_user_session(session['user_id'])
        if not user_session:
            return redirect('/login')
        
        guilds = discord_oauth.get_user_guilds(user_session['access_token'])
        admin_guilds = [g for g in guilds if (g['permissions'] & 0x8) == 0x8]  # ADMINISTRATOR permission
        
        # Get stats for first admin guild (or demo data)
        if admin_guilds:
            guild_id = admin_guilds[0]['id']
            guild_name = admin_guilds[0]['name']
        else:
            guild_id = "123456789"
            guild_name = "Demo Server"
        
        stats = db.get_server_stats(guild_id)
        recent_verifications = db.get_recent_verifications(guild_id)
        settings = db.get_server_settings(guild_id)
        
        return render_template('dashboard.html', 
                             stats=stats, 
                             recent_verifications=recent_verifications,
                             settings=settings,
                             guilds=admin_guilds,
                             current_guild={'id': guild_id, 'name': guild_name},
                             user=session,
                             DISCORD_CLIENT_ID=DISCORD_CLIENT_ID)
    except Exception as e:
        return f"Error loading dashboard: {e}", 500

# New Verification Portal Routes
@app.route('/verify/<guild_id>/<user_id>')
def verification_portal(guild_id, user_id):
    try:
        # Get user's IP address
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        # Create verification session
        session_id = str(uuid.uuid4())
        db.create_verification_session(session_id, user_id, guild_id, ip_address)
        
        # Get geolocation data
        geolocation_data = geolocation_service.get_geolocation_data(ip_address)
        
        return render_template('verification_portal.html', 
                             session_id=session_id,
                             user_id=user_id,
                             guild_id=guild_id,
                             geolocation_data=geolocation_data)
    except Exception as e:
        return f"Error loading verification portal: {e}", 500

@app.route('/api/verify', methods=['POST'])
def api_verify():
    try:
        data = request.json
        session_id = data.get('session_id')
        user_id = data.get('user_id')
        guild_id = data.get('guild_id')
        
        if not all([session_id, user_id, guild_id]):
            return jsonify({'success': False, 'error': 'Missing required fields'})
        
        # Get IP and geolocation for logging
        if request.headers.get('X-Forwarded-For'):
            ip_address = request.headers.get('X-Forwarded-For').split(',')[0]
        else:
            ip_address = request.remote_addr
        
        geolocation_data = geolocation_service.get_geolocation_data(ip_address)
        
        # Update session status
        db.update_verification_session(session_id, 'completed', geolocation_data)
        
        # Log the verification using the main database
        try:
            main_db.log_verification(
                guild_id=guild_id,
                user_id=user_id,
                user_name=f"Web User {user_id}",
                method="web",
                status="success"
            )
            print(f"✅ Web verification logged successfully: User {user_id} in Guild {guild_id}")
        except Exception as db_error:
            print(f"❌ Error logging to main database: {db_error}")
            # Fallback: log to web dashboard database
            try:
                cursor = db.conn.cursor()
                cursor.execute('''
                    INSERT INTO verification_logs 
                    (guild_id, user_id, user_name, method, status, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (guild_id, user_id, f"Web User {user_id}", "web", "success", datetime.now().isoformat()))
                db.conn.commit()
                print(f"✅ Web verification logged to fallback database")
            except Exception as fallback_error:
                print(f"❌ Error with fallback logging: {fallback_error}")
        
        print(f"✅ Web verification completed: User {user_id} in Guild {guild_id}")
        
        return jsonify({
            'success': True,
            'message': 'Verification completed successfully!',
            'session_id': session_id,
            'geolocation_data': geolocation_data
        })
    except Exception as e:
        print(f"Error in API verify: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stats/<guild_id>')
def api_stats(guild_id):
    try:
        stats = db.get_server_stats(guild_id)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/discord/assign-role', methods=['POST'])
def discord_assign_role():
    """Assign role using Discord's REST API directly (no async issues)"""
    try:
        data = request.json
        guild_id = data.get('guild_id')
        user_id = data.get('user_id')
        geolocation_data = data.get('geolocation_data', {})
        
        print(f"🔧 Direct Discord API: Assign role to {user_id} in {guild_id}")
        
        if not guild_id or not user_id:
            return jsonify({'success': False, 'error': 'Missing guild_id or user_id'})
        
        # Get server settings to find the role ID and log channel
        cursor = db.conn.cursor()
        cursor.execute('SELECT verified_role, log_channel FROM server_settings WHERE guild_id = ?', (guild_id,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'error': 'Server not configured'})
        
        verified_role_id = result[0]
        log_channel_id = result[1]
        
        # Use Discord's REST API to assign role
        headers = {
            'Authorization': f'Bot {discord_bot_token}',
            'Content-Type': 'application/json'
        }
        
        # Add role to guild member
        url = f'https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}/roles/{verified_role_id}'
        response = requests.put(url, headers=headers)
        
        if response.status_code == 204:
            # Success - log the verification
            try:
                # Get user info for logging
                user_url = f'https://discord.com/api/v10/users/{user_id}'
                user_response = requests.get(user_url, headers=headers)
                user_data = user_response.json() if user_response.status_code == 200 else {}
                username = user_data.get('username', f'User{user_id}')
                discriminator = user_data.get('discriminator', '0000')
                
                # Log to database
                from database import db as main_db
                main_db.log_verification(
                    guild_id=guild_id,
                    user_id=user_id,
                    user_name=f"{username}#{discriminator}",
                    method="web",
                    status="success"
                )
                
                # Send log to Discord channel if log channel is configured
                if log_channel_id:
                    log_embed = {
                        "title": "🔐 Web Verification Log",
                        "description": f"**User:** <@{user_id}> (`{user_id}`)\n**Method:** Web Portal\n**Status:** Success",
                        "color": 0x10B981,
                        "timestamp": datetime.now().isoformat(),
                        "fields": [
                            {
                                "name": "🌍 Location Info",
                                "value": f"**IP:** {geolocation_data.get('ip_address', 'Unknown')}\n"
                                        f"**Country:** {geolocation_data.get('country', 'Unknown')}\n"
                                        f"**ISP:** {geolocation_data.get('isp', 'Unknown')}\n"
                                        f"**VPN:** {'✅ Yes' if geolocation_data.get('vpn_detected') else '❌ No'}",
                                "inline": False
                            }
                        ],
                        "footer": {
                            "text": f"User ID: {user_id}"
                        }
                    }
                    
                    log_url = f'https://discord.com/api/v10/channels/{log_channel_id}/messages'
                    log_data = {
                        "embeds": [log_embed]
                    }
                    log_response = requests.post(log_url, headers=headers, json=log_data)
                    
                    if log_response.status_code == 200:
                        print("📝 Log sent to Discord channel")
                    else:
                        print(f"⚠️ Failed to send log: {log_response.status_code}")
                
            except Exception as log_error:
                print(f"⚠️ Could not log verification: {log_error}")
            
            return jsonify({
                'success': True,
                'message': 'Role assigned successfully via Discord API'
            })
        else:
            error_msg = f'Discord API error: {response.status_code} - {response.text}'
            print(f"❌ {error_msg}")
            return jsonify({'success': False, 'error': error_msg})
            
    except Exception as e:
        print(f"❌ Error in discord_assign_role: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/verifications/<guild_id>')
def api_verifications(guild_id):
    try:
        limit = request.args.get('limit', 10, type=int)
        verifications = db.get_recent_verifications(guild_id, limit)
        
        result = []
        for v in verifications:
            result.append({
                'user_name': v['user_name'],
                'method': v['method'],
                'status': v['status'],
                'timestamp': v['timestamp']
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/test-setup')
def test_setup():
    return render_template('test_setup.html')

if __name__ == '__main__':
    # Production-friendly runner using environment variables
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'

    print("🌐 Starting VYNK Web Dashboard...")
    print(f"📍 Features: Discord OAuth, Web Verification Portal, Abstract API Integration")
    print("🔐 OAuth Configuration:")
    print(f"   - Client ID: {DISCORD_CLIENT_ID}")
    print(f"   - Redirect URI: {DISCORD_REDIRECT_URI}")
    print(f"📊 Database Status: ✅ Connected and ready")

    if debug:
        print(f"⚙️ Running in debug mode on port {port}")
        app.run(debug=True, port=port, host='0.0.0.0')
    else:
        # Use waitress for production WSGI serving
        try:
            from waitress import serve
            print(f"🚀 Production server starting on port {port}")
            serve(app, host='0.0.0.0', port=port)
        except Exception as e:
            print(f"❌ Failed to start production server: {e}")
            # Fallback to Flask dev server if waitress not available
            app.run(debug=False, port=port, host='0.0.0.0')