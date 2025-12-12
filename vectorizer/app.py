import os
import time
import logging
from typing import List
from dataclasses import dataclass
import numpy as np
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct


@dataclass
class QdrantConfig:
    """Конфигурация подключения к Qdrant"""

    host: str = os.getenv("QDRANT_HOST", "localhost")
    port: int = int(os.getenv("QDRANT_PORT", 6333))
    collection_name: str = os.getenv("QDRANT_COLLECTION", "documents")
    vector_size: int = int(os.getenv("VECTOR_SIZE", 384))
    timeout: int = int(os.getenv("QDRANT_TIMEOUT", 30))
    max_retries: int = int(os.getenv("MAX_RETRIES", 3))


def setup_logging():
    """Настройка логирования"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(__name__)


logger = setup_logging()


class QdrantManager:
    """Управление подключением и операциями с Qdrant"""

    def __init__(self, config: QdrantConfig):
        self.config = config
        self.client = None
        self.connect()

    def connect(self) -> bool:
        """Подключение к Qdrant с повторными попытками"""
        for attempt in range(self.config.max_retries):
            try:
                self.client = QdrantClient(
                    host=self.config.host,
                    port=self.config.port,
                    timeout=self.config.timeout,
                )

                # Проверка соединения
                self.client.get_collections()
                logger.info(
                    f"✅ Подключение к Qdrant {self.config.host}:{self.config.port} установлено"
                )
                return True

            except Exception as e:
                logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(2)
                else:
                    logger.error(
                        f"Не удалось подключиться после {self.config.max_retries} попыток"
                    )
                    raise

        return False

    def init_collection(self, recreate: bool = False) -> None:
        """Инициализация коллекции"""
        try:
            if recreate:
                logger.info(f"Удаление коллекции {self.config.collection_name}")
                self.client.delete_collection(self.config.collection_name)

            self.client.get_collection(self.config.collection_name)
            logger.info(f"Коллекция '{self.config.collection_name}' уже существует")

        except Exception:
            self.client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size, distance=Distance.COSINE
                ),
            )
            logger.info(f"Создана коллекция '{self.config.collection_name}'")

    def create_test_batch(self, batch_size: int = 5) -> List[PointStruct]:
        """Создание тестового батча векторов"""
        logger.info(f"Создание тестового батча из {batch_size} векторов")

        points = []
        for i in range(batch_size):
            vector = np.random.randn(self.config.vector_size).tolist()

            point = PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "text": f"Тестовый текст {i + 1}",
                    "source": "synthetic_data",
                    "batch_id": f"batch_{int(time.time())}",
                    "created_at": time.time(),
                },
            )
            points.append(point)

        return points

    def upload_batch(self, points: List[PointStruct]) -> bool:
        """Загрузка батча векторов в Qdrant"""
        try:
            self.client.upsert(
                collection_name=self.config.collection_name, points=points, wait=True
            )
            logger.info(f"Загружено {len(points)} векторов")
            return True
        except Exception as e:
            logger.error(f"Ошибка при загрузке: {e}")
            return False

    def verify_upload(self, expected_min: int = 1) -> bool:
        """Проверка загрузки данных"""
        try:
            count_result = self.client.count(
                collection_name=self.config.collection_name, exact=True
            )

            actual_count = count_result.count
            logger.info(f"В коллекции {actual_count} векторов")

            if actual_count >= expected_min:
                return True
            else:
                logger.warning(
                    f"Ожидалось минимум {expected_min}, а есть {actual_count}"
                )
                return False

        except Exception as e:
            logger.error(f"Ошибка при проверке: {e}")
            return False

    def health_check(self) -> bool:
        """Проверка здоровья подключения"""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


def main():
    """Основная функция"""

    config = QdrantConfig(
        host=os.getenv("QDRANT_HOST", "qdrant"),
        port=int(os.getenv("QDRANT_PORT", 6333)),
        collection_name="test_documents",
        vector_size=384,
    )

    logger.info(f"Конфигурация: {config}")

    try:
        manager = QdrantManager(config)

        if not manager.health_check():
            logger.error("Qdrant недоступен")
            return

        manager.init_collection()
        test_points = manager.create_test_batch(batch_size=3)

        if manager.upload_batch(test_points):
            logger.info("Тестовые данные загружены")
        else:
            logger.error("Ошибка загрузки")
            return

        # Проверка загрузки
        if manager.verify_upload(expected_min=len(test_points)):
            logger.info("Данные успешно верифицированы")
        else:
            logger.warning("Проблемы с верификацией данных")

    except Exception as e:
        logger.error(f"Ошибка: {e}")


if __name__ == "__main__":
    main()
