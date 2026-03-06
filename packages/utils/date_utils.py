import datetime
import pytz
from typing import Tuple, Union

# Constants
MARKET_TZ = pytz.timezone('Asia/Kolkata')
UTC_TZ = pytz.utc
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
FMT_ISO_DATE = DATE_FORMAT
FMT_CLI_FULL = "%Y-%m-%d %H:%M:%S"

class DateUtils:
    """
    Standardized date and time utilities for the trade-bot project.
    Enforces Asia/Kolkata for inputs/display and UTC for internal storage where applicable.
    """
    MARKET_TZ = MARKET_TZ
    UTC_TZ = UTC_TZ
    DATE_FORMAT = DATE_FORMAT
    DATETIME_FORMAT = DATETIME_FORMAT

    @staticmethod
    def to_utc(dt: datetime.datetime) -> datetime.datetime:
        """Converts a datetime object to UTC."""
        if dt.tzinfo is None:
            # Assume it's in MARKET_TZ if naive, or raise warning? 
            # For safety, let's localize to MARKET_TZ first if naive
            dt = MARKET_TZ.localize(dt)
        return dt.astimezone(UTC_TZ)

    @staticmethod
    def to_iso(dt: datetime.datetime) -> str:
        """Returns ISO 8601 formatted string (YYYY-MM-DDTHH:MM:SS)."""
        return dt.strftime(DATETIME_FORMAT)

    @staticmethod
    def to_iso_date(dt: datetime.datetime) -> str:
        """Returns ISO 8601 date string (YYYY-MM-DD)."""
        return dt.strftime(DATE_FORMAT)

    @staticmethod
    def to_timestamp(dt: datetime.datetime, end_of_day: bool = False) -> int:
        """
        Converts a datetime to a UNIX timestamp.
        If end_of_day is True, sets the time to the end of that day (23:59:59).
        """
        if dt.tzinfo is None:
            dt = MARKET_TZ.localize(dt)
            
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            
        return int(dt.timestamp())

    # XTS Epoch Offset: 10 years (1970 to 1980) including leap years 1972, 1976
    # 3652 days * 86400 seconds = 315532800
    XTS_EPOCH_OFFSET = 315532800

    @staticmethod
    def xts_epoch_to_utc(ts: Union[int, float]) -> Union[int, float]:
        """
        XTS sockets send timestamps as IST-shifted seconds since Jan 1, 1980.
        This converts it back to a standard Unix UTC epoch (since Jan 1, 1970).
        """
        if ts and isinstance(ts, (int, float)) and ts > 1000000:
            # 1. Add 10 year offset to move from 1980-base to 1970-base
            # 2. Subtract 19800 seconds to move from IST to UTC
            return ts + DateUtils.XTS_EPOCH_OFFSET - 19800
        return ts

    @staticmethod
    def market_timestamp_to_iso(ts: Union[int, float]) -> str:
        """Converts a market/feed UTC epoch timestamp to Asia/Kolkata ISO string (YYYY-MM-DDTHH:MM:SS)."""
        if ts is None:
            return ""
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        dt_kolkata = dt.astimezone(MARKET_TZ)
        return dt_kolkata.strftime(DATETIME_FORMAT)

    @staticmethod
    def market_timestamp_to_datetime(ts: Union[int, float]) -> datetime.datetime:
        """Converts a market/feed UNIX timestamp to a localized Asia/Kolkata datetime object."""
        return datetime.datetime.fromtimestamp(ts, tz=MARKET_TZ)

    @staticmethod
    def parse_iso(date_str: str) -> datetime.datetime:
        """Parses an ISO string into a datetime object."""
        # Check if it's just a date
        try:
            dt = datetime.datetime.strptime(date_str, DATE_FORMAT)
            return MARKET_TZ.localize(dt)
        except ValueError:
            pass
        
        # Check if it includes time
        try:
            dt = datetime.datetime.strptime(date_str, DATETIME_FORMAT)
            return MARKET_TZ.localize(dt)
        except ValueError:
            # Try with native fromisoformat for other variations
            dt = datetime.datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = MARKET_TZ.localize(dt)
            return dt

    @staticmethod
    def parse_date_range(range_str: str) -> Tuple[datetime.datetime, datetime.datetime]:
        """
        Parses a date range string in the format 'start|end'.
        Supports keywords: 'now', 'yesterday', 'today', '2dago', etc.
        Example: '2dago|now' -> (2 days ago start of day, current time)
        """
        if '|' not in range_str:
            # Treat as single date/start point? Or imply |now?
            # For now, let's assume it's a single date for start, and end is end of that day
            start_str = range_str
            end_str = range_str # If single date, range is that full day?
            # Or maybe single date implies start=date, end=now? 
            # Let's stick to the separator rule for clarity, but handle single dates as full day
            pass
        else:
            start_str, end_str = range_str.split('|')

        start_dt = DateUtils._parse_keyword(start_str, is_end=False)
        end_dt = DateUtils._parse_keyword(end_str, is_end=True)

        return start_dt, end_dt

    @staticmethod
    def _parse_keyword(keyword: str, is_end: bool = False) -> datetime.datetime:
        now = datetime.datetime.now(MARKET_TZ)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        keyword = keyword.lower().strip()

        if keyword == 'now':
            return now
        elif keyword == 'today':
            return today if not is_end else today.replace(hour=23, minute=59, second=59)
        elif keyword == 'yesterday':
            Yesterday = today - datetime.timedelta(days=1)
            return Yesterday if not is_end else Yesterday.replace(hour=23, minute=59, second=59)
        elif 'dago' in keyword:
            try:
                days = int(keyword.replace('dago', ''))
                target_date = today - datetime.timedelta(days=days)
                return target_date if not is_end else target_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                pass # Fall through to ISO parse
        
        if keyword == '':
            return now if is_end else today # Default empty start to today start, empty end to now?

        # Try parsing as explicit date
        try:
            dt = DateUtils.parse_iso(keyword)
            # If it was just a date (00:00:00), and we want end, move to end of day
            if is_end and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                 dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            raise ValueError(f"Unknown date keyword or format: {keyword}")

    @staticmethod
    def get_date_chunks(start_dt: datetime.datetime, end_dt: datetime.datetime, chunk_size_days: int) -> list[Tuple[datetime.datetime, datetime.datetime]]:
        """
        Splits a date range into smaller chunks of 'chunk_size_days'.
        Returns a list of (chunk_start, chunk_end) tuples.
        """
        chunks = []
        current_start = start_dt
        while current_start < end_dt:
            current_end = min(current_start + datetime.timedelta(days=chunk_size_days), end_dt)
            chunks.append((current_start, current_end))
            current_start = current_end + datetime.timedelta(seconds=1)
        return chunks

    @staticmethod
    def get_available_dates(db, collection_name: str) -> list[str]:
        """
        Scans a collection for unique trading days (YYYY-MM-DD).
        Relies on the 't' (timestamp) field.
        """
        pipeline = [
            {
                "$project": {
                    "date": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": {"$toDate": {"$multiply": ["$t", 1000]}},
                            "timezone": "Asia/Kolkata"
                        }
                    }
                }
            },
            {
                "$group": {
                    "_id": "$date"
                }
            },
            {
                "$sort": {"_id": 1}
            }
        ]
        results = db[collection_name].aggregate(pipeline)
        return [r["_id"] for r in results if r["_id"]]




