from collections.abc import Callable

from packages.services.contract_discovery import ContractDiscoveryService
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger("DriftManager")


class DriftManager:
    """
    Manages the detection of ATM drift and resolving target option contracts.
    Decoupled from FundManager to allow independent testing and re-use.
    """

    def __init__(
        self, discovery_service: ContractDiscoveryService, drift_threshold: float = 25, instrument_type: str = "OPTIONS"
    ):
        self.discovery_service = discovery_service
        self.drift_threshold = drift_threshold
        self.instrument_type = instrument_type

        self.selection_spot_price: float | None = None
        self.last_day_str: str | None = None

        # {category: instrument_id}
        self.active_instruments: dict[str, int] = {"SPOT": 26000}
        self.active_descriptions: dict[str, str] = {}

        self.on_instruments_changed: Callable[[dict[str, int]], None] | None = None

    def check_drift(self, current_spot: float, current_ts: float) -> bool:
        """
        Checks if the spot price has drifted enough to require a change in monitored instruments.
        Returns True if instruments were updated.
        """
        if self.instrument_type != "OPTIONS":
            return False

        atm_strike = self.discovery_service.get_atm_strike(current_spot)

        # 1. Day Change Check
        current_day_str = DateUtils.market_timestamp_to_datetime(current_ts).strftime("%Y-%m-%d")
        is_new_day = False
        if self.last_day_str != current_day_str:
            is_new_day = True
            self.last_day_str = current_day_str

        # 2. Threshold Check
        needs_update = False
        if self.selection_spot_price is None or is_new_day:
            needs_update = True
        elif abs(current_spot - self.selection_spot_price) > self.drift_threshold:
            logger.debug(TradeFormatter.format_drift(current_spot, self.selection_spot_price))
            needs_update = True

        if needs_update:
            self.selection_spot_price = current_spot
            old_instruments = self.active_instruments.copy()

            for cat, is_ce in [("CE", True), ("PE", False)]:
                new_id, new_desc = self.discovery_service.resolve_option_contract(atm_strike, is_ce, current_ts)
                if new_id:
                    new_id_int = int(new_id)
                    if self.active_instruments.get(cat) != new_id_int:
                        self.active_instruments[cat] = new_id_int
                        self.active_descriptions[cat] = new_desc
                else:
                    logger.warning(
                        f"⚠️ DriftManager: Failed to resolve {cat} contract for strike {atm_strike} at {current_ts}"
                    )

            if self.on_instruments_changed:
                # Provide info about which ones changed
                changed_info = {
                    "current_ts": current_ts,
                    "instruments": {
                        cat: {
                            "id": self.active_instruments[cat],
                            "desc": self.active_descriptions.get(cat),
                            "is_new": self.active_instruments[cat] != old_instruments.get(cat),
                        }
                        for cat in ["CE", "PE"]
                        if self.active_instruments.get(cat)
                    },
                }
                self.on_instruments_changed(changed_info)

            return True

        return False

    def get_instrument_id(self, category: str) -> int | None:
        return self.active_instruments.get(category)

    def get_description(self, category: str) -> str | None:
        return self.active_descriptions.get(category)
