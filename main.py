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
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8216062426:AAGK7A9rbT5SJkalK_TGK9BsY7EerP-z438')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6521966233'))
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
SUPPORT_USER = '@xtt19x'
BOT_OWNER = '@xtt19x'

b = tb.TeleBot(BOT_TOKEN)

# 🎯 قاعدة بيانات المستخدمين
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
                is_premium INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # إعدادات افتراضية
        cursor.execute('''
            INSERT OR IGNORE INTO bot_settings (key, value) 
            VALUES ('bot_enabled', 'true')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO bot_settings (key, value) 
            VALUES ('maintenance_mode', 'false')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO bot_settings (key, value) 
            VALUES ('free_mode', 'true')
        ''')
        
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
        
        # إعدادات الفحص
        self.filter_settings = {
            'country': None,
            'protocol': 'all',
            'timeout': 10,
            'check_working': True,
            'max_workers': 15
        }

config = ProxyBotConfig()

# 🎯 قاعدة بيانات المصادر المتقدمة
PROXY_SOURCES = {
    "premium_apis": {
        "name": "🌟 واجهات برمجة",
        "enabled": True,
        "type": "api",
        "sites": [
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://www.proxy-list.download/api/v1/get?type=http",
            "https://www.proxy-list.download/api/v1/get?type=https"
        ]
    },
    "raw_sources": {
        "name": "📁 مصادر مباشرة",
        "enabled": True,
        "type": "text",
        "sites": [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
            "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt"
        ]
    }
}

# 🎯 قوائم User-Agent
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
]

# 🌐 مواقع فحص البروكسيات
TEST_SITES = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://ident.me",
    "https://ipinfo.io/json",
    "https://api.myip.com",
    "https://ipapi.co/json",
    "https://www.ipify.org",
    "https://seeip.org"
]

