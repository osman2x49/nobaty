import sqlite3
import csv
import os
from datetime import datetime, date
import telebot
from telebot import types
import threading
import time

# ============================ إعدادات البوت ============================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_CREDENTIALS = {
    'username': 'admin',
    'password': 'admin123'
}

# ============================ تهيئة البوت ============================
bot = telebot.TeleBot(BOT_TOKEN)

# ============================ قاعدة البيانات مع SQLite ============================
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
                type TEXT, -- 'exchange' or 'transfer'
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
        
        # إدخال أسعار الصرف الافتراضية إذا لم تكن موجودة
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
                    INSERT INTO exchange_rates (from_currency, to_currency, buy_rate, sell_rate)
                    VALUES (?, ?, ?, ?)
                ''', (from_curr, to_curr, buy, sell))
        
        conn.commit()
        conn.close()
    
    def get_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'user_id': user[0],
                'username': user[1],
                'full_name': user[2],
                'phone': user[3],
                'usd_balance': user[4] or 0,
                'eur_balance': user[5] or 0,
                'gbp_balance': user[6] or 0,
                'created_at': user[7]
            }
        return None
    
    def get_user_safe(self, user_id):
        user = self.get_user(user_id)
        if not user:
            # إنشاء مستخدم جديد إذا لم يوجد
            return self.create_user(user_id, "Unknown", "Unknown User")
        return user
    
    def create_user(self, user_id, username, full_name, phone=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, full_name, phone)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, full_name, phone))
            conn.commit()
            return self.get_user(user_id)
        except Exception as e:
            print(f"Error creating user: {e}")
            return None
        finally:
            conn.close()
    
    def update_user_balance(self, user_id, currency, amount):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            currency_column = f"{currency.lower()}_balance"
            cursor.execute(f'''
                UPDATE users 
                SET {currency_column} = COALESCE({currency_column}, 0) + ? 
                WHERE user_id = ?
            ''', (amount, user_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating balance: {e}")
            return False
    
    def get_balance(self, user_id, currency):
        user = self.get_user(user_id)
        if user:
            return user.get(f"{currency.lower()}_balance", 0)
        return 0
    
    def record_transaction(self, user_id, from_currency, to_currency, amount, rate, converted_amount, transaction_type):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO transactions 
                (user_id, from_currency, to_currency, amount, rate, converted_amount, type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, from_currency, to_currency, amount, rate, converted_amount, transaction_type))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error recording transaction: {e}")
            return False
        finally:
            conn.close()
    
    def get_transactions(self, user_id=None, start_date=None, end_date=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT t.*, u.full_name 
            FROM transactions t 
            LEFT JOIN users u ON t.user_id = u.user_id 
            WHERE 1=1
        '''
        params = []
        
        if user_id:
            query += ' AND t.user_id = ?'
            params.append(user_id)
        
        if start_date:
            query += ' AND DATE(t.created_at) >= ?'
            params.append(start_date)
        
        if end_date:
            query += ' AND DATE(t.created_at) <= ?'
            params.append(end_date)
        
        query += ' ORDER BY t.created_at DESC'
        
        cursor.execute(query, params)
        transactions = cursor.fetchall()
        conn.close()
        
        result = []
        for t in transactions:
            result.append({
                'id': t[0],
                'user_id': t[1],
                'user_name': t[8],
                'from_currency': t[2],
                'to_currency': t[3],
                'amount': t[4],
                'rate': t[5],
                'converted_amount': t[6],
                'type': t[7],
                'status': t[8],
                'created_at': t[9]
            })
        
        return result
    
    def get_all_users(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users ORDER BY created_at DESC')
        users = cursor.fetchall()
        conn.close()
        
        result = []
        for user in users:
            result.append({
                'user_id': user[0],
                'username': user[1],
                'full_name': user[2],
                'phone': user[3],
                'usd_balance': user[4] or 0,
                'eur_balance': user[5] or 0,
                'gbp_balance': user[6] or 0,
                'created_at': user[7]
            })
        return result
    
    def is_admin_logged_in(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT expires_at FROM admin_sessions WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            expires_at = datetime.fromisoformat(result[0])
            if expires_at > datetime.now():
                return True
            else:
                # حذف الجلسة المنتهية
                self.logout_admin(user_id)
        return False
    
    def login_admin(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
        cursor.execute('''
            INSERT OR REPLACE INTO admin_sessions (user_id, expires_at)
            VALUES (?, ?)
        ''', (user_id, expires_at))
        conn.commit()
        conn.close()
    
    def logout_admin(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM admin_sessions WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

# ============================ إدارة أسعار الصرف ============================
class ExchangeRates:
    def __init__(self, db):
        self.db = db
    
    def get_rate(self, from_currency, to_currency):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT buy_rate, sell_rate, last_updated 
            FROM exchange_rates 
            WHERE from_currency = ? AND to_currency = ?
        ''', (from_currency, to_currency))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'buy_rate': result[0],
                'sell_rate': result[1],
                'last_updated': result[2]
            }
        return None
    
    def update_rate(self, from_currency, to_currency, buy_rate, sell_rate):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO exchange_rates 
                (from_currency, to_currency, buy_rate, sell_rate, last_updated)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (from_currency, to_currency, buy_rate, sell_rate))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating rate: {e}")
            return False
        finally:
            conn.close()
    
    def get_all_rates(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM exchange_rates ORDER BY from_currency, to_currency')
        rates = cursor.fetchall()
        conn.close()
        
        result = []
        for rate in rates:
            result.append({
                'id': rate[0],
                'from_currency': rate[1],
                'to_currency': rate[2],
                'buy_rate': rate[3],
                'sell_rate': rate[4],
                'last_updated': rate[5]
            })
        return result

# ============================ نظام التقارير ============================
class Reports:
    def __init__(self, db):
        self.db = db
    
    def export_transactions_csv(self, start_date=None, end_date=None):
        transactions = self.db.get_transactions(start_date=start_date, end_date=end_date)
        
        filename = f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['ID', 'User ID', 'User Name', 'From Currency', 'To Currency', 
                           'Amount', 'Rate', 'Converted Amount', 'Type', 'Date'])
            
            for t in transactions:
                writer.writerow([
                    t['id'], t['user_id'], t['user_name'], t['from_currency'], 
                    t['to_currency'], t['amount'], t['rate'], t['converted_amount'], 
                    t['type'], t['created_at']
                ])
        
        return filename
    
    def export_users_csv(self):
        users = self.db.get_all_users()
        
        filename = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['User ID', 'Username', 'Full Name', 'Phone', 
                           'USD Balance', 'EUR Balance', 'GBP Balance', 'Join Date'])
            
            for u in users:
                writer.writerow([
                    u['user_id'], u['username'], u['full_name'], u['phone'],
                    u['usd_balance'], u['eur_balance'], u['gbp_balance'], u['created_at']
                ])
        
        return filename

# ============================ تهيئة المكونات ============================
db = Database()
exchange_rates = ExchangeRates(db)
reports = Reports(db)

# حالة المستخدمين
user_states = {}

# ============================ معالجات الأوامر ============================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "غير معروف"
    full_name = f"{message.from_user.first_name} {message.from_user.last_name or ''}".strip()
    
    # إنشاء/تحديث المستخدم
    db.create_user(user_id, username, full_name)
    
    # لوحة المفاتيح الرئيسية
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    if db.is_admin_logged_in(user_id):
        keyboard.row("💱 تحويل العملات", "📊 عرض الرصيد")
        keyboard.row("👥 إدارة المستخدمين", "⚙️ إدارة الأسعار")
        keyboard.row("📊 تصدير CSV", "🚪 تسجيل خروج الأدمن")
    else:
        keyboard.row("💱 تحويل العملات", "📊 عرض الرصيد")
        keyboard.row("ℹ️ معلومات", "🔐 دخول الأدمن")
    
    welcome_text = """
    🏦 مرحباً بك في بوت نوباتيا للخدمات التجارية!

    💰 يمكنك إجراء تحويلات العملات وعرض أرصدتك بسهولة.

    اختر أحد الخيارات أدناه:
    """
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard)

# ============================ معالجة الأزرار الرئيسية ============================
@bot.message_handler(func=lambda message: message.text == "💱 تحويل العملات")
def handle_currency_exchange(message):
    user_id = message.from_user.id
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("💰 تحويل عملات", callback_data="exchange_currency"),
        types.InlineKeyboardButton("👥 تحويل لأحد", callback_data="transfer_to_user")
    )
    
    bot.send_message(
        message.chat.id,
        "💱 اختر نوع التحويل:",
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: message.text == "📊 عرض الرصيد")
def show_balance(message):
    user_id = message.from_user.id
    user = db.get_user_safe(user_id)
    
    balance_text = f"""
    💼 رصيدك الحالي:

    💵 USD: {user['usd_balance']:,.2f}
    💶 EUR: {user['eur_balance']:,.2f}
    💷 GBP: {user['gbp_balance']:,.2f}

    💱 لتحويل العملات، استخدم زر 'تحويل العملات'
    """
    
    bot.send_message(message.chat.id, balance_text)

@bot.message_handler(func=lambda message: message.text == "🔐 دخول الأدمن")
def admin_login_start(message):
    user_id = message.from_user.id
    user_states[user_id] = {'step': 'admin_username'}
    bot.send_message(message.chat.id, "🔐 أدخل اسم مستخدم الأدمن:")

@bot.message_handler(func=lambda message: message.text == "🚪 تسجيل خروج الأدمن")
def admin_logout(message):
    user_id = message.from_user.id
    db.logout_admin(user_id)
    bot.send_message(message.chat.id, "✅ تم تسجيل الخروج من وضع الأدمن بنجاح")
    send_welcome(message)

@bot.message_handler(func=lambda message: message.text == "👥 إدارة المستخدمين")
def manage_users(message):
    if not db.is_admin_logged_in(message.from_user.id):
        bot.send_message(message.chat.id, "❌ يجب تسجيل الدخول كمدير أولاً")
        return
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📋 عرض جميع المستخدمين", callback_data="list_all_users"),
        types.InlineKeyboardButton("➕ إضافة رصيد", callback_data="add_balance")
    )
    
    bot.send_message(
        message.chat.id,
        "👥 إدارة المستخدمين:",
        reply_markup=keyboard
    )

@bot.message_handler(func=lambda message: message.text == "⚙️ إدارة الأسعار")
def manage_rates(message):
    if not db.is_admin_logged_in(message.from_user.id):
        bot.send_message(message.chat.id, "❌ يجب تسجيل الدخول كمدير أولاً")
        return
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    currencies = ['USD', 'EUR', 'GBP']
    
    for from_curr in currencies:
        for to_curr in currencies:
            if from_curr != to_curr:
                keyboard.add(
                    types.InlineKeyboardButton(
                        f"{from_curr}→{to_curr}", 
                        callback_data=f"edit_rate_{from_curr}_{to_curr}"
                    )
                )
    
    keyboard.add(types.InlineKeyboardButton("📊 عرض جميع الأسعار", callback_data="show_rates_admin"))
    
    bot.send_message(
        message.chat.id,
        "⚙️ إدارة أسعار الصرف:",
        reply_markup=keyboard
    )

# ============================ معالجة استدعاءات الأزرار ============================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    
    if call.data == "exchange_currency":
        handle_exchange_currency(call)
    elif call.data == "transfer_to_user":
        handle_transfer_to_user(call)
    elif call.data == "list_all_users":
        handle_list_all_users(call)
    elif call.data == "add_balance":
        handle_add_balance(call)
    elif call.data.startswith("edit_rate_"):
        handle_edit_rate(call)
    elif call.data == "show_rates_admin":
        handle_show_rates_admin(call)

def handle_exchange_currency(call):
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    currencies = ['USD', 'EUR', 'GBP']
    
    for from_curr in currencies:
        for to_curr in currencies:
            if from_curr != to_curr:
                keyboard.add(
                    types.InlineKeyboardButton(
                        f"{from_curr}→{to_curr}", 
                        callback_data=f"exch_{from_curr}_{to_curr}"
                    )
                )
    
    bot.edit_message_text(
        "💱 اختر زوج العملات للتحويل:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

def handle_transfer_to_user(call):
    bot.edit_message_text(
        "👥 لتحويل الأموال لمستخدم آخر، يرجى التواصل مع الدعم.",
        call.message.chat.id,
        call.message.message_id
    )

def handle_list_all_users(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    users = db.get_all_users()
    
    if not users:
        response = "❌ لا يوجد مستخدمين مسجلين بعد."
    else:
        response = "👥 جميع المستخدمين:\n\n"
        for user in users[:10]:  # عرض أول 10 مستخدمين فقط
            response += f"👤 {user['full_name']} (@{user['username']})\n"
            response += f"   📞 {user['phone'] or 'غير متوفر'}\n"
            response += f"   💰 USD: {user['usd_balance']:,.2f} | EUR: {user['eur_balance']:,.2f} | GBP: {user['gbp_balance']:,.2f}\n"
            response += f"   📅 {user['created_at'][:10]}\n\n"
    
    bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

def handle_add_balance(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    bot.edit_message_text(
        "➕ إضافة رصيد للمستخدم\n\nأدخل معرف المستخدم (User ID):",
        call.message.chat.id,
        call.message.message_id
    )
    user_states[call.from_user.id] = {'step': 'add_balance_user'}

# ============================ معالجة حالات المستخدم ============================
@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'admin_username')
def process_admin_username(message):
    user_id = message.from_user.id
    user_states[user_id]['username'] = message.text
    user_states[user_id]['step'] = 'admin_password'
    bot.send_message(message.chat.id, "🔑 أدخل كلمة مرور الأدمن:")

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'admin_password')
def process_admin_password(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    if (state['username'] == ADMIN_CREDENTIALS['username'] and 
        message.text == ADMIN_CREDENTIALS['password']):
        db.login_admin(user_id)
        bot.send_message(message.chat.id, "✅ تم تسجيل الدخول كأدمن بنجاح!")
        send_welcome(message)
    else:
        bot.send_message(message.chat.id, "❌ بيانات الدخول غير صحيحة")
    
    user_states.pop(user_id, None)

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'add_balance_user')
def process_balance_user(message):
    user_id = message.from_user.id
    
    try:
        target_user_id = int(message.text)
        target_user = db.get_user_safe(target_user_id)
        
        if target_user:
            user_states[user_id] = {
                'step': 'add_balance_currency',
                'target_user_id': target_user_id
            }
            
            keyboard = types.InlineKeyboardMarkup(row_width=3)
            keyboard.add(
                types.InlineKeyboardButton("USD", callback_data="currency_USD"),
                types.InlineKeyboardButton("EUR", callback_data="currency_EUR"),
                types.InlineKeyboardButton("GBP", callback_data="currency_GBP")
            )
            
            bot.send_message(
                message.chat.id,
                f"👤 المستخدم: {target_user['full_name']}\n\nاختر العملة:",
                reply_markup=keyboard
            )
        else:
            bot.send_message(message.chat.id, "❌ لم يتم العثور على المستخدم")
            user_states.pop(user_id, None)
    except ValueError:
        bot.send_message(message.chat.id, "❌ يرجى إدخال معرف مستخدم صحيح (أرقام فقط)")

@bot.callback_query_handler(func=lambda call: call.data.startswith('currency_'))
def handle_currency_selection(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    currency = call.data.split('_')[1]
    user_id = call.from_user.id
    
    if user_id in user_states and user_states[user_id].get('step') == 'add_balance_currency':
        user_states[user_id]['currency'] = currency
        user_states[user_id]['step'] = 'add_balance_amount'
        
        target_user_id = user_states[user_id]['target_user_id']
        target_user = db.get_user_safe(target_user_id)
        
        bot.edit_message_text(
            f"👤 المستخدم: {target_user['full_name']}\n💱 العملة: {currency}\n\nأدخل المبلغ للإضافة:",
            call.message.chat.id,
            call.message.message_id
        )

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'add_balance_amount')
def process_amount_for_balance(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    try:
        amount = float(message.text)
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ يرجى إدخال مبلغ صحيح")
            return
        
        target_user_id = state['target_user_id']
        currency = state['currency']
        
        # إضافة الرصيد
        success = db.update_user_balance(target_user_id, currency, amount)
        
        if success:
            target_user = db.get_user_safe(target_user_id)
            balance_field = f"{currency.lower()}_balance"
            new_balance = target_user.get(balance_field, 0) + amount
            
            response = f"""✅ تم إضافة الرصيد بنجاح!

👤 المستخدم: {target_user['full_name']}
💰 المبلغ المضاف: {amount:,.2f} {currency}
💳 الرصيد الجديد: {new_balance:,.2f} {currency}"""
        else:
            response = "❌ فشل في إضافة الرصيد"
        
        bot.send_message(message.chat.id, response)
        user_states.pop(user_id, None)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ يرجى إدخال رقم صحيح")

# ============================ معالجة زر تصدير CSV ============================
@bot.message_handler(func=lambda message: message.text == "📊 تصدير CSV")
def export_csv_menu(message):
    user_id = message.from_user.id
    
    if not db.is_admin_logged_in(user_id):
        bot.send_message(message.chat.id, "❌ يجب تسجيل الدخول كمدير أولاً")
        return
    
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("📋 تصدير المعاملات", callback_data="export_transactions"),
        types.InlineKeyboardButton("👥 تصدير المستخدمين", callback_data="export_users")
    )
    keyboard.add(
        types.InlineKeyboardButton("📊 تصدير مخصص", callback_data="export_custom")
    )
    
    bot.send_message(
        message.chat.id,
        "📊 اختر نوع البيانات للتصدير:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('export_'))
def handle_export(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    export_type = call.data.split('_')[1]
    
    try:
        if export_type == 'transactions':
            filename = reports.export_transactions_csv()
            bot.edit_message_text(
                f"✅ تم تصدير المعاملات بنجاح!\n📁 اسم الملف: {filename}",
                call.message.chat.id,
                call.message.message_id
            )
            
            # إرسال الملف
            with open(filename, 'rb') as file:
                bot.send_document(call.message.chat.id, file)
            
            # حذف الملف بعد الإرسال
            os.remove(filename)
        
        elif export_type == 'users':
            filename = reports.export_users_csv()
            bot.edit_message_text(
                f"✅ تم تصدير المستخدمين بنجاح!\n📁 اسم الملف: {filename}",
                call.message.chat.id,
                call.message.message_id
            )
            
            # إرسال الملف
            with open(filename, 'rb') as file:
                bot.send_document(call.message.chat.id, file)
            
            # حذف الملف بعد الإرسال
            os.remove(filename)
        
        elif export_type == 'custom':
            bot.edit_message_text(
                "📊 تصدير مخصص\n\nأدخل تاريخ البداية (YYYY-MM-DD):",
                call.message.chat.id,
                call.message.message_id
            )
            user_states[call.from_user.id] = {'step': 'export_start_date'}
    
    except Exception as e:
        bot.edit_message_text(
            f"❌ حدث خطأ في التصدير: {str(e)}",
            call.message.chat.id,
            call.message.message_id
        )

# ============================ معالجة التصدير المخصص ============================
@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'export_start_date')
def process_export_start_date(message):
    user_id = message.from_user.id
    
    try:
        start_date = datetime.strptime(message.text, '%Y-%m-%d').date()
        user_states[user_id]['export_start_date'] = start_date
        user_states[user_id]['step'] = 'export_end_date'
        
        bot.send_message(message.chat.id, "📅 أدخل تاريخ النهاية (YYYY-MM-DD):")
    except ValueError:
        bot.send_message(message.chat.id, "❌ تنسيق التاريخ غير صحيح. استخدم YYYY-MM-DD")

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'export_end_date')
def process_export_end_date(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    try:
        end_date = datetime.strptime(message.text, '%Y-%m-%d').date()
        start_date = state['export_start_date']
        
        if end_date < start_date:
            bot.send_message(message.chat.id, "❌ تاريخ النهاية يجب أن يكون بعد تاريخ البداية")
            return
        
        filename = reports.export_transactions_csv(start_date, end_date)
        
        bot.send_message(
            message.chat.id,
            f"✅ تم تصدير المعاملات للفترة ({start_date} إلى {end_date}) بنجاح!\n📁 اسم الملف: {filename}"
        )
        
        # إرسال الملف
        with open(filename, 'rb') as file:
            bot.send_document(message.chat.id, file)
        
        # حذف الملف بعد الإرسال
        os.remove(filename)
        
        user_states.pop(user_id, None)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ تنسيق التاريخ غير صحيح. استخدم YYYY-MM-DD")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ في التصدير: {str(e)}")

# ============================ معالجة استدعاءات الإدارة ============================
@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_rate_'))
def handle_edit_rate(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    currencies = call.data.split('_')[2:]
    from_currency, to_currency = currencies[0], currencies[1]
    
    current_rate = exchange_rates.get_rate(from_currency, to_currency)
    current_text = ""
    if current_rate:
        current_text = f"\n\nالأسعار الحالية:\nالشراء: {current_rate['buy_rate']}\nالبيع: {current_rate['sell_rate']}"
    
    bot.edit_message_text(
        f"⚙️ تعديل سعر {from_currency} → {to_currency}{current_text}\n\nأدخل سعر الشراء الجديد:",
        call.message.chat.id,
        call.message.message_id
    )
    
    user_states[call.from_user.id] = {
        'step': 'edit_buy_rate',
        'from_currency': from_currency,
        'to_currency': to_currency
    }

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'edit_buy_rate')
def process_buy_rate(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    try:
        buy_rate = float(message.text)
        user_states[user_id]['buy_rate'] = buy_rate
        user_states[user_id]['step'] = 'edit_sell_rate'
        
        bot.send_message(message.chat.id, "أدخل سعر البيع الجديد:")
    except ValueError:
        bot.send_message(message.chat.id, "❌ يرجى إدخال رقم صحيح")

@bot.message_handler(func=lambda message: message.from_user.id in user_states and user_states[message.from_user.id].get('step') == 'edit_sell_rate')
def process_sell_rate(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    try:
        sell_rate = float(message.text)
        
        success = exchange_rates.update_rate(
            state['from_currency'], 
            state['to_currency'], 
            state['buy_rate'], 
            sell_rate
        )
        
        if success:
            response = f"""✅ تم تحديث أسعار الصرف بنجاح!

💱 {state['from_currency']} → {state['to_currency']}:
🟢 الشراء: {state['buy_rate']}
🔴 البيع: {sell_rate}
📅 تاريخ التحديث: {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        else:
            response = "❌ فشل في تحديث الأسعار"
        
        bot.send_message(message.chat.id, response)
        user_states.pop(user_id, None)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ يرجى إدخال رقم صحيح")

@bot.callback_query_handler(func=lambda call: call.data == "show_rates_admin")
def handle_show_rates_admin(call):
    if not db.is_admin_logged_in(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ غير مصرح لك بهذا الإجراء")
        return
    
    rates = exchange_rates.get_all_rates()
    
    if rates:
        response = "⚙️ أسعار الصرف الحالية (إدارة):\n\n"
        for rate in rates:
            response += f"💱 {rate['from_currency']} → {rate['to_currency']}\n"
            response += f"   🟢 الشراء: {rate['buy_rate']}\n"
            response += f"   🔴 البيع: {rate['sell_rate']}\n"
            response += f"   📅 آخر تحديث: {rate['last_updated'][:16]}\n\n"
    else:
        response = "❌ لا توجد أسعار صرف متاحة"
    
    bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

# ============================ معالجة الرسائل غير المعروفة ============================
@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    # تجاهل الرسائل أثناء معالجة الحالات
    if message.from_user.id in user_states:
        return
    
    bot.send_message(
        message.chat.id,
        "❌ لم أفهم طلبك. استخدم الأزرار الموجودة في لوحة المفاتيح أو اكتب /start للبدء."
    )

# ============================ تشغيل البوت ============================
if __name__ == "__main__":
    print("🚀 بدء تشغيل بوت نوباتيا للخدمات التجارية...")
    print("✅ البوت يعمل الآن! اذهب إلى تلغرام وجرب الأوامر.")
    print("📊 سيتم إنشاء قاعدة البيانات تلقائياً عند التشغيل الأول")
    print("🔐 بيانات دخول الأدمن:")
    print(f"   👤 اسم المستخدم: {ADMIN_CREDENTIALS['username']}")
    print(f"   🔑 كلمة المرور: {ADMIN_CREDENTIALS['password']}")
    print("=" * 50)
    
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print(f"❌ خطأ في تشغيل البوت: {e}")
        print("🔄 إعادة المحاولة...")
        time.sleep(5)
        bot.polling(none_stop=True, interval=0, timeout=20)
