from fastapi import APIRouter, HTTPException, Body
from packages.utils.mongo import get_db
from pydantic import BaseModel
from typing import Dict, Any, List
from bson import ObjectId

router = APIRouter(prefix="/api/strategy-rules", tags=["strategy-rules"])

class StrategyRule(BaseModel):
    name: str = "Default"
    config: Dict[str, Any]
    is_active: bool = True

def _seed_default_rules(db):
    default_rules = [
        {
            "ruleId": "rsi-ema-default",
            "name": "RSI-EMA-Strategy",
            "category": "TREND",
            "goal": "Capture trend reversals using RSI and EMA",
            "config": {"rsi_buy": 60, "rsi_sell": 40, "ema_fast": 9, "ema_slow": 21},
            "enabled": True,
            "indicators": [
                {"indicatorId": "ema9", "type": "EMA", "params": {"period": 9}, "timeframe": 60},
                {"indicatorId": "ema21", "type": "EMA", "params": {"period": 21}, "timeframe": 60},
                {"indicatorId": "rsi14", "type": "RSI", "params": {"period": 14}, "timeframe": 60}
            ],
            "entry": {
                "operator": "AND",
                "conditions": [
                    {"type": "crossover", "fast": "ema9", "slow": "ema21"},
                    {"type": "threshold", "indicator": "rsi14", "op": ">", "value": 50}
                ]
            },
            "exit": {
                "operator": "OR",
                "conditions": [
                    {"type": "crossunder", "fast": "ema9", "slow": "ema21"}
                ]
            }
        }
    ]
    db['strategy_rules'].delete_many({}) # Clear before seeding for reset
    db['strategy_rules'].insert_many(default_rules)
    return default_rules

@router.get("")
async def get_rules():
    db = get_db()
    rules = list(db['strategy_rules'].find({}))
    
    # If empty, seed default
    if not rules:
        rules_data = _seed_default_rules(db)
        # Re-fetch or map rules
        rules = list(db['strategy_rules'].find({}))

    for r in rules:
        r["id"] = str(r["_id"])
        if "ruleId" not in r:
            r["ruleId"] = r["id"]
        del r["_id"]
        
    return rules

@router.get("/{id}")
async def get_rule(id: str):
    db = get_db()
    try:
        query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"ruleId": id}
        rule = db['strategy_rules'].find_one(query)
        if rule:
            rule['id'] = str(rule['_id'])
            if "ruleId" not in rule:
                rule["ruleId"] = rule["id"]
            del rule['_id']
            return rule
    except:
        pass
    return {}

@router.post("")
async def create_rule(rule: StrategyRule):
    db = get_db()
    doc = rule.dict()
    if "ruleId" not in doc:
        doc["ruleId"] = doc.get("name", "rule").lower().replace(" ", "-")
    res = db['strategy_rules'].insert_one(doc)
    return {"id": str(res.inserted_id), "status": "created"}

@router.put("/{id}")
async def update_rule(id: str, rule: StrategyRule):
    db = get_db()
    query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"ruleId": id}
    db['strategy_rules'].update_one(query, {"$set": rule.dict()})
    return {"status": "updated"}

@router.post("/reset")
async def reset_rules():
    """Reset all strategy rules to factory defaults."""
    try:
        db = get_db()
        _seed_default_rules(db)
        return {"status": "ok", "message": "Strategy rules reset to factory defaults"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
