from datetime import datetime, timedelta

from packages.services.market_history import MarketHistoryService
from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("ContractDiscoveryService")


class ContractDiscoveryService:
    """
    Service for resolving and discovering instruments, specifically option contracts and strikes.
    Replaces logic in FundManager._resolve_option_contract and LiveTradeEngine._resolve_strike_ids.
    """

    def __init__(self, db=None):
        self.db = db if db is not None else MongoRepository.get_db()
        self._cache: dict[tuple[str, str], list] = {}  # {(symbol, series): [instruments]}
        self._is_cache_loaded = False

    def load_cache(
        self, symbol: str = "NIFTY", series: str = "OPTIDX", effective_date: datetime | None = None
    ):
        """
        Loads all active instruments for a symbol into memory.
        Uses only instrument_master collection.
        If effective_date is provided, it filters expiries relative to that date (critical for backtesting).
        """
        target_date = effective_date or datetime.now()
        now_iso = DateUtils.to_iso(target_date)

        query = {"name": symbol, "series": series, "contractExpiration": {"$gte": now_iso}}
        # Smart projection to save memory
        projection = {
            "exchangeInstrumentID": 1,
            "strikePrice": 1,
            "optionType": 1,
            "description": 1,
            "displayName": 1,
            "contractExpiration": 1,
            "_id": 0,
        }

        instruments = list(self.db[settings.INSTRUMENT_MASTER_COLLECTION].find(query, projection))
        self._cache[(symbol, series)] = instruments
        self._is_cache_loaded = True
        logger.info(f"📁 Loaded {len(instruments)} {symbol} contracts into memory cache.")

    def resolve_option_contract(
        self, strike: float, is_ce: bool, current_ts: float, symbol: str = "NIFTY", series: str = "OPTIDX"
    ) -> tuple[int | None, str | None]:
        """
        Finds the nearest expiry option contract for a given strike and timestamp.
        Checks cache first if loaded.
        """
        dt_iso = DateUtils.market_timestamp_to_iso(current_ts)
        opt_type_num = 3 if is_ce else 4  # CE=3, PE=4 in XTS

        # 1. Check Cache
        if self._is_cache_loaded:
            cache = self._cache.get((symbol, series), [])
            # Filter and sort by expiry
            matches = [
                c
                for c in cache
                if c["strikePrice"] == strike and c["optionType"] == opt_type_num and c["contractExpiration"] >= dt_iso
            ]
            if matches:
                # Sort by expiry to get the nearest one
                matches.sort(key=lambda x: x["contractExpiration"])
                contract = matches[0]
                return int(contract["exchangeInstrumentID"]), contract.get("description", contract.get("displayName"))

        # 2. Fallback to DB
        query = {
            "name": symbol,
            "series": series,
            "strikePrice": strike,
            "optionType": opt_type_num,
            "contractExpiration": {"$gte": dt_iso},
        }

        contract = self.db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(query, sort=[("contractExpiration", 1)])

        if contract:
            return int(contract["exchangeInstrumentID"]), contract.get("description", contract.get("displayName"))

        logger.warning(f"No {symbol} {'CE' if is_ce else 'PE'} contract found for strike {strike} at {dt_iso}")
        return None, None

    def get_strike_window_ids(
        self,
        atm_strike: float,
        window_size: int = 3,
        symbol: str = "NIFTY",
        series: str = "OPTIDX",
        current_ts: float | None = None,
    ) -> set[int]:
        """
        Returns a set of exchange instrument IDs for ATM ± window_size strikes.
        Uses cache if loaded.
        """
        target_iso = (
            DateUtils.market_timestamp_to_iso(current_ts) if current_ts else DateUtils.to_iso(datetime.now())
        )
        step = 50 if symbol == "NIFTY" else 100
        target_strikes = [atm_strike + (i * step) for i in range(-window_size, window_size + 1)]

        # 1. Check Cache
        if self._is_cache_loaded:
            cache = self._cache.get((symbol, series), [])
            # Find nearest expiry first
            expiries = sorted({c["contractExpiration"] for c in cache if c["contractExpiration"] >= target_iso})
            if not expiries:
                logger.error(f"Could not find any active {symbol} contracts in cache relative to {target_iso}")
                return set()

            nearest_expiry = expiries[0]
            ids = {
                int(c["exchangeInstrumentID"])
                for c in cache
                if c["contractExpiration"] == nearest_expiry and c["strikePrice"] in target_strikes
            }
            logger.debug(f"Resolved {len(ids)} contracts for ATM {atm_strike} window (±{window_size}) from cache")
            return ids

        # 2. Fallback to DB
        # Get nearest expiry
        opt_ref = self.db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(
            {"name": symbol, "series": series, "contractExpiration": {"$gte": target_iso}},
            sort=[("contractExpiration", 1)],
        )

        if not opt_ref:
            logger.error(f"Could not find any active {symbol} contracts in master.")
            return set()

        expiry = opt_ref["contractExpiration"]
        contracts = list(
            self.db[settings.INSTRUMENT_MASTER_COLLECTION].find(
                {"name": symbol, "series": series, "contractExpiration": expiry, "strikePrice": {"$in": target_strikes}}
            )
        )

        ids = {int(c["exchangeInstrumentID"]) for c in contracts}
        logger.debug(f"Resolved {len(ids)} contracts for ATM {atm_strike} window (±{window_size}) from DB")
        return ids

    @staticmethod
    def get_atm_strike(price: float, step: int = 50) -> float:
        """Helper to round a price to the nearest strike. Maps exactly to Java's Math.round behavior."""
        import math
        return math.floor((price / step) + 0.5) * step

    def derive_target_contracts(self, current_dt: datetime, strike_count: int | None = None):
        """
        Derives CE/PE contracts for ATM and +/- strike_count for the given date.
        Returns contracts for BOTH the Current Weekly and the Next Weekly expiries.
        Uses NIFTY spot closing price found in nifty_candle collection via MarketHistoryService.
        """
        if strike_count is None:
            strike_count = settings.OPTIONS_STRIKE_COUNT

        master_col = self.db[settings.INSTRUMENT_MASTER_COLLECTION]

        # 1. Get NIFTY closing price to determine ATM
        history_service = MarketHistoryService(self.db)
        spot_price = history_service.get_last_nifty_price(current_dt) or 0

        if spot_price <= 0:
            logger.warning(f"No NIFTY spot price found for {current_dt}. Cannot derive contracts.")
            return []

        # 2. Derive Strikes
        strike_step = settings.NIFTY_STRIKE_STEP
        atm_strike = round(spot_price / strike_step) * strike_step
        strikes = [atm_strike + (i * strike_step) for i in range(-strike_count, strike_count + 1)]

        # 3. Find Expiries: Current Weekly and Next Weekly
        dt_iso = DateUtils.to_iso(current_dt.replace(hour=0, minute=0, second=0, microsecond=0))
        
        # Get all future/current expiries sorted
        expiries = sorted(master_col.distinct(
            "contractExpiration", 
            {"exchangeSegment": "NSEFO", "name": "NIFTY", "series": "OPTIDX", "contractExpiration": {"$gte": dt_iso}}
        ))

        if not expiries:
            logger.warning(f"No active NIFTY expiries found in master for date {dt_iso}")
            return []

        # Take first three (Current, Next, and Next-Next)
        target_expiries = expiries[:3]
        logger.info(f"Deriving contracts for {len(target_expiries)} expiries: {target_expiries}")

        # 4. Fetch Contracts
        contracts = list(
            master_col.find(
                {
                    "exchangeSegment": "NSEFO",
                    "name": "NIFTY",
                    "series": "OPTIDX",
                    "contractExpiration": {"$in": target_expiries},
                    "strikePrice": {"$in": strikes},
                    "optionType": {"$in": [3, 4]},  # CE/PE
                }
            )
        )

        return contracts
