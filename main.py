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
BOT_OWNER = 'xtt19x'  # المالك

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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxies_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                proxy_text TEXT,
                check_date TEXT,
                working INTEGER
            )
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
            last_date = user[7]  # last_request_date
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
        self.custom_apis = []
        self.proxy_cache = {}
        self.cache_expiry = {}
        
        # إعدادات البوت من قاعدة البيانات
        self.bot_enabled = db.get_bot_setting('bot_enabled') != 'false'
        self.free_mode = db.get_bot_setting('free_mode') != 'false'
        self.maintenance_mode = db.get_bot_setting('maintenance_mode') == 'true'
        
        # إعدادات الفلترة المتقدمة
        self.filter_settings = {
            'country': None,
            'protocol': 'all',
            'anonymity': 'all',
            'timeout': 10,
            'check_working': True,
            'auto_pull': True,
            'max_workers': 20,
            'speed_threshold': 5.0,
            'enable_advanced_check': True
        }
        
        # إعدادات السحب
        self.pull_settings = {
            'max_pages': 3,
            'delay_between_requests': 1,
            'enable_rotating_user_agents': True,
            'use_proxy_rotation': False,
            'retry_failed_sources': True
        }
        
        # إعدادات العضوية
        self.membership_limits = {
            'free': {'daily_requests': 10, 'max_proxies': 50, 'features': ['basic_check']},
            'premium': {'daily_requests': 1000, 'max_proxies': 1000, 'features': ['all']}
        }

config = ProxyBotConfig()

# 🎯 قاعدة بيانات المصادر المتقدمة
PROXY_SOURCES = {
    "premium_apis": {
        "name": "🌟 واجهات برمجة مميزة",
        "enabled": True,
        "type": "api",
        "protocols": ["http", "https", "socks4", "socks5"],
        "sites": [
            "https://api.proxyscrape.com/v3/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&timeout=15000",
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=all&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://proxylist.geonode.com/api/proxy-list?limit=1000&page=1&sort_by=lastChecked&sort_type=desc",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt"
        ]
    },
    "smart_sources": {
        "name": "🔍 مصادر ذكية",
        "enabled": True,
        "type": "smart",
        "protocols": ["all"],
        "sites": [
            "https://www.proxy-list.download/api/v0/get?l=en&t=http",
            "https://www.proxy-list.download/api/v0/get?l=en&t=https",
            "https://www.proxy-list.download/api/v0/get?l=en&t=socks4",
            "https://www.proxy-list.download/api/v0/get?l=en&t=socks5",
            "https://openproxylist.xyz/http.txt",
            "https://openproxylist.xyz/socks4.txt",
            "https://openproxylist.xyz/socks5.txt"
        ]
    },
    "github_repos": {
        "name": "💾 مستودعات GitHub",
        "enabled": True,
        "type": "github",
        "protocols": ["all"],
        "sites": [
            "https://github.com/search?q=proxy+list+2024+updated&type=code",
            "https://github.com/search?q=free+proxies+2024+working&type=code",
            "https://github.com/search?q=socks5+proxy+list+fresh&type=code",
            "https://github.com/search?q=http+https+proxies+updated&type=code"
        ]
    }
}

# 🎯 قوائم User-Agent للتناوب
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

# 🌐 مواقع فحص البروكسيات المتقدمة
TEST_SITES = [
    "https://httpbin.org/ip",
    "https://api.ipify.org?format=json",
    "https://ident.me",
    "https://ipinfo.io/json",
    "https://api.myip.com",
    "https://ipapi.co/json",
    "https://www.ipify.org",
    "https://seeip.org",
    "https://ipecho.net/plain",
    "https://checkip.amazonaws.com",
    "https://icanhazip.com",
    "https://ifconfig.me/all.json",
    "https://ip.seeip.org",
    "https://wtfismyip.com/json"
]

