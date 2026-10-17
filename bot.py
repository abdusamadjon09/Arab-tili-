"""Arabcha Ustoz AI Telegram bot. Python 3.10+, python-telegram-bot 22.x.
Sozlamalar .env faylida yoki muhit o‘zgaruvchilarida: BOT_TOKEN, AI_KEY (Groq/Gemini), ADMIN_IDS.
"""
import os, json, urllib.request, urllib.error, asyncio, tempfile, sqlite3, time
from types import SimpleNamespace
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters


def _load_env(path='.env'):
    """Oddiy .env o‘qish (qo‘shimcha kutubxona kerak emas)."""
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except OSError:
        pass
_load_env()

# BotFather bergan YANGI tokenni quyidagi qo‘shtirnoq ichiga kiriting.
BOT_TOKEN = "BU_YERGA_YANGI_BOTFATHER_TOKEN".strip()
if BOT_TOKEN == "BU_YERGA_YANGI_BOTFATHER_TOKEN":
    BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
# --- AI sozlamalari (bepul: Gemini yoki Groq) ---
# Key'ni pastdagi qo‘shtirnoq ichiga yozing yoki AI_KEY muhit o‘zgaruvchisiga kiriting.
AI_KEY = "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".strip()
if AI_KEY == "BU_YERGA_AI_KEY":
    AI_KEY = (os.getenv('AI_KEY') or os.getenv('OPENAI_API_KEY') or '').strip()
# Provayder key'dan avtomatik aniqlanadi: gsk_ = Groq, AIza = Gemini, sk- = OpenAI
_p = os.getenv('AI_PROVIDER', '').strip().lower()
if not _p:
    _p = 'groq' if AI_KEY.startswith('gsk_') else 'gemini' if AI_KEY.startswith('AIza') else 'openai' if AI_KEY.startswith('sk-') else 'groq'
AI_PROVIDER = _p
PROVIDERS = {
    'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
    'groq':   'https://api.groq.com/openai/v1',
    'openai': 'https://api.openai.com/v1',
}
# Model nomlari tez-tez o‘zgaradi, shuning uchun bot ro‘yxatdan mavjudini o‘zi tanlaydi.
PREFERRED = {
    'groq':   ['openai/gpt-oss-120b', 'qwen/qwen3.6-27b', 'openai/gpt-oss-20b'],
    'gemini': ['gemini-2.5-flash', 'gemini-flash-latest', 'gemini-2.5-flash-lite'],
    'openai': ['gpt-4o-mini', 'gpt-4.1-mini'],
}
AI_BASE = PROVIDERS.get(AI_PROVIDER, PROVIDERS['groq'])
AI_MODEL = os.getenv('AI_MODEL', '').strip()
_MODEL_CACHE = []
TOTAL_LESSONS = 10000
DB_PATH = os.getenv('BOT_DB_PATH', 'arabcha_ustoz.db')
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS', os.getenv('ADMIN_ID', '')).split(',') if x.strip().isdigit()}

def db_init():
    with sqlite3.connect(DB_PATH) as db:
        db.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at INTEGER)')

def remember_user(update):
    user = update.effective_user
    if not user: return
    with sqlite3.connect(DB_PATH) as db:
        db.execute('INSERT OR REPLACE INTO users(user_id, username, first_name, joined_at) VALUES(?,?,?,COALESCE((SELECT joined_at FROM users WHERE user_id=?),?))', (user.id, user.username or '', user.first_name or '', user.id, int(time.time())))

def is_admin(update):
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


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

def _http(url, payload=None, timeout=45):
    headers = {'Authorization': 'Bearer ' + AI_KEY, 'Content-Type': 'application/json', 'User-Agent': 'ArabchaUstozBot/1.0'}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if payload is not None else 'GET')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

def model_candidates():
    """Ishlatiladigan modellar ro‘yxati: avval mavjudlari, keyin qolganlari."""
    if AI_MODEL:
        return [AI_MODEL]
    if _MODEL_CACHE:
        return list(_MODEL_CACHE)
    pref = PREFERRED.get(AI_PROVIDER, [])
    found = []
    try:
        ids = [m.get('id', '').replace('models/', '') for m in _http(AI_BASE + '/models', timeout=20).get('data', [])]
        found = [m for m in pref if m in ids]
        if not found:
            found = [i for i in ids if any(k in i for k in ('gpt-oss', 'llama', 'qwen', 'gemini')) and not any(k in i for k in ('guard', 'whisper', 'tts', 'embed', 'image', 'vision'))][:3]
    except Exception as e:
        print('Modellar ro‘yxatini olib bo‘lmadi:', repr(e))
    result = found + [m for m in pref if m not in found]
    _MODEL_CACHE.extend(result)
    return result

