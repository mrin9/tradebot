from packages.config import settings
from packages.data.connectors.xts_sdk.XTSConnect import XTSConnect
from packages.data.connectors.xts_sdk.MarketDataSocketClient import MDSocket_io
from packages.utils.log_utils import setup_logger

logger = setup_logger(__name__)

class XTSManager:
    """
    Centralized manager for XTS connections.
    Handles authentication and instance management for both Market and Interactive APIs.
    """
    _market_client: XTSConnect = None
    _interactive_client: XTSConnect = None
    _socket_client: MDSocket_io = None

    @classmethod
    def get_market_client(cls) -> XTSConnect:
        """Returns an authenticated XTSConnect instance for Market Data API."""
        if cls._market_client is None:
            logger.info("Initializing Market Data API Client...")
            cls._market_client = XTSConnect(
                apiKey=settings.MARKET_API_KEY,
                secretKey=settings.MARKET_API_SECRET,
                source=settings.XTS_SOURCE,
                root=settings.XTS_ROOT_URL,
                disable_ssl=settings.XTS_DISABLE_SSL
            )
            
            response = cls._market_client.marketdata_login()
            if response and 'result' in response and 'token' in response['result']:
                logger.info(f"Market Data Login Successful. Token: {response['result']['token'][:10]}...")
            else:
                logger.error(f"Market Data Login Failed: {response}")
                raise Exception(f"Market Data Login Failed: {response}")
                
        return cls._market_client

    @classmethod
    def get_market_data_socket(cls, debug: bool = False) -> MDSocket_io:
        """Returns an authenticated Socket IO client for Market Data."""
        if cls._socket_client is None:
            # Ensure we have a valid token first
            market_client = cls.get_market_client()
            token = market_client.token
            
            logger.info("Initializing Market Data Socket...")
            cls._socket_client = MDSocket_io(
                token=token,
                userID=market_client.userID,
                logger=debug, 
                engineio_logger=debug,
                get_raw_data=True
            )
            
        return cls._socket_client

    @classmethod
    def get_interactive_client(cls) -> XTSConnect:
        """Returns an authenticated XTSConnect instance for Interactive API."""
        if cls._interactive_client is None:
             logger.info("Initializing Interactive API Client...")
             cls._interactive_client = XTSConnect(
                 apiKey=settings.INTERACTIVE_API_KEY,
                 secretKey=settings.INTERACTIVE_API_SECRET,
                 source=settings.XTS_SOURCE,
                 root=settings.XTS_ROOT_URL,
                 disable_ssl=settings.XTS_DISABLE_SSL
             )
             
             response = cls._interactive_client.interactive_login()
             if response and 'result' in response and 'token' in response['result']:
                 logger.info(f"Interactive Login Successful. Token: {response['result']['token'][:10]}...")
             else:
                 logger.error(f"Interactive Login Failed: {response}")
                 raise Exception(f"Interactive Login Failed: {response}")

        return cls._interactive_client
