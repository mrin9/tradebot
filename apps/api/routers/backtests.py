from fastapi import APIRouter
from packages.utils.mongo import get_db

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

@router.get("")
async def get_backtests():
    db = get_db()
    # Exclude heavy fields for the summary list (exclusion-only projection)
    projection = {
        "trades": 0,
        "tradeCycles": 0,
        "dailyPnl": 0,
        "instrumentsTraded": 0
    }
    # Sort by createdAt (preferred)
    results = list(db['backtest_results'].find({}, projection).sort([('createdAt', -1), ('timestamp', -1)]).limit(50))
    
    for res in results:
        # Preferred ID is sessionId
        res["id"] = res.get("sessionId") or res.get("resultId") or str(res["_id"])
        
        if "_id" in res:
            res["_id"] = str(res["_id"])
            
    return results

@router.get("/{id}")
async def get_backtest_detail(id: str):
    db = get_db()
    # Support both for transition, prioritize sessionId
    query = {
        "$or": [
            {"sessionId": id},
            {"resultId": id},
            {"backtest_id": id},
            {"backtestId": id}
        ]
    }
    res = db['backtest_results'].find_one(query, {'_id': 0})
    return res or {}
