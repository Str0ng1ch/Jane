# Джейн - ИИ ассистент преподавателя урбанистики

Бот «Джейн» — это AI-ассистент для преподавателей и студентов, сочетающий урбанистику, социальные науки и активные методы обучения. У него две ключевые функции:

- **Проверка домашних заданий** — автоматически даёт обратную связь и рекомендации по улучшению.
- **Консультация по НИР** — ведёт диалог со студентами, помогая генерировать и развивать исследовательские идеи.

«Джейн» мотивирует студентов и упрощает работу преподавателей, выступая в роли умного тьютора с выдержанным стилем общения.

---

## Быстрый старт с Docker

### 1. Создайте `.env` файл

```bash
BOT_TOKEN=ваш_telegram_bot_token
YC_API_KEY=ваш_yandex_cloud_api_key
YC_FOLDER_ID=ваш_yandex_folder_id
```

### 2. Запустите через Docker Compose

```bash
# Сборка и запуск
docker-compose up -d --build

# Просмотр логов
docker-compose logs -f

# Логи только бота
docker-compose logs -f bot

# Остановка
docker-compose down
```

### 3. Убедитесь, что папка `data/` содержит:
- `qdrant_local/` — векторная база данных
- `chunks/` — parent chunks для retriever

---

## Локальная установка

```bash
# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или: venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt
```

Создайте файл `.env` в корне проекта:
```bash
LLAMA_CLOUD_API_KEY=your_llamaparse_key
YC_API_KEY=your_yandex_api_key
YC_FOLDER_ID=your_folder_id
BOT_TOKEN=your_telegram_bot_token
```

### Запуск локально

```bash
# Терминал 1: Backend
export DATA_DIR=./data QDRANT_PATH=./data/qdrant_local PARENT_CHUNKS_DIR=./data/chunks
python -m src.backend.backend

# Терминал 2: Bot
export DATA_DIR=./data BOT_TOKEN=your_token BACKEND_URL=http://localhost:5001
python -m src.backend.bot
```

---

## Пайплайн обработки PDF

Полный пайплайн подготовки книг для RAG системы состоит из 5 шагов:

```
PDF книги → 1. Парсинг PDF → 2. Парсинг TOC → 3. Чанкинг → 4. Эмбеддинги → 5. Qdrant
```

### Структура данных

```
data/
├── books/                         # Исходные PDF книги
│   ├── urban/                     # Книги по урбанистике (для студентов)
│   └── andragogy/                 # Книги по андрагогике (для преподавателей)
├── toc/                           # JSON файлы с оглавлениями
├── cache/                         # Кэш распарсенных страниц (LlamaParse)
├── chunks/                        # Parent chunks (целые главы)
├── child_chunks_with_embeddings/  # Child chunks с эмбеддингами
└── qdrant_local/                  # Векторная база данных
```

### Скрипты обработки данных

Все скрипты находятся в `scripts/process_data/` и пронумерованы по порядку выполнения:

| Скрипт | Описание |
|--------|----------|
| `01_parse_pdf.py` | Парсинг PDF через LlamaParse |
| `02_parse_toc.py` | Парсинг оглавления через Yandex Cloud LLM |
| `03_save_chunks.py` | Сохранение parent/child chunks |
| `04_compute_embeddings.py` | Вычисление эмбеддингов (YC) |
| `05_load_to_qdrant.py` | Загрузка в векторную БД |

---

### Шаг 1: Парсинг PDF

Скрипт `01_parse_pdf.py` извлекает текст из PDF с помощью LlamaParse.

```bash
# Quick mode - указываем только имя книги:
python scripts/process_data/01_parse_pdf.py \
    --name "Название книги" \
    --subdir andragogy

# Или с явными путями:
python scripts/process_data/01_parse_pdf.py \
    --pdf data/books/book.pdf \
    --output data/cache/book_parsed.json
```

Результат: `data/cache/book_parsed.json` — JSON с текстом каждой страницы.

---

### Шаг 2: Парсинг оглавления

Скрипт `02_parse_toc.py` преобразует текстовое оглавление в структурированный JSON.

```bash
# Скопируйте оглавление из PDF в текстовый файл, затем:
python scripts/process_data/02_parse_toc.py toc.txt > data/toc/book_name_toc.json
```

Формат TOC (поддерживает любой уровень вложенности):
```json
{
  "meta": {
    "author": "Автор",
    "title": "Название книги",
    "offset": 0
  },
  "toc": [
    {
      "title": "Часть I",
      "page": null,
      "children": [
        {"title": "Глава 1", "page": 10, "children": []},
        {"title": "Глава 2", "page": 25, "children": []}
      ]
    }
  ]
}
```

> **Примечание**: Параметр `offset` в `meta` позволяет скорректировать номера страниц, если нумерация в PDF отличается от оглавления.

