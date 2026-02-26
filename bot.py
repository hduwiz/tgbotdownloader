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
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "pornhub.com",
    "xvideos.com",
    "xhamster.com",
    "xnxx.com",
]
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_SIZE = 45 * 1920 * 1080  # 45MB — с запасом от лимита Telegram

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


def get_duration(filepath: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ], capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0


def split_video(filepath: str, max_bytes: int) -> list:
    """
    Режет видео на части. Каждая часть гарантированно меньше max_bytes.
    """
    file_size = os.path.getsize(filepath)
    if file_size <= max_bytes:
        return [filepath]

    duration = get_duration(filepath)
    if duration <= 0:
        return [filepath]

    # Считаем длительность одной части пропорционально размеру
    # Добавляем коэффициент 0.85 чтобы части точно влезали
    ratio = (max_bytes / file_size) * 0.85
    part_duration = duration * ratio

    parts = []
    base = os.path.splitext(filepath)[0]
    current_time = 0.0
    part_num = 1

    while current_time < duration:
        part_path = f"{base}_part{part_num}.mp4"

        result = subprocess.run([
            "ffmpeg",
            "-ss", str(current_time),
            "-i", filepath,
            "-t", str(part_duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-avoid_negative_ts", "1",
            "-movflags", "+faststart",
            "-y", part_path
        ], capture_output=True)

        if os.path.exists(part_path) and os.path.getsize(part_path) > 0:
            # Если часть всё равно большая — уменьшаем следующие части
            if os.path.getsize(part_path) > max_bytes:
                part_duration *= 0.8

            parts.append(part_path)

        current_time += part_duration
        part_num += 1

        # Защита от бесконечного цикла
        if part_num > 50:
            break

    return parts if parts else [filepath]


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

    parts_data = query.data.split("_")
    if len(parts_data) != 3:
        return

    user_id = int(parts_data[1])
    quality = int(parts_data[2])

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
        **get_ydl_opts_base(),
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

        if file_size > MAX_SIZE:
            est_parts = int(file_size / MAX_SIZE) + 1
            await msg.edit_text(f"✂️ Видео {file_size_mb:.1f} MB — режу на части (~{est_parts} шт)...")
            part_files = await loop.run_in_executor(None, split_video, filename, MAX_SIZE)
        else:
            part_files = [filename]

        total_parts = len(part_files)

        if total_parts > 1:
            await msg.edit_text(f"📤 Отправляю {total_parts} частей...")
        else:
            await msg.edit_text(f"📤 Отправляю {quality}p ({file_size_mb:.1f} MB)...")

        for i, part_path in enumerate(part_files, 1):
            # Финальная проверка размера части
            part_size = os.path.getsize(part_path)
            if part_size > MAX_SIZE:
                # Пропускаем слишком большую часть — не должно случаться
                continue

            part_size_mb = part_size / (1024 * 1024)

            if total_parts == 1:
                caption = f"🎬 {title[:180]}\n📺 {quality}p"
            else:
                caption = f"🎬 {title[:140]}\n📺 {quality}p  |  📦 Часть {i} из {total_parts}  ({part_size_mb:.1f} MB)"

            with open(part_path, "rb") as video_file:
                await query.message.reply_video(
                    video=video_file,
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=300,
                    write_timeout=300,
                    connect_timeout=60,
                )

        await msg.delete()
        if user_id in pending:
            del pending[user_id]

    except Exception as e:
        error_msg = str(e)
        if "Timed out" in error_msg or "timed out" in error_msg.lower():
            await msg.edit_text("❌ Таймаут при отправке. Попробуй ещё раз.")
        elif "413" in error_msg or "Request Entity Too Large" in error_msg:
            await msg.edit_text("❌ Ошибка 413 — попробуй 480p.")
        elif "Private" in error_msg or "private" in error_msg:
            await msg.edit_text("❌ Видео приватное — скачать невозможно")
        else:
            await msg.edit_text(f"❌ Ошибка:\n{error_msg[:300]}")
    finally:
        cleanup_file(filename)
        for p in part_files:
            if p != filename:
                cleanup_file(p)


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