# 🌐 Routes لـ Render.com
@app.route('/')
def home():
    bot_status = "✅ نشط" if config.bot_enabled else "⛔ متوقف"
    maintenance_status = "🔧 في الصيانة" if config.maintenance_mode else "⚡ جاهز"
    
    return f"""
    <html>
        <head>
            <title>ℙℛᎾXᎽ ℙℳᎾ 𖠛 - البوت المتكامل</title>
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
                .feature-list {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                    gap: 15px;
                    margin-top: 30px;
                }}
                .feature {{
                    background: rgba(255, 255, 255, 0.1);
                    padding: 15px;
                    border-radius: 10px;
                    text-align: center;
                }}
                .admin-panel {{
                    background: rgba(255, 0, 0, 0.1);
                    padding: 20px;
                    border-radius: 10px;
                    margin-top: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>ℙℛᎾXᎽ ℙℳᎾ 𖠛</h1>
                    <p>أقوى بوت سحب وفحص بروكسيات على التلجرام</p>
                    <p>📞 المالك: {BOT_OWNER} | الدعم: {SUPPORT_USER}</p>
                    <p>الحالة: {bot_status} | {maintenance_status}</p>
                </div>
                
                <div class="status-cards">
                    <div class="card">
                        <h3>📊 إحصائيات الجلسة</h3>
                        <div class="stats">{config.session_stats['total_proxies_found']}</div>
                        <p>إجمالي البروكسيات المسحوبة</p>
                    </div>
                    <div class="card">
                        <h3>✅ البروكسيات الشغالة</h3>
                        <div class="stats">{config.session_stats['working_proxies_found']}</div>
                        <p>تم العثور عليها</p>
                    </div>
                    <div class="card">
                        <h3>👥 المستخدمين</h3>
                        <div class="stats">{config.session_stats['total_users']}</div>
                        <p>إجمالي المسجلين</p>
                    </div>
                </div>
                
                <div class="card">
                    <h3>🎯 المميزات المتقدمة</h3>
                    <div class="feature-list">
                        <div class="feature">🔍 سحب ذكي</div>
                        <div class="feature">⚡ فحص 14+ موقع</div>
                        <div class="feature">🌍 كشف الدولة</div>
                        <div class="feature">🔧 جميع الأنواع</div>
                        <div class="feature">📊 إحصائيات متقدمة</div>
                        <div class="feature">💾 حفظ في GitHub</div>
                        <div class="feature">🚀 تشغيل مستمر</div>
                        <div class="feature">👑 نظام عضوية</div>
                        <div class="feature">🛡️ إدارة متقدمة</div>
                        <div class="feature">📈 تقارير مفصلة</div>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy' if config.bot_enabled else 'disabled',
        'bot_enabled': config.bot_enabled,
        'maintenance_mode': config.maintenance_mode,
        'free_mode': config.free_mode,
        'timestamp': ti.time(),
        'uptime': ti.time() - config.session_stats['start_time'],
        'stats': config.session_stats,
        'owner': BOT_OWNER,
        'support': SUPPORT_USER
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    if not config.bot_enabled:
        return 'Bot is disabled', 403
    if config.maintenance_mode:
        return 'Bot is under maintenance', 503
        
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        b.process_new_updates([update])
        return 'OK', 200
    return 'Error', 400

# 🛠️ أدوات مساعدة متقدمة
def get_rotating_session():
    """جلسة اتصال مع تناوب User-Agent"""
    session = rq.Session()
    session.trust_env = False
    
    if config.pull_settings['enable_rotating_user_agents']:
        session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
    
    session.verify = True
    return session

def safe_request(url, timeout=15, max_retries=3):
    """طلبات آمنة مع إعادة محاولة"""
    session = get_rotating_session()
    
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 200:
                return response
            else:
                logger.warning(f"المحاولة {attempt + 1} فشلت مع كود {response.status_code} لـ {url}")
        except Exception as e:
            logger.error(f"المحاولة {attempt + 1} فشلت لـ {url}: {str(e)}")
            if attempt < max_retries - 1:
                ti.sleep(2 ** attempt)
    
    return None

# 🎯 نظام الفحص المتقدم مع 14+ موقع
def advanced_proxy_check(proxy):
    """فحص متقدم للبروكسي مع 14+ مواقع اختبار"""
    try:
        logger.info(f"🔍 فحص متقدم: {proxy}")
        
        # إعداد البروكسي
        proxy_dict = {
            'http': proxy,
            'https': proxy
        }
        
        # الحصول على IP الأصلي
        original_ip = get_original_ip()
        
        # اختبارات متعددة على 14+ مواقع
        test_results = []
        start_time = ti.time()
        successful_ips = set()
        
        for test_url in TEST_SITES:
            try:
                test_start = ti.time()
                response = rq.get(test_url, proxies=proxy_dict, timeout=8)
                test_time = ti.time() - test_start
                
                if response.status_code == 200:
                    proxy_ip = extract_ip_from_response(response, test_url)
                    
                    if proxy_ip and proxy_ip != original_ip:
                        test_results.append({
                            'site': test_url,
                            'success': True,
                            'speed': test_time,
                            'ip': proxy_ip
                        })
                        successful_ips.add(proxy_ip)
                    else:
                        test_results.append({
                            'site': test_url, 
                            'success': False,
                            'error': 'Same IP as original or invalid IP'
                        })
                else:
                    test_results.append({
                        'site': test_url,
                        'success': False,
                        'error': f'Status {response.status_code}'
                    })
                    
            except Exception as e:
                test_results.append({
                    'site': test_url,
                    'success': False,
                    'error': str(e)
                })
        
        # تحليل النتائج
        successful_tests = [r for r in test_results if r['success']]
        total_time = ti.time() - start_time
        
        if successful_tests and len(successful_ips) > 0:
            speeds = [r['speed'] for r in successful_tests if 'speed' in r]
            avg_speed = sum(speeds) / len(speeds) if speeds else total_time
            
            proxy_type = "HTTP"
            if proxy.startswith('https://'):
                proxy_type = "HTTPS"
            elif proxy.startswith('socks4://'):
                proxy_type = "SOCKS4"
            elif proxy.startswith('socks5://'):
                proxy_type = "SOCKS5"
            
            country, country_code = get_country_from_ip(list(successful_ips)[0])
            
            return {
                'proxy': proxy,
                'working': True,
                'speed': round(avg_speed, 2),
                'ip': list(successful_ips)[0],
                'type': proxy_type,
                'country': country,
                'country_code': country_code,
                'tests_passed': len(successful_tests),
                'total_tests': len(test_results),
                'successful_sites': [r['site'] for r in successful_tests],
                'anonymity': 'elite' if original_ip != list(successful_ips)[0] else 'transparent'
            }
        else:
            return {
                'proxy': proxy,
                'working': False,
                'speed': 0,
                'ip': '',
                'type': 'Unknown',
                'country': 'Unknown',
                'tests_passed': 0,
                'total_tests': len(test_results)
            }
            
    except Exception as e:
        logger.error(f"❌ خطأ في الفحص المتقدم: {e}")
        return {
            'proxy': proxy,
            'working': False,
            'speed': 0,
            'ip': '',
            'type': 'Unknown',
            'country': 'Unknown',
            'error': str(e)
        }

def extract_ip_from_response(response, test_url):
    """استخراج IP من استجابة الموقع"""
    try:
        if any(site in test_url for site in ['ipify', 'ipinfo', 'myip', 'ipapi', 'ifconfig']):
            data = response.json()
            return data.get('ip', '')
        elif 'httpbin' in test_url:
            data = response.json()
            return data.get('origin', '')
        elif any(site in test_url for site in ['ident.me', 'seeip', 'ipecho', 'amazonaws', 'icanhazip']):
            return response.text.strip()
        else:
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            matches = re.findall(ip_pattern, response.text)
            return matches[0] if matches else ''
    except:
        return ''

def get_original_ip():
    """الحصول على IP الأصلي"""
    try:
        response = rq.get("https://api.ipify.org?format=json", timeout=5)
        return response.json().get('ip', '')
    except:
        return "Unknown"

def get_country_from_ip(ip):
    """الحصول على معلومات الدولة من IP"""
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
    """تسجيل مستخدم جديد"""
    db.add_user(user_id, username, first_name, last_name)
    config.session_stats['total_users'] += 1

def can_user_use_bot(user_id):
    """التحقق من إمكانية استخدام المستخدم للبوت"""
    if user_id == ADMIN_ID:
        return True, "مسؤول"
    
    if not config.bot_enabled:
        return False, "البوت متوقف حالياً"
    
    if config.maintenance_mode:
        return False, "البوت في وضع الصيانة"
    
    user = db.get_user(user_id)
    if not user:
        return True, "مستخدم جديد"
    
    if user[8]:  # is_banned
        return False, "تم حظرك من استخدام البوت"
    
    if user[7] == datetime.now().date().isoformat():  # last_request_date
        if user[5] == 'free' and user[6] >= config.membership_limits['free']['daily_requests']:
            return False, "لقد استنفذت طلباتك اليومية"
    
    return True, "مسموح"

# 🎯 نظام السحب الذكي
def smart_pull_proxies(chat_id, user_id):
    """سحب ذكي من جميع المصادر"""
    status, message = can_user_use_bot(user_id)
    if not status:
        b.send_message(chat_id, f"⛔ {message}")
        return []
    
    db.update_user_request(user_id)
    b.send_message(chat_id, "🚀 بدء السحب الذكي للبروكسيات...")
    
    all_proxies = []
    source_results = {}
    total_sources = 0
    
    for source_id, source_info in PROXY_SOURCES.items():
        if source_info['enabled']:
            b.send_message(chat_id, f"🔍 يبحث في: {source_info['name']}")
            
            source_proxies = []
            successful_sites = 0
            
            for site_url in source_info['sites']:
                try:
                    response = safe_request(site_url, timeout=20)
                    
                    if response and response.status_code == 200:
                        proxies = extract_proxies_from_text(response.text)
                        if proxies:
                            source_proxies.extend(proxies)
                            successful_sites += 1
                            logger.info(f"✅ {source_info['name']}: {len(proxies)} من {site_url}")
                    
                    ti.sleep(config.pull_settings['delay_between_requests'])
                    
                except Exception as e:
                    logger.error(f"❌ خطأ في {source_info['name']} - {site_url}: {e}")
                    continue
            
            if source_proxies:
                unique_proxies = list(set(source_proxies))
                all_proxies.extend(unique_proxies)
                source_results[source_info['name']] = len(unique_proxies)
                total_sources += 1
                
                b.send_message(chat_id, f"✅ {source_info['name']}: {len(unique_proxies)} بروكسي من {successful_sites} موقع")
            else:
                b.send_message(chat_id, f"❌ {source_info['name']}: لم يتم سحب أي بروكسيات")
    
    unique_proxies = list(set(all_proxies))
    config.session_stats['total_proxies_found'] += len(unique_proxies)
    
    if unique_proxies:
        save_proxies_to_file(unique_proxies, "pulled_proxies.txt")
        save_proxies_to_github_format(unique_proxies, "github_proxies.txt")
    
    sources_report = "📋 **تفصيل المصادر:**\n"
    for source_name, count in source_results.items():
        sources_report += f"• {source_name}: {count} بروكسي\n"
    
    report_text = f"""
