"""Arabcha Ustoz AI Telegram bot. Python 3.10+, python-telegram-bot 22.x.
Muhit o‘zgaruvchilari: BOT_TOKEN, ADMIN_ID (admin Telegram ID, vergul bilan bir nechta), BOT_DB_PATH.
"""
import os, json, urllib.request, urllib.error, asyncio, tempfile, sqlite3, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# BotFather bergan YANGI tokenni quyidagi qo‘shtirnoq ichiga kiriting.
BOT_TOKEN = "BU_YERGA_YANGI_BOTFATHER_TOKEN".strip()
if BOT_TOKEN == "BU_YERGA_YANGI_BOTFATHER_TOKEN":
    BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
TOTAL_LESSONS = 10000
DB_PATH = os.getenv('BOT_DB_PATH', 'arabcha_ustoz.db')
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', os.getenv('ADMIN_ID', '')).split(',') if x.strip().isdigit()}

# =====================================================================
#  TIZIM: BAZA, RO‘YXATDAN O‘TISH, ID, VIP OBUNA, HISOB, ADMIN PANEL
# =====================================================================
import csv, io, datetime

UZ_TZ = datetime.timezone(datetime.timedelta(hours=5))
FOREVER = 4102444800  # cheksiz VIP (2100-yil)
PAGE_SIZE = 10
REGIONS = ['Toshkent shahri', 'Toshkent viloyati', 'Andijon', 'Buxoro', 'Farg‘ona', 'Jizzax', 'Xorazm',
           'Namangan', 'Navoiy', 'Qashqadaryo', 'Qoraqalpog‘iston', 'Samarqand', 'Sirdaryo', 'Surxondaryo']
DEFAULT_SETTINGS = {
    'sub_enabled': '0',      # 1 = obuna majburiy, 0 = hamma bepul foydalanadi
    'vip_price': '30000',    # VIP narxi (so‘m)
    'vip_days': '30',        # VIP muddati (kun)
    'card_info': 'To‘lov rekvizitlari hali kiritilmagan. Admin bilan bog‘laning.',
    'maintenance': '0',      # 1 = texnik rejim
    'notify_new': '1',       # 1 = yangi foydalanuvchi haqida adminlarga xabar
    'welcome': '',           # bo‘sh bo‘lsa standart salomlashuv
    'force_enabled': '1',    # majburiy kanal obunasi (kanallar qo‘shilgan bo‘lsa ishlaydi)
}


# ---------------------------- BAZA ----------------------------
def dbq(sql, args=(), one=False):
    """SELECT: qatorlar ro‘yxati (yoki one=True bo‘lsa bitta qator/None)."""
    db = sqlite3.connect(DB_PATH)
    try:
        db.row_factory = sqlite3.Row
        rows = db.execute(sql, args).fetchall()
        db.commit()
        return (rows[0] if rows else None) if one else rows
    finally:
        db.close()

def dbx(sql, args=()):
    """INSERT/UPDATE/DELETE: ta’sirlangan qatorlar sonini qaytaradi."""
    db = sqlite3.connect(DB_PATH)
    try:
        cur = db.execute(sql, args); db.commit(); return cur.rowcount
    finally:
        db.close()

def dbi(sql, args=()):
    """INSERT: yangi qator raqamini qaytaradi."""
    db = sqlite3.connect(DB_PATH)
    try:
        cur = db.execute(sql, args); db.commit(); return cur.lastrowid
    finally:
        db.close()

def db_init():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at INTEGER)')
        cols = {r[1] for r in db.execute('PRAGMA table_info(users)')}
        for name, ddl in [('public_id', 'INTEGER'), ('full_name', 'TEXT'), ('age', 'INTEGER'), ('region', 'TEXT'),
                          ('registered', 'INTEGER DEFAULT 0'), ('reg_at', 'INTEGER DEFAULT 0'),
                          ('balance', 'INTEGER DEFAULT 0'), ('vip_until', 'INTEGER DEFAULT 0'),
                          ('banned', 'INTEGER DEFAULT 0'), ('last_seen', 'INTEGER DEFAULT 0')]:
            if name not in cols:
                db.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
        db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_public ON users(public_id)')
        db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, added_at INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, direction TEXT, text TEXT, ts INTEGER)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id, id)')
        db.execute('CREATE TABLE IF NOT EXISTS payments (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, status TEXT, file_id TEXT, created_at INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY AUTOINCREMENT, chat TEXT UNIQUE, title TEXT, link TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER, reason TEXT, by_admin INTEGER, ts INTEGER)')

def get_set(key):
    r = dbq('SELECT value FROM settings WHERE key=?', (key,), one=True)
    return r['value'] if r else DEFAULT_SETTINGS.get(key, '')

def set_set(key, value):
    dbx('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)', (key, str(value)))

def get_user(uid):
    return dbq('SELECT * FROM users WHERE user_id=?', (uid,), one=True)

def remember_user(update):
    user = update.effective_user
    if not user: return
    now = int(time.time())
    dbx('INSERT INTO users(user_id, username, first_name, joined_at, last_seen) VALUES(?,?,?,?,?) '
        'ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_seen=excluded.last_seen',
        (user.id, user.username or '', user.first_name or '', now, now))

def next_public_id():
    r = dbq('SELECT MAX(public_id) AS m FROM users', one=True)
    return max(1000, int(r['m'] or 0)) + 1

def log_msg(uid, direction, text):
    dbx('INSERT INTO messages(user_id,direction,text,ts) VALUES(?,?,?,?)', (uid, direction, (text or '')[:3000], int(time.time())))


# ---------------------------- YORDAMCHILAR ----------------------------
def fmt_ts(ts):
    if not ts: return '—'
    return datetime.datetime.fromtimestamp(int(ts), UZ_TZ).strftime('%d.%m.%Y %H:%M')

def money(n):
    return f'{int(n or 0):,}'.replace(',', ' ') + ' so‘m'

def is_vip(u):
    return bool(u) and int(u['vip_until'] or 0) > time.time()

def vip_text(u):
    if not is_vip(u): return 'yo‘q'
    if int(u['vip_until']) >= FOREVER - 86400: return 'faol, cheksiz ♾'
    return 'faol, ' + fmt_ts(u['vip_until']) + ' gacha'

def uname(u):
    return (u['full_name'] or u['first_name'] or 'Noma’lum')

def find_user(q):
    """ID (bot ID yoki Telegram ID) yoki @username bo‘yicha qidirish."""
    q = (q or '').strip()
    if q.startswith('@'):
        return dbq('SELECT * FROM users WHERE LOWER(username)=?', (q[1:].lower(),), one=True)
    if q.isascii() and q.isdigit():
        n = int(q)
        if len(q) <= 6:
            u = dbq('SELECT * FROM users WHERE public_id=?', (n,), one=True)
            if u: return u
        return get_user(n)
    return None

def add_balance(uid, amount, reason, by=0):
    dbx('UPDATE users SET balance=balance+? WHERE user_id=?', (amount, uid))
    dbx('INSERT INTO transactions(user_id,amount,reason,by_admin,ts) VALUES(?,?,?,?,?)', (uid, amount, reason, by, int(time.time())))

def spend_balance(uid, amount, reason, by=0):
    if dbx('UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?', (amount, uid, amount)) != 1:
        return False
    dbx('INSERT INTO transactions(user_id,amount,reason,by_admin,ts) VALUES(?,?,?,?,?)', (uid, -amount, reason, by, int(time.time())))
    return True

def give_vip(uid, days):
    """days=None bo‘lsa cheksiz. Mavjud VIP ustiga qo‘shiladi."""
    u = get_user(uid); now = int(time.time())
    until = FOREVER if days is None else min(FOREVER, max(now, int(u['vip_until'] or 0)) + int(days) * 86400)
    dbx('UPDATE users SET vip_until=? WHERE user_id=?', (until, uid))
    return until

def revoke_vip(uid):
    dbx('UPDATE users SET vip_until=0 WHERE user_id=?', (uid,))

def all_admin_ids():
    return set(ADMIN_IDS) | {r['user_id'] for r in dbq('SELECT user_id FROM admins')}

def is_admin_id(uid):
    return uid in ADMIN_IDS or dbq('SELECT 1 AS x FROM admins WHERE user_id=?', (uid,), one=True) is not None

def is_admin(update):
    return bool(update.effective_user and is_admin_id(update.effective_user.id))

async def notify(bot, uid, text, **kw):
    try:
        await bot.send_message(chat_id=uid, text=text, **kw); return True
    except Exception:
        return False

async def notify_admins(bot, text, **kw):
    for a in all_admin_ids():
        await notify(bot, a, text, **kw)

def btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)

async def show(q, text, kb=None):
    """Xabarni tahrirlaydi, bo‘lmasa yangisini yuboradi."""
    try:
        await q.edit_message_text(text[:4000], reply_markup=kb)
    except Exception:
        await q.message.reply_text(text[:4000], reply_markup=kb)


# ---------------------------- MENYU ----------------------------
def main_menu(update=None):
    rows = [list(r) for r in MAIN_MENU.inline_keyboard]
    rows.append([btn('👤 Profilim', 'profile'), btn('💎 VIP obuna', 'sub:info')])
    if update is not None and is_admin(update):
        rows.append([btn('🛠 Admin panel', 'adm:menu')])
    return InlineKeyboardMarkup(rows)


# ---------------------------- MAJBURIY OBUNA (kanallar) ----------------------------
FS_CACHE = {}   # foydalanuvchi -> oxirgi muvaffaqiyatli tekshiruv vaqti (5 daqiqa kesh)

def fs_channels():
    return dbq('SELECT * FROM channels ORDER BY id')

async def fs_missing(bot, uid):
    """Foydalanuvchi a’zo bo‘lmagan kanallar ro‘yxati (bo‘sh bo‘lsa hammasiga a’zo)."""
    if get_set('force_enabled') != '1': return []
    chans = fs_channels()
    if not chans or time.time() - FS_CACHE.get(uid, 0) < 300: return []
    missing = []
    for ch in chans:
        try:
            chat = int(ch['chat']) if ch['chat'].lstrip('-').isdigit() else ch['chat']
            cm = await bot.get_chat_member(chat_id=chat, user_id=uid)
            if not (cm.status in ('member', 'administrator', 'creator') or (cm.status == 'restricted' and getattr(cm, 'is_member', False))):
                missing.append(ch)
        except Exception as e:   # bot kanalda admin emas va hokazo: foydalanuvchini to‘smaymiz
            print('Majburiy obuna tekshiruvi xatosi:', ch['chat'], repr(e)[:120])
    if not missing: FS_CACHE[uid] = time.time()
    return missing

def fs_kb(missing):
    rows = [[InlineKeyboardButton('📢 ' + (ch['title'] or ch['chat']), url=ch['link'])] for ch in missing]
    rows.append([btn('✅ Tekshirish', 'fs:check')])
    return InlineKeyboardMarkup(rows)

FS_TEXT = '📢 Botdan foydalanish uchun quyidagi kanallarga a’zo bo‘ling, so‘ng “✅ Tekshirish” tugmasini bosing:'

async def fs_callback(update, context):
    q = update.callback_query; uid = update.effective_user.id
    FS_CACHE.pop(uid, None)
    if await fs_missing(context.bot, uid):
        await q.answer('❌ Hali hamma kanalga a’zo bo‘lmadingiz.', show_alert=True); return
    await q.answer('✅ Rahmat!')
    remember_user(update)
    if not get_user(uid)['registered']:
        await start_registration(update, context)
    else:
        await q.message.reply_text('✅ Obuna tasdiqlandi! Bo‘limni tanlang:', reply_markup=main_menu(update))

def fs_panel_text():
    chans = fs_channels()
    lines = ['📢 MAJBURIY OBUNA (kanallar)', '', 'Holat: ' + ('YOQILGAN ✅' if get_set('force_enabled') == '1' else 'o‘chiq ❌'), '']
    lines += [f'{i}. {c["title"]} — {c["chat"]}' for i, c in enumerate(chans, 1)] or ['Kanallar qo‘shilmagan.']
    lines += ['', 'ℹ️ Bot har bir kanalda ADMIN bo‘lishi shart, aks holda a’zolikni tekshira olmaydi.']
    return '\n'.join(lines)

def fs_panel_kb():
    rows = [[btn('🔁 Yoqish / o‘chirish', 'adm:fstoggle')], [btn('➕ Kanal qo‘shish', 'adm:fsadd')]]
    for c in fs_channels():
        rows.append([btn('🗑 ' + (c['title'] or c['chat'])[:30], f'adm:fsdel:{c["id"]}')])
    rows.append([btn('🔙 Admin panel', 'adm:menu')])
    return InlineKeyboardMarkup(rows)

async def fs_add_channel(update, context, msg):
    """Admin yuborgan @kanal / t.me havola / -100... ID ni tekshirib, ro‘yxatga qo‘shadi."""
    parts = msg.split(); raw = parts[0]; link = parts[1] if len(parts) > 1 else ''
    if raw.startswith(('https://t.me/', 'http://t.me/', 't.me/')):
        name = raw.rstrip('/').split('/')[-1]
        if name.startswith('+') or not name:
            return '❗ Yopiq kanal uchun havola emas, kanalning ID raqamini (-100...) yozing, undan keyin havolani. Masalan: -1001234567890 https://t.me/+abc'
        raw = '@' + name
    elif raw.lstrip('-').isdigit(): pass
    elif not raw.startswith('@'): raw = '@' + raw
    chat = int(raw) if raw.lstrip('-').isdigit() else raw
    try:
        info = await context.bot.get_chat(chat)
        me = await context.bot.get_chat_member(info.id, context.bot.id)
    except Exception:
        return '❌ Kanal topilmadi yoki bot kanalga qo‘shilmagan. Botni kanalga ADMIN qiling va qayta yuboring.'
    if me.status not in ('administrator', 'creator'):
        return '❌ Bot kanalda admin emas. Botni kanalga ADMIN qiling va qayta yuboring.'
    link = link or (f'https://t.me/{info.username}' if info.username else '')
    if not link:
        return '❗ Bu yopiq kanal: ID dan keyin taklif havolasini ham yozing. Masalan: -1001234567890 https://t.me/+abc'
    if dbx('INSERT OR IGNORE INTO channels(chat,title,link) VALUES(?,?,?)', (str(info.id), info.title or str(info.id), link)) == 0:
        return 'ℹ️ Bu kanal allaqachon qo‘shilgan.'
    return None


# ---------------------------- RUXSAT TEKSHIRUVI ----------------------------
async def basic_ok(update, context):
    """Ban, texnik rejim va ro‘yxatdan o‘tish tekshiruvi."""
    user = update.effective_user; msg = update.effective_message
    if not user or not msg: return False
    remember_user(update)
    u = get_user(user.id)
    adm = is_admin_id(user.id)
    if not adm:
        if u['banned']:
            await msg.reply_text('🚫 Siz botdan foydalanishdan chetlatilgansiz.'); return False
        if get_set('maintenance') == '1':
            await msg.reply_text('🛠 Botda texnik ishlar ketmoqda. Birozdan keyin qayta urinib ko‘ring.'); return False
        missing = await fs_missing(context.bot, user.id)
        if missing:
            await msg.reply_text(FS_TEXT, reply_markup=fs_kb(missing)); return False
    if not u['registered']:
        await start_registration(update, context); return False
    return True

async def access_ok(update, context):
    """basic_ok + obuna (VIP) tekshiruvi. False bo‘lsa, foydalanuvchiga javob allaqachon yuborilgan."""
    if not await basic_ok(update, context): return False
    uid = update.effective_user.id
    if is_admin_id(uid): return True
    if get_set('sub_enabled') == '1' and not is_vip(get_user(uid)):
        await send_sub_offer(update, context); return False
    return True

def guarded(fn):
    async def wrapper(update, context):
        if not await access_ok(update, context): return
        await fn(update, context)
    return wrapper


# ---------------------------- RO‘YXATDAN O‘TISH ----------------------------
def region_kb():
    rows, row = [], []
    for i, r in enumerate(REGIONS):
        row.append(btn(r, f'reg:r:{i}'))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn('🌍 Boshqa joy', 'reg:other')])
    return InlineKeyboardMarkup(rows)

async def start_registration(update, context):
    context.user_data['mode'] = 'reg_name'
    context.user_data.pop('reg_name', None); context.user_data.pop('reg_age', None)
    await update.effective_message.reply_text('👋 Assalomu alaykum! Botdan foydalanish uchun qisqa ro‘yxatdan o‘ting.\n\n📝 Ismingizni yozing:')

async def registration_text(update, context, mode, msg):
    m = update.effective_message
    if mode == 'reg_name':
        if not 2 <= len(msg) <= 40:
            await m.reply_text('❗ Ism 2 dan 40 gacha belgidan iborat bo‘lsin. Qaytadan yozing:'); return
        context.user_data['reg_name'] = msg; context.user_data['mode'] = 'reg_age'
        await m.reply_text('🎂 Yoshingizni raqam bilan yozing (masalan: 18):')
    elif mode == 'reg_age':
        if not (msg.isascii() and msg.isdigit() and 5 <= int(msg) <= 99):
            await m.reply_text('❗ Yoshni 5 dan 99 gacha raqam bilan yozing:'); return
        context.user_data['reg_age'] = int(msg); context.user_data['mode'] = 'reg_region'
        await m.reply_text('📍 Qayerdansiz? Hududingizni tanlang:', reply_markup=region_kb())
    elif mode == 'reg_region':
        await m.reply_text('📍 Iltimos, hududni pastdagi tugmalardan tanlang:', reply_markup=region_kb())
    elif mode == 'reg_region_text':
        if not 2 <= len(msg) <= 40:
            await m.reply_text('❗ Joy nomini 2 dan 40 gacha belgi bilan yozing:'); return
        await finish_registration(update, context, msg)

async def finish_registration(update, context, region):
    uid = update.effective_user.id
    name = context.user_data.get('reg_name'); age = context.user_data.get('reg_age')
    if not name or not age:
        await start_registration(update, context); return
    u = get_user(uid)
    first_time = not u['registered']
    pid = u['public_id'] or next_public_id()
    dbx('UPDATE users SET full_name=?, age=?, region=?, registered=1, public_id=?, reg_at=CASE WHEN reg_at>0 THEN reg_at ELSE ? END WHERE user_id=?',
        (name, age, region, pid, int(time.time()), uid))
    for k in ('reg_name', 'reg_age'): context.user_data.pop(k, None)
    context.user_data['mode'] = None
    await update.effective_message.reply_text(
        f'✅ Ro‘yxatdan o‘tdingiz!\n\n🆔 Sizning ID raqamingiz: {pid}\n👤 Ism: {name}\n🎂 Yosh: {age}\n📍 Hudud: {region}\n\n'
        'ℹ️ Botga yozgan xabarlaringiz administrator tomonidan ko‘rilishi mumkin.', reply_markup=main_menu(update))
    if first_time and get_set('notify_new') == '1':
        un = update.effective_user.username
        await notify_admins(context.bot, f'🆕 Yangi foydalanuvchi\n🆔 {pid} · {name}, {age} yosh\n📍 {region}\n🔗 {"@" + un if un else "username yo‘q"}\n📱 Telegram ID: {uid}',
                            reply_markup=InlineKeyboardMarkup([[btn('👤 Kartani ochish', f'adm:u:{uid}')]]))

async def reg_callback(update, context):
    q = update.callback_query; await q.answer(); data = q.data or ''
    if data == 'reg:redo':
        await start_registration(update, context); return
    if 'reg_name' not in context.user_data or 'reg_age' not in context.user_data:
        await start_registration(update, context); return
    if data == 'reg:other':
        context.user_data['mode'] = 'reg_region_text'
        await q.message.reply_text('🌍 Shahar yoki mamlakat nomini yozing:'); return
    if data.startswith('reg:r:'):
        i = int(data.split(':')[2])
        if 0 <= i < len(REGIONS):
            await finish_registration(update, context, REGIONS[i])


# ---------------------------- PROFIL, VIP OBUNA, HISOB ----------------------------
def profile_text(u):
    return (f'👤 PROFIL\n\n🆔 ID: {u["public_id"] or "—"}\n👤 Ism: {u["full_name"] or "—"}\n🎂 Yosh: {u["age"] or "—"}\n'
            f'📍 Hudud: {u["region"] or "—"}\n💰 Hisob: {money(u["balance"])}\n💎 VIP: {vip_text(u)}')

def profile_kb():
    return InlineKeyboardMarkup([
        [btn('💎 VIP obuna', 'sub:info'), btn('💳 Hisobni to‘ldirish', 'top:start')],
        [btn('✏️ Ma’lumotni o‘zgartirish', 'reg:redo')],
        [btn('🏠 Bosh menyu', 'home')]])

async def profile_cmd(update, context):
    if not await basic_ok(update, context): return
    await update.effective_message.reply_text(profile_text(get_user(update.effective_user.id)), reply_markup=profile_kb())

async def profile_callback(update, context):
    q = update.callback_query; await q.answer()
    if not await basic_ok(update, context): return
    await q.message.reply_text(profile_text(get_user(update.effective_user.id)), reply_markup=profile_kb())

async def id_cmd(update, context):
    await update.effective_message.reply_text(f'📱 Sizning Telegram ID: {update.effective_user.id}')

def sub_text(u, locked=False):
    price = int(get_set('vip_price') or 0); days = int(get_set('vip_days') or 30)
    head = '🔒 Botdan foydalanish uchun VIP obuna kerak.\n\n' if locked else '💎 VIP OBUNA\n\n'
    return (head + f'💎 VIP narxi: {money(price)} / {days} kun\n💰 Hisobingiz: {money(u["balance"])}\n⭐ Holatingiz: {vip_text(u)}')

def sub_kb():
    return InlineKeyboardMarkup([
        [btn('💎 VIP sotib olish', 'sub:buy')],
        [btn('💳 Hisobni to‘ldirish', 'top:start'), btn('👤 Profil', 'profile')]])

async def send_sub_offer(update, context):
    await update.effective_message.reply_text(sub_text(get_user(update.effective_user.id), locked=True), reply_markup=sub_kb())

async def sub_callback(update, context):
    q = update.callback_query; await q.answer(); data = q.data or ''
    if not await basic_ok(update, context): return
    uid = update.effective_user.id; u = get_user(uid)
    price = int(get_set('vip_price') or 0); days = int(get_set('vip_days') or 30)
    if data == 'sub:info':
        await q.message.reply_text(sub_text(u), reply_markup=sub_kb())
    elif data == 'sub:buy':
        if u['balance'] < price:
            await q.message.reply_text(f'❗ Hisobingizda mablag‘ yetarli emas.\n💎 Narx: {money(price)}\n💰 Hisobingiz: {money(u["balance"])}\n\nAvval hisobni to‘ldiring.',
                                       reply_markup=InlineKeyboardMarkup([[btn('💳 Hisobni to‘ldirish', 'top:start')]])); return
        await q.message.reply_text(f'💎 VIP {days} kunga — {money(price)}\n💰 Hisobingiz: {money(u["balance"])}\n\nSotib olishni tasdiqlaysizmi?',
                                   reply_markup=InlineKeyboardMarkup([[btn('✅ Ha, sotib olish', 'sub:yes'), btn('❌ Bekor', 'home')]]))
    elif data == 'sub:yes':
        if price > 0 and not spend_balance(uid, price, f'VIP {days} kun'):
            await q.message.reply_text('❗ Hisobingizda mablag‘ yetarli emas.'); return
        until = give_vip(uid, days)
        await q.message.reply_text(f'🎉 VIP faollashdi! {fmt_ts(until)} gacha.', reply_markup=main_menu(update))
        await notify_admins(context.bot, f'💎 VIP sotib olindi: ID {u["public_id"]} · {uname(u)} · {money(price)}')

def top_cancel_kb():
    return InlineKeyboardMarkup([[btn('❌ Bekor qilish', 'top:cancel')]])

async def topup_callback(update, context):
    q = update.callback_query; await q.answer()
    if (q.data or '') == 'top:cancel':
        context.user_data['mode'] = None; context.user_data.pop('top_amount', None)
        await q.message.reply_text('❌ Bekor qilindi.', reply_markup=main_menu(update)); return
    if not await basic_ok(update, context): return
    context.user_data['mode'] = 'top_amount'; context.user_data['top_ts'] = time.time()
    await q.message.reply_text('💳 Hisobni to‘ldirish\n\nQancha so‘m kiritmoqchisiz? Faqat raqam yozing (kamida 1000).', reply_markup=top_cancel_kb())

async def topup_text(update, context, mode, msg):
    """True — xabar to‘lov jarayonida ishlatildi; False — jarayon bekor bo‘ldi, xabar oddiy tartibda ishlanadi."""
    m = update.effective_message
    expired = time.time() - context.user_data.get('top_ts', 0) > 600
    if mode == 'top_amount' and not expired and msg.isascii() and msg.isdigit():
        if not 1000 <= int(msg) <= 100_000_000:
            await m.reply_text('❗ Summa 1000 dan 100 000 000 gacha bo‘lsin:', reply_markup=top_cancel_kb()); return True
        context.user_data['top_amount'] = int(msg); context.user_data['mode'] = 'top_receipt'; context.user_data['top_ts'] = time.time()
        await m.reply_text(f'💳 To‘lov rekvizitlari:\n\n{get_set("card_info")}\n\n💰 Summa: {money(int(msg))}\n\n'
                           'To‘lovni amalga oshirib, CHEK RASMINI (skrinshot) shu yerga yuboring.', reply_markup=top_cancel_kb())
        return True
    context.user_data['mode'] = None; context.user_data.pop('top_amount', None)
    if not expired:
        await m.reply_text('ℹ️ To‘lov jarayoni bekor qilindi.')
    return False

async def photo_message(update, context):
    if not await basic_ok(update, context): return
    m = update.effective_message; uid = update.effective_user.id
    if context.user_data.get('mode') != 'top_receipt' or not context.user_data.get('top_amount') or time.time() - context.user_data.get('top_ts', 0) > 600:
        await m.reply_text('Hozircha faqat matn qabul qilinadi. Menyudan foydalaning.', reply_markup=main_menu(update)); return
    pending = dbq('SELECT COUNT(*) AS c FROM payments WHERE user_id=? AND status="pending"', (uid,), one=True)['c']
    if pending >= 3:
        await m.reply_text('⏳ Sizning 3 ta so‘rovingiz ko‘rib chiqilmoqda. Iltimos, kuting.'); return
    amount = context.user_data.pop('top_amount'); context.user_data['mode'] = None
    file_id = m.photo[-1].file_id
    pay_id = dbi('INSERT INTO payments(user_id,amount,status,file_id,created_at) VALUES(?,?,?,?,?)', (uid, amount, 'pending', file_id, int(time.time())))
    await m.reply_text(f'✅ So‘rov #{pay_id} yuborildi. Admin tasdiqlagach hisobingizga {money(amount)} tushadi.', reply_markup=main_menu(update))
    u = get_user(uid)
    kb = InlineKeyboardMarkup([[btn('✅ Tasdiqlash', f'adm:pok:{pay_id}'), btn('❌ Rad etish', f'adm:pno:{pay_id}')]])
    cap = f'🧾 To‘lov so‘rovi #{pay_id}\n🆔 {u["public_id"]} · {uname(u)}\n💰 {money(amount)}'
    for a in all_admin_ids():
        try: await context.bot.send_photo(chat_id=a, photo=file_id, caption=cap, reply_markup=kb)
        except Exception: pass


# ---------------------------- ADMIN: KO‘RINISHLAR ----------------------------
def admin_summary():
    now = int(time.time())
    total = dbq('SELECT COUNT(*) AS c FROM users', one=True)['c']
    vip = dbq('SELECT COUNT(*) AS c FROM users WHERE vip_until>?', (now,), one=True)['c']
    sub = 'YOQILGAN ✅' if get_set('sub_enabled') == '1' else 'o‘chiq ❌'
    return f'👥 Foydalanuvchilar: {total} · ⭐ VIP: {vip}\n💎 VIP obuna talabi: {sub}\n📢 Majburiy kanallar: {len(fs_channels())} ta' + (' (yoqilgan)' if get_set('force_enabled') == '1' else ' (o‘chiq)')

def admin_menu_kb():
    sub_on = get_set('sub_enabled') == '1'
    maint = get_set('maintenance') == '1'
    notif = get_set('notify_new') == '1'
    pend = dbq('SELECT COUNT(*) AS c FROM payments WHERE status="pending"', one=True)['c']
    return InlineKeyboardMarkup([
        [btn('📊 Statistika', 'adm:stats'), btn('👥 Foydalanuvchilar', 'adm:users:all:0')],
        [btn('🔎 ID bo‘yicha topish', 'adm:find'), btn('💬 Lichkani ko‘rish', 'adm:chatask')],
        [btn('💎 VIP talabi: ' + ('✅ yoqilgan' if sub_on else '❌ o‘chiq'), 'adm:subtoggle'), btn('💵 VIP narxi', 'adm:price')],
        [btn('⭐ VIP berish', 'adm:vipask'), btn('⏱ VIP muddati', 'adm:days')],
        [btn('💸 Pul o‘tkazish', 'adm:transfer'), btn(f'🧾 To‘lovlar ({pend})', 'adm:pays')],
        [btn('📣 Xabar yuborish', 'adm:broadcast'), btn('💳 Karta ma’lumoti', 'adm:card')],
        [btn('📢 Majburiy obuna (kanallar)', 'adm:fs')],
        [btn('👑 Adminlar', 'adm:admins'), btn('🚫 Banlilar', 'adm:users:banned:0')],
        [btn('🛠 Texnik rejim: ' + ('ON' if maint else 'off'), 'adm:maint'), btn('🔔 Yangi user xabari: ' + ('ON' if notif else 'off'), 'adm:notif')],
        [btn('📝 Salomlashuv matni', 'adm:welcome'), btn('📄 CSV eksport', 'adm:csv')],
        [btn('💾 Baza zaxirasi', 'adm:backup'), btn('📥 Bazani tiklash', 'adm:restore')],
        [btn('🧭 Bo‘limlar', 'adm:sections'), btn('📚 Darslar', 'adm:lessons')],
        [btn('🏠 Bosh menyu', 'home')],
    ])

