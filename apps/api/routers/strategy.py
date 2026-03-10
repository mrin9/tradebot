from fastapi import APIRouter, HTTPException, Body
from packages.utils.mongo import get_db
from pydantic import BaseModel
from typing import Dict, Any, List
from bson import ObjectId

router = APIRouter(prefix="/api/strategy-rules", tags=["strategy-rules"])

class StrategyIndicator(BaseModel):
    strategyId: str
    name: str = "Default"
    enabled: bool = True
    timeframe_seconds: int = 180
    pythonStrategyPath: str | None = None
    Indicators: List[Dict[str, Any]] = []

@router.get("")
async def get_strategies():
    db = get_db()
    strategies = list(db['strategy_indicators'].find({}))
    
    for s in strategies:
        s["id"] = str(s["_id"])
        del s["_id"]
        
    return strategies

@router.get("/{id}")
async def get_strategy(id: str):
    db = get_db()
    try:
        query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"strategyId": id}
        strategy = db['strategy_indicators'].find_one(query)
        if strategy:
            strategy['id'] = str(strategy['_id'])
            del strategy['_id']
            return strategy
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error retrieving strategy: {str(e)}")
    return {}

@router.post("")
async def create_strategy(strategy: StrategyIndicator):
    db = get_db()
    doc = strategy.dict()
    res = db['strategy_indicators'].insert_one(doc)
    return {"id": str(res.inserted_id), "status": "created"}

@router.put("/{id}")
async def update_strategy(id: str, strategy: StrategyIndicator):
    db = get_db()
    query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"strategyId": id}
    db['strategy_indicators'].update_one(query, {"$set": strategy.dict()})
    return {"status": "updated"}

@router.post("/reset")
async def reset_strategies():
    """Trigger the seeding script to reset strategy indicators."""
    try:
        from scripts.seed_strategy_indicators import seed_strategy_indicators
        seed_strategy_indicators()
        return {"status": "ok", "message": "Strategy indicators reset to factory defaults"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
