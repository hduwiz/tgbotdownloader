import os
import asyncio
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# =============================================
BOT_TOKEN = "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE"

ALLOWED_SOURCES = [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "rt.pornhub.com",
]
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Хранилище ожидающих загрузок {user_id: {url, title, thumbnail, formats}}
pending = {}


def is_allowed(url: str) -> bool:
    return any(source in url for source in ALLOWED_SOURCES)


def get_ydl_opts_base():
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 5,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sources_list = "\n".join(f"• {s}" for s in ALLOWED_SOURCES)
    await update.message.reply_text(
        f"👋 Привет! Карман меня заказал.\n\n"
        f"📋 Поддерживаю все виды ссылок для скачивания\n\n"
        f"📎 Просто отправь ссылку на видео — я его скачаю и пришлю тебе."
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

        # Определяем доступные качества
        formats = info.get("formats", [])
        available_heights = set()
        for f in formats:
            h = f.get("height")
            if h and f.get("vcodec") != "none":
                available_heights.add(h)

        # Фильтруем нужные качества
        wanted = [1080, 720, 480]
        available = [q for q in wanted if any(h >= q for h in available_heights)] if available_heights else wanted

        # Если нет информации о форматах — предлагаем все варианты
        if not available:
            available = wanted

        # Сохраняем в pending
        pending[user_id] = {
            "url": url,
            "title": title,
            "thumbnail": thumbnail,
        }

        # Кнопки выбора качества
        buttons = []
        quality_labels = {1080: "🔵 1080p HD", 720: "🟢 720p", 480: "🟡 480p"}
        for q in available:
            buttons.append(InlineKeyboardButton(
                quality_labels.get(q, f"{q}p"),
                callback_data=f"dl_{user_id}_{q}"
            ))

        keyboard = InlineKeyboardMarkup([buttons])

        # Формируем описание
        dur_str = ""
        if duration:
            mins, secs = divmod(int(duration), 60)
            dur_str = f"⏱ {mins}:{secs:02d}\n"

        caption = (
            f"🎬 *{title[:100]}*\n"
            f"{f'👤 {uploader}' if uploader else ''}\n"
            f"{dur_str}"
            f"\nВыбери качество:"
        )

        await msg.delete()

        # Отправляем превью с кнопками
        if thumbnail:
            try:
                await update.message.reply_photo(
                    photo=thumbnail,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except Exception:
                await update.message.reply_text(
                    caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
        else:
            await update.message.reply_text(
                caption,
                parse_mode="Markdown",
                reply_markup=keyboard
            )

    except Exception as e:
        await msg.edit_text(f"❌ Не удалось получить информацию:\n{str(e)[:200]}")


async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # dl_{user_id}_{quality}
    parts = data.split("_")
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

    # Убираем кнопки
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    msg = await query.message.reply_text(f"⏳ Скачиваю в {quality}p...")

    ydl_opts = {
        **get_ydl_opts_base(),
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "format": f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best",
        "merge_output_format": "mp4",
    }

    if "tiktok.com" in url:
        ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

    try:
        loop = asyncio.get_event_loop()

        def do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(dl_info)
                # Меняем расширение на mp4 если нужно
                base = os.path.splitext(filename)[0]
                if os.path.exists(base + ".mp4"):
                    filename = base + ".mp4"
                return filename

        filename = await loop.run_in_executor(None, do_download)

        # Ищем файл если не найден
        if not os.path.exists(filename):
            files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".mp4", ".webm", ".mkv"))]
            if files:
                filename = os.path.join(DOWNLOAD_DIR, sorted(files)[-1])
            else:
                raise FileNotFoundError("Файл не найден после скачивания")

        file_size = os.path.getsize(filename)
        if file_size > 50 * 1024 * 1024:
            os.remove(filename)
            await msg.edit_text("❌ Файл слишком большой (лимит Telegram — 50MB)\nПопробуй качество 480p.")
            return

        await msg.edit_text(f"📤 Отправляю {quality}p...")

        with open(filename, "rb") as video_file:
            await query.message.reply_video(
                video=video_file,
                caption=f"🎬 {title[:200]}\n📺 {quality}p",
                supports_streaming=True,
                read_timeout=180,
                write_timeout=180,
            )

        os.remove(filename)
        await msg.delete()
        del pending[user_id]

    except Exception as e:
        error_msg = str(e)
        if "Timed out" in error_msg or "timed out" in error_msg.lower():
            await msg.edit_text("❌ Таймаут. Попробуй ещё раз или выбери качество пониже.")
        elif "File is too large" in error_msg:
            await msg.edit_text("❌ Файл слишком большой (лимит Telegram — 50MB)")
        elif "Private" in error_msg or "private" in error_msg:
            await msg.edit_text("❌ Видео приватное — скачать невозможно")
        else:
            await msg.edit_text(f"❌ Ошибка:\n{error_msg[:300]}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sources", sources_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern=r"^dl_"))

    print("🤖 Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
