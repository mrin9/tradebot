import pytest
import sys
import os
from packages.config import settings

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

# Suppress noisy app logs during tests
os.environ["TESTING_ENV"] = "true"

# Standardize Default Test Database (Safety First)
settings.DB_NAME = "tradebot_test"

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    """
    1. Resets DB to 'tradebot_test' before any fixtures run.
    2. Allows test-specific fixtures to override it.
    3. Prints the header AFTER all setup is complete.
    """
    settings.DB_NAME = "tradebot_test"
    # Close connection to force picking up new DB_NAME if changed by fixtures
    from packages.utils.mongo import MongoRepository
    MongoRepository.close()

    yield # This runs all fixtures, including test-file overrides

    # Post-fixture execution: settings.DB_NAME is now final
    db_name = getattr(settings, "DB_NAME", "UNKNOWN")
    nifty_col = getattr(settings, "NIFTY_CANDLE_COLLECTION", "nifty_candle")
    
    # Extract the first line of the docstring
    test_doc = item.obj.__doc__ or "No description provided"
    test_desc = test_doc.strip().split("\n")[0]
    
    print(f"\n{'='*80}")
    print(f"🔍 TESTING: {test_desc}")
    print(f"🗄️  DATABASE: {db_name} | COLLECTION: {nifty_col}")
    print(f"🆔 ID: {item.nodeid}")
    print(f"{'='*80}")

def pytest_runtest_teardown(item, nextitem):
    """Add a line gap after the test result for better readability."""
    print("\n")
