from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from apps.api.socket_instance import sio
from packages.simulator.socket_data_provider import SocketDataProvider
from packages.config import settings

router = APIRouter(prefix="/api/simulation", tags=["simulation"])

# Singleton Provider
sim_provider = SocketDataProvider(sio)

class SimConfig(BaseModel):
    date: str
    interval: int = 5 # Speed/Delay? Or candle interval? 
    # Frontend sends 'interval' as integer (e.g. 5).
    # TickMonitorComp.vue line 98: interval = ref(5);
    # And line 13: InputNumber ... suffix="s". So it's delay in seconds? 
    # Or candle interval?
    # Logic: line 177: body: JSON.stringify({ date: selectedDate.value, interval: interval.value })
    # If the user selects "5s", it probably means REPLAY SPEED or Tick Delay.
    # Let's assume it's delay.

@router.get("/dates")
async def get_available_dates():
    # Only expose dates that have data
    # TODO: Real DB distinct query
    return {"dates": ["2026-02-02", "2026-02-03", "2026-02-04", "2026-02-18", "2026-02-19"]} 

@router.get("/status")
async def get_status():
    return {"is_running": sim_provider.running, "ticks_emitted": 0}

@router.post("/start")
async def start_sim(config: SimConfig):
    # Parse Date
    try:
        start_dt = datetime.fromisoformat(f"{config.date}T09:15:00")
        end_dt = datetime.fromisoformat(f"{config.date}T15:30:00")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    # Start Engine
    # Delay: config.interval (likely seconds per tick?). Default 0.01 for fast replay.
    # If user sets 5s, it's very slow.
    # Let's interpret 'interval' as 1/X seconds? Or X seconds.
    # Vue says "interval" with suffix "s". So X seconds.
    delay = float(config.interval) if config.interval > 0 else 0.01
    
    await sim_provider.start_simulation(
        instrument_id=settings.NIFTY_EXCHANGE_INSTRUMENT_ID, # NIFTY 50
        start_dt=start_dt,
        end_dt=end_dt,
        delay=delay,
        mode='tick' # UI Tick Monitor expects ticks
    )
    
    return {"status": "started", "config": config}

@router.post("/stop")
async def stop_sim():
    await sim_provider.stop_simulation()
    return {"status": "stopped"}