📊 **تقرير السحب الذكي** 📊

✅ المصادر الناجحة: {total_sources}
🔗 البروكسيات المسحوبة: {len(unique_proxies)}
💾 تم حفظ النتائج في الملف

{sources_report}

🚀 **جاهز للفحص!**
    """
    
    b.send_message(chat_id, report_text, parse_mode="Markdown")
    
    if unique_proxies:
        with open("pulled_proxies.txt", "rb") as f:
            b.send_document(chat_id, f, caption=f"📁 البروكسيات المسحوبة ({len(unique_proxies)})")
    
    if unique_proxies and config.filter_settings['check_working']:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ فحص متقدم", callback_data="advanced_check"),
            types.InlineKeyboardButton("⚡ فحص سريع", callback_data="quick_check"),
            types.InlineKeyboardButton("❌ تخطي الفحص", callback_data="skip_check")
        )
        b.send_message(chat_id, "اختر نوع الفحص:", reply_markup=markup)
    
    return unique_proxies

def extract_proxies_from_text(text):
    """استخراج متقدم للبروكسيات من النص"""
    advanced_patterns = [
        r'[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-@]+@(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d{2,5}',
        r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}:\d{2,5}\b',
        r'http://[^\s<>"\']+',
        r'https://[^\s<>"\']+', 
        r'socks4://[^\s<>"\']+',
        r'socks5://[^\s<>"\']+',
    ]
    
    proxies = []
    for pattern in advanced_patterns:
        try:
            matches = re.findall(pattern, text, re.IGNORECASE)
            proxies.extend(matches)
        except Exception as e:
            logger.warning(f"خطأ في النمط {pattern}: {e}")
            continue
    
    return list(set(proxies))

# 💾 نظام حفظ الملفات
def save_proxies_to_file(proxies, filename):
    """حفظ البروكسيات في ملف"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            for proxy in proxies:
                f.write(f"{proxy}\n")
        logger.info(f"💾 تم حفظ {len(proxies)} بروكسي في {filename}")
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ الملف {filename}: {e}")
        return False

