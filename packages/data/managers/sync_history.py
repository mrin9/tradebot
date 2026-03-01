import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pymongo import UpdateOne

from packages.data.connectors.xts_wrapper import XTSManager
from packages.utils.mongo import MongoRepository
from packages.utils.log_utils import setup_logger
from packages.config import settings
from packages.utils.date_utils import DateUtils

logger = setup_logger(__name__)

class HistoricalDataCollector:
    """
    Collector for Historical OHLC Data.
    """
    
    COMPRESSION_VALUE = 60 # 1 minute candles

    def sync_for_instrument(self, 
                            instrument_id: int, 
                            start_dt: datetime, 
                            end_dt: datetime, 
                            is_index: bool = False):
        """
        Fetches and syncs OHLC data for a specific instrument.
        Handles chunking to avoid API timeouts.
        """
        db = MongoRepository.get_db()
        collection_name = settings.NIFTY_CANDLE_COLLECTION if is_index else settings.OPTIONS_CANDLE_COLLECTION
        coll = db[collection_name]

        # Determine segment
        xts = XTSManager.get_market_client()
        segment = xts.EXCHANGE_NSECM if is_index else xts.EXCHANGE_NSEFO  # Simplified assumption for now

        # Chunking (7 days for large ranges, or just use 7 days default)
        chunks = DateUtils.get_date_chunks(start_dt, end_dt, chunk_size_days=7)
        
        total_upserted = 0
        
        logger.info(f"Syncing Instrument {instrument_id} ({'Index' if is_index else 'Option'}) from {start_dt} to {end_dt} ({len(chunks)} chunks)")

        for start_chunk, end_chunk in chunks:
            # XTS expects: "MMM DD YYYY HHMMSS" or similar?
            # Old script used: start_chunk.strftime(f"{FMT_XTS_API} 000000") where FMT_XTS_API = "%b %d %Y"
            # Let's check what DateUtils provides or what XTS SDK expects.
            # SDK documentation says: "May 25 2021 090000"
            
            start_str = start_chunk.strftime("%b %d %Y %H%M%S")
            end_str = end_chunk.strftime("%b %d %Y %H%M%S")
            
            try:
                response = xts.get_ohlc(
                    exchangeSegment=segment,
                    exchangeInstrumentID=instrument_id,
                    startTime=start_str,
                    endTime=end_str,
                    compressionValue=self.COMPRESSION_VALUE
                )
                
                if response and response.get('type') == 'success' and 'result' in response:
                    data_response = response['result'].get('dataReponse', '')
                    ticks = self._parse_ohlc_string(data_response, instrument_id)
                    
                    if ticks:
                        ops = [
                            UpdateOne(
                                {"i": t["i"], "t": t["t"]},
                                {"$set": t},
                                upsert=True
                            ) for t in ticks
                        ]
                        res = coll.bulk_write(ops, ordered=False)
                        total_upserted += res.upserted_count
                        # logger.debug(f" - Chunk {start_str}: {len(ticks)} ticks, {res.upserted_count} new.")
                    else:
                        pass # No data
                else:
                    logger.warning(f"Failed to fetch chunk {start_str}: {response}")
                    
            except Exception as e:
                logger.error(f"Error fetching chunk {start_str}: {e}")
                time.sleep(1) # Backoff
            
            # Avoid rate limits
            time.sleep(0.5)

        logger.info(f"Sync Complete for {instrument_id}. Total New Ticks: {total_upserted}")
        return total_upserted

    def sync_nifty_and_options_history(self, start_dt: datetime, end_dt: datetime, strike_count: int = None):
        """
        Two-phase sync: 
        1. Sync NIFTY for the whole range.
        2. Sync daily options for each day in range.
        """
        from packages.utils.market_utils import MarketUtils
        
        db = MongoRepository.get_db()
        
        # Phase 1: Sync NIFTY
        logger.info(f"--- PHASE 1: Syncing NIFTY Spot for range {start_dt} to {end_dt} ---")
        self.sync_for_instrument(settings.NIFTY_EXCHANGE_INSTRUMENT_ID, start_dt, end_dt, is_index=True)
        
        # Phase 2: Sync Daily Options
        logger.info(f"--- PHASE 2: Syncing Daily Options ---")
        
        # Loop by days
        current_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_loop_dt = end_dt.replace(hour=23, minute=59, second=59)
        
        while current_dt <= end_loop_dt:
            day_str = current_dt.strftime("%Y-%m-%d")
            
            # Derive contracts for this day
            contracts = MarketUtils.derive_target_contracts(db, current_dt, strike_count=strike_count)
            
            if not contracts:
                logger.warning(f"No contracts derived for {day_str}. Skipping.")
            else:
                logger.info(f"Syncing {len(contracts)} contracts for {day_str}...")
                day_start = current_dt.replace(hour=0, minute=0, second=0)
                day_end = current_dt.replace(hour=23, minute=59, second=59)
                
                for c in contracts:
                    inst_id = c['exchangeInstrumentID']
                    self.sync_for_instrument(inst_id, day_start, day_end, is_index=False)
                    # Small delay between instruments
                    time.sleep(0.1)
                    
            current_dt += timedelta(days=1)

    def _parse_ohlc_string(self, ohlc_str: str, instrument_id: int) -> List[Dict]:
        """
        Parses XTS OHLC string: Timestamp|Open|High|Low|Close|Volume|OI|
        """
        if not ohlc_str:
            return []
            
        ticks = []
        candles = ohlc_str.split(',')
        
        for candle in candles:
            if not candle: continue
            
            try:
                parts = candle.split('|')
                if len(parts) < 6: continue
                
                # Schema matching old project
                tick_ts = int(parts[0]) - settings.XTS_TIME_OFFSET
                tick = {
                    "i": instrument_id,
                    "t": tick_ts,
                    "isoDt": DateUtils.to_kolkata_iso(tick_ts),
                    "p": float(parts[4]), # Close
                    "o": float(parts[1]),
                    "h": float(parts[2]),
                    "l": float(parts[3]),
                    "c": float(parts[4]),
                    "v": int(parts[5]),
                    "s": 0 # Sequence (filled as 0 for historical)
                }
                ticks.append(tick)
            except Exception:
                pass
                
        return ticks
