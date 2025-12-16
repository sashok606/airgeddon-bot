#!/usr/bin/env python3
"""
Інтерактивний Telegram-бот для керування консольними програмами
Спрощена версія без ConversationHandler
"""

import asyncio
import logging
import os
import sys
import glob
from datetime import datetime
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
waiting_command: bool = False  # Режим очікування команди для Start Program


def get_main_keyboard():
    """Головна клавіатура"""
    keyboard = [
        ["🚀 Start Program", "📡 Airgeddon"],
        ["📦 Хендшейки"],
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


def get_command_keyboard():
    """Клавіатура для режиму командного рядка"""
    keyboard = [
        ["🔄 Оновити", "⛔ Ctrl+C"],
        ["🔙 Назад"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# Глобальні змінні для командного рядка
command_process: Optional[asyncio.subprocess.Process] = None
command_output: str = ""


async def check_admin(update: Update) -> bool:
    """Перевірка чи користувач - адмін"""
    if update.effective_chat.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return False
    return True


async def read_stream_and_send(stream, context, chat_id, prefix=""):
    """Читає потік та відправляє в чат - збирає весь блок і відправляє разом"""
    buffer = []
    last_send_time = 0
    
    try:
        while True:
            try:
                # Читаємо з таймаутом щоб не блокувати
                line = await asyncio.wait_for(stream.readline(), timeout=0.5)
            except asyncio.TimeoutError:
                # Якщо нічого не прийшло і є буфер - відправляємо
                if buffer and (asyncio.get_event_loop().time() - last_send_time > 2):
                    msg = "\n".join(buffer)
                    if msg.strip():
                        if len(msg) > 4000:
                            msg = msg[-4000:]
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=msg)
                        except Exception as e:
                            logger.error(f"Помилка відправки: {e}")
                    buffer = []
                    last_send_time = asyncio.get_event_loop().time()
                continue
            
            if not line:
                break
                
            decoded = line.decode('utf-8', errors='replace').strip()
            if decoded:
                logger.info(f"{prefix}{decoded}")
                buffer.append(decoded)
                last_send_time = asyncio.get_event_loop().time()
        
        # Відправляємо залишок буфера
        if buffer:
            msg = "\n".join(buffer)
            if msg.strip():
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
        "🚀 Start Program - командний рядок\n"
        "📡 Airgeddon - запустити airgeddon\n"
        "📦 Хендшейки - скачати захоплені файли",
        reply_markup=get_main_keyboard()
    )


async def button_start_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка Start Program - режим командного рядка"""
    global waiting_command
    
    if not await check_admin(update):
        return
    
    waiting_command = True
    await update.message.reply_text(
        "💻 Режим командного рядка\n\n"
        "Введи команду для виконання:\n"
        "Наприклад: `ls -la`, `ifconfig`, `ping -c 3 google.com`\n\n"
        "Натисни 🔙 Назад для виходу",
        parse_mode="Markdown",
        reply_markup=get_command_keyboard()
    )


async def run_shell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Виконує shell команду і повертає результат"""
    global waiting_command
    
    if not await check_admin(update):
        return
    
    command = update.message.text
    waiting_command = False
    
    await update.message.reply_text(f"⏳ Виконую: `{command}`", parse_mode="Markdown")
    
    try:
        # Виконуємо команду
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        
        output = ""
        if stdout:
            output += stdout.decode('utf-8', errors='replace')
        if stderr:
            output += "\n[STDERR]\n" + stderr.decode('utf-8', errors='replace')
        
        if not output.strip():
            output = "(команда виконана, вивід відсутній)"
        
        # Обрізаємо якщо занадто довгий
        if len(output) > 4000:
            output = output[:4000] + "\n... (обрізано)"
        
        await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ Таймаут команди (60 сек)", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_main_keyboard())


# Глобальний список хендшейків для вибору
handshake_files: list = []

async def button_handshakes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка для показу списку хендшейків"""
    global handshake_files
    
    if not await check_admin(update):
        return
    
    # Шукаємо файли хендшейків тільки в /root/
    handshake_patterns = [
        "/root/*.cap",
        "/root/*.pcap", 
        "/root/*.hccapx",
        "/root/*.22000",
    ]
    
    files = []
    for pattern in handshake_patterns:
        found = glob.glob(pattern)
        files.extend(found)
    
    # Видаляємо дублікати і директорії
    files = list(set([f for f in files if os.path.isfile(f)]))
    files.sort(key=os.path.getmtime, reverse=True)  # Сортуємо по даті
    
    if not files:
        await update.message.reply_text(
            "📭 Хендшейки не знайдено в /root/",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Зберігаємо список для подальшого вибору
    handshake_files = files[:20]
    
    # Показуємо список файлів
    msg = f"📦 Знайдено {len(files)} файл(ів):\n\n"
    for i, f in enumerate(handshake_files, 1):
        size = os.path.getsize(f)
        size_str = f"{size} B" if size < 1024 else f"{size//1024} KB"
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        date_str = mtime.strftime("%d.%m.%Y %H:%M")
        msg += f"{i}. `{os.path.basename(f)}`\n   📅 {date_str} | 💾 {size_str}\n\n"
    
    msg += "📥 Введи номер файлу для скачування\nабо 0 для виходу"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_handshake_keyboard())


def get_handshake_keyboard():
    """Клавіатура для вибору хендшейків"""
    keyboard = [["🔙 Назад"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def handle_handshake_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору номера хендшейку"""
    global handshake_files
    
    if not await check_admin(update):
        return
    
    text = update.message.text.strip()
    
    # Перевіряємо чи це номер
    if not text.isdigit():
        return False
    
    num = int(text)
    
    # 0 = вихід
    if num == 0:
        handshake_files = []
        await update.message.reply_text("🏠 Головне меню", reply_markup=get_main_keyboard())
        return True
    
    # Перевіряємо чи є список
    if not handshake_files:
        return False
    
    # Перевіряємо діапазон
    if num < 1 or num > len(handshake_files):
        await update.message.reply_text(f"❌ Невірний номер. Введи від 1 до {len(handshake_files)}", reply_markup=get_handshake_keyboard())
        return True
    
    # Відправляємо файл
    f = handshake_files[num - 1]
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(f))
        date_str = mtime.strftime("%d.%m.%Y %H:%M")
        size = os.path.getsize(f)
        size_str = f"{size} B" if size < 1024 else f"{size//1024} KB"
        with open(f, 'rb') as file:
            await update.message.reply_document(
                document=file,
                filename=os.path.basename(f),
                caption=f"📁 {os.path.basename(f)}\n📅 {date_str}\n💾 {size_str}"
            )
        await update.message.reply_text("✅ Надіслано!\n\nВведи ще номер або 0 для виходу", reply_markup=get_handshake_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_handshake_keyboard())
    
    return True


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
    global command_output
    
    if not await check_admin(update):
        return
    
    # Режим командного рядка
    if waiting_command:
        if command_output:
            output = command_output
            # Беремо останні 60 рядків
            lines = output.strip().split('\n')
            if len(lines) > 60:
                output = '\n'.join(lines[-60:])
                output = f"...(показано останні 60 рядків)\n{output}"
            if len(output) > 4000:
                output = output[-4000:]
            await update.message.reply_text(f"📤 Останній вивід:\n```\n{output}\n```", 
                                           parse_mode='Markdown',
                                           reply_markup=get_command_keyboard())
        else:
            await update.message.reply_text("📭 Немає збереженого виводу", reply_markup=get_command_keyboard())
        return
    
    # Режим airgeddon
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
    global command_process, command_output
    
    if not await check_admin(update):
        return
    
    # Режим командного рядка
    if waiting_command:
        if command_process and command_process.returncode is None:
            try:
                import signal
                import os as os_module
                # Відправляємо SIGTERM всій групі процесів
                os_module.killpg(os_module.getpgid(command_process.pid), signal.SIGTERM)
                await asyncio.sleep(0.5)
                # Якщо ще працює - SIGKILL
                if command_process.returncode is None:
                    os_module.killpg(os_module.getpgid(command_process.pid), signal.SIGKILL)
                
                # Показуємо останній вивід
                if command_output:
                    output = command_output
                    lines = output.strip().split('\n')
                    if len(lines) > 30:
                        output = '\n'.join(lines[-30:])
                    if len(output) > 3000:
                        output = output[-3000:]
                    await update.message.reply_text(f"⛔ Процес зупинено\n\n📤 Останній вивід:\n```\n{output}\n```", 
                                                   parse_mode='Markdown',
                                                   reply_markup=get_command_keyboard())
                else:
                    await update.message.reply_text("⛔ Процес зупинено", reply_markup=get_command_keyboard())
            except Exception as e:
                # Якщо killpg не працює - просто terminate
                try:
                    command_process.terminate()
                    await update.message.reply_text("⛔ Процес зупинено", reply_markup=get_command_keyboard())
                except:
                    await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_command_keyboard())
        else:
            await update.message.reply_text("⭕ Немає активного процесу", reply_markup=get_command_keyboard())
        return
    
    # Режим airgeddon
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
    global handshake_files
    
    if not await check_admin(update):
        return
    
    digit = update.message.text
    
    # Якщо режим вибору хендшейків - передаємо туди
    if handshake_files:
        await handle_handshake_selection(update, context)
        return
    
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


