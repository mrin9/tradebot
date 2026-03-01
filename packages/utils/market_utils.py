from datetime import datetime
import json
from typing import List, Dict, Optional
from packages.config import settings
from packages.utils.date_utils import DateUtils

# Constants for Master Data Parsing
XTS_EQUITY_HEADERS = [
    "exchangeSegment", "exchangeInstrumentID", "instrumentTypeNum", "name", "description", 
    "series", "nameWithSeries", "instrumentID", "priceBandHigh", "priceBandLow", 
    "freezeQty", "tickSize", "lotSize", "multiplier", "displayName", "ISIN", 
    "priceNumerator", "priceDenominator"
]

XTS_FO_HEADERS = [
    "exchangeSegment", "exchangeInstrumentID", "instrumentTypeNum", "name", "description", 
    "series", "nameWithSeries", "instrumentID", "priceBandHigh", "priceBandLow", 
    "freezeQty", "tickSize", "lotSize", "multiplier", "underlyingInstrumentId", 
    "underlyingIndexName", "contractExpiration", "strikePrice", "optionType", 
    "displayName", "priceNumerator", "priceDenominator"
]

class MarketUtils:
    """
    Shared utilities for market-related calculations, like contract derivation and data parsing.
    """

    # --- Master Data Parsers ---
    @staticmethod
    def get_instrument_id(db, identifier: str) -> int:
        """
        Lookup Instrument ID from Master based on Symbol (description), 
        ExchangeInstrumentID (if numeric), or Name.
        """
        # 1. Try direct numeric conversion
        try:
            return int(identifier)
        except ValueError:
            pass

        # 2. Handle NIFTY Index specific aliases with priority
        # Often 'NIFTY' returns a future/option if searched generally, 
        # but the API usually wants the index 26000.
        if identifier.upper() in ["NIFTY", "NIFTY 50", "NIFTY50", "NIFTY_50"]:
             return settings.NIFTY_EXCHANGE_INSTRUMENT_ID

        # 3. Try Description (e.g., 'NIFTY26FEB26APRFUT') or Name
        query = {
            "$or": [
                {"description": identifier},
                {"name": identifier},
                {"nameWithSeries": identifier}
            ]
        }
        
        doc = db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(query)
        
        if doc:
            return int(doc['exchangeInstrumentID'])
            
        raise ValueError(f"Instrument not found for identifier: {identifier}")

    @staticmethod
    def parse_xts_master_line(line: str) -> Optional[Dict]:
        """Parses a single line from the XTS master data pipe-separated response."""
        if not line or not line.strip(): 
            return None
        
        parts = line.strip().split('|')
        if len(parts) < 2: 
            return None
        
        segment = parts[0]
        
        if segment == 'NSECM':
            headers = XTS_EQUITY_HEADERS
        elif segment == 'NSEFO':
            headers = XTS_FO_HEADERS
        else:
            headers = [f"field_{i}" for i in range(len(parts))]
        
        doc = {}
        for i, header in enumerate(headers):
            if i < len(parts):
                val = parts[i].strip()
                if val == "" or val == "NA":
                    doc[header] = None
                else:
                    try:
                        if '.' in val or 'e' in val.lower():
                            doc[header] = float(val)
                        else:
                            doc[header] = int(val)
                    except ValueError:
                        doc[header] = val
            else:
                doc[header] = None
                
        return doc

    @staticmethod
    def parse_xts_master_data(content: str) -> List[Dict]:
        """Parses the entire response body string from get_master() API."""
        if not content: 
            return []
        return [
            item for item in (MarketUtils.parse_xts_master_line(l) for l in content.strip().split('\n')) 
            if item is not None
        ]

    @staticmethod
    def parse_custom_xts_string(data: str) -> Dict:
        """Parses XTS custom comma-separated format (e.g. t:1_9309,51:6023)."""
        try:
            parsed_dict = {}
            parts = data.split(',')
            for part in parts:
                if ':' in part:
                    k, v = part.split(':', 1)
                    try:
                        if '.' in v:
                            parsed_dict[k] = float(v)
                        elif '_' in v:
                            parsed_dict[k] = v
                        else:
                            parsed_dict[k] = int(v)
                    except ValueError:
                        parsed_dict[k] = v
                else: 
                    parsed_dict[part] = True
            return parsed_dict
        except Exception:
            return {"raw": data}

    @staticmethod
    def normalize_raw_socket_data(rawSocketData: str | None) -> Dict | None:
        """Converts raw socket payload string into a normalized Dict."""
        if rawSocketData is None:
            return None
        if not isinstance(rawSocketData, str):
            # Fallback if somehow a dict gets passed
            return rawSocketData
            
        if rawSocketData.startswith('{') or rawSocketData.startswith('['):
            try:
                return json.loads(rawSocketData)
            except:
                pass
        return MarketUtils.parse_custom_xts_string(rawSocketData)

    # --- Socket Event Normalizers ---

    @staticmethod
    def normalize_xts_event(event_type: str, rawSocketData: str | None) -> Dict | None:
        """
        Main dispatcher to normalize different XTS socket events.
        """
        # 0. Ensure data is a Dict
        norm_data = MarketUtils.normalize_raw_socket_data(rawSocketData)
        if not norm_data:
            return None

        # Route based on event type
        if any(x in event_type for x in ['1501', '1512', '1502']):
            return MarketUtils.normalize_1501_tick_event(norm_data)
        elif '1505' in event_type:
            return MarketUtils.normalize_1505_candle_event(norm_data)
        elif '1105' in event_type:
            # Property Changes (Bands, etc.) - ignore for pricing
            return None
        return None

    @staticmethod
    def _get_val(data: Dict, long_key: str, short_key: str, default=None):
        """Helper to extract value from nested 'Touchline/BarData' vs Flat structure."""
        # 1. Check nested structures first (Standard XTS JSON)
        for wrapper in ["Touchline", "BarData"]:
            if wrapper in data and isinstance(data[wrapper], dict):
                val = data[wrapper].get(long_key, data[wrapper].get(short_key))
                if val is not None:
                    return val
        
        # 2. Check flat structure (Fallback)
        return data.get(long_key, data.get(short_key, default))

    @staticmethod
    def normalize_1501_tick_event(data: Dict) -> Dict:
        """
        Normalizes 1501 (Tick) and 1512 (Market Depth) events.
        """
        # Price and Identity
        inst_id = MarketUtils._get_val(data, 'ExchangeInstrumentID', 'i', default=data.get('t', 0))
        ltp = MarketUtils._get_val(data, 'LastTradedPrice', 'ltp')
        
        # Volume (Handle common XTS typo 'Qunatity')
        last_qty = MarketUtils._get_val(data, 'LastTradedQuantity', 'ltq')
        if last_qty is None:
            last_qty = MarketUtils._get_val(data, 'LastTradedQunatity', 'ltq', default=0)
            
        total_qty = MarketUtils._get_val(data, 'TotalTradedQuantity', 'v', default=0)
        
        # Timestamps
        raw_ts = MarketUtils._get_val(data, 'ExchangeTimeStamp', 'ltt')
        if raw_ts is None:
            raw_ts = MarketUtils._get_val(data, 'LastTradedTime', 'lut')
            
        utc_ts = DateUtils.xts_epoch_to_utc(raw_ts)
        
        # Bid/Ask
        bid_info = data.get('BidInfo')
        if isinstance(bid_info, dict):
            bid = bid_info.get('Price')
        else:
            bid = str(data.get('bi', '')).split('|')[1] if '|' in str(data.get('bi')) else None

        ask_info = data.get('AskInfo')
        if isinstance(ask_info, dict):
            ask = ask_info.get('Price')
        else:
            ask = str(data.get('ai', '')).split('|')[1] if '|' in str(data.get('ai')) else None

        try:
            bid = float(bid) if bid else None
            ask = float(ask) if ask else None
        except (ValueError, TypeError):
            bid = None
            ask = None

        return {
            "i": int(str(inst_id).split('_')[-1]) if inst_id else 0,
            "t": utc_ts,
            "isoDt": DateUtils.to_kolkata_iso(utc_ts),
            "p": ltp,
            "v": last_qty,
            "q": total_qty,
            "bid": bid,
            "ask": ask
        }

    @staticmethod
    def normalize_1505_candle_event(data: Dict) -> Dict:
        """
        Normalizes 1505 (Bar/Candle) events.
        """
        inst_id = MarketUtils._get_val(data, 'ExchangeInstrumentID', 'i')
        raw_ts = MarketUtils._get_val(data, 'Timestamp', 't')
        utc_ts = DateUtils.xts_epoch_to_utc(raw_ts)

        return {
            "i": int(inst_id) if inst_id else 0,
            "t": utc_ts,
            "isoDt": DateUtils.to_kolkata_iso(utc_ts),
            "o": MarketUtils._get_val(data, 'Open', 'o'),
            "h": MarketUtils._get_val(data, 'High', 'h'),
            "l": MarketUtils._get_val(data, 'Low', 'l'),
            "c": MarketUtils._get_val(data, 'Close', 'c'),
            "v": MarketUtils._get_val(data, 'Volume', 'v')
        }

    # --- Derived CE and PE Logic ---

    @staticmethod
    def run_indicator_warmup(db, fund_manager, start_date: str, warmup_candles: int, logger):
        """
        Feeds historical data into FundManager to warm up indicators before backtest.
        """
        if warmup_candles <= 0:
            return

        logger.info(f"🔥 Warming up indicators with {warmup_candles} candles...")
        dt = DateUtils.parse_iso(start_date)
        start_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())
        
        warmup_cursor = db[settings.NIFTY_CANDLE_COLLECTION].find(
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

    @staticmethod
    def derive_target_contracts(db, current_dt: datetime, strike_count: int = None):
        """
        Derives CE/PE contracts for ATM and +/- strike_count for the given date.
        Uses NIFTY spot closing price found in nifty_candle collection.
        """
        if strike_count is None:
            strike_count = settings.OPTIONS_STRIKE_COUNT

        nifty_col = db[settings.NIFTY_CANDLE_COLLECTION]
        master_col = db[settings.INSTRUMENT_MASTER_COLLECTION]

        start_ts = DateUtils.to_timestamp(current_dt)
        end_ts = DateUtils.to_timestamp(current_dt, end_of_day=True)

        # 1. Get NIFTY closing price
        last_nifty = nifty_col.find_one(
            {"i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID, "t": {"$gte": start_ts, "$lte": end_ts}},
            sort=[("t", -1)]
        )
        spot_price = last_nifty['p'] if last_nifty else 0

        if spot_price <= 0:
            return []

        # 2. Derive Strikes
        strike_step = settings.NIFTY_STRIKE_STEP
        atm_strike = round(spot_price / strike_step) * strike_step
        strikes = [atm_strike + (i * strike_step) for i in range(-strike_count, strike_count + 1)]

        # 3. Find Nearest Weekly Expiry
        dt_iso = current_dt.strftime("%Y-%m-%dT00:00:00")
        opt_ref = master_col.find_one({
            "exchangeSegment": "NSEFO", 
            "name": "NIFTY", 
            "series": "OPTIDX",
            "contractExpiration": {"$gte": dt_iso}
        }, sort=[("contractExpiration", 1)])

        if not opt_ref:
            return []

        expiry = opt_ref["contractExpiration"]

        # 4. Fetch Contracts
        contracts = list(master_col.find({
            "exchangeSegment": "NSEFO", 
            "name": "NIFTY", 
            "series": "OPTIDX",
            "contractExpiration": expiry,
            "strikePrice": {"$in": strikes},
            "optionType": {"$in": [3, 4]}  # CE/PE
        }))

        return contracts
