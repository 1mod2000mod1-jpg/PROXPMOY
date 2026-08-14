import os
import requests as rq
import re
import json as js
import time as ti
import telebot as tb
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from telebot import types
from flask import Flask, request, jsonify
import random
import urllib.parse
from datetime import datetime, timedelta
import sqlite3
import hashlib
import io
import base64
from urllib.parse import urlparse

# إعداد Flask لـ Render
app = Flask(__name__)

# إعداد التسجيل المتقدم
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('proxy_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# متغيرات البيئة من Render
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8047604654:AAEHdsWdFLaT2-YA6zIHu5dI6JmjYnCDNhg')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6154678499'))
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
SUPPORT_USER = '@xtt19x'
BOT_OWNER = '@xtt19x'

b = tb.TeleBot(BOT_TOKEN)

# 🎯 قاعدة بيانات المستخدمين المتقدمة
class UserDatabase:
    def __init__(self):
        self.conn = sqlite3.connect('users.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                join_date TEXT,
                membership_type TEXT DEFAULT 'free',
                requests_today INTEGER DEFAULT 0,
                last_request_date TEXT,
                is_banned INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0,
                custom_sources TEXT,
                max_proxies_per_check INTEGER DEFAULT 50,
                check_speed TEXT DEFAULT 'normal',
                auto_cleanup INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS working_proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy TEXT UNIQUE,
                proxy_type TEXT,
                country TEXT,
                speed REAL,
                last_checked TEXT,
                added_by INTEGER,
                source TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                source_name TEXT,
                source_url TEXT,
                source_type TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # إعدادات افتراضية
        settings = [
            ('bot_enabled', 'true'),
            ('maintenance_mode', 'false'),
            ('free_mode', 'true'),
            ('max_workers', '20'),
            ('auto_cleanup_days', '7'),
            ('duplicate_check', 'true')
        ]
        
        for key, value in settings:
            cursor.execute('INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)', (key, value))
        
        self.conn.commit()
    
    def add_user(self, user_id, username, first_name, last_name):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, join_date) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat()))
        self.conn.commit()
    
    def get_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def update_user_request(self, user_id):
        cursor = self.conn.cursor()
        today = datetime.now().date().isoformat()
        user = self.get_user(user_id)
        
        if user:
            last_date = user[7]
            if last_date == today:
                cursor.execute('''
                    UPDATE users SET requests_today = requests_today + 1 
                    WHERE user_id = ?
                ''', (user_id,))
            else:
                cursor.execute('''
                    UPDATE users SET requests_today = 1, last_request_date = ?
                    WHERE user_id = ?
                ''', (today, user_id))
            self.conn.commit()
    
    def get_bot_setting(self, key):
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM bot_settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    
    def set_bot_setting(self, key, value):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO bot_settings (key, value) 
            VALUES (?, ?)
        ''', (key, value))
        self.conn.commit()
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users')
        return cursor.fetchall()
    
    def update_user_points(self, user_id, points):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (points, user_id))
        self.conn.commit()
    
    def set_user_premium(self, user_id, is_premium=True):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET is_premium = ? WHERE user_id = ?', (1 if is_premium else 0, user_id))
        self.conn.commit()
    
    def update_user_setting(self, user_id, setting, value):
        cursor = self.conn.cursor()
        cursor.execute(f'UPDATE users SET {setting} = ? WHERE user_id = ?', (value, user_id))
        self.conn.commit()
    
    def add_custom_source(self, user_id, name, url, source_type):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO custom_sources (user_id, source_name, source_url, source_type)
            VALUES (?, ?, ?, ?)
        ''', (user_id, name, url, source_type))
        self.conn.commit()
    
    def get_custom_sources(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM custom_sources WHERE user_id = ? AND is_active = 1', (user_id,))
        return cursor.fetchall()
    
    def add_working_proxy(self, proxy, proxy_type, country, speed, user_id, source):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO working_proxies 
                (proxy, proxy_type, country, speed, last_checked, added_by, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (proxy, proxy_type, country, speed, datetime.now().isoformat(), user_id, source))
            self.conn.commit()
            return True
        except:
            return False
    
    def get_working_proxies_count(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM working_proxies')
        return cursor.fetchone()[0]
    
    def get_proxies_by_type(self, proxy_type):
        cursor = self.conn.cursor()
        cursor.execute('SELECT proxy FROM working_proxies WHERE proxy_type = ?', (proxy_type,))
        return [row[0] for row in cursor.fetchall()]
    
    def cleanup_old_proxies(self, days=7):
        cursor = self.conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute('DELETE FROM working_proxies WHERE last_checked < ?', (cutoff_date,))
        deleted = cursor.rowcount
        self.conn.commit()
        return deleted

# تهيئة قاعدة البيانات
db = UserDatabase()

# 🎯 إعدادات البوت المتقدمة
class ProxyBotConfig:
    def __init__(self):
        self.user_states = {}
        self.working_proxies = []
        self.checked_proxies_count = 0
        self.session_stats = {
            'total_proxies_found': 0,
            'total_proxies_checked': 0,
            'working_proxies_found': 0,
            'total_users': 0,
            'start_time': ti.time()
        }
        
        # تحميل الإعدادات من قاعدة البيانات
        self.bot_enabled = db.get_bot_setting('bot_enabled') == 'true'
        self.maintenance_mode = db.get_bot_setting('maintenance_mode') == 'true'
        self.duplicate_check = db.get_bot_setting('duplicate_check') == 'true'
        self.max_workers = int(db.get_bot_setting('max_workers') or 20)
        
        # إعدادات الفحص
        self.filter_settings = {
            'country': None,
            'protocol': 'all',
            'timeout': 10,
            'check_working': True,
            'max_workers': self.max_workers
        }
        
        # إعدادات السرعة
        self.speed_settings = {
            'very_slow': {'workers': 5, 'timeout': 30, 'delay': 2},
            'slow': {'workers': 10, 'timeout': 20, 'delay': 1},
            'normal': {'workers': 15, 'timeout': 15, 'delay': 0.5},
            'fast': {'workers': 25, 'timeout': 10, 'delay': 0.2},
            'very_fast': {'workers': 40, 'timeout': 8, 'delay': 0.1}
        }

config = ProxyBotConfig()

# 🎯 قاعدة بيانات المصادر المتقدمة الموسعة
PROXY_SOURCES = {
    "premium_apis": {
        "name": "🌟 واجهات برمجة",
        "enabled": True,
        "type": "api",
        "sites": [
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://www.proxy-list.download/api/v1/get?type=http",
            "https://www.proxy-list.download/api/v1/get?type=https",
            "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc"
        ]
    },
    "raw_sources": {
        "name": "📁 مصادر مباشرة",
        "enabled": True,
        "type": "text",
        "sites": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt",
            "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
            "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
            "https://raw.githubusercontent.com/mertguvencli/http-proxy-list/main/proxy-list/data.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt"
        ]
    },
    "socks_sources": {
        "name": "🧦 مصادر SOCKS",
        "enabled": True,
        "type": "text",
        "sites": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt"
        ]
    }
}

