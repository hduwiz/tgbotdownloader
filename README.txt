=== ИНСТРУКЦИЯ ===

1. Переименуй .env.example в .env и заполни данные:
   BOT_TOKEN = токен от @BotFather
   API_ID    = число с my.telegram.org
   API_HASH  = хеш с my.telegram.org

2. Запусти локально:
   docker-compose up --build

3. Для Railway:
   - Загрузи все файлы на GitHub
   - В Railway создай проект из GitHub
   - Добавь переменные окружения: BOT_TOKEN, API_ID, API_HASH
   - Railway сам соберёт Docker контейнер

=== КАК ЭТО РАБОТАЕТ ===

Локальный Bot API сервер (aiogram/telegram-bot-api) 
снимает ограничение 50MB и позволяет отправлять файлы до 2GB.
Никаких userbot, никаких Premium аккаунтов не нужно!
