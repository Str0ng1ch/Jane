import json
import logging
import os
import re
import aiohttp
import asyncio
import psutil
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

import requests
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    FSInputFile,
    CallbackQuery,
)
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5001")

# Пути к данным
DATA_DIR = os.getenv("DATA_DIR", "./data")
USAGE_DIR = os.path.join(DATA_DIR, "usage")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
WORKS_DIR = os.path.join(DATA_DIR, "works")
FEEDBACK_DIR = os.path.join(DATA_DIR, "feedback")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")

os.makedirs(USAGE_DIR, exist_ok=True)
os.makedirs(WORKS_DIR, exist_ok=True)
os.makedirs(FEEDBACK_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Константы для кнопок
BTN_CHECK_ESSAY = "📝 Проверить задание"
BTN_CHECK_NIR = "📚 Проверить НИР"
BTN_TEACHER_HELP = "👩‍🏫 Помощь преподавателю"
BTN_ASK_QUESTION = "❓ Задать вопрос"
BTN_END_DIALOG = "🔚 Завершить диалог"
BTN_RATE_BOT = "⭐ Оценить работу бота"
BTN_CANCEL = "❌ Отменить"
BTN_SKIP = "Пропустить"
BTN_BACK = "◀️ Назад"

# Админские кнопки
BTN_ADMIN_PANEL = "⚙️ Админ-панель"
BTN_TEACHER_PANEL = "👨‍🏫 Преподавательская панель"
BTN_ADMIN_ADD_TEACHER = "👨‍🏫 Добавить преподавателя"
BTN_ADMIN_ADD_ADMIN = "👑 Добавить администратора"
BTN_ADMIN_VIEW_FEEDBACKS = "📊 Оценки пользователей"
BTN_ADMIN_VIEW_STATS = "📈 Статистика"
BTN_ADMIN_VIEW_WORKS = "📚 Просмотр работ"
BTN_ADMIN_MONITORING = "🖥 Мониторинг систем"
BTN_ADMIN_BACK = "⬅️ Назад в панель"

# Новые кнопки для удобства
BTN_SEND = "📤 Отправить"
BTN_CONTINUE = "➡️ Продолжить"
BTN_YES = "✅ Да"
BTN_NO = "❌ Нет"

# Лимиты
MAX_DIALOG_QUESTIONS = 3
DAILY_LIMITS = {
    "essay": 3,
    "nir": 3,
    "teacher": 10,
}


# Состояния FSM
class Form(StatesGroup):
    MAIN_MENU = State()
    WAITING_ASSIGNMENT = State()
    WAITING_ESSAY = State()
    WAITING_NIR = State()
    WAITING_NIR_QUERY = State()
    IN_DIALOG = State()
    WAITING_RATING = State()
    WAITING_COMMENT = State()
    WAITING_TEACHER_PLAN = State()
    WAITING_TEACHER_QUERY = State()
    IN_TEACHER_DIALOG = State()

    # Админские состояния
    ADMIN_PANEL = State()
    TEACHER_PANEL = State()
    ADMIN_ADD_TEACHER = State()
    ADMIN_ADD_ADMIN = State()
    ADMIN_VIEW_WORKS = State()
    ADMIN_VIEW_WORKS_DOWNLOAD = State()


# Глобальные переменные
USER_DATA: Dict[int, Dict[str, Any]] = {}

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)


# ========== Утилиты для работы с пользователями ==========
class UserRole(Enum):
    USER = "user"
    TEACHER = "teacher"
    ADMIN = "admin"


def load_users() -> Dict[str, List[int]]:
    """Загружает пользователей из файла."""
    if not os.path.exists(USERS_FILE):
        default_users = {"admins": [1], "teachers": []}
        save_users(default_users)
        return default_users

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"admins": [], "teachers": []}


def save_users(users_data: Dict[str, List[int]]):
    """Сохраняет пользователей в файл."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, ensure_ascii=False, indent=2)


def get_user_role(user_id: int) -> UserRole:
    """Возвращает роль пользователя."""
    users_data = load_users()

    if user_id in users_data.get("admins", []):
        return UserRole.ADMIN
    elif user_id in users_data.get("teachers", []):
        return UserRole.TEACHER
    else:
        return UserRole.USER


def add_user_role(user_id: int, role: UserRole):
    """Добавляет роль пользователю."""
    users_data = load_users()

    if role == UserRole.ADMIN:
        if user_id not in users_data["admins"]:
            users_data["admins"].append(user_id)
            if user_id in users_data.get("teachers", []):
                users_data["teachers"].remove(user_id)
    elif role == UserRole.TEACHER:
        if user_id not in users_data["teachers"]:
            users_data["teachers"].append(user_id)

    save_users(users_data)


# ========== Утилиты для работы с данными ==========
def split_text_for_telegram(text: str, max_len: int = 4096) -> List[str]:
    """Разбивает текст на части для отправки в Telegram."""
    parts = []
    remaining = text or ""
    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break
        window = remaining[:max_len]
        para_pos = window.rfind("\n\n")
        if para_pos != -1:
            split_at = para_pos
            chunk = remaining[:split_at].rstrip()
            j = split_at
            while j < len(remaining) and remaining[j] == "\n":
                j += 1
            remaining = remaining[j:]
            if chunk:
                parts.append(chunk)
            continue
        last_ws = max(window.rfind("\n"), window.rfind(" "), window.rfind("\t"))
        if last_ws <= 0:
            last_ws = max_len
        chunk = remaining[:last_ws].rstrip()
        remaining = remaining[last_ws:].lstrip()
        if chunk:
            parts.append(chunk)
    return parts


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _usage_file_path(user_id: int) -> str:
    os.makedirs(USAGE_DIR, exist_ok=True)
    return os.path.join(USAGE_DIR, f"{user_id}.json")


def has_daily_quota(user_id: int, work_type: str = "essay") -> bool:
    """Проверяет дневной лимит использования."""
    path = _usage_file_path(user_id)
    limit = DAILY_LIMITS.get(work_type, 3)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("date") != _today_str():
            return True

        counts = data.get("counts", {})
        if int(counts.get(work_type, 0)) >= limit:
            return False
        return True
    except Exception:
        return True


def record_daily_use(user_id: int, work_type: str = "essay") -> None:
    """Записывает использование для конкретного сценария."""
    path = _usage_file_path(user_id)
    try:
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            pass

        if data.get("date") != _today_str():
            data = {"date": _today_str(), "counts": {}}

        if "counts" not in data:
            data["counts"] = {}

        current_count = int(data["counts"].get(work_type, 0))
        data["counts"][work_type] = current_count + 1

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to persist usage for user {user_id}: {e}")


def save_work_file(
        user_id: int, file_bytes: bytes, file_name: str, work_type: str
) -> str:
    """Сохраняет файл работы на диск."""
    user_dir = os.path.join(WORKS_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\.\-]", "_", file_name)
    save_name = f"{timestamp}_{work_type}_{safe_name}"
    save_path = os.path.join(user_dir, save_name)

    with open(save_path, "wb") as f:
        f.write(file_bytes)

    meta_path = os.path.join(user_dir, f"{save_name}.meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "user_id": user_id,
                "original_name": file_name,
                "save_name": save_name,
                "work_type": work_type,
                "timestamp": timestamp,
                "date": _today_str(),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return save_path


def get_user_works(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Получает список работ пользователя или все работы."""
    works = []

    if user_id:
        user_dir = os.path.join(WORKS_DIR, str(user_id))
        if not os.path.exists(user_dir):
            return []

        for file in os.listdir(user_dir):
            if file.endswith(".meta.json"):
                meta_path = os.path.join(user_dir, file)
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        meta["file_path"] = os.path.join(
                            user_dir, file.replace(".meta.json", "")
                        )
                        works.append(meta)
                except:
                    continue
    else:
        for user_folder in os.listdir(WORKS_DIR):
            user_dir = os.path.join(WORKS_DIR, user_folder)
            if not os.path.isdir(user_dir):
                continue

            for file in os.listdir(user_dir):
                if file.endswith(".meta.json"):
                    meta_path = os.path.join(user_dir, file)
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            meta["file_path"] = os.path.join(
                                user_dir, file.replace(".meta.json", "")
                            )
                            works.append(meta)
                    except:
                        continue

    return sorted(works, key=lambda x: x.get("timestamp", ""), reverse=True)


