import sqlite3
import json
from datetime import datetime

class Database:
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
        
        self.conn.commit()
    
    def save_server_settings(self, guild_id, verification_channel, verified_role, log_channel=None, method='button'):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO server_settings 
            (guild_id, verification_channel, verified_role, log_channel, method)
            VALUES (?, ?, ?, ?, ?)
        ''', (guild_id, verification_channel, verified_role, log_channel, method))
        self.conn.commit()
    
    def log_verification(self, guild_id, user_id, user_name, method, status):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO verification_logs 
            (guild_id, user_id, user_name, method, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (guild_id, user_id, user_name, method, status, datetime.now().isoformat()))
        self.conn.commit()

# Global database instance
db = Database()