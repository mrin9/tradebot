from datetime import datetime, timedelta
from packages.config import settings
from packages.utils.mongo import MongoRepository
from packages.utils.log_utils import setup_logger
from packages.utils.date_utils import DateUtils, FMT_ISO_DATE
from packages.data.managers.sync_history import HistoricalDataCollector
from packages.utils.market_utils import MarketUtils

logger = setup_logger(__name__)

def _generate_diagnostic_report(s_dt: datetime, e_dt: datetime, strike_count: int = None):
    """
    Internal helper to generate a completeness report.
    """
    if strike_count is None:
        strike_count = settings.OPTIONS_STRIKE_COUNT

    db = MongoRepository.get_db()
    nifty_col = db[settings.NIFTY_CANDLE_COLLECTION]
    options_col = db[settings.OPTIONS_CANDLE_COLLECTION]
    master_col = db[settings.INSTRUMENT_MASTER_COLLECTION]
    
    # Normalize to loop by days
    current_dt = s_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    end_loop_dt = e_dt.replace(hour=23, minute=59, second=59)
    
    days_to_check = []
    while current_dt <= end_loop_dt:
        days_to_check.append(current_dt)
        current_dt += timedelta(days=1)
        
    report = []
    
    for dt in days_to_check:
        day_str = dt.strftime(FMT_ISO_DATE)
        weekday = dt.strftime("%A")
        start_ts = DateUtils.to_timestamp(dt)
        end_ts = DateUtils.to_timestamp(dt, end_of_day=True)
        
        # 1. Check Spot Data
        nifty_count = nifty_col.count_documents({
            "i": settings.NIFTY_EXCHANGE_INSTRUMENT_ID,
            "t": {"$gte": start_ts, "$lte": end_ts}
        })
        
        row = {
            "date": day_str,
            "weekday": weekday,
            "nifty_count": nifty_count,
            "opt_status": "N/A",
            "status": "NO DATA",
            "color": "\033[90m", # Gray
            "missing_contracts": []
        }

        if nifty_count == 0:
            report.append(row)
            continue

        # 2. Identify Target Contracts via MarketUtils
        expected_contracts = MarketUtils.derive_target_contracts(db, dt, strike_count=strike_count)
        
        if expected_contracts:
            active_ids = [c["exchangeInstrumentID"] for c in expected_contracts]
            total_expected = len(active_ids)
            
            # Check count for each contract
            counts = list(options_col.aggregate([
                {"$match": {"i": {"$in": active_ids}, "t": {"$gte": start_ts, "$lte": end_ts}}},
                {"$group": {"_id": "$i", "count": {"$sum": 1}}}
            ]))
            
            complete_count = sum(1 for c in counts if c['count'] >= 375)
            row['opt_status'] = f"{complete_count}/{total_expected} instr"
            row['missing_contracts'] = list(set(active_ids) - set(c['_id'] for c in counts if c['count'] >= 375))
            
            if nifty_count >= 375 and complete_count == total_expected:
                row['status'] = "FULL DATA"
                row['color'] = "\033[92m" # Green
            else:
                row['status'] = "PARTIAL"
                row['color'] = "\033[93m" # Yellow
        else:
            # If NIFTY missing, spot_price was 0 and result was empty list
            if nifty_count > 0:
                 row['opt_status'] = "NO MASTER/CLOSE"
                 row['status'] = "MISSING DATA"
                 row['color'] = "\033[91m"
            else:
                row['status'] = "SPOT MISSING"
                row['color'] = "\033[91m" # Red
            
        report.append(row)
        
    return report

def check_data_gaps(start_str: str, end_str: str, strike_count: int = None):
    """
    Analyzes data completeness for NIFTY vs derived Options.
    Reports count of 1-min candles for Spot and average count for Options.
    """
    if strike_count is None:
        strike_count = settings.OPTIONS_STRIKE_COUNT
        
    # Parse Range
    s_dt, e_dt = DateUtils.parse_date_range(f"{start_str}|{end_str}")
    
    print(f"\n{'='*20} DATA GAP ANALYSIS {'='*20}")
    print(f"{'Date':<12} | {'Day':<10} | {'Nifty (375)':<15} | {f'Options (ATM+/-{strike_count})':<18} | {'Status'}")
    print("-" * 100)
    
    report = _generate_diagnostic_report(s_dt, e_dt, strike_count=strike_count)
    
    for row in report:
        day_str = row['date']
        weekday = row['weekday']
        nifty_count = row['nifty_count']
        opt_status = row['opt_status']
        status = row['status']
        color = row['color']
        reset = "\033[0m"
        
        print(f"{day_str:<12} | {weekday:<10} | {nifty_count:<15} | {opt_status:<18} | {color}{status}{reset}")
        
    print("-" * 100)


def fill_data_gaps(date_range_keyword: str):
    """
    Identifies missing data and attempts to fetch it from XTS.
    Shows before and after state.
    """
    s_dt, e_dt = DateUtils.parse_date_range(date_range_keyword)
    
    print("\n[1/3] ANALYZING GAPS BEFORE UPDATE...")
    check_data_gaps(s_dt.strftime(FMT_ISO_DATE), e_dt.strftime(FMT_ISO_DATE), strike_count=settings.OPTIONS_STRIKE_COUNT)
    
    report = _generate_diagnostic_report(s_dt, e_dt, strike_count=settings.OPTIONS_STRIKE_COUNT)
    collector = HistoricalDataCollector()
    
    total_fetched = 0
    days_to_process = [r for r in report if r['status'] != "FULL DATA"]
    
    if not days_to_process:
        logger.info("No gaps identified. System is up to date.")
        return

    print(f"\n[2/3] FILLING GAPS FOR {len(days_to_process)} DAYS...")
    
    for row in days_to_process:
        dt_start = DateUtils.parse_iso(row['date'])
        dt_end = dt_start.replace(hour=23, minute=59, second=59)
        
        # 1. Fill NIFTY Spot if missing or partial
        if row['nifty_count'] < 375:
            logger.info(f"Targeting NIFTY Spot for {row['date']}...")
            added = collector.sync_for_instrument(settings.NIFTY_EXCHANGE_INSTRUMENT_ID, dt_start, dt_end, is_index=True)
            total_fetched += added
        
        # 2. Fill Options
        if row['missing_contracts']:
            logger.info(f"Targeting {len(row['missing_contracts'])} missing options for {row['date']}...")
            for inst_id in row['missing_contracts']:
                added = collector.sync_for_instrument(inst_id, dt_start, dt_end, is_index=False)
                total_fetched += added
                
    print(f"\n[3/3] ANALYZING GAPS AFTER UPDATE... (Total New Candles: {total_fetched})")
    check_data_gaps(s_dt.strftime(FMT_ISO_DATE), e_dt.strftime(FMT_ISO_DATE), strike_count=settings.OPTIONS_STRIKE_COUNT)
