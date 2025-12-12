import os
import time
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import numpy as np
import uuid


def wait_for_qdrant(host, port, timeout=30):
    """Ожидание запуска Qdrant"""
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
    """Инициализация коллекции в Qdrant"""
    collection_name = "test_documents"

    try:
        # Проверяем существующую коллекцию
        client.get_collection(collection_name)
        print(f"Коллекция '{collection_name}' уже существует")
    except Exception:
        # Создаем новую коллекцию
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )
        print(f"Создана коллекция '{collection_name}'")


def create_test_vectors(num_vectors=5, vector_size=384):
    """Создание тестовых векторов (нужно будет заменить на нормальные)"""
    print(f"Создаем {num_vectors} тестовых векторов размером {vector_size}")

    vectors = []
    for i in range(num_vectors):
        vector = np.random.randn(vector_size).tolist()

        # Создание точку с тестовыми данными
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": f"Тестовый текст {i + 1}",
                "source": "test_data",
                "chunk_id": i,
                "description": f"Это тестовая запись номер {i + 1} для проверки Qdrant",
                "timestamp": time.time(),
            },
        )
        vectors.append(point)

    return vectors


def main():
    """Основная функция - проверка работы Qdrant"""
    QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))

    wait_for_qdrant(QDRANT_HOST, QDRANT_PORT)
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    init_qdrant(client)

    # Добавление тестовых данных (нужно доработать для нормальных данных)
    test_vectors = create_test_vectors(num_vectors=3, vector_size=384)
    client.upsert(collection_name="test_documents", points=test_vectors, wait=True)

    # Проверки, что данные записались
    count_result = client.count(collection_name="test_documents", exact=True)

    print(f"Результат: {count_result.count} векторов записано")


if __name__ == "__main__":
    main()
