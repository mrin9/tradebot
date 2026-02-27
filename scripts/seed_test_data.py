import math
from datetime import datetime, timedelta
import pymongo
from pymongo import MongoClient
import os
import sys

sys.path.append(os.getcwd())
from packages.config import settings

DB_NAME = "tradebot_frozen_test"
NIFTY_COL = "nifty_candle_test_data"
OPT_COL = "options_candle_test_data"
RULE_COL = "strategy_rules_test_data"
INST_COL = "instrument_master_test_data"

def clear_db(db):
    print("Clearing collections...")
    db[NIFTY_COL].delete_many({})
    db[OPT_COL].delete_many({})
    db[RULE_COL].delete_many({})
    db[INST_COL].delete_many({})

def generate_instruments(db):
    print("Seeding instrument_master...")
    instruments = []
    # Spot
    instruments.append({
        "exchangeSegment": "NSECM",
        "exchangeInstrumentID": 26000,
        "name": "NIFTY 50",
        "description": "NIFTY 50",
        "instrumentTypeNum": 1
    })
    
    # Options (Strikes from 20000 to 28000, 50 intervals)
    expiry = "2026-02-12T00:00:00"
    base_id = 50000
    for strike in range(20000, 28000, 50):
        # CE
        instruments.append({
            "exchangeSegment": "NSEFO",
            "exchangeInstrumentID": base_id,
            "name": "NIFTY",
            "series": "OPTIDX",
            "contractExpiration": expiry,
            "strikePrice": strike,
            "optionType": 3, # CE
            "description": f"NIFTY {strike} CE",
            "lotSize": 50
        })
        base_id += 1
        # PE
        instruments.append({
            "exchangeSegment": "NSEFO",
            "exchangeInstrumentID": base_id,
            "name": "NIFTY",
            "series": "OPTIDX",
            "contractExpiration": expiry,
            "strikePrice": strike,
            "optionType": 4, # PE
            "description": f"NIFTY {strike} PE",
            "lotSize": 50
        })
        base_id += 1

    db[INST_COL].insert_many(instruments)
    print(f"Inserted {len(instruments)} instruments to {INST_COL}")
    
    # Return mapping for data generation
    # CE mapping: strike -> id, PE mapping: strike -> id
    ce_map = {inst["strikePrice"]: inst["exchangeInstrumentID"] for inst in instruments if inst.get("optionType") == 3}
    pe_map = {inst["strikePrice"]: inst["exchangeInstrumentID"] for inst in instruments if inst.get("optionType") == 4}
    return ce_map, pe_map

def make_candle(inst_id, t_epoch, o, h, l, c, v=1000):
    return {
        "i": inst_id,
        "t": t_epoch,
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": v
    }

