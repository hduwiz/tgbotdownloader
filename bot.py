import os
import asyncio
import glob
import logging
import subprocess
import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
BOT_TOKEN = os.environ.get("8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE", "8715702797:AAGQFyhgNGlzbFsH1SgDIqJ2tF6rbj9CwXE")
DOWNLOAD_DIR = "./downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

download_lock = asyncio.Lock()
pending = {}
active_tasks = {} # Флаги отмены {user_id: bool}
# =============================================

def cleanup(path: str):
    if path and os.path.exists(path):
        try: os.remove(path)
        except: pass

def get_ydl_opts():
    return {
        "quiet": True, 
        "no_warnings": True, 
        "cookiefile": "cookies.txt", 
        "concurrent_fragment_downloads": 20, 
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        },
    }

def split_video_by_time(input_file: str, segment_seconds: int) -> list[str]:
    if not os.path.exists(input_file): return []
    base_name = os.path.splitext(input_file)[0]
    output_pattern = f"{base_name}_part%03d.mp4"
    cmd = [
        'ffmpeg', '-i', input_file, '-c', 'copy', '-map', '0', 
        '-segment_time', str(segment_seconds), '-f', 'segment', 
        '-reset_timestamps', '1', output_pattern
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=True)
        return sorted(glob.glob(f"{base_name}_part*.mp4"))
    except: return [input_file]

def get_settings_keyboard(uid: int):
    data = pending.get(uid)
    q, d = data.get("qual", 720), data.get("dur", 30)
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{'✅ ' if q == 720 else ''}720p", callback_data=f"set_{uid}_q_720")
    kb.button(text=f"{'✅ ' if q == 480 else ''}480p", callback_data=f"set_{uid}_q_480")
    kb.button(text=f"{'✅ ' if d == 30 else ''}30 сек", callback_data=f"set_{uid}_d_30")
    kb.button(text=f"{'✅ ' if d == 15 else ''}15 сек", callback_data=f"set_{uid}_d_15")
    kb.button(text="🚀 СКАЧАТЬ", callback_data=f"start_dl_{uid}")
    kb.adjust(2, 2, 1)
    return kb.as_markup()

stop_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🛑 ОСТАНОВИТЬ")]],
    resize_keyboard=True
)

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    # ТУТ БЫЛА ОШИБКА, ТЕПЕРЬ ВСЕ В КАВЫЧКАХ
    await message.answer("🚀 Бот готов, жду ссылку на видео.", reply_markup=ReplyKeyboardRemove())

@dp.message(F.text == "🛑 ОСТАНОВИТЬ")
async def handle_stop_text(message: Message):
    uid = message.from_user.id
    if uid in active_tasks:
        active_tasks[uid] = False
        await message.answer("🛑 Останавливаю...", reply_markup=ReplyKeyboardRemove())

@dp.message(F.text.startswith("http"))
async def handle_url(message: Message):
    url = message.text.strip()
    msg = await message.answer("🔍 Анализ...")
    try:
        opts = {**get_ydl_opts(), "skip_download": True}
        info = await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))
        uid = message.from_user.id
        pending[uid] = {"url": url, "title": info.get("title", "video"), "qual": 720, "dur": 30}
        await msg.edit_text(f"🎬 <b>{info.get('title')[:100]}</b>", reply_markup=get_settings_keyboard(uid))
    except Exception: await msg.edit_text("❌ Ошибка ссылки.")

@dp.callback_query(F.data.startswith("set_"))
async def handle_settings(callback: CallbackQuery):
    _, uid, mode, val = callback.data.split("_")
    uid, val = int(uid), int(val)
    if uid not in pending: return
    if mode == "q": pending[uid]["qual"] = val
    else: pending[uid]["dur"] = val
    await callback.message.edit_reply_markup(reply_markup=get_settings_keyboard(uid))
    await callback.answer()

@dp.callback_query(F.data.startswith("start_dl_"))
async def handle_dl(callback: CallbackQuery, bot: Bot):
    uid = int(callback.data.split("_")[-1])
    if uid not in pending: return
    
    if download_lock.locked():
        return await callback.answer("⏳ Очередь занята.", show_alert=True)

    async with download_lock:
        if uid not in pending: return
        data = pending.pop(uid)
        qual, dur = data["qual"], data["dur"]
        active_tasks[uid] = True
        
        await bot.send_message(uid, f"⏳ Начинаю: {qual}p | {dur}с.", reply_markup=stop_keyboard)
        await callback.message.delete()
        
        raw_path = f"{DOWNLOAD_DIR}/{uid}_{qual}.mp4"
        try:
            ydl_opts = {**get_ydl_opts(), "outtmpl": raw_path, "format": f"bestvideo[height<={qual}][aspect_ratio>1][ext=mp4]+bestaudio[ext=m4a]/best[height<={qual}]/best", "merge_output_format": "mp4"}
            await asyncio.get_event_loop().run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([data['url']]))
            
            if not active_tasks.get(uid): raise InterruptedError()
            parts = await asyncio.get_event_loop().run_in_executor(None, lambda: split_video_by_time(raw_path, dur))
            
            for i, part in enumerate(parts):
                if not active_tasks.get(uid): raise InterruptedError()
                w, h = (1280, 720) if qual == 720 else (854, 480)
                await bot.send_video(uid, video=FSInputFile(part), caption=f"📦 {i+1}/{len(parts)}", width=w, height=h, supports_streaming=True)
                cleanup(part)
                await asyncio.sleep(2)

        except InterruptedError:
            for f in glob.glob(f"{DOWNLOAD_DIR}/{uid}_*"): cleanup(f)
        except Exception: await bot.send_message(uid, "❌ Ошибка обработки.")
        finally:
            active_tasks.pop(uid, None)
            cleanup(raw_path)
            await bot.send_message(uid, "✅ Готово.", reply_markup=ReplyKeyboardRemove())

async def main():
    for f in glob.glob(f"{DOWNLOAD_DIR}/*"): cleanup(f)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("🤖 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
