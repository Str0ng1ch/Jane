import json
import logging
import os
import re
from datetime import datetime
from typing import List

import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters, 
    ConversationHandler,
    Defaults
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния разговора
(
    MAIN_MENU, 
    WAITING_ASSIGNMENT,  # Ожидание задания от преподавателя (для эссе)
    WAITING_ESSAY,  # Ожидание эссе
    WAITING_NIR,  # Ожидание НИР
    WAITING_NIR_QUERY,  # Ожидание запроса для НИР
    IN_DIALOG,  # Диалоговый режим
    WAITING_RATING, 
    WAITING_COMMENT,
    WAITING_TEACHER_PLAN,  # Ожидание плана урока (опционально)
    WAITING_TEACHER_QUERY,  # Ожидание запроса преподавателя
    IN_TEACHER_DIALOG,  # Диалог преподавателя
) = range(11)

BOT_TOKEN = os.getenv('BOT_TOKEN')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:5001')
USER_DATA = {}

# Константы для кнопок
BTN_CHECK_ESSAY = '📝 Проверить эссе'
BTN_CHECK_NIR = '📚 Проверить НИР'
BTN_TEACHER_HELP = '👩‍🏫 Помощь преподавателю'
BTN_ASK_QUESTION = '❓ Задать вопрос'
BTN_END_DIALOG = '🔚 Завершить диалог'
BTN_RATE_BOT = '⭐ Оценить работу бота'
BTN_CANCEL = '❌ Отменить'
BTN_SKIP = 'Пропустить'
BTN_BACK = '◀️ Назад'

# Лимит вопросов в диалоговой сессии
MAX_DIALOG_QUESTIONS = 3

# Пути к данным
DATA_DIR = os.getenv('DATA_DIR', './data')
USAGE_DIR = os.path.join(DATA_DIR, "usage")


def split_text_for_telegram(text: str, max_len: int = 4096) -> List[str]:
    """
    Разбивает текст на части для отправки в Telegram.
    """
    parts = []
    remaining = text or ""
    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break
        window = remaining[:max_len]
        # 1) Пытаемся разорвать по границе абзацев (\n\n)
        para_pos = window.rfind("\n\n")
        if para_pos != -1:
            split_at = para_pos
            chunk = remaining[:split_at].rstrip()
            j = split_at
            while j < len(remaining) and remaining[j] == '\n':
                j += 1
            remaining = remaining[j:]
            if chunk:
                parts.append(chunk)
            continue
        # 2) Иначе разрываем по последнему пробелу/переводу строки
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


