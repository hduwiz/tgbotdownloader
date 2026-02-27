import os
import asyncio
import glob
import aiohttp
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# =============================================
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")

ALLOWED_SOURCES = [
    "youtube.com", "youtu.be", "vimeo.com",
    "twitter.com", "x.com", "instagram.com",
    "tiktok.com", "pornhub.com", "xvideos.com",
    "xhamster.com", "xnxx.com",
]
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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


async def upload_to_gofile(filepath: str) -> str:
    """Загружает файл на gofile.io и возвращает ссылку"""
    async with aiohttp.ClientSession() as session:
        # Получаем лучший сервер
        async with session.get("https://api.gofile.io/servers") as r:
            data = await r.json()
            server = data["data"]["servers"][0]["name"]

        # Загружаем файл
        with open(filepath, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("file", f, filename=os.path.basename(filepath))

            async with session.post(f"https://upload.gofile.io/uploadFile", data=form) as r:
                result = await r.json()

        if result["status"] == "ok":
            return result["data"]["downloadPage"]
        else:
            raise Exception(f"Gofile error: {result}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Карман меня заказал.\n\n"
        "📎 Отправь ссылку на видео — скачаю и пришлю ссылку для скачивания.\n"
        "⚡ Без лимитов на размер!"
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not url.startswith("http"):
        return

    if not is_allowed(url):
        await update.message.reply_text("❌ Источник не поддерживается.")
        return

    msg = await update.message.reply_text("🔍 Получаю информацию...")

    ydl_opts = {**get_ydl_opts(), "skip_download": True}
    if "tiktok.com" in url:
        ydl_opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

    try:
        loop = asyncio.get_event_loop()

        def fetch():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        info = await loop.run_in_executor(None, fetch)

        title = info.get("title") or "Видео"
        thumbnail = info.get("thumbnail")
        duration = info.get("duration")
        uploader = info.get("uploader") or info.get("channel") or ""

        heights = set()
        for f in info.get("formats", []):
            h = f.get("height")
            if h and f.get("vcodec") != "none":
                heights.add(h)

        wanted = [1080, 720, 480, 360]
        available = [q for q in wanted if any(h >= q for h in heights)] or [720, 480]

        pending[user_id] = {"url": url, "title": title}

        dur_str = ""
        if duration:
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            dur_str = f"\n⏱ {hours}:{mins:02d}:{secs:02d}" if hours else f"\n⏱ {mins}:{secs:02d}"

        buttons = [[InlineKeyboardButton(
            {1080: "🔵 1080p", 720: "🟢 720p", 480: "🟡 480p", 360: "🔴 360p"}.get(q, f"{q}p"),
            callback_data=f"dl_{user_id}_{q}"
        ) for q in available]]

        caption = (
            f"🎬 *{title[:100]}*\n"
            f"{'👤 ' + uploader + chr(10) if uploader else ''}"
            f"{dur_str}\n\nВыбери качество:"
        )

        await msg.delete()

        if thumbnail:
            try:
                await update.message.reply_photo(
                    photo=thumbnail, caption=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            except Exception:
                await update.message.reply_text(
                    caption, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
        else:
            await update.message.reply_text(
                caption, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")


async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, user_id_str, quality_str = query.data.split("_")
    user_id = int(user_id_str)
    quality = int(quality_str)

    if query.from_user.id != user_id:
        return

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

    msg = await query.message.reply_text(f"⏳ Скачиваю {quality}p...")

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
            import subprocess as sp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                fname = ydl.prepare_filename(dl_info)
                base = os.path.splitext(fname)[0]
                # Ищем скачанный файл
                for ext in [".mp4", ".webm", ".mkv", ".avi", ".mov"]:
                    if os.path.exists(base + ext):
                        if ext != ".mp4":
                            # Конвертируем в mp4
                            out = base + ".mp4"
                            sp.run(["ffmpeg", "-i", base + ext, "-c:v", "libx264", "-c:a", "aac", "-y", out], capture_output=True)
                            if os.path.exists(out):
                                os.remove(base + ext)
                                return out
                        return base + ext
                return fname

        filename = await loop.run_in_executor(None, do_download)

        if not os.path.exists(filename):
            files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".mp4", ".webm", ".mkv"))]
            if files:
                filename = os.path.join(DOWNLOAD_DIR, sorted(
                    files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))[-1])
            else:
                raise FileNotFoundError("Файл не найден")

        size_mb = os.path.getsize(filename) / (1024 * 1024)
        await msg.edit_text(f"☁️ Загружаю на сервер ({size_mb:.1f} MB)...")

        # Загружаем на gofile.io
        download_url = await upload_to_gofile(filename)

        await msg.edit_text(
            f"✅ Готово!\n\n"
            f"🎬 {title[:150]}\n"
            f"📺 {quality}p  |  📦 {size_mb:.1f} MB\n\n"
            f"🔗 {download_url}\n\n"
            f"⏳ Ссылка активна 10 дней"
        )

        if user_id in pending:
            del pending[user_id]

    except Exception as e:
        err = str(e)
        await msg.edit_text(f"❌ Ошибка:\n{err[:300]}")
    finally:
        cleanup_file(filename)


def main():
    cleanup_all()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern=r"^dl_"))
    print("🤖 Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
