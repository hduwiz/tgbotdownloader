import os
import asyncio
import glob
import yt_dlp
from telethon import TelegramClient, events
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
# =============================================
API_ID    = 39723229          # число с my.telegram.org
API_HASH  = "3e2b8ae519ce46f1e13f286050a56bca"         # хеш с my.telegram.org
PHONE     = "+380632362615"         # твой номер +380...
BOT_TOKEN = "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE"         # токен от @BotFather
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

ALLOWED_SOURCES = [
    "youtube.com", "youtu.be", "vimeo.com",
    "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "pornhub.com", "xvideos.com",
    "xhamster.com", "xnxx.com",
]

pending = {}


def is_allowed(url):
    return any(s in url for s in ALLOWED_SOURCES)


def cleanup_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def cleanup_all():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        try:
            os.remove(f)
        except Exception:
            pass


def get_ydl_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 5,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        },
    }


async def main():
    cleanup_all()

    # Userbot — Premium аккаунт, загружает файлы до 2GB
    userbot = TelegramClient("userbot_session", API_ID, API_HASH)
    await userbot.start(phone=PHONE)
    print("✅ Userbot запущен")

    # Bot — принимает команды от пользователей
    bot = await TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
    print("✅ Бот запущен")

    # Получаем entity бота через userbot — чтобы userbot мог слать ему файлы
    bot_entity = await userbot.get_entity(BOT_USERNAME)
    print(f"✅ Bot entity получен: {bot_entity.id}")

    @bot.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        await event.respond(
            "👋 Привет! Карман меня заказал.\n\n"
            "📎 Отправь ссылку на видео — скачаю без лимитов (до 2GB)."
        )

    @bot.on(events.NewMessage)
    async def url_handler(event):
        if not event.text or event.text.startswith("/"):
            return

        url = event.text.strip()
        if not url.startswith("http"):
            return

        if not is_allowed(url):
            await event.respond("❌ Источник не поддерживается.")
            return

        user_id = event.sender_id
        chat_id = event.chat_id

        msg = await event.respond("🔍 Получаю информацию...")

        ydl_opts = {**get_ydl_opts(), "skip_download": True}
        if "tiktok.com" in url:
            ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

        try:
            loop = asyncio.get_event_loop()

            def fetch_info():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            info = await loop.run_in_executor(None, fetch_info)

            title = info.get("title") or "Видео"
            thumbnail = info.get("thumbnail")
            duration = info.get("duration")
            uploader = info.get("uploader") or info.get("channel") or ""

            formats = info.get("formats", [])
            heights = set()
            for f in formats:
                h = f.get("height")
                if h and f.get("vcodec") != "none":
                    heights.add(h)

            wanted = [1080, 720, 480, 360]
            available = [q for q in wanted if any(h >= q for h in heights)]
            if not available:
                available = [720, 480]

            pending[user_id] = {
                "url": url,
                "title": title,
                "chat_id": chat_id,
            }

            dur_str = ""
            if duration:
                mins, secs = divmod(int(duration), 60)
                hours, mins = divmod(mins, 60)
                dur_str = f"\n⏱ {hours}:{mins:02d}:{secs:02d}" if hours else f"\n⏱ {mins}:{secs:02d}"

            quality_lines = "\n".join([f"  /q{q}_{user_id}" for q in available])
            text = (
                f"🎬 {title[:120]}\n"
                f"{'👤 ' + uploader if uploader else ''}{dur_str}\n\n"
                f"Выбери качество:\n{quality_lines}"
            )

            await msg.delete()

            if thumbnail:
                try:
                    await bot.send_file(chat_id, thumbnail, caption=text)
                except Exception:
                    await bot.send_message(chat_id, text)
            else:
                await bot.send_message(chat_id, text)

        except Exception as e:
            await msg.edit(f"❌ Ошибка: {str(e)[:200]}")

    @bot.on(events.NewMessage(pattern=r"/q(\d+)_(\d+)"))
    async def quality_handler(event):
        match = event.pattern_match
        quality = int(match.group(1))
        owner_id = int(match.group(2))
        user_id = event.sender_id

        if user_id != owner_id:
            return

        if user_id not in pending:
            await event.respond("❌ Сессия устарела. Отправь ссылку заново.")
            return

        info = pending[user_id]
        url = info["url"]
        title = info["title"]
        chat_id = info["chat_id"]

        msg = await event.respond(f"⏳ Скачиваю {quality}p...")

        ydl_opts = {
            **get_ydl_opts(),
            "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
            "format": f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
            "merge_output_format": "mp4",
        }

        if "tiktok.com" in url:
            ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

        filename = None

        try:
            loop = asyncio.get_event_loop()

            def do_download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    dl_info = ydl.extract_info(url, download=True)
                    fname = ydl.prepare_filename(dl_info)
                    base = os.path.splitext(fname)[0]
                    if os.path.exists(base + ".mp4"):
                        return base + ".mp4"
                    return fname

            filename = await loop.run_in_executor(None, do_download)

            if not os.path.exists(filename):
                files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".mp4", ".webm", ".mkv"))]
                if files:
                    filename = os.path.join(DOWNLOAD_DIR, sorted(
                        files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x))
                    )[-1])
                else:
                    raise FileNotFoundError("Файл не найден")

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            await msg.edit(f"📤 Отправляю {quality}p ({file_size_mb:.1f} MB)...")
            print(f"📤 Загружаю файл через userbot -> пересылаю в chat_id={chat_id}")

            # Шаг 1: userbot загружает файл и отправляет себе в Saved Messages
            sent = await userbot.send_file(
                "me",
                filename,
                caption=f"🎬 {title[:200]}\n📺 {quality}p  |  📦 {file_size_mb:.1f} MB",
                supports_streaming=True,
            )
            print(f"✅ Файл загружен в Saved Messages, пересылаю в чат...")

            # Шаг 2: пересылаем из Saved Messages в нужный чат через bot
            await bot.forward_messages(chat_id, sent.id, "me")
            print(f"✅ Переслано в chat_id={chat_id}!")

            # Удаляем из Saved Messages
            await userbot.delete_messages("me", sent.id)

            await msg.delete()
            if user_id in pending:
                del pending[user_id]

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            await msg.edit(f"❌ Ошибка:\n{str(e)[:300]}")
        finally:
            cleanup_file(filename)

    print("🤖 Всё запущено!")
    await asyncio.gather(
        bot.run_until_disconnected(),
        userbot.run_until_disconnected(),
    )


if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