def stats_text():
    now = int(time.time())
    day_start = int(datetime.datetime.now(UZ_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    c = lambda sql, a=(): dbq(sql, a, one=True)['c']
    return ('📊 BOT STATISTIKASI\n\n'
            f'👥 Jami foydalanuvchi: {c("SELECT COUNT(*) AS c FROM users")}\n'
            f'✅ Ro‘yxatdan o‘tgan: {c("SELECT COUNT(*) AS c FROM users WHERE registered=1")}\n'
            f'🆕 Bugun qo‘shilgan: {c("SELECT COUNT(*) AS c FROM users WHERE joined_at>=?", (day_start,))}\n'
            f'🟢 Oxirgi 24 soatda faol: {c("SELECT COUNT(*) AS c FROM users WHERE last_seen>=?", (now - 86400,))}\n'
            f'⭐ VIP: {c("SELECT COUNT(*) AS c FROM users WHERE vip_until>?", (now,))}\n'
            f'🚫 Banlangan: {c("SELECT COUNT(*) AS c FROM users WHERE banned=1")}\n'
            f'💰 Foydalanuvchilar hisobi jami: {money(dbq("SELECT COALESCE(SUM(balance),0) AS s FROM users", one=True)["s"])}\n'
            f'🧾 Kutilayotgan to‘lovlar: {c("SELECT COUNT(*) AS c FROM payments WHERE status=\'pending\'")}\n'
            f'💬 Saqlangan xabarlar: {c("SELECT COUNT(*) AS c FROM messages")}\n'
            f'📚 Darslar: {TOTAL_LESSONS}')

def users_view(flt, page):
    now = int(time.time())
    where = {'all': '1=1', 'vip': f'vip_until>{now}', 'banned': 'banned=1', 'new': 'registered=0'}.get(flt, '1=1')
    total = dbq(f'SELECT COUNT(*) AS c FROM users WHERE {where}', one=True)['c']
    rows = dbq(f'SELECT * FROM users WHERE {where} ORDER BY joined_at DESC LIMIT ? OFFSET ?', (PAGE_SIZE, page * PAGE_SIZE))
    kb = []
    for u in rows:
        label = f"{u['public_id'] or '—'} · {uname(u)[:20]}{' ⭐' if is_vip(u) else ''}{' 🚫' if u['banned'] else ''}"
        kb.append([btn(label, f"adm:u:{u['user_id']}")])
    nav = []
    if page > 0: nav.append(btn('⬅️ Oldingi', f'adm:users:{flt}:{page - 1}'))
    if (page + 1) * PAGE_SIZE < total: nav.append(btn('Keyingi ➡️', f'adm:users:{flt}:{page + 1}'))
    if nav: kb.append(nav)
    kb.append([btn('Hammasi', 'adm:users:all:0'), btn('⭐ VIP', 'adm:users:vip:0'), btn('🚫 Ban', 'adm:users:banned:0'), btn('🆕 Yangi', 'adm:users:new:0')])
    kb.append([btn('🔙 Admin panel', 'adm:menu')])
    names = {'all': 'hammasi', 'vip': 'VIP', 'banned': 'banlangan', 'new': 'ro‘yxatdan o‘tmagan'}
    pages = max(1, -(-total // PAGE_SIZE))
    return f'👥 FOYDALANUVCHILAR ({names.get(flt, flt)})\nJami: {total} · Sahifa {page + 1}/{pages}', InlineKeyboardMarkup(kb)

def card_text(u):
    un = u['username']
    return ('👤 FOYDALANUVCHI KARTASI\n\n'
            f'🆔 ID: {u["public_id"] or "— (ro‘yxatdan o‘tmagan)"}\n📱 Telegram ID: {u["user_id"]}\n'
            f'👤 Ism: {u["full_name"] or u["first_name"] or "—"}\n🔗 Username: {"@" + un if un else "—"}\n'
            f'🎂 Yosh: {u["age"] or "—"}\n📍 Hudud: {u["region"] or "—"}\n'
            f'📅 Qo‘shilgan: {fmt_ts(u["joined_at"])}\n🕒 Oxirgi faollik: {fmt_ts(u["last_seen"])}\n'
            f'💰 Hisob: {money(u["balance"])}\n⭐ VIP: {vip_text(u)}\n🚫 Ban: {"ha" if u["banned"] else "yo‘q"}')

def card_kb(u):
    uid = u['user_id']
    return InlineKeyboardMarkup([
        [btn('💬 Lichka', f'adm:chat:{uid}:0'), btn('✉️ Xabar yozish', f'adm:msg:{uid}')],
        [btn('⭐ 7 kun', f'adm:vip:{uid}:7'), btn('⭐ 30 kun', f'adm:vip:{uid}:30'), btn('⭐ 90 kun', f'adm:vip:{uid}:90')],
        [btn('⭐ 365 kun', f'adm:vip:{uid}:365'), btn('♾ Cheksiz', f'adm:vip:{uid}:0'), btn('✏️ Boshqa', f'adm:vipc:{uid}')],
        [btn('❌ VIPni olish', f'adm:unvip:{uid}')],
        [btn('➕ Pul qo‘shish', f'adm:add:{uid}'), btn('➖ Pul ayirish', f'adm:minus:{uid}')],
        [btn('✅ Bandan chiqarish' if u['banned'] else '🚫 Ban qilish', f'adm:ban:{uid}')],
        [btn('🔙 Admin panel', 'adm:menu')]])

def chat_view(uid, offset):
    u = get_user(uid)
    rows = dbq('SELECT * FROM messages WHERE user_id=? ORDER BY id DESC LIMIT 10 OFFSET ?', (uid, offset))
    head = f'💬 LICHKA — {uname(u)} (ID {u["public_id"] or "—"})\n'
    icons = {'in': '👤', 'out': '🤖', 'adm': '👮'}
    body = '\nXabarlar yo‘q.' if not rows else ''
    for r in reversed(rows):
        t = (r['text'] or '').replace('\n', ' ')
        body += f"\n{icons.get(r['direction'], '•')} {fmt_ts(r['ts'])}\n{t[:250]}\n"
    kb = []
    nav = []
    if len(rows) == 10: nav.append(btn('⬅️ Eskiroq', f'adm:chat:{uid}:{offset + 10}'))
    if offset > 0: nav.append(btn('Yangiroq ➡️', f'adm:chat:{uid}:{max(0, offset - 10)}'))
    if nav: kb.append(nav)
    kb.append([btn('✉️ Xabar yozish', f'adm:msg:{uid}'), btn('👤 Karta', f'adm:u:{uid}')])
    return (head + body)[:4000], InlineKeyboardMarkup(kb)

async def send_card(message, uid):
    u = get_user(uid)
    if not u:
        await message.reply_text('❌ Foydalanuvchi topilmadi.'); return
    await message.reply_text(card_text(u), reply_markup=card_kb(u))

def admin_back():
    return InlineKeyboardMarkup([[btn('🔙 Admin panel', 'adm:menu')]])

def ask_user_prompt(action_text):
    return action_text + '\n\nFoydalanuvchi ID sini (bot ID yoki Telegram ID) yoki @username ni yuboring.\nBekor qilish: /admin'


# ---------------------------- ADMIN: BUYRUQ VA TUGMALAR ----------------------------
async def admin_cmd(update, context):
    remember_user(update)
    if not is_admin(update):
        await update.effective_message.reply_text(
            f'⛔ Bu panel faqat bot administratori uchun.\n\n📱 Sizning Telegram ID: {update.effective_user.id}\n'
            'Agar siz egasi bo‘lsangiz, shu raqamni ADMIN_ID muhit o‘zgaruvchisiga yozing.')
        return
    context.user_data['mode'] = None
    await update.effective_message.reply_text('🛠 ADMIN PANEL\n\n' + admin_summary(), reply_markup=admin_menu_kb())

async def run_broadcast(bot, admin_chat, text, target):
    now = int(time.time())
    if target == 'vip': rows = dbq('SELECT user_id FROM users WHERE vip_until>? AND banned=0', (now,))
    elif target == 'free': rows = dbq('SELECT user_id FROM users WHERE vip_until<=? AND banned=0', (now,))
    else: rows = dbq('SELECT user_id FROM users WHERE banned=0')
    ok = failed = 0
    for r in rows:
        if await notify(bot, r['user_id'], text): ok += 1
        else: failed += 1
        await asyncio.sleep(0.05)
    await notify(bot, admin_chat, f'📣 Xabar yuborish tugadi.\n✅ Yuborildi: {ok}\n⚠️ Yuborilmadi: {failed}', reply_markup=admin_back())

def set_mode(context, mode, **ctx):
    context.user_data['mode'] = mode
    context.user_data['adm_ctx'] = ctx

async def adm_callback(update, context):
    q = update.callback_query; await q.answer()
    if not is_admin(update):
        await q.message.reply_text('⛔ Ruxsat yo‘q.'); return
    parts = (q.data or '').split(':')
    act = parts[1] if len(parts) > 1 else 'menu'
    arg = parts[2] if len(parts) > 2 else ''
    arg2 = parts[3] if len(parts) > 3 else ''
    m = q.message; adm_id = update.effective_user.id
    uid = int(arg) if arg.lstrip('-').isdigit() else None
    context.user_data['mode'] = None if act in ('menu', 'stats', 'users', 'u') else context.user_data.get('mode')

    if act == 'menu':
        await show(q, '🛠 ADMIN PANEL\n\n' + admin_summary(), admin_menu_kb())
    elif act == 'stats':
        await show(q, stats_text(), admin_back())
    elif act == 'users':
        text, kb = users_view(arg or 'all', int(arg2 or 0)); await show(q, text, kb)
    elif act == 'u' and uid:
        await send_card(m, uid)
    elif act == 'find':
        set_mode(context, 'adm_find'); await m.reply_text(ask_user_prompt('🔎 Foydalanuvchini ID orqali topish.'))
    elif act == 'vipask':
        set_mode(context, 'adm_find'); await m.reply_text(ask_user_prompt('⭐ VIP berish: avval foydalanuvchini toping.'))
    elif act == 'chatask':
        set_mode(context, 'adm_chat_id'); await m.reply_text(ask_user_prompt('💬 Foydalanuvchi lichkasini ko‘rish.'))
    elif act == 'chat' and uid:
        text, kb = chat_view(uid, int(arg2 or 0)); await show(q, text, kb)
    elif act == 'msg' and uid:
        set_mode(context, 'adm_msg', uid=uid); await m.reply_text('✉️ Foydalanuvchiga yuboriladigan xabar matnini yozing.\nBekor qilish: /admin')
    elif act == 'vip' and uid:
        days = int(arg2) if arg2.isdigit() else 30
        until = give_vip(uid, None if days == 0 else days)
        u = get_user(uid)
        await notify(context.bot, uid, f'🎉 Sizga VIP obuna berildi!\n⭐ {vip_text(u)}')
        await m.reply_text(f'✅ VIP berildi: {uname(u)} — {vip_text(u)}'); await send_card(m, uid)
    elif act == 'vipc' and uid:
        set_mode(context, 'adm_vip_days', uid=uid); await m.reply_text('⏱ Necha kunga VIP berilsin? (1–3650, faqat raqam)')
    elif act == 'unvip' and uid:
        revoke_vip(uid); await notify(context.bot, uid, 'ℹ️ VIP obunangiz administrator tomonidan bekor qilindi.')
        await m.reply_text('❌ VIP olib tashlandi.'); await send_card(m, uid)
    elif act == 'add' and uid:
        set_mode(context, 'adm_add', uid=uid); await m.reply_text('➕ Hisobga qo‘shiladigan summani yozing (so‘m):')
    elif act == 'minus' and uid:
        set_mode(context, 'adm_minus', uid=uid); await m.reply_text('➖ Hisobdan ayiriladigan summani yozing (so‘m):')
    elif act == 'ban' and uid:
        if is_admin_id(uid):
            await m.reply_text('⛔ Administratorni ban qilib bo‘lmaydi.'); return
        u = get_user(uid); new = 0 if u['banned'] else 1
        dbx('UPDATE users SET banned=? WHERE user_id=?', (new, uid))
        await notify(context.bot, uid, '🚫 Siz botdan chetlatildingiz.' if new else '✅ Siz bandan chiqarildingiz. /start')
        await send_card(m, uid)
    elif act == 'transfer':
        set_mode(context, 'adm_tr_id'); await m.reply_text(ask_user_prompt('💸 Pul o‘tkazish: kimga o‘tkazasiz?'))
    elif act == 'subtoggle':
        set_set('sub_enabled', '0' if get_set('sub_enabled') == '1' else '1')
        await show(q, '🛠 ADMIN PANEL\n\n' + admin_summary() + ('\n\n✅ Obuna YOQILDI: VIP bo‘lmaganlardan obuna so‘raladi.' if get_set('sub_enabled') == '1' else '\n\n❌ Obuna O‘CHIRILDI: hamma bepul foydalanadi.'), admin_menu_kb())
    elif act == 'maint':
        set_set('maintenance', '0' if get_set('maintenance') == '1' else '1')
        await show(q, '🛠 ADMIN PANEL\n\n' + admin_summary(), admin_menu_kb())
    elif act == 'notif':
        set_set('notify_new', '0' if get_set('notify_new') == '1' else '1')
        await show(q, '🛠 ADMIN PANEL\n\n' + admin_summary(), admin_menu_kb())
    elif act == 'price':
        set_mode(context, 'adm_price'); await m.reply_text(f'💵 Hozirgi VIP narxi: {money(int(get_set("vip_price")))}\nYangi narxni yozing (so‘m, 0 = bepul):')
    elif act == 'days':
        set_mode(context, 'adm_days'); await m.reply_text(f'⏱ Hozirgi VIP muddati: {get_set("vip_days")} kun\nYangi muddatni yozing (kun):')
    elif act == 'card':
        set_mode(context, 'adm_card'); await m.reply_text(f'💳 Hozirgi ma’lumot:\n{get_set("card_info")}\n\nYangi to‘lov rekvizitlarini yozing (karta raqami, egasi):')
    elif act == 'welcome':
        set_mode(context, 'adm_welcome'); await m.reply_text('📝 Yangi salomlashuv matnini yozing. Standartga qaytarish uchun “-” yozing.')
    elif act == 'broadcast':
        await show(q, '📣 Kimlarga xabar yuboramiz?', InlineKeyboardMarkup([
            [btn('👥 Hammaga', 'adm:bc:all')], [btn('⭐ Faqat VIP', 'adm:bc:vip')], [btn('🆓 VIP bo‘lmaganlarga', 'adm:bc:free')], [btn('🔙 Admin panel', 'adm:menu')]]))
    elif act == 'bc':
        set_mode(context, 'admin_broadcast', target=arg or 'all'); await m.reply_text('📣 Yuboriladigan xabar matnini yozing.\nBekor qilish: /admin')
    elif act == 'pays':
        rows = dbq('SELECT * FROM payments WHERE status="pending" ORDER BY id LIMIT 10')
        if not rows:
            await show(q, '🧾 Kutilayotgan to‘lov so‘rovlari yo‘q.', admin_back()); return
        for p in rows:
            u = get_user(p['user_id'])
            kb = InlineKeyboardMarkup([[btn('✅ Tasdiqlash', f'adm:pok:{p["id"]}'), btn('❌ Rad etish', f'adm:pno:{p["id"]}')]])
            cap = f'🧾 So‘rov #{p["id"]}\n🆔 {u["public_id"]} · {uname(u)}\n💰 {money(p["amount"])}\n🕒 {fmt_ts(p["created_at"])}'
            try: await context.bot.send_photo(chat_id=m.chat_id, photo=p['file_id'], caption=cap, reply_markup=kb)
            except Exception: await m.reply_text(cap, reply_markup=kb)
    elif act in ('pok', 'pno') and uid:
        p = dbq('SELECT * FROM payments WHERE id=?', (uid,), one=True)
        new = 'approved' if act == 'pok' else 'rejected'
        if not p or dbx('UPDATE payments SET status=? WHERE id=? AND status="pending"', (new, uid)) != 1:
            await m.reply_text('ℹ️ Bu so‘rov allaqachon ko‘rib chiqilgan.'); return
        try: await q.edit_message_reply_markup(reply_markup=None)
        except Exception: pass
        if act == 'pok':
            add_balance(p['user_id'], p['amount'], f'To‘ldirish #{p["id"]}', adm_id)
            await notify(context.bot, p['user_id'], f'✅ To‘lovingiz tasdiqlandi! Hisobingizga {money(p["amount"])} qo‘shildi.')
            await m.reply_text(f'✅ #{p["id"]} tasdiqlandi: {money(p["amount"])}')
        else:
            await notify(context.bot, p['user_id'], f'❌ To‘lov so‘rovingiz #{p["id"]} rad etildi. Savol bo‘lsa, admin bilan bog‘laning.')
            await m.reply_text(f'❌ #{p["id"]} rad etildi.')
    elif act == 'admins':
        lines = ['👑 ADMINLAR\n', 'Asosiy (ADMIN_ID): ' + (', '.join(map(str, sorted(ADMIN_IDS))) or '—')]
        kb = []
        for r in dbq('SELECT user_id FROM admins'):
            lines.append(f'• {r["user_id"]}')
            kb.append([btn(f'🗑 {r["user_id"]} ni o‘chirish', f'adm:deladmin:{r["user_id"]}')])
        if adm_id in ADMIN_IDS: kb.append([btn('➕ Admin qo‘shish', 'adm:addadmin')])
        else: lines.append('\nℹ️ Admin qo‘shish/o‘chirish faqat asosiy adminga ruxsat.')
        kb.append([btn('🔙 Admin panel', 'adm:menu')])
        await show(q, '\n'.join(lines), InlineKeyboardMarkup(kb))
    elif act == 'addadmin':
        if adm_id not in ADMIN_IDS: await m.reply_text('⛔ Faqat asosiy admin qo‘sha oladi.'); return
        set_mode(context, 'adm_addadmin'); await m.reply_text('👑 Yangi adminning Telegram ID raqamini yozing (u /id buyrug‘i bilan bilib oladi):')
    elif act == 'deladmin' and uid:
        if adm_id not in ADMIN_IDS: await m.reply_text('⛔ Faqat asosiy admin o‘chira oladi.'); return
        dbx('DELETE FROM admins WHERE user_id=?', (uid,)); await m.reply_text('🗑 Admin o‘chirildi.')
    elif act == 'fs':
        await show(q, fs_panel_text(), fs_panel_kb())
    elif act == 'fstoggle':
        set_set('force_enabled', '0' if get_set('force_enabled') == '1' else '1')
        await show(q, fs_panel_text(), fs_panel_kb())
    elif act == 'fsadd':
        set_mode(context, 'adm_fs_add')
        await m.reply_text('📢 Kanalni yuboring: @kanal_nomi yoki t.me havolasi.\nYopiq kanal bo‘lsa: -1001234567890 https://t.me/+taklif_havolasi\n\n⚠️ Avval botni kanalga ADMIN qiling.\nBekor qilish: /admin')
    elif act == 'fsdel' and uid:
        dbx('DELETE FROM channels WHERE id=?', (uid,)); FS_CACHE.clear()
        await show(q, fs_panel_text(), fs_panel_kb())
    elif act == 'restore':
        set_mode(context, 'adm_restore')
        await m.reply_text('📥 BAZANI TIKLASH\n\nFaylni shu yerga yuboring:\n• .db — eski bot bazasi yoki “💾 Baza zaxirasi” fayli\n• .csv / .txt — Telegram ID lar ro‘yxati\n\nMavjud foydalanuvchilar o‘chirilmaydi, faqat yetishmaganlari qo‘shiladi.\nBekor qilish: /admin')
    elif act == 'csv':
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(['bot_id', 'telegram_id', 'username', 'ism', 'yosh', 'hudud', 'balans', 'vip_gacha', 'ban', 'qoshilgan'])
        for u in dbq('SELECT * FROM users ORDER BY public_id'):
            w.writerow([u['public_id'], u['user_id'], u['username'], u['full_name'] or u['first_name'], u['age'], u['region'], u['balance'], fmt_ts(u['vip_until']) if is_vip(u) else '', u['banned'], fmt_ts(u['joined_at'])])
        bio = io.BytesIO(buf.getvalue().encode('utf-8-sig')); bio.name = 'foydalanuvchilar.csv'
        await context.bot.send_document(chat_id=m.chat_id, document=bio, caption='📄 Foydalanuvchilar ro‘yxati')
    elif act == 'backup':
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False); tmp.close()
        try:
            src = sqlite3.connect(DB_PATH); dst = sqlite3.connect(tmp.name)
            src.backup(dst); dst.close(); src.close()
            with open(tmp.name, 'rb') as f:
                await context.bot.send_document(chat_id=m.chat_id, document=f, filename='arabcha_ustoz_zaxira.db', caption='💾 Baza zaxirasi. Xavfsiz joyda saqlang!')
        finally:
            try: os.remove(tmp.name)
            except OSError: pass
    elif act == 'lessons':
        await m.reply_text(f'📚 Darslar bo‘limi: 1–{TOTAL_LESSONS}. Darsni ochish: /lesson 125. Darslar 20 ta asosiy mavzu asosida bosqichlar bo‘yicha takrorlanadi.', reply_markup=admin_back())
    elif act == 'sections':
        await m.reply_text('🧭 BOT BO‘LIMLARI\n📚 Darslar — /lessons\n🌐 Tarjimon — /translate\n📖 Qur’on audio — /quran 1\n🗣️ Gapirish mashqi — bosh menyudan\n👤 Profil — /profile\n🛠 Admin panel — /admin', reply_markup=admin_back())

async def admin_text(update, context, mode, msg):
    m = update.effective_message; adm_id = update.effective_user.id
    ctx = context.user_data.get('adm_ctx') or {}
    def done(): context.user_data['mode'] = None; context.user_data['adm_ctx'] = {}
    if mode in ('adm_find', 'adm_chat_id', 'adm_tr_id'):
        u = find_user(msg)
        if not u:
            await m.reply_text('❌ Topilmadi. ID ni qayta yuboring yoki /admin bilan bekor qiling.'); return
        if mode == 'adm_find':
            done(); await send_card(m, u['user_id'])
        elif mode == 'adm_chat_id':
            done(); text, kb = chat_view(u['user_id'], 0); await m.reply_text(text, reply_markup=kb)
        else:
            set_mode(context, 'adm_tr_amt', uid=u['user_id'])
            await m.reply_text(f'💸 Qabul qiluvchi: {uname(u)} (ID {u["public_id"] or "—"})\n💰 Hisobi: {money(u["balance"])}\n\nQancha so‘m o‘tkazasiz?')
    elif mode in ('adm_tr_amt', 'adm_add', 'adm_minus'):
        if not (msg.isascii() and msg.isdigit() and 0 < int(msg) <= 10_000_000_000):
            await m.reply_text('❗ Summani raqam bilan yozing:'); return
        amt = int(msg); uid = ctx.get('uid'); u = get_user(uid) if uid else None
        if not u: done(); await m.reply_text('❌ Foydalanuvchi topilmadi.'); return
        if mode == 'adm_minus':
            if not spend_balance(uid, amt, 'Admin ayirdi', adm_id):
                await m.reply_text(f'❗ Hisobda {money(u["balance"])} bor, bundan ko‘p ayirib bo‘lmaydi. Boshqa summa yozing:'); return
            await notify(context.bot, uid, f'ℹ️ Hisobingizdan {money(amt)} ayirildi.')
            res = f'➖ {money(amt)} ayirildi.'
        else:
            add_balance(uid, amt, 'Admin o‘tkazdi' if mode == 'adm_tr_amt' else 'Admin qo‘shdi', adm_id)
            await notify(context.bot, uid, f'💰 Hisobingizga {money(amt)} o‘tkazildi!')
            res = f'✅ {uname(u)} hisobiga {money(amt)} o‘tkazildi.'
        done(); await m.reply_text(res); await send_card(m, uid)
    elif mode == 'adm_msg':
        uid = ctx.get('uid'); done()
        if uid and await notify(context.bot, uid, '✉️ Administrator xabari:\n\n' + msg):
            log_msg(uid, 'adm', msg); await m.reply_text('✅ Xabar yuborildi.', reply_markup=admin_back())
        else:
            await m.reply_text('⚠️ Xabarni yuborib bo‘lmadi (foydalanuvchi botni to‘xtatgan bo‘lishi mumkin).', reply_markup=admin_back())
    elif mode == 'adm_vip_days':
        if not (msg.isascii() and msg.isdigit() and 1 <= int(msg) <= 3650):
            await m.reply_text('❗ 1 dan 3650 gacha raqam yozing:'); return
        uid = ctx.get('uid'); done(); give_vip(uid, int(msg)); u = get_user(uid)
        await notify(context.bot, uid, f'🎉 Sizga VIP obuna berildi!\n⭐ {vip_text(u)}')
        await m.reply_text('✅ VIP berildi.'); await send_card(m, uid)
    elif mode in ('adm_price', 'adm_days'):
        if not (msg.isascii() and msg.isdigit()): await m.reply_text('❗ Faqat raqam yozing:'); return
        n = int(msg)
        if mode == 'adm_days' and not 1 <= n <= 3650: await m.reply_text('❗ 1 dan 3650 gacha yozing:'); return
        set_set('vip_price' if mode == 'adm_price' else 'vip_days', n); done()
        await m.reply_text(('💵 VIP narxi: ' + money(n)) if mode == 'adm_price' else f'⏱ VIP muddati: {n} kun', reply_markup=admin_menu_kb())
    elif mode == 'adm_fs_add':
        err = await fs_add_channel(update, context, msg)
        if err: await m.reply_text(err); return
        done(); FS_CACHE.clear()
        await m.reply_text('✅ Kanal qo‘shildi.\n\n' + fs_panel_text(), reply_markup=fs_panel_kb())
    elif mode == 'adm_restore':
        await m.reply_text('📎 Matn emas, fayl yuboring (.db, .csv yoki .txt). Bekor qilish: /admin'); return
    elif mode == 'adm_card':
        set_set('card_info', msg[:500]); done(); await m.reply_text('✅ Saqlandi.', reply_markup=admin_menu_kb())
    elif mode == 'adm_welcome':
        set_set('welcome', '' if msg == '-' else msg[:1500]); done(); await m.reply_text('✅ Salomlashuv matni yangilandi.', reply_markup=admin_menu_kb())
    elif mode == 'adm_addadmin':
        if adm_id not in ADMIN_IDS: done(); await m.reply_text('⛔ Faqat asosiy admin.'); return
        if not (msg.isascii() and msg.isdigit()): await m.reply_text('❗ Telegram ID raqamini yozing:'); return
        dbx('INSERT OR IGNORE INTO admins(user_id, added_at) VALUES(?,?)', (int(msg), int(time.time()))); done()
        await m.reply_text('✅ Admin qo‘shildi.', reply_markup=admin_back())
    elif mode == 'admin_broadcast':
        target = ctx.get('target', 'all'); done()
        await m.reply_text('📣 Xabar yuborish boshlandi. Tugagach hisobot keladi.')
        context.application.create_task(run_broadcast(context.bot, update.effective_chat.id, msg, target))
    else:
        done()


# ---------------------------- BAZANI TIKLASH (zaxira / eski baza / ID ro‘yxati) ----------------------------
def restore_from_file(path, name):
    """Admin yuborgan faylni bazaga qo‘shadi (mavjudlarni o‘chirmaydi). Natija matnini qaytaradi."""
    name = (name or '').lower()
    now = int(time.time())
    if name.endswith(('.txt', '.csv')):
        text = open(path, encoding='utf-8-sig', errors='ignore').read()
        ids = set()
        if name.endswith('.csv') and 'telegram_id' in text.splitlines()[0]:
            for row in csv.DictReader(io.StringIO(text)):
                v = (row.get('telegram_id') or '').strip()
                if v.isdigit(): ids.add(int(v))
        else:
            ids = {int(x) for x in re.findall(r'\d{6,15}', text)}
        added = sum(dbx('INSERT OR IGNORE INTO users(user_id, first_name, joined_at) VALUES(?,?,?)', (i, '', now)) for i in ids)
        return f'✅ Fayldan {len(ids)} ta ID topildi, yangi qo‘shildi: {added}, avvaldan bor: {len(ids) - added}.'
    src = sqlite3.connect(path)
    try:
        src.row_factory = sqlite3.Row
        tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'users' not in tables: raise ValueError('faylda “users” jadvali yo‘q')
        scols = [r[1] for r in src.execute('PRAGMA table_info(users)')]
        if 'user_id' not in scols: raise ValueError('“users” jadvalida user_id ustuni yo‘q')
        dcols = {r['name'] for r in dbq('PRAGMA table_info(users)')}
        common = [c for c in scols if c in dcols]
        rows = src.execute('SELECT * FROM users').fetchall()
    finally:
        src.close()
    added = updated = 0
    for r in rows:
        data = {c: r[c] for c in common}
        uid = data['user_id']
        if 'public_id' in data and data['public_id']:
            clash = dbq('SELECT user_id FROM users WHERE public_id=?', (data['public_id'],), one=True)
            if clash and clash['user_id'] != uid: data['public_id'] = next_public_id()
        ex = get_user(uid)
        if not ex:
            data.setdefault('joined_at', now)
            cols = list(data)
            added += dbx(f'INSERT OR IGNORE INTO users({",".join(cols)}) VALUES({",".join("?" * len(cols))})', [data[c] for c in cols])
        elif data.get('registered') and not ex['registered']:
            cols = [c for c in data if c not in ('user_id', 'username', 'first_name', 'joined_at', 'last_seen')]
            if cols:
                dbx(f'UPDATE users SET {",".join(c + "=?" for c in cols)} WHERE user_id=?', [data[c] for c in cols] + [uid]); updated += 1
    return f'✅ Zaxira faylida {len(rows)} ta foydalanuvchi bor edi.\n➕ Yangi qo‘shildi: {added}\n♻️ Ma’lumoti tiklandi (ro‘yxatdan o‘tgan): {updated}\nℹ️ Qolganlari allaqachon bazada.'

async def doc_message(update, context):
    m = update.effective_message
    if context.user_data.get('mode') != 'adm_restore' or not is_admin(update): return
    doc = m.document
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await m.reply_text('❗ Fayl 20 MB dan katta. Telegram bot orqali bunday faylni qabul qila olmaydi.'); return
    tmp = tempfile.NamedTemporaryFile(suffix='_restore', delete=False); tmp.close()
    try:
        f = await doc.get_file(); await f.download_to_drive(tmp.name)
        res = await asyncio.to_thread(restore_from_file, tmp.name, doc.file_name or '')
        context.user_data['mode'] = None
        await m.reply_text(res, reply_markup=admin_menu_kb())
    except Exception as e:
        await m.reply_text('❌ Faylni o‘qib bo‘lmadi: ' + str(e)[:200] + '\n\n.db (zaxira yoki eski baza), .csv yoki .txt (ID lar ro‘yxati) yuboring.')
    finally:
        try: os.remove(tmp.name)
        except OSError: pass


# ---------------------------- XABARLARNI SAQLASH (lichka) ----------------------------
async def log_incoming(update, context):
    try:
        u = update.effective_user; m = update.effective_message
        if not u or not m or is_admin_id(u.id): return
        text = m.text or ('[rasm] ' + (m.caption or ''))
        log_msg(u.id, 'in', text)
    except Exception as e:
        print('log xatosi:', repr(e))

def register_system_handlers(app):
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & filters.ChatType.PRIVATE, log_incoming), group=-1)
    app.add_handler(CommandHandler('id', id_cmd))
    app.add_handler(CommandHandler('profile', profile_cmd))
    app.add_handler(CallbackQueryHandler(adm_callback, pattern=r'^adm:'))
    app.add_handler(CallbackQueryHandler(reg_callback, pattern=r'^reg:'))
    app.add_handler(CallbackQueryHandler(sub_callback, pattern=r'^sub:'))
    app.add_handler(CallbackQueryHandler(fs_callback, pattern=r'^fs:'))
    app.add_handler(CallbackQueryHandler(topup_callback, pattern=r'^top:'))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern=r'^profile$'))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_message))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, doc_message))