def api_chat(message: str, mode='chat') -> str:
    if not AI_KEY:
        return ('AI ustozning to‘liq javobi uchun AI_KEY sozlanishi kerak.\n\n'
                'Hozircha menyudagi darslar, arabcha iboralar va tarjima misollaridan foydalanishingiz mumkin.')
    system = ('Sen o‘zbek tilida tushuntiradigan arab tili ustozisan. Arabcha gapirishni noldan o‘rgat. '
              'Javobni o‘zbek tilida ber; arabcha yozuv, lotincha talaffuz va o‘zbekcha ma’noni alohida ko‘rsat. '
              'Keyin o‘quvchiga bitta gapirish mashqi yoki savol ber. Noma’lum Qur’on oyatini to‘qib chiqarmagin.')
    if mode == 'translate':
        system += ' Tarjimon sifatida matnni o‘zbekcha va arabcha izoh bilan tarjima qil.'
    last_err = ''
    for model in model_candidates():
        payload = {'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': message}], 'temperature': 0.5}
        try:
            data = _http(AI_BASE + '/chat/completions', payload)
            text = (data['choices'][0]['message'].get('content') or '').strip()
            if text:
                return text
            last_err = model + ': bo‘sh javob'
        except urllib.error.HTTPError as e:
            try: body = e.read().decode()[:200]
            except Exception: body = ''
            last_err = f'{model}: HTTP {e.code} {body}'
            print('AI xatosi:', last_err)
            if e.code in (400, 404):
                continue   # model topilmadi/o‘chirilgan bo‘lishi mumkin, keyingisini sinaymiz
            if e.code in (401, 403):
                return 'AI kaliti noto‘g‘ri yoki ruxsat yo‘q. Key’ni tekshiring. (' + last_err[:150] + ')'
            if e.code == 429:
                return 'AI kunlik/daqiqalik limiti tugadi. Birozdan keyin qayta urinib ko‘ring.'
            break
        except Exception as e:
            last_err = f'{model}: {e!r}'
            print('AI xatosi:', last_err)
            break
    _MODEL_CACHE.clear()
    return 'AI xizmatiga ulanishda xatolik. (' + last_err[:200] + ')'

def _btn(text, data, style=None):
    """Tugma. style: 'primary' (ko‘k), 'success' (yashil), 'danger' (qizil). Yangi Telegram versiyalarida rangli ko‘rinadi."""
    if not style:
        return InlineKeyboardButton(text, callback_data=data)
    try:
        return InlineKeyboardButton(text, callback_data=data, style=style)
    except TypeError:   # eski python-telegram-bot versiyasi
        return InlineKeyboardButton(text, callback_data=data, api_kwargs={'style': style})

def _kb(*rows):
    return InlineKeyboardMarkup([[_btn(*b) for b in row] for row in rows])

BACK = [('⬅️ Bosh panel', 'home', 'danger')]

MAIN_MENU = _kb(
 [('🚀 Arab tilini 0 dan', 'zero_panel')],
 [('📚 O‘rganish', 'menu:learn', 'success'), ('🤖 AI ustoz', 'menu:ai', 'primary')],
 [('🎧 Tinglash', 'menu:listen', 'danger'), ('📝 Mashq va test', 'menu:practice', 'success')],
 [('ℹ️ Yo‘riqnoma', 'menu:help')],
)

