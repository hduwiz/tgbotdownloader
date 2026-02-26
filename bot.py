import os
import asyncio
import glob
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# =============================================
# Токен берётся из переменной окружения Railway
# В Railway: Variables -> BOT_TOKEN = твой токен
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")

ALLOWED_SOURCES = [
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "rt.pornhub.com",
    "xvideos.com",
    "xhamster.com",
    "xnxx.com",
    "ru.pinterest.com",
]
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

pending = {}


def is_allowed(url: str) -> bool:
    return any(source in url for source in ALLOWED_SOURCES)


def get_ydl_opts_base():
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 5,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }


def cleanup_file(filepath: str):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass


def cleanup_all_downloads():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        try:
            os.remove(f)
        except Exception:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Карман меня заказал.\n\n"
        "📋 Поддерживаю все виды ссылок для скачивания\n\n"
        "📎 Просто отправь ссылку на видео — я его скачаю и пришлю тебе."
    )


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sources_list = "\n".join(f"• {s}" for s in ALLOWED_SOURCES)
    await update.message.reply_text(f"📋 Разрешённые источники:\n{sources_list}")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not url.startswith("http"):
        return

    if not is_allowed(url):
        await update.message.reply_text("❌ Этот источник не разрешён. /sources — список доступных.")
        return

    msg = await update.message.reply_text("🔍 Получаю информацию о видео...")

    ydl_opts = {**get_ydl_opts_base(), "skip_download": True}

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

        pending[user_id] = {"url": url, "title": title, "thumbnail": thumbnail}

        # Только 720p и 480p
        buttons = [[
            InlineKeyboardButton("🟢 720p", callback_data=f"dl_{user_id}_720"),
            InlineKeyboardButton("🟡 480p", callback_data=f"dl_{user_id}_480"),
        ]]
        keyboard = InlineKeyboardMarkup(buttons)

        dur_str = ""
        if duration:
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            dur_str = f"⏱ {hours}:{mins:02d}:{secs:02d}\n" if hours else f"⏱ {mins}:{secs:02d}\n"

        caption = (
            f"🎬 *{title[:100]}*\n"
            f"{f'👤 {uploader}' + chr(10) if uploader else ''}"
            f"{dur_str}"
            f"\nВыбери качество:"
        )

        await msg.delete()

        if thumbnail:
            try:
                await update.message.reply_photo(
                    photo=thumbnail, caption=caption,
                    parse_mode="Markdown", reply_markup=keyboard
                )
            except Exception:
                await update.message.reply_text(
                    caption, parse_mode="Markdown", reply_markup=keyboard
                )
        else:
            await update.message.reply_text(
                caption, parse_mode="Markdown", reply_markup=keyboard
            )

    except Exception as e:
        await msg.edit_text(f"❌ Не удалось получить информацию:\n{str(e)[:200]}")


async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    if len(parts) != 3:
        return

    user_id = int(parts[1])
    quality = int(parts[2])

    if user_id not in pending:
        await query.edit_message_caption("❌ Сессия устарела. Отправь ссылку заново.")
        return

    info = pending[user_id]
    url = info["url"]
    title = info["title"]

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    msg = await query.message.reply_text(f"⏳ Скачиваю {quality}p... Подожди, для больших видео это может занять время.")

    ydl_opts = {
        **get_ydl_opts_base(),
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        # Без лимита размера
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
                raise FileNotFoundError("Файл не найден после скачивания")

        file_size = os.path.getsize(filename)
        file_size_mb = file_size / (1024 * 1024)

        await msg.edit_text(f"📤 Отправляю {quality}p ({file_size_mb:.1f} MB)...")

        with open(filename, "rb") as video_file:
            if file_size <= 50 * 1024 * 1024:
                # До 50MB — отправляем как видео (с плеером)
                await query.message.reply_video(
                    video=video_file,
                    caption=f"🎬 {title[:200]}\n📺 {quality}p",
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60,
                )
            else:
                # Больше 50MB — отправляем как файл
                await query.message.reply_document(
                    document=video_file,
                    caption=f"🎬 {title[:200]}\n📺 {quality}p\n📦 {file_size_mb:.1f} MB",
                    read_timeout=600,
                    write_timeout=600,
                    connect_timeout=60,
                )

        await msg.delete()
        del pending[user_id]

    except Exception as e:
        error_msg = str(e)
        if "Timed out" in error_msg or "timed out" in error_msg.lower():
            await msg.edit_text("❌ Таймаут при отправке. Попробуй ещё раз.")
        elif "Private" in error_msg or "private" in error_msg:
            await msg.edit_text("❌ Видео приватное — скачать невозможно")
        elif "not supported" in error_msg.lower():
            await msg.edit_text("❌ Этот сайт или формат не поддерживается")
        else:
            await msg.edit_text(f"❌ Ошибка:\n{error_msg[:300]}")
    finally:
        # Всегда удаляем файл после отправки или ошибки
        cleanup_file(filename)


def main():
    cleanup_all_downloads()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sources", sources_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern=r"^dl_"))

    print("🤖 Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
