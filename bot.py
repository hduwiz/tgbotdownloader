import os
import asyncio
import glob
import logging
import subprocess
import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
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

# Замок для очереди скачивания
download_lock = asyncio.Lock()

ALLOWED_SOURCES = ["youtube.com", "youtu.be", "vimeo.com", "twitter.com", "x.com", "instagram.com", "tiktok.com", "pornhub.com", "xvideos.com", "xhamster.com", "xnxx.com"]

pending = {}

def cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception: pass

def cleanup_all():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        cleanup_file(f)

def get_ydl_opts():
    return {
        "quiet": True, "no_warnings": True, "socket_timeout": 30, "retries": 15, "noprogress": True,
        "concurrent_fragment_downloads": 20, "buffersize": 1024 * 512, "http_chunk_size": 5242880,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"},
    }

def split_video_by_time(input_file: str, segment_seconds: int = 30) -> list[str]:
    if not os.path.exists(input_file): return []
    base_name = os.path.splitext(input_file)[0]
    output_pattern = f"{base_name}_part%03d.mp4"
    cmd = ['ffmpeg', '-i', input_file, '-c', 'copy', '-map', '0', '-segment_time', str(segment_seconds), '-f', 'segment', '-reset_timestamps', '1', output_pattern]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        return sorted(glob.glob(f"{base_name}_part*.mp4"))
    except Exception: return [input_file]

async def fetch_info(url: str) -> dict:
    opts = {**get_ydl_opts(), "skip_download": True}
    return await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))

async def download_video(url: str, quality: int) -> str:
    opts = {**get_ydl_opts(), "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s", "format": f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best", "merge_output_format": "mp4"}
    def do_download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    return await asyncio.get_event_loop().run_in_executor(None, do_download)

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Работаем друзья. Пришли ссылку, я скачаю и нарежу по 30 сек.")

@dp.message(F.text)
async def handle_url(message: Message):
    url = message.text.strip()
    if not url.startswith("http"): return
    msg = await message.answer("🔍 Анализ...")
    try:
        info = await fetch_info(url)
        user_id = message.from_user.id
        pending[user_id] = {"url": url, "title": info.get("title", "video")}
        kb = InlineKeyboardBuilder()
        kb.button(text="🟢 720p", callback_data=f"dl_{user_id}_720")
        kb.button(text="🟡 480p", callback_data=f"dl_{user_id}_480")
        kb.adjust(1)
        await msg.edit_text(f"🎬 <b>{info.get('title')[:100]}</b>\n\nВыбери качество:", reply_markup=kb.as_markup())
    except Exception as e: await msg.edit_text(f"❌ Ошибка: {str(e)[:50]}")

@dp.callback_query(F.data.startswith("dl_"))
async def handle_dl(callback: CallbackQuery, bot: Bot):
    _, uid_str, qual_str = callback.data.split("_")
    uid, qual = int(uid_str), int(qual_str)
    if callback.from_user.id != uid or uid not in pending: return

    # Проверка очереди
    if download_lock.locked():
        await callback.answer("⏳ Бот занят. Вы добавлены в очередь!", show_alert=True)

    async with download_lock:
        data = pending.pop(uid)
        status = await callback.message.edit_text(f"⚡️ Ваша очередь! Качаю {qual}p...")
        raw_file = None
        try:
            raw_file = await download_video(data['url'], qual)
            await status.edit_text("✂️ Нарезка по 30 секунд...")
            parts = await asyncio.get_event_loop().run_in_executor(None, lambda: split_video_by_time(raw_file, 30))
            for i, part in enumerate(parts):
                await bot.send_video(chat_id=callback.message.chat.id, video=FSInputFile(part), 
                                     caption=f"🎬 Часть {i+1}/{len(parts)}", request_timeout=600)
                cleanup_file(part)
            await status.delete()
        except Exception: await callback.message.answer("❌ Ошибка обработки.")
        finally: cleanup_file(raw_file)

async def main():
    cleanup_all()
    session = AiohttpSession(timeout=3600)
    bot = Bot(token=BOT_TOKEN, session=session, base_url=f"{LOCAL_API}/", default=DefaultBotProperties(parse_mode="HTML"))
    
    # 1. СБРОС КОНФЛИКТА
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("🤖 Бот запущен (CLEAN START)")
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