def has_daily_quota(user_id: int) -> bool:
    """Проверяет дневной лимит использования."""
    path = _usage_file_path(user_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == _today_str() and int(data.get("count", 0)) >= 3:
            return False
        return True
    except Exception:
        return True


def record_daily_use(user_id: int) -> None:
    """Записывает использование."""
    path = _usage_file_path(user_id)
    try:
        current_count = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("date") == _today_str():
                    current_count = int(data.get("count", 0))
        except:
            pass
        
        payload = {"date": _today_str(), "count": current_count + 1}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to persist usage for user {user_id}: {e}")


def get_main_menu_keyboard():
    """Главное меню."""
    return [
        [BTN_CHECK_ESSAY, BTN_CHECK_NIR],
        [BTN_TEACHER_HELP],
        [BTN_RATE_BOT]
    ]




def get_dialog_keyboard():
    """Меню для диалогового режима."""
    return [
        [BTN_ASK_QUESTION],
        [BTN_END_DIALOG]
    ]


def md_bold_to_html(s: str) -> str:
    """Преобразует **bold** в HTML <b>bold</b>."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает команду /start."""
    user = update.message.from_user
    USER_DATA[user.id] = {'username': user.username, 'first_name': user.first_name}

    keyboard = get_main_menu_keyboard()
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = """
Приветствую! 🏙

Я - Джейн, ваш AI-ассистент в мире городских исследований и образования.

<b>Что я умею:</b>
• 📝 Проверять эссе с обратной связью
• 📚 Анализировать НИР (научно-исследовательские работы)
• 👩‍🏫 Помогать преподавателям с подготовкой к занятиям
• 💬 Вести диалог для уточнения рекомендаций

<b>Для студентов:</b>
Выберите тип работы, загрузите задание и получите рекомендации.

<b>Для преподавателей:</b>
Загрузите план урока (опционально) и задайте вопрос — я помогу с методикой!

⚠️ Лимит: не более 3 проверок в день
"""

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return MAIN_MENU


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает выбор в главном меню."""
    text = update.message.text
    user_id = update.message.from_user.id

    if text == BTN_CHECK_ESSAY:
        context.user_data['work_type'] = 'essay'
        context.user_data['work_type_name'] = 'эссе'
        
        # Проверяем лимит
        if not has_daily_quota(user_id):
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ Лимит: не более 3 проверок в день. Попробуйте завтра.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        cancel_keyboard = [[BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📋 <b>Шаг 1 из 2: Задание от преподавателя</b>\n\n"
            "Отправьте файл с заданием (.txt или .docx)\n\n"
            "<i>Это поможет оценить эссе по критериям преподавателя.</i>",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return WAITING_ASSIGNMENT

    elif text == BTN_CHECK_NIR:
        context.user_data['work_type'] = 'nir'
        context.user_data['work_type_name'] = 'НИР'
        
        # Проверяем лимит
        if not has_daily_quota(user_id):
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ Лимит: не более 3 проверок в день. Попробуйте завтра.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        cancel_keyboard = [[BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📤 <b>Отправьте вашу НИР</b>\n\n"
            "Поддерживаемые форматы: .txt, .docx",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return WAITING_NIR

    elif text == BTN_TEACHER_HELP:
        context.user_data['work_type'] = 'teacher'
        context.user_data['work_type_name'] = 'помощь преподавателю'
        
        # Проверяем лимит
        if not has_daily_quota(user_id):
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ Лимит: не более 3 проверок в день. Попробуйте завтра.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        skip_keyboard = [[BTN_SKIP], [BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(skip_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "👩‍🏫 <b>Помощь преподавателю</b>\n\n"
            "📋 <b>Шаг 1 из 2: План урока</b> (опционально)\n\n"
            "Отправьте файл с планом урока (.txt или .docx), "
            "чтобы я мог дать более точные рекомендации.\n\n"
            "Или нажмите <b>Пропустить</b>, чтобы сразу задать вопрос.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return WAITING_TEACHER_PLAN

    elif text == BTN_RATE_BOT:
        rating_keyboard = [['1', '2', '3', '4', '5'], [BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(rating_keyboard, resize_keyboard=True)

        await update.message.reply_text(
            "Пожалуйста, оцените мою работу по шкале от 1 до 5:",
            reply_markup=reply_markup
        )
        return WAITING_RATING

    else:
        keyboard = get_main_menu_keyboard()
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Пожалуйста, выберите одну из предложенных опций:",
            reply_markup=reply_markup
        )
        return MAIN_MENU


async def handle_assignment_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает загрузку задания от преподавателя для эссе."""
    user_id = update.message.from_user.id
    
    if not update.message.document:
        await update.message.reply_text("Пожалуйста, отправьте файл с заданием (.txt или .docx).")
        return WAITING_ASSIGNMENT

    if not (update.message.document.file_name.endswith('.txt') or 
            update.message.document.file_name.endswith('.docx')):
        await update.message.reply_text("Неверный формат файла. Поддерживаются только .txt и .docx.")
        return WAITING_ASSIGNMENT

    try:
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        file_name = update.message.document.file_name
        
        # Отправляем задание на backend
        files = {'file': (file_name, file_bytes)}
        data = {'user_id': str(user_id), 'work_type': 'essay'}
        
        response = requests.post(
            f"{BACKEND_URL}/assignment",
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            cancel_keyboard = [[BTN_CANCEL]]
            reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ Задание получено: <b>{file_name}</b>\n\n"
                "📤 <b>Шаг 2 из 2: Отправьте ваше эссе</b>\n\n"
                "Поддерживаемые форматы: .txt, .docx",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            return WAITING_ESSAY
        else:
            await update.message.reply_text("❌ Ошибка при сохранении задания. Попробуйте ещё раз.")
            return WAITING_ASSIGNMENT
            
    except Exception as e:
        logger.error(f"Error uploading assignment: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
        return WAITING_ASSIGNMENT


async def handle_essay_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает загрузку эссе и возвращает обратную связь."""
    user_id = update.message.from_user.id

    if not update.message.document:
        await update.message.reply_text("Пожалуйста, отправьте файл (.txt или .docx).")
        return WAITING_ESSAY

    if not (update.message.document.file_name.endswith('.txt') or 
            update.message.document.file_name.endswith('.docx')):
        await update.message.reply_text("Неверный формат файла. Поддерживаются только .txt и .docx.")
        return WAITING_ESSAY

    try:
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        file_name = update.message.document.file_name

        files = {'file': (file_name, file_bytes)}
        data = {'user_id': str(user_id), 'top_k': '5'}

        await update.message.reply_text("⏳ Анализирую ваше эссе...")
        
        response = requests.post(
            f"{BACKEND_URL}/analyze/essay",
            files=files,
            data=data,
            timeout=180
        )

        if response.status_code == 200:
            response_data = response.json()
            recommendation = response_data.get('recommendation', '')

            # Для эссе - возвращаемся в главное меню
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

            recommendation_html = md_bold_to_html(recommendation)
            parts = split_text_for_telegram(recommendation_html, max_len=4096)
            
            if parts:
                for part in parts[:-1]:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                await update.message.reply_text(
                    parts[-1] + "\n\n✅ Анализ завершён. Вы можете проверить другую работу.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "Анализ завершён.",
                    reply_markup=reply_markup
                )

            record_daily_use(user_id)
            return MAIN_MENU

        else:
            try:
                error_data = response.json()
                error_type = error_data.get('error')
                
                error_messages = {
                    'invalid_docx': "❌ Загруженный DOCX файл поврежден.",
                    'unsupported_format': "❌ Неподдерживаемый формат файла.",
                    'processing_error': "❌ Ошибка при обработке файла.",
                }
                
                message = error_messages.get(error_type, "❌ Ошибка при обработке файла.")
                await update.message.reply_text(message)
            except:
                await update.message.reply_text("❌ Ошибка при обработке файла. Попробуйте ещё раз.")
            
            return WAITING_ESSAY

    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Превышено время ожидания. Попробуйте ещё раз.")
        return WAITING_ESSAY
    except Exception as e:
        logger.error(f"Error processing essay: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
        return WAITING_ESSAY


async def handle_nir_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает загрузку НИР и переходит к вопросу."""
    user_id = update.message.from_user.id

    if not update.message.document:
        await update.message.reply_text("Пожалуйста, отправьте файл (.txt или .docx).")
        return WAITING_NIR

    if not (update.message.document.file_name.endswith('.txt') or 
            update.message.document.file_name.endswith('.docx')):
        await update.message.reply_text("Неверный формат файла. Поддерживаются только .txt и .docx.")
        return WAITING_NIR

    try:
        file = await update.message.document.get_file()
        file_bytes = await file.download_as_bytearray()
        file_name = update.message.document.file_name

        # Сохраняем файл для последующего анализа
        context.user_data['nir_file_bytes'] = file_bytes
        context.user_data['nir_file_name'] = file_name
        
        cancel_keyboard = [[BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"✅ Файл <b>{file_name}</b> получен!\n\n"
            "📝 <b>На что обратить внимание?</b>\n\n"
            "Напишите, что именно вы хотите проверить или улучшить.\n\n"
            "<i>Примеры:</i>\n"
            "• Проверь логику аргументации\n"
            "• Какие источники добавить?\n"
            "• Как улучшить введение?\n"
            "• Соответствует ли текст теме?",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
        return WAITING_NIR_QUERY
        
    except Exception as e:
        logger.error(f"Error receiving NIR file: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
        return WAITING_NIR


async def handle_nir_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает запрос пользователя для НИР и запускает анализ."""
    text = update.message.text
    user_id = update.message.from_user.id
    
    if text == BTN_CANCEL:
        # Очищаем сохранённый файл
        context.user_data.pop('nir_file_bytes', None)
        context.user_data.pop('nir_file_name', None)
        context.user_data.pop('nir_file_ready', None)
        return await cancel(update, context)
    
    # Сохраняем запрос пользователя
    context.user_data['user_query'] = text
    
    # Получаем сохранённый файл
    file_bytes = context.user_data.get('nir_file_bytes')
    file_name = context.user_data.get('nir_file_name')
    
    if not file_bytes or not file_name:
        keyboard = get_main_menu_keyboard()
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "⚠️ Файл не найден. Пожалуйста, загрузите НИР заново.",
            reply_markup=reply_markup
        )
        return MAIN_MENU
    
    await update.message.reply_text(
        f"✅ Запрос: <i>«{text[:100]}{'...' if len(text) > 100 else ''}»</i>\n\n"
        "⏳ Анализирую вашу НИР...",
        parse_mode='HTML'
    )
    
    try:
        files = {'file': (file_name, file_bytes)}
        data = {'user_id': str(user_id), 'top_k': '5', 'user_query': text}
        
        endpoint = f"{BACKEND_URL}/analyze/nir"
        response = requests.post(endpoint, files=files, data=data, timeout=180)
        
        if response.status_code == 200:
            response_data = response.json()
            recommendation = response_data.get('recommendation', '')
            
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            recommendation_html = md_bold_to_html(recommendation)
            parts = split_text_for_telegram(recommendation_html, max_len=4096)
            
            if parts:
                for part in parts[:-1]:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                await update.message.reply_text(
                    parts[-1] + "\n\n💬 Вы можете задать дополнительные вопросы или завершить диалог.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "Анализ завершен. Вы можете задать вопросы.",
                    reply_markup=reply_markup
                )
            
            # Начинаем диалоговую сессию с сохранением начального ответа в историю
            try:
                dialog_resp = requests.post(
                    f"{BACKEND_URL}/dialog/start",
                    files={'file': (file_name, file_bytes)},
                    data={
                        'user_id': str(user_id),
                        'work_type': 'nir',
                        'user_query': text,
                        'initial_response': recommendation,  # Сохраняем начальный ответ в историю
                    },
                    timeout=60
                )
                
                if dialog_resp.status_code == 200:
                    session_data = dialog_resp.json()
                    context.user_data['session_id'] = session_data.get('session_id')
                    context.user_data['dialog_questions_count'] = 0  # Счётчик вопросов
                    logger.info(f"Dialog session created: {session_data.get('session_id')}")
            except Exception as e:
                logger.warning(f"Failed to start dialog session: {e}")
            
            # Очищаем сохранённый файл
            context.user_data.pop('nir_file_bytes', None)
            context.user_data.pop('nir_file_name', None)
            context.user_data.pop('nir_file_ready', None)
            
            record_daily_use(user_id)
            return IN_DIALOG
        else:
            await update.message.reply_text("❌ Ошибка при анализе. Попробуйте ещё раз.")
            return WAITING_NIR_QUERY
            
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Превышено время ожидания. Попробуйте ещё раз.")
        return WAITING_NIR_QUERY
    except Exception as e:
        logger.error(f"Error processing NIR: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
        return WAITING_NIR_QUERY


async def handle_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает диалог с пользователем."""
    text = update.message.text
    user_id = update.message.from_user.id
    session_id = context.user_data.get('session_id')

    if text == BTN_END_DIALOG:
        # Завершаем сессию
        if session_id:
            try:
                requests.post(
                    f"{BACKEND_URL}/dialog/end",
                    json={'session_id': session_id},
                    timeout=10
                )
            except:
                pass
            context.user_data.pop('session_id', None)
        context.user_data.pop('dialog_questions_count', None)

        keyboard = get_main_menu_keyboard()
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "✅ Диалог завершен. Спасибо за использование!\n\nЧем еще могу помочь?",
            reply_markup=reply_markup
        )
        return MAIN_MENU

    elif text == BTN_ASK_QUESTION:
        await update.message.reply_text(
            "💭 Напишите ваш вопрос, и я постараюсь помочь."
        )
        return IN_DIALOG

    else:
        # Это вопрос пользователя
        if not session_id:
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ Сессия диалога не найдена. Пожалуйста, загрузите работу заново.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        # Проверяем лимит вопросов
        questions_count = context.user_data.get('dialog_questions_count', 0)
        if questions_count >= MAX_DIALOG_QUESTIONS:
            # Завершаем сессию
            try:
                requests.post(
                    f"{BACKEND_URL}/dialog/end",
                    json={'session_id': session_id},
                    timeout=10
                )
            except:
                pass
            context.user_data.pop('session_id', None)
            context.user_data.pop('dialog_questions_count', None)

            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"⚠️ Достигнут лимит: {MAX_DIALOG_QUESTIONS} вопроса в диалоге.\n\n"
                "Диалог завершён. Вы можете загрузить работу заново для нового анализа.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        try:
            await update.message.reply_text("⏳ Обрабатываю ваш вопрос...")
            
            response = requests.post(
                f"{BACKEND_URL}/dialog/ask",
                json={
                    'session_id': session_id,
                    'question': text,
                },
                timeout=120
            )

            if response.status_code == 200:
                answer = response.json().get('response', '')
                answer_html = md_bold_to_html(answer)
                
                # Увеличиваем счётчик вопросов
                context.user_data['dialog_questions_count'] = questions_count + 1
                remaining = MAX_DIALOG_QUESTIONS - questions_count - 1
                
                # Проверяем, остались ли ещё вопросы
                if remaining <= 0:
                    # Это был последний вопрос — завершаем сессию
                    try:
                        requests.post(
                            f"{BACKEND_URL}/dialog/end",
                            json={'session_id': session_id},
                            timeout=10
                        )
                    except:
                        pass
                    context.user_data.pop('session_id', None)
                    context.user_data.pop('dialog_questions_count', None)
                    
                    keyboard = get_main_menu_keyboard()
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    parts = split_text_for_telegram(answer_html, max_len=4096)
                    if parts:
                        for part in parts[:-1]:
                            await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                        await update.message.reply_text(
                            parts[-1] + f"\n\n✅ Лимит вопросов ({MAX_DIALOG_QUESTIONS}) исчерпан. Диалог завершён.",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"✅ Лимит вопросов ({MAX_DIALOG_QUESTIONS}) исчерпан. Диалог завершён.",
                            reply_markup=reply_markup
                        )
                    return MAIN_MENU
                else:
                    keyboard = get_dialog_keyboard()
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    parts = split_text_for_telegram(answer_html, max_len=4096)
                    if parts:
                        for part in parts[:-1]:
                            await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                        await update.message.reply_text(
                            parts[-1] + f"\n\n<i>Осталось вопросов: {remaining}</i>",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"Я не смог сформулировать ответ. Попробуйте переформулировать вопрос.\n\n<i>Осталось вопросов: {remaining}</i>",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
            else:
                keyboard = get_dialog_keyboard()
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(
                    "❌ Ошибка при обработке вопроса. Попробуйте ещё раз.",
                    reply_markup=reply_markup
                )

            return IN_DIALOG

        except requests.exceptions.Timeout:
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⏰ Превышено время ожидания. Попробуйте ещё раз.",
                reply_markup=reply_markup
            )
            return IN_DIALOG
        except Exception as e:
            logger.error(f"Error in dialog: {e}")
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "❌ Произошла ошибка. Попробуйте ещё раз.",
                reply_markup=reply_markup
            )
            return IN_DIALOG


async def handle_teacher_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает загрузку плана урока (опционально)."""
    text = update.message.text
    user_id = update.message.from_user.id
    
    if text == BTN_CANCEL:
        return await cancel(update, context)
    
    if text == BTN_SKIP:
        # Пропускаем план урока
        context.user_data['teacher_plan_bytes'] = None
        context.user_data['teacher_plan_name'] = None
        
        cancel_keyboard = [[BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📝 <b>Шаг 2 из 2: Ваш запрос</b>\n\n"
            "Напишите, с чем вам нужна помощь:\n\n"
            "<i>Примеры:</i>\n"
            "• Как сделать урок более интерактивным?\n"
            "• Какие техники обратной связи использовать?\n"
            "• Как мотивировать студентов?\n"
            "• Как организовать групповую работу?",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        return WAITING_TEACHER_QUERY
    
    # Проверяем, загружен ли документ
    if update.message.document:
        if not (update.message.document.file_name.endswith('.txt') or 
                update.message.document.file_name.endswith('.docx')):
            await update.message.reply_text("Неверный формат файла. Поддерживаются только .txt и .docx.")
            return WAITING_TEACHER_PLAN
        
        try:
            file = await update.message.document.get_file()
            file_bytes = await file.download_as_bytearray()
            file_name = update.message.document.file_name
            
            context.user_data['teacher_plan_bytes'] = file_bytes
            context.user_data['teacher_plan_name'] = file_name
            
            cancel_keyboard = [[BTN_CANCEL]]
            reply_markup = ReplyKeyboardMarkup(cancel_keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ План урока получен: <b>{file_name}</b>\n\n"
                "📝 <b>Шаг 2 из 2: Ваш запрос</b>\n\n"
                "Напишите, с чем вам нужна помощь:\n\n"
                "<i>Примеры:</i>\n"
                "• Как улучшить этот урок?\n"
                "• Какие активности добавить?\n"
                "• Как проверить понимание?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            return WAITING_TEACHER_QUERY
            
        except Exception as e:
            logger.error(f"Error receiving teacher plan: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
            return WAITING_TEACHER_PLAN
    
    await update.message.reply_text(
        "Пожалуйста, отправьте файл (.txt или .docx) или нажмите 'Пропустить'."
    )
    return WAITING_TEACHER_PLAN


async def handle_teacher_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает запрос преподавателя и запускает RAG."""
    text = update.message.text
    user_id = update.message.from_user.id
    
    if text == BTN_CANCEL:
        context.user_data.pop('teacher_plan_bytes', None)
        context.user_data.pop('teacher_plan_name', None)
        return await cancel(update, context)
    
    context.user_data['teacher_query'] = text
    
    await update.message.reply_text(
        f"✅ Запрос: <i>«{text[:100]}{'...' if len(text) > 100 else ''}»</i>\n\n"
        "⏳ Ищу методические рекомендации...",
        parse_mode=ParseMode.HTML
    )
    
    try:
        # Подготавливаем данные
        plan_bytes = context.user_data.get('teacher_plan_bytes')
        plan_name = context.user_data.get('teacher_plan_name', 'plan.txt')
        
        data = {'user_id': str(user_id), 'top_k': '5', 'user_query': text}
        
        if plan_bytes:
            files = {'file': (plan_name, plan_bytes)}
            response = requests.post(
                f"{BACKEND_URL}/analyze/teacher",
                files=files,
                data=data,
                timeout=180
            )
        else:
            response = requests.post(
                f"{BACKEND_URL}/analyze/teacher",
                data=data,
                timeout=180
            )
        
        if response.status_code == 200:
            response_data = response.json()
            recommendation = response_data.get('recommendation', '')
            
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            recommendation_html = md_bold_to_html(recommendation)
            parts = split_text_for_telegram(recommendation_html, max_len=4096)
            
            if parts:
                for part in parts[:-1]:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                await update.message.reply_text(
                    parts[-1] + "\n\n💬 Вы можете задать дополнительные вопросы или завершить диалог.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    "Готово! Вы можете задать вопросы.",
                    reply_markup=reply_markup
                )
            
            # Начинаем диалоговую сессию
            try:
                session_data = {'user_id': str(user_id), 'work_type': 'teacher'}
                if plan_bytes:
                    dialog_resp = requests.post(
                        f"{BACKEND_URL}/dialog/start",
                        files={'file': (plan_name, plan_bytes)},
                        data={
                            'user_id': str(user_id),
                            'work_type': 'teacher',
                            'user_query': text,
                            'initial_response': recommendation,
                        },
                        timeout=60
                    )
                else:
                    dialog_resp = requests.post(
                        f"{BACKEND_URL}/dialog/start",
                        data={
                            'user_id': str(user_id),
                            'work_type': 'teacher',
                            'work_text': text,  # Используем запрос как текст работы
                            'user_query': text,
                            'initial_response': recommendation,
                        },
                        timeout=60
                    )
                
                if dialog_resp.status_code == 200:
                    session_data = dialog_resp.json()
                    context.user_data['session_id'] = session_data.get('session_id')
                    context.user_data['dialog_questions_count'] = 0
                    logger.info(f"Teacher dialog session created: {session_data.get('session_id')}")
            except Exception as e:
                logger.warning(f"Failed to start teacher dialog session: {e}")
            
            # Очищаем временные данные
            context.user_data.pop('teacher_plan_bytes', None)
            context.user_data.pop('teacher_plan_name', None)
            
            record_daily_use(user_id)
            return IN_TEACHER_DIALOG
        else:
            await update.message.reply_text("❌ Ошибка при обработке. Попробуйте ещё раз.")
            return WAITING_TEACHER_QUERY
            
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏰ Превышено время ожидания. Попробуйте ещё раз.")
        return WAITING_TEACHER_QUERY
    except Exception as e:
        logger.error(f"Error processing teacher request: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте ещё раз.")
        return WAITING_TEACHER_QUERY


async def handle_teacher_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает диалог с преподавателем (без повторного RAG)."""
    text = update.message.text
    user_id = update.message.from_user.id
    session_id = context.user_data.get('session_id')

    if text == BTN_END_DIALOG:
        if session_id:
            try:
                requests.post(
                    f"{BACKEND_URL}/dialog/end",
                    json={'session_id': session_id},
                    timeout=10
                )
            except:
                pass
            context.user_data.pop('session_id', None)
        context.user_data.pop('dialog_questions_count', None)

        keyboard = get_main_menu_keyboard()
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "✅ Диалог завершен. Успехов в преподавании!\n\nЧем еще могу помочь?",
            reply_markup=reply_markup
        )
        return MAIN_MENU

    elif text == BTN_ASK_QUESTION:
        await update.message.reply_text(
            "💭 Напишите ваш уточняющий вопрос."
        )
        return IN_TEACHER_DIALOG

    else:
        # Это вопрос преподавателя (без повторного RAG)
        if not session_id:
            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ Сессия диалога не найдена. Начните заново.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        # Проверяем лимит вопросов
        questions_count = context.user_data.get('dialog_questions_count', 0)
        if questions_count >= MAX_DIALOG_QUESTIONS:
            try:
                requests.post(
                    f"{BACKEND_URL}/dialog/end",
                    json={'session_id': session_id},
                    timeout=10
                )
            except:
                pass
            context.user_data.pop('session_id', None)
            context.user_data.pop('dialog_questions_count', None)

            keyboard = get_main_menu_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                f"⚠️ Достигнут лимит: {MAX_DIALOG_QUESTIONS} вопроса в диалоге.\n\n"
                "Начните новый запрос для продолжения.",
                reply_markup=reply_markup
            )
            return MAIN_MENU

        try:
            await update.message.reply_text("⏳ Обрабатываю ваш вопрос...")
            
            response = requests.post(
                f"{BACKEND_URL}/dialog/ask",
                json={
                    'session_id': session_id,
                    'question': text,
                },
                timeout=120
            )

            if response.status_code == 200:
                answer = response.json().get('response', '')
                answer_html = md_bold_to_html(answer)
                
                context.user_data['dialog_questions_count'] = questions_count + 1
                remaining = MAX_DIALOG_QUESTIONS - questions_count - 1
                
                if remaining <= 0:
                    try:
                        requests.post(
                            f"{BACKEND_URL}/dialog/end",
                            json={'session_id': session_id},
                            timeout=10
                        )
                    except:
                        pass
                    context.user_data.pop('session_id', None)
                    context.user_data.pop('dialog_questions_count', None)
                    
                    keyboard = get_main_menu_keyboard()
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    parts = split_text_for_telegram(answer_html, max_len=4096)
                    if parts:
                        for part in parts[:-1]:
                            await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                        await update.message.reply_text(
                            parts[-1] + f"\n\n✅ Лимит вопросов ({MAX_DIALOG_QUESTIONS}) исчерпан. Диалог завершён.",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                    return MAIN_MENU
                else:
                    keyboard = get_dialog_keyboard()
                    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                    
                    parts = split_text_for_telegram(answer_html, max_len=4096)
                    if parts:
                        for part in parts[:-1]:
                            await update.message.reply_text(part, parse_mode=ParseMode.HTML)
                        await update.message.reply_text(
                            parts[-1] + f"\n\n<i>Осталось вопросов: {remaining}</i>",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await update.message.reply_text(
                            f"Попробуйте переформулировать вопрос.\n\n<i>Осталось вопросов: {remaining}</i>",
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.HTML
                        )
            else:
                keyboard = get_dialog_keyboard()
                reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                await update.message.reply_text(
                    "❌ Ошибка при обработке вопроса. Попробуйте ещё раз.",
                    reply_markup=reply_markup
                )

            return IN_TEACHER_DIALOG

        except requests.exceptions.Timeout:
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⏰ Превышено время ожидания. Попробуйте ещё раз.",
                reply_markup=reply_markup
            )
            return IN_TEACHER_DIALOG
        except Exception as e:
            logger.error(f"Error in teacher dialog: {e}")
            keyboard = get_dialog_keyboard()
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "❌ Произошла ошибка. Попробуйте ещё раз.",
                reply_markup=reply_markup
            )
            return IN_TEACHER_DIALOG


async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает оценку от пользователя."""
    rating = update.message.text
    user_id = update.message.from_user.id

    if rating == BTN_CANCEL:
        return await cancel(update, context)

    if rating not in ['1', '2', '3', '4', '5']:
        rating_keyboard = [['1', '2', '3', '4', '5'], [BTN_CANCEL]]
        reply_markup = ReplyKeyboardMarkup(rating_keyboard, resize_keyboard=True)
        await update.message.reply_text("Пожалуйста, выберите оценку от 1 до 5:", reply_markup=reply_markup)
        return WAITING_RATING

    if user_id not in USER_DATA:
        USER_DATA[user_id] = {}
    USER_DATA[user_id]['rating'] = rating

    await update.message.reply_text(
        "Спасибо за оценку! Напишите ваш комментарий или нажмите 'Пропустить':",
        reply_markup=ReplyKeyboardMarkup([[BTN_SKIP]], resize_keyboard=True)
    )
    return WAITING_COMMENT


async def handle_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает комментарий от пользователя."""
    comment = update.message.text
    user_id = update.message.from_user.id

    if comment == BTN_SKIP:
        comment = ''

    if user_id not in USER_DATA:
        USER_DATA[user_id] = {}
    USER_DATA[user_id]['comment'] = comment

    try:
        payload = {
            'user_id': user_id,
            'rating': USER_DATA[user_id].get('rating', ''),
            'comment': comment
        }

        response = requests.post(f"{BACKEND_URL}/feedback", json=payload, timeout=10)

        if response.status_code == 200:
            await update.message.reply_text("✅ Спасибо за ваш отзыв! Он поможет мне стать лучше.")
        else:
            await update.message.reply_text("Спасибо за отзыв!")
    except Exception as e:
        logger.error(f"Error sending feedback: {e}")
        await update.message.reply_text("Спасибо за отзыв!")

    keyboard = get_main_menu_keyboard()
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Чем еще могу помочь?",
        reply_markup=reply_markup
    )
    return MAIN_MENU


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает отмену операции."""
    # Завершаем диалоговую сессию если есть
    session_id = context.user_data.get('session_id')
    if session_id:
        try:
            requests.post(
                f"{BACKEND_URL}/dialog/end",
                json={'session_id': session_id},
                timeout=10
            )
        except:
            pass
        context.user_data.pop('session_id', None)
    
    # Очищаем временные данные НИР
    context.user_data.pop('nir_file_bytes', None)
    context.user_data.pop('nir_file_name', None)
    context.user_data.pop('nir_file_ready', None)
    context.user_data.pop('user_query', None)
    context.user_data.pop('dialog_questions_count', None)

    keyboard = get_main_menu_keyboard()
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "❌ Операция отменена. Чем еще могу помочь?",
        reply_markup=reply_markup
    )
    return MAIN_MENU


async def handle_incorrect_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает неправильные действия."""
    keyboard = get_main_menu_keyboard()
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Пожалуйста, используйте кнопки меню для навигации.",
        reply_markup=reply_markup
    )
    return MAIN_MENU


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ошибки в работе бота."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    if update and update.message:
        keyboard = get_main_menu_keyboard()
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "❌ Произошла ошибка. Давайте начнем сначала.",
            reply_markup=reply_markup
    )


def main() -> None:
    """Основная функция запуска бота."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return

    app = Application.builder().token(BOT_TOKEN).defaults(Defaults(parse_mode=ParseMode.HTML)).build()
    app.add_error_handler(error_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main_menu),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            WAITING_ASSIGNMENT: [
                MessageHandler(filters.Document.ALL, handle_assignment_document),
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incorrect_action),
            ],
            WAITING_ESSAY: [
                MessageHandler(filters.Document.ALL, handle_essay_document),
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incorrect_action),
            ],
            WAITING_NIR: [
                MessageHandler(filters.Document.ALL, handle_nir_document),
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_incorrect_action),
            ],
            WAITING_NIR_QUERY: [
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_nir_query),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            IN_DIALOG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_dialog),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            WAITING_TEACHER_PLAN: [
                MessageHandler(filters.Document.ALL, handle_teacher_plan),
                MessageHandler(filters.Regex(f'^{re.escape(BTN_SKIP)}$'), handle_teacher_plan),
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_teacher_plan),
            ],
            WAITING_TEACHER_QUERY: [
                MessageHandler(filters.Regex(f'^{re.escape(BTN_CANCEL)}$'), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_teacher_query),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            IN_TEACHER_DIALOG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_teacher_dialog),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            WAITING_RATING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rating),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
            WAITING_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_comment),
                MessageHandler(filters.Document.ALL, handle_incorrect_action),
            ],
        },
        fallbacks=[
            CommandHandler('start', start),
            CommandHandler('cancel', cancel),
        ]
    )

    app.add_handler(conv_handler)
    logger.info("Бот запущен")
    app.run_polling()


if __name__ == '__main__':
    main()