# 🌐 Routes لـ Render.com
@app.route('/')
def home():
    bot_status = "✅ نشط" if config.bot_enabled else "⛔ متوقف"
    maintenance_status = "🔧 في الصيانة" if config.maintenance_mode else "⚡ جاهز"
    
    return f"""
    <html>
        <head>
            <title>ℙℛᎾXᎽ ℙℳᎾ 𖠛</title>
            <style>
                body {{ 
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    margin: 0;
                    padding: 0;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 40px 20px;
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 50px;
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
                }}
                .stats {{
                    font-size: 2.5em;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .btn {{
                    display: inline-block;
                    background: #007bff;
                    color: white;
                    padding: 10px 20px;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 5px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>ℙℛᎾXᎽ ℙℳᎾ 𖠛</h1>
                    <p>أقوى بوت سحب وفحص بروكسيات</p>
                    <p>👑 المالك: {BOT_OWNER} | 📞 الدعم: {SUPPORT_USER}</p>
                    <p>الحالة: {bot_status} | {maintenance_status}</p>
                </div>
                
                <div class="status-cards">
                    <div class="card">
                        <h3>📊 البروكسيات المسحوبة</h3>
                        <div class="stats">{config.session_stats['total_proxies_found']}</div>
                    </div>
                    <div class="card">
                        <h3>✅ البروكسيات الشغالة</h3>
                        <div class="stats">{config.session_stats['working_proxies_found']}</div>
                    </div>
                    <div class="card">
                        <h3>👥 المستخدمين</h3>
                        <div class="stats">{config.session_stats['total_users']}</div>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 30px;">
                    <a href="/test-proxy" class="btn">🧪 فحص بروكسي</a>
                    <a href="/health" class="btn">📊 حالة البوت</a>
                    <a href="https://t.me/{BOT_OWNER}" class="btn">👑 تواصل مع المالك</a>
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'bot_enabled': config.bot_enabled,
        'maintenance_mode': config.maintenance_mode,
        'timestamp': ti.time(),
        'uptime': ti.time() - config.session_stats['start_time'],
        'stats': config.session_stats,
        'owner': BOT_OWNER,
        'support': SUPPORT_USER
    })

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
                <head><title>نتيجة الفحص</title></head>
                <body style="font-family: Arial; padding: 20px;">
                    <h2>🧪 نتيجة فحص البروكسي</h2>
                    <div style="background: {'#d4edda' if result['working'] else '#f8d7da'}; padding: 20px; border-radius: 10px;">
                        <h3>{'✅ البروكسي شغال' if result['working'] else '❌ البروكسي لا يعمل'}</h3>
                        <p><strong>البروكسي:</strong> {proxy}</p>
                        {f"<p><strong>IP الجديد:</strong> {result['ip']}</p>" if result['working'] else ""}
                        {f"<p><strong>السرعة:</strong> {result['speed']} ثانية</p>" if result['working'] else ""}
                        {f"<p><strong>النوع:</strong> {result['type']}</p>" if result['working'] else ""}
                        {f"<p><strong>الدولة:</strong> {result['country']}</p>" if result['working'] else ""}
                    </div>
                    <br>
                    <a href="/test-proxy" style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">فحص بروكسي آخر</a>
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
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; }
            input, button { padding: 10px; margin: 5px; width: 100%; box-sizing: border-box; }
            button { background: #007bff; color: white; border: none; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧪 فحص البروكسيات يدوياً</h1>
            <form method="POST">
                <input type="text" name="proxy" placeholder="أدخل البروكسي (مثال: 194.35.125.100:8080)" required>
                <button type="submit">فحص البروكسي</button>
            </form>
        </div>
    </body>
    </html>
    '''

# 🛠️ أدوات مساعدة
def get_rotating_session():
    session = rq.Session()
    session.trust_env = False
    session.headers.update({
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': '*/*'
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

# 🎯 نظام الفحص المتقدم
def advanced_proxy_check(proxy):
    try:
        proxy_dict = {'http': proxy, 'https': proxy}
        original_ip = get_original_ip()
        
        test_results = []
        start_time = ti.time()
        
        for test_url in TEST_SITES[:4]:  # اختبار 4 مواقع فقط للسرعة
            try:
                test_start = ti.time()
                response = rq.get(test_url, proxies=proxy_dict, timeout=8)
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
            
            proxy_type = "HTTP"
            if proxy.startswith('https://'): proxy_type = "HTTPS"
            elif proxy.startswith('socks4://'): proxy_type = "SOCKS4"
            elif proxy.startswith('socks5://'): proxy_type = "SOCKS5"
            
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

# 🎯 نظام إدارة المستخدمين
def register_user(user_id, username, first_name, last_name):
    db.add_user(user_id, username, first_name, last_name)
    config.session_stats['total_users'] += 1

def can_user_use_bot(user_id):6521966233
    if user_id == ADMIN_ID:
        return True, "مسؤول"
    
    if not config.bot_enabled:
        return False, "البوت متوقف حالياً"
    
    if config.maintenance_mode:
        return False, "البوت في وضع الصيانة"
    
    user = db.get_user(user_id)
    if user and user[8]:  # is_banned
        return False, "تم حظرك من استخدام البوت"
    
    return True, "مسموح"

# 🎯 نظام السحب الذكي
def smart_pull_proxies(chat_id, user_id):
    status, message = can_user_use_bot(user_id)
    if not status:
        b.send_message(chat_id, f"⛔ {message}")
        return []
    
    db.update_user_request(user_id)
    b.send_message(chat_id, "🚀 بدء السحب الذكي للبروكسيات...")
    
    all_proxies = []
    
    for source_id, source_info in PROXY_SOURCES.items():
        if source_info['enabled']:
            b.send_message(chat_id, f"🔍 يبحث في: {source_info['name']}")
            
            for site_url in source_info['sites']:
                try:
                    response = safe_request(site_url, timeout=20)
                    if response:
                        proxies = extract_proxies_from_text(response.text)
                        if proxies:
                            all_proxies.extend(proxies)
                            b.send_message(chat_id, f"✅ تم سحب {len(proxies)} بروكسي")
                    ti.sleep(1)
                except Exception as e:
                    continue
    
    unique_proxies = list(set(all_proxies))
    config.session_stats['total_proxies_found'] += len(unique_proxies)
    
    if unique_proxies:
        save_proxies_to_file(unique_proxies, "pulled_proxies.txt")
        b.send_message(chat_id, f"📊 تم سحب {len(unique_proxies)} بروكسي بنجاح!")
        
        with open("pulled_proxies.txt", "rb") as f:
            b.send_document(chat_id, f, caption=f"📁 البروكسيات المسحوبة ({len(unique_proxies)})")
        
        # عرض أزرار الفحص
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ فحص متقدم", callback_data="advanced_check"),
            types.InlineKeyboardButton("🔍 فحص سريع", callback_data="quick_check")
        )
        b.send_message(chat_id, "اختر نوع الفحص:", reply_markup=markup)
    
    return unique_proxies

def extract_proxies_from_text(text):
    patterns = [
        r'[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-@]+@(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d{2,5}',
        r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d{2,5}\b',
        r'http://[^\s<>"\']+',
        r'https://[^\s<>"\']+', 
        r'socks4://[^\s<>"\']+',
        r'socks5://[^\s<>"\']+',
    ]
    
    proxies = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        proxies.extend(matches)
    
    return list(set(proxies))

def save_proxies_to_file(proxies, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            for proxy in proxies:
                f.write(f"{proxy}\n")
        return True
    except:
        return False

# 🎯 نظام الفحص المتقدم
def advanced_mass_check(proxies_list, chat_id, user_id):
    status, message = can_user_use_bot(user_id)
    if not status:
        b.send_message(chat_id, f"⛔ {message}")
        return [], 0
    
    db.update_user_request(user_id)
    b.send_message(chat_id, f"🔬 بدء الفحص المتقدم لـ {len(proxies_list)} بروكسي...")
    
    start_time = ti.time()
    working_proxies = []
    
    with ThreadPoolExecutor(max_workers=config.filter_settings['max_workers']) as executor:
        future_to_proxy = {executor.submit(advanced_proxy_check, proxy): proxy for proxy in proxies_list}
        
        completed = 0
        for future in as_completed(future_to_proxy):
            try:
                result = future.result()
                if result['working']:
                    working_proxies.append(result)
                    config.session_stats['working_proxies_found'] += 1
                
                completed += 1
                
                if completed % 10 == 0:
                    elapsed = ti.time() - start_time
                    progress_text = f"📊 تم فحص {completed}/{len(proxies_list)} | ⚡ الشغالة: {len(working_proxies)}"
                    b.send_message(chat_id, progress_text)
                    
            except Exception as e:
                completed += 1
    
    elapsed_time = ti.time() - start_time
    config.session_stats['total_proxies_checked'] += len(proxies_list)
    
    return working_proxies, elapsed_time

# 📊 دوال التقارير
def generate_detailed_report(proxies_list, elapsed_time, user_id):
    if not proxies_list:
        return "❌ لا توجد بروكسيات شغالة"
    
    user_type = "👑 مسؤول" if user_id == ADMIN_ID else "👤 مستخدم"
    
    by_type = {}
    by_country = {}
    
    for proxy in proxies_list:
        proxy_type = proxy.get('type', 'Unknown')
        by_type[proxy_type] = by_type.get(proxy_type, 0) + 1
        country = proxy.get('country', 'Unknown')
        by_country[country] = by_country.get(country, 0) + 1
    
    fast_proxies = sorted(proxies_list, key=lambda x: x['speed'])[:5]
    
    report = f"""
