from typing import Dict, List, Any, Optional
from datetime import datetime
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter
from packages.utils.trade_persistence import TradePersistence
from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils

logger = setup_logger("TradeEventService")

class TradeEventService:
    """
    Centralized sink for all trade-related events (init, signals, trades, summary).
    Handles formatting, logging, and DB persistence.
    """
    def __init__(self, session_id: str, record_papertrade: bool = True):
        self.session_id = session_id
        self.record_papertrade = record_papertrade
        self.persistence = TradePersistence()
        self.db = MongoRepository.get_db()
        self.active_signals: List[Dict] = []

    def record_init(self, fund_manager: Any, mode: str = "live"):
        """Records the session initialization."""
        config = self.build_config_summary(fund_manager, mode=mode)
        event = {
            "type": "INIT",
            "msg": "Trading session initialized.",
            "config": config
        }
        self._persist_non_position_event(event)

    def record_signal(self, payload: Dict):
        """Records a strategy signal."""
        self.active_signals.append(payload)
        
        # Format and log the signal
        # payload format from FundManager contains signal name, reason, etc.
        log_msg = TradeFormatter.format_signal(
            signal_name=payload.get('reason_desc', 'SIGNAL'),
            reason=payload.get('reason', ''),
            time_str=datetime.fromtimestamp(payload.get('timestamp', 0)).strftime("%H:%M:%S"),
            timeframe=payload.get('timeframe', 0),
            indicators={} # Indicators are logged in heartbeat, keeping signal clean
        )
        logger.info(log_msg)

    def record_trade_event(self, event_data: Dict, fund_manager: Any):
        """
        Records position-specific events (Entry, Target, Exit, SL).
        """
        if not self.record_papertrade:
            return
            
        # Skip summary records in papertrade collection as requested
        if event_data.get("type", "").upper() == "SUMMARY":
            return

        nifty_price = fund_manager.latest_tick_prices.get(26000, 0.0)
        pos_manager = fund_manager.position_manager
        pos = pos_manager.current_position
        
        if pos:
            # Update realised pnl for the session on the position object for formatter
            setattr(pos, 'session_realized_pnl', pos_manager.session_realized_pnl)
            
            # Record via persistence utility
            self.persistence.record_granular_event(
                session_id=self.session_id,
                event_type=event_data.get("type", "EVENT"),
                pos=pos,
                nifty_price=nifty_price,
                msg=event_data.get("transaction"),
                action_pnl=event_data.get("actionPnL", 0.0)
            )
            
            # If it's an exit or target event, sync the full session summary
            if event_data.get("type", "").lower() in ["exit", "target", "breakeven"]:
                self.sync_session_summary(fund_manager)
        else:
            # Handle events that happen when no position is active (e.g., target hit on closed chunk)
            self._persist_non_position_event(event_data, fund_manager)

    @staticmethod
    def build_config_summary(fund_manager: Any, mode: str = "live") -> Dict:
        """
        Builds a comprehensive configuration summary for the session.
        """
        config = fund_manager.config.copy()
        config.update({
            "mode": mode,
            "strategy": fund_manager.config.get('name'),
            "strategyId": fund_manager.config.get('strategyId'),
            "python_strategy_path": fund_manager.position_config.get("python_strategy_path") or fund_manager.config.get("pythonStrategyPath"),
            "timeframe": fund_manager.global_timeframe,
            "indicators": [
                f"{ind.get('InstrumentType', 'SPOT').replace('_', '-')}-{ind.get('indicator', 'N/A')}".upper()
                for ind in fund_manager.indicator_calculator.config
            ],
            "tsl_indicator_id": fund_manager.tsl_indicator_id,
            "budget": fund_manager.position_config.get("budget"),
            "invest_mode": fund_manager.invest_mode,
            "stop_loss_points": fund_manager.stop_loss_points,
            "target_points": fund_manager.target_points,
            "trailing_sl_points": fund_manager.trailing_sl_points,
            "use_break_even": fund_manager.use_break_even,
            "strike_selection": getattr(fund_manager, 'strike_selection', 'ATM'),
            "price_source": getattr(fund_manager, 'price_source', 'close'),
            "pyramid_steps": fund_manager.position_config.get("pyramid_steps"),
            "pyramid_confirm_pts": fund_manager.position_config.get("pyramid_confirm_pts"),
        })
        return config

    def sync_session_summary(self, fund_manager: Any):
        """
        Synchronizes the current session state to the summary collection.
        """
        try:
            pos_manager = fund_manager.position_manager
            
            daily_pnl = {}
            today_str = datetime.now(DateUtils.MARKET_TZ).strftime("%Y-%m-%d")
            daily_pnl[today_str] = pos_manager.session_realized_pnl
            
            # Prepare config summary
            config = self.build_config_summary(fund_manager, mode="live")
            
            self.persistence.save_session_summary(
                session_id=self.session_id,
                trades=pos_manager.trades_history,
                config=config,
                daily_pnl=daily_pnl,
                is_live=True
            )
            self.persistence.update_session_status(self.session_id, "ACTIVE", is_live=True)
            
        except Exception as e:
            logger.error(f"❌ Failed to sync session summary: {e}")

    def _persist_non_position_event(self, event_data: Dict, fund_manager: Optional[Any] = None):
        """Helper to persist generic events to papertrade collection."""
        # Skip summary records in papertrade
        if event_data.get("type", "").upper() == "SUMMARY":
            return

        event_data.update({
            "sessionId": self.session_id,
            "createdAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat()
        })
        # Remove redundant timestamp
        if "timestamp" in event_data:
            del event_data["timestamp"]

        try:
            self.db["papertrade"].insert_one(event_data)
        except Exception as e:
            logger.error(f"❌ Failed to record non-position event: {e}")