def generate_day_data(db, start_dt, day_type, ce_map, pe_map, start_nifty_price=22000.0):
    print(f"Generating data for {start_dt.date()} (Type: {day_type})...")
    nifty_candles = []
    opt_candles = []
    
    timestamp = int(start_dt.timestamp())
    nifty_price = start_nifty_price
    
    # Derive initial ATM strike
    atm_strike = round(nifty_price / 50) * 50
    ce_id = ce_map[atm_strike]
    pe_id = pe_map[atm_strike]
    
    ce_price = 100.0
    pe_price = 100.0
    
    for minutes in range(375): # 09:15 to 15:30
        current_ts = timestamp + (minutes * 60)
        
        # Determine price movement based on day_type
        if day_type == "UP_TREND_PERFECT":
            # Spot goes up smoothly
            n_o, n_c = nifty_price, nifty_price + 2.0
            nifty_price = n_c
            # CE goes up (confirms)
            c_o, c_c = ce_price, ce_price + 1.0
            ce_price = c_c
            # PE goes down (confirms)
            p_o, p_c = pe_price, pe_price - 0.5
            pe_price = max(1.0, p_c)
            
        elif day_type == "DOWN_TREND_PERFECT":
            n_o, n_c = nifty_price, nifty_price - 2.0
            nifty_price = n_c
            c_o, c_c = ce_price, ce_price - 0.5
            ce_price = max(1.0, c_c)
            p_o, p_c = pe_price, pe_price + 1.0
            pe_price = p_c
            
        elif day_type == "PARTIAL_ALIGNMENT":
            # Active (CE) looks great, Spot flat/down, PE flat
            n_o, n_c = nifty_price, nifty_price - 0.1
            nifty_price = n_c
            c_o, c_c = ce_price, ce_price + 1.5 # Fake breakout on option
            ce_price = c_c
            p_o, p_c = pe_price, pe_price - 0.1
            pe_price = max(1.0, p_c)
            
        elif day_type == "STRIKE_ROLLING":
            # Huge jump in price (100 points over 2 hours)
            if minutes < 120:
                n_o, n_c = nifty_price, nifty_price + 1.0
                c_o, c_c = ce_price, ce_price + 0.2
                p_o, p_c = pe_price, pe_price - 0.1
            else:
                n_o, n_c = nifty_price, nifty_price + 3.0 # acceleration
                c_o, c_c = ce_price, ce_price + 1.5
                p_o, p_c = pe_price, pe_price - 0.5
            nifty_price = n_c
            ce_price = c_c
            pe_price = max(1.0, p_c)
            
        elif day_type == "CHOPPY":
            # Up and down
            change = 2.0 if (minutes // 10) % 2 == 0 else -2.0
            n_o, n_c = nifty_price, nifty_price + change
            nifty_price = n_c
            c_o, c_c = ce_price, ce_price + (change * 0.5)
            ce_price = max(1.0, c_c)
            p_o, p_c = pe_price, pe_price - (change * 0.5)
            pe_price = max(1.0, p_c)
            
        else:
            n_o, n_c = nifty_price, nifty_price
            c_o, c_c = ce_price, ce_price
            p_o, p_c = pe_price, pe_price

        # Update ATM tracking logic for generating data on the active strike
        new_atm_strike = round(nifty_price / 50) * 50
        active_ce_id = ce_map[new_atm_strike]
        active_pe_id = pe_map[new_atm_strike]
        
        # Nifty Candle
        nifty_candles.append(make_candle(26000, current_ts, n_o, max(n_o, n_c)+1, min(n_o, n_c)-1, n_c))
        
        # CE Candle (generate for the currently active ATM strike specifically to ensure data exists for that strike)
        # We also generate data for the previous strike if it diverged, but for simplicity, we provide valid options data for all generated strikes close to ATM
        for strike in [new_atm_strike - 50, new_atm_strike, new_atm_strike + 50]:
            if strike in ce_map:
                offset_factor = (strike - new_atm_strike)/50.0  # Just arbitrary pricing difference
                strike_ce_o = max(1.0, c_o - offset_factor * 10)
                strike_ce_c = max(1.0, c_c - offset_factor * 10)
                opt_candles.append(make_candle(ce_map[strike], current_ts, strike_ce_o, max(strike_ce_o, strike_ce_c)+0.5, min(strike_ce_o, strike_ce_c)-0.5, strike_ce_c))
                
            if strike in pe_map:
                offset_factor = (new_atm_strike - strike)/50.0 
                strike_pe_o = max(1.0, p_o - offset_factor * 10)
                strike_pe_c = max(1.0, p_c - offset_factor * 10)
                opt_candles.append(make_candle(pe_map[strike], current_ts, strike_pe_o, max(strike_pe_o, strike_pe_c)+0.5, min(strike_pe_o, strike_pe_c)-0.5, strike_pe_c))

    if nifty_candles:
        db[NIFTY_COL].insert_many(nifty_candles)
    if opt_candles:
        db[OPT_COL].insert_many(opt_candles)
        
    return nifty_price # return ending price for next day

def generate_rules(db):
    print("Seeding strategy rules...")
    rules = [
        # 1. EMA 5/21 + RSI Filter (180s Timeframe) - Triple Lock
        {
            "ruleId": "ema-5x21+rsi-180s-triple",
            "name": "EMA 5x21 + RSI Triple Lock",
            "category": "TREND",
            "enabled": True,
            "applicableTo": ["NIFTY"],
            "timeframe": 180,
            "indicators": [
                {"indicatorId": "ema5", "displayLabel": "EMA 5 SPOT", "type": "EMA", "params": {"period": 5}, "InstrumentType": "SPOT"},
                {"indicatorId": "ema21", "displayLabel": "EMA 21 SPOT", "type": "EMA", "params": {"period": 21}, "InstrumentType": "SPOT"},
                {"indicatorId": "rsi", "displayLabel": "RSI 14 SPOT", "type": "RSI", "params": {"period": 14}, "InstrumentType": "SPOT"},
                {"indicatorId": "ema5", "displayLabel": "EMA 5", "type": "EMA", "params": {"period": 5}, "InstrumentType": "OPTIONS_BOTH"},
                {"indicatorId": "ema21", "displayLabel": "EMA 21", "type": "EMA", "params": {"period": 21}, "InstrumentType": "OPTIONS_BOTH"},
                {"indicatorId": "rsi", "displayLabel": "RSI 14", "type": "RSI", "params": {"period": 14}, "InstrumentType": "OPTIONS_BOTH"}
            ],
            "entry": {
                "intent": "AUTO",
                "evaluateSpot": True,
                "evaluateInverse": True,
                "operator": "AND",
                "conditions": [
                    {
                        "operator": "OR",
                        "conditions": [
                            {"type": "crossover", "fastIndicatorId": "ema5", "slowIndicatorId": "ema21"},
                            {"type": "crossover", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"},
                            {"type": "crossunder", "fastIndicatorId": "INVERSE_ema5", "slowIndicatorId": "INVERSE_ema21"}
                        ]
                    },
                    {"type": "threshold", "indicatorId": "ema5", "op": ">", "valueIndicatorId": "ema21"},
                    {"type": "threshold", "indicatorId": "ACTIVE_ema5", "op": ">", "valueIndicatorId": "ACTIVE_ema21"},
                    {"type": "threshold", "indicatorId": "INVERSE_ema5", "op": "<", "valueIndicatorId": "INVERSE_ema21"},
                    {"type": "threshold", "indicatorId": "rsi", "op": ">", "value": 50},
                    {"type": "threshold", "indicatorId": "ACTIVE_rsi", "op": ">", "value": 50},
                    {"type": "threshold", "indicatorId": "INVERSE_rsi", "op": "<", "value": 50}
                ]
            },
            "exit": {
                "evaluateSpot": True,
                "evaluateInverse": False,
                "operator": "AND",
                "conditions": [
                    {"type": "crossunder", "fastIndicatorId": "ACTIVE_ema5", "slowIndicatorId": "ACTIVE_ema21"}
                ]
            }
        },
        # 2. EMA 9/21 + Supertrend + RSI (300s Timeframe) - Active-Only
        {
            "ruleId": "ema-9x21+st+rsi-300s-active",
            "name": "EMA 9x21 Supertrend Active Only",
            "category": "TREND",
            "enabled": True,
            "applicableTo": ["NIFTY"],
            "timeframe": 300,
            "indicators": [
                {"indicatorId": "ema9", "displayLabel": "EMA 9", "type": "EMA", "params": {"period": 9}, "InstrumentType": "OPTIONS_BOTH"},
                {"indicatorId": "ema21", "displayLabel": "EMA 21", "type": "EMA", "params": {"period": 21}, "InstrumentType": "OPTIONS_BOTH"},
                {"indicatorId": "st", "displayLabel": "Supertrend", "type": "SUPERTREND", "params": {"period": 10, "multiplier": 3}, "InstrumentType": "OPTIONS_BOTH"},
                {"indicatorId": "rsi", "displayLabel": "RSI", "type": "RSI", "params": {"period": 14}, "InstrumentType": "OPTIONS_BOTH"}
            ],
            "entry": {
                "intent": "AUTO",
                "evaluateSpot": False, # ACTIVE ONLY
                "evaluateInverse": False,
                "operator": "AND",
                "conditions": [
                    {"type": "crossover", "fastIndicatorId": "ACTIVE_ema9", "slowIndicatorId": "ACTIVE_ema21"},
                    {"type": "direction_match", "indicatorId": "ACTIVE_st_dir", "op": "==", "value": 1},
                    {"type": "threshold", "indicatorId": "ACTIVE_rsi", "op": ">", "value": 50}
                ]
            },
            "exit": {
                "evaluateSpot": False,
                "evaluateInverse": False,
                "operator": "AND",
                "conditions": [
                    {"type": "crossunder", "fastIndicatorId": "ACTIVE_ema9", "slowIndicatorId": "ACTIVE_ema21"}
                ]
            }
        },
        # 3. MACD + Supertrend + EMA Slope (180s Timeframe) - Active + Spot
        {
            "ruleId": "macd+st+slope-180s-dual",
            "name": "MACD ST Slope Dual",
            "category": "MOMENTUM",
            "enabled": True,
            "applicableTo": ["NIFTY"],
            "timeframe": 180,
            "indicators": [
                {"indicatorId": "macd", "displayLabel": "MACD", "type": "MACD", "params": {"fast": 12, "slow": 26, "signal": 9}, "InstrumentType": "SPOT"},
                {"indicatorId": "st", "displayLabel": "Supertrend", "type": "SUPERTREND", "params": {"period": 10, "multiplier": 3}, "InstrumentType": "SPOT"},
                {"indicatorId": "ema_slope", "displayLabel": "EMA Slope", "type": "EMA", "params": {"period": 20}, "InstrumentType": "SPOT"} # Simplified slope as just the indicator to mock
            ],
            "entry": {
                "intent": "AUTO",
                "evaluateSpot": True,
                "evaluateInverse": False,
                "operator": "AND",
                "conditions": [
                    {"type": "threshold", "indicatorId": "macd_hist", "op": ">", "value": 0},
                    {"type": "direction_match", "indicatorId": "st_dir", "op": "==", "value": 1}
                ]
            },
            "exit": {
                "evaluateSpot": False,
                "evaluateInverse": True,
                "operator": "OR",
                "conditions": [
                    {"type": "threshold", "indicatorId": "macd_hist", "op": "<", "value": 0},
                    {"type": "crossover", "fastIndicatorId": "INVERSE_macd_hist", "slowIndicatorId": "INVERSE_ema_slope", "op": ">", "value": 0} # Dummy cross to trigger inverse evaluate parsing
                ]
            }
        }
    ]
    db[RULE_COL].insert_many(rules)

def generate_all():
    client = MongoClient(settings.MONGODB_URI)
    db = client[DB_NAME]
    
    clear_db(db)
    generate_rules(db)
    ce_map, pe_map = generate_instruments(db)
    
    start_dt = datetime(2026, 2, 2, 9, 15) # Monday
    
    # Day 1: Perfect Up Trend
    price = generate_day_data(db, start_dt, "UP_TREND_PERFECT", ce_map, pe_map, start_nifty_price=22000.0)
    
    # Day 2: Partial Alignment (False breakout option, Spot flat)
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "PARTIAL_ALIGNMENT", ce_map, pe_map, start_nifty_price=price)
    
    # Day 3: Strike Rolling (Huge trend up)
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "STRIKE_ROLLING", ce_map, pe_map, start_nifty_price=price)
    
    # Day 4: Perfect Down Trend
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "DOWN_TREND_PERFECT", ce_map, pe_map, start_nifty_price=price)
    
    # Day 5: Choppy
    start_dt += timedelta(days=1)
    price = generate_day_data(db, start_dt, "CHOPPY", ce_map, pe_map, start_nifty_price=price)

    print("Data Generation Complete!")

if __name__ == "__main__":
    generate_all()