📊 **تقرير البروكسيات الشغالة**

✅ الإجمالي: {len(proxies_list)} بروكسي
⏱ وقت الفحص: {elapsed_time:.2f} ثانية
👤 نوع المستخدم: {user_type}

🔧 **التوزيع حسب النوع:**
"""
    
    for ptype, count in by_type.items():
        report += f"• {ptype}: {count}\n"
    
    report += f"\n🌍 **الدول:**\n"
    for country, count in sorted(by_country.items(), key=lambda x: x[1], reverse=True)[:5]:
        report += f"• {country}: {count}\n"
    
    report += f"\n🏆 **أفضل البروكسيات:**\n"
    for i, proxy in enumerate(fast_proxies, 1):
        report += f"{i}. `{proxy['proxy']}`\n"
        report += f"   ⚡ {proxy['speed']}s | 🌍 {proxy['country']}\n\n"

    report += f"\n👑 **المالك:** {BOT_OWNER}"
    
    return report

# 🤖 Handlers للبوت - محدثة تماماً
@b.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "بدون يوزر"
    first_name = message.from_user.first_name or "بدون اسم"
    last_name = message.from_user.last_name or ""
    
    register_user(user_id, username, first_name, last_name)
    
    if user_id == ADMIN_ID:
        # واجهة المسؤول المتكاملة
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        buttons = [
            "🚀 سحب بروكسيات", "🔍 فحص متقدم", "📁 فحص من ملف",
            "👑 لوحة التحكم", "📊 إحصائيات البوت", "👥 إدارة المستخدمين",
            "⚡ تشغيل البوت", "⛔ إيقاف البوت", "🔧 وضع الصيانة",
            "🌐 واجهات الويب", "🆘 المساعدة", "🔄 تحديث البوت"
        ]
        markup.add(*buttons)
        
        welcome_text = f"""
