import os
import asyncio
import glob
import subprocess
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

MAX_SIZE = 44 * 1024 * 1024  # 44MB — с хорошим запасом

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


def get_duration(filepath):
    try:
        r = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ], capture_output=True, text=True)
        return float(r.stdout.strip())
    except Exception:
        return 0


def split_video(filepath, max_bytes):
    """Режет видео на части гарантированно меньше max_bytes"""
    if os.path.getsize(filepath) <= max_bytes:
        return [filepath]

    duration = get_duration(filepath)
    if duration <= 0:
        return [filepath]

    file_size = os.path.getsize(filepath)
    # Считаем длительность части с запасом 80%
    ratio = (max_bytes / file_size) * 0.80
    part_duration = duration * ratio

    parts = []
    base = os.path.splitext(filepath)[0]
    current = 0.0
    part_num = 1

    while current < duration - 1:
        part_path = f"{base}_part{part_num}.mp4"

        subprocess.run([
            "ffmpeg", "-ss", str(current),
            "-i", filepath,
            "-t", str(part_duration),
            "-c:v", "libx264", "-c:a", "aac",
            "-avoid_negative_ts", "1",
            "-movflags", "+faststart",
            "-y", part_path
        ], capture_output=True)

        if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
            actual_size = os.path.getsize(part_path)
            # Если часть всё равно большая — уменьшаем следующие
            if actual_size > max_bytes:
                part_duration *= 0.75
                cleanup_file(part_path)
                continue
            parts.append(part_path)

        current += part_duration
        part_num += 1

        if part_num > 99:
            break

    return parts if parts else [filepath]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Карман меня заказал.\n\n"
        "📎 Отправь ссылку на видео — скачаю и пришлю.\n"
        "Большие видео автоматически разбиваются на части."
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
    part_files = []

    try:
        loop = asyncio.get_event_loop()

        def do_download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                fname = ydl.prepare_filename(dl_info)
                base = os.path.splitext(fname)[0]
                return base + ".mp4" if os.path.exists(base + ".mp4") else fname

        filename = await loop.run_in_executor(None, do_download)

        if not os.path.exists(filename):
            files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".mp4", ".webm", ".mkv"))]
            if files:
                filename = os.path.join(DOWNLOAD_DIR, sorted(
                    files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))[-1])
            else:
                raise FileNotFoundError("Файл не найден")

        size = os.path.getsize(filename)
        size_mb = size / (1024 * 1024)

        if size > MAX_SIZE:
            est = int(size / MAX_SIZE) + 1
            await msg.edit_text(f"✂️ Видео {size_mb:.0f} MB — режу на ~{est} части...")
            part_files = await loop.run_in_executor(None, split_video, filename, MAX_SIZE)
        else:
            part_files = [filename]

        total = len(part_files)
        await msg.edit_text(f"📤 Отправляю {'1 файл' if total == 1 else f'{total} частей'}...")

        for i, part in enumerate(part_files, 1):
            if not os.path.exists(part):
                continue

            part_mb = os.path.getsize(part) / (1024 * 1024)

            if total == 1:
                cap = f"🎬 {title[:180]}\n📺 {quality}p  |  📦 {part_mb:.1f} MB"
            else:
                cap = f"🎬 {title[:140]}\n📺 {quality}p  |  📦 Часть {i}/{total}  ({part_mb:.1f} MB)"

            with open(part, "rb") as f:
                await query.message.reply_video(
                    video=f,
                    caption=cap,
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60,
                )

        await msg.delete()
        if user_id in pending:
            del pending[user_id]

    except Exception as e:
        err = str(e)
        if "413" in err or "Request Entity Too Large" in err:
            await msg.edit_text("❌ Часть всё равно большая. Попробуй 480p или 360p.")
        elif "Timed out" in err:
            await msg.edit_text("❌ Таймаут. Попробуй ещё раз.")
        else:
            await msg.edit_text(f"❌ Ошибка:\n{err[:300]}")
    finally:
        cleanup_file(filename)
        for p in part_files:
            if p != filename:
                cleanup_file(p)


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
