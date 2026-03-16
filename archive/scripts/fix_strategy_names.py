import logging

from packages.utils.mongo import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    db = get_db()
    col = db["backtest_results"]

    # Find records where config.strategy is missing but config.rule_id exists
    cursor = col.find({"config.strategy": {"$exists": False}, "config.rule_id": {"$exists": True}})

    count = 0
    for doc in cursor:
        rule_id = doc["config"].get("rule_id")
        if rule_id:
            col.update_one({"_id": doc["_id"]}, {"$set": {"config.strategy": rule_id}})
            count += 1

    logger.info(f"✅ Migrated {count} records. config.strategy set to config.rule_id.")


if __name__ == "__main__":
    migrate()