**👑 أهلاً بك يا {BOT_OWNER}**

🎯 **ℙℛᎾXᎽ ℙℳᎾ 𖠛 - البوت المتكامل**

✅ **الحالة:** {'🟢 نشط' if config.bot_enabled else '🔴 متوقف'}
🔧 **الصيانة:** {'⚙️ مفعل' if config.maintenance_mode else '✅ غير مفعل'}

🚀 **استخدم الأزرار للتحكم الكامل في البوت:**
• ⚡ تشغيل البوت - لتفعيل الخدمة
• ⛔ إيقاف البوت - لإيقاف الخدمة
• 🔧 وضع الصيانة - للصيانة
• 👑 لوحة التحكم - للإدارة المتقدمة

📞 **للتواصل:** {SUPPORT_USER}
        """
    else:
        # واجهة المستخدم العادي
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        buttons = [
            "🚀 سحب بروكسيات", "🔍 فحص متقدم", 
            "📁 فحص من ملف", "📊 إحصائياتي",
            "👑 ترقية عضوية", "🆘 المساعدة"
        ]
        markup.add(*buttons)
        
        user = db.get_user(user_id)
        requests_used = user[6] if user else 0
        requests_left = 10 - requests_used
        
        welcome_text = f"""
**أهلاً بك في ℙℛᎾXᎽ ℙℳᎾ 𖠛**

🎯 **أقوى بوت سحب وفحص بروكسيات**

📊 **حسابك:**
• العضوية: 🆓 مجانية
• الطلبات المستخدمة: {requests_used}
• الطلبات المتبقية: {requests_left}

🚀 **لبدء الاستخدام:**
1. اضغط على \"🚀 سحب بروكسيات\"
2. انتظر اكتمال السحب
3. اضغط على \"🔍 فحص متقدم\"

