from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    # 1. MongoDB Settings
    MONGODB_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "tradebot"
    
    # Collection Names (camelCase per new standard, but mapped to existing if needed)
    # Using existing names for compatibility with old DB
    NIFTY_CANDLE_COLLECTION: str = "nifty_candle"
    OPTIONS_CANDLE_COLLECTION: str = "options_candle"
    STOCK_TICKS_PER_SECOND_COLLECTION: str = "stockticks_per_second"
    ACTIVE_CONTRACT_COLLECTION: str = "active_contract"
    INSTRUMENT_MASTER_COLLECTION: str = "instrument_master"
    STOCK_INDICATOR_COLLECTION: str = "stock_indicator"
    BACKTEST_RESULT_COLLECTION: str = "backtest_results"

    # 1.5 NIFTY Specifics
    NIFTY_EXCHANGE_SEGMENT: int = 1
    NIFTY_EXCHANGE_INSTRUMENT_ID: int = 26000
    NIFTY_INSTRUMENT_ID: int = 26000 # Alias as requested
    NIFTY_LOT_SIZE: int = 65
    NIFTY_STRIKE_STEP: int = 50
    
    OPTIONS_STRIKE_COUNT: int = 10  # ATM +/- 10 strikes

    # 1.6 Backtesting Defaults
    BACKTEST_STOP_LOSS: float = 15.0
    BACKTEST_TARGET_STEPS: str = "15,25,50"
    BACKTEST_INVEST_MODE: str = "compound"
    BACKTEST_WARMUP_CANDLES: int = 200
    
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
    XTS_API_KEY: str | None = None
    XTS_API_SECRET: str | None = None
    MARKET_API_KEY: str | None = None
    MARKET_API_SECRET: str | None = None
    INTERACTIVE_API_KEY: str | None = None
    INTERACTIVE_API_SECRET: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

settings = Settings()
