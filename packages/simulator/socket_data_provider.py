import asyncio
import json
import time
import heapq
from datetime import datetime
from typing import List, Dict
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
            # Note: Pymongo cursors are iterable. merge is efficient for already sorted inputs.
            # We wrap doc in a tuple (timestamp, doc) for sorting
            merged_stream = heapq.merge(
                ((doc['t'], doc) for doc in nifty_cursor),
                ((doc['t'], doc) for doc in options_cursor),
                key=lambda x: x[0]
            )

            logger.info(f"Replaying {mode} from {start_dt} to {end_dt}...")
            
            count = 0
            for timestamp, doc in merged_stream:
                if not self.running: break
                
                inst_id = doc['i']
                base_t = doc['t']
                
                if mode == 'candle':
                    await self._emit_candle(inst_id, doc)
                    if delay > 0: await asyncio.sleep(delay)
                else:
                    # Tick Breakdown logic (4 sub-ticks per 1-min bar)
                    vol_chunk = doc.get('v', 0) // 4
                    
                    # 1. Open
                    await self._emit_tick(inst_id, doc['o'], base_t, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 2. High
                    if not self.running: break
                    await self._emit_tick(inst_id, doc['h'], base_t + 15, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 3. Low
                    if not self.running: break
                    await self._emit_tick(inst_id, doc['l'], base_t + 30, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                    
                    # 4. Close
                    if not self.running: break
                    await self._emit_tick(inst_id, doc['c'], base_t + 59, vol_chunk)
                    if delay > 0: await asyncio.sleep(delay)
                
                count += 1
                if count % 10 == 0:
                    await asyncio.sleep(0) # Yield control

            logger.info("Replay Finished.")
            await self.sio.emit('simulation_complete', {'status': 'done'})
            self.running = False
            
        except asyncio.CancelledError:
            logger.info("Simulation Cancelled.")
        except Exception as e:
            logger.error(f"Simulation Error: {e}", exc_info=True)
            await self.sio.emit('error', {'message': f"Streaming failed: {str(e)}"})
            self.running = False

    async def _emit_candle(self, instrument_id, doc):
        payload = {
            "ExchangeInstrumentID": instrument_id,
            "BarData": {
                "Open": doc['o'],
                "High": doc['h'],
                "Low": doc['l'],
                "Close": doc['c'],
                "Volume": doc.get('v', 0),
                "Timestamp": doc['t'] + settings.XTS_TIME_OFFSET
            }
        }
        await self.sio.emit('1505-json-full', payload)

    async def _emit_tick(self, instrument_id, price, timestamp, volume):
        payload = {
            "ExchangeInstrumentID": instrument_id,
            "Touchline": {
                "LastTradedPrice": float(price),
                "LastTradedQuantity": int(volume),
                "LastTradedTime": int(timestamp) + settings.XTS_TIME_OFFSET,
                "TotalTradedQuantity": 0,
                "PercentChange": 0.0, 
                "Open": 0.0,
                "High": 0.0,
                "Low": 0.0,
                "Close": 0.0
            }
        }
        await self.sio.emit('1501-json-full', payload)