# Har bir panel: (matn, tugmalar). Panellar xabarni o‘zida almashtiradi (chat to‘lib ketmaydi).
PANELS = {
 'main': ('🌙 ARABCHA USTOZ — BOSH PANEL\n\nQuyidagi bo‘limlardan birini tanlang:', MAIN_MENU),
 'learn': ('📚 O‘RGANISH PANELI\n\nAlifbodan boshlab, bosqichma-bosqich o‘rganing.', _kb(
    [('🪜 Arab tilini 0 dan', 'zero_panel')],
    [('🔤 Alifbo', 'alphabet', 'success'), ('َ Harakatlar', 'harakatlar', 'primary')],
    [('✍️ Harf shakllari', 'letterforms'), ('🧩 So‘z va iboralar', 'lessons:3')],
    [('📘 Grammatika', 'lessons:11'), ('📚 10 000 ta dars', 'lessons:1', 'success')],
    BACK)),
 'ai': ('🤖 AI USTOZ PANELI\n\nSavol bering, tarjima qiling yoki gapirishni mashq qiling.', _kb(
    [('💬 Savol berish', 'ask', 'success'), ('🌐 Tarjimon', 'translate', 'primary')],
    [('🗣️ Gapirish mashqi', 'speak'), ('🗣️ Noldan gapirish', 'speak_start')],
    BACK)),
 'listen': ('🎧 TINGLASH PANELI\n\nTalaffuz va Qur’on qiroatini tinglang.', _kb(
    [('🔊 Alifbo talaffuzi', 'alphabet_audio', 'primary')],
    [('📖 Qur’on suralari', 'quran', 'success')],
    BACK)),
 'practice': ('📝 MASHQ VA TEST PANELI\n\nO‘rganganingizni mustahkamlang.', _kb(
    [('📝 Mini-test', 'quiz_start', 'success'), ('🗣️ Gapirish mashqi', 'speak', 'primary')],
    [('🤖 AI bilan mashq', 'ask')],
    BACK)),
 'quran': ('📖 QUR’ON SURALARI\n\nSurani tanlang (to‘liq audio). Boshqa sura uchun: /quran 1 … /quran 114', _kb(
    [('1 Fotiha', 'sura:1', 'success'), ('36 Yosin', 'sura:36', 'danger')],
    [('55 Rahmon', 'sura:55', 'primary'), ('67 Mulk', 'sura:67', 'success')],
    [('18 Kahf', 'sura:18', 'danger'), ('112 Ixlos', 'sura:112', 'primary')],
    [('113 Falaq', 'sura:113'), ('114 Nos', 'sura:114')],
    [('⬅️ Tinglash', 'menu:listen'), ('🏠 Bosh panel', 'home', 'danger')])),
 'help': ('ℹ️ YO‘RIQNOMA\n\n/start — bosh panel\n/lesson 1 — darsni ochish\n/lessons — dars raqamlari\n/ask — AI ustoz\n/translate — tarjimon\n/quran 1 — sura audiosi', _kb(BACK)),
}

# ---------- Pastki doimiy menyu (klaviatura o‘rnida chiqadi) ----------
MB = {
 'zero': '🚀 Arab tilini 0 dan', 'learn': '📚 O‘rganish', 'ai': '🤖 AI ustoz',
 'translate': '🌐 Tarjimon', 'speak': '🗣️ Gapirish mashqi', 'listen': '🎧 Tinglash',
 'quran': '📖 Qur’on suralari', 'practice': '📝 Mashq va test', 'lessons': '📚 10 000 ta dars',
 'alphabet': '🔤 Alifbo', 'help': 'ℹ️ Yordam', 'admin': '🛠 Admin panel',
}
# tugma yozuvi -> callback_data (mavjud handlerlar qayta ishlatiladi)
MENU_BUTTONS = {
 MB['zero']: 'zero_panel', MB['learn']: 'menu:learn', MB['ai']: 'ask',
 MB['translate']: 'translate', MB['speak']: 'speak', MB['listen']: 'menu:listen',
 MB['quran']: 'quran', MB['practice']: 'menu:practice', MB['lessons']: 'lessons:1',
 MB['alphabet']: 'alphabet', MB['help']: 'menu:help',
}

def _rbtn(text, style=None):
    if not style:
        return KeyboardButton(text)
    try:
        return KeyboardButton(text, style=style)
    except TypeError:   # eski python-telegram-bot versiyasi
        return KeyboardButton(text, api_kwargs={'style': style})

