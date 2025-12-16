#!/usr/bin/env python3
"""
Інтерактивний Telegram-бот для керування консольними програмами
Спрощена версія без ConversationHandler
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Завантажуємо змінні середовища
load_dotenv()

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфігурація
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', '0'))

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    logger.error("BOT_TOKEN або ADMIN_CHAT_ID не налаштовані в .env файлі")
    sys.exit(1)

# Глобальні змінні для процесу
active_process: Optional[asyncio.subprocess.Process] = None
waiting_manual_input: bool = False


def get_main_keyboard():
    """Головна клавіатура"""
    keyboard = [
        ["🚀 Start Program"],
        ["📡 Airgeddon"],
        ["🛑 Stop Program", "📊 Status"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_airgeddon_keyboard():
    """Клавіатура для Airgeddon з цифрами"""
    keyboard = [
        ["1", "2", "3", "4", "5"],
        ["6", "7", "8", "9", "0"],
        ["⏎ Enter", "🔄 Оновити"],
        ["✍️ Ввід", "⛔ Ctrl+C"],
        ["🛑 Stop Program"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def check_admin(update: Update) -> bool:
    """Перевірка чи користувач - адмін"""
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return False
    return True


async def read_stream_and_send(stream, context, chat_id, prefix=""):
    """Читає потік та відправляє в чат"""
    buffer = []
    try:
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode('utf-8', errors='replace').strip()
            if decoded:
                logger.info(f"{prefix}{decoded}")
                buffer.append(decoded)
                if len(buffer) >= 15:
                    msg = "\n".join(buffer)
                    if len(msg) > 4000:
                        msg = msg[-4000:]
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                    except Exception as e:
                        logger.error(f"Помилка відправки: {e}")
                    buffer = []
        
        if buffer:
            msg = "\n".join(buffer)
            if len(msg) > 4000:
                msg = msg[-4000:]
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg)
            except Exception as e:
                logger.error(f"Помилка відправки: {e}")
    except Exception as e:
        logger.error(f"Помилка читання потоку: {e}")


async def start_process(command, context, chat_id):
    """Запускає процес"""
    global active_process
    
    try:
        active_process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Процес запущено: {' '.join(command)}\nPID: {active_process.pid}",
            reply_markup=get_airgeddon_keyboard()
        )
        
        stdout_task = asyncio.create_task(
            read_stream_and_send(active_process.stdout, context, chat_id, "[OUT] ")
        )
        stderr_task = asyncio.create_task(
            read_stream_and_send(active_process.stderr, context, chat_id, "[ERR] ")
        )
        
        returncode = await active_process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏁 Процес завершено з кодом: {returncode}",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Помилка запуску процесу: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Помилка: {e}")
    finally:
        active_process = None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    if not await check_admin(update):
        return
    
    await update.message.reply_text(
        "👋 Вітаю! Бот для керування програмами.\n\n"
        "📡 Airgeddon - запустити airgeddon\n"
        "🚀 Start Program - запустити свою команду",
        reply_markup=get_main_keyboard()
    )


async def button_airgeddon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка запуску Airgeddon"""
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        await update.message.reply_text("⚠️ Програма вже запущена!", reply_markup=get_airgeddon_keyboard())
        return
    
    command = ["/home/kali/airgeddon_tmux.sh"]
    await update.message.reply_text("📡 Запускаю Airgeddon...\n⏳ Зачекай 10 секунд на завантаження", reply_markup=get_airgeddon_keyboard())
    asyncio.create_task(start_process(command, context, update.effective_chat.id))


