import os
import time
import logging
from typing import List, Optional
from dataclasses import dataclass
import numpy as np
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct


@dataclass
class QdrantConfig:
    """
    Конфигурационные параметры для подключения к Qdrant векторной базе данных.

    Attributes:
        host (str): Хост сервера Qdrant. По умолчанию 'localhost' или значение
                   из переменной окружения QDRANT_HOST.
        port (int): Порт сервера Qdrant. По умолчанию 6333 или значение из
                   переменной окружения QDRANT_PORT.
        collection_name (str): Название коллекции для хранения векторов.
                              По умолчанию 'documents' или значение из
                              переменной окружения QDRANT_COLLECTION.
        vector_size (int): Размерность векторов. По умолчанию 384 или значение
                          из переменной окружения VECTOR_SIZE.
        timeout (int): Таймаут подключения в секундах. По умолчанию 30 или
                      значение из переменной окружения QDRANT_TIMEOUT.
        max_retries (int): Максимальное количество попыток подключения.
                          По умолчанию 3 или значение из переменной
                          окружения MAX_RETRIES.
    """

    host: str = os.getenv("QDRANT_HOST", "localhost")
    port: int = int(os.getenv("QDRANT_PORT", 6333))
    collection_name: str = os.getenv("QDRANT_COLLECTION", "documents")
    vector_size: int = int(os.getenv("VECTOR_SIZE", 384))
    timeout: int = int(os.getenv("QDRANT_TIMEOUT", 30))
    max_retries: int = int(os.getenv("MAX_RETRIES", 3))


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """
    Настройка логирования для приложения.

    Args:
        log_level (str): Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            По умолчанию 'INFO'.

    Returns:
        logging.Logger: Настроенный логгер.
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(),  # Вывод в консоль
            logging.FileHandler("qdrant_operations.log"),  # Вывод в файл
        ],
    )

    return logging.getLogger(__name__)


logger = setup_logging()


class QdrantManager:
    """
    Менеджер для управления подключением и операциями с Qdrant.

    Этот класс предоставляет методы для подключения к Qdrant, создания коллекций,
    загрузки векторов и проверки целостности данных.

    Attributes:
        config (QdrantConfig): Конфигурация подключения.
        client (Optional[QdrantClient]): Клиент для работы с Qdrant.

    Example:
        >>> config = QdrantConfig(host='localhost', port=6333)
        >>> manager = QdrantManager(config)
        >>> manager.init_collection()
        >>> points = manager.create_test_batch(5)
        >>> manager.upload_batch(points)
        >>> manager.verify_upload(5)
    """

    def __init__(self, config: QdrantConfig) -> None:
        """
        Инициализирует QdrantManager с заданной конфигурацией.

        Args:
            config (QdrantConfig): Конфигурация для подключения к Qdrant.

        Note:
            Автоматически вызывает метод connect() для установки соединения.
        """
        self.config = config
        self.client: Optional[QdrantClient] = None
        self.connect()

    def connect(self) -> bool:
        """
        Устанавливает подключение к серверу Qdrant с повторными попытками.

        Returns:
            bool: True если подключение установлено успешно, иначе False.

        Raises:
            ConnectionError: Если не удалось подключиться после всех попыток.

        Note:
            Использует экспоненциальную задержку между попытками.
            Проверяет соединение через вызов get_collections().
        """
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
                    f"Подключение к Qdrant {self.config.host}:{self.config.port} установлено"
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
                    raise ConnectionError(f"Не удалось подключиться к Qdrant: {e}")

        return False

    def init_collection(self, recreate: bool = False) -> None:
        """
        Инициализирует коллекцию в Qdrant.

        Args:
            recreate (bool): Если True, удаляет существующую коллекцию перед созданием.
                           Если False, использует существующую коллекцию.
                           По умолчанию False.

        Note:
            Создает коллекцию с косинусной метрикой расстояния и заданным размером вектора.
            Если коллекция уже существует и recreate=False, просто логирует этот факт.
        """
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
                    size=self.config.vector_size,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Создана коллекция '{self.config.collection_name}'")

    def create_test_batch(self, batch_size: int = 5) -> List[PointStruct]:
        """
        Создает батч тестовых векторов со случайными значениями.

        Args:
            batch_size (int): Количество векторов в батче. По умолчанию 5.

        Returns:
            List[PointStruct]: Список точек (векторов) для загрузки в Qdrant.
        """
        logger.info(f"Создание тестового батча из {batch_size} векторов")

        points: List[PointStruct] = []
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
        """
        Загружает батч векторов в коллекцию Qdrant.

        Args:
            points (List[PointStruct]): Список точек для загрузки.

        Returns:
            bool: True если загрузка прошла успешно, иначе False.

        Note:
            Использует параметр wait=True для синхронной загрузки.
        """
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
        """
        Проверяет, что данные были успешно загружены в коллекцию.

        Args:
            expected_min (int): Минимальное ожидаемое количество векторов в коллекции.
                              По умолчанию 1.

        Returns:
            bool: True если количество векторов соответствует ожиданиям, иначе False.
        """
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
        """
        Проверяет доступность сервера Qdrant.

        Returns:
            bool: True если сервер доступен и отвечает, иначе False.
        """
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False


def main() -> None:
    """
    Основная функция для демонстрации работы с Qdrant.

    Выполняет следующие шаги:
    1. Загружает конфигурацию из переменных окружения
    2. Создает менеджер Qdrant
    3. Проверяет доступность сервера
    4. Инициализирует коллекцию
    5. Создает и загружает тестовые векторы
    6. Проверяет успешность загрузки
    """

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
            logger.info("Тестовые данные успешно загружены")
        else:
            logger.error("Ошибка загрузки тестовых данных")
            return

        # Верификация загрузки
        if manager.verify_upload(expected_min=len(test_points)):
            logger.info("Данные успешно верифицированы")
        else:
            logger.warning("Проблемы с верификацией данных")

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)


if __name__ == "__main__":
    """
    Точка входа в приложение.

    При прямом запуске скрипта вызывает основную функцию main().
    """
    main()
