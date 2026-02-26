=== ИНСТРУКЦИЯ ===

ШАГ 1 — Вставь свои данные в bot.py:
  API_ID    = число с my.telegram.org
  API_HASH  = хеш с my.telegram.org
  PHONE     = твой номер +380...
  BOT_TOKEN = токен от @BotFather

ШАГ 2 — Запусти ЛОКАЛЬНО на компьютере:
  pip install telethon yt-dlp
  py bot.py

  Введи код который придёт в Telegram.
  После входа появится файл userbot_session.session

ШАГ 3 — Загрузи ВСЕ файлы на GitHub:
  bot.py
  requirements.txt
  nixpacks.toml
  Procfile
  userbot_session.session   <-- важно!

ШАГ 4 — Задеплой на Railway:
  railway.app -> New Project -> Deploy from GitHub

Готово! Бот работает без лимитов (до 2GB).
