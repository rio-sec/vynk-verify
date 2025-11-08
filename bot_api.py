from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import os
from dotenv import load_dotenv
import asyncio
import concurrent.futures

load_dotenv()

# This runs alongside the bot to handle web verification requests
bot_api = Flask(__name__)
CORS(bot_api)  # Enable CORS for all routes
bot_api.secret_key = os.getenv('FLASK_SECRET_KEY', 'bot-api-secret-2024')

# Store bot instance globally
bot_instance = None
bot_loop = None

def set_bot_instance(bot):
    global bot_instance, bot_loop
    bot_instance = bot
    bot_loop = asyncio.new_event_loop()

@bot_api.route('/api/assign-role', methods=['POST', 'OPTIONS'])
def assign_role():
    if request.method == 'OPTIONS':
        return '', 200
        
    try:
        data = request.json
        guild_id = data.get('guild_id')
        user_id = data.get('user_id')
        
        print(f"🔧 API Request: Assign role to {user_id} in {guild_id}")
        
        if not guild_id or not user_id:
            return jsonify({'success': False, 'error': 'Missing guild_id or user_id'})
        
        if not bot_instance:
            return jsonify({'success': False, 'error': 'Bot not initialized'})
        
        # Run the async function in the bot's event loop
        result = run_async_in_thread(assign_role_async(guild_id, user_id))
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Error in assign_role: {e}")
        return jsonify({'success': False, 'error': str(e)})

def run_async_in_thread(coroutine):
    """Run an async coroutine in a separate thread with its own event loop"""
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(asyncio.run, coroutine)
        return future.result(timeout=30)  # 30 second timeout

async def assign_role_async(guild_id, user_id):
    try:
        print(f"🔄 Starting role assignment for {user_id} in {guild_id}")
        
        # Get the guild and user
        guild = bot_instance.get_guild(int(guild_id))
        if not guild:
            return {'success': False, 'error': 'Guild not found'}
        
        member = guild.get_member(int(user_id))
        if not member:
            return {'success': False, 'error': 'User not found in guild'}
        
        # Get verified role from database
        from database import db
        cursor = db.conn.cursor()
        cursor.execute('SELECT verified_role FROM server_settings WHERE guild_id = ?', (guild_id,))
        result = cursor.fetchone()
        
        if not result:
            return {'success': False, 'error': 'Server not configured. Please run /setup-web-verification first.'}
        
        verified_role_id = result[0]
        verified_role = guild.get_role(int(verified_role_id))
        
        if not verified_role:
            return {'success': False, 'error': f'Verified role (ID: {verified_role_id}) not found in server'}
        
        # Check if user already has the role
        if verified_role in member.roles:
            return {'success': True, 'message': f'User already has {verified_role.name} role'}
        
        print(f"🎯 Assigning role {verified_role.name} to {member.display_name}")
        
        # Assign the role
        await member.add_roles(verified_role)
        
        # Log the verification
        db.log_verification(
            guild_id=guild_id,
            user_id=user_id,
            user_name=str(member),
            method="web",
            status="success"
        )
        
        print(f"✅ Role assigned via web: {member} in {guild.name}")
        
        return {
            'success': True,
            'message': f'Role {verified_role.name} assigned successfully to {member.display_name}'
        }
        
    except Exception as e:
        print(f"❌ Error in assign_role_async: {e}")
        return {'success': False, 'error': str(e)}

@bot_api.route('/api/bot-status', methods=['GET'])
def bot_status():
    if bot_instance and bot_instance.is_ready():
        return jsonify({
            'status': 'online',
            'guilds': len(bot_instance.guilds),
            'user': str(bot_instance.user),
            'latency': round(bot_instance.latency * 1000, 2)
        })
    return jsonify({'status': 'offline'})

@bot_api.route('/api/test-role-assignment', methods=['POST'])
def test_role_assignment():
    """Test endpoint to verify role assignment works"""
    try:
        data = request.json
        guild_id = data.get('guild_id', '1427670272118624258')  # Your guild ID
        user_id = data.get('user_id', '987764845027950602')     # Your user ID
        
        result = run_async_in_thread(assign_role_async(guild_id, user_id))
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def run_bot_api():
    print("🤖 Starting Bot API Server on port 5001...")
    bot_api.run(debug=False, port=5001, host='0.0.0.0', use_reloader=False)

# Run in a separate thread
def start_bot_api(bot):
    set_bot_instance(bot)
    api_thread = threading.Thread(target=run_bot_api, daemon=True)
    api_thread.start()
    return api_thread