def main_reply_kb(update=None):
    rows = [
        [_rbtn(MB['zero'])],
        [_rbtn(MB['learn'], 'success'), _rbtn(MB['ai'], 'primary')],
        [_rbtn(MB['translate'], 'primary'), _rbtn(MB['speak'], 'success')],
        [_rbtn(MB['listen'], 'danger'), _rbtn(MB['quran'], 'success')],
        [_rbtn(MB['practice'], 'success'), _rbtn(MB['lessons'], 'primary')],
        [_rbtn(MB['alphabet']), _rbtn(MB['help'])],
    ]
    if update is not None and is_admin(update):
        rows.append([_rbtn(MB['admin'], 'danger')])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True,
                               input_field_placeholder='Bo‘limni tanlang yoki savol yozing…')

class _MsgProxy:
    """Foydalanuvchi xabarini callback kodi uchun moslashtiradi (tahrirlash o‘rniga yangi xabar yuboradi)."""
    def __init__(self, msg): self._m = msg
    def __getattr__(self, name): return getattr(self._m, name)
    async def edit_text(self, text, reply_markup=None, **kw):
        return await self._m.reply_text(text, reply_markup=reply_markup)

class _FakeQuery:
    def __init__(self, msg, data):
        self.message = _MsgProxy(msg); self.data = data
    async def answer(self, *a, **k): pass

async def run_menu_button(update, context, data):
    fake = SimpleNamespace(callback_query=_FakeQuery(update.effective_message, data),
                           effective_user=update.effective_user, effective_message=update.effective_message)
    await callback(fake, context)