👑 **المالك:** {BOT_OWNER}
        """
    
    b.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@b.message_handler(commands=['toggle_bot'])
def toggle_bot(message):
    """تشغيل/إيقاف البوت - محدث"""
    if message.from_user.id == ADMIN_ID:
        config.bot_enabled = not config.bot_enabled
        db.set_bot_setting('bot_enabled', 'true' if config.bot_enabled else 'false')
        
        status = "✅ **تم تشغيل البوت**" if config.bot_enabled else "⛔ **تم إيقاف البوت**"
        b.send_message(message.chat.id, f"{status}\n\n📞 الدعم: {SUPPORT_USER}")
        
        # إرسال إشعار للمستخدمين إذا تم التشغيل
        if config.bot_enabled:
            b.send_message(message.chat.id, "🔔 تم إرسال إشعار تشغيل البوت للمستخدمين")
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية هذه الأمر")

@b.message_handler(func=lambda message: message.text == "⚡ تشغيل البوت")
def enable_bot_button(message):
    if message.from_user.id == ADMIN_ID:
        if not config.bot_enabled:
            config.bot_enabled = True
            db.set_bot_setting('bot_enabled', 'true')
            b.send_message(message.chat.id, "✅ **تم تشغيل البوت بنجاح**\n\nيمكن للمستخدمين الآن استخدام البوت")
        else:
            b.send_message(message.chat.id, "ℹ️ البوت مشغل بالفعل")
    else:
        b.send_message(message.chat.id, "⛔ هذه الخاصية للمسؤول فقط")

@b.message_handler(func=lambda message: message.text == "⛔ إيقاف البوت")
def disable_bot_button(message):
    if message.from_user.id == ADMIN_ID:
        if config.bot_enabled:
            config.bot_enabled = False
            db.set_bot_setting('bot_enabled', 'false')
            b.send_message(message.chat.id, "⛔ **تم إيقاف البوت بنجاح**\n\nتم منع جميع المستخدمين من استخدام البوت")
        else:
            b.send_message(message.chat.id, "ℹ️ البوت موقف بالفعل")
    else:
        b.send_message(message.chat.id, "⛔ هذه الخاصية للمسؤول فقط")

@b.message_handler(func=lambda message: message.text == "🔧 وضع الصيانة")
def maintenance_button(message):
    if message.from_user.id == ADMIN_ID:
        config.maintenance_mode = not config.maintenance_mode
        db.set_bot_setting('maintenance_mode', 'true' if config.maintenance_mode else 'false')
        
        status = "🔧 **تم تفعيل وضع الصيانة**" if config.maintenance_mode else "⚡ **تم تعطيل وضع الصيانة**"
        b.send_message(message.chat.id, f"{status}\n\n📞 الدعم: {SUPPORT_USER}")
    else:
        b.send_message(message.chat.id, "⛔ هذه الخاصية للمسؤول فقط")

@b.message_handler(func=lambda message: message.text == "👑 لوحة التحكم")
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:6521966233
        users = db.get_all_users()
        total_users = len(users)
        active_today = len([u for u in users if u[7] == datetime.now().date().isoformat()])
        
        admin_text = f"""
👑 **لوحة تحكم المسؤول**

📊 **إحصائيات البوت:**
• المستخدمين: {total_users}
• النشطين اليوم: {active_today}
• البروكسيات المسحوبة: {config.session_stats['total_proxies_found']}
• البروكسيات الشغالة: {config.session_stats['working_proxies_found']}

⚙️ **حالة البوت:**
• التشغيل: {'✅ نشط' if config.bot_enabled else '⛔ متوقف'}
• الصيانة: {'🔧 مفعل' if config.maintenance_mode else '✅ غير مفعل'}

🌐 **الواجهات:**
• الموقع: {RENDER_URL}
• فحص يدوي: {RENDER_URL}/test-proxy
• حالة البوت: {RENDER_URL}/health

📞 **الدعم:** {SUPPORT_USER}
        """
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 تحديث الإحصائيات", callback_data="refresh_stats"),
            types.InlineKeyboardButton("📋 قائمة المستخدمين", callback_data="users_list")
        )
        
        b.send_message(message.chat.id, admin_text, reply_markup=markup, parse_mode="Markdown")
    else:
        b.send_message(message.chat.id, "⛔ هذه الخاصية للمسؤول فقط")

@b.message_handler(func=lambda message: message.text == "🚀 سحب بروكسيات")
def start_smart_pull(message):
    smart_pull_proxies(message.chat.id, message.from_user.id)

@b.message_handler(func=lambda message: message.text == "🔍 فحص متقدم")
def start_advanced_check(message):
    user_id = message.from_user.id
    try:
        with open("pulled_proxies.txt", "r", encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip()]
        
        if proxies:
            # تحديد عدد البروكسيات للفحص
            proxies_to_check = proxies[:50]  # حد أقصى 50 للسرعة
            
            b.send_message(message.chat.id, f"🔬 بدء الفحص المتقدم لـ {len(proxies_to_check)} بروكسي...")
            working_proxies, elapsed_time = advanced_mass_check(proxies_to_check, message.chat.id, user_id)
            
            report = generate_detailed_report(working_proxies, elapsed_time, user_id)
            b.send_message(message.chat.id, report, parse_mode="Markdown")
            
            if working_proxies:
                with open("working_proxies.txt", "w", encoding="utf-8") as f:
                    for proxy_info in working_proxies:
                        f.write(f"{proxy_info['proxy']}\n")
                
                with open("working_proxies.txt", "rb") as f:
                    b.send_document(message.chat.id, f, caption=f"📁 البروكسيات الشغالة ({len(working_proxies)})")
        else:
            b.send_message(message.chat.id, "❌ لا توجد بروكسيات مسحوبة. قم بالسحب أولاً.")
    except FileNotFoundError:
        b.send_message(message.chat.id, "❌ لا توجد بروكسيات مسحوبة. قم بالسحب أولاً.")

@b.message_handler(func=lambda message: message.text == "📁 فحص من ملف")
def check_from_file(message):
    b.send_message(message.chat.id, "📁 أرسل ملف txt يحتوي على البروكسيات (بروكسي في كل سطر)")
    config.user_states[message.chat.id] = 'awaiting_file'

@b.message_handler(func=lambda message: message.text == "📊 إحصائيات البوت")
def bot_stats(message):
    if message.from_user.id == ADMIN_ID:6521966233
        uptime = ti.time() - config.session_stats['start_time']
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        stats_text = f"""
📊 **إحصائيات البوت المتقدمة**

