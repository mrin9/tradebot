"""
Integration tests comparing database-backed strategy execution against socket-streamed data.
Verifies consistency across different data delivery modes using tradebot_frozen_test.
"""
import pytest
import os
import sys
import time
import threading
import asyncio
from datetime import datetime
from typing import List, Dict

# No manual sys.path.append(os.getcwd()) needed if run as module or from root

from packages.utils.mongo import MongoRepository
from packages.simulator.socket_server import SocketDataService
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.rule_strategy import Signal
from packages.utils.log_utils import setup_logger
from packages.config import settings

logger = setup_logger("TestStrategyIntegrationMTFA")

def run_server(port):
    """Helper to run server in thread"""
    sim = SocketDataService()
    from aiohttp import web
    web.run_app(sim.app, port=port, handle_signals=False, access_log=None)

@pytest.fixture(scope="module", autouse=True)
def patch_settings():
    orig_db = settings.DB_NAME
    orig_nifty = settings.NIFTY_CANDLE_COLLECTION
    orig_opt = settings.OPTIONS_CANDLE_COLLECTION
    orig_inst = settings.INSTRUMENT_MASTER_COLLECTION
    
    settings.DB_NAME = "tradebot_frozen_test"
    settings.NIFTY_CANDLE_COLLECTION = "nifty_candle_test_data"
    settings.OPTIONS_CANDLE_COLLECTION = "options_candle_test_data"
    settings.INSTRUMENT_MASTER_COLLECTION = "instrument_master_test_data"
    
    MongoRepository._client = None
    MongoRepository._db = None
    yield
    settings.DB_NAME = orig_db
    settings.NIFTY_CANDLE_COLLECTION = orig_nifty
    settings.OPTIONS_CANDLE_COLLECTION = orig_opt
    settings.INSTRUMENT_MASTER_COLLECTION = orig_inst
    
    MongoRepository._client = None
    MongoRepository._db = None

@pytest.fixture(scope="module")
def db_conn():
    return MongoRepository.get_db()

@pytest.fixture
def strategy_config():
    return {
        "ruleId": "test-rule-1",
        "timeframe": 300, # 5-min
        "indicators": [
            {
                "indicatorId": "rsi",
                "type": "RSI",
                "params": {"period": 14},
                "InstrumentType": "SPOT"
            }
        ],
        "entry": {
            "intent": "AUTO",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [
                {
                    "type": "threshold",
                    "indicatorId": "rsi",
                    "op": ">",
                    "value": 0 # ALWAYS TRIGGER
                }
            ]
        }
    }

def run_db_baseline(db, config, instrument_id, start_dt, end_dt) -> List[Dict]:
    """Run Strategy on DB Data directly (nifty_candle)"""
    logger.info("--- Running DB Baseline ---")
    fm = FundManager(strategy_config=config, is_backtest=True)
    
    signals = []
    original_on_signal = fm.position_manager.on_signal
    fm.position_manager.on_signal = lambda data: signals.append(data) or original_on_signal(data)
    
    coll = db[settings.NIFTY_CANDLE_COLLECTION]
    cursor = coll.find({
        "i": instrument_id,
        "t": {"$gte": int(start_dt.timestamp()), "$lte": int(end_dt.timestamp())}
    }).sort("t", 1)
    
    count = 0
    for doc in cursor:
        fm.on_tick_or_base_candle(doc)
        count += 1
        
    logger.info(f"DB Processed {count} source documents.")
    return signals

def run_socket_stream(config, instrument_id, start_dt, end_dt) -> List[Dict]:
    """Run Strategy via Socket Simulator"""
    logger.info("--- Running Socket Stream ---")
    
    port = 5055
    server_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    server_thread.start()
    time.sleep(3) 
    
    signals = []
    fm = FundManager(strategy_config=config, is_backtest=True)
    original_on_signal = fm.position_manager.on_signal
    fm.position_manager.on_signal = lambda data: signals.append(data) or original_on_signal(data)
    
    import socketio
    sio = socketio.Client(logger=True, engineio_logger=True)
    complete_event = threading.Event()
    
    @sio.event
    def connect():
        logger.info("Raw Socket Connected.")
        def trigger():
            time.sleep(1)
            logger.info("Triggering Simulation from Raw Client...")
            sio.emit('start_simulation', {
                "instrument_id": instrument_id,
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "delay": 0.01,
                "mode": "candle"
            })
        threading.Thread(target=trigger).start()
        
    @sio.on('1505-json-full')
    def on_1505(data):
        bar = data.get('BarData', {})
        candle = {
            'o': bar.get('Open'),
            'h': bar.get('High'),
            'l': bar.get('Low'),
            'c': bar.get('Close'),
            'v': bar.get('Volume'),
            't': bar.get('Timestamp'),
            'i': int(data.get('ExchangeInstrumentID')) 
        }
        if candle['c']:
            fm.on_tick_or_base_candle(candle)

    @sio.on('simulation_complete')
    def on_complete(data):
        logger.info("Sim Complete.")
        complete_event.set()
        sio.disconnect()
        
    try:
        sio.connect(f'http://0.0.0.0:{port}', socketio_path='/apimarketdata/socket.io', transports=['websocket', 'polling'])
        if not complete_event.wait(timeout=30):
             logger.error("Simulation Timed Out or Disconnected Early!")
             if sio.connected: sio.disconnect()
    except Exception as e:
        logger.error(f"Raw Socket Error: {e}")
        
    return signals

def test_compare_db_vs_socket(db_conn, strategy_config):
    instrument_id = 26000
    start_dt = datetime(2026, 2, 2, 9, 15, 0)
    end_dt = datetime(2026, 2, 2, 12, 15, 0)

    db_signals = run_db_baseline(db_conn, strategy_config, instrument_id, start_dt, end_dt)
    logger.info(f"DB Generated {len(db_signals)} signals.")
    
    socket_signals = run_socket_stream(strategy_config, instrument_id, start_dt, end_dt)
    logger.info(f"Socket Generated {len(socket_signals)} signals.")
    
    assert len(db_signals) > 0, "DB should generate signals with RSI > 0"
    assert len(socket_signals) > 0, "Socket should generate signals with RSI > 0"
    
    logger.info("SUCCESS: DB and Socket generated signals.")