async def show_panel(q, key):
    """Panelni mavjud xabarning o‘zida almashtiradi; bo‘lmasa yangi xabar yuboradi."""
    text, kb = PANELS.get(key, PANELS['main'])
    try:
        await q.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        if 'not modified' in str(e).lower():
            return
        await q.message.reply_text(text, reply_markup=kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    context.user_data['mode'] = None
    await update.effective_message.reply_text('🌙 Assalomu alaykum! Arabcha Ustoz AI botiga xush kelibsiz.\n\nArab tilini o‘zbek tilida o‘rganing: darslar, tarjima, gapirish mashqlari va Qur’on qiroati.', reply_markup=main_reply_kb(update))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('/start — bosh menyu\n/lesson 1 — dars raqami\n/lessons — darslar ro‘yxati\n/ask — AI ustoz\n/translate — tarjimon\n/quran 1 — sura audiosi\n\nJami 10 000 ta raqamlangan dars yo‘li mavjud. AI javoblari uchun AI_KEY kerak.', reply_markup=MAIN_MENU)

async def send_lesson(chat, n: int, context):
    l = lesson_data(n)
    text = (f"📚 {l['n']}/ {TOTAL_LESSONS}-dars — {l['title']}\n"
            f"🎯 Bosqich: {l['level']} · Mavzu takrorlanish bosqichi: {l['stage']}\n\n"
            f"📝 Maqsad: {l['goal']}\n\n🇸🇦 Arabcha: {l['ar']}\n🔤 Talaffuz: {l['latin']}\n🇺🇿 O‘zbekcha ma’nosi: {l['uz']}\n\n"
            '🔊 Arabcha iborani eshitish uchun “Arabcha audio” tugmasini bosing. Keyin jumlani ovoz chiqarib 3 marta takrorlang.')
    keyboard = InlineKeyboardMarkup([
      [InlineKeyboardButton('🔊 Arabcha audio', callback_data=f"audio:{n}"), InlineKeyboardButton('🤖 Shu darsni ustoz bilan', callback_data=f"practice:{n}")],
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

ADMIN_MENU = InlineKeyboardMarkup([
 [InlineKeyboardButton('📊 Statistika', callback_data='admin:stats'), InlineKeyboardButton('📣 Xabar yuborish', callback_data='admin:broadcast')],
 [InlineKeyboardButton('📚 Darslar sozlamasi', callback_data='admin:lessons'), InlineKeyboardButton('🧭 Bo‘limlar', callback_data='admin:sections')],
 [InlineKeyboardButton('🏠 Bosh menyu', callback_data='home')]
])

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    if not is_admin(update):
        await update.effective_message.reply_text('⛔ Bu panel faqat bot administratori uchun. ADMIN_ID sozlamasini tekshiring.')
        return
    context.user_data['mode'] = None
    await update.effective_message.reply_text('🛠 ADMIN PANEL\n\nKerakli bo‘limni tanlang:', reply_markup=ADMIN_MENU)

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.effective_message.reply_text('Ruxsat yo‘q.'); return
    context.user_data['mode'] = 'admin_broadcast'
    await update.effective_message.reply_text('📣 Barcha foydalanuvchilarga yuboriladigan xabar matnini yuboring. Bekor qilish: /admin')

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not is_admin(update):
        await update.effective_message.reply_text('Ruxsat yo‘q.'); return
    with sqlite3.connect(DB_PATH) as db:
        ids = [row[0] for row in db.execute('SELECT user_id FROM users').fetchall()]
    ok = 0; failed = 0
    await update.effective_message.reply_text(f'📣 Xabar {len(ids)} foydalanuvchiga yuborilmoqda...')
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            ok += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1
    context.user_data['mode'] = None
    await update.effective_message.reply_text(f'✅ Yuborildi: {ok}\n⚠️ Yuborilmadi: {failed}', reply_markup=ADMIN_MENU)

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


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; data=q.data or ''
    try:
        await q.answer()
    except Exception:
        pass   # eski tugma bosilganda "Query is too old" chiqadi — bu xavfli emas, davom etamiz
    if data.startswith('admin:'):
        if not is_admin(update):
            await q.message.reply_text('⛔ Ruxsat yo‘q.'); return
        action = data.split(':', 1)[1]
        if action == 'stats':
            with sqlite3.connect(DB_PATH) as db: count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            await q.message.reply_text(f'📊 BOT STATISTIKASI\n👥 Ro‘yxatdagi foydalanuvchilar: {count}\n📚 Darslar: {TOTAL_LESSONS}\n🧩 Asosiy bo‘limlar: Darslar, AI ustoz, Tarjimon, Gapirish, Qur’on', reply_markup=ADMIN_MENU)
        elif action == 'broadcast':
            context.user_data['mode'] = 'admin_broadcast'
            await q.message.reply_text('📣 Yuboriladigan xabar matnini yuboring. Bekor qilish uchun /admin yozing.')
        elif action == 'lessons':
            await q.message.reply_text(f'📚 Darslar bo‘limi: 1–{TOTAL_LESSONS}. Darsni ochish: /lesson 125. Hozir darslar 20 ta asosiy mavzu asosida bosqichlar bo‘yicha takrorlanadi; bu 10 000 ta alohida yozilgan dars emas.', reply_markup=ADMIN_MENU)
        elif action == 'sections':
            await q.message.reply_text('🧭 BOT BO‘LIMLARI\n📚 Darslar — /lessons\n🤖 AI ustoz — /ask\n🌐 Tarjimon — /translate\n📖 Qur’on audio — /quran 1\n🗣️ Gapirish mashqi — bosh menyudan\n🛠️ Admin panel — /admin', reply_markup=ADMIN_MENU)
        return
    if data.startswith('menu:'):
        await show_panel(q, data.split(':', 1)[1]); return
    if data.startswith('sura:'):
        await send_sura(q.message, int(data.split(':')[1])); return
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
    elif data == 'speak_start':
        context.user_data['mode']='chat'
        await q.message.reply_text('🗣️ GAPIRISHNI NOLDAN BOSHLAYMIZ. Birinchi jumla: السَّلَامُ عَلَيْكُمْ — as-salāmu alaykum — Assalomu alaykum. Javob: وَعَلَيْكُمُ السَّلَامُ — wa alaykumu-s-salām — Va alaykum assalom. Shu jumlalarni yozib yuboring yoki mikrofon orqali ovozli xabar jo‘nating. AI bilan mashq qilish uchun AI_KEY kerak.', reply_markup=ZERO_MENU)
    elif data == 'quiz_start':
        await q.message.reply_text('📝 MINI-TEST: بَ harfi qanday o‘qiladi?\nA) bi\nB) ba\nC) bu\n\nJavobni AI ustozga yozing yoki harakatlar bo‘limini qayta ko‘ring.', reply_markup=ZERO_MENU)
    elif data=='home':
        context.user_data['mode']=None; await show_panel(q, 'main')
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
    elif data.startswith('practice:'):
        l=lesson_data(int(data.split(':')[1])); context.user_data['mode']='chat'
        prompt=f"Menga {l['n']}-dars: {l['title']} mavzusini o‘zbek tilida tushuntir. Arabcha: {l['ar']}. Talaffuz: {l['latin']}. Ma’nosi: {l['uz']}. Keyin men bilan arabcha gapirish mashqi qil."
        await q.message.reply_text('🤖 AI ustoz javob tayyorlamoqda...')
        ans=await asyncio.to_thread(api_chat,prompt)
        await q.message.reply_text(ans)
    elif data=='ask':
        context.user_data['mode']='chat'; await q.message.reply_text('AI ustozga savolingizni yozing. Masalan: “O‘zimni arab tilida tanishtirishni o‘rgat”.')
    elif data=='translate':
        context.user_data['mode']='translate'; await q.message.reply_text('Tarjima qilinadigan arabcha yoki o‘zbekcha matnni yuboring. Tarjima o‘zbek tilida tushuntiriladi.')
    elif data=='speak':
        context.user_data['mode']='chat'; await q.message.reply_text('🗣️ Gapirish mashqi: “Salomlashishni mashq qilaylik” deb yozing. Men arabcha jumla, talaffuz va o‘zbekcha ma’nosini beraman. Telegramda ovozli xabar ham yuborishingiz mumkin, agar botingizda speech-to-text qo‘shilmagan bo‘lsa, uni matnga aylantirib yuboring.')
    elif data=='quran':
        await show_panel(q, 'quran')
    elif data=='help':
        await show_panel(q, 'help')

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg=(update.effective_message.text or '').strip()
    mode=context.user_data.get('mode')
    if msg == MB['admin']:
        context.user_data['mode'] = None
        await admin_cmd(update, context); return
    if msg in MENU_BUTTONS:
        context.user_data['mode'] = None
        await run_menu_button(update, context, MENU_BUTTONS[msg]); return
    if mode == 'admin_broadcast':
        if not is_admin(update):
            context.user_data['mode'] = None
            await update.effective_message.reply_text('⛔ Ruxsat yo‘q.'); return
        await process_broadcast(update, context, msg)
        return
    if not mode:
        await update.effective_message.reply_text('Pastdagi menyudan bo‘lim tanlang yoki /lesson 1, /ask, /translate buyruqlaridan foydalaning.',reply_markup=main_reply_kb(update)); return
    if mode=='translate': prompt='Quyidagi matnni arabcha↔o‘zbekcha tarjima qil. Javob o‘zbek tilida bo‘lsin; arabcha matn, talaffuz va ma’noni ajrat. Matn: '+msg
    else: prompt=msg
    await update.effective_message.reply_text('⏳ Ustoz javob tayyorlamoqda...')
    ans=await asyncio.to_thread(api_chat,prompt,mode)
    await update.effective_message.reply_text(ans)

async def quran_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/quran N — suraning to‘liq audio faylini yuboradi."""
    try:
        n = int(context.args[0]) if context.args else 1
    except ValueError:
        await update.effective_message.reply_text('Sura raqamini yozing. Masalan: /quran 1')
        return
    if not 1 <= n <= 114:
        await update.effective_message.reply_text('Sura raqami 1 dan 114 gacha bo‘lishi kerak. Masalan: /quran 1')
        return
    await send_sura(update.effective_message, n)

_SURA_FILE_IDS = {}   # bir marta yuborilgan sura qayta yuklanmasligi uchun (Telegram file_id)
SURAH_NAMES = {
    1: 'Fotiha', 2: 'Baqara', 3: 'Oli Imron', 4: 'Niso', 5: 'Moida',
    6: 'An’om', 7: 'A’rof', 8: 'Anfol', 9: 'Tavba', 10: 'Yunus',
    11: 'Hud', 12: 'Yusuf', 18: 'Kahf', 36: 'Yosin', 55: 'Rahmon',
    67: 'Mulk', 112: 'Ixlos', 113: 'Falaq', 114: 'Nos'
}

def _download(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 ArabchaUstozBot/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

async def send_sura(msg, n: int):
    """Suraning to‘liq audiosini yuklab, Telegramga yuboradi (buyruq ham, tugma ham shu funksiyani ishlatadi)."""
    # Bu manba har bir sura uchun bitta to‘liq MP3 beradi (oyatma-oyat emas).
    audio_url = f'https://cdn.islamic.network/quran/audio-surah/128/ar.alafasy/{n}.mp3'
    name = SURAH_NAMES.get(n, f'{n}-sura')
    title = f'{n}. {name} — to‘liq sura'
    caption = f'📖 {n}-sura: {name}\n🔊 Mishary Rashid Alafasy qiroati. Audio suraning boshidan oxirigacha.'
    audio_path = None
    try:
        if n in _SURA_FILE_IDS:   # avval yuborilgan bo‘lsa, qayta yuklamaymiz
            await msg.reply_audio(audio=_SURA_FILE_IDS[n], title=title, caption=caption)
            return
        await msg.reply_text(f'⏳ {n}-suraning to‘liq qiroati yuklanmoqda... (sekin internetda bir necha daqiqa ketishi mumkin)')
        audio_bytes = await asyncio.to_thread(_download, audio_url)   # bot qotib qolmasligi uchun alohida oqimda
        if not audio_bytes or len(audio_bytes) < 1000:
            raise ValueError('Audio fayli bo‘sh yoki juda kichik.')
        if len(audio_bytes) > 49 * 1024 * 1024:   # Telegram bot fayl limiti ~50 MB
            await msg.reply_text(f'📖 {n}-sura ({name}) fayli juda katta, botdan yuborib bo‘lmaydi. Havola orqali tinglang:\n{audio_url}')
            return
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name
        with open(audio_path, 'rb') as audio_file:
            sent = await msg.reply_audio(audio=audio_file, title=title, caption=caption)
        try:
            _SURA_FILE_IDS[n] = sent.audio.file_id
        except Exception:
            pass
    except Exception as e:
        print('Qur’on audio xatosi:', repr(e))
        if 'TimedOut' in repr(e) or 'timed out' in repr(e).lower():
            text = ('⚠️ Internet sekin bo‘lgani uchun audio yuborilmadi (vaqt tugadi). Qayta urinib ko‘ring '
                    'yoki qisqaroq sura tanlang (masalan, 112 Ixlos).\nHavola orqali ham tinglash mumkin:\n' + audio_url)
        else:
            text = ('⚠️ To‘liq sura audiosini yuklab bo‘lmadi. Internetni tekshiring va qayta urinib ko‘ring.\n'
                    'Havola orqali tinglash mumkin:\n' + audio_url)
        try:
            await msg.reply_text(text)
        except Exception:
            pass
    finally:
        if audio_path:
            try:
                os.remove(audio_path)
            except OSError:
                pass

BOT_VERSION = '2026-10-17 v6 (pastki rangli menyu)'

async def version_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('🤖 Bot versiyasi: ' + BOT_VERSION)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    err = str(context.error)
    if 'Query is too old' in err or 'query id is invalid' in err:
        return   # eski inline tugma bosilgan, e’tibor bermaymiz
    if 'Conflict' in err:
        print('⚠️ DIQQAT: shu token bilan boshqa joyda ham bot ishlayapti! Eski nusxani to‘xtating. (' + err[:120] + ')')
    else:
        print('Bot xatosi:', err)

def main():
    if not BOT_TOKEN:
        raise SystemExit('BOT_TOKEN topilmadi. BotFather tokenini BOT_TOKEN muhit o‘zgaruvchisiga kiriting.')
    app=Application.builder().token(BOT_TOKEN).connect_timeout(30).read_timeout(120).write_timeout(300).pool_timeout(30).get_updates_read_timeout(60).build()
    db_init()
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('menu',start))
    app.add_handler(CommandHandler('version',version_cmd))
    app.add_handler(CommandHandler('admin',admin_cmd))
    app.add_handler(CommandHandler('help',help_cmd))
    app.add_handler(CommandHandler('lesson',lesson_cmd))
    app.add_handler(CommandHandler('lessons',lessons_cmd))
    app.add_handler(CommandHandler('ask',lambda u,c: ask_shortcut(u,c)))
    app.add_handler(CommandHandler('translate',translate_shortcut))
    app.add_handler(CommandHandler('quran',quran_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_message))
    app.add_error_handler(error_handler)
    print('Arabcha Ustoz AI bot ishga tushmoqda...')
    app.run_polling()

async def ask_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode']='chat'; await update.effective_message.reply_text('Savolingizni yozing — arab tilini o‘zbek tilida tushuntiraman.')
async def translate_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode']='translate'; await update.effective_message.reply_text('Tarjima qilinadigan matnni yuboring.')

if __name__=='__main__': main()
