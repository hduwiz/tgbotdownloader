import os
import asyncio
import glob
import logging
import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")
LOCAL_API = os.environ.get("LOCAL_API_URL", "http://telegram-bot-api:8081")
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

def is_allowed(url: str) -> bool:
    return any(s in url for s in ALLOWED_SOURCES)

def cleanup_file(path: str):
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
        "socket_timeout": 30,
        "retries": 10,
        "concurrent_fragment_downloads": 15,
        "buffersize": 1024 * 1024, # 1MB буфер
        "noprogress": True,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    }

async def fetch_info(url: str) -> dict:
    opts = {**get_ydl_opts(), "skip_download": True}
    if "tiktok.com" in url:
        opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))

async def download_video(url: str, quality: int) -> str:
    # 0 = Оригинальное качество
    if quality == 0:
        format_str = "bestvideo+bestaudio/best"
    else:
        format_str = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"

    opts = {
        **get_ydl_opts(),
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "format": format_str,
        "merge_output_format": "mp4",
    }
    
    if "tiktok.com" in url:
        opts["extractor_args"] = {"tiktok": {"api_hostname": "api22-normal-c-useast2a.tiktokv.com"}}

    loop = asyncio.get_event_loop()

    def do_download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(info)
            base = os.path.splitext(fname)[0]
            for ext in [".mp4", ".webm", ".mkv"]:
                if os.path.exists(base + ext):
                    return base + ext
            return fname

    return await loop.run_in_executor(None, do_download)

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я скачаю видео в оригинальном качестве.\n\n"
        "📎 Отправь ссылку — поддержка файлов до 2GB активна!"
    )

@dp.message(F.text)
async def handle_url(message: Message):
    url = message.text.strip()
    user_id = message.from_user.id

    if not url.startswith("http"):
        return

    if not is_allowed(url):
        await message.answer("❌ Источник не поддерживается.")
        return

    msg = await message.answer("🔍 Получаю информацию...")

    try:
        info = await fetch_info(url)
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
        available = [q for q in wanted if any(h >= q for h in heights)]

        pending[user_id] = {"url": url, "title": title}

        dur_str = ""
        if duration:
            mins, secs = divmod(int(duration), 60)
            hours, mins = divmod(mins, 60)
            dur_str = f"\n⏱ {hours}:{mins:02d}:{secs:02d}" if hours else f"\n⏱ {mins}:{secs:02d}"

        labels = {1080: "🔵 1080p", 720: "🟢 720p", 480: "🟡 480p", 360: "🔴 360p"}
        kb = InlineKeyboardBuilder()
        
        # Кнопка для оригинала
        kb.button(text="🔥 Original (Best)", callback_data=f"dl_{user_id}_0")
        
        for q in available:
            kb.button(text=labels.get(q, f"{q}p"), callback_data=f"dl_{user_id}_{q}")
        kb.adjust(1, len(available))

        caption = (
            f"🎬 <b>{title[:100]}</b>\n"
            f"{'👤 ' + uploader + chr(10) if uploader else ''}"
            f"{dur_str}\n\nВыбери качество:"
        )

        await msg.delete()
        if thumbnail:
            try:
                await message.answer_photo(photo=thumbnail, caption=caption, reply_markup=kb.as_markup())
            except Exception:
                await message.answer(caption, reply_markup=kb.as_markup())
        else:
            await message.answer(caption, reply_markup=kb.as_markup())

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

@dp.callback_query(F.data.startswith("dl_"))
async def handle_quality(callback: CallbackQuery, bot: Bot):
    _, user_id_str, quality_str = callback.data.split("_")
    user_id = int(user_id_str)
    quality = int(quality_str)

    if callback.from_user.id != user_id:
        await callback.answer("Это не твой запрос!", show_alert=True)
        return

    if user_id not in pending:
        await callback.answer("Сессия устарела", show_alert=True)
        return

    await callback.answer()
    
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass

    info = pending[user_id]
    url, title = info["url"], info["title"]
    q_text = "Original" if quality == 0 else f"{quality}p"

    msg = await callback.message.answer(f"⏳ Скачиваю {q_text}...")

    filename = None
    try:
        filename = await download_video(url, quality)
        size_mb = os.path.getsize(filename) / (1024 * 1024)
        
        await msg.edit_text(f"📤 Отправляю {q_text} ({size_mb:.1f} MB)...")

        # Отправка видео с огромным таймаутом
        await bot.send_video(
            chat_id=callback.message.chat.id,
            video=FSInputFile(filename),
            caption=f"🎬 {title[:200]}\n📺 {q_text}  |  📦 {size_mb:.1f} MB",
            supports_streaming=True,
            request_timeout=3600 
        )
        await msg.delete()
        pending.pop(user_id, None)

    except Exception as e:
        logger.error(f"Ошибка при загрузке: {e}")
        await msg.edit_text(f"❌ Ошибка:\n{str(e)[:300]}")
    finally:
        cleanup_file(filename)

async def main():
    cleanup_all()
    
    # ПРАВИЛЬНО: Таймаут задается здесь, в сессии
    session = AiohttpSession(
        timeout=3600 
    )
    
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        base_url=f"{LOCAL_API}/",
        default=DefaultBotProperties(
            parse_mode="HTML"
        ),
    )

    logger.info("🤖 Бот запущен с локальным API!")
    
    # polling_timeout — это частота опроса серверов Telegram
    await dp.start_polling(
        bot, 
        allowed_updates=dp.resolve_used_update_types(),
        polling_timeout=30
    )

if __name__ == "__main__":
    asyncio.run(main())
