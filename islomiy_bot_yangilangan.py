"""Arabcha Ustoz AI Telegram bot. Python 3.10+, python-telegram-bot 22.x.
Set BOT_TOKEN and optionally OPENAI_API_KEY as environment variables.
"""
import os, json, urllib.request, urllib.error, asyncio, tempfile, sqlite3, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# BotFather bergan YANGI tokenni quyidagi qo‘shtirnoq ichiga kiriting.
BOT_TOKEN = "BU_YERGA_YANGI_BOTFATHER_TOKEN".strip()
if BOT_TOKEN == "BU_YERGA_YANGI_BOTFATHER_TOKEN":
    BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
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

def api_chat(message: str, mode='chat') -> str:
    if not OPENAI_API_KEY:
        return ('AI ustozning to‘liq javobi uchun serverda OPENAI_API_KEY sozlanishi kerak.\n\n'
                'Hozircha menyudagi darslar, arabcha iboralar va tarjima misollaridan foydalanishingiz mumkin.')
    system = ('Sen o‘zbek tilida tushuntiradigan arab tili ustozisan. Arabcha gapirishni noldan o‘rgat. '
              'Javobni o‘zbek tilida ber; arabcha yozuv, lotincha talaffuz va o‘zbekcha ma’noni alohida ko‘rsat. '
              'Keyin o‘quvchiga bitta gapirish mashqi yoki savol ber. Noma’lum Qur’on oyatini to‘qib chiqarmagin.')
    if mode == 'translate':
        system += ' Tarjimon sifatida matnni o‘zbekcha va arabcha izoh bilan tarjima qil.'
    payload = {'model': OPENAI_MODEL, 'messages': [{'role':'system','content':system},{'role':'user','content':message}], 'temperature':0.5}
    req = urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(payload).encode(), headers={'Authorization':'Bearer '+OPENAI_API_KEY,'Content-Type':'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=45) as r: data=json.loads(r.read().decode())
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        return 'AI xizmatiga ulanishda xatolik. API kaliti va billing sozlamalarini tekshiring. ('+str(e)[:180]+')'

MAIN_MENU = InlineKeyboardMarkup([
 [InlineKeyboardButton('🪜 Arab tilini 0 dan', callback_data='zero_panel')],
 [InlineKeyboardButton('🌙 Payg‘ambarimiz Muhammad ﷺ hayoti', callback_data='seerah_panel')],
 [InlineKeyboardButton('📚 Islom va Qur’on haqida', callback_data='islam_panel')],
 [InlineKeyboardButton('🧔 Payg‘ambarlar qissalari', callback_data='prophets_panel')],
 [InlineKeyboardButton('📝 Islomiy testlar', callback_data='test_panel')],
 [InlineKeyboardButton('📚 10 000 ta arab tili darsi', callback_data='lessons:1')],
 [InlineKeyboardButton('🌐 Tarjimon', callback_data='translate'), InlineKeyboardButton('📖 Qur’on suralari', callback_data='quran')],
 [InlineKeyboardButton('🗣️ Gapirish mashqi', callback_data='speak'), InlineKeyboardButton('📊 Yo‘riqnoma', callback_data='help')],
])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    context.user_data['mode'] = None
    await update.effective_message.reply_text('🌙 Assalomu alaykum! Islomiy bilimlar va arab tilini o‘rganish botiga xush kelibsiz.\n\nPayg‘ambarimiz ﷺ siyratlari, Qur’on, Islom asoslari, testlar va arab tili darslarini tanlang.', reply_markup=MAIN_MENU)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text('/start — bosh menyu\n/lesson 1 — dars raqami\n/lessons — darslar ro‘yxati\n/ask — AI ustoz\n/translate — tarjimon\n/quran 1 — sura audiosi\n\nJami 10 000 ta raqamlangan dars yo‘li mavjud. AI javoblari uchun OPENAI_API_KEY kerak.', reply_markup=MAIN_MENU)

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
    q=update.callback_query; await q.answer(); data=q.data or ''
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
    if data.startswith('admin:'):
        if not is_admin(update):
            await q.message.reply_text('⛔ Ruxsat yo‘q.'); return
        action = data.split(':', 1)[1]
        if action == 'stats':
            with sqlite3.connect(DB_PATH) as db: count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            await q.message.reply_text(f'📊 BOT STATISTIKASI\n👥 Ro‘yxatdagi foydalanuvchilar: {count}\n📚 Darslar: {TOTAL_LESSONS}\n🧩 Asosiy bo‘limlar: Siyrat, Islom va Qur’on, testlar, darslar, tarjimon', reply_markup=ADMIN_MENU)
        elif action == 'broadcast':
            context.user_data['mode'] = 'admin_broadcast'
            await q.message.reply_text('📣 Yuboriladigan xabar matnini yuboring. Bekor qilish uchun /admin yozing.')
        elif action == 'lessons':
            await q.message.reply_text(f'📚 Darslar bo‘limi: 1–{TOTAL_LESSONS}. Darsni ochish: /lesson 125. Hozir darslar 20 ta asosiy mavzu asosida bosqichlar bo‘yicha takrorlanadi; bu 10 000 ta alohida yozilgan dars emas.', reply_markup=ADMIN_MENU)
        elif action == 'sections':
            await q.message.reply_text('🧭 BOT BO‘LIMLARI\n📚 Darslar — /lessons\n🤖 🌐 Tarjimon — /translate\n📖 Qur’on audio — /quran 1\n🗣️ Gapirish mashqi — bosh menyudan\n🛠️ Admin panel — /admin', reply_markup=ADMIN_MENU)
        return
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
        await q.message.reply_text('🗣️ GAPIRISHNI NOLDAN BOSHLAYMIZ. Birinchi jumla: السَّلَامُ عَلَيْكُمْ — as-salāmu alaykum — Assalomu alaykum. Javob: وَعَلَيْكُمُ السَّلَامُ — wa alaykumu-s-salām — Va alaykum assalom. Shu jumlalarni yozib yuboring yoki mikrofon orqali ovozli xabar jo‘nating. AI bilan mashq qilish uchun OPENAI_API_KEY kerak.', reply_markup=ZERO_MENU)
    elif data == 'quiz_start':
        import random
        await send_quiz(q.message, context, random.choice(ARABIC_QUIZ_IDS))
    elif data=='home':
        context.user_data['mode']=None; await q.message.reply_text('Bosh menyu:',reply_markup=MAIN_MENU)
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
        await q.message.reply_text('📖 Qur’on surasi audiosi uchun /quran 1 deb yozing. Raqam 1–114 oralig‘ida bo‘lsin.')
    elif data=='help':
        await q.message.reply_text('/lesson 1 — darsni ochish\n/lessons — dars raqamlari\n/ask — AI ustoz\n/translate — tarjimon\n/quran 1 — Fotiha surasi audiosi')

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_user(update)
    msg=(update.effective_message.text or '').strip()
    mode=context.user_data.get('mode')
    if mode == 'admin_broadcast':
        if not is_admin(update):
            context.user_data['mode'] = None
            await update.effective_message.reply_text('⛔ Ruxsat yo‘q.'); return
        await process_broadcast(update, context, msg)
        return
    if not mode:
        await update.effective_message.reply_text('Menyudan bo‘lim tanlang yoki /lesson 1, /ask, /translate buyruqlaridan foydalaning.',reply_markup=MAIN_MENU); return
    if mode=='translate': prompt='Quyidagi matnni arabcha↔o‘zbekcha tarjima qil. Javob o‘zbek tilida bo‘lsin; arabcha matn, talaffuz va ma’noni ajrat. Matn: '+msg
    else: prompt=msg
    await update.effective_message.reply_text('⏳ Ustoz javob tayyorlamoqda...')
    ans=await asyncio.to_thread(api_chat,prompt,mode)
    await update.effective_message.reply_text(ans)

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
