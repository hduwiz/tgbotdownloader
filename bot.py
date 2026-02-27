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

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")
LOCAL_API = os.environ.get("LOCAL_API_URL", "http://telegram-bot-api:8081")
# =============================================

DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Очередь и хранилище
download_lock = asyncio.Lock()
pending = {}

def cleanup(path: str):
    """Удаление файла с диска"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            logger.error(f"Ошибка удаления {path}: {e}")

def get_ydl_opts():
    """Настройки yt-dlp для Railway (без aria2)"""
    return {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 10,
        "noprogress": True,
        "concurrent_fragment_downloads": 20,
        "buffersize": 1024 * 512,
        "http_chunk_size": 5242880,
        "geo_bypass": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        },
    }

def split_video_by_time(input_file: str, segment_seconds: int = 30) -> list[str]:
    """Быстрая нарезка видео по 30 секунд без перекодирования"""
    if not os.path.exists(input_file):
        return []

    base_name = os.path.splitext(input_file)[0]
    output_pattern = f"{base_name}_part%03d.mp4"

    cmd = [
        'ffmpeg', '-i', input_file,
        '-c', 'copy', # Копируем потоки (0% нагрузки на CPU)
        '-map', '0',
        '-segment_time', str(segment_seconds),
        '-f', 'segment',
        '-reset_timestamps', '1',
        output_pattern
    ]
    
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        return sorted(glob.glob(f"{base_name}_part*.mp4"))
    except Exception as e:
        logger.error(f"Ошибка FFmpeg: {e}")
        return [input_file]

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("🚀 <b>Бот готов к работе!</b>\n\nПришли мне ссылку, я скачаю видео и нарежу его по 30 секунд.", parse_mode="HTML")

@dp.message(F.text.startswith("http"))
async def handle_url(message: Message):
    url = message.text.strip()
    msg = await message.answer("🔍 Анализирую видео...")
    
    try:
        opts = {**get_ydl_opts(), "skip_download": True}
        info = await asyncio.get_event_loop().run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False)
        )
        
        user_id = message.from_user.id
        pending[user_id] = {"url": url, "title": info.get("title", "video")}

        kb = InlineKeyboardBuilder()
        kb.button(text="🟢 720p (HD)", callback_data=f"dl_{user_id}_720")
        kb.button(text="🟡 480p (SD)", callback_data=f"dl_{user_id}_480")
        kb.adjust(1)

        await msg.edit_text(
            f"🎬 <b>{info.get('title')[:100]}</b>\n\nВыбери качество:",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:100]}")

@dp.callback_query(F.data.startswith("dl_"))
async def handle_dl(callback: CallbackQuery, bot: Bot):
    _, uid_str, qual_str = callback.data.split("_")
    uid, qual = int(uid_str), int(qual_str)
    
    if callback.from_user.id != uid or uid not in pending:
        return

    # Проверка очереди
    if download_lock.locked():
        await callback.answer("⏳ Бот занят. Вы поставлены в очередь!", show_alert=True)

    async with download_lock:
        data = pending.pop(uid)
        status_msg = await callback.message.edit_text(f"🚀 Начинаю загрузку ({qual}p)...")
        
        raw_path = f"{DOWNLOAD_DIR}/{uid}_{qual}.mp4"
        ydl_opts = {
            **get_ydl_opts(),
            "outtmpl": raw_path,
            "format": f"bestvideo[height<={qual}][ext=mp4]+bestaudio[ext=m4a]/best[height<={qual}]/best",
            "merge_output_format": "mp4",
        }

        try:
            # 1. Скачивание
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([data['url']])
            )
            
            # 2. Нарезка
            await status_msg.edit_text("✂️ Нарезаю видео по 30 секунд...")
            parts = await asyncio.get_event_loop().run_in_executor(
                None, lambda: split_video_by_time(raw_path, 30)
            )
            
            # 3. Отправка частей с подписями
            for i, part in enumerate(parts):
                size_mb = os.path.getsize(part) / (1024 * 1024)
                caption = (
                    f"🎬 <b>{data['title'][:100]}</b>\n"
                    f"📦 Часть {i+1}/{len(parts)} | {qual}p | {size_mb:.1f} MB"
                )
                
                await bot.send_video(
                    chat_id=callback.message.chat.id,
                    video=FSInputFile(part),
                    caption=caption,
                    supports_streaming=True,
                    parse_mode="HTML",
                    request_timeout=600
                )
                cleanup(part)

            await status_msg.delete()
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            await callback.message.answer("❌ Ошибка при обработке видео.")
        finally:
            cleanup(raw_path)

async def main():
    # Полная очистка перед стартом
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"):
        cleanup(f)
    
    session = AiohttpSession(timeout=3600)
    bot = Bot(
        token=BOT_TOKEN, 
        session=session, 
        base_url=f"{LOCAL_API}/", 
        default=DefaultBotProperties(parse_mode="HTML")
    )
    
    # ПРИНУДИТЕЛЬНОЕ УДАЛЕНИЕ ВЕБХУКА (Лечит Conflict Error)
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("🤖 Бот запущен (Clean Mode)")
    await dp.start_polling(bot, polling_timeout=30)

if __name__ == "__main__":
    asyncio.run(main())