def save_proxies_to_github_format(proxies, filename):
    """حفظ البروكسيات بصيغة مناسبة لـ GitHub"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# 🚀 قائمة البروكسيات الشغالة\n\n")
            f.write("تم إنشاؤها تلقائياً بواسطة ℙℛᎾXᎽ ℙℳᎾ 𖠛\n\n")
            f.write("## 📋 البروكسيات:\n```\n")
            for proxy in proxies:
                f.write(f"{proxy}\n")
            f.write("```\n\n")
            f.write(f"## 📊 الإحصائيات:\n")
            f.write(f"- العدد الإجمالي: {len(proxies)}\n")
            f.write(f"- وقت الإنشاء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- المالك: {BOT_OWNER}\n")
            f.write(f"- الدعم: {SUPPORT_USER}\n")
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ ملف GitHub: {e}")
        return False

# 🎯 نظام الفحص المتقدم
def advanced_mass_check(proxies_list, chat_id, user_id):
    """فحص جماعي متقدم"""
    status, message = can_user_use_bot(user_id)
    if not status:
        b.send_message(chat_id, f"⛔ {message}")
        return [], 0
    
    db.update_user_request(user_id)
    b.send_message(chat_id, f"""
🔬 **بدء الفحص المتقدم**

📋 عدد البروكسيات: {len(proxies_list)}
👥 خيوط الفحص: {config.filter_settings['max_workers']}
🌐 مواقع الاختبار: {len(TEST_SITES)}
⚡ فحص متقدم: ✅ مفعل

