from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import os
from dotenv import load_dotenv
import asyncio
import queue
import time

load_dotenv()

app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'bot-api-secret-2024')

# Global bot reference and task queue
bot_ref = None
task_queue = queue.Queue()
results = {}

def set_bot(bot):
    global bot_ref
    bot_ref = bot

def bot_worker():
    """Run bot tasks in the bot's thread"""
    while True:
        try:
            task_id, guild_id, user_id = task_queue.get(timeout=1)
            if bot_ref and bot_ref.loop:
                # Schedule the task in the bot's event loop
                future = asyncio.run_coroutine_threadsafe(
                    assign_role_task(guild_id, user_id), 
                    bot_ref.loop
                )
                try:
                    result = future.result(timeout=10)  # 10 second timeout
                    results[task_id] = result
                except Exception as e:
                    results[task_id] = {'success': False, 'error': str(e)}
            task_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"❌ Bot worker error: {e}")

# Start the worker thread
worker_thread = threading.Thread(target=bot_worker, daemon=True)
worker_thread.start()

@app.route('/api/assign-role', methods=['POST', 'OPTIONS'])
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
        
        if not bot_ref:
            return jsonify({'success': False, 'error': 'Bot not initialized'})
        
        # Create task and wait for result
        task_id = f"{guild_id}_{user_id}_{int(time.time())}"
        task_queue.put((task_id, guild_id, user_id))
        
        # Wait for result (max 15 seconds)
        for _ in range(150):  # 150 * 0.1 = 15 seconds
            if task_id in results:
                result = results.pop(task_id)
                return jsonify(result)
            time.sleep(0.1)
        
        return jsonify({'success': False, 'error': 'Operation timeout'})
        
    except Exception as e:
        print(f"❌ Error in assign_role: {e}")
        return jsonify({'success': False, 'error': str(e)})

async def assign_role_task(guild_id, user_id):
    try:
        print(f"🔄 Starting role assignment for {user_id} in {guild_id}")
        
        guild = bot_ref.get_guild(int(guild_id))
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
        print(f"❌ Error in assign_role_task: {e}")
        return {'success': False, 'error': str(e)}

@app.route('/api/bot-status', methods=['GET'])
def bot_status():
    if bot_ref and bot_ref.is_ready():
        return jsonify({
            'status': 'online', 
            'guilds': len(bot_ref.guilds),
            'user': str(bot_ref.user),
            'latency': round(bot_ref.latency * 1000, 2)
        })
    return jsonify({'status': 'offline'})

def run_api():
    print("🤖 Starting Working Bot API on port 5001...")
    app.run(debug=False, port=5001, host='0.0.0.0', use_reloader=False)

def start_working_api(bot):
    set_bot(bot)
    thread = threading.Thread(target=run_api, daemon=True)
    thread.start()
    return thread