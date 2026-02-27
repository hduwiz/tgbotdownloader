import os
import asyncio
import glob
import logging
import subprocess
import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")
LOCAL_API = os.environ.get("LOCAL_API_URL", "http://telegram-bot-api:8081")
DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Замок для очереди (чтобы Railway не падал от нагрузки)
download_lock = asyncio.Lock()
pending = {}

def cleanup(path: str):
    if path and os.path.exists(path):
        try: os.remove(path)
        except: pass

def get_ydl_opts():
    return {
        "quiet": True, "no_warnings": True, "socket_timeout": 30, "retries": 10,
        "concurrent_fragment_downloads": 20, "buffersize": 1024 * 512,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"},
    }

def split_video(input_file: str):
    """Нарезка по 30 секунд"""
    base = os.path.splitext(input_file)[0]
    output = f"{base}_part%03d.mp4"
    cmd = ['ffmpeg', '-i', input_file, '-c', 'copy', '-map', '0', '-segment_time', '30', '-f', 'segment', '-reset_timestamps', '1', output]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        return sorted(glob.glob(f"{base}_part*.mp4"))
    except: return [input_file]

dp = Dispatcher()

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("🚀 Пришли ссылку — скачаю и нарежу по 30 сек.")

@dp.message(F.text.startswith("http"))
async def handle_url(m: Message):
    url = m.text.strip()
    msg = await m.answer("🔍 Анализ...")
    try:
        opts = {**get_ydl_opts(), "skip_download": True}
        info = await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))
        pending[m.from_user.id] = {"url": url, "title": info.get("title", "video")}
        kb = InlineKeyboardBuilder()
        kb.button(text="🟢 720p", callback_data=f"dl_{m.from_user.id}_720")
        kb.button(text="🟡 480p", callback_data=f"dl_{m.from_user.id}_480")
        await msg.edit_text(f"🎬 {info.get('title')[:100]}\nКачество:", reply_markup=kb.as_markup())
    except Exception as e: await msg.edit_text(f"❌ Ошибка: {str(e)[:50]}")

@dp.callback_query(F.data.startswith("dl_"))
async def download(c: CallbackQuery, bot: Bot):
    _, uid, qual = c.data.split("_")
    if c.from_user.id != int(uid): return
    
    if download_lock.locked():
        await c.answer("⏳ Очередь занята, подождите...", show_alert=True)

    async with download_lock:
        data = pending.pop(int(uid), None)
        if not data: return
        status = await c.message.edit_text(f"⚡️ Качаю {qual}p...")
        
        path = f"{DOWNLOAD_DIR}/{c.from_user.id}.mp4"
        opts = {**get_ydl_opts(), "outtmpl": path, "format": f"bestvideo[height<={qual}]+bestaudio/best"}
        
        try:
            await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([data['url']]))
            await status.edit_text("✂️ Нарезка по 30 сек...")
            parts = await asyncio.get_event_loop().run_in_executor(None, split_video, path)
            
            for part in parts:
                await bot.send_video(chat_id=c.message.chat.id, video=FSInputFile(part), request_timeout=600)
                cleanup(part)
            await status.delete()
        except: await c.message.answer("❌ Ошибка")
        finally: cleanup(path)

async def main():
    # Очистка старых файлов перед стартом
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"): cleanup(f)
    
    session = AiohttpSession(timeout=3600)
    bot = Bot(token=BOT_TOKEN, session=session, base_url=f"{LOCAL_API}/", default=DefaultBotProperties(parse_mode="HTML"))
    
    # --- ФИКС CONFLICT ERROR ---
    # 1. Удаляем все старые вебхуки
    # 2. drop_pending_updates=True — удаляет сообщения, присланные пока бот был оффлайн (чтобы не спамил при старте)
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("🤖 Бот запущен БЕЗ КОНФЛИКТОВ")
    
    # Запуск
    await dp.start_polling(bot, polling_timeout=20)

if __name__ == "__main__":
    asyncio.run(main())
