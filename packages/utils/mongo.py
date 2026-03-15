from pymongo import MongoClient

from packages.settings import settings
from packages.utils.log_utils import setup_logger

logger = setup_logger(__name__)


class MongoRepository:
    """
    Centralized MongoDB Handler.
    """

    _client = None
    _db = None

    @classmethod
    def get_db(cls):
        if cls._db is None:
            logger.info(f"Connecting to MongoDB: {settings.MONGODB_URI} ({settings.DB_NAME})")
            try:
                cls._client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
                cls._db = cls._client[settings.DB_NAME]
                # Trigger checking connection
                cls._client.admin.command("ping")
                logger.info("MongoDB Connection Established and Pinged.")
            except Exception as e:
                logger.error(f"MongoDB Connection Failed: {e}")
                raise e
        return cls._db

    @classmethod
    def get_collection(cls, collection_name: str):
        return cls.get_db()[collection_name]

    @classmethod
    def close(cls):
        cls._client = None
        cls._db = None
        logger.info("MongoDB Connection Closed.")


get_db = MongoRepository.get_db