🕒 وقت التشغيل: {int(hours)}h {int(minutes)}m
🔗 بروكسيات مسحوبة: {config.session_stats['total_proxies_found']}
✅ بروكسيات شغالة: {config.session_stats['working_proxies_found']}
🔍 بروكسيات مفحوصة: {config.session_stats['total_proxies_checked']}
👥 المستخدمين: {config.session_stats['total_users']}

🌐 **المصادر النشطة:**
"""
        
        for source_id, source_info in PROXY_SOURCES.items():
            if source_info['enabled']:
                stats_text += f"• {source_info['name']}: {len(source_info['sites'])} موقع\n"
        
        stats_text += f"""
⚡ **حالة البوت:** {'🟢 نشط' if config.bot_enabled else '🔴 متوقف'}
🔧 **الصيانة:** {'🟡 مفعل' if config.maintenance_mode else '🟢 غير مفعل'}

👑 **المالك:** {BOT_OWNER}
        """
        
        b.send_message(message.chat.id, stats_text, parse_mode="Markdown")
    else:
        user = db.get_user(message.from_user.id)
        requests_used = user[6] if user else 0
        requests_left = 10 - requests_used
        
        user_stats = f"""
📊 **إحصائيات حسابك**

• الطلبات المستخدمة: {requests_used}
• الطلبات المتبقية: {requests_left}
• العضوية: 🆓 مجانية

