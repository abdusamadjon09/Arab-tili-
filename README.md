# 🌙 Arabcha Ustoz AI — Telegram bot

Arab tilini o'zbek tilida o'rgatadigan Telegram bot: darslar, AI ustoz, tarjimon, talaffuz audiosi va Qur'on suralari.

## Imkoniyatlar
- 📚 10 000 ta raqamlangan dars yo'li (alifbo, harakatlar, so'zlar, grammatika)
- 🤖 AI ustoz va tarjimon (bepul Groq yoki Gemini orqali)
- 🎧 Talaffuz audiosi va Qur'on suralari (to'liq audio)
- 📝 Mini-test va gapirish mashqlari
- 🎛 Pastki doimiy rangli menyu va inline panellar
- 🛠 Admin panel: `/admin` (statistika, xabar yuborish)

## O'rnatish
```bash
pip install -r requirements.txt
cp env.example .env     # keyin .env ichini to'ldiring
python bot.py
```

## Sozlamalar (`.env`)
| O'zgaruvchi | Izoh |
|---|---|
| `BOT_TOKEN` | @BotFather bergan token |
| `AI_KEY` | Groq (`gsk_...`) yoki Gemini (`AIza...`) key |
| `ADMIN_IDS` | Admin Telegram ID'lari, vergul bilan |
| `AI_PROVIDER` | Ixtiyoriy: `groq`, `gemini`, `openai` (odatda key'dan avtomatik aniqlanadi) |
| `AI_MODEL` | Ixtiyoriy: model nomini qo'lda berish |

Bepul key olish: [console.groq.com](https://console.groq.com) yoki [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

## Buyruqlar
`/start` · `/menu` · `/lesson 1` · `/lessons` · `/ask` · `/translate` · `/quran 1` · `/help` · `/admin`

## ⚠️ Xavfsizlik
Token va API key'larni **hech qachon** GitHub'ga yuklamang. Ular faqat `.env` faylida turadi (`.gitignore` uni yuklashdan saqlaydi).