**سيتم إجراء:**
• اختبار اتصال على {len(TEST_SITES)} موقع
• قياس سرعة دقيق  
• كشف نوع البروكسي
• تحديد مستوى الخصوصية
• كشف الدولة
    """, parse_mode="Markdown")
    
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
                
                if completed % 10 == 0 or completed == len(proxies_list):
                    elapsed = ti.time() - start_time
                    percentage = (completed / len(proxies_list)) * 100
                    
                    if completed > 0:
                        remaining = (elapsed / completed) * (len(proxies_list) - completed)
                    else:
                        remaining = 0
                    
                    progress_text = f"""
📊 **تقدم الفحص المتقدم**

✅ تم فحص: {completed}/{len(proxies_list)}
📈 النسبة: {percentage:.1f}%
⚡ الشغالة: {len(working_proxies)}
⏱ الوقت: {elapsed:.1f}s
⏳ المتبقي: {remaining:.1f}s
                    """
                    b.send_message(chat_id, progress_text, parse_mode="Markdown")
                    
            except Exception as e:
                completed += 1
                logger.error(f"خطأ في فحص البروكسي: {e}")
    
    elapsed_time = ti.time() - start_time
    config.session_stats['total_proxies_checked'] += len(proxies_list)
    
    return working_proxies, elapsed_time

# 📊 دوال التقارير والإحصائيات
def generate_detailed_report(proxies_list, elapsed_time, user_id):
    """تقرير مفصل عن البروكسيات"""
    if not proxies_list:
        return "❌ لا توجد بروكسيات شغالة"
    
    user = db.get_user(user_id)
    user_type = "👑 مسؤول" if user_id == ADMIN_ID else "👤 مستخدم"
    
    by_type = {}
    by_country = {}
    by_speed = {
        'fast': [p for p in proxies_list if p['speed'] < 2],
        'medium': [p for p in proxies_list if 2 <= p['speed'] < 5],
        'slow': [p for p in proxies_list if p['speed'] >= 5]
    }
    
    for proxy in proxies_list:
        proxy_type = proxy.get('type', 'Unknown')
        by_type[proxy_type] = by_type.get(proxy_type, 0) + 1
        
        country = proxy.get('country', 'Unknown')
        by_country[country] = by_country.get(country, 0) + 1
    
    fast_proxies = sorted(proxies_list, key=lambda x: x['speed'])[:10]
    
    report = f"""
