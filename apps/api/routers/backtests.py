from fastapi import APIRouter
from packages.utils.mongo import get_db

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

@router.get("")
async def get_backtests():
    db = get_db()
    # Exclude heavy fields for the summary list
    projection = {
        "_id": 1, # Keep _id to fallback if needed
        "trades": 0,
        "dailyPnl": 0
    }
    # Sort by timestamp or createdAt (whichever is present)
    # MongoDB sort can take multiple fields
    results = list(db['backtest_results'].find({}, projection).sort([('timestamp', -1), ('createdAt', -1)]).limit(50))
    
    # Ensure consistency in ID handling
    for res in results:
        # Check all possible ID fields
        bid = res.get("backtest_id") or res.get("backtestId") or res.get("resultId")
        if bid:
            res["id"] = bid
        else:
            res["id"] = str(res["_id"])
        
        # Cleanup _id for JSON serializability if it's an ObjectId
        if "_id" in res:
            res["_id"] = str(res["_id"])
            
    return results

@router.get("/{id}")
async def get_backtest_detail(id: str):
    db = get_db()
    # Try finding by various ID fields
    query = {
        "$or": [
            {"backtest_id": id},
            {"backtestId": id},
            {"resultId": id}
        ]
    }
    res = db['backtest_results'].find_one(query, {'_id': 0})
    return res or {}