async def button_stop_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка зупинки програми"""
    global active_process
    
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        try:
            active_process.terminate()
            await asyncio.sleep(1)
            if active_process.returncode is None:
                active_process.kill()
            await update.message.reply_text("🛑 Програму зупинено", reply_markup=get_main_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка статусу"""
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        await update.message.reply_text(
            f"✅ Процес активний\nPID: {active_process.pid}",
            reply_markup=get_airgeddon_keyboard()
        )
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка Enter"""
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        try:
            active_process.stdin.write(b"enter\n")
            await active_process.stdin.drain()
            await update.message.reply_text("⏎ Enter відправлено\n⏳ Зачекай 3 сек...", reply_markup=get_airgeddon_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_airgeddon_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка оновлення"""
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        try:
            active_process.stdin.write(b"refresh\n")
            await active_process.stdin.drain()
            await update.message.reply_text("🔄 Оновлення...", reply_markup=get_airgeddon_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_airgeddon_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_ctrlc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка Ctrl+C"""
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        try:
            active_process.stdin.write(b"ctrlc\n")
            await active_process.stdin.drain()
            await update.message.reply_text("⛔ Ctrl+C відправлено\n⏳ Зачекай 2 сек...", reply_markup=get_airgeddon_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_airgeddon_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_digit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка цифрових кнопок"""
    if not await check_admin(update):
        return
    
    digit = update.message.text
    
    if active_process and active_process.returncode is None:
        try:
            active_process.stdin.write(f"{digit}\n".encode())
            await active_process.stdin.drain()
            await update.message.reply_text(f"📤 Відправлено: {digit}\n⏳ Зачекай 3 сек...", reply_markup=get_airgeddon_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_airgeddon_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def button_manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка для ручного вводу"""
    global waiting_manual_input
    
    if not await check_admin(update):
        return
    
    if active_process and active_process.returncode is None:
        waiting_manual_input = True
        await update.message.reply_text(
            "✍️ Тепер введи команду (наприклад: 11, wlan0, Y, N)\n"
            "Будь-який наступний текст буде відправлено в програму",
            reply_markup=get_airgeddon_keyboard()
        )
    else:
        await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_main_keyboard())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка будь-якого тексту - відправляє в процес"""
    global waiting_manual_input
    
    if not await check_admin(update):
        return
    
    text = update.message.text
    
    # Ігноруємо якщо це кнопка
    buttons = ["🚀 Start Program", "📡 Airgeddon", "🛑 Stop Program", "📊 Status", 
               "⏎ Enter", "🔄 Оновити", "✍️ Ввід", "⛔ Ctrl+C"]
    if text in buttons:
        return
    
    if active_process and active_process.returncode is None:
        try:
            active_process.stdin.write(f"{text}\n".encode())
            await active_process.stdin.drain()
            waiting_manual_input = False
            await update.message.reply_text(f"✅ Відправлено: {text}\n⏳ Зачекай 3 сек...", reply_markup=get_airgeddon_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_airgeddon_keyboard())
    else:
        await update.message.reply_text("⭕ Немає активного процесу. Спочатку запусти програму.", reply_markup=get_main_keyboard())


def main():
    """Головна функція"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Команди
    application.add_handler(CommandHandler("start", start_command))
    
    # Кнопки (порядок важливий - специфічні перед загальними)
    application.add_handler(MessageHandler(filters.Regex("^📡 Airgeddon$"), button_airgeddon))
    application.add_handler(MessageHandler(filters.Regex("^🛑 Stop Program$"), button_stop_program))
    application.add_handler(MessageHandler(filters.Regex("^📊 Status$"), button_status))
    application.add_handler(MessageHandler(filters.Regex("^⏎ Enter$"), button_enter))
    application.add_handler(MessageHandler(filters.Regex("^🔄 Оновити$"), button_refresh))
    application.add_handler(MessageHandler(filters.Regex("^✍️ Ввід$"), button_manual_input))
    application.add_handler(MessageHandler(filters.Regex("^⛔ Ctrl\\+C$"), button_ctrlc))
    application.add_handler(MessageHandler(filters.Regex("^[0-9]$"), button_digit))
    
    # Будь-який інший текст - відправляємо в процес
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Бот запущено...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Бот зупинено")
