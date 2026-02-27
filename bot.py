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
# ТОКЕН И URL API
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

def cleanup_file(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def cleanup_all():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        cleanup_file(f)

def get_ydl_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 15,
        "noprogress": True,
        "concurrent_fragment_downloads": 30, # Скорость для Railway
        "buffersize": 1024 * 1024,
        "http_chunk_size": 5242880,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        },
    }

def split_video_by_time(input_file: str, segment_seconds: int = 30) -> list[str]:
    """Нарезка видео по 30 секунд без перекодирования"""
    if not os.path.exists(input_file):
        return []

    base_name = os.path.splitext(input_file)[0]
    output_pattern = f"{base_name}_part%03d.mp4"

    cmd = [
        'ffmpeg', '-i', input_file,
        '-c', 'copy',
        '-map', '0',
        '-segment_time', str(segment_seconds),
        '-f', 'segment',
        '-reset_timestamps', '1',
        output_pattern
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        parts = sorted(glob.glob(f"{base_name}_part*.mp4"))
        return parts
    except Exception as e:
        logger.error(f"Ошибка нарезки: {e}")
        return [input_file]

async def fetch_info(url: str) -> dict:
    opts = {**get_ydl_opts(), "skip_download": True}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))

async def download_video(url: str, quality: int) -> str:
    format_str = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]/best"
    opts = {
        **get_ydl_opts(),
        "outtmpl": f"{DOWNLOAD_DIR}/%(id)s.%(ext)s",
        "format": format_str,
        "merge_output_format": "mp4",
    }
    loop = asyncio.get_event_loop()
    def do_download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    return await loop.run_in_executor(None, do_download)

dp = Dispatcher()

# --- КОМАНДЫ БОТА ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🚀 <b>РАБОТАЕМ ДРУЗЬЯ</b>\n\n"
        "Я скачиваю видео в 720p/480p и режу их по 30 секунд для удобства.\n\n"
        "📎 Просто пришли мне ссылку на видео.\n"
    )

@dp.message(Command("support"))
async def cmd_support(message: Message):
    text = (
        "💎 <b>Поддержать проект</b>\n\n"
        "Бот работает на платных серверах Railway. Если он тебе полезен, "
        "можешь закинуть копеечку на его развитие и оплату ресурсов. "
        "Буду очень благодарен! 🙏\n\n"
        "💳 <b>МОНОБАНКА:</b> https://send.monobank.ua/jar/4xgRXxMGSF\n"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="👨‍💻 Связаться с автором", url="https://t.me/твой_ник")
    
    await message.answer(text, reply_markup=kb.as_markup())

# --- ОБРАБОТКА ССЫЛОК ---

@dp.message(F.text)
async def handle_url(message: Message):
    url = message.text.strip()
    if not url.startswith("http"): return
    
    msg = await message.answer("🔍 Анализирую ссылку...")
    try:
        info = await fetch_info(url)
        user_id = message.from_user.id
        pending[user_id] = {"url": url, "title": info.get("title", "video")}

        kb = InlineKeyboardBuilder()
        kb.button(text="🟢 720p (HD)", callback_data=f"dl_{user_id}_720")
        kb.button(text="🟡 480p (SD)", callback_data=f"dl_{user_id}_480")
        kb.adjust(1)

        await msg.edit_text(
            f"🎬 <b>{info.get('title')[:100]}</b>\n\nВыбери качество:",
            reply_markup=kb.as_markup()
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:100]}")

@dp.callback_query(F.data.startswith("dl_"))
async def handle_dl(callback: CallbackQuery, bot: Bot):
    _, uid_str, qual_str = callback.data.split("_")
    uid, qual = int(uid_str), int(qual_str)
    
    if callback.from_user.id != uid or uid not in pending: return
    
    data = pending.pop(uid)
    await callback.message.edit_text(f"⚡️ Начинаю загрузку ({qual}p)...")

    raw_file = None
    try:
        # 1. Загрузка
        raw_file = await download_video(data['url'], qual)
        
        # 2. Нарезка
        await callback.message.edit_text("✂️ Режу видео по 30 секунд...")
        parts = await asyncio.get_event_loop().run_in_executor(None, lambda: split_video_by_time(raw_file, 30))
        
        # 3. Отправка
        for i, part in enumerate(parts):
            caption = f"🎬 Часть {i+1}/{len(parts)} | {qual}p"
            await bot.send_video(
                chat_id=callback.message.chat.id,
                video=FSInputFile(part),
                caption=caption,
                supports_streaming=True,
                request_timeout=600
            )
            cleanup_file(part)

        await callback.message.delete()
        cleanup_file(raw_file)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback.message.answer("❌ Не удалось обработать видео.")
        if raw_file: cleanup_file(raw_file)

async def main():
    cleanup_all()
    session = AiohttpSession(timeout=3600)
    bot = Bot(
        token=BOT_TOKEN, 
        session=session, 
        base_url=f"{LOCAL_API}/", 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    logger.info("🤖 Бот запущен (720/480 + 30s split + Support)")
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
