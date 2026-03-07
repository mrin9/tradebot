
from datetime import datetime
import pytz
from pymongo import MongoClient
from bson import ObjectId
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from packages.config import settings
from packages.utils.mongo import MongoRepository

MARKET_TZ = pytz.timezone("Asia/Kolkata")

def migrate():
    db = MongoRepository.get_db()
    collections = [settings.BACKTEST_RESULT_COLLECTION, "papertrades"]
    
    for col_name in collections:
        print(f"\nMigrating collection: {col_name}")
        coll = db[col_name]
        
        cursor = coll.find({})
        count = 0
        for doc in cursor:
            updates = {}
            unset = []
            
            # 1. ruleId -> rule_id
            if "ruleId" in doc:
                updates["rule_id"] = doc["ruleId"]
                unset.append("ruleId")
            
            # 2. strategyId (remove)
            if "strategyId" in doc:
                unset.append("strategyId")
                
            # 3. timestamp -> createdAt
            if "timestamp" in doc:
                ts = doc["timestamp"]
                # Convert to ISO if it's epoch or other format, but usually it's already ISO string in this project
                # If it's a date object or string, ensure it's ISO IST
                updates["createdAt"] = ts
                unset.append("timestamp")
            
            # 4. config fields
            config = doc.get("config", {})
            if config:
                new_config = config.copy()
                changed_config = False
                if "ruleId" in new_config:
                    new_config["rule_id"] = new_config.pop("ruleId")
                    changed_config = True
                if "option_type" in new_config:
                    new_config["strike_selection"] = new_config.pop("option_type")
                    changed_config = True
                if "no_break_even" in new_config:
                    new_config["break_even"] = not new_config.pop("no_break_even")
                    changed_config = True
                
                if changed_config:
                    updates["config"] = new_config
            
            # 5. Remove epochTime from tradeCycles
            trade_cycles = doc.get("tradeCycles", [])
            if trade_cycles:
                changed_cycles = False
                for cycle in trade_cycles:
                    # Entry
                    if "entry" in cycle and "epochTime" in cycle["entry"]:
                        del cycle["entry"]["epochTime"]
                        changed_cycles = True
                    # Exit
                    if "exit" in cycle and "epochTime" in cycle["exit"]:
                        del cycle["exit"]["epochTime"]
                        changed_cycles = True
                    # Targets
                    targets = cycle.get("targets", [])
                    for t in targets:
                        if "epochTime" in t:
                            del t["epochTime"]
                            changed_cycles = True
                
                if changed_cycles:
                    updates["tradeCycles"] = trade_cycles

            # 6. updatedAt (Ensure ISO IST)
            if "updatedAt" in doc:
                ua = doc["updatedAt"]
                # If ua is a string, we assume it's already IST ISO. 
                # To be safe, we can re-format it if needed, but let's stick to renaming for now.
                pass

            if updates or unset:
                update_query = {}
                if updates:
                    update_query["$set"] = updates
                if unset:
                    update_query["$unset"] = {f: "" for f in unset}
                
                coll.update_one({"_id": doc["_id"]}, update_query)
                count += 1
        
        print(f"Finished {col_name}. Updated {count} documents.")

if __name__ == "__main__":
    migrate()
