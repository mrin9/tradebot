import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    print("Testing DateUtils import...")
    from packages.utils.date_utils import DateUtils
    print(f"DateUtils imported. Current Time: {DateUtils.to_iso(DateUtils.get_market_time())}")
    
    print("\nTesting Config import...")
    from packages.config import settings
    print(f"Config imported. Market Timezone: {settings.MARKET_TIMEZONE}")

    print("\nTesting XTS Wrapper import...")
    from packages.data.connectors.xts_wrapper import XTSManager
    print("XTSManager imported.")
    
    print("\nAll Core Imports Successful!")

except Exception as e:
    print(f"\nIMPORT FAILED: {e}")
    sys.exit(1)
