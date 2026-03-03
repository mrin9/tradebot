from packages.utils.mongo import MongoRepository
from packages.config import settings
from packages.utils.log_utils import setup_logger
from pymongo import ASCENDING, DESCENDING

logger = setup_logger(__name__)

class DatabaseManager:
    """
    Manages database schema, specifically ensuring indexes exist.
    """

    @classmethod
    def ensure_all_indexes(cls):
        """
        Ensures all required indexes are created for all core collections.
        """
        db = MongoRepository.get_db()
        logger.info("Synchronizing database indexes...")

        try:
            # 1. Instrument Master
            master_coll = db[settings.INSTRUMENT_MASTER_COLLECTION]
            master_coll.create_index([("exchangeInstrumentID", ASCENDING)], unique=True)
            master_coll.create_index([("name", ASCENDING), ("series", ASCENDING)])
            master_coll.create_index([("contractExpiration", ASCENDING)])

            # 2. NIFTY Candles
            nifty_coll = db[settings.NIFTY_CANDLE_COLLECTION]
            # Primary lookup: Instrument + Timestamp
            nifty_coll.create_index([("i", ASCENDING), ("t", ASCENDING)], unique=True)
            # Time-based sorting for range queries
            nifty_coll.create_index([("t", DESCENDING)])
            # ISO Date for human-readable queries
            nifty_coll.create_index([("isoDt", DESCENDING)])

            # 3. Options Candles
            options_coll = db[settings.OPTIONS_CANDLE_COLLECTION]
            options_coll.create_index([("i", ASCENDING), ("t", ASCENDING)], unique=True)
            options_coll.create_index([("t", DESCENDING)])
            options_coll.create_index([("isoDt", DESCENDING)])

            # 4. Active Contracts
            active_coll = db[settings.ACTIVE_CONTRACT_COLLECTION]
            active_coll.create_index([("exchangeInstrumentID", ASCENDING)], unique=True)
            active_coll.create_index([("activeDates", ASCENDING)])

            # 5. Backtest Results
            results_coll = db[settings.BACKTEST_RESULT_COLLECTION]
            results_coll.create_index([("resultId", ASCENDING)], unique=True)
            results_coll.create_index([("timestamp", DESCENDING)])

            logger.info("✅ Database indexes synchronized successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to synchronize indexes: {e}")
            # We don't raise here to prevent startup failure if index creation fails 
            # (e.g. background indexing already in progress), but it will be logged.

if __name__ == "__main__":
    # Allow running as a standalone script
    DatabaseManager.ensure_all_indexes()