👑 **لترقية العضوية:** تواصل مع {BOT_OWNER}
        """
        b.send_message(message.chat.id, user_stats, parse_mode="Markdown")

@b.message_handler(func=lambda message: message.text == "🔄 تحديث البوت")
def refresh_bot(message):
    if message.from_user.id == ADMIN_ID:
        b.send_message(message.chat.id, "🔄 **جاري تحديث البوت...**")
        
        # إعادة تحميل الإعدادات من قاعدة البيانات
        config.bot_enabled = db.get_bot_setting('bot_enabled') == 'true'
        config.maintenance_mode = db.get_bot_setting('maintenance_mode') == 'true'
        
        b.send_message(message.chat.id, "✅ **تم تحديث البوت بنجاح**\n\nتم تحميل أحدث الإعدادات")
    else:
        b.send_message(message.chat.id, "⛔ هذه الخاصية للمسؤول فقط")

@b.message_handler(content_types=['document'])
def handle_document(message):
    if config.user_states.get(message.chat.id) == 'awaiting_file':
        try:
            file_info = b.get_file(message.document.file_id)
            downloaded_file = b.download_file(file_info.file_path)
            
            # قراءة البروكسيات من الملف
            proxies = []
            for line in downloaded_file.decode('utf-8').split('\n'):
                line = line.strip()
                if line:
                    proxies.append(line)
            
            b.send_message(message.chat.id, f"📥 تم تحميل {len(proxies)} بروكسي من الملف")
            config.user_states[message.chat.id] = None
            
            if proxies:
                # حفظ الملف المؤقت
                with open("user_proxies.txt", "w", encoding="utf-8") as f:
                    for proxy in proxies:
                        f.write(f"{proxy}\n")
                
                # عرض خيارات الفحص
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("✅ فحص الكل", callback_data="check_all"),
                    types.InlineKeyboardButton("🔍 فحص 20 بروكسي", callback_data="check_20")
                )
                b.send_message(message.chat.id, f"اختر خيار الفحص لـ {len(proxies)} بروكسي:", reply_markup=markup)
            
        except Exception as e:
            b.send_message(message.chat.id, f"❌ خطأ في تحميل الملف: {e}")
            config.user_states[message.chat.id] = None

@b.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    if call.data == "advanced_check":
        b.answer_callback_query(call.id, "بدء الفحص المتقدم")
        start_advanced_check(call.message)
    
    elif call.data == "quick_check":
        b.answer_callback_query(call.id, "بدء الفحص السريع")
        # يمكن إضافة فحص سريع هنا
    
    elif call.data == "refresh_stats":
        if user_id == ADMIN_ID:
            bot_stats(call.message)
            b.answer_callback_query(call.id, "تم تحديث الإحصائيات")
    
    elif call.data == "check_all":
        try:
            with open("user_proxies.txt", "r", encoding="utf-8") as f:
                proxies = [line.strip() for line in f if line.strip()]
            
            if proxies:
                working_proxies, elapsed_time = advanced_mass_check(proxies[:100], chat_id, user_id)  # حد 100 للسلامة
                report = generate_detailed_report(working_proxies, elapsed_time, user_id)
                b.send_message(chat_id, report, parse_mode="Markdown")
                
                if working_proxies:
                    with open("working_proxies.txt", "w", encoding="utf-8") as f:
                        for proxy_info in working_proxies:
                            f.write(f"{proxy_info['proxy']}\n")
                    
                    with open("working_proxies.txt", "rb") as f:
                        b.send_document(chat_id, f, caption=f"📁 النتائج ({len(working_proxies)})")
        except Exception as e:
            b.send_message(chat_id, f"❌ خطأ في الفحص: {e}")

# 🚀 تشغيل البوت
def setup_webhook():
    """إعداد Webhook محسن"""
    try:
        if RENDER_URL:
            webhook_url = f"{RENDER_URL}/webhook"
            b.remove_webhook()
            ti.sleep(1)
            b.set_webhook(url=webhook_url)
            logger.info(f"✅ تم تعيين Webhook: {webhook_url}")
            return True
    except Exception as e:
        logger.error(f"❌ خطأ في Webhook: {e}")
    return False

if __name__ == "__main__":
    logger.info("🚀 بدء تشغيل ℙℛᎾXᎽ ℙℳᎾ 𖠛...")
    logger.info(f"👑 المالك: {BOT_OWNER}")
    
    # التأكد من أن البوت مشغل افتراضياً
    if db.get_bot_setting('bot_enabled') is None:
        db.set_bot_setting('bot_enabled', 'true')
        config.bot_enabled = True
    
    # محاولة إعداد Webhook
    webhook_setup = setup_webhook()
    
    if webhook_setup and RENDER_URL:
        print(f"""
🎉 ℙℛᎾXᎽ ℙℳᎾ 𖠛 يعمل على Render.com!
✅ Webhook: {RENDER_URL}/webhook
✅ الواجهة: {RENDER_URL}
✅ فحص يدوي: {RENDER_URL}/test-proxy

👑 المالك: {BOT_OWNER}
📞 الدعم: {SUPPORT_USER}
📊 البوت جاهز للعمل!
        """)
        
        port = int(os.environ.get("PORT", 10000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    else:
        print(f"""
🔄 استخدام Polling mode
✅ جميع الميزات تعمل
👑 المالك: {BOT_OWNER}

💡 تعليمات التشغيل:
1. أرسل /start لرؤية الأزرار
2. استخدم "⚡ تشغيل البوت" لتفعيل الخدمة
3. استخدم "🚀 سحب بروكسيات" للبدء
        """)
        b.infinity_polling(timeout=60, long_polling_timeout=60)
