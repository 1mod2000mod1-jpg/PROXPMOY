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
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8071531346:AAG6gePsfFBTXinak1XaBUIUV6glVck1KUk')
ADMIN_ID = int(os.environ.get('ADMIN_ID', '6521966233'))
RENDER_URL = os.environ.get('https://naxmu-na-afd8.onrender.com', '')
SUPPORT_USER = '@xtt19x'  # يوزر الدعم

b = tb.TeleBot(BOT_TOKEN)

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

# 🎯 إعدادات متقدمة
class ProxyBotConfig:
    def __init__(self):
        self.user_states = {}
        self.working_proxies = []
        self.checked_proxies_count = 0
        self.session_stats = {
            'total_proxies_found': 0,
            'total_proxies_checked': 0,
            'working_proxies_found': 0,
            'start_time': ti.time()
        }
        self.custom_apis = []
        self.proxy_cache = {}
        self.cache_expiry = {}
        self.bot_enabled = True  # التحكم بتشغيل/إيقاف البوت
        
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

config = ProxyBotConfig()

# 🎯 قوائم User-Agent للتناوب
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
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
    "https://seeip.org",
    "https://ipecho.net/plain",
    "https://checkip.amazonaws.com"
]

# 🌐 Routes لـ Render.com
@app.route('/')
def home():
    if not config.bot_enabled:
        return "<h1>⛔ البوت متوقف حالياً</h1><p>يرجى التواصل مع المسؤول {}</p>".format(SUPPORT_USER)
    
    uptime = ti.time() - config.session_stats['start_time']
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return f"""
    <html>
        <head>
            <title>🚀 Proxy Master Bot - Render</title>
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
                    <h1>🚀 Proxy Master Bot</h1>
                    <p>أقوى أداة سحب وفحص بروكسيات على Render.com</p>
                    <p>📞 الدعم: {SUPPORT_USER}</p>
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
                        <h3>⏰ وقت التشغيل</h3>
                        <div class="stats">{int(hours)}h {int(minutes)}m</div>
                        <p>منذ بدء التشغيل</p>
                    </div>
                </div>
                
                <div class="card">
                    <h3>🎯 المميزات المتاحة</h3>
                    <div class="feature-list">
                        <div class="feature">🔍 سحب ذكي</div>
                        <div class="feature">⚡ فحص 10+ مواقع</div>
                        <div class="feature">🌍 كشف الدولة</div>
                        <div class="feature">🔧 جميع الأنواع</div>
                        <div class="feature">📊 إحصائيات متقدمة</div>
                        <div class="feature">💾 حفظ في GitHub</div>
                        <div class="feature">🚀 تشغيل مستمر</div>
                        <div class="feature">🔐 إدارة المسؤول</div>
                    </div>
                </div>

                <div class="admin-panel">
                    <h3>⚙️ لوحة التحكم</h3>
                    <p>حالة البوت: <strong>{'✅ نشط' if config.bot_enabled else '⛔ متوقف'}</strong></p>
                    <p>للتغيير، أرسل /toggle_bot إلى البوت</p>
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
        'timestamp': ti.time(),
        'uptime': ti.time() - config.session_stats['start_time'],
        'stats': config.session_stats,
        'support': SUPPORT_USER
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    if not config.bot_enabled:
        return 'Bot is disabled', 403
        
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        b.process_new_updates([update])
        return 'OK', 200
    return 'Error', 400

@app.route('/api/proxies', methods=['GET'])
def api_get_proxies():
    """واجهة برمجة للحصول على البروكسيات الشغالة"""
    if not config.bot_enabled:
        return jsonify({'error': 'Bot is disabled', 'support': SUPPORT_USER}), 403
        
    protocol = request.args.get('protocol', 'all')
    country = request.args.get('country', 'all')
    limit = int(request.args.get('limit', 50))
    
    filtered_proxies = []
    for proxy in config.working_proxies:
        if protocol != 'all' and proxy.get('type', '').lower() != protocol.lower():
            continue
        if country != 'all' and proxy.get('country', '').lower() != country.lower():
            continue
        filtered_proxies.append(proxy)
    
    return jsonify({
        'success': True,
        'count': len(filtered_proxies[:limit]),
        'proxies': filtered_proxies[:limit],
        'support': SUPPORT_USER
    })

@app.route('/test-proxy', methods=['GET', 'POST'])
def test_proxy_web():
    """واجهة ويب لفحص البروكسيات"""
    if not config.bot_enabled:
        return "<h1>⛔ البوت متوقف حالياً</h1><p>يرجى التواصل مع المسؤول {}</p>".format(SUPPORT_USER)
        
    if request.method == 'POST':
        proxy = request.form.get('proxy', '')
        if proxy:
            try:
                # فحص البروكسي
                result = advanced_proxy_check(proxy)
                return f"""
                <html>
                <head>
                    <title>نتيجة الفحص</title>
                    <style>
                        body {{ font-family: Arial; padding: 20px; background: #f5f5f5; }}
                        .result {{ background: {'#d4edda' if result['working'] else '#f8d7da'}; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                        .btn {{ background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 5px; }}
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
                        {f"<p><strong>الاختبارات الناجحة:</strong> {result['tests_passed']}/{result['total_tests']}</p>" if result['working'] else ""}
                    </div>
                    <a href="/test-proxy" class="btn">فحص بروكسي آخر</a>
                    <a href="/" class="btn">الرئيسية</a>
                </body>
                </html>
                """
            except Exception as e:
                return f"<h2>❌ خطأ في الفحص</h2><p>{str(e)}</p><p>الدعم: {SUPPORT_USER}</p>"
    
    return '''
    <html>
    <head>
        <title>🔧 فحص البروكسيات</title>
        <style>
            body { font-family: Arial; margin: 40px; background: #f5f5f5; }
            .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            input, button { padding: 10px; margin: 5px; width: 100%; box-sizing: border-box; }
            button { background: #007bff; color: white; border: none; cursor: pointer; }
            button:hover { background: #0056b3; }
            .support { background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧪 فحص البروكسيات يدوياً</h1>
            <div class="support">
                <strong>📞 الدعم:</strong> ''' + SUPPORT_USER + '''
            </div>
            <form method="POST">
                <input type="text" name="proxy" placeholder="أدخل البروكسي (مثال: 194.35.125.100:8080 أو user:pass@194.35.125.100:8080)" required>
                <button type="submit">فحص البروكسي</button>
            </form>
            <br>
            <h3>📝 أمثلة على تنسيقات البروكسيات:</h3>
            <ul>
                <li>194.35.125.100:8080</li>
                <li>user:password@194.35.125.100:8080</li>
                <li>http://194.35.125.100:8080</li>
                <li>socks5://194.35.125.100:1080</li>
            </ul>
        </div>
    </body>
    </html>
    '''

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
                ti.sleep(2 ** attempt)  # Exponential backoff
    
    return None

# 🎯 نظام الفحص المتقدم مع 10+ مواقع
def advanced_proxy_check(proxy):
    """فحص متقدم للبروكسي مع 10+ مواقع اختبار"""
    try:
        logger.info(f"🔍 فحص متقدم: {proxy}")
        
        # إعداد البروكسي
        proxy_dict = {
            'http': proxy,
            'https': proxy
        }
        
        # الحصول على IP الأصلي
        original_ip = get_original_ip()
        
        # اختبارات متعددة على 10+ مواقع
        test_results = []
        start_time = ti.time()
        successful_ips = set()
        
        for test_url in TEST_SITES:
            try:
                test_start = ti.time()
                response = rq.get(test_url, proxies=proxy_dict, timeout=8)
                test_time = ti.time() - test_start
                
                if response.status_code == 200:
                    # استخراج IP من الاستجابة
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
            # احسب متوسط السرعة
            speeds = [r['speed'] for r in successful_tests if 'speed' in r]
            avg_speed = sum(speeds) / len(speeds) if speeds else total_time
            
            # حدد نوع البروكسي
            proxy_type = "HTTP"
            if proxy.startswith('https://'):
                proxy_type = "HTTPS"
            elif proxy.startswith('socks4://'):
                proxy_type = "SOCKS4"
            elif proxy.startswith('socks5://'):
                proxy_type = "SOCKS5"
            
            # احصل على معلومات الدولة من أول IP ناجح
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
        if 'ipify' in test_url or 'ipinfo' in test_url or 'myip' in test_url or 'ipapi' in test_url:
            data = response.json()
            return data.get('ip', '')
        elif 'httpbin' in test_url:
            data = response.json()
            return data.get('origin', '')
        elif 'ident.me' in test_url or 'seeip' in test_url or 'ipecho' in test_url or 'amazonaws' in test_url:
            return response.text.strip()
        else:
            # محاولة استخراج IP من النص
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

# 🎯 نظام السحب الذكي
def smart_pull_proxies(chat_id):
    """سحب ذكي من جميع المصادر"""
    if not config.bot_enabled:
        b.send_message(chat_id, "⛔ البوت متوقف حالياً. يرجى التواصل مع المسؤول.")
        return []
        
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
    
    # معالجة النتائج
    unique_proxies = list(set(all_proxies))
    config.session_stats['total_proxies_found'] += len(unique_proxies)
    
    # حفظ البروكسيات المسحوبة
    if unique_proxies:
        save_proxies_to_file(unique_proxies, "pulled_proxies.txt")
        save_proxies_to_github_format(unique_proxies, "github_proxies.txt")
    
    # إنشاء تقرير
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
    
    # إرسال الملف
    if unique_proxies:
        with open("pulled_proxies.txt", "rb") as f:
            b.send_document(chat_id, f, caption=f"📁 البروكسيات المسحوبة ({len(unique_proxies)})")
    
    # سؤال عن الفحص
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
            f.write("تم إنشاؤها تلقائياً بواسطة Proxy Master Bot\n\n")
            f.write("## 📋 البروكسيات:\n```\n")
            for proxy in proxies:
                f.write(f"{proxy}\n")
            f.write("```\n\n")
            f.write(f"## 📊 الإحصائيات:\n")
            f.write(f"- العدد الإجمالي: {len(proxies)}\n")
            f.write(f"- وقت الإنشاء: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- الدعم: {SUPPORT_USER}\n")
        return True
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ ملف GitHub: {e}")
        return False

def save_working_proxies_to_github(proxies_list):
    """حفظ البروكسيات الشغالة بصيغة GitHub"""
    if not proxies_list:
        return False
        
    filename = "working_proxies_github.txt"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("# 🎯 البروكسيات الشغالة - Proxy Master Bot\n\n")
            f.write("## 📊 ملخص النتائج:\n")
            f.write(f"- عدد البروكسيات الشغالة: {len(proxies_list)}\n")
            f.write(f"- وقت الفحص: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- الدعم: {SUPPORT_USER}\n\n")
            
            f.write("## 🔧 حسب النوع:\n")
            by_type = {}
            for proxy_info in proxies_list:
                ptype = proxy_info.get('type', 'Unknown')
                by_type[ptype] = by_type.get(ptype, 0) + 1
            
            for ptype, count in by_type.items():
                f.write(f"- {ptype}: {count}\n")
            
            f.write("\n## 🌍 حسب الدولة:\n")
            by_country = {}
            for proxy_info in proxies_list:
                country = proxy_info.get('country', 'Unknown')
                by_country[country] = by_country.get(country, 0) + 1
            
            for country, count in sorted(by_country.items(), key=lambda x: x[1], reverse=True)[:10]:
                f.write(f"- {country}: {count}\n")
            
            f.write("\n## 📋 قائمة البروكسيات:\n```\n")
            for proxy_info in proxies_list:
                f.write(f"{proxy_info['proxy']}\n")
            f.write("```\n")
        
        logger.info(f"💾 تم حفظ {len(proxies_list)} بروكسي شغال بصيغة GitHub")
        return filename
    except Exception as e:
        logger.error(f"❌ خطأ في حفظ ملف GitHub: {e}")
        return None

# 🎯 نظام الفحص المتقدم
def advanced_mass_check(proxies_list, chat_id):
    """فحص جماعي متقدم"""
    if not config.bot_enabled:
        b.send_message(chat_id, "⛔ البوت متوقف حالياً. يرجى التواصل مع المسؤول.")
        return [], 0
        
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
                
                # تحديث التقدم
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
def generate_detailed_report(proxies_list, elapsed_time):
    """تقرير مفصل عن البروكسيات"""
    if not proxies_list:
        return "❌ لا توجد بروكسيات شغالة"
    
    # إحصائيات متقدمة
    by_type = {}
    by_country = {}
    by_speed = {
        'fast': [p for p in proxies_list if p['speed'] < 2],
        'medium': [p for p in proxies_list if 2 <= p['speed'] < 5],
        'slow': [p for p in proxies_list if p['speed'] >= 5]
    }
    
    for proxy in proxies_list:
        # حسب النوع
        proxy_type = proxy.get('type', 'Unknown')
        by_type[proxy_type] = by_type.get(proxy_type, 0) + 1
        
        # حسب الدولة
        country = proxy.get('country', 'Unknown')
        by_country[country] = by_country.get(country, 0) + 1
    
    # أفضل البروكسيات
    fast_proxies = sorted(proxies_list, key=lambda x: x['speed'])[:10]
    
    report = f"""
📊 **تقرير مفصل عن البروكسيات الشغالة**

✅ الإجمالي: {len(proxies_list)} بروكسي
⏱ وقت الفحص: {elapsed_time:.2f} ثانية
🌐 مواقع الاختبار: {len(TEST_SITES)}

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

    report += f"\n📞 **الدعم:** {SUPPORT_USER}"
    
    return report

# 🤖 Handlers للبوت
@b.message_handler(commands=['start'])
def send_welcome(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. يرجى التواصل مع المسؤول {SUPPORT_USER}")
        return
        
    if message.from_user.id == ADMIN_ID:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        buttons = [
            "🚀 سحب ذكي", 
            "🔍 فحص متقدم",
            "📁 فحص من ملف",
            "⚙️ إدارة المسؤول",
            "📊 إحصائيات حية",
            "🌐 فحص يدوي",
            "🆘 المساعدة"
        ]
        markup.add(*buttons)
        
        welcome_text = f"""
🚀 **أهلاً بك في ℙℛᎾXᎽ ℙℳᎾ 𖠛** 

🎯 **أقوى أداة سحب وفحص بروكسيات على Render.com**

✅ **المميزات المتقدمة:**
• 🔍 سحب ذكي من 15+ مصدر
• ⚡ فحص على 10+ مواقع (ipinfo.io وغيره)
• 🌍 كشف الدولة والخصوصية
• 🔧 دعم جميع أنواع البروكسيات
• 📊 إحصائيات وتقارير متقدمة
• 💾 حفظ بصيغة GitHub
• 🚀 تشغيل مستمر 24/7

📞 **الدعم:** {SUPPORT_USER}

📋 **لبدء الاستخدام:**
1. 🚀 سحب ذكي - لجمع البروكسيات
2. 🔍 فحص متقدم - لاختبار الجودة
3. 📁 فحص من ملف - لفحص قوائم جاهزة

⚙️ **أوامر المسؤول:**
/toggle_bot - تشغيل/إيقاف البوت
/stats - إحصائيات مفصلة
/test URL - فحص بروكسي يدوي
        """
        b.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")
    else:
        b.send_message(message.chat.id, f"⛔ أنت لست مسؤولاً مصرحًا به. الدعم: {SUPPORT_USER}")

@b.message_handler(commands=['toggle_bot'])
def toggle_bot(message):
    """تشغيل/إيقاف البوت (للمسؤول فقط)"""
    if message.from_user.id == ADMIN_ID:
        config.bot_enabled = not config.bot_enabled
        status = "✅ تم تشغيل البوت" if config.bot_enabled else "⛔ تم إيقاف البوت"
        b.send_message(message.chat.id, f"{status}\n\n📞 الدعم: {SUPPORT_USER}")
        
        # تسجيل في السجلات
        logger.info(f"البوت { 'مفعل' if config.bot_enabled else 'موقف' } بواسطة المسؤول")
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية هذه الأمر. الدعم: {SUPPORT_USER}")

@b.message_handler(commands=['stats'])
def show_stats(message):
    """إظهار إحصائيات مفصلة"""
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    uptime = ti.time() - config.session_stats['start_time']
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    stats_text = f"""
📊 **إحصائيات البوت المتقدمة**

🕒 وقت التشغيل: {int(hours)}h {int(minutes)}m {int(seconds)}s
🔗 بروكسيات مسحوبة: {config.session_stats['total_proxies_found']}
✅ بروكسيات شغالة: {config.session_stats['working_proxies_found']}
🔍 بروكسيات مفحوصة: {config.session_stats['total_proxies_checked']}

🌐 **المصادر النشطة:**
"""
    
    for source_id, source_info in PROXY_SOURCES.items():
        if source_info['enabled']:
            stats_text += f"• {source_info['name']}: {len(source_info['sites'])} موقع\n"
    
    stats_text += f"""
⚡ **مواقع الفحص:** {len(TEST_SITES)} موقع
🔧 **الحالة:** {'✅ نشط' if config.bot_enabled else '⛔ متوقف'}

📞 **الدعم:** {SUPPORT_USER}
    """
    
    b.send_message(message.chat.id, stats_text, parse_mode="Markdown")

@b.message_handler(commands=['test'])
def test_single_proxy_command(message):
    """فحص بروكسي فردي عبر الأمر"""
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    try:
        proxy = message.text.split(' ', 1)[1].strip()
    except:
        b.send_message(message.chat.id, f"❌ استخدم: /test proxy_url\nمثال: /test http://194.35.125.100:8080\n\n📞 الدعم: {SUPPORT_USER}")
        return
    
    b.send_message(message.chat.id, f"🔍 جاري فحص البروكسي: `{proxy}`", parse_mode="Markdown")
    
    result = advanced_proxy_check(proxy)
    
    if result['working']:
        response_text = f"""
🎉 **البروكسي شغال!**

✅ `{result['proxy']}`
⚡ **السرعة:** {result['speed']} ثانية
🔧 **النوع:** {result['type']}
🌐 **IP الجديد:** {result['ip']}
🏴 **الدولة:** {result['country']}
📊 **الاختبارات:** {result['tests_passed']}/{result['total_tests']}

**تم الفحص على {len(TEST_SITES)} موقع بنجاح!** ✅
        """
    else:
        response_text = f"""
❌ **البروكسي لا يعمل**

`{proxy}`

**الأسباب المحتملة:**
• الخادم غير متصل
• البورت مغلق
• بيانات الدخول خاطئة
• البروكسي محظور

**جرب بروكسي آخر** 🔄
        """
    
    b.send_message(message.chat.id, response_text, parse_mode="Markdown")

@b.message_handler(func=lambda message: message.text == "🚀 سحب ذكي")
def start_smart_pull(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    if message.from_user.id == ADMIN_ID:
        proxies = smart_pull_proxies(message.chat.id)
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية هذه الأمر. الدعم: {SUPPORT_USER}")

@b.message_handler(func=lambda message: message.text == "🔍 فحص متقدم")
def start_advanced_check(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    try:
        with open("pulled_proxies.txt", "r", encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip()]
        
        if proxies:
            b.send_message(message.chat.id, "🔬 بدء الفحص المتقدم...")
            working_proxies, elapsed_time = advanced_mass_check(proxies, message.chat.id)
            
            # إرسال التقرير
            report = generate_detailed_report(working_proxies, elapsed_time)
            b.send_message(message.chat.id, report, parse_mode="Markdown")
            
            # حفظ البروكسيات الشغالة
            if working_proxies:
                with open("working_proxies.txt", "w", encoding="utf-8") as f:
                    for proxy_info in working_proxies:
                        f.write(f"{proxy_info['proxy']}\n")
                
                # حفظ بصيغة GitHub
                github_file = save_working_proxies_to_github(working_proxies)
                
                with open("working_proxies.txt", "rb") as f:
                    b.send_document(message.chat.id, f, caption=f"📁 البروكسيات الشغالة ({len(working_proxies)})")
                
                if github_file:
                    with open(github_file, "rb") as f:
                        b.send_document(message.chat.id, f, caption="💾 ملف GitHub جاهز للرفع")
        else:
            b.send_message(message.chat.id, "❌ لا توجد بروكسيات مسحوبة. قم بالسحب أولاً.")
    except FileNotFoundError:
        b.send_message(message.chat.id, "❌ لا توجد بروكسيات مسحوبة. قم بالسحب أولاً.")

@b.message_handler(func=lambda message: message.text == "📁 فحص من ملف")
def check_from_file(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    b.send_message(message.chat.id, "📁 أرسل ملف البروكسيات (txt)")
    config.user_states[message.chat.id] = 'awaiting_check_file'

@b.message_handler(func=lambda message: message.text == "🌐 فحص يدوي")
def manual_test_info(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    test_info = f"""
🌐 **الفحص اليدوي عبر المتصفح**

يمكنك فحص البروكسيات يدوياً عبر:
1. **الويب:** {RENDER_URL}/test-proxy
2. **الأمر:** /test proxy_url
3. **الواجهة:** {RENDER_URL}

📋 **مواقع الفحص المستخدمة:**
"""
    
    for site in TEST_SITES:
        test_info += f"• {site}\n"
    
    test_info += f"\n📞 **الدعم:** {SUPPORT_USER}"
    
    b.send_message(message.chat.id, test_info, parse_mode="Markdown")

@b.message_handler(func=lambda message: message.text == "⚙️ إدارة المسؤول")
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:
        admin_text = f"""
⚙️ **لوحة تحكم المسؤول**

🔧 **حالة البوت:** {'✅ نشط' if config.bot_enabled else '⛔ متوقف'}
📊 **الإحصائيات:** {config.session_stats['working_proxies_found']} بروكسي شغال
🌐 **الواجهات:** {RENDER_URL}

🎯 **الأوامر المتاحة:**
/toggle_bot - تشغيل/إيقاف البوت
/stats - إحصائيات مفصلة  
/test URL - فحص بروكسي

📞 **الدعم:** {SUPPORT_USER}
        """
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🔄 " + ("إيقاف البوت" if config.bot_enabled else "تشغيل البوت"), callback_data="toggle_bot"),
            types.InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats")
        )
        
        b.send_message(message.chat.id, admin_text, reply_markup=markup, parse_mode="Markdown")
    else:
        b.send_message(message.chat.id, f"⛔ ليس لديك صلاحية الوصول. الدعم: {SUPPORT_USER}")

@b.message_handler(func=lambda message: message.text == "🆘 المساعدة")
def help_command(message):
    help_text = f"""
🆘 **دليل استخدام البوت**

🚀 **لبدء الاستخدام:**
1. اضغط على \"🚀 سحب ذكي\" لجمع البروكسيات
2. اضغط على \"🔍 فحص متقدم\" لاختبارها
3. احصل على الملف النهائي

🔧 **الفحص اليدوي:**
• عبر المتصفح: {RENDER_URL}/test-proxy
• عبر الأمر: /test proxy_url

📁 **فحص الملفات:**
• أرسل ملف txt يحتوي على بروكسيات
• بروكسي في كل سطر

⚙️ **للمسؤولين:**
• /toggle_bot - التحكم بالبوت
• /stats - إحصائيات مفصلة

📞 **الدعم:** {SUPPORT_USER}
    """
    b.send_message(message.chat.id, help_text, parse_mode="Markdown")

@b.message_handler(content_types=['document'])
def handle_document(message):
    if not config.bot_enabled:
        b.send_message(message.chat.id, f"⛔ البوت متوقف حالياً. الدعم: {SUPPORT_USER}")
        return
        
    if config.user_states.get(message.chat.id) == 'awaiting_check_file':
        try:
            file_info = b.get_file(message.document.file_id)
            downloaded_file = b.download_file(file_info.file_path)
            
            filename = f"user_proxies_{message.chat.id}.txt"
            with open(filename, 'wb') as f:
                f.write(downloaded_file)
            
            # قراءة البروكسيات من الملف
            proxies = []
            with open(filename, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        proxies.append(line)
            
            b.send_message(message.chat.id, f"📥 تم تحميل {len(proxies)} بروكسي من الملف")
            config.user_states[message.chat.id] = None
            
            # بدء الفحص
            if proxies:
                b.send_message(message.chat.id, "🔬 بدء فحص البروكسيات من الملف...")
                working_proxies, elapsed_time = advanced_mass_check(proxies, message.chat.id)
                
                # إرسال النتائج
                report = generate_detailed_report(working_proxies, elapsed_time)
                b.send_message(message.chat.id, report, parse_mode="Markdown")
                
                if working_proxies:
                    with open("working_proxies.txt", "w", encoding="utf-8") as f:
                        for proxy_info in working_proxies:
                            f.write(f"{proxy_info['proxy']}\n")
                    
                    with open("working_proxies.txt", "rb") as f:
                        b.send_document(message.chat.id, f, caption=f"📁 البروكسيات الشغالة ({len(working_proxies)})")
            
        except Exception as e:
            b.send_message(message.chat.id, f"❌ خطأ في تحميل الملف: {e}\n\n📞 الدعم: {SUPPORT_USER}")
            config.user_states[message.chat.id] = None

@b.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    
    if call.data == "toggle_bot" and call.from_user.id == ADMIN_ID:
        config.bot_enabled = not config.bot_enabled
        status = "✅ تم تشغيل البوت" if config.bot_enabled else "⛔ تم إيقاف البوت"
        b.answer_callback_query(call.id, status)
        admin_panel(call.message)
    
    elif call.data == "show_stats":
        show_stats(call.message)
        b.answer_callback_query(call.id, "تم عرض الإحصائيات")
    
    elif call.data == "advanced_check":
        b.answer_callback_query(call.id, "بدء الفحص المتقدم")
        start_advanced_check(call.message)
    
    elif call.data == "quick_check":
        b.answer_callback_query(call.id, "بدء الفحص السريع")
        # يمكنك إضافة فحص سريع هنا
    
    elif call.data == "skip_check":
        b.answer_callback_query(call.id, "تم تخطي الفحص")
        b.send_message(chat_id, "✅ تم تخطي الفحص. يمكنك فحص البروكسيات لاحقاً.")

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
    logger.info("🚀 بدء تشغيل Proxy Master Bot على Render.com...")
    logger.info(f"📞 دعم المسؤول: {SUPPORT_USER}")
    
    # محاولة إعداد Webhook
    webhook_setup = setup_webhook()
    
    if webhook_setup and RENDER_URL:
        print(f"""
🎉 Proxy Master Bot يعمل على ℙℛᎾXᎽ ℙℳᎾ 𖠛!
✅ Webhook: {RENDER_URL}/webhook
✅ الواجهة: {RENDER_URL}
✅ فحص يدوي: {RENDER_URL}/test-proxy
✅ API: {RENDER_URL}/api/proxies
✅ الصحة: {RENDER_URL}/health

📞 الدعم: {SUPPORT_USER}
📊 البوت جاهز للعمل بكامل الميزات!
        """)
        
        # تشغيل Flask app
        port = int(os.environ.get("PORT", 10000))
        app.run(host='0.0.0.0', port=port, debug=False)
        
    else:
        print(f"""
🔄 استخدام Polling mode
✅ جميع الميزات تعمل
📞 الدعم: {SUPPORT_USER}
💡 Webhook مفقود - باستخدام Polling
        """)
        b.infinity_polling(timeout=60, long_polling_timeout=60)