async def button_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопка Назад - повернення в головне меню"""
    global waiting_command, handshake_files, command_process
    
    if not await check_admin(update):
        return
    
    # Зупиняємо процес якщо є
    if command_process and command_process.returncode is None:
        try:
            command_process.terminate()
        except:
            pass
    
    waiting_command = False
    handshake_files = []
    await update.message.reply_text("🏠 Головне меню", reply_markup=get_main_keyboard())


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка будь-якого тексту - відправляє в процес або виконує команду"""
    global waiting_manual_input, waiting_command, handshake_files
    
    if not await check_admin(update):
        return
    
    text = update.message.text
    
    # Ігноруємо якщо це кнопка
    buttons = ["🚀 Start Program", "📡 Airgeddon", "🛑 Stop Program", "📊 Status", 
               "⏎ Enter", "🔄 Оновити", "✍️ Ввід", "⛔ Ctrl+C", "📦 Хендшейки", "🔙 Назад",
               "🔄 Оновити", "⛔ Ctrl+C"]
    if text in buttons:
        return
    
    # Режим вибору хендшейка (перевіряємо ПЕРШИМ!)
    if handshake_files:
        if text.isdigit():
            handled = await handle_handshake_selection(update, context)
            if handled:
                return
        else:
            await update.message.reply_text("❌ Введи номер файлу або 0 для виходу", reply_markup=get_handshake_keyboard())
            return
    
    # Режим командного рядка
    if waiting_command:
        global command_process, command_output
        try:
            await update.message.reply_text(f"⏳ Виконую: `{text}`\n\nНатисни 🔄 Оновити щоб побачити вивід\n⛔ Ctrl+C щоб зупинити", 
                                           parse_mode='Markdown', reply_markup=get_command_keyboard())
            
            import os as os_module
            # Виконуємо команду в новій групі процесів для можливості зупинки
            command_process = await asyncio.create_subprocess_shell(
                text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os_module.setsid  # Створюємо нову групу процесів
            )
            
            command_output = ""
            
            # Читаємо вивід асинхронно в фоні (не блокуємо!)
            async def read_output():
                global command_output, command_process
                try:
                    while command_process and command_process.returncode is None:
                        try:
                            line = await asyncio.wait_for(command_process.stdout.readline(), timeout=0.5)
                            if not line:
                                break
                            command_output += line.decode('utf-8', errors='replace')
                            # Обмежуємо розмір буфера
                            if len(command_output) > 50000:
                                command_output = command_output[-40000:]
                        except asyncio.TimeoutError:
                            continue
                except:
                    pass
            
            # Запускаємо читання в фоні - НЕ чекаємо!
            asyncio.create_task(read_output())
                
        except Exception as e:
            await update.message.reply_text(f"❌ Помилка: {e}", reply_markup=get_command_keyboard())
            command_process = None
        return
    
    # Режим airgeddon
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
    application.add_handler(MessageHandler(filters.Regex("^🚀 Start Program$"), button_start_program))
    application.add_handler(MessageHandler(filters.Regex("^📡 Airgeddon$"), button_airgeddon))
    application.add_handler(MessageHandler(filters.Regex("^📦 Хендшейки$"), button_handshakes))
    application.add_handler(MessageHandler(filters.Regex("^🛑 Stop Program$"), button_stop_program))
    application.add_handler(MessageHandler(filters.Regex("^📊 Status$"), button_status))
    application.add_handler(MessageHandler(filters.Regex("^⏎ Enter$"), button_enter))
    application.add_handler(MessageHandler(filters.Regex("^🔄 Оновити$"), button_refresh))
    application.add_handler(MessageHandler(filters.Regex("^✍️ Ввід$"), button_manual_input))
    application.add_handler(MessageHandler(filters.Regex("^⛔ Ctrl\\+C$"), button_ctrlc))
    application.add_handler(MessageHandler(filters.Regex("^🔙 Назад$"), button_back))
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
