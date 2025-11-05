from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import requests
import time
import logging
import hashlib
import json
import os
import threading
import platform
import psutil
import socket
from datetime import datetime, timedelta

# Настройки
TELEGRAM_BOT_TOKEN = "" #токен для бота в ТГ
ADMIN_PASSWORD = "" #пароль для админ панели
MAX_GROUP_URL = "" #URL для чата в MAX

# Файлы для хранения данных
SETTINGS_FILE = "bot_settings.json"
CHATS_FILE = "telegram_chats.json"
PROCESSED_MESSAGES_FILE = "processed_messages.json"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальные переменные для отслеживания производительности
BOT_START_TIME = datetime.now()
TOTAL_FORWARDED_MESSAGES = 0

class BotSettings:
    def __init__(self):
        self.settings = self.load_settings()
        self.telegram_chats = self.load_telegram_chats()
        self.processed_messages = self.load_processed_messages()
        
    def load_settings(self):
        """Загрузка настроек из файла"""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
        return {
            "forwarding_enabled": False,
            "admin_chat_id": None,  # ID постоянного администратора
            "selected_chat_id": None,
            "auto_start": False,
            "last_error": None
        }
    
    def load_telegram_chats(self):
        """Загрузка списка чатов из файла"""
        try:
            if os.path.exists(CHATS_FILE):
                with open(CHATS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки чатов: {e}")
        return {}
    
    def load_processed_messages(self):
        """Загрузка обработанных сообщений из файла"""
        try:
            if os.path.exists(PROCESSED_MESSAGES_FILE):
                with open(PROCESSED_MESSAGES_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки обработанных сообщений: {e}")
        return {}
    
    def save_settings(self):
        """Сохранение настроек в файл"""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения настроек: {e}")
    
    def save_telegram_chats(self):
        """Сохранение списка чатов в файл"""
        try:
            with open(CHATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.telegram_chats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения чатов: {e}")
    
    def save_processed_messages(self):
        """Сохранение обработанных сообщений в файл"""
        try:
            with open(PROCESSED_MESSAGES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.processed_messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения обработанных сообщений: {e}")
    
    def add_processed_message(self, chat_id, message_hash):
        """Добавление обработанного сообщения для конкретного чата"""
        if chat_id not in self.processed_messages:
            self.processed_messages[chat_id] = []
        
        # Ограничиваем историю последними 1000 сообщениями для каждого чата
        if len(self.processed_messages[chat_id]) > 1000:
            self.processed_messages[chat_id] = self.processed_messages[chat_id][-900:]
        
        if message_hash not in self.processed_messages[chat_id]:
            self.processed_messages[chat_id].append(message_hash)
            self.save_processed_messages()
    
    def is_message_processed(self, chat_id, message_hash):
        """Проверка, было ли сообщение уже обработано для чата"""
        return chat_id in self.processed_messages and message_hash in self.processed_messages[chat_id]

class MaxToTelegramForwarder:
    def __init__(self, bot_settings):
        self.settings = bot_settings
        self.driver = None
        self.is_ready = False
        self.forwarding_active = False
        self.application = None
        
    def setup_selenium(self):
        """Настройка Selenium WebDriver"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument("--start-maximized")
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            logger.info("Браузер запущен")
            return True
        except Exception as e:
            error_msg = f"Ошибка настройки браузера: {e}"
            logger.error(error_msg)
            self.send_admin_message(f"❌ {error_msg}")
            return False
    
    def open_max(self):
        """Открытие MAX в браузере"""
        try:
            self.driver.get("https://web.max.ru")
            logger.info("MAX открыт в браузере")
            return True
        except Exception as e:
            error_msg = f"Ошибка открытия MAX: {e}"
            logger.error(error_msg)
            self.send_admin_message(f"❌ {error_msg}")
            return False
    
    def navigate_to_group(self):
        """Переход к конкретной группе в MAX по прямому URL"""
        try:
            logger.info(f"Переход в группу: {MAX_GROUP_URL}")
            self.driver.get(MAX_GROUP_URL)
            time.sleep(5)
            
            # Проверяем, что загрузилась страница группы
            chat_indicators = [
                "input[placeholder*='сообщени']",
                "input[placeholder*='message']",
                "div[contenteditable='true']",
                "[class*='message']",
                "[class*='chat']"
            ]
            
            for indicator in chat_indicators:
                elements = self.driver.find_elements(By.CSS_SELECTOR, indicator)
                if elements:
                    logger.info("Успешно перешли в группу MAX")
                    return True
            
            logger.warning("Не удалось подтвердить переход в группу, но продолжаем...")
            return True
            
        except Exception as e:
            error_msg = f"Ошибка перехода в группу: {e}"
            logger.error(error_msg)
            self.send_admin_message(f"❌ {error_msg}")
            return False
    
    def send_to_telegram(self, text, chat_id=None):
        """Отправка сообщения в Telegram через бота"""
        if not chat_id:
            chat_id = self.settings.settings.get("selected_chat_id")
            if not chat_id:
                logger.error("Не выбран чат для отправки")
                return False
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            return result.get("ok", False)
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
            return False
    
    def send_admin_message(self, text):
        """Отправка сообщения админу"""
        admin_chat_id = self.settings.settings.get("admin_chat_id")
        if admin_chat_id:
            self.send_to_telegram(text, admin_chat_id)
    
    def extract_messages_from_max(self):
        """Извлечение сообщений из группы MAX"""
        messages = []
        
        try:
            # Ищем все элементы, которые могут быть сообщениями
            all_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class]")
            
            for element in all_elements[-50:]:  # Проверяем последние 50 элементов
                try:
                    text = element.text.strip()
                    # Фильтруем сообщения
                    if (text and 
                        len(text) > 5 and 
                        len(text) < 1000 and
                        not text.startswith("http")):
                        
                        if any(keyword in text.lower() for keyword in [':', 'написал', 'отправлено', 'message']):
                            messages.append(text)
                        elif len(text) > 20:
                            messages.append(text)
                            
                except:
                    continue
                    
        except Exception as e:
            error_msg = f"Ошибка извлечения сообщений: {e}"
            logger.error(error_msg)
            self.send_admin_message(f"❌ {error_msg}")
        
        return messages
    
    def get_message_hash(self, message):
        """Создание хеша для сообщения"""
        return hashlib.md5(message.encode()).hexdigest()
    
    def start_forwarding_process(self):
        """Запуск процесса пересылки сообщений"""
        if self.forwarding_active:
            return
        
        self.forwarding_active = True
        
        # Настраиваем Selenium
        if not self.setup_selenium():
            self.forwarding_active = False
            return
        
        # Открываем MAX для входа
        if not self.open_max():
            self.forwarding_active = False
            return
        
        self.send_admin_message("🔐 Браузер открыт. Войдите в MAX вручную и нажмите кнопку 'Я вошел' в меню бота.")
        
        # Ждем готовности через флаг is_ready
        while not self.is_ready and self.forwarding_active:
            time.sleep(5)
        
        if not self.forwarding_active:
            return
        
        # Переходим в группу
        if not self.navigate_to_group():
            self.forwarding_active = False
            return
        
        # Начинаем пересылку
        self.send_admin_message("🚀 Начата пересылка сообщений из MAX!")
        logger.info("Начата пересылка сообщений")
        
        error_count = 0
        
        try:
            while self.forwarding_active:
                try:
                    # Получаем сообщения из MAX
                    messages = self.extract_messages_from_max()
                    
                    # Получаем выбранный чат
                    selected_chat = self.settings.settings.get("selected_chat_id")
                    if not selected_chat:
                        logger.warning("Не выбран чат для отправки")
                        time.sleep(10)
                        continue
                    
                    # Обрабатываем только новые сообщения
                    new_messages = []
                    for message in messages:
                        msg_hash = self.get_message_hash(message)
                        if not self.settings.is_message_processed(selected_chat, msg_hash):
                            new_messages.append(message)
                            self.settings.add_processed_message(selected_chat, msg_hash)
                    
                    # Отправляем новые сообщения в Telegram
                    for message in new_messages:
                        if len(message) > 4000:
                            message = message[:4000] + "..."
                            
                        success = self.send_to_telegram(f"📨 Из MAX:\n{message}")
                        if success:
                            global TOTAL_FORWARDED_MESSAGES
                            TOTAL_FORWARDED_MESSAGES += 1
                            logger.info(f"Переслано в {selected_chat}: {message[:80]}...")
                        else:
                            logger.error("Ошибка отправки в Telegram")
                            error_count += 1
                    
                    # Сбрасываем счетчик ошибок при успешной отправке
                    if new_messages:
                        error_count = 0
                    
                    # Перезапуск при множественных ошибках
                    if error_count >= 5:
                        self.send_admin_message("⚠️ Много ошибок, перезапускаю браузер...")
                        self.driver.quit()
                        time.sleep(5)
                        if not self.setup_selenium() or not self.navigate_to_group():
                            self.send_admin_message("❌ Не удалось восстановить соединение")
                            break
                        error_count = 0
                    
                    # Обновление страницы
                    if len(messages) % 30 == 0:
                        self.driver.refresh()
                        time.sleep(5)
                    
                    time.sleep(5)
                    
                except Exception as e:
                    error_msg = f"Ошибка в основном цикле: {e}"
                    logger.error(error_msg)
                    error_count += 1
                    time.sleep(5)
                    
        except Exception as e:
            error_msg = f"Критическая ошибка: {e}"
            logger.error(error_msg)
            self.send_admin_message(f"❌ {error_msg}")
        finally:
            if self.driver:
                self.driver.quit()
            self.forwarding_active = False
            self.send_admin_message("🛑 Пересылка сообщений остановлена")
    
    def stop_forwarding(self):
        """Остановка пересылки сообщений"""
        self.forwarding_active = False
        self.is_ready = False
        if self.driver:
            self.driver.quit()

# Глобальные объекты
bot_settings = BotSettings()
forwarder = MaxToTelegramForwarder(bot_settings)

# Словарь для временных сессий (user_id -> время авторизации)
user_sessions = {}

def is_user_authorized(user_id):
    """Проверка авторизации пользователя (сессия 1 час)"""
    if user_id in user_sessions:
        session_time = user_sessions[user_id]
        if datetime.now() - session_time < timedelta(hours=1):
            # Обновляем время сессии
            user_sessions[user_id] = datetime.now()
            return True
        else:
            # Удаляем просроченную сессию
            del user_sessions[user_id]
    return False

def get_system_info():
    """Получение информации о системе"""
    try:
        # Информация о системе
        system_info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version()
        }
        
        # Информация о памяти
        memory = psutil.virtual_memory()
        system_info["memory_total"] = memory.total // (1024**3)  # GB
        system_info["memory_used"] = memory.used // (1024**3)    # GB
        system_info["memory_percent"] = memory.percent
        
        # Информация о диске
        disk = psutil.disk_usage('/')
        system_info["disk_total"] = disk.total // (1024**3)      # GB
        system_info["disk_used"] = disk.used // (1024**3)        # GB
        system_info["disk_percent"] = disk.percent
        
        # Информация о CPU
        system_info["cpu_cores"] = psutil.cpu_count()
        system_info["cpu_usage"] = psutil.cpu_percent(interval=1)
        
        return system_info
    except Exception as e:
        logger.error(f"Ошибка получения информации о системе: {e}")
        return None

def test_ping_and_speed():
    """Тестирование пинга и скорости через ya.ru"""
    try:
        results = {
            "ping": "Ошибка",
            "download_speed": "Ошибка",
            "upload_speed": "N/A"
        }
        
        # Тестируем пинг до ya.ru
        start_time = time.time()
        try:
            response = requests.get("https://ya.ru", timeout=10)
            ping_time = (time.time() - start_time) * 1000  # в миллисекундах
            results["ping"] = f"{ping_time:.2f} мс"
        except Exception as e:
            results["ping"] = f"Ошибка: {str(e)}"
        
        # Тестируем скорость загрузки через ya.ru
        start_time = time.time()
        try:
            response = requests.get("https://ya.ru", timeout=10)
            download_time = time.time() - start_time
            # Размер контента в байтах
            content_size = len(response.content)
            # Скорость в Mbps (мегабит в секунду)
            speed_mbps = (content_size * 8) / (download_time * 1_000_000)
            results["download_speed"] = f"{speed_mbps:.2f} Mbps"
        except Exception as e:
            results["download_speed"] = f"Ошибка: {str(e)}"
        
        return results
    except Exception as e:
        logger.error(f"Ошибка тестирования скорости и пинга: {e}")
        return None

def get_network_info():
    """Получение информации о сети"""
    try:
        network_info = {}
        
        # Внутренний IP
        hostname = socket.gethostname()
        network_info["hostname"] = hostname
        try:
            internal_ip = socket.gethostbyname(hostname)
            network_info["internal_ip"] = internal_ip
        except:
            network_info["internal_ip"] = "Не удалось определить"
        
        # Внешний IP
        try:
            external_ip = requests.get('https://api.ipify.org', timeout=10).text
            network_info["external_ip"] = external_ip
        except:
            network_info["external_ip"] = "Не удалось определить"
        
        # Тестируем пинг и скорость через ya.ru
        speed_test_results = test_ping_and_speed()
        if speed_test_results:
            network_info.update(speed_test_results)
        else:
            network_info["ping"] = "Ошибка тестирования"
            network_info["download_speed"] = "Ошибка тестирования"
            network_info["upload_speed"] = "N/A"
        
        return network_info
    except Exception as e:
        logger.error(f"Ошибка получения информации о сети: {e}")
        return None

def get_bot_performance():
    """Получение информации о производительности бота"""
    try:
        uptime = datetime.now() - BOT_START_TIME
        hours, remainder = divmod(uptime.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        performance_info = {
            "uptime": f"{int(days)}д {int(hours)}ч {int(minutes)}м {int(seconds)}с",
            "total_messages": TOTAL_FORWARDED_MESSAGES,
            "forwarding_active": forwarder.forwarding_active,
            "is_ready": forwarder.is_ready,
            "total_chats": len(bot_settings.telegram_chats),
            "selected_chat": bot_settings.settings.get("selected_chat_id"),
            "processed_messages_total": sum(len(messages) for messages in bot_settings.processed_messages.values())
        }
        
        return performance_info
    except Exception as e:
        logger.error(f"Ошибка получения информации о производительности: {e}")
        return None

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🔐 Авторизация", callback_data="auth")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    
    # Если пользователь авторизован, показываем админ-панель
    if is_user_authorized(user_id):
        keyboard.insert(0, [InlineKeyboardButton("👑 Админ панель", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 Бот для пересылки сообщений из MAX в Telegram\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    # Проверяем авторизацию для админских функций
    if data in ["admin_menu", "start_forwarding", "stop_forwarding", "list_chats", 
                "add_chat", "select_chat", "im_ready", "performance"]:
        if not is_user_authorized(user_id):
            await query.edit_message_text(
                "❌ Доступ запрещен. Требуется авторизация.\n"
                "Используйте команду: /password <пароль>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]])
            )
            return
    
    if data == "auth":
        await auth_handler(query, user_id)
    elif data == "status":
        await status_handler(query, user_id)
    elif data == "help":
        await help_handler(query, user_id)
    elif data == "main_menu":
        await main_menu_handler(query, user_id)
    elif data == "admin_menu":
        await admin_menu_handler(query, user_id)
    elif data == "start_forwarding":
        await start_forwarding_handler(query, user_id)
    elif data == "stop_forwarding":
        await stop_forwarding_handler(query, user_id)
    elif data == "list_chats":
        await list_chats_handler(query, user_id)
    elif data == "add_chat":
        await add_chat_handler(query, user_id)
    elif data == "select_chat":
        await select_chat_handler(query, user_id)
    elif data == "im_ready":
        await im_ready_handler(query, user_id)
    elif data == "performance":
        await performance_handler(query, user_id)
    elif data.startswith("chat_"):
        await chat_selection_handler(query, data)

async def auth_handler(query, user_id):
    """Обработчик авторизации"""
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔐 Для авторизации введите пароль администратора:\n"
        "Используйте команду: /password <ваш_пароль>",
        reply_markup=reply_markup
    )

async def status_handler(query, user_id):
    """Обработчик статуса"""
    status_text = "📊 Статус бота:\n\n"
    
    # Статус авторизации
    if is_user_authorized(user_id):
        status_text += "✅ Вы авторизованы\n"
    else:
        status_text += "❌ Вы не авторизованы\n"
    
    # Статус пересылки
    if forwarder.forwarding_active:
        if forwarder.is_ready:
            status_text += "🟢 Пересылка активна\n"
        else:
            status_text += "🟡 Ожидание входа в MAX\n"
    else:
        status_text += "🔴 Пересылка не активна\n"
    
    # Выбранный чат
    selected_chat = bot_settings.settings.get("selected_chat_id")
    if selected_chat:
        chat_name = bot_settings.telegram_chats.get(str(selected_chat), "Неизвестно")
        status_text += f"📱 Выбранный чат: {chat_name}\n"
    else:
        status_text += "📱 Чат не выбран\n"
    
    # Количество чатов
    status_text += f"💬 Всего чатов: {len(bot_settings.telegram_chats)}\n"
    
    # Последняя ошибка
    last_error = bot_settings.settings.get("last_error")
    if last_error:
        status_text += f"⚠️ Последняя ошибка: {last_error}\n"
    
    # Определяем, куда ведет кнопка "Назад"
    if is_user_authorized(user_id):
        back_target = "admin_menu"
    else:
        back_target = "main_menu"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=back_target)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(status_text, reply_markup=reply_markup)

async def help_handler(query, user_id):
    """Обработчик помощи"""
    help_text = (
        "ℹ️ Помощь по боту:\n\n"
        "🔐 Авторизация:\n"
        "Используйте /password <пароль> для авторизации\n\n"
        "💬 Управление чатами:\n"
        "Добавьте бота в чат и используйте меню для выбора\n\n"
        "🔄 Запуск пересылки:\n"
        "1. Авторизуйтесь\n"
        "2. Выберите чат\n"
        "3. Запустите пересылку\n"
        "4. Войдите в MAX в браузере\n"
        "5. Нажмите 'Я вошел'\n\n"
        "⏹️ Остановка:\n"
        "Используйте кнопку 'Остановить пересылку'\n\n"
        "🛠️ Команды:\n"
        "/start - Главное меню\n"
        "/password <пароль> - Авторизация\n"
        "/addchat - Добавить текущий чат\n"
        "/status - Статус бота\n"
        "/logout - Выйти из системы"
    )
    
    # Определяем, куда ведет кнопка "Назад"
    if is_user_authorized(user_id):
        back_target = "admin_menu"
    else:
        back_target = "main_menu"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=back_target)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(help_text, reply_markup=reply_markup)

async def performance_handler(query, user_id):
    """Обработчик производительности"""
    # Отправляем сообщение о сборе информации
    await query.edit_message_text("📊 Сбор информации о производительности...")
    
    # Собираем информацию
    system_info = get_system_info()
    network_info = get_network_info()
    performance_info = get_bot_performance()
    
    # Формируем сообщение
    performance_text = "🚀 Производительность бота\n\n"
    
    # Информация о системе
    performance_text += "💻 Системная информация:\n"
    if system_info:
        performance_text += f"• ОС: {system_info['platform']} {system_info['platform_release']}\n"
        performance_text += f"• Архитектура: {system_info['architecture']}\n"
        performance_text += f"• Процессор: {system_info['cpu_cores']} ядер, {system_info['cpu_usage']}% загрузки\n"
        performance_text += f"• Память: {system_info['memory_used']}/{system_info['memory_total']} GB ({system_info['memory_percent']}%)\n"
        performance_text += f"• Диск: {system_info['disk_used']}/{system_info['disk_total']} GB ({system_info['disk_percent']}%)\n"
        performance_text += f"• Python: {system_info['python_version']}\n"
    else:
        performance_text += "• Не удалось получить информацию о системе\n"
    
    performance_text += "\n🌐 Сетевая информация:\n"
    if network_info:
        performance_text += f"• Хост: {network_info['hostname']}\n"
        performance_text += f"• Внутренний IP: {network_info['internal_ip']}\n"
        performance_text += f"• Внешний IP: {network_info['external_ip']}\n"
        performance_text += f"• Пинг до Яндекс: {network_info['ping']}\n"
        performance_text += f"• Скорость загрузки: {network_info['download_speed']}\n"
        performance_text += f"• Скорость отдачи: {network_info['upload_speed']}\n"
    else:
        performance_text += "• Не удалось получить информацию о сети\n"
    
    performance_text += "\n🤖 Производительность бота:\n"
    if performance_info:
        performance_text += f"• Время работы: {performance_info['uptime']}\n"
        performance_text += f"• Всего переслано: {performance_info['total_messages']} сообщений\n"
        performance_text += f"• Обработано всего: {performance_info['processed_messages_total']} сообщений\n"
        performance_text += f"• Пересылка: {'активна' if performance_info['forwarding_active'] else 'не активна'}\n"
        performance_text += f"• Готовность: {'да' if performance_info['is_ready'] else 'нет'}\n"
        performance_text += f"• Чатов в базе: {performance_info['total_chats']}\n"
    else:
        performance_text += "• Не удалось получить информацию о производительности\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(performance_text, reply_markup=reply_markup)

async def main_menu_handler(query, user_id):
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("🔐 Авторизация", callback_data="auth")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    
    # Если пользователь авторизован, показываем админ-панель
    if is_user_authorized(user_id):
        keyboard.insert(0, [InlineKeyboardButton("👑 Админ панель", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🤖 Главное меню\nВыберите действие:",
        reply_markup=reply_markup
    )

async def admin_menu_handler(query, user_id):
    """Админ панель"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    keyboard = [
        [InlineKeyboardButton("🚀 Запустить пересылку", callback_data="start_forwarding")],
        [InlineKeyboardButton("⏹️ Остановить пересылку", callback_data="stop_forwarding")],
        [InlineKeyboardButton("💬 Управление чатами", callback_data="list_chats")],
        [InlineKeyboardButton("📊 Статус", callback_data="status")],
        [InlineKeyboardButton("🚀 Производительность", callback_data="performance")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="logout")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
    ]
    
    # Если пересылка запущена, но пользователь еще не вошел
    if forwarder.forwarding_active and not forwarder.is_ready:
        keyboard.insert(1, [InlineKeyboardButton("✅ Я вошел в MAX", callback_data="im_ready")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👑 Админ панель\nВыберите действие:",
        reply_markup=reply_markup
    )

async def start_forwarding_handler(query, user_id):
    """Запуск пересылки"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    if not bot_settings.settings.get("selected_chat_id"):
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Сначала выберите чат для отправки!", reply_markup=reply_markup)
        return
    
    if forwarder.forwarding_active:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("ℹ️ Пересылка уже запущена!", reply_markup=reply_markup)
        return
    
    # Запускаем пересылку в отдельном потоке
    threading.Thread(target=forwarder.start_forwarding_process, daemon=True).start()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🚀 Запускаю пересылку...\n\n"
        "1. Браузер откроется автоматически\n"
        "2. Войдите в MAX вручную\n"
        "3. Нажмите кнопку '✅ Я вошел в MAX'\n\n"
        "После этого начнется пересылка сообщений.",
        reply_markup=reply_markup
    )

async def stop_forwarding_handler(query, user_id):
    """Остановка пересылки"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    if not forwarder.forwarding_active:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("ℹ️ Пересылка не активна!", reply_markup=reply_markup)
        return
    
    forwarder.stop_forwarding()
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("🛑 Пересылка остановлена!", reply_markup=reply_markup)

async def list_chats_handler(query, user_id):
    """Список чатов"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    if not bot_settings.telegram_chats:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Чаты не добавлены!", reply_markup=reply_markup)
        return
    
    keyboard = []
    for chat_id, chat_name in bot_settings.telegram_chats.items():
        keyboard.append([InlineKeyboardButton(f"💬 {chat_name}", callback_data=f"chat_{chat_id}")])
    
    keyboard.append([InlineKeyboardButton("➕ Добавить текущий чат", callback_data="add_chat")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "💬 Список чатов:\nВыберите чат для отправки сообщений:",
        reply_markup=reply_markup
    )

async def add_chat_handler(query, user_id):
    """Добавление чата"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    chat_id = query.message.chat_id
    chat_title = query.message.chat.title or "Личные сообщения"
    
    bot_settings.telegram_chats[str(chat_id)] = chat_title
    bot_settings.save_telegram_chats()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="list_chats")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(f"✅ Чат '{chat_title}' добавлен!", reply_markup=reply_markup)

async def select_chat_handler(query, user_id):
    """Выбор чата"""
    await list_chats_handler(query, user_id)

async def im_ready_handler(query, user_id):
    """Подтверждение входа в MAX"""
    if not is_user_authorized(user_id):
        await query.edit_message_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    if not forwarder.forwarding_active:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("❌ Пересылка не запущена!", reply_markup=reply_markup)
        return
    
    forwarder.is_ready = True
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("✅ Отлично! Начинаю пересылку сообщений...", reply_markup=reply_markup)

async def chat_selection_handler(query, data):
    """Обработчик выбора чата"""
    chat_id = data.split("_")[1]
    chat_name = bot_settings.telegram_chats.get(chat_id, "Неизвестно")
    
    bot_settings.settings["selected_chat_id"] = chat_id
    bot_settings.save_settings()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="list_chats")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(f"✅ Выбран чат: {chat_name}", reply_markup=reply_markup)

async def password_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /password"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text("❌ Используйте: /password <ваш_пароль>")
        return
    
    password = context.args[0]
    if password == ADMIN_PASSWORD:
        # Авторизуем пользователя (сессия на 1 час)
        user_sessions[user_id] = datetime.now()
        
        # Устанавливаем постоянного администратора (только если не установлен)
        if not bot_settings.settings.get("admin_chat_id"):
            bot_settings.settings["admin_chat_id"] = update.message.chat_id
            bot_settings.save_settings()
        
        # Добавляем текущий чат в список
        chat_id = update.message.chat_id
        chat_title = update.message.chat.title or "Личные сообщения"
        bot_settings.telegram_chats[str(chat_id)] = chat_title
        bot_settings.save_telegram_chats()
        
        await update.message.reply_text("✅ Авторизация успешна! Доступ к админ панели открыт на 1 час.")
        
        # Показываем админ панель
        keyboard = [
            [InlineKeyboardButton("👑 Админ панель", callback_data="admin_menu")],
            [InlineKeyboardButton("📊 Статус", callback_data="status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("❌ Неверный пароль!")

async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /logout"""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        del user_sessions[user_id]
        await update.message.reply_text("✅ Вы вышли из системы. Для доступа к админ-панели потребуется снова ввести пароль.")
    else:
        await update.message.reply_text("ℹ️ Вы не авторизованы.")

async def addchat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /addchat"""
    user_id = update.effective_user.id
    
    if not is_user_authorized(user_id):
        await update.message.reply_text("❌ Доступ запрещен. Требуется авторизация.")
        return
    
    chat_id = update.message.chat_id
    chat_title = update.message.chat.title or "Личные сообщения"
    
    bot_settings.telegram_chats[str(chat_id)] = chat_title
    bot_settings.save_telegram_chats()
    
    await update.message.reply_text(f"✅ Чат '{chat_title}' добавлен в список!")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /status"""
    user_id = update.effective_user.id
    
    status_text = "📊 Статус бота:\n\n"
    
    # Статус авторизации
    if is_user_authorized(user_id):
        status_text += "✅ Вы авторизованы\n"
    else:
        status_text += "❌ Вы не авторизованы\n"
    
    # Статус пересылки
    if forwarder.forwarding_active:
        status_text += "🟢 Пересылка активна\n"
    else:
        status_text += "🔴 Пересылка не активна\n"
    
    # Выбранный чат
    selected_chat = bot_settings.settings.get("selected_chat_id")
    if selected_chat:
        chat_name = bot_settings.telegram_chats.get(str(selected_chat), "Неизвестно")
        status_text += f"📱 Выбранный чат: {chat_name}\n"
    else:
        status_text += "📱 Чат не выбран\n"
    
    await update.message.reply_text(status_text)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    error_msg = f"Ошибка в боте: {context.error}"
    logger.error(error_msg)
    
    # Сохраняем ошибку в настройках
    bot_settings.settings["last_error"] = f"{datetime.now()}: {error_msg}"
    bot_settings.save_settings()
    
    # Отправляем админу
    forwarder.send_admin_message(f"❌ {error_msg}")

def main():
    """Основная функция"""
    # Проверяем зависимости
    try:
        import psutil
        logger.info("Библиотека psutil доступна")
    except ImportError as e:
        logger.warning(f"Библиотека psutil не установлена: {e}")
        print("⚠️  Для полной функциональности установите: pip install psutil")
    
    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    forwarder.application = application
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("password", password_command))
    application.add_handler(CommandHandler("logout", logout_command))
    application.add_handler(CommandHandler("addchat", addchat_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("Бот запущен")
    print("🤖 Бот запущен! Используйте /start в Telegram")
    print("🔐 Безопасность: доступ к админ-панели только по паролю с сессией 1 час")
    print("🚪 Команда /logout для выхода из системы")
    
    application.run_polling()

if __name__ == "__main__":
    main()
