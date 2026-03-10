from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.config import settings
from packages.utils.log_utils import setup_logger

logger = setup_logger("MarketHistoryService")

class MarketHistoryService:
    """
    Consolidates historical data access, warmup logic, and replay orchestration.
    Used by both FundManager and LiveTradeEngine.
    """

    def __init__(self, db=None, fetch_ohlc_api_fn: Optional[Callable] = None):
        self.db = db if db is not None else MongoRepository.get_db()
        self.fetch_ohlc_api_fn = fetch_ohlc_api_fn

    def fetch_historical_candles(
        self, 
        instrument_id: int, 
        start_ts: float, 
        end_ts: float, 
        limit: int = settings.GLOBAL_WARMUP_CANDLES,
        segment: int = 1,
        use_api: bool = False
    ) -> List[Dict]:
        """
        Fetches historical 1m candles from API or DB.
        """
        if use_api and self.fetch_ohlc_api_fn:
            fmt = "%b %d %Y %H%M%S"
            start_dt = DateUtils.market_timestamp_to_datetime(start_ts)
            end_dt = DateUtils.market_timestamp_to_datetime(end_ts)
            
            logger.debug(f"🌐 Fetching API History for {instrument_id}: {start_dt} -> {end_dt}")
            history = self.fetch_ohlc_api_fn(segment, instrument_id, start_dt.strftime(fmt), end_dt.strftime(fmt))
            
            if history:
                return history[-limit:]
            
            logger.warning(f"⚠️ API returned no data for {instrument_id}. Falling back to DB.")

        # DB Logic
        collection = settings.NIFTY_CANDLE_COLLECTION if instrument_id == 26000 else settings.OPTIONS_CANDLE_COLLECTION
        
        query = {"i": instrument_id, "t": {"$lte": end_ts}}
        if start_ts:
            query["t"]["$gte"] = start_ts
            
        history_cursor = list(self.db[collection].find(query).sort("t", -1).limit(limit))
        return sorted(history_cursor, key=lambda x: x['t'])

    def run_warmup(
        self, 
        fund_manager, 
        instrument_id: int, 
        current_ts: float, 
        category: str,
        limit: int = settings.GLOBAL_WARMUP_CANDLES,
        use_api: bool = False
    ) -> int:
        """
        Orchestrates the warmup for a specific instrument and category inside FundManager.
        """
        # Determine sync range (standard 4 days covers weekends)
        start_ts = current_ts - (3600 * 24 * 4)
        
        # Segment 1 for Nifty (SPOT), 2 for Options (NSEFO)
        segment = 1 if instrument_id == 26000 else 2
        
        history = self.fetch_historical_candles(
            instrument_id=instrument_id,
            start_ts=start_ts,
            end_ts=current_ts,
            limit=limit,
            segment=segment,
            use_api=use_api
        )
        
        if not history:
            logger.warning(f"No history found for warmup: {category} ({instrument_id}) at {current_ts}")
            return 0
            
        count = 0
        # Suppress heartbeats and signals during warmup
        saved_warming_up = fund_manager.is_warming_up
        fund_manager.is_warming_up = True
        
        try:
            for candle in history:
                if candle['t'] < current_ts:
                    fund_manager.on_tick_or_base_candle(candle)
                    count += 1
        finally:
            fund_manager.is_warming_up = saved_warming_up
            
        logger.info(f"✅ Warmup complete for {category} ({instrument_id}): {count} candles processed.")
        return count

    def run_full_backtest_warmup(self, fund_manager, start_date: str, warmup_candles: int = None):
        """
        Feeds historical data into FundManager to warm up indicators before backtest.
        """
        if warmup_candles is None:
            warmup_candles = settings.GLOBAL_WARMUP_CANDLES
            
        if warmup_candles <= 0:
            return

        logger.info(f"🔥 Warming up indicators with {warmup_candles} candles...")
        dt = DateUtils.parse_iso(start_date)
        start_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())
        
        warmup_cursor = self.db[settings.NIFTY_CANDLE_COLLECTION].find(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID, "t": {"$lt": start_ts}}
        ).sort("t", -1).limit(warmup_candles)
        
        warmup_ticks = list(warmup_cursor)
        warmup_ticks.reverse() # Chronological
        
        if warmup_ticks:
            logger.info(f"Feeding {len(warmup_ticks)} warmup candles.")
            # Temporarily disable logging and TRADING for warmup
            original_log_heartbeat = fund_manager.log_heartbeat
            fund_manager.log_heartbeat = False
            fund_manager.is_warming_up = True
            
            original_on_signal = fund_manager.position_manager.on_signal
            fund_manager.position_manager.on_signal = lambda x: None
            
            for tick in warmup_ticks:
                fund_manager.on_tick_or_base_candle(tick)
            
            fund_manager.log_heartbeat = original_log_heartbeat
            fund_manager.is_warming_up = False
            fund_manager.position_manager.on_signal = original_on_signal
        else:
            logger.warning("No historical data found for warmup.")
    def get_last_nifty_price(self, dt: datetime) -> Optional[float]:
        """
        Centrally retrieves the last known NIFTY spot price for a given day.
        """
        start_ts = DateUtils.to_timestamp(dt, end_of_day=False)
        end_ts = DateUtils.to_timestamp(dt, end_of_day=True)
        
        doc = self.db[settings.NIFTY_CANDLE_COLLECTION].find_one(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID, "t": {"$gte": start_ts, "$lte": end_ts}},
            sort=[("t", -1)]
        )
        
        return doc['p'] if doc else None
