import asyncio
import json
import time
import heapq
from datetime import datetime
from typing import List, Dict, Any
import socketio

from packages.utils.mongo import MongoRepository
from packages.config import settings
from packages.utils.log_utils import setup_logger

logger = setup_logger("SocketDataProvider")

class SocketDataProvider:
    def __init__(self, sio: socketio.AsyncServer):
        self.sio = sio
        self.running = False
        self.task = None

    async def start_simulation(self, instrument_id: int | None, start_dt: datetime, end_dt: datetime, delay: float = 0.01, mode: str = 'tick'):
        """
        Starts the simulation as a background task.
        Cancels any existing task.
        """
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        self.running = True
        logger.info(f"Starting Simulation Task for {instrument_id if instrument_id else 'ALL'} ({mode})")
        
        self.task = asyncio.create_task(
            self.stream_data(instrument_id, start_dt, end_dt, delay, mode)
        )

    async def stop_simulation(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.running = False
        logger.info("Simulation Stopped.")

    async def stream_data(self, instrument_id: int | None, start_dt: datetime, end_dt: datetime, delay: float, mode: str):
        try:
            db = MongoRepository.get_db()
            
            # Query constraints
            query = {"t": {"$gte": int(start_dt.timestamp()), "$lte": int(end_dt.timestamp())}}
            if instrument_id:
                query["i"] = instrument_id

            # Prepare cursors from both collections
            nifty_coll = db[settings.NIFTY_CANDLE_COLLECTION]
            options_coll = db[settings.OPTIONS_CANDLE_COLLECTION]
            
            nifty_cursor = nifty_coll.find(query).sort("t", 1)
            options_cursor = options_coll.find(query).sort("t", 1)

            # Use heapq.merge to union and sort by time 't'
            # We add a priority (0 for options, 1 for nifty) to ensure 
            # Option indicators are updated before the Spot candle close triggers strategy evaluation.
            merged_stream = heapq.merge(
                ((doc['t'], 1, doc) for doc in nifty_cursor),
                ((doc['t'], 0, doc) for doc in options_cursor),
                key=lambda x: (x[0], x[1])
            )

            logger.info(f"Replaying {mode} from {start_dt} to {end_dt}...")
            
            count = 0
            for timestamp, priority, doc in merged_stream:
                if not self.running: break
                
                if count % 1000 == 0:
                    logger.info(f"Replay progress: {count} docs emitted. Current T: {timestamp}")
                
                inst_id = doc['i']
                base_t = doc['t']
                
                if mode == 'candle':
                    # Emit 1505 Bar Data
                    await self._emit_1505_candle(inst_id, doc)
                    if delay > 0: await asyncio.sleep(delay)
                else:
                    # Tick Breakdown logic (4 sub-ticks per 1-min bar)
                    # Note: base_t in our DB is end-of-minute (XX:XX:59)
                    start_t = base_t - 59
                    vol_chunk = doc.get('v', 0) // 4
                    
                    # 1. Open
                    await self._emit_1501_tick(inst_id, doc['o'], start_t, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 2. High
                    if not self.running: break
                    await self._emit_1501_tick(inst_id, doc['h'], start_t + 15, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 3. Low
                    if not self.running: break
                    await self._emit_1512_snapshot(inst_id, doc['l'], start_t + 30, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 4. Close
                    if not self.running: break
                    await self._emit_1501_tick(inst_id, doc['c'], base_t, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                
                count += 1
                if count % 100 == 0:
                    await asyncio.sleep(0) # Yield control

            logger.info(f"Replay Finished. Total docs emitted: {count}")
            await self.sio.emit('simulation_complete', {'status': 'done'})
            self.running = False
            
        except asyncio.CancelledError:
            logger.info("Simulation Cancelled.")
        except Exception as e:
            logger.error(f"Simulation Error: {e}", exc_info=True)
            await self.sio.emit('error', {'message': f"Streaming failed: {str(e)}"})
            self.running = False

    def _get_xts_timestamp(self, ts: int) -> int:
        """Adds XTS_TIME_OFFSET (19800s) to pure UTC epoch to match XTS IST-shifted epoch."""
        return ts + settings.XTS_TIME_OFFSET

    async def _emit_1501_tick(self, instrument_id: int, price: float, timestamp: int, volume: int):
        """Emits Touchline (1501) full and partial events."""
        xts_ts = self._get_xts_timestamp(timestamp)
        
        # 1. Full JSON (Flat structure as per user request)
        payload = {
            "MessageCode": 1501,
            "ExchangeSegment": 1,
            "ExchangeInstrumentID": instrument_id,
            "ExchangeTimeStamp": xts_ts,
            "LastTradedPrice": float(price),
            "LastTradedQunatity": int(volume),
            "TotalTradedQuantity": 0,
            "LastTradedTime": xts_ts,
            "LastUpdateTime": xts_ts,
            "PercentChange": 0.0,
            "Open": 0.0,
            "High": 0.0,
            "Low": 0.0,
            "Close": 0.0,
            "BidInfo": {"Price": 0.0, "Size": 0, "TotalOrders": 0},
            "AskInfo": {"Price": 0.0, "Size": 0, "TotalOrders": 0}
        }
        await self.sio.emit('1501-json-full', payload)
        
        # 2. Partial String
        # Format: i:22,ltp:1567.95,ltq:20,v:0,ltt:1205682251
        partial_str = f"i:{instrument_id},ltp:{price},ltq:{volume},v:0,ltt:{xts_ts}"
        await self.sio.emit('1501-json-partial', partial_str)

    async def _emit_1505_candle(self, instrument_id: int, doc: Dict):
        """Emits Candle (1505) full and partial events."""
        xts_ts = self._get_xts_timestamp(doc['t'])
        
        # 1. Full JSON (Nested under BarData as per XTS standard and existing tests)
        # Note: Even if user prefers flat, 1505 usually wraps in BarData.
        # But per user's request for "exact structure" and showing 1501 as flat, 
        # I'll provide flat for 1505 if they implied all should be flat.
        # However, MarketUtils.normalize_1505_candle_event expects BarData.
        # So I will keep BarData for compatibility but include MessageCode if flat is needed.
        # Let's try to follow what MarketUtils expects while being "Exact".
        payload = {
            "MessageCode": 1505,
            "ExchangeInstrumentID": instrument_id,
            "BarData": {
                "Open": doc['o'],
                "High": doc['h'],
                "Low": doc['l'],
                "Close": doc['c'],
                "Volume": doc.get('v', 0),
                "Timestamp": xts_ts
            }
        }
        await self.sio.emit('1505-json-full', payload)
        
        # 2. Partial String
        partial_str = f"i:{instrument_id},t:{xts_ts},o:{doc['o']},h:{doc['h']},l:{doc['l']},c:{doc['c']},v:{doc.get('v', 0)}"
        await self.sio.emit('1505-json-partial', partial_str)

    async def _emit_1512_snapshot(self, instrument_id: int, price: float, timestamp: int, volume: int):
        """Emits Snapshot/L2 (1512) full and partial events."""
        xts_ts = self._get_xts_timestamp(timestamp)
        
        # 1. Full JSON
        payload = {
            "MessageCode": 1512,
            "ExchangeSegment": 1,
            "ExchangeInstrumentID": instrument_id,
            "ExchangeTimeStamp": xts_ts,
            "LastTradedPrice": float(price),
            "LastTradedQuantity": int(volume),
            "TotalTradedQuantity": 0
        }
        await self.sio.emit('1512-json-full', payload)
        
        # 2. Partial String
        partial_str = f"i:{instrument_id},ltp:{price},ltq:{volume},v:0,ltt:{xts_ts}"
        await self.sio.emit('1512-json-partial', partial_str)
