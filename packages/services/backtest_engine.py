from abc import ABC, abstractmethod

from packages.services.trade_event import TradeEventService
from packages.settings import settings
from packages.tradeflow.fund_manager import FundManager
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.utils.trade_persistence import TradePersistence

logger = setup_logger("BacktestEngine")


class BacktestFeeder(ABC):
    """Abstract interface for feeding data into the BacktestEngine."""

    @abstractmethod
    def start(self, engine: "BacktestEngine"):
        pass


class DBFeeder(BacktestFeeder):
    """Feeds historical data from MongoDB."""

    def start(self, engine: "BacktestEngine"):
        fm = engine.fund_manager
        db = MongoRepository.get_db()

        # 1. Warmup
        from packages.services.market_history import MarketHistoryService

        MarketHistoryService(db).run_full_backtest_warmup(fm, engine.start_date, settings.GLOBAL_WARMUP_CANDLES)

        # 2. Get Trading Days
        iso_start = DateUtils._parse_keyword(engine.start_date, is_end=False).strftime("%Y-%m-%d")
        iso_end = DateUtils._parse_keyword(engine.end_date, is_end=True).strftime("%Y-%m-%d")
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        trading_days = sorted([d for d in available_days if iso_start <= d <= iso_end])

        if not trading_days:
            logger.error("No trading days found in range.")
            return

        logger.info(f"🧪 DB Mode Backtest Started: {len(trading_days)} days.")
        for day_str in trading_days:
            logger.info(f"📅 Trading Day: {day_str}")
            dt = DateUtils.parse_iso(day_str)
            day_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())
            eod_ts = int(dt.replace(hour=15, minute=30, second=0).timestamp())

            # Fetch Ticks
            nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
            nifty_cursor = db[settings.NIFTY_CANDLE_COLLECTION].find(
                {"i": nifty_id, "t": {"$gte": day_ts, "$lte": eod_ts}}
            )
            ticks = list(nifty_cursor)

            if fm.trade_instrument_type != "CASH":
                opt_cursor = db[settings.OPTIONS_CANDLE_COLLECTION].find({"t": {"$gte": day_ts, "$lte": eod_ts}})
                ticks.extend(list(opt_cursor))

            ticks.sort(key=lambda x: (x["t"], 1 if x["i"] == nifty_id else 0))

            for tick in ticks:
                fm.on_tick_or_base_candle(tick)

            fm.handle_eod_settlement(eod_ts)
            engine.record_daily_pnl(day_str)


class BacktestEngine:
    """
    Orchestrates the backtest session.
    """

    def __init__(
        self,
        strategy_config: dict,
        position_config: dict,
        start_date: str,
        end_date: str | None = None,
        mode: str = "db",
    ):
        self.strategy_config = strategy_config
        self.position_config = position_config
        self.start_date = start_date
        self.end_date = end_date or start_date
        self.mode = mode

        self.fund_manager = FundManager(
            strategy_config=strategy_config, position_config=position_config, is_backtest=True
        )

        # Performance optimization: Load contract cache for the symbol relative to backtest start
        bt_start_dt = DateUtils.parse_iso(self.start_date)
        self.fund_manager.discovery_service.load_cache(
            symbol=self.strategy_config.get("symbol", "NIFTY"),
            series=self.strategy_config.get("series", "OPTIDX"),
            effective_date=bt_start_dt,
        )

        self.daily_pnl = {}
        self._last_pnl_checkpoint = 0.0
        # 2. Setup Session ID
        # bt_start_dt is already defined above
        prefix = self.strategy_config.get("strategyId", "BT")
        self.session_id = DateUtils.generate_session_id(prefix, custom_time=bt_start_dt)
        self.event_service = TradeEventService(
            self.session_id, record_papertrade=position_config.get("record_papertrade", True)
        )

    def record_daily_pnl(self, day_str: str):
        current_total_pnl = sum([t.pnl for t in self.fund_manager.position_manager.trades_history])
        daily_increment = current_total_pnl - self._last_pnl_checkpoint
        self.daily_pnl[day_str] = daily_increment
        self._last_pnl_checkpoint = current_total_pnl
        logger.info(f"Day {day_str} PnL: {int(daily_increment):,} | Total: {int(current_total_pnl):,}")

    def run(self):
        """Starts the backtest execution."""
        if self.mode == "db":
            feeder = DBFeeder()
        else:
            # Fallback for now, could implement SocketFeeder here too
            raise NotImplementedError(f"Mode {self.mode} not implemented in BacktestEngine yet.")

        feeder.start(self)

        # Record INIT event with enriched config
        self.event_service.record_init(self.fund_manager, mode=self.mode)

        self.generate_report()
        self.save_results()

    def generate_report(self):
        pm = self.fund_manager.position_manager
        trades = pm.trades_history
        total_pnl = sum([t.pnl for t in trades])
        budget = self.position_config.get("budget", 200000.0)
        roi = (total_pnl / budget) * 100 if budget > 0 else 0

        logger.info("=" * 40)
        logger.info(f"BACKTEST COMPLETE | Total PnL: {total_pnl:,.2f} | ROI: {roi:.2f}%")
        logger.info(f"Total Trades: {len(trades)}")
        logger.info("=" * 40)

    def save_results(self):
        try:
            config_summary = TradeEventService.build_config_summary(self.fund_manager, mode=self.mode)

            persistence = TradePersistence()
            persistence.save_session_summary(
                session_id=self.session_id,
                trades=self.fund_manager.position_manager.trades_history,
                config=config_summary,
                daily_pnl=self.daily_pnl,
                is_live=False,
            )
            logger.info(f"✅ Results saved to {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to save results: {e}")
