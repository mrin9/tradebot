from typing import Dict, Optional, Tuple, Set
from datetime import datetime
from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.config import settings
from packages.utils.log_utils import setup_logger
from packages.services.market_history import MarketHistoryService

logger = setup_logger("ContractDiscoveryService")

class ContractDiscoveryService:
    """
    Service for resolving and discovering instruments, specifically option contracts and strikes.
    Replaces logic in FundManager._resolve_option_contract and LiveTradeEngine._resolve_strike_ids.
    """

    def __init__(self, db=None):
        self.db = db if db is not None else MongoRepository.get_db()

    def resolve_option_contract(
        self, 
        strike: float, 
        is_ce: bool, 
        current_ts: float, 
        symbol: str = "NIFTY", 
        series: str = "OPTIDX"
    ) -> Tuple[Optional[int], Optional[str]]:
        """
        Finds the nearest expiry option contract for a given strike and timestamp.
        """
        dt_iso = DateUtils.market_timestamp_to_iso(current_ts)
        opt_type_num = 3 if is_ce else 4  # CE=3, PE=4 in XTS
        
        query = {
            "name": symbol,
            "series": series,
            "strikePrice": strike,
            "optionType": opt_type_num,
            "contractExpiration": {"$gte": dt_iso}
        }
        
        contract = self.db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(
            query,
            sort=[("contractExpiration", 1)]
        )
        
        if contract:
            return int(contract["exchangeInstrumentID"]), contract.get("description", contract.get("displayName"))
        
        logger.warning(f"No {symbol} {'CE' if is_ce else 'PE'} contract found for strike {strike} at {dt_iso}")
        return None, None

    def get_strike_window_ids(
        self, 
        atm_strike: float, 
        window_size: int = 3, 
        symbol: str = "NIFTY",
        series: str = "OPTIDX"
    ) -> Set[int]:
        """
        Returns a set of exchange instrument IDs for ATM ± window_size strikes.
        """
        now_iso = DateUtils.to_iso(datetime.now())
        # Step increment depends on the index (NIFTY is 50, BANKNIFTY is 100)
        step = 50 if symbol == "NIFTY" else 100
        
        target_strikes = [atm_strike + (i * step) for i in range(-window_size, window_size + 1)]
        
        # Get nearest expiry
        opt_ref = self.db[settings.INSTRUMENT_MASTER_COLLECTION].find_one({
            "name": symbol, 
            "series": series, 
            "contractExpiration": {"$gte": now_iso}
        }, sort=[("contractExpiration", 1)])
        
        if not opt_ref:
            logger.error(f"Could not find any active {symbol} contracts in master.")
            return set()
        
        expiry = opt_ref["contractExpiration"]
        contracts = list(self.db[settings.INSTRUMENT_MASTER_COLLECTION].find({
            "name": symbol, 
            "series": series, 
            "contractExpiration": expiry, 
            "strikePrice": {"$in": target_strikes}
        }))
        
        ids = {int(c['exchangeInstrumentID']) for c in contracts}
        logger.debug(f"Resolved {len(ids)} contracts for ATM {atm_strike} window (±{window_size})")
        return ids

    @staticmethod
    def get_atm_strike(price: float, step: int = 50) -> float:
        """Helper to round a price to the nearest strike."""
        return round(price / step) * step

    def derive_target_contracts(self, current_dt: datetime, strike_count: int = None):
        """
        Derives CE/PE contracts for ATM and +/- strike_count for the given date.
        Uses NIFTY spot closing price found in nifty_candle collection.
        """
        if strike_count is None:
            strike_count = settings.OPTIONS_STRIKE_COUNT

        nifty_col = self.db[settings.NIFTY_CANDLE_COLLECTION]
        master_col = self.db[settings.INSTRUMENT_MASTER_COLLECTION]

        start_ts = DateUtils.to_timestamp(current_dt)
        end_ts = DateUtils.to_timestamp(current_dt, end_of_day=True)

        # 1. Get NIFTY closing price
        history_service = MarketHistoryService(self.db)
        spot_price = history_service.get_last_nifty_price(current_dt) or 0

        if spot_price <= 0:
            return []

        # 2. Derive Strikes
        strike_step = settings.NIFTY_STRIKE_STEP
        atm_strike = round(spot_price / strike_step) * strike_step
        strikes = [atm_strike + (i * strike_step) for i in range(-strike_count, strike_count + 1)]

        # 3. Find Nearest Weekly Expiry
        dt_iso = DateUtils.to_iso(current_dt.replace(hour=0, minute=0, second=0))
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