---

### Шаг 3: Чанкинг

Скрипт `03_save_chunks.py` создаёт parent chunks (главы) и child chunks (мелкие части для поиска).

```bash
# Quick mode - указываем имя книги:
python scripts/process_data/03_save_chunks.py \
    --name "1 Приемы педагогической техники" \
    --subdir andragogy \
    --source-type teacher

# Обработка всей директории:
python scripts/process_data/03_save_chunks.py \
    --books-dir data/books \
    --parsed-dir data/cache \
    --toc-dir data/toc \
    --source-type student
```

Параметр `--source-type`:
- `student` — книги по урбанистике (для проверки работ студентов)
- `teacher` — книги по андрагогике (для помощи преподавателям)

Результат:
- `data/chunks/book_name_parent.json` — parent chunks
- `data/chunks/book_name_child.json` — child chunks

---

### Шаг 4: Вычисление эмбеддингов

Скрипт `04_compute_embeddings.py` вычисляет эмбеддинги для child chunks.

```bash
python scripts/process_data/04_compute_embeddings.py

# С явными путями:
python scripts/process_data/04_compute_embeddings.py \
    --input-dir data/chunks \
    --output-dir data/child_chunks_with_embeddings

# Перезаписать существующие:
python scripts/process_data/04_compute_embeddings.py --force
```

Результат: `data/child_chunks_with_embeddings/` — JSON файлы с векторами.

---

### Шаг 5: Загрузка в Qdrant

Скрипт `05_load_to_qdrant.py` загружает чанки с эмбеддингами в векторную базу.

```bash
python scripts/process_data/05_load_to_qdrant.py

# Пересоздать коллекцию:
python scripts/process_data/05_load_to_qdrant.py --recreate

# Показать информацию о коллекции:
python scripts/process_data/05_load_to_qdrant.py --info
```

Результат: `data/qdrant_local/` — готовая векторная база.

---

### Полный пайплайн одной книги

```bash
# 1. Парсинг PDF
python scripts/process_data/01_parse_pdf.py --name "book" --subdir urban

# 2. Парсинг оглавления (ручной шаг: скопировать TOC из PDF в txt)
python scripts/process_data/02_parse_toc.py toc.txt > data/toc/book_toc.json

# 3. Чанкинг
python scripts/process_data/03_save_chunks.py --name "book" --subdir urban --source-type student

# 4. Эмбеддинги
python scripts/process_data/04_compute_embeddings.py

# 5. Загрузка в Qdrant
python scripts/process_data/05_load_to_qdrant.py
```

---

## Parent Document Retriever

Пайплайн реализует стратегию Parent Document Retriever:

- **Parent chunks** = целые главы (для полного контекста LLM)
- **Child chunks** = мелкие части (для точного векторного поиска)

Каждый child chunk содержит `parent_id` для получения полного контекста главы.

### Метаданные чанков

```python
{
    "source": "data/books/book.pdf",
    "book_title": "Название книги",
    "page_number": 45,
    "page_range": [45, 46, 47, 48],
    "chapter": "Часть II > Глава 3 > Раздел 3.1",
    "chunk_type": "child",  # или "parent"
    "parent_id": "uuid...",
    "chunk_id": "uuid...",
    "source_type": "student"  # или "teacher"
}
```

---

## Скрипты

### Обработка данных (`scripts/process_data/`)

| Скрипт | Описание |
|--------|----------|
| `01_parse_pdf.py` | Парсинг PDF через LlamaParse |
| `02_parse_toc.py` | Парсинг оглавления через Yandex Cloud LLM |
| `03_save_chunks.py` | Сохранение parent/child chunks |
| `04_compute_embeddings.py` | Вычисление эмбеддингов (YC) |
| `05_load_to_qdrant.py` | Загрузка в векторную БД |

### Утилиты (`scripts/`)

| Скрипт | Описание |
|--------|----------|
| `search.py` | Тестовый поиск по базе |
| `check_essay.py` | Проверка эссе (CLI) |
| `check_nir.py` | Проверка НИР (CLI) |
| `evaluate_rag.py` | Оценка качества RAG |
| `evaluate_rag_ragas.py` | Оценка RAG через RAGAS |

---

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `BOT_TOKEN` | Telegram Bot Token | — |
| `YC_API_KEY` | Yandex Cloud API Key | — |
| `YC_FOLDER_ID` | Yandex Cloud Folder ID | — |
| `LLAMA_CLOUD_API_KEY` | LlamaParse API Key | — |
| `BACKEND_URL` | URL backend сервера | `http://localhost:5001` |
| `DATA_DIR` | Директория данных | `./data` |
| `QDRANT_PATH` | Путь к Qdrant | `./data/qdrant_local` |
| `PARENT_CHUNKS_DIR` | Путь к parent chunks | `./data/chunks` |
