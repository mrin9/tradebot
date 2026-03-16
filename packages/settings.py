from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 1. MongoDB Settings
    MONGODB_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "tradebot"

    @property
    def COLLECTION_SUFFIX(self) -> str:
        if self.DB_NAME == "tradebot_test":
            return "_test"
        if self.DB_NAME == "tradebot_frozen":
            return "_frozen"
        return ""

    @property
    def NIFTY_CANDLE_COLLECTION(self) -> str:
        return f"nifty_candle{self.COLLECTION_SUFFIX}"

    @property
    def OPTIONS_CANDLE_COLLECTION(self) -> str:
        return f"options_candle{self.COLLECTION_SUFFIX}"

    @property
    def STOCK_TICKS_PER_SECOND_COLLECTION(self) -> str:
        return f"stockticks_per_second{self.COLLECTION_SUFFIX}"

    @property
    def ACTIVE_CONTRACT_COLLECTION(self) -> str:
        return f"active_contract{self.COLLECTION_SUFFIX}"

    @property
    def INSTRUMENT_MASTER_COLLECTION(self) -> str:
        return f"instrument_master{self.COLLECTION_SUFFIX}"

    @property
    def STOCK_INDICATOR_COLLECTION(self) -> str:
        return f"stock_indicator{self.COLLECTION_SUFFIX}"

    @property
    def BACKTEST_RESULT_COLLECTION(self) -> str:
        return f"backtest{self.COLLECTION_SUFFIX}"

    @property
    def STRATEGY_INDICATORS_COLLECTION(self) -> str:
        return f"strategy_indicator{self.COLLECTION_SUFFIX}"

    @property
    def LIVE_TRADES_COLLECTION(self) -> str:
        return f"livetrade{self.COLLECTION_SUFFIX}"

    @property
    def PAPERTRADE_COLLECTION(self) -> str:
        return f"papertrade{self.COLLECTION_SUFFIX}"

    # 1.5 NIFTY Specifics
    NIFTY_EXCHANGE_SEGMENT: int = 1
    NIFTY_EXCHANGE_INSTRUMENT_ID: int = 26000
    NIFTY_INSTRUMENT_ID: int = 26000  # Alias as requested
    NIFTY_LOT_SIZE: int = 65
    NIFTY_STRIKE_STEP: int = 50

    OPTIONS_STRIKE_COUNT: int = 10  # ATM +/- 10 strikes

    # 1.6 Backtesting Defaults
    BACKTEST_STOP_LOSS: float = 15.0
    BACKTEST_TARGET_STEPS: str = "15,25,50"
    BACKTEST_INVEST_MODE: str = "compound"
    GLOBAL_WARMUP_CANDLES: int = 200
    BACKTEST_PRICE_SOURCE: str = "close"  # Default price source for backtest (open or close)

    # 2. Core Operation Modes
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    DEFAULT_TIMEFRAME: int = 180

    # 4. Socket & Simulator Settings
    SOCKET_SIMULATOR_URL: str = "http://localhost:5050"

    # 6. XTS API Configuration
    XTS_ROOT_URL: str = "https://blazemum.indiainfoline.com"
    XTS_SOURCE: str = "WEBAPI"
    XTS_DISABLE_SSL: bool = True
    XTS_BROADCAST_MODE: Literal["Full", "Partial"] = "Full"

    # XTS Time Offset: API returns timestamps shifted by +5.5h (treats IST as UTC)
    XTS_TIME_OFFSET: int = 19800

    # 7. Sensitive API Credentials (Stored in .env)
    MARKET_API_KEY: str | None = None
    MARKET_API_SECRET: str | None = None
    INTERACTIVE_API_KEY: str | None = None
    INTERACTIVE_API_SECRET: str | None = None

    @field_validator("*", mode="after")
    @classmethod
    def unescape_dollar_signs(cls, v):
        if isinstance(v, str):
            return v.replace("$$", "$")
        return v

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