# 🎯 قوائم User-Agent الموسعة
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0'
]

# 🌐 مواقع فحص البروكسيات الموسعة
TEST_SITES = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://ident.me",
    "https://ipinfo.io/json",
    "https://api.myip.com",
    "https://ipapi.co/json",
    "https://www.ipify.org",
    "https://seeip.org",
    "https://checkip.amazonaws.com",
    "https://icanhazip.com"
]

# 🌐 Routes لـ Render.com
@app.route('/')
def home():
    bot_status = "✅ نشط" if config.bot_enabled else "⛔ متوقف"
    maintenance_status = "🔧 في الصيانة" if config.maintenance_mode else "⚡ جاهز"
    working_proxies_count = db.get_working_proxies_count()
    
    return f"""
    <html>
        <head>
            <title>⚡ ℙℛᎾXᎽ ℙℳᎾ 𖠛 - الأقوى على الإطلاق</title>
            <style>
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    min-height: 100vh;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 50px;
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    padding: 30px;
                    border-radius: 20px;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                }}
                .status-cards {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .card {{
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    padding: 25px;
                    border-radius: 15px;
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    transition: transform 0.3s ease;
                }}
                .card:hover {{
                    transform: translateY(-5px);
                }}
                .stats {{
                    font-size: 2.5em;
                    font-weight: bold;
                    margin: 10px 0;
                    color: #ffd700;
                }}
                .btn {{
                    display: inline-block;
                    background: linear-gradient(45deg, #007bff, #0056b3);
                    color: white;
                    padding: 12px 25px;
                    text-decoration: none;
                    border-radius: 8px;
                    margin: 8px;
                    font-weight: bold;
                    transition: all 0.3s ease;
                    box-shadow: 0 4px 15px rgba(0, 123, 255, 0.3);
                }}
                .btn:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(0, 123, 255, 0.4);
                    color: white;
                }}
                .premium {{
                    background: linear-gradient(45deg, #ff6b6b, #ee5a24);
                }}
                .owner {{
                    background: linear-gradient(45deg, #ffd700, #ffa500);
                    color: #333;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1 style="font-size: 3em; margin-bottom: 10px;">⚡ ℙℛᎾXᎽ ℙℳᎾ 𖠛</h1>
                    <p style="font-size: 1.3em; opacity: 0.9;">أقوى وأسرع بوت سحب وفحص بروكسيات على الإطلاق</p>
                    <div style="display: flex; justify-content: center; gap: 20px; margin-top: 20px;">
                        <div style="background: rgba(255, 215, 0, 0.2); padding: 10px 20px; border-radius: 10px;">
                            👑 المالك: {BOT_OWNER}
                        </div>
                        <div style="background: rgba(0, 123, 255, 0.2); padding: 10px 20px; border-radius: 10px;">
                            📞 الدعم: {SUPPORT_USER}
                        </div>
                    </div>
                    <div style="margin-top: 20px;">
                        <span style="background: {'#28a745' if config.bot_enabled else '#dc3545'}; padding: 8px 16px; border-radius: 20px;">
                            الحالة: {bot_status}
                        </span>
                        <span style="background: {'#ffc107' if config.maintenance_mode else '#17a2b8'}; padding: 8px 16px; border-radius: 20px; margin-left: 10px;">
                            {maintenance_status}
                        </span>
                    </div>
                </div>
                
                <div class="status-cards">
                    <div class="card">
                        <h3>📊 البروكسيات المسحوبة</h3>
                        <div class="stats">{config.session_stats['total_proxies_found']}</div>
                    </div>
                    <div class="card">
                        <h3>✅ البروكسيات الشغالة</h3>
                        <div class="stats">{working_proxies_count}</div>
                    </div>
                    <div class="card">
                        <h3>👥 المستخدمين</h3>
                        <div class="stats">{config.session_stats['total_users']}</div>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 40px;">
                    <a href="/test-proxy" class="btn">🧪 فحص بروكسي يدوي</a>
                    <a href="/health" class="btn">📊 حالة البوت المتقدمة</a>
                    <a href="/proxies-list" class="btn premium">📁 البروكسيات الشغالة</a>
                    <a href="https://t.me/{BOT_OWNER.replace('@', '')}" class="btn owner">👑 تواصل مع المالك</a>
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/health')
def health_check():
    working_proxies_count = db.get_working_proxies_count()
    return jsonify({
        'status': 'healthy',
        'bot_enabled': config.bot_enabled,
        'maintenance_mode': config.maintenance_mode,
        'timestamp': ti.time(),
        'uptime': ti.time() - config.session_stats['start_time'],
        'stats': config.session_stats,
        'working_proxies': working_proxies_count,
        'owner': BOT_OWNER,
        'support': SUPPORT_USER
    })

@app.route('/proxies-list')
def proxies_list():
    http_proxies = db.get_proxies_by_type('HTTP')
    https_proxies = db.get_proxies_by_type('HTTPS')
    socks4_proxies = db.get_proxies_by_type('SOCKS4')
    socks5_proxies = db.get_proxies_by_type('SOCKS5')
    
    return f"""
    <html>
        <head>
            <title>📁 البروكسيات الشغالة</title>
            <style>
                body {{ font-family: Arial; margin: 20px; background: #f5f5f5; }}
                .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 10px; }}
                .proxy-type {{ margin-bottom: 20px; }}
                .proxy-list {{ background: #f8f9fa; padding: 10px; border-radius: 5px; max-height: 200px; overflow-y: auto; }}
                h2 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📁 البروكسيات الشغالة المخزنة</h1>
                
                <div class="proxy-type">
                    <h2>🌐 HTTP ({len(http_proxies)})</h2>
                    <div class="proxy-list">
                        {''.join([f'<div>{proxy}</div>' for proxy in http_proxies[:50]])}
                        {f'<div>... و {len(http_proxies) - 50} أكثر</div>' if len(http_proxies) > 50 else ''}
                    </div>
                </div>
                
                <div class="proxy-type">
                    <h2>🔒 HTTPS ({len(https_proxies)})</h2>
                    <div class="proxy-list">
                        {''.join([f'<div>{proxy}</div>' for proxy in https_proxies[:50]])}
                        {f'<div>... و {len(https_proxies) - 50} أكثر</div>' if len(https_proxies) > 50 else ''}
                    </div>
                </div>
                
                <div class="proxy-type">
                    <h2>🧦 SOCKS4 ({len(socks4_proxies)})</h2>
                    <div class="proxy-list">
                        {''.join([f'<div>{proxy}</div>' for proxy in socks4_proxies[:50]])}
                        {f'<div>... و {len(socks4_proxies) - 50} أكثر</div>' if len(socks4_proxies) > 50 else ''}
                    </div>
                </div>
                
                <div class="proxy-type">
                    <h2>🧦 SOCKS5 ({len(socks5_proxies)})</h2>
                    <div class="proxy-list">
                        {''.join([f'<div>{proxy}</div>' for proxy in socks5_proxies[:50]])}
                        {f'<div>... و {len(socks5_proxies) - 50} أكثر</div>' if len(socks5_proxies) > 50 else ''}
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 20px;">
                    <a href="/" class="btn" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">العودة للرئيسية</a>
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook مع معالجة الأخطاء المحسنة"""
    try:
        if request.headers.get('content-type') == 'application/json':
            json_string = request.get_data().decode('utf-8')
            update = types.Update.de_json(json_string)
            b.process_new_updates([update])
            return 'OK', 200
        return 'Invalid content type', 400
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'Error', 500

@app.route('/test-proxy', methods=['GET', 'POST'])
def test_proxy_web():
    if request.method == 'POST':
        proxy = request.form.get('proxy', '')
        if proxy:
            try:
                result = advanced_proxy_check(proxy)
                return f"""
                <html>
                <head>
                    <title>نتيجة الفحص</title>
                    <style>
                        body {{ font-family: Arial; padding: 20px; background: #f5f5f5; }}
                        .result {{ background: {'#d4edda' if result['working'] else '#f8d7da'}; padding: 20px; border-radius: 10px; }}
                        .btn {{ background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }}
                    </style>
                </head>
                <body>
                    <h2>🧪 نتيجة فحص البروكسي</h2>
                    <div class="result">
                        <h3>{'✅ البروكسي شغال' if result['working'] else '❌ البروكسي لا يعمل'}</h3>
                        <p><strong>البروكسي:</strong> {proxy}</p>
                        {f"<p><strong>IP الجديد:</strong> {result['ip']}</p>" if result['working'] else ""}
                        {f"<p><strong>السرعة:</strong> {result['speed']} ثانية</p>" if result['working'] else ""}
                        {f"<p><strong>النوع:</strong> {result['type']}</p>" if result['working'] else ""}
                        {f"<p><strong>الدولة:</strong> {result['country']}</p>" if result['working'] else ""}
                    </div>
                    <br>
                    <a href="/test-proxy" class="btn">فحص بروكسي آخر</a>
                </body>
                </html>
                """
            except Exception as e:
                return f"خطأ في الفحص: {str(e)}"
    
    return '''
    <html>
    <head>
        <title>فحص البروكسيات</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #f5f5f5; }
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            input, button { padding: 12px; margin: 10px 0; width: 100%; box-sizing: border-box; }
            button { background: #007bff; color: white; border: none; cursor: pointer; border-radius: 5px; font-size: 16px; }
            input { border: 1px solid #ddd; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 style="text-align: center; color: #333;">🧪 فحص البروكسيات يدوياً</h1>
            <form method="POST">
                <input type="text" name="proxy" placeholder="أدخل البروكسي (مثال: 194.35.125.100:8080 أو https://194.35.125.100:8080)" required>
                <button type="submit">فحص البروكسي</button>
            </form>
        </div>
    </body>
    </html>
    '''

# 🛠️ أدوات مساعدة محسنة
def get_rotating_session():
    session = rq.Session()
    session.trust_env = False
    session.headers.update({
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    })
    session.verify = True
    return session

def safe_request(url, timeout=15):
    try:
        session = get_rotating_session()
        response = session.get(url, timeout=timeout)
        return response if response.status_code == 200 else None
    except:
        return None

# 🎯 نظام الفحص المتقدم المحسن
def advanced_proxy_check(proxy):
    try:
        # تحديد نوع البروكسي
        if proxy.startswith('https://'):
            proxy_dict = {'https': proxy}
            proxy_type = "HTTPS"
        elif proxy.startswith('socks4://'):
            proxy_dict = {'http': proxy, 'https': proxy}
            proxy_type = "SOCKS4"
        elif proxy.startswith('socks5://'):
            proxy_dict = {'http': proxy, 'https': proxy}
            proxy_type = "SOCKS5"
        else:
            proxy_dict = {'http': proxy, 'https': proxy}
            proxy_type = "HTTP"
        
        original_ip = get_original_ip()
        
        test_results = []
        start_time = ti.time()
        
        for test_url in TEST_SITES[:6]:  # اختبار 6 مواقع للدقة
            try:
                test_start = ti.time()
                response = rq.get(test_url, proxies=proxy_dict, timeout=8, verify=False)
                test_time = ti.time() - test_start
                
                if response.status_code == 200:
                    proxy_ip = extract_ip_from_response(response, test_url)
                    if proxy_ip and proxy_ip != original_ip:
                        test_results.append({'success': True, 'speed': test_time, 'ip': proxy_ip})
            except:
                continue
        
        successful_tests = [r for r in test_results if r['success']]
        
        if successful_tests:
            speeds = [r['speed'] for r in successful_tests]
            avg_speed = sum(speeds) / len(speeds)
            
            country, country_code = get_country_from_ip(successful_tests[0]['ip'])
            
            return {
                'proxy': proxy, 'working': True, 'speed': round(avg_speed, 2),
                'ip': successful_tests[0]['ip'], 'type': proxy_type,
                'country': country, 'tests_passed': len(successful_tests)
            }
        else:
            return {'proxy': proxy, 'working': False, 'speed': 0, 'ip': '', 'type': 'Unknown', 'country': 'Unknown'}
            
    except Exception as e:
        return {'proxy': proxy, 'working': False, 'speed': 0, 'ip': '', 'type': 'Unknown', 'country': 'Unknown', 'error': str(e)}

def extract_ip_from_response(response, test_url):
    try:
        if any(site in test_url for site in ['ipify', 'ipinfo', 'myip', 'ipapi']):
            return response.json().get('ip', '')
        elif 'httpbin' in test_url:
            return response.json().get('origin', '')
        else:
            return response.text.strip()
    except:
        return ''

def get_original_ip():
    try:
        response = rq.get("https://api.ipify.org?format=json", timeout=5)
        return response.json().get('ip', '')
    except:
        return "Unknown"

def get_country_from_ip(ip):
    try:
        response = rq.get(f"http://ip-api.com/json/{ip}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get('country', 'Unknown'), data.get('countryCode', 'Unknown')
    except:
        pass
    return 'Unknown', 'Unknown'

# 🎯 نظام إدارة المستخدمين المحسن
def register_user(user_id, username, first_name, last_name):
    db.add_user(user_id, username, first_name, last_name)
    config.session_stats['total_users'] += 1

def can_user_use_bot(user_id):
    if user_id == ADMIN_ID:
        return True, "مسؤول"
    
    if not config.bot_enabled:
        return False, "البوت متوقف حالياً"
    
    if config.maintenance_mode:
        return False, "البوت في وضع الصيانة"
    
    user = db.get_user(user_id)
    if user and user[8]:  # is_banned
        return False, "تم حظرك من استخدام البوت"
    
    # التحقق من حد الطلبات اليومي للمستخدمين العاديين
    if user and user[5] == 'free':  # membership_type
        today = datetime.now().date().isoformat()
        if user[7] == today and user[6] >= 10:  # last_request_date و requests_today
            return False, "لقد استخدمت جميع طلباتك اليومية (10 طلبات)"
    
    return True, "مسموح"

# 🎯 نظام السحب الذكي المحسن
def smart_pull_proxies(chat_id, user_id):
    status, message = can_user_use_bot(user_id)
    if not status:
        b.send_message(chat_id, f"⛔ {message}")
        return []
    
    db.update_user_request(user_id)
    
    # الحصول على إعدادات المستخدم
    user = db.get_user(user_id)
    check_speed = user[13] if user and len(user) > 13 else 'normal'  # check_speed
    
    msg = b.send_message(chat_id, "🚀 بدء السحب الذكي المتقدم للبروكسيات...")
    
    all_proxies = []
    
    # سحب من المصادر الأساسية
    for source_id, source_info in PROXY_SOURCES.items():
        if source_info['enabled']:
            b.edit_message_text(f"🔍 يبحث في: {source_info['name']}", chat_id, msg.message_id)
            
            for site_url in source_info['sites']:
                try:
                    response = safe_request(site_url, timeout=25)
                    if response:
                        proxies = extract_proxies_from_text(response.text)
                        if proxies:
                            all_proxies.extend(proxies)
                            b.edit_message_text(f"✅ {source_info['name']}: تم سحب {len(proxies)} بروكسي", chat_id, msg.message_id)
                    ti.sleep(0.5)
                except Exception as e:
                    continue
    
    # سحب من المصادر المخصصة للمستخدم
    custom_sources = db.get_custom_sources(user_id)
    if custom_sources:
        b.edit_message_text(f"🔍 يبحث في المصادر المخصصة ({len(custom_sources)})", chat_id, msg.message_id)
        
        for source in custom_sources:
            try:
                response = safe_request(source[3], timeout=25)
                if response:
                    proxies = extract_proxies_from_text(response.text)
                    if proxies:
                        all_proxies.extend(proxies)
                        b.edit_message_text(f"✅ {source[2]}: تم سحب {len(proxies)} بروكسي", chat_id, msg.message_id)
                ti.sleep(0.5)
            except:
                continue
    
    # إزالة التكرارات
    all_proxies = list(set(all_proxies))
    config.session_stats['total_proxies_found'] += len(all_proxies)
    
    if all_proxies:
        b.edit_message_text(f"📥 تم سحب {len(all_proxies)} بروكسي بنجاح!\n⚡ جاري الفحص المتقدم...", chat_id, msg.message_id)
        
        # الفحص حسب سرعة المستخدم المختارة
        working_proxies = advanced_check_proxies(all_proxies, chat_id, msg.message_id, check_speed)
        
        # حفظ البروكسيات الشغالة في قاعدة البيانات
        for proxy_data in working_proxies:
            db.add_working_proxy(
                proxy_data['proxy'], proxy_data['type'], 
                proxy_data['country'], proxy_data['speed'], 
                user_id, "smart_pull"
            )
        
        return working_proxies
    else:
        b.edit_message_text("❌ لم يتم العثور على أي بروكسيات من المصادر المتاحة", chat_id, msg.message_id)
        return []

def extract_proxies_from_text(text):
    proxy_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}\b'
    return re.findall(proxy_pattern, text)

# 🎯 نظام الفحص المتقدم المحسن
def advanced_check_proxies(proxies, chat_id, message_id, speed='normal'):
    speed_config = config.speed_settings.get(speed, config.speed_settings['normal'])
    max_workers = speed_config['workers']
    timeout = speed_config['timeout']
    delay = speed_config['delay']
    
    working_proxies = []
    checked_count = 0
    total_proxies = len(proxies)
    
    def check_single_proxy(proxy):
        nonlocal checked_count
        result = advanced_proxy_check(proxy)
        checked_count += 1
        
        if result['working']:
            working_proxies.append(result)
        
        # تحديث التقدم كل 10 بروكسيات
        if checked_count % 10 == 0:
            progress = (checked_count / total_proxies) * 100
            try:
                b.edit_message_text(
                    f"🔍 فحص البروكسيات...\n"
                    f"📊 التقدم: {progress:.1f}%\n"
                    f"✅ الشغالة: {len(working_proxies)}\n"
                    f"🔍 تم فحص: {checked_count}/{total_proxies}\n"
                    f"⚡ السرعة: {speed.replace('_', ' ').title()}",
                    chat_id, message_id
                )
            except:
                pass
        
        ti.sleep(delay)
        return result
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(check_single_proxy, proxy) for proxy in proxies]
        
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                pass
    
    config.session_stats['total_proxies_checked'] += total_proxies
    config.session_stats['working_proxies_found'] += len(working_proxies)
    
    return working_proxies

# 🎯 نظام الواجهات المحسن
def create_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    
    # الحصول على معلومات المستخدم
    user = db.get_user(user_id)
    membership = "👑 مميز" if user and user[9] else "🆓 عادي"  # is_premium
    
    # الأزرار الأساسية
    btn1 = types.KeyboardButton('🚀 سحب وفحص بروكسيات')
    btn2 = types.KeyboardButton('📁 البروكسيات الشغالة')
    btn3 = types.KeyboardButton('⚙️ الإعدادات المتقدمة')
    btn4 = types.KeyboardButton('👑 العضوية والمميزات')
    
    # الأزرار الإضافية للمستخدمين المميزين والمسؤولين
    if user_id == ADMIN_ID:
        btn5 = types.KeyboardButton('👨‍💼 لوحة التحكم')
        markup.add(btn1, btn2, btn3, btn4, btn5)
    elif user and user[9]:  # is_premium
        btn5 = types.KeyboardButton('🌟 المميزات')
        markup.add(btn1, btn2, btn3, btn4, btn5)
    else:
        markup.add(btn1, btn2, btn3, btn4)
    
    return markup

def create_settings_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    user = db.get_user(user_id)
    current_speed = user[13] if user and len(user) > 13 else 'normal'  # check_speed
    current_max = user[12] if user and len(user) > 12 else 50  # max_proxies_per_check
    auto_cleanup = user[14] if user and len(user) > 14 else 1  # auto_cleanup
    
    speed_btn = types.InlineKeyboardButton(f'⚡ السرعة: {current_speed.replace("_", " ").title()}', callback_data='speed_settings')
    max_btn = types.InlineKeyboardButton(f'📊 العدد: {current_max}', callback_data='max_settings')
    cleanup_btn = types.InlineKeyboardButton(f'🧹 التنظيف: {"✅" if auto_cleanup else "❌"}', callback_data='toggle_cleanup')
    sources_btn = types.InlineKeyboardButton('🔗 المصادر المخصصة', callback_data='custom_sources')
    back_btn = types.InlineKeyboardButton('🔙 رجوع', callback_data='main_menu')
    
    markup.add(speed_btn, max_btn, cleanup_btn, sources_btn, back_btn)
    return markup

def create_speed_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    speeds = [
        ('🐌 بطيء جداً', 'very_slow'),
        ('🐢 بطيء', 'slow'),
        ('⚡ عادي', 'normal'),
        ('🚀 سريع', 'fast'),
        ('🔥 سريع جداً', 'very_fast')
    ]
    
    buttons = []
    for name, value in speeds:
        buttons.append(types.InlineKeyboardButton(name, callback_data=f'set_speed_{value}'))
    
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton('🔙 رجوع', callback_data='settings_menu'))
    return markup

def create_admin_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton('📊 إحصائيات البوت', callback_data='bot_stats')
    btn2 = types.InlineKeyboardButton('👥 إدارة المستخدمين', callback_data='manage_users')
    btn3 = types.InlineKeyboardButton('⚙️ إعدادات البوت', callback_data='bot_settings')
    btn4 = types.InlineKeyboardButton('🔧 الصيانة', callback_data='maintenance')
    btn5 = types.InlineKeyboardButton('🧹 تنظيف النظام', callback_data='cleanup_system')
    btn6 = types.InlineKeyboardButton('📤 تصدير البيانات', callback_data='export_data')
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    return markup

def create_membership_menu(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    user = db.get_user(user_id)
    points = user[10] if user and len(user) > 10 else 0  # points
    is_premium = user[9] if user and len(user) > 9 else 0  # is_premium
    
    btn1 = types.InlineKeyboardButton(f'🎯 نقاطي: {points}', callback_data='my_points')
    btn2 = types.InlineKeyboardButton('🆓 ترقية عضوية', callback_data='upgrade_membership')
    btn3 = types.InlineKeyboardButton('🎁 المميزات', callback_data='premium_features')
    btn4 = types.InlineKeyboardButton('💎 شراء نقاط', callback_data='buy_points')
    
    if user_id == ADMIN_ID:
        btn5 = types.InlineKeyboardButton('👑 إدارة النقاط', callback_data='manage_points')
        markup.add(btn1, btn2, btn3, btn4, btn5)
    else:
        markup.add(btn1, btn2, btn3, btn4)
    
    return markup

# 🎯 نظام الدعم الفخم
def create_support_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton('📞 تواصل مع الدعم', url=f'https://t.me/{SUPPORT_USER.replace("@", "")}')
    btn2 = types.InlineKeyboardButton('👑 تواصل مع المالك', url=f'https://t.me/{BOT_OWNER.replace("@", "")}')
    btn3 = types.InlineKeyboardButton('🌐 موقع البوت', url=RENDER_URL if RENDER_URL else 'https://t.me/')
    btn4 = types.InlineKeyboardButton('📚 الدليل والمساعدة', callback_data='help_guide')
    
    markup.add(btn1, btn2, btn3, btn4)
    return markup

# 🎯 معالجات الأوامر المحسنة
@b.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    register_user(user_id, username, first_name, last_name)
    
    welcome_text = f"""
    ⚡ **مرحباً بك في أقوى بوت بروكسيات على التليجرام!** ⚡

    👑 **المالك:** {BOT_OWNER}
    📞 **الدعم:** {SUPPORT_USER}

    🚀 **المميزات المتوفرة:**
    • ✅ سحب بروكسيات من مصادر متعددة
    • 🔍 فحص متقدم بدقة عالية
    • ⚡ سرعات فحص قابلة للتخصيص
    • 📊 إحصائيات مفصلة
    • 👥 نظام عضوية متكامل
    • 🎯 نقاط ومكافآت

    **اختر من القائمة أدناه:** 👇
    """
    
    b.send_message(message.chat.id, welcome_text, 
                  reply_markup=create_main_menu(user_id),
                  parse_mode='Markdown')

@b.message_handler(commands=['support'])
def support_command(message):
    support_text = f"""
    🛠️ **مركز الدعم الفخم** 🛠️

    👑 **المطور والمالك:** {BOT_OWNER}
    📞 **الدعم الفني:** {SUPPORT_USER}
    🌐 **موقع البوت:** {RENDER_URL if RENDER_URL else 'قريباً'}

    ⭐ **مميزات البوت:**
    • نظام سحب ذكي متقدم
    • فحص بدقة وجودة عالية
    • واجهة مستخدم فخمة
    • إعدادات متقدمة قابلة للتخصيص
    • دعم فني سريع

    📧 **للاستفسارات والشكاوى:**
    تواصل مباشرة مع فريق الدupport
    """
    
    b.send_message(message.chat.id, support_text,
                  reply_markup=create_support_menu(),
                  parse_mode='Markdown')

@b.message_handler(func=lambda message: message.text == '🚀 سحب وفحص بروكسيات')
def smart_pull_handler(message):
    user_id = message.from_user.id
    
    status, msg_text = can_user_use_bot(user_id)
    if not status:
        b.send_message(message.chat.id, f"⛔ {msg_text}")
        return
    
    # عرض خيارات السحب
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton('🌐 سحب ذكي من الإنترنت', callback_data='pull_smart')
    btn2 = types.InlineKeyboardButton('📁 فحص ملف بروكسيات', callback_data='pull_file')
    btn3 = types.InlineKeyboardButton('⚡ فحص سريع (محدود)', callback_data='pull_quick')
    btn4 = types.InlineKeyboardButton('🔙 رجوع', callback_data='main_menu')
    
    markup.add(btn1, btn2, btn3, btn4)
    
    b.send_message(message.chat.id, 
                  "🚀 **اختر طريقة سحب البروكسيات:**\n\n"
                  "• 🌐 السحب الذكي: سحب من جميع المصادر\n"
                  "• 📁 فحص ملف: رفع ملف بروكسيات لفحصه\n"
                  "• ⚡ فحص سريع: فحص محدود وسريع", 
                  reply_markup=markup,
                  parse_mode='Markdown')

@b.message_handler(func=lambda message: message.text == '📁 البروكسيات الشغالة')
def working_proxies_handler(message):
    user_id = message.from_user.id
    
    http_count = len(db.get_proxies_by_type('HTTP'))
    https_count = len(db.get_proxies_by_type('HTTPS'))
    socks4_count = len(db.get_proxies_by_type('SOCKS4'))
    socks5_count = len(db.get_proxies_by_type('SOCKS5'))
    total_count = db.get_working_proxies_count()
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton(f'🌐 HTTP ({http_count})', callback_data='get_http')
    btn2 = types.InlineKeyboardButton(f'🔒 HTTPS ({https_count})', callback_data='get_https')
    btn3 = types.InlineKeyboardButton(f'🧦 SOCKS4 ({socks4_count})', callback_data='get_socks4')
    btn4 = types.InlineKeyboardButton(f'🧦 SOCKS5 ({socks5_count})', callback_data='get_socks5')
    btn5 = types.InlineKeyboardButton('📥 تحميل الكل', callback_data='get_all_proxies')
    btn6 = types.InlineKeyboardButton('🔄 تحديث', callback_data='refresh_proxies')
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    
    text = f"""
    📊 **البروكسيات الشغالة المخزنة:**

    🌐 **HTTP:** `{http_count}`
    🔒 **HTTPS:** `{https_count}`
    🧦 **SOCKS4:** `{socks4_count}`
    🧦 **SOCKS5:** `{socks5_count}`
    📁 **المجموع:** `{total_count}`

    ⏰ **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    **اختر النوع الذي تريد تحميله:** 👇
    """
    
    b.send_message(message.chat.id, text, 
                  reply_markup=markup,
                  parse_mode='Markdown')

@b.message_handler(func=lambda message: message.text == '⚙️ الإعدادات المتقدمة')
def settings_handler(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    current_speed = user[13] if user and len(user) > 13 else 'normal'
    current_max = user[12] if user and len(user) > 12 else 50
    auto_cleanup = user[14] if user and len(user) > 14 else 1
    
    text = f"""
    ⚙️ **الإعدادات المتقدمة**

    ⚡ **سرعة الفحص:** `{current_speed.replace('_', ' ').title()}`
    📊 **الحد الأقصى:** `{current_max} بروكسي`
    🧹 **التنظيف التلقائي:** `{'مفعل' if auto_cleanup else 'معطل'}`

    **اختر الإعداد الذي تريد تعديله:** 👇
    """
    
    b.send_message(message.chat.id, text,
                  reply_markup=create_settings_menu(user_id),
                  parse_mode='Markdown')

@b.message_handler(func=lambda message: message.text == '👑 العضوية والمميزات')
def membership_handler(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    points = user[10] if user and len(user) > 10 else 0
    is_premium = user[9] if user and len(user) > 9 else 0
    membership_type = "👑 مميز" if is_premium else "🆓 عادي"
    
    text = f"""
    👑 **نظام العضوية والمميزات**

    🎯 **نقاطك:** `{points}`
    💎 **عضويتك:** `{membership_type}`
    📅 **تاريخ الانضمام:** `{user[4] if user else 'غير معروف'}`

    🚀 **مميزات العضوية المميزة:**
    • ✅ عدد غير محدود من الطلبات
    • ⚡ سرعات فحص أعلى
    • 🔗 إضافة مصادر مخصصة
    • 📊 إحصائيات متقدمة
    • 🎯 دعم فني متميز

    **اختر من الخيارات أدناه:** 👇
    """
    
    b.send_message(message.chat.id, text,
                  reply_markup=create_membership_menu(user_id),
                  parse_mode='Markdown')

@b.message_handler(func=lambda message: message.text == '👨‍💼 لوحة التحكم')
def admin_panel_handler(message):
    if message.from_user.id != ADMIN_ID:
        b.send_message(message.chat.id, "⛔ ليس لديك صلاحية الوصول لهذا القسم!")
        return
    
    text = """
    👨‍💼 **لوحة تحكم المسؤول**

    🛠️ **إدارة البوت بالكامل:**
    • 📊 الإحصائيات والمتابعة
    • 👥 إدارة المستخدمين
    • ⚙️ إعدادات البوت المتقدمة
    • 🔧 وضع الصيانة
    • 🧹 تنظيف النظام

    **اختر المهمة التي تريد تنفيذها:** 👇
    """
    
    b.send_message(message.chat.id, text,
                  reply_markup=create_admin_menu(),
                  parse_mode='Markdown')

# 🎯 معالجات Callback المحسنة
@b.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    try:
        if call.data == 'main_menu':
            b.edit_message_text("🏠 **القائمة الرئيسية**", chat_id, message_id,
                              reply_markup=create_main_menu(user_id),
                              parse_mode='Markdown')
        
        elif call.data == 'settings_menu':
            user = db.get_user(user_id)
            current_speed = user[13] if user and len(user) > 13 else 'normal'
            current_max = user[12] if user and len(user) > 12 else 50
            
            text = f"""
            ⚙️ **الإعدادات المتقدمة**

            ⚡ **سرعة الفحص:** `{current_speed.replace('_', ' ').title()}`
            📊 **الحد الأقصى:** `{current_max} بروكسي`

            **اختر الإعداد الذي تريد تعديله:** 👇
            """
            
            b.edit_message_text(text, chat_id, message_id,
                              reply_markup=create_settings_menu(user_id),
                              parse_mode='Markdown')
        
        elif call.data == 'speed_settings':
            b.edit_message_text("⚡ **اختر سرعة الفحص:**\n\n"
                              "• 🐌 بطيء جداً: دقة عالية، وقت أطول\n"
                              "• 🐢 بطيء: دقة جيدة، وقت معقول\n"
                              "• ⚡ عادي: توازن بين السرعة والدقة\n"
                              "• 🚀 سريع: سرعة عالية، دقة أقل\n"
                              "• 🔥 سريع جداً: أقصى سرعة", 
                              chat_id, message_id,
                              reply_markup=create_speed_menu())
        
        elif call.data.startswith('set_speed_'):
            speed = call.data.replace('set_speed_', '')
            db.update_user_setting(user_id, 'check_speed', speed)
            
            b.edit_message_text(f"✅ **تم تحديث سرعة الفحص إلى:** `{speed.replace('_', ' ').title()}`", 
                              chat_id, message_id,
                              reply_markup=create_settings_menu(user_id),
                              parse_mode='Markdown')
        
        elif call.data == 'pull_smart':
            b.edit_message_text("🚀 **بدء السحب الذكي المتقدم...**", chat_id, message_id)
            working_proxies = smart_pull_proxies(chat_id, user_id)
            
            if working_proxies:
                # تجميع البروكسيات حسب النوع
                http_proxies = [p for p in working_proxies if p['type'] == 'HTTP']
                https_proxies = [p for p in working_proxies if p['type'] == 'HTTPS']
                socks4_proxies = [p for p in working_proxies if p['type'] == 'SOCKS4']
                socks5_proxies = [p for p in working_proxies if p['type'] == 'SOCKS5']
                
                # إنشاء الملف النهائي
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"working_proxies_{timestamp}.txt"
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write("# ⚡ ℙℛᎾXᎽ ℙℳᎾ 𖠛 - البروكسيات الشغالة\n")
                    f.write(f"# 📅 التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"# 👤 المستخدم: {call.from_user.first_name}\n")
                    f.write(f"# 📊 الإجمالي: {len(working_proxies)} بروكسي\n\n")
                    
                    if http_proxies:
                        f.write(f"\n# 🌐 HTTP ({len(http_proxies)})\n")
                        for proxy in http_proxies:
                            f.write(f"{proxy['proxy']}\n")
                    
                    if https_proxies:
                        f.write(f"\n# 🔒 HTTPS ({len(https_proxies)})\n")
                        for proxy in https_proxies:
                            f.write(f"{proxy['proxy']}\n")
                    
                    if socks4_proxies:
                        f.write(f"\n# 🧦 SOCKS4 ({len(socks4_proxies)})\n")
                        for proxy in socks4_proxies:
                            f.write(f"{proxy['proxy']}\n")
                    
                    if socks5_proxies:
                        f.write(f"\n# 🧦 SOCKS5 ({len(socks5_proxies)})\n")
                        for proxy in socks5_proxies:
                            f.write(f"{proxy['proxy']}\n")
                
                # إرسال الملف مع الإحصائيات
                stats_text = f"""
    ✅ **تم الانتهاء من السحب والفحص بنجاح!**

    📊 **الإحصائيات النهائية:**
    • 🌐 HTTP: `{len(http_proxies)}`
    • 🔒 HTTPS: `{len(https_proxies)}`
    • 🧦 SOCKS4: `{len(socks4_proxies)}`
    • 🧦 SOCKS5: `{len(socks5_proxies)}`
    • 📁 الإجمالي: `{len(working_proxies)}`

    ⏰ **الوقت المستغرق:** {datetime.now().strftime('%H:%M:%S')}
    👤 **بواسطة:** {call.from_user.first_name}

    📥 **الملف المرفق يحتوي على جميع البروكسيات الشغالة**
                """
                
                with open(filename, 'rb') as file:
                    b.send_document(chat_id, file, caption=stats_text, parse_mode='Markdown')
                
                os.remove(filename)
                
                # إضافة نقاط للمستخدم
                if user_id != ADMIN_ID:
                    points_earned = min(len(working_proxies) // 5, 20)
                    if points_earned > 0:
                        db.update_user_points(user_id, points_earned)
                        b.send_message(chat_id, f"🎯 **لقد كسبت {points_earned} نقطة!**", parse_mode='Markdown')
            else:
                b.edit_message_text("❌ **لم يتم العثور على أي بروكسيات شغالة**", chat_id, message_id)
        
        elif call.data.startswith('get_'):
            proxy_type = call.data.replace('get_', '').upper()
            if proxy_type == 'ALL_PROXIES':
                proxies = db.get_proxies_by_type('HTTP') + db.get_proxies_by_type('HTTPS') + \
                         db.get_proxies_by_type('SOCKS4') + db.get_proxies_by_type('SOCKS5')
                filename = "all_proxies.txt"
                caption = "🌐 جميع البروكسيات الشغالة"
            else:
                proxies = db.get_proxies_by_type(proxy_type)
                type_names = {'HTTP': '🌐 HTTP', 'HTTPS': '🔒 HTTPS', 'SOCKS4': '🧦 SOCKS4', 'SOCKS5': '🧦 SOCKS5'}
                filename = f"{proxy_type.lower()}_proxies.txt"
                caption = f"{type_names.get(proxy_type, proxy_type)} البروكسيات الشغالة"
            
            if proxies:
                with open(filename, 'w') as f:
                    f.write('\n'.join(proxies))
                
                with open(filename, 'rb') as file:
                    b.send_document(chat_id, file, caption=f"📁 {caption} - {len(proxies)} بروكسي")
                
                os.remove(filename)
            else:
                b.answer_callback_query(call.id, f"❌ لا توجد بروكسيات شغالة من نوع {proxy_type}")
        
        elif call.data == 'bot_stats':
            if user_id != ADMIN_ID:
                b.answer_callback_query(call.id, "⛔ ليس لديك صلاحية الوصول!")
                return
            
            total_users = len(db.get_all_users())
            working_proxies_count = db.get_working_proxies_count()
            uptime = ti.time() - config.session_stats['start_time']
            
            stats_text = f"""
    📊 **إحصائيات البوت المتقدمة**

    👥 **المستخدمين:** `{total_users}`
    📁 **البروكسيات الشغالة:** `{working_proxies_count}`
    ⏰ **مدة التشغيل:** `{timedelta(seconds=int(uptime))}`
    🔍 **إجمالي المسحوب:** `{config.session_stats['total_proxies_found']}`
    ✅ **إجمالي الشغالة:** `{config.session_stats['working_proxies_found']}`

    ⚙️ **الإعدادات:**
    • البوت: `{'✅ نشط' if config.bot_enabled else '⛔ متوقف'}`
    • الصيانة: `{'🔧 مفعل' if config.maintenance_mode else '⚡ غير مفعل'}`
    • الفحص المكرر: `{'✅ مفعل' if config.duplicate_check else '❌ معطل'}`

    🗓️ **آخر تحديث:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            b.edit_message_text(stats_text, chat_id, message_id, parse_mode='Markdown')
        
        elif call.data == 'manage_users':
            if user_id != ADMIN_ID:
                b.answer_callback_query(call.id, "⛔ ليس لديك صلاحية الوصول!")
                return
            
            users = db.get_all_users()
            premium_users = [u for u in users if u[9]]  # is_premium
            banned_users = [u for u in users if u[8]]  # is_banned
            
            users_text = f"""
    👥 **إدارة المستخدمين**

    📊 **الإحصائيات:**
    • 👥 إجمالي المستخدمين: `{len(users)}`
    • 👑 مستخدمين مميزين: `{len(premium_users)}`
    • ⛔ محظورين: `{len(banned_users)}`

    📋 **آخر 5 مستخدمين:**
    """
            
            for user in users[-5:]:
                users_text += f"\n• {user[2] or 'بدون اسم'} (ID: `{user[0]}`) - {user[5]}"
            
            users_text += "\n\n**استخدم /broadcast لإرسال رسالة جماعية**"
            
            b.edit_message_text(users_text, chat_id, message_id, parse_mode='Markdown')
        
        elif call.data == 'cleanup_system':
            if user_id != ADMIN_ID:
                b.answer_callback_query(call.id, "⛔ ليس لديك صلاحية الوصول!")
                return
            
            deleted_proxies = db.cleanup_old_proxies(7)
            b.edit_message_text(f"🧹 **تم تنظيف النظام!**\n\nتم حذف `{deleted_proxies}` بروكسي قديم", 
                              chat_id, message_id, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Callback error: {e}")
        b.answer_callback_query(call.id, "❌ حدث خطأ أثناء المعالجة")

# 🎯 معالجة الملفات
@b.message_handler(content_types=['document'])
def handle_document(message):
    user_id = message.from_user.id
    
    status, msg_text = can_user_use_bot(user_id)
    if not status:
        b.send_message(message.chat.id, f"⛔ {msg_text}")
        return
    
    try:
        file_info = b.get_file(message.document.file_id)
        downloaded_file = b.download_file(file_info.file_path)
        
        # حفظ الملف مؤقتاً
        temp_filename = f"temp_{user_id}_{int(ti.time())}.txt"
        with open(temp_filename, 'wb') as f:
            f.write(downloaded_file)
        
        # استخراج البروكسيات من الملف
        with open(temp_filename, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        proxies = extract_proxies_from_text(content)
        os.remove(temp_filename)
        
        if not proxies:
            b.send_message(message.chat.id, "❌ لم يتم العثور على أي بروكسيات في الملف")
            return
        
        # عرض خيارات الفحص
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        user = db.get_user(user_id)
        current_speed = user[13] if user and len(user) > 13 else 'normal'
        
        btn1 = types.InlineKeyboardButton(f'⚡ فحص ({current_speed})', callback_data=f'check_file_{len(proxies)}')
        btn2 = types.InlineKeyboardButton('⚙️ تغيير الإعدادات', callback_data='settings_menu')
        btn3 = types.InlineKeyboardButton('❌ إلغاء', callback_data='main_menu')
        
        markup.add(btn1, btn2, btn3)
        
        b.send_message(message.chat.id,
                      f"📁 **تم استخراج {len(proxies)} بروكسي من الملف**\n\n"
                      f"⚡ **سرعة الفحص الحالية:** `{current_speed.replace('_', ' ').title()}`\n\n"
                      f"**اختر الإجراء المناسب:** 👇",
                      reply_markup=markup,
                      parse_mode='Markdown')
    
    except Exception as e:
        b.send_message(message.chat.id, f"❌ خطأ في معالجة الملف: {str(e)}")

# 🎯 تشغيل البوت
def run_bot():
    try:
        if RENDER_URL:
            # على Render، استخدم Webhook
            b.remove_webhook()
            ti.sleep(1)
            webhook_url = f"{RENDER_URL}/webhook"
            b.set_webhook(url=webhook_url)
            logger.info(f"Webhook set to: {webhook_url}")
            
            # تشغيل Flask
            app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
        else:
            # محلياً، استخدم Polling
            b.remove_webhook()
            ti.sleep(1)
            logger.info("Starting bot in polling mode...")
            b.polling(none_stop=True, interval=1, timeout=60)
    except Exception as e:
        logger.error(f"Bot startup error: {e}")
        ti.sleep(10)
        run_bot()

if __name__ == "__main__":
    logger.info("🚀 Starting Advanced Proxy Bot...")
    logger.info(f"👑 Bot Owner: {BOT_OWNER}")
    logger.info(f"📞 Support: {SUPPORT_USER}")
    
    # تهيئة الإحصائيات
    config.session_stats['total_users'] = len(db.get_all_users())
    
    run_bot()