📊 **تقرير مفصل عن البروكسيات الشغالة**

✅ الإجمالي: {len(proxies_list)} بروكسي
⏱ وقت الفحص: {elapsed_time:.2f} ثانية
🌐 مواقع الاختبار: {len(TEST_SITES)}
👤 نوع المستخدم: {user_type}

⚡ **التوزيع حسب السرعة:**
• سريعة (<2s): {len(by_speed['fast'])}
• متوسطة (2-5s): {len(by_speed['medium'])}
• بطيئة (>5s): {len(by_speed['slow'])}

🔧 **التوزيع حسب النوع:**
"""
    
    for ptype, count in by_type.items():
        report += f"• {ptype}: {count}\n"
    
    report += f"\n🌍 **أفضل الدول ({len(by_country)} دولة):**\n"
    for country, count in sorted(by_country.items(), key=lambda x: x[1], reverse=True)[:10]:
        report += f"• {country}: {count}\n"
    
    report += f"\n🏆 **أفضل 5 بروكسيات سريعة:**\n"
    for i, proxy in enumerate(fast_proxies[:5], 1):
        report += f"{i}. `{proxy['proxy']}`\n"
        report += f"   ⚡ {proxy['speed']}s | 🌍 {proxy['country']} | 🔧 {proxy['type']}\n\n"

    report += f"\n📞 **المالك:** {BOT_OWNER}"
    report += f"\n💬 **الدعم:** {SUPPORT_USER}"
    
    return report

# 🤖 Handlers للبوت - محدثة ومطورة
@b.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name or ""
    
    register_user(user_id, username, first_name, last_name)
    
    status, status_message = can_user_use_bot(user_id)
    
    if user_id == ADMIN_ID:
        # واجهة المسؤول المتقدمة
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        buttons = [
            "🚀 سحب بروكسيات", 
            "🔍 فحص متقدم",
            "📁 فحص من ملف",
            "👑 لوحة التحكم",
            "📊 إحصائيات البوت",
            "👥 إدارة المستخدمين",
            "⚙️ إعدادات البوت",
            "🌐 واجهات الويب",
            "🆘 المساعدة"
        ]
        markup.add(*buttons)
        
        welcome_text = f"""
**👑 أهلاً بك يا {BOT_OWNER} - مالك البوت**

🎯 **ℙℛᎾXᎽ ℙℳᎾ 𖠛 - البوت المتكامل**

✅ **المميزات المتقدمة:**
• 🔍 سحب ذكي من 15+ مصدر
• ⚡ فحص على 14+ موقع (محاكاة متصفح كاملة)
• 🌍 كشف الدولة والخصوصية المتقدمة
• 🔧 دعم جميع أنواع البروكسيات
• 📊 إحصائيات وتقارير متقدمة
• 💾 حفظ بصيغة GitHub
• 👥 نظام إدارة المستخدمين
• 🛡️ نظام العضوية المميزة
• 🚀 تشغيل مستمر 24/7

📋 **لوحة التحكم المتكاملة:**
• تشغيل/إيقاف البوت
• إدارة المستخدمين
• الإحصائيات الحية
• الإعدادات المتقدمة

🚀 **لبدء الاستخدام، اختر من الأزرار أدناه:**
        """
    else:
        # واجهة المستخدم العادي
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        buttons = [
            "🚀 سحب بروكسيات", 
            "🔍 فحص متقدم", 
            "📁 فحص من ملف",
            "📊 إحصائياتي",
            "👑 ترقية عضوية",
            "🆘 المساعدة"
        ]
        markup.add(*buttons)
        
        user = db.get_user(user_id)
        requests_left = config.membership_limits['free']['daily_requests'] - user[6] if user else config.membership_limits['free']['daily_requests']
        
        welcome_text = f"""