# Curriculum sequence: 10,000 numbered lesson paths are generated from these learning themes.
TOPICS = [
 ('Arab alifbosi','Harflar shakli va nomini o‘rganing.','ا ب ت ث','alif, ba, ta, sa','Arab alifbosi'),
 ('Harakatlar','Fatha, kasra va damma bilan tovushlarni mashq qiling.','بَ بِ بُ','ba, bi, bu','Harakatlar'),
 ('Salomlashish','Salom aytish va javob berish.','السَّلَامُ عَلَيْكُمْ','as-salāmu alaykum','Salomlashish'),
 ('Ahvol so‘rash','Suhbatdoshning ahvolini so‘rash.','كَيْفَ حَالُكَ؟','kayfa hāluka?','Ahvolingiz qanday?'),
 ('O‘zingizni tanishtirish','Ismingizni va qayerdan ekaningizni ayting.','اِسْمِي ...','ismī ...','Mening ismim ...'),
 ('Rahmat va iltimos','Minnatdorchilik va muloyim iboralar.','شُكْرًا جَزِيلًا','shukran jazīlan','Katta rahmat'),
 ('Ha va yo‘q','Qisqa javoblar bilan gapirishni mashq qiling.','نَعَمْ / لَا','na‘am / lā','Ha / Yo‘q'),
 ('Savol tuzish','Oddiy savol so‘zlarini ishlating.','مَا هٰذَا؟','mā hādhā?','Bu nima?'),
 ('Oila','Oila a’zolari haqida sodda gaplar tuzing.','هٰذِهِ أُسْرَتِي','hādhihi usratī','Bu mening oilam'),
 ('Maktab va o‘qish','O‘qish va darslar haqida gapiring.','أَنَا أَدْرُسُ الْعَرَبِيَّةَ','anā adrusu-l-arabiyya','Men arab tilini o‘rganyapman'),
 ('Ovqat va ichimlik','Ovqat yoki ichimlik so‘rash.','أُرِيدُ مَاءً','urīdu mā’an','Men suv xohlayman'),
 ('Do‘kon va narx','Narx so‘rash va xarid qilish.','بِكَمْ هٰذَا؟','bikam hādhā?','Bu qancha turadi?'),
 ('Manzil so‘rash','Joylashuvni so‘rash va yo‘l tushunish.','أَيْنَ الْمَسْجِدُ؟','ayna-l-masjidu?','Masjid qayerda?'),
 ('Vaqt','Bugun, ertaga va vaqt haqida gapirish.','الْيَوْمَ وَغَدًا','al-yawma wa ghadan','Bugun va ertaga'),
 ('Fe’llar','Kundalik harakatlarni fe’llar bilan ayting.','أَذْهَبُ إِلَى الْمَدْرَسَةِ','adhhabu ila-l-madrasati','Men maktabga boraman'),
 ('O‘tgan va hozirgi zamon','Fe’l zamonlarini sodda misollarda solishtiring.','أَنَا أَكْتُبُ','anā aktubu','Men yozyapman'),
 ('Sifatlar','Narsa va odamlarni sodda sifatlar bilan tasvirlang.','الْكِتَابُ جَدِيدٌ','al-kitābu jadīdun','Kitob yangi'),
 ('Raqamlar','Raqamlar va miqdorlarni mashq qiling.','وَاحِدٌ، اِثْنَانِ، ثَلَاثَةٌ','wāhid, ithnān, thalātha','Bir, ikki, uch'),
 ('Kundalik suhbat','Ikki-uch jumlali dialog tuzing.','مَرْحَبًا، كَيْفَ حَالُكَ؟','marhaban, kayfa hāluka','Salom, ahvolingiz qanday?'),
 ('Mustaqil gapirish','O‘rgangan iboralarni bir suhbatga birlashtiring.','أُرِيدُ أَنْ أَتَعَلَّمَ الْعَرَبِيَّةَ','urīdu an ata‘allama-l-arabiyya','Men arab tilini o‘rganmoqchiman'),
]

