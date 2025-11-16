import os
import time
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import numpy as np


def wait_for_qdrant(host, port, timeout=30):
    """Ждем пока Qdrant запустится"""
    print(f"Ждем запуск Qdrant на {host}:{port}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            client = QdrantClient(host=host, port=port, timeout=5)
            client.get_collections()
            print("Qdrant готов!")
            return True
        except Exception as e:
            print(f"Ожидание Qdrant... ({e})")
            time.sleep(2)
    raise Exception(f"Qdrant не запустился за {timeout} секунд")


def init_qdrant(client):
    """Инициализируем коллекцию в Qdrant"""
    collection_name = "documents"

    try:
        # Проверяем существующую коллекцию
        client.get_collection(collection_name)
        print(f"Коллекция '{collection_name}' уже существует")
    except Exception:
        # Создаем новую коллекцию
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE)
        )
        print(f"Создана коллекция '{collection_name}'")


def process_pdf(file_path, client, model):
    """Обрабатываем PDF и загружаем в Qdrant"""
    print(f"Обрабатываем PDF: {file_path}")

    # Читаем PDF
    reader = PdfReader(file_path)
    text_chunks = []

    # Извлекаем текст со всех страниц
    for page_num, page in enumerate(reader.pages):
        text = page.extract_text()
        if text.strip():  # Если страница не пустая
            # Просто разбиваем на чанки по предложениям (упрощенно)
            sentences = [s.strip() for s in text.split('.') if s.strip()]
            # Объединяем в чанки по 3-5 предложений
            chunk_size = 3
            for i in range(0, len(sentences), chunk_size):
                chunk = '. '.join(sentences[i:i + chunk_size]) + '.'
                text_chunks.append({
                    'text': chunk,
                    'source': os.path.basename(file_path),
                    'page': page_num + 1,
                    'chunk_id': len(text_chunks)
                })

    print(f"Извлечено {len(text_chunks)} текстовых чанков")

    # Создаем эмбеддинги и загружаем в Qdrant
    points = []
    for chunk in text_chunks:
        # Создаем эмбеддинг для текста
        embedding = model.encode(chunk['text']).tolist()

        # Создаем точку для Qdrant
        point = {
            'id': chunk['chunk_id'],
            'vector': embedding,
            'payload': chunk
        }
        points.append(point)

    # Загружаем в Qdrant
    client.upsert(
        collection_name="documents",
        points=points
    )

    print(f"Загружено {len(points)} векторов в Qdrant")
    return len(points)


def main():
    # Конфигурация
    QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
    QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))
    PDFS_DIR = '/data/pdfs'

    # Ждем пока Qdrant запустится
    wait_for_qdrant(QDRANT_HOST, QDRANT_PORT)

    # Инициализируем клиент и модель
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    model = SentenceTransformer('all-MiniLM-L6-v2')

    # Инициализируем Qdrant
    init_qdrant(client)

    # Обрабатываем все PDF файлы в директории
    if not os.path.exists(PDFS_DIR):
        print(f"Директория {PDFS_DIR} не существует")
        return

    pdf_files = [f for f in os.listdir(PDFS_DIR) if f.endswith('.pdf')]

    if not pdf_files:
        print(f"В директории {PDFS_DIR} нет PDF файлов")
        return

    total_vectors = 0
    for pdf_file in pdf_files:
        pdf_path = os.path.join(PDFS_DIR, pdf_file)
        try:
            vectors_count = process_pdf(pdf_path, client, model)
            total_vectors += vectors_count
        except Exception as e:
            print(f"Ошибка при обработке {pdf_file}: {e}")

    print(f"\n✅ Готово! Всего загружено {total_vectors} векторов")

    # Проверяем что данные есть
    collections = client.get_collections()
    print(f"\nДоступные коллекции: {[col.name for col in collections.collections]}")

    # Показываем статистику коллекции
    collection_info = client.get_collection("documents")
    print(f"Коллекция 'documents': {collection_info.vectors_count} векторов")


if __name__ == "__main__":
    main()