def get_feedbacks() -> List[Dict[str, Any]]:
    """Получает все отзывы пользователей."""
    feedbacks = []

    for file in os.listdir(FEEDBACK_DIR):
        if file.endswith(".json"):
            file_path = os.path.join(FEEDBACK_DIR, file)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    feedback = json.load(f)
                    feedbacks.append(feedback)
            except:
                continue

    return feedbacks


def get_usage_stats() -> Dict[str, Any]:
    """Получает статистику использования."""
    total_users = set()
    today_users = set()
    total_uses = 0

    for file in os.listdir(USAGE_DIR):
        if file.endswith(".json"):
            user_id = file.replace(".json", "")
            try:
                user_id_int = int(user_id)
                total_users.add(user_id_int)

                file_path = os.path.join(USAGE_DIR, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                    if data.get("date") == _today_str():
                        today_users.add(user_id_int)

                    for count in data.get("counts", {}).values():
                        total_uses += int(count)
            except:
                continue

    return {
        "total_users": len(total_users),
        "today_users": len(today_users),
        "total_uses": total_uses,
    }


def md_bold_to_html(s: str) -> str:
    """Преобразует **bold** в HTML <b>bold</b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)


# ========== Функции мониторинга ==========
async def check_backend_health() -> Tuple[bool, str]:
    """Проверяет доступность бэкенда."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BACKEND_URL}/health", timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "ok":
                        return True, "✅ Бэкенд доступен и работает"
                    else:
                        return False, "⚠️ Бэкенд доступен, но не работает корректно"
                else:
                    return False, f"❌ Бэкенд недоступен (статус: {response.status})"
    except aiohttp.ClientConnectorError:
        return False, "❌ Не удалось подключиться к бэкенду"
    except asyncio.TimeoutError:
        return False, "❌ Таймаут при подключении к бэкенду"
    except Exception as e:
        return False, f"❌ Ошибка подключения к бэкенду: {str(e)}"


async def check_yandex_api() -> Tuple[bool, str]:
    """Проверяет доступность API Yandex."""
    yandex_api_key = os.getenv("YC_API_KEY")
    yandex_folder_id = os.getenv("YC_FOLDER_ID")

    if not yandex_api_key:
        return False, "❌ API Yandex не настроено (отсутствует YC_API_KEY)"

    if not yandex_folder_id:
        return False, "⚠️ API Yandex настроено частично (отсутствует YC_FOLDER_ID)"

    return True, "✅ API Yandex настроено"


async def check_database() -> Tuple[bool, str]:
    """Проверяет доступность базы данных."""
    try:
        qdrant_path = os.getenv("QDRANT_PATH", os.path.join(DATA_DIR, "qdrant_local"))

        if not os.path.exists(qdrant_path):
            return False, "❌ Локальная база данных Qdrant не найдена"

        return True, "✅ Локальная база данных Qdrant доступна"
    except Exception as e:
        return False, f"❌ Ошибка проверки базы данных: {str(e)}"


async def check_storage() -> Tuple[bool, str]:
    """Проверяет доступность хранилища данных."""
    try:
        required_dirs = [DATA_DIR, USAGE_DIR, FEEDBACK_DIR, UPLOADS_DIR, WORKS_DIR]
        missing_dirs = []

        for dir_path in required_dirs:
            if not os.path.exists(dir_path):
                missing_dirs.append(dir_path)
                try:
                    os.makedirs(dir_path, exist_ok=True)
                    missing_dirs.remove(dir_path)
                except:
                    pass

        if missing_dirs:
            return False, f"❌ Отсутствуют директории: {', '.join(missing_dirs)}"

        return True, "✅ Хранилище данных доступно"
    except Exception as e:
        return False, f"❌ Ошибка проверки хранилища: {str(e)}"


async def check_system_resources() -> Tuple[bool, str]:
    """Проверяет системные ресурсы."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        disk = psutil.disk_usage("/")
        disk_percent = disk.percent

        status = "✅"
        if cpu_percent > 90:
            status = "⚠️"
        if memory_percent > 90:
            status = "⚠️"
        if disk_percent > 90:
            status = "⚠️"

        return (
            True,
            f"{status} Системные ресурсы: CPU: {cpu_percent}%, RAM: {memory_percent}%, Disk: {disk_percent}%",
        )
    except ImportError:
        return False, "❌ Не удалось проверить системные ресурсы (требуется psutil)"
    except Exception as e:
        return False, f"❌ Ошибка проверки ресурсов: {str(e)}"


# ========== Клавиатуры ==========
def get_main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Главное меню с учетом роли пользователя."""
    user_role = get_user_role(user_id)

    keyboard = [
        [KeyboardButton(text=BTN_CHECK_ESSAY), KeyboardButton(text=BTN_CHECK_NIR)],
        [KeyboardButton(text=BTN_RATE_BOT)],
    ]

    if user_role in [UserRole.TEACHER, UserRole.ADMIN]:
        keyboard.append([KeyboardButton(text=BTN_TEACHER_HELP)])

    if user_role == UserRole.ADMIN:
        keyboard.append([KeyboardButton(text=BTN_ADMIN_PANEL)])
    elif user_role == UserRole.TEACHER:
        keyboard.append([KeyboardButton(text=BTN_TEACHER_PANEL)])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_dialog_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для диалога - только завершение."""
    keyboard = [
        [KeyboardButton(text=BTN_END_DIALOG)],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=BTN_ADMIN_ADD_TEACHER)],
        [KeyboardButton(text=BTN_ADMIN_ADD_ADMIN)],
        [KeyboardButton(text=BTN_ADMIN_VIEW_FEEDBACKS)],
        [KeyboardButton(text=BTN_ADMIN_VIEW_STATS)],
        [KeyboardButton(text=BTN_ADMIN_VIEW_WORKS)],
        [KeyboardButton(text=BTN_ADMIN_MONITORING)],
        [KeyboardButton(text=BTN_ADMIN_BACK)],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_teacher_keyboard(user_role: UserRole) -> ReplyKeyboardMarkup:
    keyboard = []

    if user_role == UserRole.ADMIN:
        keyboard.append([KeyboardButton(text=BTN_ADMIN_ADD_TEACHER)])
        keyboard.append([KeyboardButton(text=BTN_ADMIN_ADD_ADMIN)])

    keyboard.extend(
        [
            [KeyboardButton(text=BTN_ADMIN_VIEW_FEEDBACKS)],
            [KeyboardButton(text=BTN_ADMIN_VIEW_STATS)],
            [KeyboardButton(text=BTN_ADMIN_VIEW_WORKS)],
            [KeyboardButton(text=BTN_ADMIN_BACK)],
        ]
    )

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=BTN_CANCEL)]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_skip_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=BTN_SKIP)], [KeyboardButton(text=BTN_CANCEL)]]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_rating_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="1"),
            KeyboardButton(text="2"),
            KeyboardButton(text="3"),
            KeyboardButton(text="4"),
            KeyboardButton(text="5"),
        ],
        [KeyboardButton(text=BTN_CANCEL)],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_works_list_keyboard(
        works: List[Dict[str, Any]], page: int = 0, works_per_page: int = 5
) -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру для списка работ."""
    builder = InlineKeyboardBuilder()

    start_idx = page * works_per_page
    end_idx = min(start_idx + works_per_page, len(works))

    for i in range(start_idx, end_idx):
        work = works[i]
        work_type = work.get("work_type", "неизвестно")
        original_name = work.get("original_name", "без имени")
        date = work.get("date", "неизвестно")

        display_name = (
            original_name[:30] + "..." if len(original_name) > 30 else original_name
        )
        button_text = f"{i + 1}. {work_type} - {display_name}"

        # Используем только индекс в callback_data
        builder.button(text=button_text, callback_data=f"download:{i}")

    # Кнопки навигации
    if page > 0:
        builder.button(text="⬅️ Назад", callback_data=f"page:{page - 1}")

    if end_idx < len(works):
        builder.button(text="Вперед ➡️", callback_data=f"page:{page + 1}")

    builder.button(text="🔙 Назад в админ-панель", callback_data="back_to_admin")

    builder.adjust(1)
    return builder.as_markup()


# ========== Обработчики команд ==========
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = message.from_user
    USER_DATA[user.id] = {"username": user.username, "first_name": user.first_name}

    welcome_text = """
Приветствую, дорогой урбанист! 🏙

Я - Джейн, AI-ассистент в мире городских исследований. Я помогу улучшить ваши работы, предоставляя конструктивные рекомендации на основе академических источников.

<b>Что я умею:</b>
• 📝 Проверять задания с обратной связью
• 📚 Анализировать НИР (научно-исследовательские работы)
• 💬 Вести диалог для уточнения рекомендаций

<b>Как начать:</b>
1️⃣ Выберите тип работы (Задание или НИР)
2️⃣ Загрузите задание от преподавателя
3️⃣ Отправьте свою работу и получите рекомендации
4️⃣ Задавайте вопросы для уточнения

⚠️ Лимит: не более 3 проверок в день (для каждого типа работы)
Чтобы перезагрузить меню, напишите /start
"""

    await message.answer(
        welcome_text,
        reply_markup=get_main_menu_keyboard(user.id),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.MAIN_MENU)


@router.message(Command("assist"))
async def cmd_assist(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_role = get_user_role(user_id)

    if user_role not in [UserRole.TEACHER, UserRole.ADMIN]:
        await message.answer(
            "⚠️ Эта функция доступна только преподавателям и администраторам.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    if not has_daily_quota(user_id, work_type="teacher"):
        await message.answer(
            "⚠️ Лимит запросов для преподавателя: не более 10 в день. Попробуйте завтра.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await state.update_data(work_type="teacher", work_type_name="помощь преподавателю")

    await message.answer(
        "👩‍🏫 <b>Помощь преподавателю</b>\n\n"
        "📋 <b>Шаг 1 из 2: План урока</b> (опционально)\n\n"
        "Отправьте файл с планом урока (.txt или .docx), "
        "чтобы я могла дать более точные рекомендации.\n\n"
        "Или нажмите <b>Пропустить</b>, чтобы сразу задать вопрос.",
        reply_markup=get_skip_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.WAITING_TEACHER_PLAN)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await cancel_operation(message, state)


# ========== Основные обработчики меню ==========
@router.message(Form.MAIN_MENU, F.text == BTN_CHECK_ESSAY)
async def handle_check_essay(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not has_daily_quota(user_id, work_type="essay"):
        await message.answer(
            "⚠️ Лимит проверок заданий: не более 3 в день. Попробуйте завтра.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await state.update_data(work_type="essay", work_type_name="задание")

    await message.answer(
        "📋 <b>Шаг 1 из 2: Задание от преподавателя</b>\n\n"
        "Отправьте файл с заданием (.txt или .docx)\n\n"
        "<i>Это поможет оценить вашу работу по критериям преподавателя.</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.WAITING_ASSIGNMENT)


@router.message(Form.MAIN_MENU, F.text == BTN_CHECK_NIR)
async def handle_check_nir(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not has_daily_quota(user_id, work_type="nir"):
        await message.answer(
            "⚠️ Лимит проверок НИР: не более 3 в день. Попробуйте завтра.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await state.update_data(work_type="nir", work_type_name="НИР")

    await message.answer(
        "📤 <b>Отправьте вашу НИР</b>\n\nПоддерживаемые форматы: .txt, .docx",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.WAITING_NIR)


@router.message(Form.MAIN_MENU, F.text == BTN_TEACHER_HELP)
async def handle_teacher_help(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_role = get_user_role(user_id)

    if user_role not in [UserRole.TEACHER, UserRole.ADMIN]:
        await message.answer(
            "⚠️ Эта функция доступна только преподавателям и администраторам.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    if not has_daily_quota(user_id, work_type="teacher"):
        await message.answer(
            "⚠️ Лимит запросов для преподавателя: не более 10 в день. Попробуйте завтра.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await state.update_data(work_type="teacher", work_type_name="помощь преподавателю")

    await message.answer(
        "👩‍🏫 <b>Помощь преподавателю</b>\n\n"
        "📋 <b>Шаг 1 из 2: План урока</b> (опционально)\n\n"
        "Отправьте файл с планом урока (.txt или .docx), "
        "чтобы я могла дать более точные рекомендации.\n\n"
        "Или нажмите <b>Пропустить</b>, чтобы сразу задать вопрос.",
        reply_markup=get_skip_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.WAITING_TEACHER_PLAN)


@router.message(Form.MAIN_MENU, F.text == BTN_RATE_BOT)
async def handle_rate_bot(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, оцените мою работу по шкале от 1 до 5:",
        reply_markup=get_rating_keyboard(),
    )
    await state.set_state(Form.WAITING_RATING)


@router.message(Form.MAIN_MENU, F.text == BTN_ADMIN_PANEL)
async def handle_admin_panel(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_role = get_user_role(user_id)

    if user_role != UserRole.ADMIN:
        await message.answer(
            "⚠️ У вас нет прав для доступа к админ-панели.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.ADMIN_PANEL)


@router.message(Form.MAIN_MENU, F.text == BTN_TEACHER_PANEL)
async def handle_teacher_panel(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_role = get_user_role(user_id)

    if user_role not in [UserRole.TEACHER, UserRole.ADMIN]:
        await message.answer(
            "⚠️ У вас нет прав для доступа к преподавательской панели.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        return

    await message.answer(
        "👨‍🏫 <b>Преподавательская панель</b>\n\nВыберите действие:",
        reply_markup=get_teacher_keyboard(user_role),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.TEACHER_PANEL)


# ========== Обработчики оценки бота ==========
@router.message(Form.WAITING_RATING, F.text.in_(["1", "2", "3", "4", "5"]))
async def handle_rating_selected(message: Message, state: FSMContext):
    rating = message.text
    user_id = message.from_user.id

    await state.update_data(rating=rating)

    await message.answer(
        f"Спасибо за оценку {rating}⭐! Теперь напишите ваш комментарий или нажмите 'Пропустить':",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_SKIP)]], resize_keyboard=True
        ),
    )
    await state.set_state(Form.WAITING_COMMENT)


@router.message(Form.WAITING_RATING)
async def handle_invalid_rating(message: Message):
    await message.answer(
        "Пожалуйста, выберите оценку от 1 до 5 с помощью кнопок:",
        reply_markup=get_rating_keyboard(),
    )


@router.message(Form.WAITING_COMMENT)
async def handle_comment(message: Message, state: FSMContext):
    user_id = message.from_user.id
    comment = message.text

    data = await state.get_data()
    rating = data.get("rating", "")

    feedback_dir = FEEDBACK_DIR
    os.makedirs(feedback_dir, exist_ok=True)

    feedback_data = {
        "user_id": user_id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "rating": rating,
        "comment": comment if comment != BTN_SKIP else "",
        "date": _today_str(),
        "timestamp": datetime.now().isoformat(),
    }

    feedback_file = os.path.join(
        feedback_dir, f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(feedback_file, "w", encoding="utf-8") as f:
        json.dump(feedback_data, f, ensure_ascii=False, indent=2)

    try:
        response = requests.post(
            f"{BACKEND_URL}/feedback", json=feedback_data, timeout=10
        )
    except:
        pass

    if comment == BTN_SKIP:
        await message.answer(
            "✅ Спасибо за вашу оценку! Она поможет мне стать лучше.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
    else:
        await message.answer(
            "✅ Спасибо за ваш отзыв! Он поможет мне стать лучше.",
            reply_markup=get_main_menu_keyboard(user_id),
        )

    await state.set_state(Form.MAIN_MENU)


# ========== Обработчики админ-панели ==========
@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_ADD_TEACHER)
async def admin_add_teacher(message: Message, state: FSMContext):
    await message.answer(
        "👨‍🏫 <b>Добавление преподавателя</b>\n\n"
        "Отправьте ID пользователя, которого хотите сделать преподавателем.\n\n"
        "<i>ID можно получить с помощью бота @userinfobot</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.ADMIN_ADD_TEACHER)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_ADD_ADMIN)
async def admin_add_admin(message: Message, state: FSMContext):
    await message.answer(
        "👑 <b>Добавление администратора</b>\n\n"
        "Отправьте ID пользователя, которого хотите сделать администратором.\n\n"
        "<i>ID можно получить с помощью бота @userinfobot</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.ADMIN_ADD_ADMIN)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_VIEW_FEEDBACKS)
async def admin_view_feedbacks(message: Message, state: FSMContext):
    feedbacks = get_feedbacks()

    if not feedbacks:
        await message.answer("📊 Нет доступных отзывов.")
        return

    total_rating = 0
    rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    feedback_text = "📊 <b>Оценки пользователей:</b>\n\n"

    for i, feedback in enumerate(feedbacks[:20], 1):
        user_id = feedback.get("user_id", "Неизвестно")
        username = feedback.get("username", "")
        first_name = feedback.get("first_name", "")
        rating = feedback.get("rating", "Нет")
        comment = feedback.get("comment", "")
        date = feedback.get("date", "")

        if rating and rating.isdigit():
            rating_int = int(rating)
            total_rating += rating_int
            rating_counts[rating_int] = rating_counts.get(rating_int, 0) + 1

        user_display = (
            f"{first_name} (@{username})" if username else f"Пользователь {user_id}"
        )
        feedback_text += f"<b>{i}. {user_display}</b> ({date})\n"
        feedback_text += f"   ⭐ Оценка: {rating}/5\n"
        if comment:
            feedback_text += f"   💬 Комментарий: {comment}\n"
        feedback_text += "\n"

    avg_rating = total_rating / len(feedbacks) if feedbacks else 0

    feedback_text += "\n<b>Статистика:</b>\n"
    feedback_text += f"• Всего отзывов: {len(feedbacks)}\n"
    feedback_text += f"• Средняя оценка: {avg_rating:.2f}/5\n"
    for rating in range(1, 6):
        count = rating_counts.get(rating, 0)
        percentage = (count / len(feedbacks)) * 100 if feedbacks else 0
        feedback_text += f"• {rating} звезд: {count} ({percentage:.1f}%)\n"

    await message.answer(feedback_text, parse_mode=ParseMode.HTML)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_VIEW_STATS)
async def admin_view_stats(message: Message, state: FSMContext):
    stats = get_usage_stats()
    users_data = load_users()

    stats_text = "📈 <b>Статистика бота:</b>\n\n"
    stats_text += f"• Всего пользователей: {stats['total_users']}\n"
    stats_text += f"• Активных сегодня: {stats['today_users']}\n"
    stats_text += f"• Всего использований: {stats['total_uses']}\n\n"

    stats_text += "<b>Пользователи по ролям:</b>\n"
    stats_text += f"• Администраторов: {len(users_data.get('admins', []))}\n"
    stats_text += f"• Преподавателей: {len(users_data.get('teachers', []))}\n"

    all_works = get_user_works()
    essay_count = len([w for w in all_works if w.get("work_type") == "essay"])
    nir_count = len([w for w in all_works if w.get("work_type") == "nir"])
    assignment_count = len([w for w in all_works if w.get("work_type") == "assignment"])

    stats_text += "\n<b>Загруженные работы:</b>\n"
    stats_text += f"• Всего работ: {len(all_works)}\n"
    stats_text += f"• Заданий от преподавателей: {assignment_count}\n"
    stats_text += f"• Проверенных заданий: {essay_count}\n"
    stats_text += f"• НИР: {nir_count}\n"

    await message.answer(stats_text, parse_mode=ParseMode.HTML)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_VIEW_WORKS)
async def admin_view_works(message: Message, state: FSMContext):
    await message.answer(
        "📚 <b>Просмотр работ</b>\n\n"
        "Отправьте ID пользователя для просмотра его работ\n"
        "или отправьте 'all' для просмотра всех работ.",
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(Form.ADMIN_VIEW_WORKS)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_MONITORING)
async def admin_monitoring(message: Message, state: FSMContext):
    await message.answer("🖥 <b>Проверяю системы...</b>", parse_mode=ParseMode.HTML)

    monitoring_text = "🖥 <b>Мониторинг систем:</b>\n\n"

    backend_status, backend_msg = await check_backend_health()
    monitoring_text += f"{backend_msg}\n\n"

    yandex_status, yandex_msg = await check_yandex_api()
    monitoring_text += f"{yandex_msg}\n\n"

    db_status, db_msg = await check_database()
    monitoring_text += f"{db_msg}\n\n"

    storage_status, storage_msg = await check_storage()
    monitoring_text += f"{storage_msg}\n\n"

    resources_status, resources_msg = await check_system_resources()
    monitoring_text += f"{resources_msg}\n\n"

    all_ok = all(
        [backend_status, yandex_status, db_status, storage_status, resources_status]
    )
    if all_ok:
        monitoring_text += "✅ <b>Все системы работают нормально.</b>"
    else:
        monitoring_text += "⚠️ <b>Есть проблемы в работе систем.</b>"

    await message.answer(monitoring_text, parse_mode=ParseMode.HTML)


@router.message(Form.ADMIN_PANEL, F.text == BTN_ADMIN_BACK)
async def admin_back(message: Message, state: FSMContext):
    await message.answer(
        "Главное меню:", reply_markup=get_main_menu_keyboard(message.from_user.id)
    )
    await state.set_state(Form.MAIN_MENU)


# ========== Обработчики просмотра и скачивания работ ==========
@router.message(Form.ADMIN_VIEW_WORKS)
async def process_view_works(message: Message, state: FSMContext):
    if message.text == BTN_CANCEL:
        await message.answer("Админ-панель:", reply_markup=get_admin_keyboard())
        await state.set_state(Form.ADMIN_PANEL)
        return

    user_id = None
    if message.text.lower() != "all":
        try:
            user_id = int(message.text)
        except ValueError:
            await message.answer(
                "❌ Неверный формат. Отправьте числовой ID или 'all'.",
                reply_markup=get_cancel_keyboard(),
            )
            return

    works = get_user_works(user_id)

    if not works:
        await message.answer(
            "📚 Работ не найдено.",
            reply_markup=get_admin_keyboard()
            if user_id is None
            else get_cancel_keyboard(),
        )
        return

    # Сохраняем работы в состоянии
    await state.update_data(works_list=works, works_page=0)

    # Создаем инлайн-клавиатуру
    keyboard = get_works_list_keyboard(works, page=0)

    works_text = f"📚 <b>Найдено работ: {len(works)}</b>\n\n"
    works_text += "<i>Выберите работу для скачивания:</i>"

    await message.answer(works_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await state.set_state(Form.ADMIN_VIEW_WORKS_DOWNLOAD)


@router.callback_query(F.data.startswith("page:"))
async def handle_works_page(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает переключение страниц списка работ."""
    data = callback.data.split(":")
    page = int(data[1])

    data_state = await state.get_data()
    works = data_state.get("works_list", [])

    if not works:
        await callback.answer("Список работ пуст")
        return

    keyboard = get_works_list_keyboard(works, page=page)

    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await state.update_data(works_page=page)
        await callback.answer()
    except Exception as e:
        logger.error(f"Error updating keyboard: {e}")
        await callback.answer("Ошибка при обновлении списка")


@router.callback_query(F.data.startswith("download:"))
async def handle_download_work(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает запрос на скачивание работы."""
    data = callback.data.split(":")
    work_index = int(data[1])

    data_state = await state.get_data()
    works = data_state.get("works_list", [])

    if work_index < 0 or work_index >= len(works):
        await callback.answer("❌ Работа не найдена")
        return

    work = works[work_index]
    file_path = work.get("file_path")
    original_name = work.get("original_name", "работа.txt")

    if not os.path.exists(file_path):
        await callback.answer("❌ Файл не найден на сервере")
        return

    try:
        document = FSInputFile(file_path, filename=original_name)
        await callback.message.answer_document(
            document,
            caption=f"📄 <b>{original_name}</b>\n"
                    f"👤 Пользователь: {work.get('user_id', 'Неизвестно')}\n"
                    f"📝 Тип: {work.get('work_type', 'Неизвестно')}\n"
                    f"📅 Дата: {work.get('date', 'Неизвестно')}",
            parse_mode=ParseMode.HTML,
        )
        await callback.answer("✅ Файл отправлен")
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        await callback.answer("❌ Ошибка при отправке файла")


@router.callback_query(F.data == "back_to_admin")
async def handle_back_to_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Админ-панель:", reply_markup=get_admin_keyboard())
    await state.set_state(Form.ADMIN_PANEL)
    await callback.answer()


# ========== Обработчики преподавательской панели ==========
@router.message(Form.TEACHER_PANEL, F.text == BTN_ADMIN_BACK)
async def teacher_back(message: Message, state: FSMContext):
    await message.answer(
        "Главное меню:", reply_markup=get_main_menu_keyboard(message.from_user.id)
    )
    await state.set_state(Form.MAIN_MENU)


@router.message(Form.TEACHER_PANEL)
async def handle_teacher_panel_actions(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_role = get_user_role(user_id)
    text = message.text

    if text == BTN_ADMIN_ADD_TEACHER and user_role == UserRole.ADMIN:
        await admin_add_teacher(message, state)
    elif text == BTN_ADMIN_ADD_ADMIN and user_role == UserRole.ADMIN:
        await admin_add_admin(message, state)
    elif text == BTN_ADMIN_VIEW_FEEDBACKS:
        await admin_view_feedbacks(message, state)
    elif text == BTN_ADMIN_VIEW_STATS:
        await admin_view_stats(message, state)
    elif text == BTN_ADMIN_VIEW_WORKS:
        await admin_view_works(message, state)
    else:
        await message.answer(
            "Неизвестная команда. Используйте кнопки меню.",
            reply_markup=get_teacher_keyboard(user_role),
        )


# ========== Обработчики добавления пользователей ==========
@router.message(Form.ADMIN_ADD_TEACHER)
async def process_add_teacher(message: Message, state: FSMContext):
    if message.text == BTN_CANCEL:
        await cancel_operation(message, state)
        return

    try:
        teacher_id = int(message.text)
        add_user_role(teacher_id, UserRole.TEACHER)

        await message.answer(
            f"✅ Пользователь {teacher_id} добавлен как преподаватель.",
            reply_markup=get_admin_keyboard(),
        )
        await state.set_state(Form.ADMIN_PANEL)
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Отправьте числовой ID пользователя.",
            reply_markup=get_cancel_keyboard(),
        )


@router.message(Form.ADMIN_ADD_ADMIN)
async def process_add_admin(message: Message, state: FSMContext):
    if message.text == BTN_CANCEL:
        await cancel_operation(message, state)
        return

    try:
        admin_id = int(message.text)
        add_user_role(admin_id, UserRole.ADMIN)

        await message.answer(
            f"✅ Пользователь {admin_id} добавлен как администратор.",
            reply_markup=get_admin_keyboard(),
        )
        await state.set_state(Form.ADMIN_PANEL)
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Отправьте числовой ID пользователя.",
            reply_markup=get_cancel_keyboard(),
        )


# ========== Обработчики документов ==========
@router.message(Form.WAITING_ASSIGNMENT, F.document)
async def handle_assignment_document(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not message.document:
        await message.answer("Пожалуйста, отправьте файл с заданием (.txt или .docx).")
        return

    file_name = message.document.file_name
    if not (file_name.endswith(".txt") or file_name.endswith(".docx")):
        await message.answer(
            "Неверный формат файла. Поддерживаются только .txt и .docx."
        )
        return

    try:
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)

        save_work_file(user_id, file_bytes.read(), file_name, "assignment")
        file_bytes.seek(0)

        files = {"file": (file_name, file_bytes.read())}
        data = {"user_id": str(user_id), "work_type": "essay"}

        response = requests.post(
            f"{BACKEND_URL}/assignment", files=files, data=data, timeout=30
        )

        if response.status_code == 200:
            await message.answer(
                f"✅ Задание получено: <b>{file_name}</b>\n\n"
                "📤 <b>Шаг 2 из 2: Отправьте вашу работу</b>\n\n"
                "Поддерживаемые форматы: .txt, .docx",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await state.set_state(Form.WAITING_ESSAY)
        else:
            await message.answer(
                "❌ Ошибка при сохранении задания. Попробуйте ещё раз."
            )

    except Exception as e:
        logger.error(f"Error uploading assignment: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")


@router.message(Form.WAITING_ESSAY, F.document)
async def handle_essay_document(message: Message, state: FSMContext):
    user_id = message.from_user.id

    file_name = message.document.file_name
    if not (file_name.endswith(".txt") or file_name.endswith(".docx")):
        await message.answer(
            "Неверный формат файла. Поддерживаются только .txt и .docx."
        )
        return

    try:
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)

        save_work_file(user_id, file_bytes.read(), file_name, "essay")
        file_bytes.seek(0)

        files = {"file": (file_name, file_bytes.read())}
        data = {"user_id": str(user_id), "top_k": "5"}

        await message.answer("⏳ Анализирую вашу работу...")

        response = requests.post(
            f"{BACKEND_URL}/analyze/essay", files=files, data=data, timeout=180
        )

        if response.status_code == 200:
            response_data = response.json()
            recommendation = response_data.get("recommendation", "")

            recommendation_html = md_bold_to_html(recommendation)
            parts = split_text_for_telegram(recommendation_html, max_len=4096)

            if parts:
                for part in parts[:-1]:
                    await message.answer(part, parse_mode=ParseMode.HTML)
                await message.answer(
                    parts[-1]
                    + "\n\n✅ Анализ завершён. Вы можете проверить другую работу.",
                    reply_markup=get_main_menu_keyboard(user_id),
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer(
                    "Анализ завершён.", reply_markup=get_main_menu_keyboard(user_id)
                )

            record_daily_use(user_id, work_type="essay")
            await state.set_state(Form.MAIN_MENU)
        else:
            await message.answer("❌ Ошибка при обработке файла. Попробуйте ещё раз.")

    except requests.exceptions.Timeout:
        await message.answer("⏰ Превышено время ожидания. Попробуйте ещё раз.")
    except Exception as e:
        logger.error(f"Error processing essay: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")


# ========== Обработчики для НИР ==========
@router.message(Form.WAITING_NIR, F.document)
async def handle_nir_document(message: Message, state: FSMContext):
    """Обрабатывает загрузку НИР и переходит к запросу."""
    user_id = message.from_user.id

    file_name = message.document.file_name
    if not (file_name.endswith(".txt") or file_name.endswith(".docx")):
        await message.answer(
            "Неверный формат файла. Поддерживаются только .txt и .docx."
        )
        return

    try:
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)
        file_content = file_bytes.read()

        # Сохраняем файл
        save_work_file(user_id, file_content, file_name, "nir")

        # Сохраняем данные в состоянии
        await state.update_data(nir_file_content=file_content, nir_file_name=file_name)

        await message.answer(
            f"✅ Файл <b>{file_name}</b> получен!\n\n"
            "📝 <b>На что обратить внимание?</b>\n\n"
            "Напишите, что именно вы хотите проверить или улучшить.\n\n"
            "<i>Примеры:</i>\n"
            "• Проверь логику аргументации\n"
            "• Какие источники добавить?\n"
            "• Как улучшить введение?\n"
            "• Соответствует ли текст теме?",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        await state.set_state(Form.WAITING_NIR_QUERY)

    except Exception as e:
        logger.error(f"Error receiving NIR file: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")


# ========== Обработчики для НИР ==========
@router.message(Form.WAITING_NIR_QUERY)
async def handle_nir_query(message: Message, state: FSMContext):
    """Обрабатывает запрос пользователя для НИР."""
    text = message.text
    user_id = message.from_user.id

    if text == BTN_CANCEL:
        await cancel_operation(message, state)
        return

    data = await state.get_data()
    file_content = data.get("nir_file_content")
    file_name = data.get("nir_file_name")

    if not file_content or not file_name:
        await message.answer(
            "⚠️ Файл не найден. Пожалуйста, загрузите НИР заново.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        await state.set_state(Form.MAIN_MENU)
        return

    await message.answer(
        f"✅ Запрос: <i>«{text[:100]}{'...' if len(text) > 100 else ''}»</i>\n\n"
        "⏳ Анализирую вашу НИР...",
        parse_mode="HTML",
    )

    try:
        files = {"file": (file_name, file_content)}
        data_payload = {"user_id": str(user_id), "top_k": "5", "user_query": text}

        endpoint = f"{BACKEND_URL}/analyze/nir"
        response = requests.post(endpoint, files=files, data=data_payload, timeout=180)

        if response.status_code == 200:
            try:
                response_data = response.json()
                # Проверяем разные варианты структуры ответа
                if isinstance(response_data, dict):
                    recommendation = response_data.get("recommendation", "")
                elif isinstance(response_data, str):
                    recommendation = response_data
                else:
                    recommendation = str(response_data)

                if not recommendation:
                    await message.answer(
                        "✅ Анализ завершен, но рекомендации не сгенерированы.",
                        reply_markup=get_main_menu_keyboard(user_id),
                    )
                    await state.set_state(Form.MAIN_MENU)
                    return

                # ПРАВИЛЬНО: используем get_dialog_keyboard() напрямую
                reply_markup = get_dialog_keyboard()

                # Преобразуем markdown в HTML
                recommendation_html = md_bold_to_html(recommendation)
                parts = split_text_for_telegram(recommendation_html, max_len=4096)

                if parts:
                    for part in parts[:-1]:
                        await message.answer(part, parse_mode=ParseMode.HTML)
                    await message.answer(
                        parts[-1]
                        + "\n\n💬 Вы можете задать дополнительные вопросы или завершить диалог.",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await message.answer(
                        "✅ Анализ завершен. Вы можете задать вопросы.",
                        reply_markup=reply_markup,
                    )

                record_daily_use(user_id, work_type="nir")

                # Сохраняем данные для диалога
                await state.update_data(
                    dialog_type="nir",
                    session_data={
                        "file_content": file_content,
                        "file_name": file_name,
                        "user_query": text,
                    },
                    dialog_questions_count=0,
                    last_recommendation=recommendation,
                )
                await state.set_state(Form.IN_DIALOG)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response for NIR: {e}")
                await message.answer(
                    "❌ Ошибка при обработке ответа от сервера анализа.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
            except Exception as e:
                logger.error(f"Unexpected error processing NIR response: {e}")
                await message.answer(
                    "❌ Непредвиденная ошибка при обработке ответа.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
        else:
            logger.error(
                f"Backend error for NIR: {response.status_code} - {response.text}"
            )
            await message.answer(
                f"❌ Ошибка при анализе (код {response.status_code}). Попробуйте ещё раз.",
                reply_markup=get_cancel_keyboard(),
            )

    except requests.exceptions.Timeout:
        await message.answer("⏰ Превышено время ожидания. Попробуйте ещё раз.")
    except Exception as e:
        logger.error(f"Error processing NIR: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")


# ========== Обработчики для помощи преподавателю ==========
@router.message(Form.WAITING_TEACHER_PLAN)
async def handle_teacher_plan(message: Message, state: FSMContext):
    """Обрабатывает план урока или пропуск."""
    text = message.text
    user_id = message.from_user.id

    if text == BTN_CANCEL:
        await cancel_operation(message, state)
        return

    if text == BTN_SKIP:
        # Пропускаем план урока
        await state.update_data(teacher_plan_content=None, teacher_plan_name=None)

        await message.answer(
            "📝 <b>Шаг 2 из 2: Ваш запрос</b>\n\n"
            "Напишите, с чем вам нужна помощь:\n\n"
            "<i>Примеры:</i>\n"
            "• Как сделать урок более интерактивным?\n"
            "• Какие техники обратной связи использовать?\n"
            "• Как мотивировать студентов?\n"
            "• Как организовать групповую работу?",
            reply_markup=get_cancel_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        await state.set_state(Form.WAITING_TEACHER_QUERY)
        return

    # Проверяем, загружен ли документ
    if message.document:
        file_name = message.document.file_name
        if not (file_name.endswith(".txt") or file_name.endswith(".docx")):
            await message.answer(
                "Неверный формат файла. Поддерживаются только .txt и .docx."
            )
            return

        try:
            file = await bot.get_file(message.document.file_id)
            file_bytes = await bot.download_file(file.file_path)
            file_content = file_bytes.read()

            await state.update_data(
                teacher_plan_content=file_content, teacher_plan_name=file_name
            )

            await message.answer(
                f"✅ План урока получен: <b>{file_name}</b>\n\n"
                "📝 <b>Шаг 2 из 2: Ваш запрос</b>\n\n"
                "Напишите, с чем вам нужна помощь:\n\n"
                "<i>Примеры:</i>\n"
                "• Как улучшить этот урок?\n"
                "• Какие активности добавить?\n"
                "• Как проверить понимание?",
                reply_markup=get_cancel_keyboard(),
                parse_mode=ParseMode.HTML,
            )
            await state.set_state(Form.WAITING_TEACHER_QUERY)

        except Exception as e:
            logger.error(f"Error receiving teacher plan: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")
    else:
        await message.answer(
            "Пожалуйста, отправьте файл (.txt или .docx) или нажмите 'Пропустить'."
        )


# ========== Обработчики для помощи преподавателю ==========
@router.message(Form.WAITING_TEACHER_QUERY)
async def handle_teacher_query(message: Message, state: FSMContext):
    """Обрабатывает запрос преподавателя."""
    text = message.text
    user_id = message.from_user.id

    if text == BTN_CANCEL:
        await cancel_operation(message, state)
        return

    await state.update_data(teacher_query=text)

    await message.answer(
        f"✅ Запрос: <i>«{text[:100]}{'...' if len(text) > 100 else ''}»</i>\n\n"
        "⏳ Ищу методические рекомендации...",
        parse_mode=ParseMode.HTML,
    )

    try:
        data = await state.get_data()
        plan_content = data.get("teacher_plan_content")
        plan_name = data.get("teacher_plan_name", "plan.txt")

        request_data = {"user_id": str(user_id), "top_k": "5", "user_query": text}

        if plan_content:
            files = {"file": (plan_name, plan_content)}
            response = requests.post(
                f"{BACKEND_URL}/analyze/teacher",
                files=files,
                data=request_data,
                timeout=180,
            )
        else:
            response = requests.post(
                f"{BACKEND_URL}/analyze/teacher", data=request_data, timeout=180
            )

        if response.status_code == 200:
            try:
                response_data = response.json()
                # Проверяем разные варианты структуры ответа
                if isinstance(response_data, dict):
                    recommendation = response_data.get("recommendation", "")
                elif isinstance(response_data, str):
                    recommendation = response_data
                else:
                    recommendation = str(response_data)

                if not recommendation:
                    await message.answer(
                        "✅ Запрос обработан, но рекомендации не сгенерированы.",
                        reply_markup=get_main_menu_keyboard(user_id),
                    )
                    await state.set_state(Form.MAIN_MENU)
                    return

                # ПРАВИЛЬНО: используем get_dialog_keyboard() напрямую
                reply_markup = get_dialog_keyboard()

                # Преобразуем markdown в HTML
                recommendation_html = md_bold_to_html(recommendation)
                parts = split_text_for_telegram(recommendation_html, max_len=4096)

                if parts:
                    for part in parts[:-1]:
                        await message.answer(part, parse_mode=ParseMode.HTML)
                    await message.answer(
                        parts[-1]
                        + "\n\n💬 Вы можете задать дополнительные вопросы или завершить диалог.",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await message.answer(
                        "✅ Готово! Вы можете задать вопросы.",
                        reply_markup=reply_markup,
                    )

                record_daily_use(user_id, work_type="teacher")

                # Сохраняем данные для диалога (БЕЗ создания сессии сразу)
                await state.update_data(
                    dialog_type="teacher",
                    session_data={
                        "plan_content": plan_content,
                        "plan_name": plan_name,
                        "user_query": text,
                    },
                    dialog_questions_count=0,
                    last_recommendation=recommendation,
                    dialog_session_id=None,  # Сессия создается при первом вопросе
                )

                # Используем обновленную клавиатуру диалога (без кнопки "Задать вопрос")
                await message.answer(
                    parts[-1] + "\n\n💬 Вы можете задать дополнительные вопросы или завершить диалог.",
                    reply_markup=get_dialog_keyboard(),  # Теперь только кнопка завершения
                    parse_mode=ParseMode.HTML,
                )

                await state.set_state(Form.IN_TEACHER_DIALOG)

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response for teacher: {e}")
                await message.answer(
                    "❌ Ошибка при обработке ответа от сервера анализа.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
            except Exception as e:
                logger.error(f"Unexpected error processing teacher response: {e}")
                await message.answer(
                    "❌ Непредвиденная ошибка при обработке ответа.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
        else:
            logger.error(
                f"Backend error for teacher: {response.status_code} - {response.text}"
            )
            await message.answer(
                f"❌ Ошибка при обработке (код {response.status_code}). Попробуйте ещё раз.",
                reply_markup=get_cancel_keyboard(),
            )

    except requests.exceptions.Timeout:
        await message.answer("⏰ Превышено время ожидания. Попробуйте ещё раз.")
    except Exception as e:
        logger.error(f"Error processing teacher request: {e}")
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз.")


# ========== Обработчики диалога ==========
@router.message(Form.IN_DIALOG)
async def handle_dialog(message: Message, state: FSMContext):
    """Обрабатывает диалог с пользователем."""
    text = message.text
    user_id = message.from_user.id

    if text == BTN_END_DIALOG:
        await message.answer(
            "✅ Диалог завершен. Спасибо за использование!\n\nЧем еще могу помочь?",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        await state.set_state(Form.MAIN_MENU)
        return

    elif text == BTN_ASK_QUESTION:
        await message.answer("💭 Напишите ваш вопрос, и я постараюсь помочь.")
        return

    else:
        data = await state.get_data()
        questions_count = data.get("dialog_questions_count", 0)
        dialog_type = data.get("dialog_type", "nir")

        if questions_count >= MAX_DIALOG_QUESTIONS:
            await message.answer(
                f"⚠️ Достигнут лимит: {MAX_DIALOG_QUESTIONS} вопроса в диалоге.\n\n"
                "Диалог завершён. Вы можете загрузить работу заново для нового анализа.",
                reply_markup=get_main_menu_keyboard(user_id),
            )
            await state.set_state(Form.MAIN_MENU)
            return

        try:
            await message.answer("⏳ Обрабатываю ваш вопрос...")

            # Отправляем вопрос на бэкенд
            session_data = data.get("session_data", {})

            if dialog_type == "nir":
                endpoint = f"{BACKEND_URL}/dialog/nir"
                payload = {
                    "user_id": str(user_id),
                    "question": text,
                    "file_content": session_data.get("file_content", b"").decode(
                        "utf-8", errors="ignore"
                    )
                    if session_data.get("file_content")
                    else "",
                    "file_name": session_data.get("file_name", ""),
                    "user_query": session_data.get("user_query", ""),
                    "conversation_history": data.get("conversation_history", []),
                }
            else:
                endpoint = f"{BACKEND_URL}/dialog/teacher"
                payload = {
                    "user_id": str(user_id),
                    "question": text,
                    "plan_content": session_data.get("plan_content", b"").decode(
                        "utf-8", errors="ignore"
                    )
                    if session_data.get("plan_content")
                    else "",
                    "plan_name": session_data.get("plan_name", ""),
                    "user_query": session_data.get("user_query", ""),
                    "conversation_history": data.get("conversation_history", []),
                }

            response = requests.post(endpoint, json=payload, timeout=120)

            if response.status_code == 200:
                try:
                    response_data = response.json()
                    if isinstance(response_data, dict):
                        answer = response_data.get("response", "")
                        conversation_history = response_data.get(
                            "conversation_history", []
                        )
                    elif isinstance(response_data, str):
                        answer = response_data
                        conversation_history = []
                    else:
                        answer = str(response_data)
                        conversation_history = []

                    if not answer:
                        answer = "Не удалось сформулировать ответ. Попробуйте переформулировать вопрос."

                    # Обновляем историю диалога
                    await state.update_data(
                        dialog_questions_count=questions_count + 1,
                        conversation_history=conversation_history,
                    )

                    remaining = MAX_DIALOG_QUESTIONS - questions_count - 1

                    if remaining <= 0:
                        await message.answer(
                            answer,
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_main_menu_keyboard(user_id),
                        )
                        await message.answer(
                            f"✅ Лимит вопросов ({MAX_DIALOG_QUESTIONS}) исчерпан. Диалог завершён.",
                            reply_markup=get_main_menu_keyboard(user_id),
                        )
                        await state.set_state(Form.MAIN_MENU)
                    else:
                        answer_html = md_bold_to_html(answer)
                        await message.answer(
                            f"{answer_html}\n\n<i>Осталось вопросов: {remaining}</i>",
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_dialog_keyboard(),
                        )

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response in dialog: {e}")
                    await message.answer(
                        "❌ Ошибка при обработке ответа. Попробуйте ещё раз.",
                        reply_markup=get_dialog_keyboard(),
                    )
            else:
                await message.answer(
                    "❌ Ошибка при обработке вопроса. Попробуйте ещё раз.",
                    reply_markup=get_dialog_keyboard(),
                )

        except requests.exceptions.Timeout:
            await message.answer(
                "⏰ Превышено время ожидания. Попробуйте ещё раз.",
                reply_markup=get_dialog_keyboard(),
            )
        except Exception as e:
            logger.error(f"Error in dialog: {e}")
            await message.answer(
                "❌ Произошла ошибка. Попробуйте ещё раз.",
                reply_markup=get_dialog_keyboard(),
            )


# ========== Обработчики диалога ==========
async def _start_dialog_session(
        user_id: int,
        work_type: str,
        work_text: str,
        user_query: str,
        initial_response: str,
        session_data: Dict[str, Any]
) -> Optional[str]:
    """Создает сессию диалога на бэкенде и возвращает session_id."""
    try:
        # Подготавливаем данные для создания сессии
        payload = {
            "user_id": str(user_id),
            "work_type": work_type,
            "work_text": work_text,
            "user_query": user_query,
            "initial_response": initial_response,
            "top_k": 5
        }

        # Для преподавателя добавляем план урока
        if work_type == "teacher" and session_data.get("plan_content"):
            plan_content = session_data.get("plan_content")
            plan_name = session_data.get("plan_name", "plan.txt")

            # Отправляем как файл
            files = {"file": (plan_name, plan_content)}
            response = requests.post(
                f"{BACKEND_URL}/dialog/start",
                files=files,
                data=payload,
                timeout=30
            )
        else:
            response = requests.post(
                f"{BACKEND_URL}/dialog/start",
                json=payload,
                timeout=30
            )

        if response.status_code == 200:
            response_data = response.json()
            return response_data.get("session_id")
        else:
            logger.error(f"Failed to start dialog session: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error starting dialog session: {e}")
        return None


# ========== Обработчики диалога ==========
@router.message(Form.IN_TEACHER_DIALOG)
async def handle_teacher_dialog(message: Message, state: FSMContext):
    """Обрабатывает диалог с преподавателем - любой текст считается вопросом."""
    text = message.text
    user_id = message.from_user.id

    if text == BTN_END_DIALOG:
        # Завершаем сессию на бэкенде
        data = await state.get_data()
        session_id = data.get("dialog_session_id")

        if session_id:
            try:
                requests.post(f"{BACKEND_URL}/dialog/end", json={"session_id": session_id})
            except:
                pass

        await message.answer(
            "✅ Диалог завершен. Успехов в преподавании!\n\nЧем еще могу помочь?",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        await state.set_state(Form.MAIN_MENU)
        return

    # Любой другой текст считается вопросом
    data = await state.get_data()
    questions_count = data.get("dialog_questions_count", 0)
    session_id = data.get("dialog_session_id")

    if questions_count >= MAX_DIALOG_QUESTIONS:
        await message.answer(
            f"⚠️ Достигнут лимит: {MAX_DIALOG_QUESTIONS} вопроса в диалоге.\n\n"
            "Начните новый запрос для продолжения.",
            reply_markup=get_main_menu_keyboard(user_id),
        )
        await state.set_state(Form.MAIN_MENU)
        return

    # Если нет сессии, пытаемся создать
    if not session_id:
        session_data = data.get("session_data", {})
        initial_response = data.get("last_recommendation", "")
        user_query = session_data.get("user_query", "")

        # Для преподавателя work_text - это user_query
        work_text = user_query

        session_id = await _start_dialog_session(
            user_id=user_id,
            work_type="teacher",
            work_text=work_text,
            user_query=user_query,
            initial_response=initial_response,
            session_data=session_data
        )

        if not session_id:
            await message.answer(
                "❌ Не удалось создать сессию диалога. Попробуйте начать заново.",
                reply_markup=get_main_menu_keyboard(user_id),
            )
            await state.set_state(Form.MAIN_MENU)
            return

        await state.update_data(dialog_session_id=session_id)

    try:
        await message.answer("⏳ Обрабатываю ваш вопрос...")

        # Отправляем вопрос на бэкенд
        payload = {
            "session_id": session_id,
            "question": text
        }

        response = requests.post(
            f"{BACKEND_URL}/dialog/ask",
            json=payload,
            timeout=120
        )

        if response.status_code == 200:
            response_data = response.json()
            answer = response_data.get("response", "")

            if not answer:
                answer = "Не удалось сформулировать ответ. Попробуйте переформулировать вопрос."

            # Обновляем счетчик вопросов
            await state.update_data(
                dialog_questions_count=questions_count + 1,
            )

            remaining = MAX_DIALOG_QUESTIONS - questions_count - 1

            if remaining <= 0:
                # Лимит вопросов исчерпан
                # Разбиваем ответ на части если слишком длинный
                answer_html = md_bold_to_html(answer)
                parts = split_text_for_telegram(answer_html, max_len=4096)

                if parts:
                    for part in parts:
                        await message.answer(
                            part,
                            parse_mode=ParseMode.HTML,
                        )
                else:
                    await message.answer(
                        answer_html,
                        parse_mode=ParseMode.HTML,
                    )

                await message.answer(
                    f"✅ Лимит вопросов ({MAX_DIALOG_QUESTIONS}) исчерпан. Диалог завершён.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
            else:
                # Еще есть вопросы
                answer_html = md_bold_to_html(answer)
                parts = split_text_for_telegram(answer_html, max_len=4096)

                if parts:
                    # Отправляем все части кроме последней
                    for part in parts[:-1]:
                        await message.answer(
                            part,
                            parse_mode=ParseMode.HTML,
                        )
                    # Последнюю часть отправляем с информацией о количестве оставшихся вопросов
                    last_part = f"{parts[-1]}\n\n<i>Осталось вопросов: {remaining}</i>"
                    await message.answer(
                        last_part,
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_dialog_keyboard(),
                    )
                else:
                    await message.answer(
                        f"{answer_html}\n\n<i>Осталось вопросов: {remaining}</i>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_dialog_keyboard(),
                    )

        else:
            logger.error(f"Dialog ask error: {response.status_code} - {response.text}")
            if response.status_code == 404:
                await message.answer(
                    "❌ Функция диалога временно недоступна. Пожалуйста, начните новый запрос.",
                    reply_markup=get_main_menu_keyboard(user_id),
                )
                await state.set_state(Form.MAIN_MENU)
            else:
                await message.answer(
                    f"❌ Ошибка при обработке вопроса (код {response.status_code}). Попробуйте ещё раз.",
                    reply_markup=get_dialog_keyboard(),
                )

    except requests.exceptions.Timeout:
        await message.answer(
            "⏰ Превышено время ожидания. Попробуйте ещё раз.",
            reply_markup=get_dialog_keyboard(),
        )
    except Exception as e:
        logger.error(f"Error in teacher dialog: {e}")
        await message.answer(
            "❌ Произошла внутренняя ошибка. Попробуйте ещё раз.",
            reply_markup=get_dialog_keyboard(),
        )


# ========== Утилиты ==========
async def cancel_operation(message: Message, state: FSMContext):
    """Отмена операции и возврат в главное меню."""
    await state.clear()

    await message.answer(
        "❌ Операция отменена. Чем еще могу помочь?",
        reply_markup=get_main_menu_keyboard(message.from_user.id),
    )
    await state.set_state(Form.MAIN_MENU)


# ========== Общие обработчики отмены ==========
@router.message(F.text == BTN_CANCEL)
async def handle_cancel_button(message: Message, state: FSMContext):
    await cancel_operation(message, state)


# ========== Запуск бота ==========
async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return

    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