def lesson_data(n: int):
    n = max(1, min(TOTAL_LESSONS, n))
    topic_i = (n - 1) % len(TOPICS)
    stage = (n - 1) // len(TOPICS) + 1
    title, goal, arabic, latin, meaning = TOPICS[topic_i]
    levels = ['Boshlang‘ich','Boshlang‘ich mustahkamlash','Oddiy jumlalar','Kundalik suhbat','Grammatika va gap tuzish','Erkin suhbat']
    level = levels[min(5, (n - 1) // 500)]
    # Numbered lessons cycle through core themes, increasing the task difficulty across the curriculum.
    return {'n': n, 'title': title, 'goal': goal, 'ar': arabic, 'latin': latin, 'uz': meaning, 'stage': stage, 'level': level}


ZERO_MENU = InlineKeyboardMarkup([
 [InlineKeyboardButton('🔤 Arab alifbosi (28 harf)', callback_data='alphabet')],
 [InlineKeyboardButton('َ ُ ِ Harakatlar va cho‘ziq tovushlar', callback_data='harakatlar')],
 [InlineKeyboardButton('✍️ Harf shakllari va ulanishi', callback_data='letterforms')],
 [InlineKeyboardButton('🔊 Talaffuzni tinglash', callback_data='alphabet_audio')],
 [InlineKeyboardButton('🧩 So‘z yodlash va iboralar', callback_data='lessons:3')],
 [InlineKeyboardButton('📘 Grammatika asoslari', callback_data='lessons:11')],
 [InlineKeyboardButton('🗣️ Gapirishni boshlash', callback_data='speak_start')],
 [InlineKeyboardButton('📝 Test va mashqlar', callback_data='quiz_start')],
 [InlineKeyboardButton('🏠 Bosh menyu', callback_data='home')]
])

ALPHABET = [
 ('ا','Alif','a / ā'),('ب','Ba','b'),('ت','Ta','t'),('ث','Sa','th'),('ج','Jim','j'),('ح','Ha','ḥ'),('خ','Xo','kh'),
 ('د','Dal','d'),('ذ','Zal','dh'),('ر','Ro','r'),('ز','Zay','z'),('س','Sin','s'),('ش','Shin','sh'),('ص','Sod','ṣ'),
 ('ض','Zod','ḍ'),('ط','To','ṭ'),('ظ','Zo','ẓ'),('ع','Ayn','‘'),('غ','G‘ayn','gh'),('ف','Fa','f'),('ق','Qof','q'),
 ('ك','Kaf','k'),('ل','Lam','l'),('م','Mim','m'),('ن','Nun','n'),('ه','Ha','h'),('و','Vov','w / ū'),('ي','Ya','y / ī')
]

MAIN_MENU = InlineKeyboardMarkup([
 [InlineKeyboardButton('🪜 Arab tilini 0 dan', callback_data='zero_panel')],
 [InlineKeyboardButton('📚 Mavzular (lug‘at)', callback_data='tp_panel'), InlineKeyboardButton('🧩 Grammatika', callback_data='gr_panel')],
 [InlineKeyboardButton('🌙 Payg‘ambarimiz Muhammad ﷺ hayoti', callback_data='seerah_panel')],
 [InlineKeyboardButton('📚 Islom va Qur’on haqida', callback_data='islam_panel')],
 [InlineKeyboardButton('🧔 Payg‘ambarlar qissalari', callback_data='prophets_panel')],
 [InlineKeyboardButton('📝 Islomiy testlar', callback_data='test_panel')],
 [InlineKeyboardButton('📚 10 000 ta arab tili darsi', callback_data='lessons:1')],
 [InlineKeyboardButton('🌐 Tarjimon', callback_data='translate'), InlineKeyboardButton('📖 Qur’on suralari', callback_data='quran')],
 [InlineKeyboardButton('🗣️ Gapirish mashqi', callback_data='speak'), InlineKeyboardButton('📊 Yo‘riqnoma', callback_data='help')],
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode'] = None
    if not await access_ok(update, context): return
    welcome = get_set('welcome') or '🌙 Assalomu alaykum! Islomiy bilimlar va arab tilini o‘rganish botiga xush kelibsiz.\n\nPayg‘ambarimiz ﷺ siyratlari, Qur’on, Islom asoslari, testlar va arab tili darslarini tanlang.'
    await update.effective_message.reply_text(welcome, reply_markup=main_menu(update))
    await update.effective_message.reply_text('⌨️ Pastdagi tugmalar orqali ham bo‘limlarni tanlashingiz mumkin.', reply_markup=REPLY_KB)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('/start — bosh menyu\n/lesson 1 — dars raqami\n/lessons — darslar ro‘yxati\n/translate — tarjimon\n/quran 1 — sura audiosi\n/profile — profil va hisob\n/id — Telegram ID\n\nJami 10 000 ta raqamlangan dars yo‘li mavjud.', reply_markup=main_menu(update))

async def send_lesson(chat, n: int, context):
    l = lesson_data(n)
    text = (f"📚 {l['n']}/ {TOTAL_LESSONS}-dars — {l['title']}\n"
            f"🎯 Bosqich: {l['level']} · Mavzu takrorlanish bosqichi: {l['stage']}\n\n"
            f"📝 Maqsad: {l['goal']}\n\n🇸🇦 Arabcha: {l['ar']}\n🔤 Talaffuz: {l['latin']}\n🇺🇿 O‘zbekcha ma’nosi: {l['uz']}\n\n"
            '🔊 Arabcha iborani eshitish uchun “Arabcha audio” tugmasini bosing. Keyin jumlani ovoz chiqarib 3 marta takrorlang.')
    keyboard = InlineKeyboardMarkup([
      [InlineKeyboardButton('🔊 Arabcha audio', callback_data=f"audio:{n}")],
      [InlineKeyboardButton('⬅️ Oldingi', callback_data=f"lessons:{max(1,n-1)}"), InlineKeyboardButton('Keyingi ➡️', callback_data=f"lessons:{min(TOTAL_LESSONS,n+1)}")],
      [InlineKeyboardButton('📚 Dars raqamini tanlash', callback_data='lessons:1'), InlineKeyboardButton('🏠 Menyu', callback_data='home')]
    ])
    await chat.reply_text(text, reply_markup=keyboard)

async def lesson_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: n=int(context.args[0]) if context.args else 1
    except ValueError: n=1
    await send_lesson(update.effective_message, max(1,min(TOTAL_LESSONS,n)), context)

async def lessons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('Dars raqamini yuboring: 1 dan 10000 gacha. Masalan: /lesson 125\n\nYoki quyidagi tugmalar orqali birinchi darsdan boshlang.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('1-dars',callback_data='lessons:1'),InlineKeyboardButton('100-dars',callback_data='lessons:100')],[InlineKeyboardButton('1000-dars',callback_data='lessons:1000'),InlineKeyboardButton('5000-dars',callback_data='lessons:5000')],[InlineKeyboardButton('10000-dars',callback_data='lessons:10000')]]))


# Islomiy ma'lumotlar: qisqa, ehtiyotkor va manbaga yo'naltirilgan.
SEERAH_TOPICS = [
("Tug‘ilishlari", "Payg‘ambar Muhammad ﷺ Makkada, Quraysh qabilasining Banu Hoshim urug‘ida tug‘ilganlar. An’anaviy siyrat manbalarida tug‘ilgan yil Fil yili deb ataladi."),
("Otalari va onalari", "Otalarining ismi Abdulloh, onalarining ismi Omina binti Vahb edi. Otalari u zot tug‘ilishlaridan oldin vafot etgan."),
("Bolaliklari", "U zot bolaliklarida avval Halima Sa’diya huzurlarida, keyin bobolari Abdulmuttalib va amakilari Abu Tolib himoyasida ulg‘ayganlar."),
("Yoshliklari", "Payg‘ambarimiz ﷺ rostgo‘yliklari va omonatdorliklari bilan tanilganlar. Makkaliklar u zotni Al-Amin deb atashgan."),
("Oila qurishlari", "U zot 25 yoshlarida Xadicha binti Xuvaylidga uylanganlar. Xadicha onamiz birinchi bo‘lib iymon keltirgan mo‘minlardan edilar."),
("Birinchi vahiy", "Birinchi vahiy Hiro g‘orida nozil bo‘lgan. Jabroil alayhissalom Allohning amri bilan “Iqro’” — “O‘qi” oyatlarini yetkazganlar. (Qur’on, Alaq 96:1–5)"),
("Makkadagi da’vat", "Dastlab da’vat maxfiy tarzda, keyinchalik oshkora olib borilgan. Musulmonlar qiyinchilik va qarshiliklarga duch kelganlar."),
("Hijrat", "Payg‘ambarimiz ﷺ va musulmonlar Makkadan Madinaga hijrat qilganlar. Hijrat musulmon taqvimining boshlanish nuqtasi sifatida qabul qilingan."),
("Madinadagi hayot", "Madinada masjid qurilgan, muhojirlar va ansorlar o‘rtasida birodarlik mustahkamlangan."),
("Xulqlari", "Qur’onda Payg‘ambarimiz ﷺ ulug‘ xulq sohibi ekanlari aytiladi (Qalam 68:4). U zot rahm-shafqat, rostgo‘ylik va adolatga chaqirganlar."),
("Vafotlari", "Payg‘ambarimiz Muhammad ﷺ Madinada vafot etganlar. Siyrat manbalarida vafotlari 11-hijriy yil deb qayd etiladi.")
]
ISLAM_TOPICS = [
("Qur’on", "Qur’on musulmonlar e’tiqodida Allohning Muhammad ﷺ ga nozil qilgan kalomidir. U 114 suradan iborat."),
("Vahiy", "Qur’on oyatlari Jabroil alayhissalom orqali Payg‘ambar Muhammad ﷺ ga nozil qilingan."),
("Fotiha surasi", "Fotiha surasi Qur’onning birinchi surasi bo‘lib, 7 oyatdan iborat."),
("Baqara surasi", "Baqara surasi Qur’onning eng uzun surasidir. Unda 286 oyat bor."),
("Islomning besh ustuni", "Shahodat, namoz, zakot, Ramazon ro‘zasi va imkon topgan kishining haj qilishi Islomning besh ustunidir."),
("Iymon asoslari", "Odatda iymonning olti sharti: Allohga, farishtalarga, kitoblarga, payg‘ambarlarga, oxirat kuniga va taqdirga ishonish deb o‘rgatiladi."),
("Namoz", "Besh vaqt namoz: bomdod, peshin, asr, shom va xufton."),
("Ro‘za", "Ramazon ro‘zasi Islomning besh ustunidan biridir. Ro‘za ibodati tong otishidan quyosh botguniga qadar davom etadi."),
("Zakot", "Zakot moliyaviy ibodat bo‘lib, shartlari topilgan mol-mulkdan haqdorlarga beriladi."),
("Haj", "Haj — imkoniyati yetgan musulmon uchun umrida bir marta ado etiladigan farz ibodat."),
("Masjid", "Masjid musulmonlar namoz o‘qiydigan va ibodat qiladigan joy."),
("Tahorat", "Tahorat namoz kabi ayrim ibodatlardan oldin bajariladigan poklanish amalidir.")
]

# 100 000 gacha test topshirig'i raqami: savollar ishonchli asosiy bankdan
# tasodifiy tartibda tanlanadi. Bu 100 000 ta alohida yangi fakt degani emas.
QUIZ_BANK = [
("Qur'on nechta suradan iborat?", ['114', '110', '120'], 0, "Qur’on 114 suradan iborat."),
("Qur'onning birinchi surasi qaysi?", ['Fotiha', 'Baqara', 'Ixlos'], 0, "Fotiha — Qur’onning birinchi surasi."),
("Qur'onning eng uzun surasi qaysi?", ['Baqara', 'Fotiha', 'Kavsar'], 0, "Baqara surasi eng uzun suradir."),
("Birinchi vahiy qayerda nozil bo'lgan?", ["Hiro g'orida", "Savr g'orida", 'Madinada'], 0, "Birinchi vahiy Hiro g'orida nozil bo'lgan."),
("Birinchi vahiydagi buyruq qaysi so'z bilan boshlanadi?", ["Iqro' (O'qi)", 'Sabr', 'Shukr'], 0, "Alaq surasi 1-oyati “Iqro’” so‘zi bilan boshlanadi."),
("Payg'ambarimiz ﷺ ning otalari kim?", ['Abdulloh', 'Abu Tolib', 'Abdulmuttalib'], 0, "Otalarining ismi Abdulloh edi."),
("Payg'ambarimiz ﷺ ning onalari kim?", ['Omina', 'Xadicha', 'Oisha'], 0, "Onalarining ismi Omina binti Vahb edi."),
("Payg'ambarimiz ﷺ qaysi shaharda tug'ilganlar?", ['Makka', 'Madina', 'Toif'], 0, "U zot Makkada tug‘ilganlar."),
("Hijrat qaysi shaharga bo'lgan?", ['Madina', 'Toif', 'Shom'], 0, "Musulmonlar Makkadan Madinaga hijrat qilganlar."),
("Payg'ambarimiz ﷺ ning birinchi rafiqalari kim?", ['Xadicha', 'Oisha', 'Hafsa'], 0, "Birinchi rafiqalari Xadicha binti Xuvaylid edi."),
("Islomning ustunlari nechta?", ['5', '4', '6'], 0, "Islomning besh ustuni bor."),
("Bir kunda farz namozlar necha vaqt?", ['5', '3', '4'], 0, "Farz namozlar besh vaqt."),
("Ramazon oyida qaysi ibodat farz?", ["Ro'za", 'Haj', 'Qurbonlik'], 0, "Ramazon ro‘zasi farz ibodatdir."),
("Zakot qanday ibodat?", ['Moliyaviy ibodat', 'Faqat jismoniy mashq', 'Safar'], 0, "Zakot moliyaviy ibodatdir."),
("Haj qayerda ado etiladi?", ['Makka va muqaddas manzillarda', 'Faqat Madinada', 'Quddusda'], 0, "Haj Makka va unga tegishli muqaddas manzillarda ado etiladi."),
("Fotiha surasi necha oyatdan iborat?", ['7', '5', '6'], 0, "Fotiha surasi 7 oyatdan iborat."),
("Qur'on vahiyini yetkazgan farishta kim?", ['Jabroil', 'Mikoil', 'Isrofil'], 0, "Vahiy Jabroil alayhissalom orqali yetkazilgan."),
("Payg'ambarimiz ﷺ qanday laqab bilan tanilganlar?", ['Al-Amin', 'Al-Faruq', 'As-Siddiq'], 0, "U zot rostgo‘ylik va omonatdorliklari sabab Al-Amin deb atalganlar."),
("Qur'onda Payg'ambarimiz ﷺ xulqlari qanday ta'riflangan?", ["Ulug' xulq", 'Boylik', 'Shohlik'], 0, "Qalam surasi 4-oyatda ulug‘ xulq zikr qilingan."),
("Masjidda musulmonlar nima qiladilar?", ['Ibodat va namoz', 'Savdo majburiy', 'Faqat uxlash'], 0, "Masjid ibodat va namoz joyidir."),
('Qur’on qaysi tilda nozil bo‘lgan?', ['Arab tilida', 'Fors tilida', 'Ibroniy tilida'], 0, 'Qur’on arab tilida nozil qilingan.'),
('Qur’onning oxirgi surasi qaysi?', ['An-Nos', 'Al-Falaq', 'Al-Ikhlos'], 0, 'Mushaf tartibida An-Nos surasi oxirgi suradir.'),
('Qur’onning eng qisqa surasi qaysi?', ['Al-Kavsar', 'Al-Baqara', 'Yosin'], 0, 'Al-Kavsar surasi uch oyatdan iborat.'),
('Oyatul Kursiy qaysi surada?', ['Al-Baqara', 'Al-Fotiha', 'An-Nos'], 0, 'Oyatul Kursiy Baqara surasining 255-oyatidir.'),
('Qadr kechasi qaysi oy bilan bog‘liq?', ['Ramazon', 'Shavvol', 'Muharram'], 0, 'Qadr kechasi Ramazon oyidadir.'),
('Musulmonlarning muqaddas kitobi qaysi?', ['Qur’on', 'Tavrot', 'Zabur'], 0, 'Musulmonlar Qur’onni Allohning kalomi deb e’tiqod qiladilar.'),
('Namozdan oldin odatda qanday poklanish qilinadi?', ['Tahorat', 'Tayammum har doim', 'G‘usl har doim'], 0, 'Namozdan oldin tahorat talab qilinadi; ayrim holatlarda boshqa poklanish hukmlari bor.'),
('Bomdod namozi qaysi vaqtda o‘qiladi?', ['Tongda', 'Tushda', 'Quyosh botganda'], 0, 'Bomdod namozi tong vaqti kirgach o‘qiladi.'),
('Shom namozi qachon o‘qiladi?', ['Quyosh botgach', 'Quyosh chiqqach', 'Tush payti'], 0, 'Shom namozi quyosh botgach kiradi.'),
('Juma namozi haftaning qaysi kuni ado etiladi?', ['Juma', 'Dushanba', 'Yakshanba'], 0, 'Juma namozi juma kuni ado etiladi.'),
('Ka’ba qaysi shaharda joylashgan?', ['Makka', 'Madina', 'Toif'], 0, 'Ka’ba Makkadagi Masjidul Haromda joylashgan.'),
('Masjidul Nabaviy qaysi shaharda?', ['Madina', 'Makka', 'Quddus'], 0, 'Masjidul Nabaviy Madina shahrida joylashgan.'),
('Zamzam qudug‘i qayerda?', ['Makkada', 'Madinada', 'Toifda'], 0, 'Zamzam qudug‘i Masjidul Harom hududida joylashgan.'),
('Islom taqvimidagi birinchi oy qaysi?', ['Muharram', 'Ramazon', 'Rajab'], 0, 'Hijriy-qamariy taqvim Muharram oyidan boshlanadi.'),
('Ramazondan keyingi oy qaysi?', ['Shavvol', 'Safar', 'Sha’bon'], 0, 'Ramazondan keyin Shavvol oyi keladi.'),
('Hijrat safarida Payg‘ambarimiz ﷺ bilan birga bo‘lgan sahoba kim?', ['Abu Bakr', 'Umar', 'Usmon'], 0, 'Hijrat safarida Abu Bakr roziyallohu anhu hamroh bo‘lganlar.'),
('Ansorlar kimlar?', ['Madinada musulmonlarga yordam berganlar', 'Makkadagi barcha savdogarlar', 'Faqat safar qiluvchilar'], 0, 'Ansorlar Madinada hijrat qilgan musulmonlarga yordam bergan musulmonlardir.'),
('Muhojirlar kimlar?', ['Makkadan Madinaga hijrat qilgan musulmonlar', 'Faqat Madina aholisi', 'Faqat safar savdogarlari'], 0, 'Muhojirlar dinlari uchun Makkadan Madinaga hijrat qilgan musulmonlardir.'),
('Payg‘ambarimiz ﷺ ning bobolari kim edi?', ['Abdulmuttalib', 'Abu Lahab', 'Abu Sufyon'], 0, 'Bobolarining ismi Abdulmuttalib edi.'),
('Qur’onda nechta juz bor?', ['30', '20', '40'], 0, 'Qur’on odatda 30 juzga bo‘lib o‘qiladi.'),
('Qur’onning birinchi nozil bo‘lgan oyatlari qaysi suradan?', ['Al-Alaq', 'Al-Fotiha', 'Al-Masad'], 0, 'Birinchi nozil bo‘lgan oyatlar Al-Alaq surasining boshidagi oyatlardir.'),
('Iymon shartlari odatda nechta deb o‘rgatiladi?', ['6', '5', '7'], 0, 'Iymonning olti sharti mashhur tarzda o‘rgatiladi.'),
('Islomning birinchi ustuni nima?', ['Shahodat kalimasi', 'Haj', 'Zakot'], 0, 'Islomning birinchi ustuni shahodatdir.'),
('Haj ibodati qaysi oyda ado etiladi?', ['Zulhijja', 'Ramazon', 'Muharram'], 0, 'Hajning asosiy amallari Zulhijja oyida ado etiladi.'),
('Musulmonlar namozda qaysi tomonga yuzlanadilar?', ['Qiblaga', 'Sharqqa doim', 'Shimolga doim'], 0, 'Namozda Ka’ba tomondagi qiblaga yuzlaniladi.'),
('Qibla qaysi muqaddas bino tomonga?', ['Ka’ba', 'Masjidul Aqso hovlisi', 'Masjidul Nabaviy'], 0, 'Musulmonlarning qiblasi Ka’badir.'),
('Qurbon hayiti qaysi oyda?', ['Zulhijja', 'Ramazon', 'Safar'], 0, 'Qurbon hayiti Zulhijja oyining 10-kunida boshlanadi.'),
('Fitr sadaqasi qaysi hayit bilan bog‘liq?', ['Ramazon hayiti', 'Qurbon hayiti', 'Juma'], 0, 'Fitr sadaqasi Ramazon hayiti bilan bog‘liq.'),
('Payg‘ambarlar insonlarni nimaga chaqirgan?', ['Yagona Allohga ibodat qilishga', 'Boylik yig‘ishga', 'Qabila ustunligiga'], 0, 'Payg‘ambarlarning asosiy da’vati tavhid — yagona Allohga ibodat qilishdir.'),
('Musulmonlar bir-biriga odatda qanday salom beradi?', ['Assalomu alaykum', 'Xayrli tun majburiy', 'Marhabo faqat'], 0, 'Musulmonlar orasidagi mashhur salom: Assalomu alaykum.'),
('Sadaqa nimani anglatadi?', ['Yaxshilik va ehson', 'Faqat qarz', 'Savdo foydasi'], 0, 'Sadaqa Alloh roziligi uchun qilinadigan ehson va yaxshilikdir.'),
('Islomda ota-onaga qanday munosabat buyuriladi?', ['Yaxshilik va hurmat', 'Beparvolik', 'Qo‘pollik'], 0, 'Islom ota-onaga yaxshilik va hurmat ko‘rsatishga buyuradi.'),

('Qur’onda nechta sura Madaniy deb tasniflanadi?', ['28', '86', '114'], 0, 'Keng tarqalgan tasnifda 28 ta sura Madaniy, 86 tasi Makkiy deb beriladi; tasnif tafsilotlarida ulamolar qarashlari uchrashi mumkin.'),
('Qur’onning birinchi juz’i qaysi suradan boshlanadi?', ['Al-Fotiha', 'Al-Baqara 142-oyat', 'An-Nos'], 0, 'Birinchi juz Al-Fotiha surasidan boshlanadi.'),
('Qur’onning 30-juz’i qaysi suradan boshlanadi?', ['An-Naba', 'Al-Fotiha', 'Al-Baqara'], 0, '30-juz’ An-Naba surasidan boshlanadi.'),
('“Qul huvallohu ahad” qaysi suraning boshlanishi?', ['Al-Ixlos', 'Al-Falaq', 'Al-Kavsar'], 0, 'Bu Al-Ixlos surasining birinchi oyatidir.'),
('“Tabbat yada abi Lahab” qaysi surada keladi?', ['Al-Masad', 'An-Nasr', 'Al-Qadr'], 0, 'Bu Al-Masad surasining boshlanishidir.'),
('Qur’ondagi “Oyatul Kursiy” qaysi oyat?', ['Baqara 255', 'Fotiha 1', 'Ixlos 3'], 0, 'Oyatul Kursiy Baqara surasining 255-oyatidir.'),
('Qur’onda Maryam nomli sura bormi?', ['Ha', 'Yo‘q', 'Faqat hadisda'], 0, 'Maryam — Qur’onning 19-surasi.'),
('Qur’onda Yusuf nomli sura bormi?', ['Ha', 'Yo‘q', 'Faqat tafsirda'], 0, 'Yusuf — Qur’onning 12-surasi.'),
('Qur’ondagi eng uzun oyat qaysi surada?', ['Baqara', 'Fotiha', 'Kavsar'], 0, 'Qarz muomalasi haqidagi eng uzun oyat Baqara surasining 282-oyatidir.'),
('Qur’onda sajda oyatlari bormi?', ['Ha', 'Yo‘q', 'Faqat bir surada'], 0, 'Qur’onda tilovat sajdasi bilan bog‘liq oyatlar mavjud.'),
('Payg‘ambarimiz ﷺ ga vahiy kelgan g‘or nomi nima?', ['Hiro', 'Savr', 'Uhud'], 0, 'Birinchi vahiy Hiro g‘orida nozil bo‘lgan.'),
('Payg‘ambarimiz ﷺ qaysi qabiladan edilar?', ['Quraysh', 'Aws', 'Xazraj'], 0, 'U zot Quraysh qabilasidan edilar.'),
('Payg‘ambarimiz ﷺ qaysi urug‘dan edilar?', ['Banu Hoshim', 'Banu Umayya', 'Banu Tamim'], 0, 'U zot Qurayshning Banu Hoshim urug‘idan edilar.'),
('Payg‘ambarimiz ﷺ ga birinchi iymon keltirgan ayol kim?', ['Xadicha', 'Oisha', 'Hafsa'], 0, 'Xadicha roziyallohu anho birinchi iymon keltirgan ayol edilar.'),
('Payg‘ambarimiz ﷺ ning emizgan onalaridan mashhuri kim?', ['Halima Sa’diya', 'Omina', 'Safiyya'], 0, 'Halima Sa’diya u zotni emizgan onalaridan mashhuridir.'),
('Hijrat vaqtida Payg‘ambarimiz ﷺ va Abu Bakr qaysi g‘orda panoh topganlar?', ['Savr', 'Hiro', 'Uhud'], 0, 'Hijrat safarida ular Savr g‘orida panoh topganlar.'),
('Badr jangi qaysi hijriy yilda bo‘lgan?', ['2-hijriy yil', '5-hijriy yil', '8-hijriy yil'], 0, 'Badr jangi 2-hijriy yilda bo‘lgan.'),
('Uhud jangi qaysi hijriy yilda bo‘lgan?', ['3-hijriy yil', '1-hijriy yil', '9-hijriy yil'], 0, 'Uhud jangi 3-hijriy yilda bo‘lgan.'),
('Xandaq jangi yana qaysi nom bilan tanilgan?', ['Ahzob', 'Badr', 'Hunayn'], 0, 'Xandaq jangi Ahzob jangi nomi bilan ham tanilgan.'),
('Hudaybiya sulhi qaysi hijriy yilda tuzilgan?', ['6-hijriy yil', '2-hijriy yil', '10-hijriy yil'], 0, 'Hudaybiya sulhi 6-hijriy yilda tuzilgan.'),
('Makka fath etilishi qaysi hijriy yilda bo‘lgan?', ['8-hijriy yil', '2-hijriy yil', '11-hijriy yil'], 0, 'Makka fath etilishi 8-hijriy yilda bo‘lgan.'),
('Payg‘ambarimiz ﷺ ning qizlaridan biri kim?', ['Fotima', 'Maryam', 'Osiyo'], 0, 'Fotima roziyallohu anho Payg‘ambarimiz ﷺ ning qizlaridan edilar.'),
('Payg‘ambarimiz ﷺ ning mashhur muazzin sahobalaridan kim?', ['Bilol', 'Salmon', 'Zayd'], 0, 'Bilol ibn Raboh roziyallohu anhu mashhur muazzin sahoba edilar.'),
('Birinchi xalifa kim bo‘lgan?', ['Abu Bakr', 'Umar', 'Ali'], 0, 'Rashid xalifalarning birinchisi Abu Bakr roziyallohu anhu bo‘lganlar.'),
('Ikkinchi roshid xalifa kim?', ['Umar ibn Xattob', 'Usmon ibn Affon', 'Ali ibn Abu Tolib'], 0, 'Ikkinchi roshid xalifa Umar ibn Xattob roziyallohu anhu bo‘lganlar.'),
('Uchinchi roshid xalifa kim?', ['Usmon ibn Affon', 'Abu Bakr', 'Ali'], 0, 'Uchinchi roshid xalifa Usmon ibn Affon roziyallohu anhu bo‘lganlar.'),
('To‘rtinchi roshid xalifa kim?', ['Ali ibn Abu Tolib', 'Umar', 'Usmon'], 0, 'To‘rtinchi roshid xalifa Ali ibn Abu Tolib roziyallohu anhu bo‘lganlar.'),
('Islomda juma kuni qaysi ibodat alohida ado etiladi?', ['Juma namozi', 'Taroveh', 'Hayit namozi'], 0, 'Juma kuni peshin o‘rniga juma namozi ado etiladi, uning shartlari va tafsilotlari fiqhda bayon qilingan.'),
('Taroveh namozi qaysi oyda o‘qiladi?', ['Ramazon', 'Muharram', 'Safar'], 0, 'Taroveh namozi Ramazon oyida o‘qiladi.'),
('Laylatul Qadr qanday kecha?', ['Qadr kechasi', 'Arafa kuni', 'Juma kechasi'], 0, 'Laylatul Qadr — Qur’onda zikr qilingan ulug‘ kecha.'),
('Arafa kuni qaysi oyda bo‘ladi?', ['Zulhijja', 'Ramazon', 'Shavvol'], 0, 'Arafa kuni Zulhijja oyining 9-kunidir.'),
('Tayammum qachon ruxsat etiladi?', ['Suv topilmasa yoki ishlatish mumkin bo‘lmasa, shartlari bilan', 'Har doim tahorat o‘rniga', 'Faqat safarda'], 0, 'Tayammum suv topilmasa yoki undan foydalanish mumkin bo‘lmagan holatlarda, fiqhiy shartlar asosida qilinadi.'),
('G‘usl nimani anglatadi?', ['Butun badan bilan shar’iy poklanish', 'Faqat qo‘l yuvish', 'Faqat oyoq yuvish'], 0, 'G‘usl — belgilangan holatlarda butun badan bilan poklanishdir.'),
('Azon nima uchun aytiladi?', ['Namoz vaqti kirganini bildirish uchun', 'Dars boshlanishi uchun', 'Safar e’lon qilish uchun'], 0, 'Azon musulmonlarni farz namoziga chaqiradi.'),
('Qaysi namozda ruku va sajda bor?', ['Farz namozlarda', 'Faqat janozada', 'Faqat hayit takbirida'], 0, 'Kundalik farz namozlarda qiyom, qiroat, ruku va sajdalar mavjud.'),
('Janoza namozida ruku va sajda qilinadimi?', ['Yo‘q', 'Ha, ikki sajda', 'Ha, bir ruku'], 0, 'Janoza namozi tik turib, takbirlar bilan ado etiladi; unda ruku va sajda yo‘q.'),
('Qur’onni yod olgan kishi qanday ataladi?', ['Hofiz', 'Muazzin', 'Xatib'], 0, 'Qur’onni yod olgan kishi hofiz deb ataladi.'),
('Qur’on oyatlarini izohlovchi ilm nima deyiladi?', ['Tafsir', 'Fiqh', 'Sarf'], 0, 'Tafsir Qur’on oyatlarining ma’nolarini sharhlash ilmidir.'),
('Islomiy amaliy hukmlarni o‘rganuvchi ilm nima?', ['Fiqh', 'Tajvid', 'Tarix'], 0, 'Fiqh amaliy shar’iy hukmlarni o‘rganuvchi ilmdir.'),
('Qur’onni qoidalar bilan to‘g‘ri o‘qish ilmi nima?', ['Tajvid', 'Hadis', 'Siyrat'], 0, 'Tajvid Qur’on tilovatini to‘g‘ri ado etish qoidalarini o‘rgatadi.'),
('Payg‘ambarimiz ﷺ hayotlari haqidagi ilm nima deyiladi?', ['Siyrat', 'Tajvid', 'Nahv'], 0, 'Siyrat Payg‘ambarimiz ﷺ hayotlari va faoliyatlarini o‘rganuvchi sohadir.'),
('Payg‘ambarimiz ﷺ so‘zlari, amallari va taqrirlarini o‘rganuvchi rivoyatlar nima?', ['Hadis', 'Tafsir', 'Fiqh'], 0, 'Hadislar Payg‘ambarimiz ﷺ ga nisbat berilgan so‘z, amal va taqrirlarni rivoyat qiladi.'),
('“Sahih” hadis atamasi nimani bildiradi?', ['Ishonchli shartlarga javob bergan hadis', 'Har qanday hikoya', 'Faqat tarixiy she’r'], 0, 'Sahih hadis hadis ilmi mezonlariga ko‘ra ishonchli deb baholangan rivoyatdir.'),
('Islomda rostgo‘ylik qanday fazilat?', ['Maqtovli fazilat', 'Qoralangan odat', 'Faqat savdogarlarga kerak'], 0, 'Rostgo‘ylik Islomda ulug‘langan axloqiy fazilatdir.'),
('G‘iybat nima?', ['Birovni yo‘qligida u yoqtirmaydigan narsa bilan eslash', 'Yaxshi salom berish', 'Ilm o‘rganish'], 0, 'G‘iybat — kishi yo‘qligida u yoqtirmaydigan sifatini aytishdir.'),
('Islomda salomga qanday javob qaytariladi?', ['Va alaykum assalom', 'Xayr', 'Rahmat, xolos'], 0, '“Assalomu alaykum” salomiga “Va alaykum assalom” deb javob beriladi.'),
('Sadaqai joriya nimani anglatadi?', ['Savobi davom etadigan xayrli ehson', 'Bir martalik qarz', 'Majburiy soliq'], 0, 'Sadaqai joriya foydasi davom etadigan xayrli ehsondir.'),
('Islomda ilm talab qilish qanday qadrlanadi?', ['Yuksak qadrlanadi', 'Man etiladi', 'Faqat savdogarlarga tegishli'], 0, 'Islom ta’limotida foydali ilm olish yuksak qadrlanadi.'),
('Musulmonlar uchun Qur’onni qanday o‘rganish ma’qul?', ['Ishonchli ustoz va tafsirlar bilan', 'Manbasiz ijtimoiy tarmoq gaplari bilan', 'Faqat taxmin bilan'], 0, 'Qur’onni ishonchli ustozlar va e’tiborli tafsir manbalari orqali o‘rganish ma’qul.'),
('Diniy masalada ixtilofli hukmga duch kelsa nima qilish kerak?', ['Malakali olimdan so‘rash', 'Shoshilib hukm chiqarish', 'Tasodifiy javobni tanlash'], 0, 'Murakkab yoki ixtilofli masalalarda malakali, ishonchli olimga murojaat qilish kerak.'),

# Qur’on va ishonchli rivoyatlarga tayangan payg‘ambarlar hamda qabr savollari
('Qur’onda nomi zikr qilingan payg‘ambarlar soni nechta deb mashhur o‘rgatiladi?', ['25 ta', '10 ta', '40 ta'], 0, 'Qur’onda nomi zikr qilingan 25 payg‘ambar bor. Bu barcha payg‘ambarlar soni degani emas.'),
('Qur’onda kemani yasagan payg‘ambar kim?', ['Nuh alayhissalom', 'Yusuf alayhissalom', 'Yahyo alayhissalom'], 0, 'Nuh alayhissalomga kema yasash vahiy qilingan (Hud surasi 37-oyat).'),
('Allohning izni bilan olov unga salqin va omonlik bo‘lgan payg‘ambar kim?', ['Ibrohim alayhissalom', 'Muso alayhissalom', 'Dovud alayhissalom'], 0, 'Qur’onda olovga Ibrohim alayhissalom uchun salqin va omonlik bo‘lishi buyurilgani bayon qilinadi (Anbiyo 69).'),
('Qaysi payg‘ambar quduqqa tashlangan va keyinchalik Misrda yuqori martabaga erishgan?', ['Yusuf alayhissalom', 'Yunus alayhissalom', 'Hud alayhissalom'], 0, 'Yusuf alayhissalom qissasi Yusuf surasida bayon qilingan.'),
('Qaysi payg‘ambar baliq qornida qolgan?', ['Yunus alayhissalom', 'Solih alayhissalom', 'Ismoil alayhissalom'], 0, 'Yunus alayhissalom qissasi Anbiyo 87–88 va boshqa oyatlarda zikr qilingan.'),
('Qaysi payg‘ambar Alloh bilan bevosita kalom qilgani bilan tanilgan?', ['Muso alayhissalom', 'Lut alayhissalom', 'Ayyub alayhissalom'], 0, 'Qur’onda Alloh Muso alayhissalom bilan gaplashgani zikr qilinadi (Niso 164).'),
('Qaysi payg‘ambarga Zabur berilgan?', ['Dovud alayhissalom', 'Sulaymon alayhissalom', 'Zakariyo alayhissalom'], 0, 'Qur’onda Dovud alayhissalomga Zabur berilgani aytiladi (Niso 163).'),
('Qaysi payg‘ambar qushlar tilini tushunish ne’matiga ega bo‘lgan?', ['Sulaymon alayhissalom', 'Nuh alayhissalom', 'Ayyub alayhissalom'], 0, 'Sulaymon alayhissalomga qushlar tilidan anglash o‘rgatilgani Naml surasida keladi.'),
('Qaysi payg‘ambar sabr-toqati bilan mashhur qissa egasi?', ['Ayyub alayhissalom', 'Hud alayhissalom', 'Ilyos alayhissalom'], 0, 'Ayyub alayhissalomning sabri va Allohga duo qilishi Anbiyo 83–84 da zikr qilinadi.'),
('Maryamga Iso alayhissalom haqida xushxabar bergan farishta kim?', ['Jabroil alayhissalom', 'Mikoil alayhissalom', 'Isrofil alayhissalom'], 0, 'Qur’onda Maryamga Ruh (Jabroil) yuborilgani Maryam surasida bayon qilinadi.'),
('Iso alayhissalomning onalari kim?', ['Maryam', 'Osiyo', 'Hojar'], 0, 'Iso alayhissalomning onalari Maryamdir. Qur’onda Maryam nomli sura ham bor.'),
('Yahyo alayhissalomning otalari kim?', ['Zakariyo alayhissalom', 'Ibrohim alayhissalom', 'Ya’qub alayhissalom'], 0, 'Zakariyo alayhissalomga Yahyo ismli farzand xushxabari berilgani Oli Imron surasida keladi.'),
('Qaysi payg‘ambar qavmiga mo‘jiza sifatida urg‘ochi tuya berilgan?', ['Solih alayhissalom', 'Shuayb alayhissalom', 'Idris alayhissalom'], 0, 'Solih alayhissalom qavmiga tuya mo‘jizasi berilgani A’rof va boshqa suralarda bayon qilingan.'),
('Qaysi payg‘ambar Madyan ahliga yuborilgan?', ['Shuayb alayhissalom', 'Yunus alayhissalom', 'Dovud alayhissalom'], 0, 'Shuayb alayhissalomning Madyan ahliga da’vati A’rof surasida zikr qilinadi.'),
('Qaysi payg‘ambar Lut alayhissalomning jiyani sifatida tafsirlarda tanilgan?', ['Ibrohim alayhissalom', 'Muso alayhissalom', 'Yusuf alayhissalom'], 0, 'Lut alayhissalom Ibrohim alayhissalom bilan bir davrda yashagan; qarindoshlik tafsilotlari tafsir va tarixiy rivoyatlarda keladi.'),
('Ismoil alayhissalomning otalari kim?', ['Ibrohim alayhissalom', 'Ya’qub alayhissalom', 'Nuh alayhissalom'], 0, 'Ismoil alayhissalom Ibrohim alayhissalomning o‘g‘illaridir.'),
('Ya’qub alayhissalomning o‘g‘li bo‘lgan payg‘ambar kim?', ['Yusuf alayhissalom', 'Muso alayhissalom', 'Solih alayhissalom'], 0, 'Yusuf alayhissalom Ya’qub alayhissalomning o‘g‘li edi.'),
('Qaysi payg‘ambar “Zunnun” nomi bilan ham tilga olinadi?', ['Yunus alayhissalom', 'Nuh alayhissalom', 'Harun alayhissalom'], 0, 'Zunnun — Yunus alayhissalomga nisbatan ishlatilgan nomlardan biri (Anbiyo 87).'),
('Qaysi payg‘ambar Fir’avn huzuriga yuborilgan va akasi Harun unga yordamchi bo‘lgan?', ['Muso alayhissalom', 'Yusuf alayhissalom', 'Dovud alayhissalom'], 0, 'Muso alayhissalom Fir’avnga yuborilgan; Harun alayhissalom unga yordamchi bo‘lishini so‘ragan (Toha 29–36).'),
('Qaysi payg‘ambar temirni yumshatish ne’matiga ega bo‘lgan?', ['Dovud alayhissalom', 'Idris alayhissalom', 'Lut alayhissalom'], 0, 'Saba surasi 10–11-oyatlarda Dovud alayhissalomga temirni yumshatish ne’mati berilgani aytiladi.'),
('Qabrga qo‘yilgan inson haqida sahih Buxoriy 1338-hadisida ikki farishta nima haqida so‘rashi bayon qilingan?', ['Muhammad ﷺ haqida nima deb e’tiqod qilgani', 'Qaysi shaharda tug‘ilgani', 'Qancha moli borligi'], 0, 'Sahih al-Buxoriy 1338 rivoyatida ikki farishta insondan Muhammad ﷺ haqida nima deganini so‘rashi keladi.'),
('Qabr savolida mo‘min Muhammad ﷺ haqida qanday guvohlik berishi rivoyat qilingan?', ['U Allohning bandasi va elchisidir', 'U farishtadir', 'U podshohdir'], 0, 'Sahih al-Buxoriy 1338 da mo‘min: “U Allohning bandasi va Rasulidir”, deb guvohlik berishi keladi.'),
('Qabr savollariga oid mashhur ta’limotda “Robbing kim?” savoliga javob nima?', ['Alloh — Rabbim', 'Mening qabilam', 'Mening molim'], 0, 'Islom aqidasida qabr savollari “Robbing kim?”, “Dining nima?” va “Payg‘ambaring kim?” mazmunida o‘rgatiladi.'),
('Qabr savollariga oid mashhur ta’limotda “Dining nima?” savoliga javob nima?', ['Islom', 'Savdo', 'Sayohat'], 0, 'Musulmon kishi dinim Islom, deb javob beradi. Bu mavzu aqida darslarida hadislar asosida o‘rgatiladi.'),
('Qabr savollariga oid mashhur ta’limotda “Payg‘ambaring kim?” savoliga javob nima?', ['Muhammad ﷺ', 'Muso alayhissalom', 'Ibrohim alayhissalom'], 0, 'Oxirgi payg‘ambar Muhammad ﷺ dirlar. Qabr savollari haqidagi rivoyatlarda u zot haqida so‘ralishi keladi.'),
('Qabr savollari haqidagi mashhur rivoyatlarda savol beruvchi farishtalar soni nechta deb keladi?', ['Ikki', 'Uch', 'To‘rt'], 0, 'Sahih al-Buxoriy 1338 da ikki farishta kelishi zikr qilinadi.'),
('Qabr savollari mavzusida to‘g‘ri bilimni qanday o‘rganish kerak?', ['Qur’on va ishonchli hadislar hamda malakali ustoz orqali', 'Manbasiz qo‘rqinchli hikoyalar orqali', 'Faqat mish-mishlar orqali'], 0, 'G‘ayb masalalarida Qur’on, ishonchli hadis va malakali ustozlarning sharhiga tayanish kerak.'),
('Qur’onda barcha payg‘ambarlarning ismlari to‘liq sanab o‘tilganmi?', ['Yo‘q, ayrim payg‘ambarlar zikr qilingan, ayrimlari zikr qilinmagan', 'Ha, barchasining ismi bir oyatda', 'Faqat beshtasi zikr qilingan'], 0, 'Qur’on 40:78 da ayrim rasullar qissasi aytilgani, ayrimlari aytilmagani bildiriladi.'),
('Payg‘ambarlarning asosiy da’vati nima bo‘lgan?', ['Yagona Allohga ibodat qilish', 'Odamlarga boylik va’da qilish', 'O‘zlarini iloh deb tanitish'], 0, 'An-Nahl 36-oyatda har bir ummatga Allohga ibodat qilishga chaqiruvchi rasul yuborilgani bayon qilinadi.'),
('Ulul azm payg‘ambarlar qatorida qaysi besh zot mashhur sanaladi?', ['Muhammad, Nuh, Ibrohim, Muso va Iso alayhimussalom', 'Odam, Idris, Hud, Solih va Lut', 'Yusuf, Ya’qub, Ayyub, Yunus va Zakariyo'], 0, 'Tafsir va aqida manbalarida ulul azm rasullar sifatida Muhammad, Nuh, Ibrohim, Muso va Iso alayhimussalom zikr qilinadi.'),
('Qur’onda “Muhammad Allohning rasuli va payg‘ambarlarning muhridir” mazmuni qaysi aqidani bildiradi?', ['Muhammad ﷺ oxirgi payg‘ambar ekanini', 'Undan keyin yana payg‘ambar kelishini', 'Payg‘ambarlar bo‘lmaganini'], 0, 'Ahzob 40-oyatda Muhammad ﷺ “xotamun-nabiyyin” — payg‘ambarlarning oxirgisi deb ta’riflanadi.'),
('Nuh alayhissalom qavmini nimaga chaqirgan?', ['Allohga ibodat qilishga', 'Butlarga sajda qilishga', 'Faqat savdo qilishga'], 0, 'Nuh alayhissalom qavmini Allohga ibodat qilishga chaqirgan (A’rof 59).'),
('Ibrohim alayhissalom otasini nimadan qaytargan?', ['Butlarga ibodat qilishdan', 'Dehqonchilikdan', 'Safar qilishdan'], 0, 'Maryam surasida Ibrohim alayhissalom otasiga butlarga ibodat qilmaslik haqida nasihat qilgani bayon qilinadi.'),
('Yusuf alayhissalom tush ta’birini bilish ne’matiga ega bo‘lganmi?', ['Ha', 'Yo‘q', 'Faqat podshoh bo‘lgach o‘rgangan'], 0, 'Yusuf surasida Yusuf alayhissalomga tushlar ta’birini o‘rgatish ne’mati zikr qilinadi.'),
('Muso alayhissalomga berilgan mashhur mo‘jizalardan biri qaysi?', ['Hassasining Alloh izni bilan ilonga aylanishi', 'Temirni yumshatish', 'Baliq qornida qolish'], 0, 'Muso alayhissalom hassasi mo‘jizasi Toha va A’rof suralarida zikr qilingan.'),
('Iso alayhissalom Allohning izni bilan qaysi mo‘jizani ko‘rsatgan?', ['Tug‘ma ko‘r va pesni shifolash', 'Dengizni hassasi bilan yorish', 'Kema yasash'], 0, 'Oli Imron 49-oyatda Iso alayhissalomning Alloh izni bilan bemorlarni shifolashi zikr qilinadi.'),
('Qur’onda Maryamning pokligi va iffatiga bag‘ishlangan qissa qaysi surada keng bayon qilinadi?', ['Maryam surasida', 'Fil surasida', 'Kavsar surasida'], 0, 'Maryam surasida Maryam va Iso alayhimassalom qissasi bayon qilinadi.'),

]

# Arab tili: so‘z boyligi, kundalik iboralar va suhbat testlari.
# ===================== QO‘SHIMCHA BO‘LIM (yangi) =====================
# Payg‘ambarlar qissalari va qo‘shimcha testlar. Mavjud kodga tegilmagan.
PROPHET_NOTE = "Eslatma: bu qisqa ma’lumot. Batafsil o‘rganish uchun Qur’on tafsiri va ishonchli qissalarga murojaat qiling."
PROPHETS = [
("Odam alayhissalom", "Odam alayhissalom — Alloh tuproqdan yaratgan birinchi inson va ko‘pchilik ulamolar fikricha, birinchi payg‘ambar.\n\nAlloh farishtalarga unga ta’zim sajdasi qilishni buyurdi; Iblis takabburlik qilib bosh tortdi. Odam va juft Havvo jannatda yashadilar, ammo taqiqlangan daraxt mevasidan totishdi. Ular tavba qilishdi va Alloh tavbalarini qabul qildi. So‘ngra yer yuziga tushirildilar.\n\n📖 Baqara 30–39, A’rof 11–25."),
("Idris alayhissalom", "Idris alayhissalom Qur’onda ikki joyda zikr qilingan.\n\nMaryam surasida u rostgo‘y payg‘ambar va yuksak martabaga ko‘tarilgan zot deb ta’riflanadi; Anbiyo surasida sabr qiluvchilar qatorida tilga olinadi. Uning hayoti haqidagi boshqa tafsilotlar tafsir manbalarida turlicha keltirilgan, shuning uchun Qur’ondagi ma’lumot bilan cheklanamiz.\n\n📖 Maryam 56–57, Anbiyo 85."),
("Nuh alayhissalom", "Nuh alayhissalom qavmini uzoq yillar yagona Allohga ibodat qilishga da’vat qildi; Qur’onga ko‘ra, ular orasida 950 yil turgan.\n\nQavmining aksari rad etdi va masxara qildi. Alloh unga kema yasashni vahiy qildi: iymon keltirganlar va har turdan bir juft hayvon kemaga chiqarildi, qolganlar to‘fonda halok bo‘ldi. Nuh — ulul azm payg‘ambarlardan biri.\n\n📖 Hud 25–49, Ankabut 14, Nuh surasi."),
("Hud alayhissalom", "Hud alayhissalom Od qavmiga yuborilgan.\n\nOd qavmi baland binolar qurgan, kuch-quvvatli edi, lekin Allohga shukr qilmay, butlarga sig‘inishdi. Hud ularni tavhidga chaqirdi, ular rad etdilar. Natijada ularga kuchli, sovuq shamol yuborilib, halok qilindilar.\n\n📖 A’rof 65–72, Hud 50–60, Haqqa 6–7."),
("Solih alayhissalom", "Solih alayhissalom Samud qavmiga yuborilgan. Samud qavmi tog‘larni o‘yib uylar qurgan edi.\n\nAlloh ularga mo‘jiza sifatida urg‘ochi tuyani yubordi; tuya uchun suv ichish navbati belgilandi va unga ziyon yetkazmaslik buyurildi. Ular tuyani so‘yishdi, so‘ng dahshatli ovoz va zilzila bilan halok bo‘ldilar.\n\n📖 A’rof 73–79, Hud 61–68, Shuaro 141–159."),
("Ibrohim alayhissalom", "Ibrohim alayhissalom “Xalilulloh” (Allohning do‘sti) laqabi bilan mashhur, ulul azm payg‘ambarlardan.\n\nU otasi va qavmini butparastlikdan qaytardi, butlarni sindirdi; qavmi uni olovga tashladi, Alloh olovni unga salqin va omonlik qildi. U Ismoil va Ishoqning otasi; Ismoil bilan birga Ka’ba poydevorini ko‘targan. O‘g‘lini qurbon qilish sinovida tayyorlik ko‘rsatganida Alloh uning o‘rniga katta qurbonlik berdi; Qurbon hayiti shu voqea xotirasi bilan bog‘liq.\n\n📖 Anbiyo 51–73, Saffot 99–111, Baqara 124–127."),
("Lut alayhissalom", "Lut alayhissalom Ibrohim alayhissalomning zamondoshi.\n\nQavmi buzuq va uyatsiz ishlarga berilgan edi; Lut ularni bundan qaytardi, ular esa uni va iymonlilarni shahardan chiqarib yubormoqchi bo‘lishdi. Alloh Lut va uning oilasini (xotinidan boshqa) najot berdi, qavmiga esa azob yubordi.\n\n📖 A’rof 80–84, Hud 77–83, Tahrim 10."),
("Ismoil alayhissalom", "Ismoil alayhissalom Ibrohim alayhissalomning o‘g‘li; onasi Hojar.\n\nMashhur rivoyatga ko‘ra, Hojar go‘dak Ismoil bilan Makkada qolganda Zamzam chashmasi qaynab chiqqan. Qur’onda u va’dasiga sodiq rasul va nabiy deb ta’riflanadi. Otasi bilan Ka’bani ko‘targan. Payg‘ambarimiz Muhammad ﷺ uning avlodidan ekanlari an’anaviy nasab manbalarida keltiriladi.\n\n📖 Maryam 54–55, Baqara 125–129, Saffot 100–107."),
("Ishoq alayhissalom", "Ishoq alayhissalom Ibrohim alayhissalomning o‘g‘li.\n\nIbrohim va ahli keksayganda farishtalar ularga Ishoq haqida xushxabar yetkazishgan. Ishoqning o‘g‘li Ya’qub ham payg‘ambar bo‘lgan; Bani Isroil payg‘ambarlarining ko‘pchiligi shu naslga mansub.\n\n📖 Hud 69–73, Hijr 51–56, Saffot 112–113."),
("Ya’qub alayhissalom", "Ya’qub alayhissalom Ishoqning o‘g‘li; “Isroil” laqabi unga tegishli, Bani Isroil nomi shundan.\n\nU o‘g‘illariga tavhidni vasiyat qilgan. Yusufdan ayrilganda go‘zal sabr qildi, qayg‘udan ko‘zlari oqarib ketdi; keyinchalik Yusufning ko‘ylagi yuziga tashlanganda ko‘rish qobiliyati qaytdi.\n\n📖 Baqara 132–133, Yusuf 83–96."),
("Yusuf alayhissalom", "Yusuf alayhissalom Ya’qubning o‘g‘li.\n\nYoshligida “o‘n bir yulduz, quyosh va oy menga sajda qilyapti” degan tush ko‘rdi. Akalari hasad qilib uni quduqqa tashlashdi; karvon uni Misrga olib borib sotdi. Aziz xonadonida, so‘ng zindonda sabr va iffat ko‘rsatdi. Tush ta’biri tufayli podshoh huzuriga chaqirilib, mamlakat g‘aznalari mas’uli bo‘ldi. Oxir-oqibat oilasi bilan uchrashdi va akalarini kechirdi. Qur’on bu qissani “eng go‘zal qissa” deb ataydi.\n\n📖 Yusuf surasi (12)."),
("Ayyub alayhissalom", "Ayyub alayhissalom og‘ir sinovga — kasallik va mashaqqatga — sabr qilgan payg‘ambar.\n\nU Allohga umid bilan duo qildi: o‘ziga zarar yetganini va Alloh rahmlilarning eng rahmlisi ekanini aytdi. Alloh duosini ijobat qildi, unga shifo berdi va ahlini qaytardi. Ayyub sabr timsoli sifatida tilga olinadi.\n\n📖 Anbiyo 83–84, Sod 41–44."),
("Shuayb alayhissalom", "Shuayb alayhissalom Madyan ahliga yuborilgan.\n\nMadyanliklar butparastlik bilan birga o‘lchov va tarozida aldov qilishar, odamlarga ozor berishar edi. Shuayb ularni tavhidga va adolatli savdoga chaqirdi. Rad etganlari uchun zilzila va dahshatli ovoz bilan halok bo‘ldilar.\n\n📖 A’rof 85–93, Hud 84–95."),
("Muso alayhissalom", "Muso alayhissalom — Qur’onda ismi eng ko‘p zikr qilingan payg‘ambarlardan, ulul azm payg‘ambar.\n\nGo‘dakligida Fir’avn zulmi tufayli sandiqqa solinib daryoga qo‘yilgan, Fir’avn saroyida ulg‘aygan. Madyanga ketib, qaytishda Tur tog‘i yonida Alloh bilan kalom qilgan va payg‘ambarlik berilgan. Hassasi va yorug‘ qo‘li (yad bayzo) mo‘jizalari bilan Fir’avnga yuborildi; akasi Horun unga yordamchi bo‘ldi. Bani Isroilni olib chiqqanda dengiz yorilib, ular najot topdi, Fir’avn va lashkari g‘arq bo‘ldi. Unga Tavrot berilgan.\n\n📖 Qasas, Toha 9–98, Shuaro 10–68."),
("Horun alayhissalom", "Horun alayhissalom Muso alayhissalomning akasi.\n\nMuso Allohdan unga yordamchi bo‘lishini so‘ragan, Alloh bu duoni ijobat qilgan. Horun Muso bilan birga Fir’avnni da’vat qildi. Muso Tur tog‘iga ketganda Bani Isroil buzoqqa sig‘inishga ketganida, Horun ularni bundan qaytarishga urindi.\n\n📖 Toha 29–36, 90–94, Qasas 34."),
("Zulkifl alayhissalom", "Zulkifl alayhissalom Qur’onda Ismoil va Idris bilan birga sabrlilar va solihlardan sifatida ikki joyda zikr qilingan.\n\nUning hayotiy tafsilotlari Qur’onda yoritilmagan, tafsir kitoblarida turlicha fikrlar bor. Shu sababli ishonchli ma’lumot sifatida faqat Qur’ondagi ta’rif bilan cheklanamiz.\n\n📖 Anbiyo 85–86, Sod 48."),
("Dovud alayhissalom", "Dovud alayhissalom payg‘ambar va podshoh.\n\nYoshligida Jolutni mag‘lub qilgan. Unga Zabur berilgan, temir yumshatilgan (zirh yasash uchun), tog‘lar va qushlar u bilan birga Allohni tasbeh aytgan. Hukm chiqarishda haq bilan adolat qilishga buyurilgan.\n\n📖 Baqara 251, Sod 17–26, Saba 10–11, Anbiyo 78–80."),
("Sulaymon alayhissalom", "Sulaymon alayhissalom Dovud alayhissalomning o‘g‘li, payg‘ambar va podshoh.\n\nUnga shamol va jinlar bo‘ysundirilgan, qushlar hamda chumolilar tilini tushunish ilmi berilgan. Hud-hud orqali Saba malikasi haqida xabar topgan; malika oxir-oqibat Alloh yo‘liga kelgan. Bu ne’matlar unga shukr uchun berilgan.\n\n📖 Naml 15–44, Saba 12–14, Anbiyo 81–82."),
("Ilyos alayhissalom", "Ilyos alayhissalom Ba’l degan butga sig‘inayotgan qavmga yuborilgan.\n\nU qavmini Eng yaxshi Yaratuvchini qo‘yib, Ba’lga duo qilishdan ogohlantirdi. Qavmning aksari rad etdi; Allohning ixlosli bandalari esa najot topdi.\n\n📖 Saffot 123–132, An’om 85."),
("Alyasa’ alayhissalom", "Alyasa’ alayhissalom Qur’onda ikki joyda nomi zikr qilingan; An’om surasida Alloh olamlar orasidan afzal qilgan zotlar qatorida eslangan.\n\nTafsirlarda u Ilyos alayhissalomdan keyin kelgan, deyiladi; Qur’onda boshqa tafsilot yo‘q.\n\n📖 An’om 86, Sod 48."),
("Yunus alayhissalom", "Yunus alayhissalom Ninavo ahliga yuborilgan.\n\nQavmi iymon keltirmaganida u g‘azablanib ketib qoldi; keyin baliq uni yutdi. Baliq qornidagi zulmatda u “Sendan o‘zga iloh yo‘q, Sen pok-subhonsan, men zolimlardan bo‘ldim”, deb tavba qildi. Alloh uni qutqardi; qavmi esa iymon keltirib azobdan qutuldi.\n\n📖 Anbiyo 87–88, Saffot 139–148, Yunus 98."),
("Zakariyo alayhissalom", "Zakariyo alayhissalom Maryamning homiysi bo‘lgan.\n\nU keksayib qolgan, ahli esa farzandsiz edi; shunga qaramay Allohdan farzand so‘rab, yashirin duo qildi. Alloh unga Yahyo ismli o‘g‘il xushxabarini berdi.\n\n📖 Oli Imron 37–41, Maryam 1–11."),
("Yahyo alayhissalom", "Yahyo alayhissalom Zakariyo alayhissalomning o‘g‘li.\n\nAlloh unga yoshligidayoq hikmat bergan. U mehribon, pok, taqvodor va ota-onasiga yaxshilik qiluvchi, qo‘pol va isyonkor bo‘lmagan zot sifatida ta’riflanadi.\n\n📖 Oli Imron 39, Maryam 12–15."),
("Iso alayhissalom", "Iso alayhissalom Maryamning o‘g‘li, ulul azm payg‘ambarlardan.\n\nAlloh uni otasiz yaratgan; Qur’onda bu Odamning yaratilishiga o‘xshatiladi. Beshikda gapirib, “Men Allohning bandasiman”, degan. Alloh izni bilan kasallarni shifolagan, loydan qush shaklini yasab puflaganida u tirik qush bo‘lgan. Unga Injil nozil qilingan; hawariylar uning yordamchilari edi. Qur’on ta’limotiga ko‘ra, uni o‘ldirishmagan va osishmagan; Alloh uni o‘z huzuriga ko‘targan.\n\n📖 Oli Imron 45–59, Maryam 16–36, Niso 157–158, Moida 110–120."),
("Muhammad ﷺ", "Muhammad ﷺ — payg‘ambarlarning oxirgisi (Ahzob 40). Alloh uni butun insoniyatga rahmat sifatida yubordi.\n\nU zotning hayotlari haqida batafsil ma’lumot uchun bosh menyudagi “🌙 Payg‘ambarimiz Muhammad ﷺ hayoti” bo‘limiga o‘ting."),
]

# ---- Payg‘ambarlar bo‘yicha yangi testlar ----
PROPHET_QUIZ = [
("Birinchi inson va ko‘pchilik ulamolar fikricha birinchi payg‘ambar kim?", ['Odam alayhissalom', 'Nuh alayhissalom', 'Idris alayhissalom'], 0, "Odam alayhissalom Alloh yaratgan birinchi inson va birinchi payg‘ambar deb e’tiqod qilinadi (Baqara 30–37)."),
("Odam alayhissalomning juftlari kim?", ['Havvo', 'Sora', 'Hojar'], 0, "Odam alayhissalomning juftlari Havvo onamizdir."),
("Farishtalar Odam alayhissalomga Alloh amri bilan nima qildilar?", ['Ta’zim sajdasi qildilar', 'Unga duo o‘qidilar', 'Undan yuz o‘girdilar'], 0, "Farishtalar sajda qildilar, Iblis bosh tortdi (Baqara 34)."),
("Iblis Odamga sajda qilishdan nega bosh tortgan?", ['Takabburlik qilgani uchun', 'Buyruqni eshitmagani uchun', 'Kasal bo‘lgani uchun'], 0, "Iblis takabburlik qilib: “Men undan yaxshiman”, degan (A’rof 12)."),
("Odam va Havvo xatoga yo‘l qo‘ygach nima qildilar?", ['Tavba qildilar va Alloh qabul qildi', 'Shaytonga ergashdilar', 'Gunohda turib oldilar'], 0, "Ular tavba qildilar va Alloh tavbalarini qabul qildi (Baqara 37, A’rof 23)."),
("Od qavmiga qaysi payg‘ambar yuborilgan?", ['Hud alayhissalom', 'Solih alayhissalom', 'Lut alayhissalom'], 0, "Hud alayhissalom Od qavmiga yuborilgan (A’rof 65)."),
("Samud qavmiga qaysi payg‘ambar yuborilgan?", ['Solih alayhissalom', 'Hud alayhissalom', 'Shuayb alayhissalom'], 0, "Solih alayhissalom Samud qavmiga yuborilgan (A’rof 73)."),
("Od qavmi qanday azob bilan halok qilingan?", ['Kuchli sovuq shamol bilan', 'Suv toshqini bilan', 'Yer yutishi bilan'], 0, "Haqqa surasida Od qavmiga kuchli sovuq shamol yuborilgani aytiladi (Haqqa 6)."),
("Qur’onga ko‘ra, Nuh alayhissalom qavmi orasida qancha turgan?", ['950 yil', '100 yil', '500 yil'], 0, "Ankabut 14-oyatda “ellik yili kam ming yil” deyiladi, ya’ni 950 yil."),
("Nuh alayhissalomning kemasiga hayvonlardan nima olish buyurilgan?", ['Har turdan bir juft', 'Faqat uy hayvonlari', 'Faqat qushlar'], 0, "Hud 40-oyatda har narsadan bir juft olish buyurilgani bayon qilinadi."),
("Ibrohim alayhissalom butlarni sindirgach, qaysi birini butun qoldirgan?", ['Kattasini', 'Eng kichigini', 'Hammasini sindirgan'], 0, "Anbiyo 58-oyatga ko‘ra, kattasidan boshqasini parchalab tashladi."),
("Ibrohim alayhissalom qaysi laqab bilan mashhur?", ['Xalilulloh (Allohning do‘sti)', 'Kalimulloh', 'Zabihulloh'], 0, "Niso 125-oyatda Alloh Ibrohimni xalil — do‘st qilib olgani aytiladi."),
("Ka’ba poydevorini kimlar ko‘targan?", ['Ibrohim va Ismoil alayhimussalom', 'Nuh va Hud alayhimussalom', 'Muso va Horun alayhimussalom'], 0, "Baqara 127-oyatda Ibrohim va Ismoil Ka’ba poydevorini ko‘tarishgani zikr qilinadi."),
("Ismoil alayhissalomning onasi kim?", ['Hojar', 'Sora', 'Maryam'], 0, "Ismoil alayhissalomning onasi Hojar onamizdir."),
("Zamzam chashmasining qaynab chiqishi mashhur rivoyatda kim bilan bog‘liq?", ['Hojar va Ismoil', 'Muso va Horun', 'Nuh va o‘g‘illari'], 0, "Sahih rivoyatga ko‘ra, Hojar va go‘dak Ismoil Makkada qolganda Zamzam paydo bo‘lgan."),
("Ibrohim alayhissalom o‘g‘lini qurbon qilishga tayyor bo‘lganda Alloh nima berdi?", ['Katta qurbonlik', 'Katta mol-mulk', 'Yangi yer'], 0, "Saffot 107-oyat: “Biz uni katta qurbonlik bilan fidya qildik”."),
("Qurbon hayiti qaysi voqea xotirasi bilan bog‘liq?", ['Ibrohim va Ismoil alayhimussalom sinovi', 'Badr jangi', 'Hijrat'], 0, "Qurbonlik an’anasi Ibrohim va Ismoil alayhimussalom voqeasi xotirasi bilan bog‘lanadi."),
("Ishoq alayhissalomning o‘g‘li bo‘lgan payg‘ambar kim?", ['Ya’qub alayhissalom', 'Yusuf alayhissalom', 'Ismoil alayhissalom'], 0, "Ya’qub alayhissalom Ishoqning o‘g‘lidir (Baqara 132)."),
("Ya’qub alayhissalomning laqabi qaysi?", ['Isroil', 'Xalil', 'Zunnun'], 0, "Ya’qub alayhissalom Isroil deb ham ataladi; Bani Isroil nomi shundan."),
("Yusuf alayhissalom tushida nechta yulduzni ko‘rgan?", ['O‘n bir', 'Yetti', 'O‘n ikki'], 0, "Yusuf 4-oyat: o‘n bir yulduz, quyosh va oy unga sajda qilayotgani."),
("Yusuf alayhissalom podshohdan nimani so‘ragan?", ['Yer g‘aznalari ustidan mas’ullikni', 'Katta saroyni', 'Lashkar boshlig‘ligini'], 0, "Yusuf 55-oyatga ko‘ra, u yer g‘aznalari mas’uli qilinishini so‘radi."),
("Ya’qub alayhissalomning ko‘rish qobiliyati nima orqali qaytgan?", ['Yusufning ko‘ylagi yuziga tashlanishi bilan', 'Zamzam suvi bilan', 'Dengiz suvi bilan'], 0, "Yusuf 93–96: ko‘ylak yuziga tashlanganda Ya’qub ko‘rar bo‘ldi."),
("Qur’on Yusuf qissasini qanday ataydi?", ['Eng go‘zal qissa', 'Eng qisqa qissa', 'Eng og‘ir qissa'], 0, "Yusuf 3-oyatda bu qissa “ahsanul qasas” — eng go‘zal qissa deb ataladi."),
("Muso alayhissalom go‘dakligida qayerga qo‘yilgan?", ['Sandiqqa solinib daryoga', 'G‘orga', 'Quduqqa'], 0, "Qasas 7 va Toha 39-oyatlarda Musoni sandiqqa solib daryoga tashlash vahiy qilingani bayon etiladi."),
("Muso alayhissalom Alloh kalomini qayerda eshitgan?", ['Tur tog‘i yonida', 'Uhud tog‘i yonida', 'Nur tog‘ida'], 0, "Toha 12–14: Muso Tuvo vodiysida, Tur tomonda Alloh nidosini eshitdi."),
("Muso alayhissalomga qaysi kitob berilgan?", ['Tavrot', 'Injil', 'Zabur'], 0, "Muso alayhissalomga Tavrot nozil qilingan."),
("Iso alayhissalomga qaysi kitob nozil qilingan?", ['Injil', 'Tavrot', 'Zabur'], 0, "Iso alayhissalomga Injil nozil qilingan (Moida 46)."),
("Muso alayhissalomning qo‘li qanday mo‘jiza bo‘lgan?", ['Nur sochib oppoq bo‘lishi', 'Undan suv oqishi', 'Temirni yumshatishi'], 0, "Toha 22 va Naml 12: qo‘lini qo‘ynidan chiqarganda ravshan oq bo‘lardi (yad bayzo)."),
("Fir’avn va lashkari qanday halok bo‘lgan?", ['Dengizda g‘arq bo‘lib', 'Zilzilada', 'Shamolda'], 0, "Bani Isroil o‘tgach, Fir’avn va lashkari dengizda g‘arq qilindi (Shuaro 63–66)."),
("Dovud alayhissalom qaysi dushmanni mag‘lub qilgan?", ['Jolutni', 'Fir’avnni', 'Abrahani'], 0, "Baqara 251-oyatda Dovud Jolutni o‘ldirgani zikr qilinadi."),
("Dovud alayhissalom bilan birga tog‘lar va qushlar nima qilgan?", ['Allohni tasbeh aytgan', 'Uni himoya qilgan', 'Yo‘l ko‘rsatgan'], 0, "Sod 18–19 va Anbiyo 79: tog‘lar va qushlar Dovud bilan tasbeh aytgan."),
("Sulaymon alayhissalomga Alloh izni bilan nimalar bo‘ysundirilgan?", ['Shamol va jinlar', 'Faqat dengiz', 'Faqat yer'], 0, "Saba 12 va Anbiyo 81–82: Sulaymonga shamol va jinlar bo‘ysundirilgan."),
("Naml surasida Sulaymon alayhissalom bilan bog‘liq qaysi qush zikr qilinadi?", ['Hud-hud', 'Kaptar', 'Burgut'], 0, "Naml 20–22: Sulaymon hud-hudni so‘raganda u Saba haqida xabar keltirgan."),
("Yunus alayhissalom baliq qornidagi zulmatda qaysi zikrni aytgan?", ['Lo ilaha illa anta, subhonaka inni kuntu minaz-zolimin', 'Rabbi zidni ilma', 'Rabbano otina fid-dunya hasana'], 0, "Anbiyo 87-oyatdagi bu duo Yunus alayhissalomning duosidir."),
("Yunus alayhissalom qavmi qachon azobdan qutulgan?", ['Iymon keltirgach', 'Shahardan ketgach', 'Yomg‘ir yoqqach'], 0, "Yunus 98-oyatga ko‘ra, Yunus qavmi iymon keltirgani uchun azobdan qutuldi."),
("Zakariyo alayhissalom Allohdan nimani so‘ragan?", ['Farzand', 'Mol-mulk', 'Podshohlik'], 0, "Maryam 3–6: Zakariyo yashirin tarzda Allohdan farzand so‘radi."),
("Yahyo alayhissalomga yoshligida nima berilgan?", ['Hikmat', 'Podshohlik', 'Saroy'], 0, "Maryam 12-oyat: “Biz unga go‘dakligidayoq hikmat berdik”."),
("Iso alayhissalom beshikda gapirganida nima degan?", ['Men Allohning bandasiman', 'Men podshohman', 'Men farishtaman'], 0, "Maryam 30-oyat: “Men Allohning bandasiman, menga Kitob berdi”."),
("Iso alayhissalom Alloh izni bilan loydan nima yasagan?", ['Qush shaklini', 'Uy', 'Kema'], 0, "Oli Imron 49-oyat: loydan qush shaklini yasab puflasa, Alloh izni bilan qush bo‘lardi."),
("Qur’onda Iso alayhissalomning yaratilishi kimning yaratilishiga o‘xshatilgan?", ['Odam alayhissalom', 'Nuh alayhissalom', 'Yunus alayhissalom'], 0, "Oli Imron 59-oyat: Isoning misoli Odam misolidek."),
("Iso alayhissalomning yordamchi izdoshlari qanday ataladi?", ['Hawariylar', 'Ansorlar', 'Muhojirlar'], 0, "Oli Imron 52-oyatda Isoning yordamchilari hawariylar deb atalgan."),
("Ilyos alayhissalom qavmi qaysi butga sig‘ingan?", ['Ba’l', 'Lot', 'Uzzo'], 0, "Saffot 125-oyat: “Ba’lga duo qilib, Eng yaxshi Yaratuvchini tashlaysizlarmi?”"),
("Qur’onda Idris alayhissalom qanday ta’riflangan?", ['Rostgo‘y payg‘ambar', 'Podshoh', 'Hakim'], 0, "Maryam 56-oyat: u “siddiq” — rostgo‘y payg‘ambar edi."),
("Ibrohim alayhissalomga nima nozil qilingan?", ['Sahifalar (suhuf)', 'Tavrot', 'Injil'], 0, "A’lo 18–19-oyatlarda Ibrohim va Musoning sahifalari zikr qilinadi."),
("Qaysi sura payg‘ambar nomi bilan atalgan?", ['Nuh', 'Fil', 'Kavsar'], 0, "Qur’onning 71-surasi Nuh surasidir."),
("Qur’onda Nuh va Lut alayhimussalomning xotinlari qanday kishilar sifatida eslanadi?", ['Kofirlarga misol sifatida', 'Solihalarga misol sifatida', 'Zohidlarga misol sifatida'], 0, "Tahrim 10-oyatda ular kofirlarga misol qilib keltirilgan."),
("Shuayb alayhissalom qavmini qaysi gunohdan qaytargan?", ['O‘lchov va tarozida aldashdan', 'Ichkilikdan', 'Safar qilishdan'], 0, "Hud 84-oyat: “O‘lchov va tarozini kamaytirmanglar”."),
("Quyidagilardan qaysi biri Qur’onda nomi zikr qilingan payg‘ambar?", ['Zulkifl', 'Abu Lahab', 'Bilol'], 0, "Zulkifl alayhissalom Anbiyo va Sod suralarida zikr qilingan."),
("Alloh Musoga yordamchi qilib kimni yubordi?", ['Akasi Horunni', 'Do‘sti Yusufni', 'O‘g‘li Ismoilni'], 0, "Toha 29–36: Muso akasi Horunni yordamchi qilishni so‘radi va Alloh uni bergan."),
]

# ---- Boshqa yangi testlar: siyrat, Qur’on, ibodat, aqida va ulamolar ----
EXTRA_ISLAMIC_QUIZ = [
# Siyrat
("Payg‘ambarimiz ﷺ tug‘ilgan yil qanday nom bilan ataladi?", ['Fil yili', 'Hijrat yili', 'Qadr yili'], 0, "An’anaviy siyrat manbalarida u zot tug‘ilgan yil Fil yili deb ataladi."),
("Payg‘ambarimiz ﷺ ga birinchi vahiy kelganda u zot necha yoshda edilar?", ['40 yoshda', '25 yoshda', '60 yoshda'], 0, "Payg‘ambarlik 40 yoshda vahiy bilan boshlangan."),
("Payg‘ambarimiz ﷺ Madinada taxminan necha yil yashadilar?", ['Taxminan 10 yil', '3 yil', '20 yil'], 0, "Hijratdan vafotgacha taxminan o‘n yil o‘tgan."),
("Payg‘ambarimiz ﷺ vafot etganda necha yoshda edilar?", ['63 yoshda', '50 yoshda', '80 yoshda'], 0, "Sahih rivoyatlarga ko‘ra, u zot 63 yoshda vafot etganlar."),
("Payg‘ambarimiz ﷺ Xadicha onamizga uylanganlarida necha yoshda edilar?", ['25 yoshda', '15 yoshda', '40 yoshda'], 0, "U zot 25 yoshlarida Xadicha binti Xuvaylidga uylanganlar."),
("Voyaga yetgan erkaklardan birinchi iymon keltirgan sahoba kim?", ['Abu Bakr as-Siddiq', 'Umar ibn Xattob', 'Usmon ibn Affon'], 0, "Abu Bakr roziyallohu anhu erkaklardan birinchi iymon keltirganlar sifatida mashhur."),
("Bolalardan birinchi iymon keltirgan sahoba kim?", ['Ali ibn Abu Tolib', 'Zubayr ibn Avvom', 'Anas ibn Molik'], 0, "Ali roziyallohu anhu yoshlikda iymon keltirgan sahobalardandir."),
("Ali ibn Abu Tolib Payg‘ambarimiz ﷺ ning kimlari edilar?", ['Amakivachchasi va kuyovi', 'Tog‘asi', 'Bobosi'], 0, "Ali roziyallohu anhu u zotning amakivachchasi va Fotima onamizning eri edilar."),
("Abu Tolib Payg‘ambarimiz ﷺ ning kimlari edilar?", ['Amakisi va himoyachisi', 'Otasi', 'Qaynotasi'], 0, "Abu Tolib u zotni yoshligidan himoya qilgan amakilari edilar."),
("Masad surasida zikr qilingan Payg‘ambarimiz ﷺ ning amakisi kim?", ['Abu Lahab', 'Abu Tolib', 'Hamza'], 0, "Masad surasi Abu Lahabning qilmishiga ishora qiladi."),
("Musulmonlarni panohiga olgan Habashiston podshosining nomi nima?", ['Najoshiy', 'Hirakl', 'Kisro'], 0, "Habashistonga hijrat qilgan musulmonlarga Najoshiy panoh bergan."),
("Isro voqeasida Payg‘ambarimiz ﷺ Masjidul Haromdan qaysi masjidgacha olib borilganlar?", ['Masjidul Aqso', 'Masjidul Nabaviy', 'Qubo masjidi'], 0, "Isro 1-oyatda Masjidul Haromdan Masjidul Aqsogacha olib borilgani zikr qilinadi."),
("Mi’roj kechasida qaysi ibodat farz qilingani sahih rivoyatlarda keladi?", ['Besh vaqt namoz', 'Ramazon ro‘zasi', 'Haj'], 0, "Besh vaqt namoz Mi’roj kechasi farz qilingani mashhur sahih rivoyatlarda bayon etiladi."),
("Madinaning hijratdan oldingi nomi nima edi?", ['Yasrib', 'Taybo', 'Toif'], 0, "Madina avval Yasrib deb ataldi, keyinchalik Madinatun-Nabiy — Madina nomi bilan mashhur bo‘ldi."),
("Hijratdan so‘ng Madina yaqinida qurilgan birinchi masjid qaysi?", ['Qubo masjidi', 'Masjidul Aqso', 'Masjidul Haram'], 0, "Qubo masjidi Islomda qurilgan birinchi masjid sifatida tanilgan."),
("Namozda avval qaysi tomonga yuzlanilgan, keyin qibla Ka’baga o‘zgargan?", ['Baytul Maqdis tomonga', 'Madina tomonga', 'Toif tomonga'], 0, "Baqara 144-oyat qiblaning Ka’baga o‘zgarishiga ishora qiladi."),
("Badr jangida musulmonlar soni taxminan nechta bo‘lgan?", ['Taxminan 313 kishi', '10 000 kishi', '100 kishi'], 0, "Rivoyatlarda Badr ishtirokchilari soni taxminan 313 deb keltiriladi."),
("Uhud jangida shahid bo‘lgan Payg‘ambarimiz ﷺ ning amakisi kim?", ['Hamza ibn Abdulmuttalib', 'Abbos ibn Abdulmuttalib', 'Abu Tolib'], 0, "Hamza roziyallohu anhu Uhud jangida shahid bo‘lganlar."),
("Xandaq jangida xandaq qazish maslahatini bergan sahoba kim?", ['Salmon Forsiy', 'Bilol Habashiy', 'Abu Zar G‘iforiy'], 0, "Xandaq qazish maslahati Salmon Forsiyga nisbat beriladi."),
("Hudaybiya sulhi musulmonlar bilan qaysi qabila o‘rtasida tuzilgan?", ['Quraysh', 'Aws', 'Xazraj'], 0, "Hudaybiya sulhi Payg‘ambarimiz ﷺ va Quraysh vakillari o‘rtasida tuzilgan."),
("Payg‘ambarimiz ﷺ ning yagona haji qanday nomlanadi?", ['Vido haji', 'Fath haji', 'Umra haji'], 0, "10-hijriy yilda ado etilgan haj “Hajjatul Vido” — xayrlashuv haji deb ataladi."),
("Payg‘ambarimiz ﷺ qayerga dafn etilganlar?", ['Oisha onamiz hujrasiga (Madinada)', 'Makkada Ka’ba yoniga', 'Quddusga'], 0, "U zot Madinada, Oisha onamiz hujrasida dafn qilingan; bu joy hozir Masjidul Nabaviy ichida."),
("Usmon ibn Affon qaysi laqab bilan mashhur?", ['Zun-nurayn', 'Foruq', 'Siddiq'], 0, "Usmon roziyallohu anhu Payg‘ambarimiz ﷺ ning ikki qiziga uylangani uchun Zun-nurayn deb atalgan."),
("Umar ibn Xattob qaysi laqab bilan mashhur?", ['Foruq', 'Siddiq', 'Sayfulloh'], 0, "Umar roziyallohu anhu al-Foruq — haq va botilni ajratuvchi laqabi bilan mashhur."),
("Abu Bakr roziyallohu anhu qaysi laqab bilan mashhur?", ['Siddiq', 'Foruq', 'Zun-nurayn'], 0, "Abu Bakr roziyallohu anhu as-Siddiq — tasdiqlovchi, rostgo‘y laqabi bilan mashhur."),
("Xolid ibn Validning mashhur laqabi qaysi?", ['Sayfulloh (Allohning qilichi)', 'Foruq', 'Aminul ummat'], 0, "Hadislarda Xolid ibn Valid “Allohning qilichlaridan bir qilich” deb ta’riflangan."),
("Fotima onamiz kimga turmushga chiqqan?", ['Ali ibn Abu Tolib', 'Usmon ibn Affon', 'Abu Bakr'], 0, "Fotima roziyallohu anho Ali roziyallohu anhuga turmushga chiqqan."),
("Hasan va Husayn roziyallohu anhumo Payg‘ambarimiz ﷺ ning kimlari?", ['Nevaralari', 'O‘g‘illari', 'Amakivachchalari'], 0, "Ular Fotima va Ali roziyallohu anhumoning o‘g‘illari — Payg‘ambarimiz ﷺ nevaralaridir."),
("Oisha onamiz kimning qizi?", ['Abu Bakrning', 'Umarning', 'Alining'], 0, "Oisha roziyallohu anho Abu Bakr as-Siddiqning qizidir."),
("Qur’on taxminan necha yil davomida nozil bo‘lgan?", ['23 yil', '3 yil', '40 yil'], 0, "Qur’on vahiy sifatida taxminan 23 yil davomida bo‘lib-bo‘lib nozil bo‘lgan."),
("Qur’on dastlab bir mushafga qaysi xalifa davrida jamlana boshlagan?", ['Abu Bakr davrida', 'Ali davrida', 'Umar ibn Abdulaziz davrida'], 0, "Abu Bakr davrida Zayd ibn Sobit rahbarligida Qur’on jamlandi."),
("Qur’on mushaflari nusxalanib shaharlarga yuborilishi qaysi xalifa davrida bo‘lgan?", ['Usmon ibn Affon davrida', 'Umar davrida', 'Ali davrida'], 0, "Usmon roziyallohu anhu davrida mushaflar nusxalanib asosiy shaharlarga yuborilgan."),
("Hijriy taqvim qaysi xalifa davrida joriy etilgan?", ['Umar ibn Xattob', 'Abu Bakr', 'Usmon ibn Affon'], 0, "Hijriy sana Umar roziyallohu anhu davrida joriy qilingan."),
("Payg‘ambarimiz ﷺ ning nechta qizlari bo‘lgan (mashhur rivoyatga ko‘ra)?", ['To‘rtta', 'Ikkita', 'Oltita'], 0, "Zaynab, Ruqayya, Ummu Kulsum va Fotima roziyallohu anhunna."),
# Qur’on
("Qur’on qaysi oyda nozil bo‘la boshlagan?", ['Ramazon', 'Muharram', 'Zulhijja'], 0, "Baqara 185-oyat: Ramazon oyida Qur’on nozil qilindi."),
("Qaysi sura boshida Basmala (Bismillah) yozilmaydi?", ['Tavba', 'Yunus', 'Hud'], 0, "Tavba (Baro’a) surasi boshida Basmala yo‘q."),
("Mulk surasi nechta oyatdan iborat?", ['30', '20', '50'], 0, "Mulk surasi 30 oyatdan iborat."),
("Ixlos surasi nechta oyatdan iborat?", ['4', '3', '6'], 0, "Ixlos surasi 4 oyatdan iborat."),
("Falaq surasi nechta oyatdan iborat?", ['5', '3', '7'], 0, "Falaq surasi 5 oyatdan iborat."),
("Nos surasi nechta oyatdan iborat?", ['6', '4', '8'], 0, "Nos surasi 6 oyatdan iborat."),
("Yosin surasi nechta oyatdan iborat?", ['83', '40', '110'], 0, "Yosin surasi 83 oyatdan iborat."),
("“Mu’avvizatayn” deb atalgan ikki sura qaysi?", ['Falaq va Nos', 'Fotiha va Baqara', 'Kavsar va Ixlos'], 0, "Falaq va Nos suralari panoh so‘rash mazmuni sababli mu’avvizatayn deyiladi."),
("Qaysi surani juma kuni o‘qish mustahab deyilgan?", ['Kahf', 'Masad', 'Fil'], 0, "Hadislarda juma kuni Kahf surasini o‘qish tavsiya qilingan."),
("Hadisda Qur’onning uchdan biriga tenglashtirilgan sura qaysi?", ['Ixlos', 'Kavsar', 'Asr'], 0, "Sahih Buxoriyda Ixlos surasi Qur’onning uchdan biriga tenglashtirilgani rivoyat qilinadi."),
("Qur’on o‘qishdan oldin nima aytiladi?", ['A’uzu billahi minash-shaytonir-rojim', 'Subhanalloh', 'Alhamdulillah'], 0, "Nahl 98-oyat: Qur’on o‘qiganda quvilgan shaytondan Allohga panoh so‘rang."),
("Fotihadan keyingi sura qaysi?", ['Baqara', 'Oli Imron', 'Niso'], 0, "Mushaf tartibida 1-sura Fotiha, 2-sura Baqara."),
("Qur’onning 3-surasi qaysi?", ['Oli Imron', 'Niso', 'Moida'], 0, "3-sura Oli Imron surasidir."),
("Rahmon surasida qayta-qayta keladigan savol mazmuni qaysi?", ['Robbingizning qaysi ne’matlarini inkor qilasiz?', 'Qachon qiyomat bo‘ladi?', 'Kim bizga yo‘l ko‘rsatadi?'], 0, "Rahmon surasida bu savol ko‘p marta takrorlanadi."),
("Kahf surasida qaysi mashhur qissa bor?", ['G‘or sohiblari', 'Fil egalari', 'Abu Lahab qissasi'], 0, "Kahf surasida G‘or sohiblari qissasi bayon qilinadi."),
("Fil surasi nima haqida?", ['Ka’bani buzmoqchi bo‘lgan fil lashkari haqida', 'Hijrat haqida', 'Badr jangi haqida'], 0, "Fil surasi Ka’bani buzmoqchi bo‘lgan lashkarning halok bo‘lishini eslatadi."),
("Quyidagilardan qaysi biri Madaniy sura?", ['Baqara', 'Alaq', 'Fil'], 0, "Baqara Madinada nozil bo‘lgan sura; Alaq va Fil Makkiy suralar."),
("Qaysi surada Luqmon o‘g‘liga nasihat qiladi?", ['Luqmon surasida', 'Yunus surasida', 'Hud surasida'], 0, "Luqmon surasida Luqmonning o‘g‘liga nasihatlari bayon qilinadi."),
("Qur’onda ismi zikr qilingan yagona ayol kim?", ['Maryam', 'Xadicha', 'Osiyo'], 0, "Qur’onda faqat Maryamning ismi aniq zikr qilingan."),
("“Furqon” so‘zi Qur’on haqida nimani anglatadi?", ['Haq va botilni ajratuvchi', 'Yig‘uvchi', 'Qissa'], 0, "Furqon — haq bilan botilni ajratuvchi degani; Qur’onning nomlaridan biri."),
# Ibodat
("Peshin namozining farz qismi necha rakat?", ['4', '2', '3'], 0, "Peshin namozining farzi to‘rt rakat."),
("Asr namozining farz qismi necha rakat?", ['4', '3', '2'], 0, "Asr namozining farzi to‘rt rakat."),
("Shom namozining farz qismi necha rakat?", ['3', '2', '4'], 0, "Shom namozining farzi uch rakat."),
("Bomdod namozining farz qismi necha rakat?", ['2', '3', '4'], 0, "Bomdod namozining farzi ikki rakat."),
("Xufton namozining farz qismi necha rakat?", ['4', '2', '3'], 0, "Xufton namozining farzi to‘rt rakat."),
("Hanafiy mazhabida vitr namozi necha rakat?", ['3', '1', '5'], 0, "Hanafiy mazhabida vitr uch rakat va vojib hisoblanadi."),
("Hayit namozi necha rakat?", ['2', '3', '4'], 0, "Hayit namozi ikki rakat bo‘lib, undan keyin xutba o‘qiladi."),
("Hanafiy mazhabida taroveh namozi necha rakat?", ['20', '8', '12'], 0, "Hanafiy mazhabida taroveh 20 rakat."),
("Janoza namozida nechta takbir aytiladi?", ['4', '2', '6'], 0, "Janoza namozida to‘rt takbir aytiladi."),
("Namozni boshlash uchun aytiladigan birinchi “Allohu akbar” nima deyiladi?", ['Takbiri tahrima', 'Takbiri tashriq', 'Takbiri azon'], 0, "Takbiri tahrima namozga kirishni anglatadi."),
("Azon so‘zlaridan “Allohu akbar” nimani anglatadi?", ['Alloh eng ulug‘dir', 'Alloh kechirimlidir', 'Alloh yagonadir'], 0, "“Allohu akbar” — Alloh eng ulug‘dir."),
("Tahoratda qo‘llar qayergacha yuviladi?", ['Tirsakkacha (tirsak bilan)', 'Bilakkacha', 'Yelkagacha'], 0, "Moida 6-oyat: yuzlaringizni va qo‘llaringizni tirsaklargacha yuvinglar."),
("Tahoratda yuvilmay, mas’h qilinadigan a’zo qaysi?", ['Bosh', 'Yuz', 'Qo‘l'], 0, "Moida 6-oyatda boshga mas’h tortish zikr qilingan."),
("Ro‘zadorning tong otishdan oldin yeydigan ovqati nima deyiladi?", ['Saharlik', 'Iftor', 'Peshin'], 0, "Saharlik ro‘zani boshlashdan oldingi taomdir."),
("Ro‘zani ochish nima deyiladi?", ['Iftor', 'Saharlik', 'Sadaqa'], 0, "Iftor — quyosh botgach ro‘zani ochish."),
("Pul va oltin-kumush zakoti odatda necha foiz?", ['2,5 %', '10 %', '20 %'], 0, "Zakot nisobga yetgan mol-mulkdan qirqdan biri, ya’ni 2,5 % miqdorida beriladi."),
("Qur’onga ko‘ra, zakot nechta toifaga beriladi?", ['8 ta', '3 ta', '5 ta'], 0, "Tavba 60-oyatda zakot sarflanadigan sakkiz toifa sanab o‘tilgan."),
("Hajda Safo va Marva o‘rtasida yurish nima deyiladi?", ['Sa’y', 'Tavof', 'Ihrom'], 0, "Safo va Marva o‘rtasidagi yurish sa’y deyiladi."),
("Hajda Ka’bani aylanish nima deyiladi?", ['Tavof', 'Sa’y', 'Vuquf'], 0, "Ka’ba atrofida yetti marta aylanish tavof deyiladi."),
("Haj va umra uchun kiyiladigan maxsus kiyim nima deyiladi?", ['Ihrom', 'Jubba', 'Izor'], 0, "Haj yoki umra niyatida kiyiladigan maxsus kiyim ihrom deyiladi."),
("Ka’bada joylashgan qora tosh nima deyiladi?", ['Hajarul Asvad', 'Maqomi Ibrohim', 'Hijr'], 0, "Hajarul Asvad — Ka’ba burchagidagi qora tosh."),
("Hajda qaysi joyda turish hajning asosi hisoblanadi?", ['Arafot', 'Muzdalifa', 'Mino'], 0, "Hadisda Haj Arafotda turishdir, deyilgan."),
("Umra yilning qaysi vaqtida ado etilishi mumkin?", ['Yil davomida', 'Faqat Ramazonda', 'Faqat Zulhijjada'], 0, "Umra hajdan farqli ravishda yil davomida ado etilishi mumkin."),
# Aqida va axloq
("Tavhid nimani anglatadi?", ['Allohning yagonaligiga ishonish', 'Namoz vaqtlarini bilish', 'Qur’onni yod olish'], 0, "Tavhid — Allohning yagonaligiga va Undan o‘zga iloh yo‘qligiga ishonish."),
("Shirk nima?", ['Allohga sherik qo‘shish', 'Tavba qilish', 'Sadaqa berish'], 0, "Shirk — Allohga ibodatda yoki ilohiylikda sherik qo‘shish."),
("Qiyomatda Sur chaluvchi farishta kim?", ['Isrofil', 'Mikoil', 'Jabroil'], 0, "Sur chalish Isrofil farishtaga nisbat beriladi."),
("Yomg‘ir va rizq bilan mas’ul deb tanilgan farishta kim?", ['Mikoil', 'Isrofil', 'Jabroil'], 0, "Mikoil alayhissalom tafsir manbalarida yomg‘ir va rizq bilan bog‘liq zikr qilinadi."),
("Insonning amallarini yozuvchi farishtalar qanday ataladi?", ['Kiromon kotibin', 'Munkar va Nakir', 'Hamalatul arsh'], 0, "Infitor 10–12: hurmatli yozuvchilar — Kiromon kotibin."),
("Qiyomat kunida amallar o‘lchanadigan tarozi nima deyiladi?", ['Mizon', 'Sirot', 'Kavsar'], 0, "Mizon — qiyomatdagi adolat tarozisi."),
("Qiyomatda do‘zax ustiga qo‘yiladigan ko‘prik nima deyiladi?", ['Sirot', 'Mizon', 'Havz'], 0, "Sirot — do‘zax ustidagi ko‘prik."),
("Imom Buxoriy qaysi yurtdan?", ['Buxorodan', 'Samarqanddan', 'Xivadan'], 0, "Imom Muhammad ibn Ismoil al-Buxoriy Buxoroda tug‘ilgan."),
("“Sahihayn” deb qaysi ikki hadis to‘plami aytiladi?", ['Buxoriy va Muslim', 'Termiziy va Abu Dovud', 'Molik va Ahmad'], 0, "Sahihayn — Sahih al-Buxoriy va Sahih Muslim."),
("Imom Termiziy qaysi shahardan?", ['Termizdan', 'Buxorodan', 'Toshkentdan'], 0, "Imom Termiziy Termiz yaqinida tug‘ilgan."),
("Imom Moturidiy qaysi shahar bilan bog‘liq?", ['Samarqand', 'Madina', 'Bag‘dod'], 0, "Abu Mansur al-Moturidiy Samarqandda yashab ijod qilgan."),
("Hanafiy mazhabining asoschisi kim?", ['Imom A’zam Abu Hanifa', 'Imom Molik', 'Imom Shofe’iy'], 0, "Hanafiy mazhabi Imom A’zam Abu Hanifa nomi bilan bog‘liq."),
("Fiqhdagi to‘rt sunniy mazhabdan biri qaysi?", ['Hanbaliy', 'Buxoriy', 'Naqshbandiy'], 0, "To‘rt mazhab: Hanafiy, Molikiy, Shofe’iy, Hanbaliy."),
("Shariatning birinchi va asosiy manbai nima?", ['Qur’on', 'Qiyos', 'Urf'], 0, "Shariatning birinchi manbai Qur’ondir."),
("Sahih Buxoriydagi birinchi hadis nima haqida?", ['Amallar niyatga bog‘liqligi haqida', 'Namoz vaqti haqida', 'Zakot haqida'], 0, "Birinchi hadis: “Amallar niyatlarga bog‘liqdir”."),
("Hadisga ko‘ra, eng yaxshi kishilar kimlar?", ['Qur’onni o‘rganib, o‘rgatganlar', 'Eng boylar', 'Eng baland binoda yashaganlar'], 0, "Sahih Buxoriy 5027: “Sizlarning eng yaxshingiz Qur’onni o‘rganib, o‘rgatganingizdir”."),
("Hadisga ko‘ra, munofiqning alomatlaridan biri nima?", ['Gapirsa yolg‘on gapirishi', 'Ko‘p namoz o‘qishi', 'Ko‘p sadaqa qilishi'], 0, "Sahih hadisda munofiq alomatlaridan biri gapirsa yolg‘on gapirishi deb keltirilgan."),
("Jabroil hadisida “ihson” nima deb ta’riflangan?", ['Allohni ko‘rib turgandek ibodat qilish', 'Ko‘p mol yig‘ish', 'Faqat bayramda namoz o‘qish'], 0, "Ihson — Allohni ko‘rib turgandek ibodat qilishdir; ko‘rmasang ham U seni ko‘rib turibdi."),
("“Bismillahir-Rohmanir-Rohim” qanday ma’noni bildiradi?", ['Mehribon va rahmli Alloh nomi bilan', 'Alloh buyukdir', 'Hamd Allohgadir'], 0, "Basmala — Mehribon va rahmli Alloh nomi bilan (boshlayman)."),
("“Alhamdulillah” qanday ma’noni bildiradi?", ['Hamd Allohgadir', 'Alloh pokdir', 'Alloh xohlasa'], 0, "Alhamdulillah — barcha hamd Allohgadir."),
("“Subhanalloh” qanday ma’noni bildiradi?", ['Alloh pokdir', 'Hamd Allohgadir', 'Alloh buyukdir'], 0, "Subhanalloh — Alloh barcha nuqsonlardan pokdir."),
("“Insha Alloh” qanday ma’noni bildiradi?", ['Alloh xohlasa', 'Alloh rozi bo‘lsin', 'Alloh yordam bersin'], 0, "Insha Alloh — Alloh xohlasa."),
("“Astag‘firulloh” qanday ma’noni bildiradi?", ['Allohdan mag‘firat so‘rayman', 'Allohga hamd aytaman', 'Allohdan yordam so‘rayman'], 0, "Astag‘firulloh — Allohdan kechirim so‘rayman."),
("“Jazakallohu xayran” nimani anglatadi?", ['Alloh sizga yaxshilik bersin', 'Alloh sizni asrasin', 'Alloh sizni kechirsin'], 0, "Minnatdorchilik bildirish uchun aytiladigan duo: Alloh yaxshilik bersin."),
("Kalimai shahodat mazmuni qaysi?", ['Allohdan o‘zga iloh yo‘q va Muhammad ﷺ Allohning elchisidir', 'Alloh pokdir va hamd Unga xos', 'Allohdan boshqasiga tayanmayman'], 0, "Kalimai shahodat Islomga kirishning va birinchi ustunning asosidir."),
("Hujurot surasiga ko‘ra, mo‘minlar bir-birining nimasi?", ['Birodari', 'Raqibi', 'Xizmatkori'], 0, "Hujurot 10-oyat: “Mo‘minlar faqat birodarlardir”."),
("Qur’onda ota-onaga nima demaslik buyurilgan?", ['“Uf” deb ham demaslik', 'Salom bermaslik', 'Duo qilmaslik'], 0, "Isro 23-oyat: ota-onaga “uf” demang va ularni qaytarmang."),
("Qur’onga ko‘ra, Alloh nazdida oylar soni nechta?", ['12', '10', '13'], 0, "Tavba 36-oyat: Alloh nazdida oylar soni o‘n ikkita."),
("Hadisga ko‘ra, birodaringga tabassum qilish nima hisoblanadi?", ['Sadaqa', 'Gunoh', 'Mubohlik'], 0, "Termiziy rivoyat qilgan hadisda tabassum sadaqa deyilgan."),
]

# Qo‘shimcha arab tili testlari (so‘z boyligi, iboralar)
EXTRA_ARABIC_QUIZ = [
('“Do‘st” arab tilida qaysi?', ['صَدِيقٌ', 'مُعَلِّمٌ', 'طَالِبٌ'], 0, 'صَدِيقٌ — ṣadīqun — Do‘st.'),
('“O‘qituvchi” arab tilida qaysi?', ['مُعَلِّمٌ', 'طَالِبٌ', 'صَدِيقٌ'], 0, 'مُعَلِّمٌ — mu‘allimun — O‘qituvchi.'),
('“Talaba” arab tilida qaysi?', ['طَالِبٌ', 'مُعَلِّمٌ', 'طَبِيبٌ'], 0, 'طَالِبٌ — ṭālibun — Talaba.'),
('“Ona” arab tilida qaysi?', ['أُمٌّ', 'أَبٌ', 'أَخٌ'], 0, 'أُمٌّ — ummun — Ona.'),
('“Ota” arab tilida qaysi?', ['أَبٌ', 'أُمٌّ', 'أُخْتٌ'], 0, 'أَبٌ — abun — Ota.'),
('“Aka yoki uka” arab tilida qaysi?', ['أَخٌ', 'أُخْتٌ', 'أُمٌّ'], 0, 'أَخٌ — akhun — Aka yoki uka.'),
('“Opa yoki singil” arab tilida qaysi?', ['أُخْتٌ', 'أَخٌ', 'أَبٌ'], 0, 'أُخْتٌ — ukhtun — Opa yoki singil.'),
('“Katta” arab tilida qaysi?', ['كَبِيرٌ', 'صَغِيرٌ', 'جَدِيدٌ'], 0, 'كَبِيرٌ — kabīrun — Katta.'),
('“Kichik” arab tilida qaysi?', ['صَغِيرٌ', 'كَبِيرٌ', 'جَمِيلٌ'], 0, 'صَغِيرٌ — ṣaghīrun — Kichik.'),
('“Chiroyli” arab tilida qaysi?', ['جَمِيلٌ', 'قَدِيمٌ', 'صَغِيرٌ'], 0, 'جَمِيلٌ — jamīlun — Chiroyli.'),
('“Yangi” arab tilida qaysi?', ['جَدِيدٌ', 'قَدِيمٌ', 'كَبِيرٌ'], 0, 'جَدِيدٌ — jadīdun — Yangi.'),
('“Tun” arab tilida qaysi?', ['لَيْلٌ', 'يَوْمٌ', 'شَمْسٌ'], 0, 'لَيْلٌ — laylun — Tun.'),
('“Quyosh” arab tilida qaysi?', ['شَمْسٌ', 'قَمَرٌ', 'لَيْلٌ'], 0, 'شَمْسٌ — shamsun — Quyosh.'),
('“Oy” (osmondagi) arab tilida qaysi?', ['قَمَرٌ', 'شَمْسٌ', 'نَجْمٌ'], 0, 'قَمَرٌ — qamarun — Oy.'),
('“Sut” arab tilida qaysi?', ['حَلِيبٌ', 'شَايٌ', 'مَاءٌ'], 0, 'حَلِيبٌ — ḥalībun — Sut.'),
('“Choy” arab tilida qaysi?', ['شَايٌ', 'حَلِيبٌ', 'خُبْزٌ'], 0, 'شَايٌ — shāyun — Choy.'),
('“Olma” arab tilida qaysi?', ['تُفَّاحٌ', 'خُبْزٌ', 'حَلِيبٌ'], 0, 'تُفَّاحٌ — tuffāḥun — Olma.'),
('“To‘rt” soni arab tilida qaysi?', ['أَرْبَعَةٌ', 'ثَلَاثَةٌ', 'خَمْسَةٌ'], 0, 'أَرْبَعَةٌ — arba‘atun — To‘rt.'),
('“Besh” soni arab tilida qaysi?', ['خَمْسَةٌ', 'أَرْبَعَةٌ', 'عَشَرَةٌ'], 0, 'خَمْسَةٌ — khamsatun — Besh.'),
('“O‘n” soni arab tilida qaysi?', ['عَشَرَةٌ', 'خَمْسَةٌ', 'وَاحِدٌ'], 0, 'عَشَرَةٌ — ‘asharatun — O‘n.'),
('“Men musulmonman” (erkak) qaysi?', ['أَنَا مُسْلِمٌ', 'أَنَا طَالِبٌ', 'أَنَا جَائِعٌ'], 0, 'أَنَا مُسْلِمٌ — anā muslimun — Men musulmonman.'),
('“Alhamdulillah” qaysi?', ['الْحَمْدُ لِلَّهِ', 'شُكْرًا', 'عَفْوًا'], 0, 'الْحَمْدُ لِلَّهِ — al-ḥamdu lillāh — Hamd Allohgadir.'),
('“Xush kelibsiz” qaysi?', ['أَهْلًا وَسَهْلًا', 'إِلَى اللِّقَاءِ', 'لَا أَفْهَمُ'], 0, 'أَهْلًا وَسَهْلًا — ahlan wa sahlan — Xush kelibsiz.'),
('“Yoshingiz nechada?” (erkakka) qaysi?', ['كَمْ عُمْرُكَ؟', 'مَا اسْمُكَ؟', 'أَيْنَ بَيْتُكَ؟'], 0, 'كَمْ عُمْرُكَ؟ — kam ‘umruka? — Yoshingiz nechada?'),
('“Men yaxshiman” qaysi?', ['أَنَا بِخَيْرٍ', 'أَنَا جَائِعٌ', 'لَا أَفْهَمُ'], 0, 'أَنَا بِخَيْرٍ — anā bi-khayr — Men yaxshiman.'),
('“Nima uchun?” savol so‘zi qaysi?', ['لِمَاذَا', 'مَتَى', 'أَيْنَ'], 0, 'لِمَاذَا — limādhā — Nima uchun?'),
('“Qancha / nechta?” savol so‘zi qaysi?', ['كَمْ', 'مَنْ', 'كَيْفَ'], 0, 'كَمْ — kam — Qancha? Nechta?'),
('“Stol” arab tilida qaysi?', ['طَاوِلَةٌ', 'كُرْسِيٌّ', 'نَافِذَةٌ'], 0, 'طَاوِلَةٌ — ṭāwilatun — Stol.'),
('“Stul” arab tilida qaysi?', ['كُرْسِيٌّ', 'طَاوِلَةٌ', 'بَابٌ'], 0, 'كُرْسِيٌّ — kursiyyun — Stul.'),
('“Shahar” arab tilida qaysi?', ['مَدِينَةٌ', 'سُوقٌ', 'شَارِعٌ'], 0, 'مَدِينَةٌ — madīnatun — Shahar.'),
('“Bozor” arab tilida qaysi?', ['سُوقٌ', 'مَدِينَةٌ', 'مَسْجِدٌ'], 0, 'سُوقٌ — sūqun — Bozor.'),
('“Ko‘cha” arab tilida qaysi?', ['شَارِعٌ', 'سُوقٌ', 'بَيْتٌ'], 0, 'شَارِعٌ — shāri‘un — Ko‘cha.'),
('“Dars” arab tilida qaysi?', ['دَرْسٌ', 'قَلَمٌ', 'مَدْرَسَةٌ'], 0, 'دَرْسٌ — darsun — Dars.'),
('“Men arab tilini yaxshi ko‘raman” qaysi?', ['أَنَا أُحِبُّ اللُّغَةَ الْعَرَبِيَّةَ', 'أَنَا أَذْهَبُ إِلَى السُّوقِ', 'لَا أَفْهَمُ'], 0, 'أَنَا أُحِبُّ اللُّغَةَ الْعَرَبِيَّةَ — anā uḥibbu-l-lughata-l-‘arabiyya — Men arab tilini yaxshi ko‘raman.'),
]

_prophet_start = len(QUIZ_BANK)
QUIZ_BANK.extend(PROPHET_QUIZ)
PROPHET_QUIZ_IDS = list(range(_prophet_start, len(QUIZ_BANK)))
QUIZ_BANK.extend(EXTRA_ISLAMIC_QUIZ)
# ===================== QO‘SHIMCHA BO‘LIM TUGADI =====================

ARABIC_QUIZ_START = len(QUIZ_BANK)
ARABIC_QUIZ_BANK = [('Arab tilida “Assalomu alaykum” qanday yoziladi?', ['السَّلَامُ عَلَيْكُمْ', 'صَبَاحُ الْخَيْرِ', 'مَعَ السَّلَامَةِ'], 0, 'السَّلَامُ عَلَيْكُمْ — as-salāmu alaykum — Assalomu alaykum.'), ('“Va alaykum assalom” javobi qaysi?', ['وَعَلَيْكُمُ السَّلَامُ', 'شُكْرًا', 'نَعَمْ'], 0, 'وَعَلَيْكُمُ السَّلَامُ — wa alaykumu-s-salām — Va alaykum assalom.'), ('“Xayrli tong” arab tilida qaysi?', ['صَبَاحُ الْخَيْرِ', 'مَسَاءُ الْخَيْرِ', 'إِلَى اللِّقَاءِ'], 0, 'صَبَاحُ الْخَيْرِ — sabāhu-l-khayr — Xayrli tong.'), ('“Xayrli kech” arab tilida qaysi?', ['مَسَاءُ الْخَيْرِ', 'صَبَاحُ الْخَيْرِ', 'أَهْلًا'], 0, 'مَسَاءُ الْخَيْرِ — masā’u-l-khayr — Xayrli kech.'), ('“Rahmat” so‘zi qaysi?', ['شُكْرًا', 'عَفْوًا', 'آسِفٌ'], 0, 'شُكْرًا — shukran — Rahmat.'), ('“Iltimos” ma’nosida ko‘p ishlatiladigan ibora qaysi?', ['مِنْ فَضْلِكَ', 'لَا شُكْرَ', 'إِلَى اللِّقَاءِ'], 0, 'مِنْ فَضْلِكَ — min faḍlika — Iltimos (erkakka murojaat).'), ('“Ha” arab tilida qanday?', ['نَعَمْ', 'لَا', 'مَتَى'], 0, 'نَعَمْ — na‘am — Ha.'), ('“Yo‘q” arab tilida qanday?', ['لَا', 'نَعَمْ', 'مَرْحَبًا'], 0, 'لَا — lā — Yo‘q.'), ('“Ahvolingiz qanday?” (erkakka) qaysi?', ['كَيْفَ حَالُكَ؟', 'مَا اسْمُكَ؟', 'أَيْنَ تَسْكُنُ؟'], 0, 'كَيْفَ حَالُكَ؟ — kayfa ḥāluka? — Ahvolingiz qanday? (erkakka).'), ('“Ismingiz nima?” (erkakka) qaysi?', ['مَا اسْمُكَ؟', 'كَمْ عُمْرُكَ؟', 'مِنْ أَيْنَ أَنْتَ؟'], 0, 'مَا اسْمُكَ؟ — mā ismuka? — Ismingiz nima? (erkakka).'), ('“Mening ismim Ali” qanday aytiladi?', ['اِسْمِي عَلِيٌّ', 'أَنَا مِنْ عَلِيٍّ', 'هٰذَا عَلِيٌّ'], 0, 'اِسْمِي عَلِيٌّ — ismī ‘Aliyyun — Mening ismim Ali.'), ('“Men O‘zbekistondanman” qaysi?', ['أَنَا مِنْ أُوزْبِكِسْتَانَ', 'أَنَا فِي الْمَاءِ', 'أَنَا أَكْتُبُ'], 0, 'أَنَا مِنْ أُوزْبِكِسْتَانَ — anā min Ūzbikistān — Men O‘zbekistondanman.'), ('“Qayerda?” savol so‘zi qaysi?', ['أَيْنَ', 'مَتَى', 'مَنْ'], 0, 'أَيْنَ — ayna — Qayerda?'), ('“Qachon?” savol so‘zi qaysi?', ['مَتَى', 'أَيْنَ', 'مَاذَا'], 0, 'مَتَى — matā — Qachon?'), ('“Kim?” savol so‘zi qaysi?', ['مَنْ', 'كَيْفَ', 'كَمْ'], 0, 'مَنْ — man — Kim?'), ('“Nima?” savol so‘zi qaysi?', ['مَاذَا', 'أَيْنَ', 'مَتَى'], 0, 'مَاذَا — mādhā — Nima?'), ('“Bu nima?” arab tilida qaysi?', ['مَا هٰذَا؟', 'مَنْ هُوَ؟', 'أَيْنَ هُوَ؟'], 0, 'مَا هٰذَا؟ — mā hādhā? — Bu nima?'), ('“Suv” arab tilida qaysi?', ['مَاءٌ', 'خُبْزٌ', 'بَيْتٌ'], 0, 'مَاءٌ — mā’un — Suv.'), ('“Non” arab tilida qaysi?', ['خُبْزٌ', 'مَاءٌ', 'كِتَابٌ'], 0, 'خُبْزٌ — khubzun — Non.'), ('“Kitob” arab tilida qaysi?', ['كِتَابٌ', 'قَلَمٌ', 'بَابٌ'], 0, 'كِتَابٌ — kitābun — Kitob.'), ('“Qalam” arab tilida qaysi?', ['قَلَمٌ', 'كِتَابٌ', 'مَسْجِدٌ'], 0, 'قَلَمٌ — qalamun — Qalam.'), ('“Uy” arab tilida qaysi?', ['بَيْتٌ', 'مَدْرَسَةٌ', 'سُوقٌ'], 0, 'بَيْتٌ — baytun — Uy.'), ('“Maktab” arab tilida qaysi?', ['مَدْرَسَةٌ', 'مَسْجِدٌ', 'مَطْعَمٌ'], 0, 'مَدْرَسَةٌ — madrasatun — Maktab.'), ('“Masjid” arab tilida qaysi?', ['مَسْجِدٌ', 'مَدْرَسَةٌ', 'مَكْتَبٌ'], 0, 'مَسْجِدٌ — masjidun — Masjid.'), ('“Men o‘qiyman” (hozirgi zamon) qaysi?', ['أَنَا أَقْرَأُ', 'أَنَا أَكَلْتُ', 'أَنَا نَامَ'], 0, 'أَنَا أَقْرَأُ — anā aqra’u — Men o‘qiyman / o‘qiyapman.'), ('“Men yozaman” arab tilida qaysi?', ['أَنَا أَكْتُبُ', 'أَنَا أَشْرَبُ', 'أَنَا أَذْهَبُ'], 0, 'أَنَا أَكْتُبُ — anā aktubu — Men yozaman / yozyapman.'), ('“Men ichaman” arab tilida qaysi?', ['أَنَا أَشْرَبُ', 'أَنَا أَكْتُبُ', 'أَنَا أَفْتَحُ'], 0, 'أَنَا أَشْرَبُ — anā ashrabu — Men ichaman.'), ('“Men boraman” arab tilida qaysi?', ['أَنَا أَذْهَبُ', 'أَنَا أَجْلِسُ', 'أَنَا أَنَامُ'], 0, 'أَنَا أَذْهَبُ — anā adhhabu — Men boraman.'), ('“Men tushunmayapman” arab tilida qaysi?', ['لَا أَفْهَمُ', 'أَفْهَمُ جَيِّدًا', 'أَيْنَ الْبَيْتُ؟'], 0, 'لَا أَفْهَمُ — lā afhamu — Men tushunmayapman.'), ('“Sekinroq gapiring, iltimos” qaysi?', ['تَكَلَّمْ بِبُطْءٍ مِنْ فَضْلِكَ', 'أَنَا جَائِعٌ', 'مَا اسْمُكَ؟'], 0, 'تَكَلَّمْ بِبُطْءٍ مِنْ فَضْلِكَ — takallam bibut’in min faḍlika — Sekinroq gapiring, iltimos (erkakka).'), ('“Bu qancha turadi?” qaysi?', ['بِكَمْ هٰذَا؟', 'أَيْنَ الْمَسْجِدُ؟', 'مَنْ أَنْتَ؟'], 0, 'بِكَمْ هٰذَا؟ — bikam hādhā? — Bu qancha turadi?'), ('“Masjid qayerda?” qaysi?', ['أَيْنَ الْمَسْجِدُ؟', 'كَيْفَ حَالُكَ؟', 'مَا هٰذَا؟'], 0, 'أَيْنَ الْمَسْجِدُ؟ — ayna-l-masjidu? — Masjid qayerda?'), ('“Bugun” arab tilida qaysi?', ['الْيَوْمَ', 'غَدًا', 'أَمْسِ'], 0, 'الْيَوْمَ — al-yawma — Bugun.'), ('“Ertaga” arab tilida qaysi?', ['غَدًا', 'الْيَوْمَ', 'أَمْسِ'], 0, 'غَدًا — ghadan — Ertaga.'), ('“Kecha” arab tilida qaysi?', ['أَمْسِ', 'غَدًا', 'الْآنَ'], 0, 'أَمْسِ — amsi — Kecha.'), ('“Bir” soni arab tilida qaysi?', ['وَاحِدٌ', 'اِثْنَانِ', 'ثَلَاثَةٌ'], 0, 'وَاحِدٌ — wāḥidun — Bir.'), ('“Ikki” soni arab tilida qaysi?', ['اِثْنَانِ', 'وَاحِدٌ', 'أَرْبَعَةٌ'], 0, 'اِثْنَانِ — ithnān — Ikki.'), ('“Uch” soni arab tilida qaysi?', ['ثَلَاثَةٌ', 'خَمْسَةٌ', 'وَاحِدٌ'], 0, 'ثَلَاثَةٌ — thalāthatun — Uch.'), ('“Men ochman” (erkak kishi aytsa) qaysi?', ['أَنَا جَائِعٌ', 'أَنَا عَطْشَانُ', 'أَنَا سَعِيدٌ'], 0, 'أَنَا جَائِعٌ — anā jā’i‘un — Men ochman (erkak shakli).'), ('“Men chanqadim” (erkak kishi aytsa) qaysi?', ['أَنَا عَطْشَانُ', 'أَنَا جَائِعٌ', 'أَنَا مُتْعَبٌ'], 0, 'أَنَا عَطْشَانُ — anā ‘aṭshānu — Men chanqadim (erkak shakli).'), ('“Xayr, ko‘rishguncha” qaysi ibora?', ['إِلَى اللِّقَاءِ', 'شُكْرًا', 'نَعَمْ'], 0, 'إِلَى اللِّقَاءِ — ilā-l-liqā’ — Ko‘rishguncha.'), ('“Kechirasiz” / “uzr” so‘zi qaysi?', ['عَفْوًا', 'مَاءٌ', 'كِتَابٌ'], 0, 'عَفْوًا — ‘afwan — Arzimaydi / kechirasiz (vaziyatga qarab).')]
ARABIC_QUIZ_BANK.extend(EXTRA_ARABIC_QUIZ)
QUIZ_BANK.extend(ARABIC_QUIZ_BANK)
ARABIC_QUIZ_IDS = list(range(ARABIC_QUIZ_START, len(QUIZ_BANK)))
ARABIC_SPEAKING_IDS = [ARABIC_QUIZ_START + i for i in (0,1,2,3,4,5,8,9,10,11,12,13,14,15,28,29,30,31,38,39,40,41)]

def islam_panel_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌙 Payg‘ambarimiz ﷺ hayotlari", callback_data="seerah_panel")],
        [InlineKeyboardButton("📖 Qur’on haqida", callback_data="islam:0"),
         InlineKeyboardButton("🕌 Islom asoslari", callback_data="islam:1")],
        [InlineKeyboardButton("🤲 Ibodatlar", callback_data="islam:2"),
         InlineKeyboardButton("📚 Odob-axloq", callback_data="islam:3")],
        [InlineKeyboardButton("🧔 Payg‘ambarlar qissalari", callback_data="prophets_panel")],
        [InlineKeyboardButton("📝 Testlar", callback_data="test_panel")],
        [InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]
    ])

def make_quiz_keyboard(qid):
    import random
    q = QUIZ_BANK[qid]
    opts = list(enumerate(q[1][:3]))
    random.shuffle(opts)
    rows = [[InlineKeyboardButton(f"{chr(65+i)}) {label}", callback_data=f"answer:{qid}:{orig}")]
            for i,(orig,label) in enumerate(opts)]
    rows.append([InlineKeyboardButton("🎲 Keyingi test", callback_data="quiz_next")])
    rows.append([InlineKeyboardButton("📚 Test bo‘limlari", callback_data="test_panel")])
    return InlineKeyboardMarkup(rows)

async def send_quiz(chat, context, qid=None):
    import random
    if qid is None: qid = random.randrange(len(QUIZ_BANK))
    q = QUIZ_BANK[qid]
    context.user_data["current_quiz"] = qid
    context.user_data["quiz_count"] = context.user_data.get("quiz_count", 0) + 1
    await chat.reply_text(f"📝 TEST {context.user_data['quiz_count']}/100000\nSavollar banki: {len(QUIZ_BANK)} ta\n\n{q[0]}\n\nJavobni tanlang:",
                          reply_markup=make_quiz_keyboard(qid))


async def make_arabic_audio(text_to_say: str, audio_path: str):
    """Create Arabic speech; try Google TTS first, then Edge TTS as fallback."""
    errors = []
    try:
        from gtts import gTTS
        await asyncio.to_thread(gTTS(text=text_to_say, lang="ar", slow=True).save, audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 500:
            return
        errors.append("gTTS bo‘sh audio qaytardi")
    except Exception as e:
        errors.append("gTTS: " + str(e)[:100])
    try:
        import edge_tts
        await edge_tts.Communicate(text_to_say, voice="ar-SA-ZariyahNeural", rate="-15%").save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 500:
            return
        errors.append("Edge TTS bo‘sh audio qaytardi")
    except Exception as e:
        errors.append("Edge TTS: " + str(e)[:100])
    raise RuntimeError("; ".join(errors))


# =====================================================================
#  ARAB TILI: MAVZULAR PANELI (lug‘at), GRAMMATIKA, MAVZU TESTLARI
# =====================================================================
import re, random, types, unicodedata

TOPIC_PANEL = [
 ('👋 Salomlashish', [
  ('مَرْحَبًا', 'marḥaban', 'Salom'), ('السَّلَامُ عَلَيْكُمْ', 'as-salāmu ‘alaykum', 'Assalomu alaykum'),
  ('وَعَلَيْكُمُ السَّلَامُ', 'wa ‘alaykumu s-salām', 'Va alaykum assalom'), ('صَبَاحُ الْخَيْرِ', 'ṣabāḥu l-khayr', 'Xayrli tong'),
  ('مَسَاءُ الْخَيْرِ', 'masā’u l-khayr', 'Xayrli kech'), ('شُكْرًا', 'shukran', 'Rahmat'),
  ('عَفْوًا', '‘afwan', 'Arzimaydi'), ('مِنْ فَضْلِكَ', 'min faḍlika', 'Iltimos'),
  ('أَنَا آسِفٌ', 'anā āsifun', 'Kechirasiz'), ('مَعَ السَّلَامَةِ', 'ma‘a s-salāma', 'Xayr, omon bo‘ling')]),
 ('👨‍👩‍👧 Oila', [
  ('أَبٌ', 'abun', 'Ota'), ('أُمٌّ', 'ummun', 'Ona'), ('أَخٌ', 'akhun', 'Aka / uka'), ('أُخْتٌ', 'ukhtun', 'Opa / singil'),
  ('جَدٌّ', 'jaddun', 'Bobo'), ('جَدَّةٌ', 'jaddatun', 'Buvi'), ('اِبْنٌ', 'ibnun', 'O‘g‘il'), ('بِنْتٌ', 'bintun', 'Qiz'),
  ('زَوْجٌ', 'zawjun', 'Er'), ('زَوْجَةٌ', 'zawjatun', 'Xotin'), ('عَمٌّ', '‘ammun', 'Amaki'), ('خَالٌ', 'khālun', 'Tog‘a')]),
 ('🔢 Raqamlar', [
  ('صِفْرٌ', 'ṣifr', 'Nol'), ('وَاحِدٌ', 'wāḥid', 'Bir'), ('اِثْنَانِ', 'ithnān', 'Ikki'), ('ثَلَاثَةٌ', 'thalātha', 'Uch'),
  ('أَرْبَعَةٌ', 'arba‘a', 'To‘rt'), ('خَمْسَةٌ', 'khamsa', 'Besh'), ('سِتَّةٌ', 'sitta', 'Olti'), ('سَبْعَةٌ', 'sab‘a', 'Yetti'),
  ('ثَمَانِيَةٌ', 'thamāniya', 'Sakkiz'), ('تِسْعَةٌ', 'tis‘a', 'To‘qqiz'), ('عَشَرَةٌ', '‘ashara', 'O‘n'),
  ('مِائَةٌ', 'mi’a', 'Yuz'), ('أَلْفٌ', 'alf', 'Ming')]),
 ('🎨 Ranglar', [
  ('أَحْمَرُ', 'aḥmar', 'Qizil'), ('أَزْرَقُ', 'azraq', 'Ko‘k'), ('أَخْضَرُ', 'akhḍar', 'Yashil'), ('أَصْفَرُ', 'aṣfar', 'Sariq'),
  ('أَبْيَضُ', 'abyaḍ', 'Oq'), ('أَسْوَدُ', 'aswad', 'Qora'), ('بُنِّيٌّ', 'bunniyy', 'Jigarrang'),
  ('رَمَادِيٌّ', 'ramādiyy', 'Kulrang'), ('بُرْتُقَالِيٌّ', 'burtuqāliyy', 'To‘q sariq'), ('وَرْدِيٌّ', 'wardiyy', 'Pushti')]),
 ('📅 Kunlar va vaqt', [
  ('الأَحَدُ', 'al-aḥad', 'Yakshanba'), ('الاِثْنَيْنِ', 'al-ithnayn', 'Dushanba'), ('الثُّلَاثَاءُ', 'ath-thulāthā’', 'Seshanba'),
  ('الأَرْبِعَاءُ', 'al-arbi‘ā’', 'Chorshanba'), ('الْخَمِيسُ', 'al-khamīs', 'Payshanba'), ('الْجُمُعَةُ', 'al-jumu‘a', 'Juma'),
  ('السَّبْتُ', 'as-sabt', 'Shanba'), ('الْيَوْمَ', 'al-yawma', 'Bugun'), ('غَدًا', 'ghadan', 'Ertaga'), ('أَمْسِ', 'amsi', 'Kecha'),
  ('صَبَاحٌ', 'ṣabāḥun', 'Ertalab'), ('سَاعَةٌ', 'sā‘atun', 'Soat')]),
 ('🍽 Ovqat va ichimlik', [
  ('خُبْزٌ', 'khubzun', 'Non'), ('مَاءٌ', 'mā’un', 'Suv'), ('حَلِيبٌ', 'ḥalībun', 'Sut'), ('شَايٌ', 'shāyun', 'Choy'),
  ('قَهْوَةٌ', 'qahwatun', 'Qahva'), ('لَحْمٌ', 'laḥmun', 'Go‘sht'), ('دَجَاجٌ', 'dajājun', 'Tovuq'), ('سَمَكٌ', 'samakun', 'Baliq'),
  ('أَرُزٌّ', 'aruzzun', 'Guruch'), ('تُفَّاحٌ', 'tuffāḥun', 'Olma'), ('مَوْزٌ', 'mawzun', 'Banan'), ('بَيْضٌ', 'bayḍun', 'Tuxum'),
  ('عَسَلٌ', '‘asalun', 'Asal'), ('مِلْحٌ', 'milḥun', 'Tuz')]),
 ('🏠 Uy va buyumlar', [
  ('بَيْتٌ', 'baytun', 'Uy'), ('غُرْفَةٌ', 'ghurfatun', 'Xona'), ('بَابٌ', 'bābun', 'Eshik'), ('نَافِذَةٌ', 'nāfidhatun', 'Deraza'),
  ('مَطْبَخٌ', 'maṭbakhun', 'Oshxona'), ('سَرِيرٌ', 'sarīrun', 'Karavot'), ('طَاوِلَةٌ', 'ṭāwilatun', 'Stol'),
  ('كُرْسِيٌّ', 'kursiyyun', 'Stul'), ('مِفْتَاحٌ', 'miftāḥun', 'Kalit'), ('حَدِيقَةٌ', 'ḥadīqatun', 'Bog‘')]),
 ('🚗 Transport va yo‘l', [
  ('سَيَّارَةٌ', 'sayyāratun', 'Mashina'), ('حَافِلَةٌ', 'ḥāfilatun', 'Avtobus'), ('قِطَارٌ', 'qiṭārun', 'Poyezd'),
  ('طَائِرَةٌ', 'ṭā’iratun', 'Samolyot'), ('دَرَّاجَةٌ', 'darrājatun', 'Velosiped'), ('شَارِعٌ', 'shāri‘un', 'Ko‘cha'),
  ('طَرِيقٌ', 'ṭarīqun', 'Yo‘l'), ('مَطَارٌ', 'maṭārun', 'Aeroport'), ('يَمِينٌ', 'yamīnun', 'O‘ng'),
  ('يَسَارٌ', 'yasārun', 'Chap'), ('مُسْتَقِيمٌ', 'mustaqīmun', 'To‘g‘ri')]),
 ('🛒 Bozor va pul', [
  ('سُوقٌ', 'sūqun', 'Bozor'), ('مَحَلٌّ', 'maḥallun', 'Do‘kon'), ('ثَمَنٌ', 'thamanun', 'Narx'), ('مَالٌ', 'mālun', 'Pul / mol'),
  ('رَخِيصٌ', 'rakhīṣun', 'Arzon'), ('غَالٍ', 'ghālin', 'Qimmat'), ('بِكَمْ هٰذَا؟', 'bikam hādhā?', 'Bu qancha turadi?'),
  ('أُرِيدُ هٰذَا', 'urīdu hādhā', 'Men buni xohlayman'), ('أَشْتَرِي', 'ashtarī', 'Sotib olaman'), ('أَبِيعُ', 'abī‘u', 'Sotaman')]),
 ('👔 Kiyim-kechak', [
  ('قَمِيصٌ', 'qamīṣun', 'Ko‘ylak (erkaklar)'), ('بَنْطَلُونٌ', 'banṭalūnun', 'Shim'), ('حِذَاءٌ', 'ḥidhā’un', 'Poyabzal'),
  ('قُبَّعَةٌ', 'qubba‘atun', 'Shapka'), ('مِعْطَفٌ', 'mi‘ṭafun', 'Palto'), ('فُسْتَانٌ', 'fustānun', 'Ko‘ylak (ayollar)'),
  ('جَوْرَبٌ', 'jawrabun', 'Paypoq'), ('عِمَامَةٌ', '‘imāmatun', 'Salla'), ('حِزَامٌ', 'ḥizāmun', 'Kamar'), ('نَظَّارَةٌ', 'naẓẓāratun', 'Ko‘zoynak')]),
 ('🏥 Salomatlik va tana', [
  ('طَبِيبٌ', 'ṭabībun', 'Shifokor'), ('مُسْتَشْفَى', 'mustashfā', 'Kasalxona'), ('صَيْدَلِيَّةٌ', 'ṣaydaliyyatun', 'Dorixona'),
  ('دَوَاءٌ', 'dawā’un', 'Dori'), ('مَرِيضٌ', 'marīḍun', 'Bemor'), ('رَأْسٌ', 'ra’sun', 'Bosh'), ('عَيْنٌ', '‘aynun', 'Ko‘z'),
  ('يَدٌ', 'yadun', 'Qo‘l'), ('رِجْلٌ', 'rijlun', 'Oyoq'), ('قَلْبٌ', 'qalbun', 'Yurak'), ('بَطْنٌ', 'baṭnun', 'Qorin'),
  ('أَنَا مَرِيضٌ', 'anā marīḍun', 'Men kasalman')]),
 ('🌤 Tabiat va ob-havo', [
  ('شَمْسٌ', 'shamsun', 'Quyosh'), ('قَمَرٌ', 'qamarun', 'Oy'), ('نَجْمٌ', 'najmun', 'Yulduz'), ('سَمَاءٌ', 'samā’un', 'Osmon'),
  ('أَرْضٌ', 'arḍun', 'Yer'), ('مَطَرٌ', 'maṭarun', 'Yomg‘ir'), ('ثَلْجٌ', 'thaljun', 'Qor'), ('رِيحٌ', 'rīḥun', 'Shamol'),
  ('بَحْرٌ', 'baḥrun', 'Dengiz'), ('نَهْرٌ', 'nahrun', 'Daryo'), ('جَبَلٌ', 'jabalun', 'Tog‘'), ('شَجَرَةٌ', 'shajaratun', 'Daraxt'),
  ('حَارٌّ', 'ḥārrun', 'Issiq'), ('بَارِدٌ', 'bāridun', 'Sovuq')]),
 ('💼 Kasblar', [
  ('مُعَلِّمٌ', 'mu‘allimun', 'O‘qituvchi'), ('طَالِبٌ', 'ṭālibun', 'Talaba'), ('طَبِيبٌ', 'ṭabībun', 'Shifokor'),
  ('مُهَنْدِسٌ', 'muhandisun', 'Muhandis'), ('سَائِقٌ', 'sā’iqun', 'Haydovchi'), ('تَاجِرٌ', 'tājirun', 'Savdogar'),
  ('شُرْطِيٌّ', 'shurṭiyyun', 'Politsiyachi'), ('طَبَّاخٌ', 'ṭabbākhun', 'Oshpaz'), ('مُزَارِعٌ', 'muzāri‘un', 'Dehqon'),
  ('عَامِلٌ', '‘āmilun', 'Ishchi'), ('مُحَاسِبٌ', 'muḥāsibun', 'Hisobchi')]),
 ('🕌 Masjid va ibodat', [
  ('مَسْجِدٌ', 'masjidun', 'Masjid'), ('صَلَاةٌ', 'ṣalātun', 'Namoz'), ('وُضُوءٌ', 'wuḍū’un', 'Tahorat'), ('قِبْلَةٌ', 'qiblatun', 'Qibla'),
  ('قُرْآنٌ', 'qur’ānun', 'Qur’on'), ('دُعَاءٌ', 'du‘ā’un', 'Duo'), ('صَوْمٌ', 'ṣawmun', 'Ro‘za'), ('زَكَاةٌ', 'zakātun', 'Zakot'),
  ('حَجٌّ', 'ḥajjun', 'Haj'), ('عُمْرَةٌ', '‘umratun', 'Umra'), ('أَذَانٌ', 'adhānun', 'Azon'), ('إِمَامٌ', 'imāmun', 'Imom'),
  ('مُصْحَفٌ', 'muṣḥafun', 'Mushaf'), ('سَجْدَةٌ', 'sajdatun', 'Sajda'), ('رُكُوعٌ', 'rukū‘un', 'Ruku')]),
 ('✈️ Safar', [
  ('جَوَازُ سَفَرٍ', 'jawāzu safarin', 'Pasport'), ('تَذْكِرَةٌ', 'tadhkiratun', 'Chipta'), ('فُنْدُقٌ', 'funduqun', 'Mehmonxona'),
  ('حَقِيبَةٌ', 'ḥaqībatun', 'Sumka / chamadon'), ('خَرِيطَةٌ', 'kharīṭatun', 'Xarita'), ('سَفَرٌ', 'safarun', 'Safar'),
  ('أَيْنَ الْفُنْدُقُ؟', 'ayna l-funduq?', 'Mehmonxona qayerda?'), ('مِنْ أَيْنَ أَنْتَ؟', 'min ayna anta?', 'Siz qayerdansiz?'),
  ('أَنَا مِنْ أُوزْبِكِسْتَانَ', 'anā min Ūzbikistān', 'Men O‘zbekistondanman'), ('أُرِيدُ غُرْفَةً', 'urīdu ghurfatan', 'Menga xona kerak')]),
 ('🧩 Olmoshlar va savollar', [
  ('أَنَا', 'anā', 'Men'), ('أَنْتَ', 'anta', 'Sen (erkak)'), ('أَنْتِ', 'anti', 'Sen (ayol)'), ('هُوَ', 'huwa', 'U (erkak)'),
  ('هِيَ', 'hiya', 'U (ayol)'), ('نَحْنُ', 'naḥnu', 'Biz'), ('هٰذَا', 'hādhā', 'Bu (erkak)'), ('هٰذِهِ', 'hādhihi', 'Bu (ayol)'),
  ('مَنْ', 'man', 'Kim?'), ('مَا', 'mā', 'Nima?'), ('أَيْنَ', 'ayna', 'Qayerda?'), ('مَتَى', 'matā', 'Qachon?'),
  ('كَيْفَ', 'kayfa', 'Qanday?'), ('لِمَاذَا', 'limādhā', 'Nega?'), ('كَمْ', 'kam', 'Nechta?')]),
 ('🏃 Muhim fe‘llar', [
  ('أَذْهَبُ', 'adhhabu', 'Boraman'), ('آكُلُ', 'ākulu', 'Yeyman'), ('أَشْرَبُ', 'ashrabu', 'Ichaman'), ('أَقْرَأُ', 'aqra’u', 'O‘qiyman'),
  ('أَكْتُبُ', 'aktubu', 'Yozaman'), ('أَنَامُ', 'anāmu', 'Uxlayman'), ('أَفْهَمُ', 'afhamu', 'Tushunaman'),
  ('أَتَكَلَّمُ', 'atakallamu', 'Gapiraman'), ('أُحِبُّ', 'uḥibbu', 'Yaxshi ko‘raman'), ('أُرِيدُ', 'urīdu', 'Xohlayman'),
  ('أَعْرِفُ', 'a‘rifu', 'Bilaman'), ('أَعْمَلُ', 'a‘malu', 'Ishlayman'), ('أَجْلِسُ', 'ajlisu', 'O‘tiraman')]),
 ('🎓 Maktab va o‘qish', [
  ('كِتَابٌ', 'kitābun', 'Kitob'), ('قَلَمٌ', 'qalamun', 'Qalam'), ('دَفْتَرٌ', 'daftarun', 'Daftar'), ('مَدْرَسَةٌ', 'madrasatun', 'Maktab'),
  ('فَصْلٌ', 'faṣlun', 'Sinf xonasi'), ('دَرْسٌ', 'darsun', 'Dars'), ('سُؤَالٌ', 'su’ālun', 'Savol'), ('جَوَابٌ', 'jawābun', 'Javob'),
  ('اِمْتِحَانٌ', 'imtiḥānun', 'Imtihon'), ('جَامِعَةٌ', 'jāmi‘atun', 'Universitet'), ('مَكْتَبَةٌ', 'maktabatun', 'Kutubxona'), ('لُغَةٌ', 'lughatun', 'Til')]),
 ('💬 Foydali iboralar', [
  ('لَا أَفْهَمُ', 'lā afhamu', 'Tushunmayapman'), ('أَعِدْ مِنْ فَضْلِكَ', 'a‘id min faḍlika', 'Qaytaring, iltimos'),
  ('تَكَلَّمْ بِبُطْءٍ', 'takallam bibuṭ’in', 'Sekinroq gapiring'), ('مَا مَعْنَى هٰذَا؟', 'mā ma‘nā hādhā?', 'Bu nima degani?'),
  ('أَيْنَ الْحَمَّامُ؟', 'ayna l-ḥammām?', 'Hojatxona qayerda?'), ('هَلْ تَتَكَلَّمُ الْعَرَبِيَّةَ؟', 'hal tatakallamu l-‘arabiyya?', 'Arabcha gapirasizmi?'),
  ('أَنَا أَتَعَلَّمُ الْعَرَبِيَّةَ', 'anā ata‘allamu l-‘arabiyya', 'Men arab tilini o‘rganyapman'),
  ('إِنْ شَاءَ اللَّهُ', 'in shā’a llāh', 'Alloh xohlasa'), ('مَا شَاءَ اللَّهُ', 'mā shā’a llāh', 'Alloh xohlagan'),
  ('بَارَكَ اللَّهُ فِيكَ', 'bāraka llāhu fīka', 'Alloh sizga baraka bersin')]),
]

# Barcha so‘zlar bitta ro‘yxatda: (mavzu_raqami, arabcha, talaffuz, o‘zbekcha)
WORDS = [(ti, ar, lat, uz) for ti, (_, items) in enumerate(TOPIC_PANEL) for (ar, lat, uz) in items]

GRAMMAR = [
 ('Jins: erkak va ayol', 'Arab tilida ismlar erkak yoki ayol jinsida bo‘ladi. Ayol jinsi ko‘pincha oxiridagi ـَة (ta marbuta) bilan bilinadi.\n\n'
  'طَالِبٌ — ṭālibun — talaba (o‘g‘il bola)\nطَالِبَةٌ — ṭālibatun — talaba (qiz bola)\n\n'
  'Sifat ismga jinsda mos keladi:\nطَالِبٌ جَدِيدٌ — yangi talaba (erkak)\nطَالِبَةٌ جَدِيدَةٌ — yangi talaba (ayol)'),
 ('Aniqlik: ال artikli', 'Ism oxiridagi tanvin (ـٌ ـً ـٍ) noaniqlikni bildiradi. Aniq qilish uchun boshiga «ال» qo‘shiladi va tanvin tushadi.\n\n'
  'كِتَابٌ — kitābun — (bitta) kitob\nالْكِتَابُ — al-kitābu — o‘sha kitob\n\n'
  'Ba’zi harflar (ت ث د ذ ر ز س ش ص ض ط ظ ل ن) oldidan «ل» o‘qilmaydi, harf ikkilanadi:\nالشَّمْسُ — ash-shamsu — quyosh (al-shamsu emas)'),
 ('Ismiy jumla (ot gap)', 'Arabchada «bo‘lmoq» fe’li hozirgi zamonda ishlatilmaydi. Ikki ism yonma-yon turadi.\n\n'
  'الْبَيْتُ كَبِيرٌ — al-baytu kabīrun — Uy katta.\nأَنَا طَالِبٌ — anā ṭālibun — Men talabaman.\nهُوَ مُعَلِّمٌ — huwa mu‘allimun — U o‘qituvchi.'),
 ('Hozirgi zamon fe’li', 'Hozirgi zamon fe’li boshidagi harf bilan shaxsni ko‘rsatadi: أ (men), ن (biz), ت (sen/u-ayol), ي (u-erkak).\n\n'
  'أَكْتُبُ — aktubu — men yozaman\nتَكْتُبُ — taktubu — sen yozasan (erkak)\nيَكْتُبُ — yaktubu — u yozadi\nنَكْتُبُ — naktubu — biz yozamiz'),
 ('O‘tgan zamon fe’li', 'O‘tgan zamon fe’lida shaxs oxirgi qo‘shimcha bilan ko‘rsatiladi.\n\n'
  'كَتَبْتُ — katabtu — men yozdim\nكَتَبْتَ — katabta — sen yozding (erkak)\nكَتَبَ — kataba — u yozdi\nكَتَبَتْ — katabat — u yozdi (ayol)\nكَتَبْنَا — katabnā — biz yozdik'),
 ('Egalik qo‘shimchalari', 'Ism oxiriga qo‘shimcha qo‘shilib «mening, sening, uning…» ma’nosi hosil bo‘ladi.\n\n'
  'كِتَابِي — kitābī — mening kitobim\nكِتَابُكَ — kitābuka — sening kitobing (erkak)\nكِتَابُهُ — kitābuhu — uning kitobi (erkak)\nكِتَابُهَا — kitābuhā — uning kitobi (ayol)\nكِتَابُنَا — kitābunā — bizning kitobimiz'),
 ('Ko‘plik', 'Ko‘plik ikki xil: sog‘lom (qo‘shimcha bilan) va singan (so‘z ichki shakli o‘zgaradi).\n\n'
  'Sog‘lom:\nمُعَلِّمٌ ← مُعَلِّمُونَ — o‘qituvchilar (erkak)\nمُعَلِّمَةٌ ← مُعَلِّمَاتٌ — o‘qituvchilar (ayol)\n\n'
  'Singan (har so‘zni alohida yodlash kerak):\nكِتَابٌ ← كُتُبٌ — kitoblar\nبَيْتٌ ← بُيُوتٌ — uylar'),
 ('Predloglar', 'فِي — fī — -da (ichida)\nمِنْ — min — -dan\nإِلَى — ilā — -ga (tomon)\nعَلَى — ‘alā — ustida\nمَعَ — ma‘a — bilan\nعَنْ — ‘an — haqida\n\n'
  'Misol:\nأَنَا فِي الْبَيْتِ — men uydaman.\nأَذْهَبُ إِلَى الْمَدْرَسَةِ — maktabga boraman.\nأَنَا مِنْ أُوزْبِكِسْتَانَ — men O‘zbekistondanman.'),
 ('«Menda bor» — عِنْد', '«Menda bor» deyish uchun عِنْدَ predlogi ishlatiladi.\n\n'
  'عِنْدِي كِتَابٌ — ‘indī kitābun — menda kitob bor.\nعِنْدَكَ قَلَمٌ — ‘indaka qalamun — senda qalam bor.\nلَيْسَ عِنْدِي وَقْتٌ — laysa ‘indī waqtun — menda vaqt yo‘q.'),
 ('Inkor qilish', 'لَا — hozirgi zamon fe’lini inkor qiladi: لَا أَفْهَمُ — tushunmayapman.\n'
  'مَا — o‘tgan zamonni inkor qiladi: مَا ذَهَبْتُ — bormadim.\n'
  'لَيْسَ — ot gapni inkor qiladi: لَيْسَ الْبَيْتُ كَبِيرًا — uy katta emas.'),
]

REPLY_KB = ReplyKeyboardMarkup([
 ['🚀 Arab tilini 0 dan'],
 ['📚 O‘rganish', '🧩 Grammatika'],
 ['🌐 Tarjimon', '🗣 Gapirish mashqi'],
 ['🎧 Tinglash', '📖 Qur’on suralari'],
 ['📝 Mashq va test', '📚 10 000 ta dars'],
 ['🔤 Alifbo', 'ℹ️ Yordam'],
], resize_keyboard=True, input_field_placeholder='Bo‘limni tanlang…')

REPLY_ACTIONS = {
 'arab tilini 0 dan': 'zero_panel', 'organish': 'tp_panel', 'grammatika': 'gr_panel', 'ai ustoz': 'tp_panel', 'tarjimon': 'translate',
 'gapirish mashqi': 'speak', 'tinglash': 'listen_panel', 'quron suralari': 'quran',
 'mashq va test': 'test_panel', '10 000 ta dars': 'lessons:1', 'alifbo': 'alphabet', 'yordam': 'help',
}

def norm_label(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', '', (text or '').lower())).strip()

async def dispatch_callback(update, context, data):
    """Pastki (reply) tugma bosilganda mos inline amalni ishga tushiradi."""
    async def _ans(*a, **k): pass
    q = types.SimpleNamespace(data=data, message=update.effective_message, answer=_ans)
    shim = types.SimpleNamespace(callback_query=q, effective_user=update.effective_user,
                                 effective_message=update.effective_message, effective_chat=update.effective_chat)
    await callback(shim, context)

def topics_kb(prefix, extra=()):
    rows, row = [], []
    for i, (title, _) in enumerate(TOPIC_PANEL):
        row.append(btn(title, f'{prefix}:{i}'))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.extend(list(extra))
    rows.append([btn('🏠 Bosh menyu', 'home')])
    return InlineKeyboardMarkup(rows)

def topic_text(i):
    title, items = TOPIC_PANEL[i]
    lines = [f'{title}  ({i + 1}/{len(TOPIC_PANEL)})', '']
    for n, (ar, lat, uz) in enumerate(items, 1):
        lines.append(f'{n}. {ar}\n    {lat} — {uz}')
    lines += ['', '🔊 Tinglash, 📝 yoki 📝 test tugmasini bosing.']
    return '\n'.join(lines)

def topic_kb(i):
    last = len(TOPIC_PANEL) - 1
    return InlineKeyboardMarkup([
        [btn('🔊 Audio', f'tpa:{i}'), btn('📝 Test', f'tq:{i}')],
        [btn('⬅️ Oldingi', f'tp:{max(0, i - 1)}'), btn('Keyingi ➡️', f'tp:{min(last, i + 1)}')],
        [btn('📚 Mavzular', 'tp_panel'), btn('🏠 Menyu', 'home')]])

def tq_make(topic):
    pool = [k for k, w in enumerate(WORDS) if topic == 'a' or w[0] == int(topic)]
    c = random.choice(pool)
    uz_to_ar = random.random() < 0.5
    key = 1 if uz_to_ar else 3
    others = [k for k in pool if WORDS[k][key] != WORDS[c][key]]
    seen, picks = {WORDS[c][key]}, []
    random.shuffle(others)
    for k in others:
        if WORDS[k][key] not in seen:
            seen.add(WORDS[k][key]); picks.append(k)
        if len(picks) == 2: break
    opts = picks + [c]; random.shuffle(opts)
    w = WORDS[c]
    text = f'“{w[3]}” arabchada qaysi?' if uz_to_ar else f'{w[1]} — o‘zbekchada nima?'
    rows = [[btn(WORDS[k][key], f'tqa:{topic}:{c}:{k}')] for k in opts]
    rows.append([btn('📚 Mavzular', 'tp_panel')])
    return '📝 MAVZU TESTI\n\n' + text, InlineKeyboardMarkup(rows)

_HARAKAT = re.compile('[\u064B-\u065F\u0670\u0640]')

def norm_search(t):
    t = unicodedata.normalize('NFKD', (t or '').lower())
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[‘’ʻʼ'`´-]", '', _HARAKAT.sub('', t)).strip()

def dict_search(q):
    qn = norm_search(q)
    if len(qn) < 2: return []
    exact, part, seen = [], [], set()
    for k, w in enumerate(WORDS):
        if (w[1], w[3]) in seen: continue
        fields = [norm_search(w[1]), norm_search(w[2]), norm_search(w[3])]
        if qn in fields: exact.append(k); seen.add((w[1], w[3]))
        elif any(qn in f for f in fields): part.append(k); seen.add((w[1], w[3]))
    return (exact + part)[:8]

def dict_reply(q):
    res = dict_search(q)
    if not res:
        return '🔎 Topilmadi. Boshqa so‘z yozing (arabcha, talaffuz yoki o‘zbekcha) yoki 📚 Mavzular bo‘limidan qidiring.'
    return '📖 LUG‘AT\n\n' + '\n\n'.join(f'{WORDS[k][1]}\n{WORDS[k][2]} — {WORDS[k][3]}' for k in res)

SPEAK_TOPICS = ('👋 Salomlashish', '💬 Foydali iboralar')

def speak_pool():
    return [k for k, w in enumerate(WORDS) if TOPIC_PANEL[w[0]][0] in SPEAK_TOPICS]

async def send_tts(m, text, title, caption):
    audio_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f: audio_path = f.name
        await make_arabic_audio(text, audio_path)
        with open(audio_path, 'rb') as af:
            await m.reply_audio(audio=af, title=title, caption=caption)
    except Exception as e:
        await m.reply_text('Audio yaratilmadi: ' + str(e)[:160])
    finally:
        if audio_path:
            try: os.remove(audio_path)
            except OSError: pass

async def topics_callbacks(update, context, data):
    """Mavzular paneli, grammatika va mavzu testlari. Qayta ishlangan bo‘lsa True qaytaradi."""
    m = update.callback_query.message
    if data == 'tp_panel':
        await m.reply_text('📚 ARAB TILI MAVZULARI\n\nHar bir mavzuda so‘zlar, talaffuz, audio va test bor. Mavzuni tanlang:',
                           reply_markup=topics_kb('tp', [[btn('🧩 Grammatika', 'gr_panel'), btn('🎲 Aralash test', 'tq:a')], [btn('🌟 Tasodifiy so‘z', 'tw')]]))
    elif data == 'listen_panel':
        await m.reply_text('🎧 TINGLASH\n\nMavzuni tanlang — bot so‘zlarni arabcha o‘qib beradi:',
                           reply_markup=topics_kb('tpa', [[btn('🔤 Alifbo talaffuzi', 'alphabet_audio')]]))
    elif data.startswith('tp:'):
        i = max(0, min(len(TOPIC_PANEL) - 1, int(data.split(':')[1])))
        await m.reply_text(topic_text(i), reply_markup=topic_kb(i))
    elif data.startswith('tpa:'):
        i = max(0, min(len(TOPIC_PANEL) - 1, int(data.split(':')[1])))
        audio_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f: audio_path = f.name
            await make_arabic_audio('. '.join(ar for ar, _, _ in TOPIC_PANEL[i][1]), audio_path)
            with open(audio_path, 'rb') as af:
                await m.reply_audio(audio=af, title=TOPIC_PANEL[i][0], caption=f'{TOPIC_PANEL[i][0]} — so‘zlarni tinglang va takrorlang.')
        except Exception as e:
            await m.reply_text('Audio yaratilmadi: ' + str(e)[:160])
        finally:
            if audio_path:
                try: os.remove(audio_path)
                except OSError: pass
    elif data in ('sp', 'speak', 'speak_start'):
        k = random.choice(speak_pool()); w = WORDS[k]
        await m.reply_text(f'🗣 GAPIRISH MASHQI\n\nIborani eshiting, so‘ng ovoz chiqarib 3 marta ayting:\n\n{w[1]}\n{w[2]} — {w[3]}',
                           reply_markup=InlineKeyboardMarkup([[btn('🔊 Eshitish', f'spa:{k}'), btn('➡️ Keyingi', 'sp')], [btn('📚 Mavzular', 'tp_panel'), btn('🏠 Menyu', 'home')]]))
    elif data.startswith('spa:'):
        w = WORDS[max(0, min(len(WORDS) - 1, int(data.split(':')[1])))]
        await send_tts(m, w[1], 'Gapirish mashqi', f'{w[2]} — {w[3]}')
    elif data == 'translate':
        context.user_data['mode'] = 'translate'
        await m.reply_text('📖 LUG‘AT\n\nSo‘zni yozing — arabcha, lotincha talaffuz yoki o‘zbekcha (masalan: kitob, shukran, اسم). Bot lug‘atdan topib beradi.\nChiqish: /start')
    elif data == 'ask':
        return await topics_callbacks(update, context, 'tp_panel')
    elif data.startswith('practice:'):
        await send_lesson(m, int(data.split(':')[1]), context)
    elif data.startswith('tq:'):
        text, kb = tq_make(data.split(':')[1])
        await m.reply_text(text, reply_markup=kb)
    elif data.startswith('tqa:'):
        _, topic, c, x = data.split(':')
        c, x = int(c), int(x); w = WORDS[c]
        res = '✅ To‘g‘ri!' if c == x else '❌ Noto‘g‘ri.'
        await m.reply_text(f'{res}\n\n{w[1]}\n{w[2]} — {w[3]}',
                           reply_markup=InlineKeyboardMarkup([[btn('🎲 Keyingi savol', f'tq:{topic}')], [btn('📚 Mavzular', 'tp_panel')]]))
    elif data == 'tw':
        w = random.choice(WORDS)
        await m.reply_text(f'🌟 TASODIFIY SO‘Z\n\n{w[1]}\n{w[2]} — {w[3]}\n\nMavzu: {TOPIC_PANEL[w[0]][0]}',
                           reply_markup=InlineKeyboardMarkup([[btn('🌟 Yana', 'tw'), btn('📚 Mavzular', 'tp_panel')]]))
    elif data == 'gr_panel':
        rows = [[btn(f'{i + 1}. {t}', f'gr:{i}')] for i, (t, _) in enumerate(GRAMMAR)]
        rows.append([btn('📚 Mavzular', 'tp_panel'), btn('🏠 Menyu', 'home')])
        await m.reply_text('🧩 ARAB TILI GRAMMATIKASI\n\nQisqa va sodda darslar. Birini tanlang:', reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith('gr:'):
        i = max(0, min(len(GRAMMAR) - 1, int(data.split(':')[1])))
        t, body = GRAMMAR[i]
        await m.reply_text(f'🧩 {i + 1}/{len(GRAMMAR)} — {t}\n\n{body}', reply_markup=InlineKeyboardMarkup([
            [btn('⬅️ Oldingi', f'gr:{max(0, i - 1)}'), btn('Keyingi ➡️', f'gr:{min(len(GRAMMAR) - 1, i + 1)}')],
            [btn('🧩 Ro‘yxat', 'gr_panel'), btn('🏠 Menyu', 'home')]]))
    else:
        return False
    return True


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); data=q.data or ''
    if not await access_ok(update, context): return
    if await topics_callbacks(update, context, data): return
    if data == 'seerah_panel':
        body = "🌙 PAYG‘AMBARIMIZ MUHAMMAD ﷺ HAYOTLARI\n\n" + "\n\n".join(
            f"📌 {title}\n{desc}" for title, desc in SEERAH_TOPICS
        ) + "\n\nEslatma: batafsil siyratni ishonchli siyrat va hadis manbalari bilan birga o‘rganing."
        await q.message.reply_text(body, reply_markup=islam_panel_markup())
    elif data == 'islam_panel':
        await q.message.reply_text("📚 ISLOM VA QUR’ON ILMLARI\n\nBo‘limni tanlang:", reply_markup=islam_panel_markup())
    elif data.startswith('islam:'):
        cat = int(data.split(':')[1])
        titles = ["📖 QUR’ON HAQIDA", "🕌 ISLOM ASOSLARI", "🤲 IBODATLAR", "🌿 ODOB-AXLOQ"]
        if cat == 0: items = ISLAM_TOPICS[:4]
        elif cat == 1: items = ISLAM_TOPICS[4:6]
        elif cat == 2: items = ISLAM_TOPICS[6:10]
        else: items = [("Yaxshi xulq", "Islom rostgo‘ylik, omonatdorlik, mehr-shafqat, adolat va ota-onaga yaxshilik qilishga chaqiradi.")]
        await q.message.reply_text(titles[cat] + "\n\n" + "\n\n".join(f"🔹 {a}\n{b}" for a,b in items),
                                   reply_markup=islam_panel_markup())
    elif data == 'test_panel':
        await q.message.reply_text(
            "📝 ISLOMIY TESTLAR\n\nQur’on, siyrat, payg‘ambarlar, Islom asoslari, arab alifbosi, so‘zlar, kundalik iboralar va suhbatlar bo‘yicha test ishlang.\n"
            f"Test topshiriqlari: 100 000 tagacha davom ettiriladigan mashq raqami.\n"
            f"Hozirgi tekshirilgan asosiy savollar banki: {len(QUIZ_BANK)} ta. Savollar tartibi va javob variantlari aralashtiriladi; bu 100 000 ta alohida tekshirilgan savol degani emas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 Testni boshlash", callback_data="quiz_next")],
                [InlineKeyboardButton("📖 Qur’on testlari", callback_data="quiz_quran")],
                [InlineKeyboardButton("🌙 Siyrat testlari", callback_data="quiz_seerah")],
                [InlineKeyboardButton("🕌 Islom asoslari testi", callback_data="quiz_islam")],
                [InlineKeyboardButton("🔤 Arab tili va so‘zlar testi", callback_data="quiz_arabic")],
                [InlineKeyboardButton("🗣️ Arabcha suhbat testi", callback_data="quiz_speaking")],
                [InlineKeyboardButton("🧔 Payg‘ambarlar testi", callback_data="quiz_prophets")],
                [InlineKeyboardButton("🏠 Bosh menyu", callback_data="home")]
            ])
        )
    elif data == 'prophets_panel':
        rows = []; row = []
        for i, (pname, _) in enumerate(PROPHETS):
            row.append(InlineKeyboardButton(pname.replace(' alayhissalom', ''), callback_data=f'prophet:{i}'))
            if len(row) == 2: rows.append(row); row = []
        if row: rows.append(row)
        rows.append([InlineKeyboardButton('📝 Payg‘ambarlar testi', callback_data='quiz_prophets')])
        rows.append([InlineKeyboardButton('🏠 Bosh menyu', callback_data='home')])
        await q.message.reply_text('🧔 PAYG‘AMBARLAR QISSALARI\n\nQur’onda nomi zikr qilingan 25 payg‘ambar haqida qisqa ma’lumot. Birini tanlang:', reply_markup=InlineKeyboardMarkup(rows))
    elif data.startswith('prophet:'):
        pi = max(0, min(len(PROPHETS) - 1, int(data.split(':')[1])))
        pname, ptext = PROPHETS[pi]
        await q.message.reply_text(f'🧔 {pi+1}/{len(PROPHETS)} — {pname}\n\n{ptext}\n\n{PROPHET_NOTE}', reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('⬅️ Oldingi', callback_data=f'prophet:{max(0, pi-1)}'), InlineKeyboardButton('Keyingi ➡️', callback_data=f'prophet:{min(len(PROPHETS)-1, pi+1)}')],
            [InlineKeyboardButton('📝 Payg‘ambarlar testi', callback_data='quiz_prophets')],
            [InlineKeyboardButton('🧔 Ro‘yxat', callback_data='prophets_panel'), InlineKeyboardButton('🏠 Menyu', callback_data='home')]
        ]))
    elif data == 'quiz_prophets':
        import random
        await send_quiz(q.message, context, random.choice(PROPHET_QUIZ_IDS))
    elif data in ('quiz_next','quiz_quran','quiz_seerah','quiz_islam','quiz_arabic','quiz_speaking'):
        if data in ('quiz_arabic','quiz_speaking'):
            import random
            pool = ARABIC_SPEAKING_IDS if data == 'quiz_speaking' else ARABIC_QUIZ_IDS
            chosen = random.choice(pool)
            await send_quiz(q.message, context, chosen)
        else:
            await send_quiz(q.message, context)
    elif data.startswith('answer:'):
        _, qid_s, answer_s = data.split(':')
        qid, answer = int(qid_s), int(answer_s)
        item = QUIZ_BANK[qid]
        if answer == item[2]:
            result = "✅ To‘g‘ri! "
        else:
            result = f"❌ Bu javob to‘g‘ri emas. To‘g‘ri javob: {item[1][item[2]]}. "
        await q.message.reply_text(result + item[3], reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎲 Keyingi test", callback_data="quiz_next")],
            [InlineKeyboardButton("📚 Test paneli", callback_data="test_panel")]
        ]))
        context.user_data['quiz_answered'] = context.user_data.get('quiz_answered', 0) + 1
    if data == 'zero_panel':
        await q.message.reply_text('🪜 ARAB TILINI 0 DAN O‘RGANISH\n\nBu yo‘l alifbodan boshlanib, talaffuz, so‘zlar, gap tuzish va mustaqil suhbatgacha olib boradi. Har kuni 15–20 daqiqa mashq qiling.\n\nBoshlash uchun bir bo‘limni tanlang:', reply_markup=ZERO_MENU)
    elif data == 'alphabet':
        lines = ['🔤 ARAB ALIFBOSI — 28 HARF', 'Har bir harfni nomi va lotincha talaffuzi bilan o‘rganing:', '']
        lines += [f'{i+1}. {ar} — {name} — {sound}' for i,(ar,name,sound) in enumerate(ALPHABET)]
        lines += ['', 'Eslatma: ث، ح، خ، ذ، ص، ض، ط، ظ، ع، غ، ق tovushlari o‘zbek tilidagi tovushlardan farq qilishi mumkin.']
        await q.message.reply_text('\n'.join(lines), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔊 Harflarni eshitish', callback_data='alphabet_audio')],[InlineKeyboardButton('⬅️ 0 dan o‘rganish', callback_data='zero_panel')]]))
    elif data == 'harakatlar':
        await q.message.reply_text('📘 HARAKATLAR\nَ Fatha — a: بَ = ba\nِ Kasra — i: بِ = bi\nُ Damma — u: بُ = bu\nْ Sukun — unlisiz: بْ\nّ Shadda — undoshni ikki marta aytish: بّ\nً ٍ ٌ Tanvin: an / in / un\n\nMashq: بَ بِ بُ ni sekin 5 marta o‘qing.', reply_markup=ZERO_MENU)
    elif data == 'letterforms':
        await q.message.reply_text('✍️ HARF SHAKLLARI\nArab harflari so‘z boshida, o‘rtasida va oxirida shaklini o‘zgartirishi mumkin. Masalan: ب  بـ  ـبـ  ـب\nا، د، ذ، ر، ز، و harflari keyingi harfga ulanmaydi. Avval harflarni alohida tanib, keyin bo‘g‘inlarni o‘qing.', reply_markup=ZERO_MENU)
    elif data == 'alphabet_audio':
        audio_path = None
        try:
            text_to_say = ' '.join(f'{name}. {sound}.' for _,name,sound in ALPHABET)
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f: audio_path=f.name
            await make_arabic_audio(text_to_say, audio_path)
            with open(audio_path,'rb') as af:
                await q.message.reply_audio(audio=af, title='Arab alifbosi talaffuzi', caption='Arab harflari talaffuzi. Tinglang va takrorlang.')
        except Exception as e:
            await q.message.reply_text('Audio yaratilmadi. Internetni tekshiring. Terminalda: pip install gTTS edge-tts. Xato: '+str(e)[:220])
        finally:
            if audio_path:
                try: os.remove(audio_path)
                except OSError: pass
    elif data == 'quiz_start':
        import random
        await send_quiz(q.message, context, random.choice(ARABIC_QUIZ_IDS))
    elif data=='home':
        context.user_data['mode']=None; await q.message.reply_text('Bosh menyu:',reply_markup=main_menu(update))
    elif data.startswith('lessons:'):
        await send_lesson(q.message,int(data.split(':')[1]),context)
    elif data.startswith('audio:'):
        n=int(data.split(':')[1]); l=lesson_data(n)
        audio_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f: audio_path=f.name
            await make_arabic_audio(l['ar'], audio_path)
            with open(audio_path, 'rb') as audio_file:
                await q.message.reply_audio(audio=audio_file, title=f"{n}-dars arabcha talaffuz", caption=l['ar'])
        except Exception as e:
            await q.message.reply_text(f"Arabcha matn: {l['ar']}\nTalaffuz: {l['latin']}\nAudio xatosi: {str(e)[:180]}\nTerminal: pip install gTTS edge-tts")
        finally:
            if audio_path:
                try: os.remove(audio_path)
                except OSError: pass
    elif data=='quran':
        await q.message.reply_text('📖 Qur’on surasi audiosi uchun /quran 1 deb yozing. Raqam 1–114 oralig‘ida bo‘lsin.')
    elif data=='help':
        await q.message.reply_text('📖 YORDAM\n\n/start — bosh menyu\n/lesson 1 — darsni ochish\n/lessons — dars raqamlari\n/translate — lug‘at\n/quran 1 — sura audiosi\n/profile — profil va hisob\n\n📚 O‘rganish tugmasi — mavzular, so‘zlar, audio va testlar\n🧩 Grammatika — qisqa darslar', reply_markup=main_menu(update))

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg=(update.effective_message.text or '').strip()
    mode=context.user_data.get('mode') or ''
    if mode.startswith('adm_') or mode=='admin_broadcast':
        if not is_admin(update):
            context.user_data['mode'] = None
            await update.effective_message.reply_text('⛔ Ruxsat yo‘q.'); return
        await admin_text(update, context, mode, msg); return
    if mode.startswith('reg_'):
        await registration_text(update, context, mode, msg); return
    if mode in ('top_amount','top_receipt'):
        if not await basic_ok(update, context): return
        if await topup_text(update, context, mode, msg): return
        mode = ''
    if not await access_ok(update, context): return
    act = REPLY_ACTIONS.get(norm_label(msg))
    if act:
        context.user_data['mode'] = None
        await dispatch_callback(update, context, act); return
    if mode != 'translate':
        await update.effective_message.reply_text('Menyudan bo‘lim tanlang yoki /lesson 1, /translate buyruqlaridan foydalaning.',reply_markup=main_menu(update)); return
    await update.effective_message.reply_text(dict_reply(msg), reply_markup=InlineKeyboardMarkup([[btn('📚 Mavzular', 'tp_panel'), btn('🏠 Menyu', 'home')]])); return
async def quran_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yuborilgan suraning to‘liq audio faylini yuklab, Telegramga fayl sifatida yuboradi."""
    try:
        n = int(context.args[0]) if context.args else 1
    except ValueError:
        await update.effective_message.reply_text('Sura raqamini yozing. Masalan: /quran 1')
        return
    if not 1 <= n <= 114:
        await update.effective_message.reply_text('Sura raqami 1 dan 114 gacha bo‘lishi kerak. Masalan: /quran 1')
        return

    # Bu manba har bir sura uchun bitta to‘liq MP3 beradi (oyatma-oyat emas).
    audio_url = f'https://cdn.islamic.network/quran/audio-surah/128/ar.alafasy/{n}.mp3'
    audio_path = None
    try:
        await update.effective_message.reply_text(f'⏳ {n}-suraning to‘liq qiroati yuklanmoqda...')
        req = urllib.request.Request(audio_url, headers={'User-Agent': 'Mozilla/5.0 ArabchaUstozBot/1.0'})
        with urllib.request.urlopen(req, timeout=60) as response:
            audio_bytes = response.read()
        if not audio_bytes or len(audio_bytes) < 1000:
            raise ValueError('Audio fayli bo‘sh yoki juda kichik.')
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name
        surah_names = {
            1: 'Fotiha', 2: 'Baqara', 3: 'Oli Imron', 4: 'Niso', 5: 'Moida',
            6: 'An’om', 7: 'A’rof', 8: 'Anfol', 9: 'Tavba', 10: 'Yunus',
            11: 'Hud', 12: 'Yusuf', 18: 'Kahf', 36: 'Yosin', 55: 'Rahmon',
            67: 'Mulk', 112: 'Ixlos', 113: 'Falaq', 114: 'Nos'
        }
        name = surah_names.get(n, f'{n}-sura')
        with open(audio_path, 'rb') as audio_file:
            await update.effective_message.reply_audio(
                audio=audio_file,
                title=f'{n}. {name} — to‘liq sura',
                caption=f'📖 {n}-sura: {name}\n🔊 Mishary Rashid Alafasy qiroati. Audio suraning boshidan oxirigacha.'
            )
    except Exception as e:
        print('Qur’on audio xatosi:', repr(e))
        await update.effective_message.reply_text(
            '⚠️ To‘liq sura audiosini yuklab bo‘lmadi. Internetni tekshiring va qayta urinib ko‘ring. '
            'Agar hostingda tashqi audio manbasi bloklangan bo‘lsa, boshqa hosting yoki audio manbasi kerak bo‘lishi mumkin.'
        )
    finally:
        if audio_path:
            try:
                os.remove(audio_path)
            except OSError:
                pass

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print('Bot xatosi:', context.error)

def main():
    if not BOT_TOKEN:
        raise SystemExit('BOT_TOKEN topilmadi. BotFather tokenini BOT_TOKEN muhit o‘zgaruvchisiga kiriting.')
    app=Application.builder().token(BOT_TOKEN).build()
    db_init()
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('admin',admin_cmd))
    app.add_handler(CommandHandler('help',help_cmd))
    app.add_handler(CommandHandler('lesson',guarded(lesson_cmd)))
    app.add_handler(CommandHandler('lessons',guarded(lessons_cmd)))
    app.add_handler(CommandHandler('translate',guarded(translate_shortcut)))
    app.add_handler(CommandHandler('quran',guarded(quran_cmd)))
    register_system_handlers(app)
    app.add_handler(CallbackQueryHandler(callback, pattern=r'^(?!adm:|reg:|sub:|top:|fs:|profile$)'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_message))
    app.add_error_handler(error_handler)
    print('Arabcha Ustoz AI bot ishga tushmoqda...')
    app.run_polling()

async def translate_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode']='translate'; await update.effective_message.reply_text('📖 LUG‘AT: so‘zni yozing (arabcha, talaffuz yoki o‘zbekcha). Masalan: kitob, shukran.')

if __name__=='__main__': main()
