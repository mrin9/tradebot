from datetime import datetime, timedelta
from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.mongo import MongoRepository
from packages.utils.log_utils import setup_logger
from packages.config import settings
from packages.utils.market_utils import MarketUtils
from packages.utils.date_utils import DateUtils

logger = setup_logger(__name__)

class MasterDataCollector:
    """
    Collector for Master Instrument Data (Contract Specs).
    Fetches raw master dump from XTS, parses it, filters irrelevant contracts,
    and updates the local MongoDB.
    """

    def update_master_db(self):
        """
        Main execution method to sync master data.
        """
        xts = XTSManager.get_market_client()

        # 1. Fetch Data
        segments = [xts.EXCHANGE_NSECM, xts.EXCHANGE_NSEFO]
        logger.info(f"Fetching master data for segments: {segments}")
        
        response = xts.get_master(exchangeSegmentList=segments)
        
        if not isinstance(response, dict) or response.get('type') != 'success' or 'result' not in response:
            logger.error(f"Failed to fetch master data: {response}")
            return False

        content = response['result']
        logger.info(f"Master data received. Size: {len(content)} chars. Parsing...")

        # 2. Parse
        raw_data = MarketUtils.parse_xts_master_data(content)
        
        # 3. Filter Logic (Replicated from legacy update_master_instrument.py)
        filtered_data = self._filter_instruments(raw_data)
        
        if not filtered_data:
            logger.warning("No instruments remained after filtering.")
            return False

        # 4. Update DB
        self._update_mongo(filtered_data)
        return True

    def _filter_instruments(self, raw_data):
        now = datetime.now(DateUtils.MARKET_TZ)
        # 30 days window logic
        cutoff_date = now + timedelta(days=30)
        
        filtered = []
        skipped_expired = 0
        skipped_future = 0
        skipped_equity = 0

        # We need naive ISO strings for comparison with XTS format strings
        # XTS Expiry format: YYYY-MM-DDT00:00:00 (usually)
        # Let's ensure strict string comparison
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
        cutoff_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S")

        for doc in raw_data:
            # Filter 1: Remove Instruments with Type 8 (Equity?) - legacy rule
            if doc.get("instrumentTypeNum") == 8:
                skipped_equity += 1
                continue

            # Filter 2: NSEFO Expiry Checks
            if doc.get("exchangeSegment") == "NSEFO":
                expiry = doc.get("contractExpiration")
                if not expiry:
                    # Keep if no expiry (e.g. continuous futures? usually have expiry though)
                    filtered.append(doc)
                    continue

                if expiry < now_str:
                    skipped_expired += 1
                    continue
                
                if expiry > cutoff_str:
                    skipped_future += 1
                    continue
            
            # If passed all checks
            filtered.append(doc)

        logger.info(f"Filtered {len(raw_data)} -> {len(filtered)} instruments.")
        logger.info(f"Skipped: Equity={skipped_equity}, Expired={skipped_expired}, Future={skipped_future}")
        return filtered

    def _update_mongo(self, data):
        db = MongoRepository.get_db()
        coll = db[settings.INSTRUMENT_MASTER_COLLECTION]
        
        # Mark all as old
        logger.info("Marking existing instruments as 'isOld=True'...")
        coll.update_many({}, {"$set": {"isOld": True}})
        
        # Tag new data
        for d in data:
            d["isOld"] = False
            
        # Bulk Upsert
        logger.info(f"Upserting {len(data)} instruments to MongoDB...")
        
        # Using DB handler or raw pymongo
        # We can use bulk_write for efficiency
        from pymongo import UpdateOne
        ops = [
            UpdateOne(
                {"exchangeInstrumentID": d["exchangeInstrumentID"]}, 
                {"$set": d}, 
                upsert=True
            ) for d in data
        ]
        
        if ops:
            res = coll.bulk_write(ops, ordered=False)
            logger.info(f"Sync Complete. Matched: {res.matched_count}, Upserted: {res.upserted_count}")