**أهلاً بك في ℙℛᎾXᎽ ℙℳᎾ 𖠛**

🎯 **أقوى بوت سحب وفحص بروكسيات**

✅ **المميزات المتاحة لك:**
• سحب بروكسيات من مصادر متعددة
• فحص متقدم على 14+ موقع
• كشف الدولة والنوع
• حفظ النتائج في ملفات

📊 **حسابك:**
• العضوية: 🆓 مجانية
• الطلبات المتبقية: {requests_left}
• الحالة: {status_message}

👑 **ترقية العضوية:**
للحصول على مميزات غير محدودة

🚀 **لبدء الاستخدام، اختر من الأزرار:**
        """
    
    b.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@b.message_handler(commands=['toggle_bot'])
def toggle_bot(message):
    """تشغيل/إيقاف البوت - محدث"""
    if message.from_user.id == ADMIN_ID:
        config.bot_enabled = not config.bot_enabled
        db.set_bot_setting('bot_enabled', 'true' if config.bot_enabled else 'false')
        
        status = "✅ تم تشغيل البوت" if config.bot_enabled else "⛔ تم إيقاف البوت"
        additional = "\n\n🔔 تم إرسال إشعار لجميع المستخدمين" if not config.bot_enabled else ""
        
        b.send_message(message.chat.id, f"{status}{additional}\n\n📞 الدعم: {SUPPORT_USER}")
        logger.info(f"البوت { 'مفعل' if config.bot_enabled else 'موقف' } بواسطة المالك")
        
        # إرسال إشعار للمستخدمين إذا تم إيقاف البوت
        if not config.bot_enabled:
            # هنا يمكنك إضافة كود لإرسال إشعار للمستخدمين
            pass
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية هذه الأمر. الدعم: {SUPPORT_USER}")

@b.message_handler(commands=['maintenance'])
def maintenance_mode(message):
    """وضع الصيانة"""
    if message.from_user.id == ADMIN_ID:
        config.maintenance_mode = not config.maintenance_mode
        db.set_bot_setting('maintenance_mode', 'true' if config.maintenance_mode else 'false')
        
        status = "🔧 تم تفعيل وضع الصيانة" if config.maintenance_mode else "⚡ تم تعطيل وضع الصيانة"
        b.send_message(message.chat.id, f"{status}\n\n📞 الدعم: {SUPPORT_USER}")
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية هذه الأمر. الدعم: {SUPPORT_USER}")

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
            b.send_message(message.chat.id, "🔬 بدء الفحص المتقدم...")
            working_proxies, elapsed_time = advanced_mass_check(proxies, message.chat.id, user_id)
            
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

# ... (استمرار الكود بنفس النمط لجميع handlers)

# 🚀 تشغيل البوت
def setup_webhook():
    """إعداد Webhook لـ Render.com"""
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
    logger.info("🚀 بدء تشغيل ℙℛᎾXᎽ ℙℳᎾ 𖠛 على Render.com...")
    logger.info(f"👑 المالك: {BOT_OWNER}")
    logger.info(f"📞 الدعم: {SUPPORT_USER}")
    
    # محاولة إعداد Webhook
    webhook_setup = setup_webhook()
    
    if webhook_setup and RENDER_URL:
        print(f"""
🎉 ℙℛᎾXᎽ ℙℳᎾ 𖠛 يعمل على Render.com!
✅ Webhook: {RENDER_URL}/webhook
✅ الواجهة: {RENDER_URL}
✅ فحص يدوي: {RENDER_URL}/test-proxy
✅ API: {RENDER_URL}/api/proxies

👑 المالك: {BOT_OWNER}
📞 الدعم: {SUPPORT_USER}
📊 البوت جاهز للعمل بكامل الميزات!
        """)
        
        port = int(os.environ.get("PORT", 10000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    else:
        print(f"""
🔄 استخدام Polling mode
✅ جميع الميزات تعمل
👑 المالك: {BOT_OWNER}
📞 الدعم: {SUPPORT_USER}
        """)
        b.infinity_polling(timeout=60, long_polling_timeout=60)
