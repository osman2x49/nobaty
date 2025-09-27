import os
import telebot
from threading import Thread
from flask import Flask

# إعدادات البوت
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# تهيئة البوت
bot = telebot.TeleBot(BOT_TOKEN)

# تطبيق Flask للويب (مطلوب من Render)
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 بوت نوباتيا يعمل بنجاح!"

@app.route('/health')
def health():
    return "✅ البوت يعمل بشكل طبيعي"

# ============================ قاعدة البيانات مع SQLite ============================
import sqlite3
from datetime import datetime, timedelta
import csv
import logging

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)

class Database:
    def __init__(self, db_name='nobatia_bot.db'):
        self.db_name = db_name
        self.init_db()
    
    def get_connection(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)
    
    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # جدول المستخدمين
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                usd_balance REAL DEFAULT 0,
                eur_balance REAL DEFAULT 0,
                gbp_balance REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول المعاملات
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                from_currency TEXT,
                to_currency TEXT,
                amount REAL,
                rate REAL,
                converted_amount REAL,
                type TEXT,
                status TEXT DEFAULT 'completed',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # جدول أسعار الصرف
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_currency TEXT,
                to_currency TEXT,
                buy_rate REAL,
                sell_rate REAL,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # جدول جلسات الأدمن
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                user_id INTEGER PRIMARY KEY,
                expires_at TEXT
            )
        ''')
        
        # إدخال أسعار الصرف الافتراضية
        cursor.execute('SELECT COUNT(*) FROM exchange_rates')
        if cursor.fetchone()[0] == 0:
            default_rates = [
                ('USD', 'EUR', 0.85, 0.87),
                ('USD', 'GBP', 0.73, 0.75),
                ('EUR', 'USD', 1.15, 1.17),
                ('EUR', 'GBP', 0.86, 0.88),
                ('GBP', 'USD', 1.33, 1.35),
                ('GBP', 'EUR', 1.14, 1.16)
            ]
            
            for from_curr, to_curr, buy, sell in default_rates:
                cursor.execute('''
                    INSERT OR IGNORE INTO exchange_rates (from_currency, to_currency, buy_rate, sell_rate)
                    VALUES (?, ?, ?, ?)
                ''', (from_curr, to_curr, buy, sell))
        
        conn.commit()
        conn.close()
        logging.info("✅ قاعدة البيانات مهيأة بنجاح")

# باقي الكود (نفس الكود السابق)...
# ... [أدخل هنا كل كود الدوال والكلاسات السابقة] ...

# ============================ تشغيل البوت ============================
def run_bot():
    """تشغيل البوت في thread منفصل"""
    try:
        logging.info("🚀 بدء تشغيل بوت نوباتيا...")
        bot.remove_webhook()
        bot.polling(none_stop=True, timeout=60)
    except Exception as e:
        logging.error(f"❌ خطأ في البوت: {e}")
        # إعادة المحاولة بعد 10 ثواني
        time.sleep(10)
        run_bot()

if __name__ == "__main__":
    # تشغيل البوت في thread منفصل
    bot_thread = Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # تشغيل تطبيق Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
