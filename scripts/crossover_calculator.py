import sys
import os
import argparse
from datetime import datetime, time, timedelta
import polars as pl
from typing import List, Optional
from rich.console import Console
from rich.table import Table

# Enforce project root in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.config import settings

console = Console()

def get_instrument_id(db, description: str) -> Optional[int]:
    """Finds the exchangeInstrumentID for a given description."""
    # Special case for NIFTY
    if description.upper() == "NIFTY":
        return settings.NIFTY_EXCHANGE_INSTRUMENT_ID
        
    doc = db[settings.INSTRUMENT_MASTER_COLLECTION].find_one({"description": description})
    if doc:
        return int(doc["exchangeInstrumentID"])
    return None

def fetch_candles(db, instrument_id: int, date_str: str, is_index: bool = False):
    """Fetches 1-minute candles for a specific day."""
    collection = settings.NIFTY_CANDLE_COLLECTION if is_index else settings.OPTIONS_CANDLE_COLLECTION
    
    # Parse date to get start and end timestamps in IST (and convert to UTC since DB stores UTC)
    # Actually DB 't' seems to be epoch seconds in IST (per sync_history.py logic? No, check sync_history.py)
    # _parse_ohlc_string does: "t": int(parts[0]) - settings.XTS_TIME_OFFSET
    # settings.XTS_TIME_OFFSET is 19800 (5.5h)
    # XTS API returns IST time as if it's UTC. So subtracting 19800 makes it UTC epoch.
    
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    
    cursor = db[collection].find({
        "i": instrument_id,
        "t": {"$gte": start_ts, "$lt": end_ts}
    }).sort("t", 1)
    
    data = list(cursor)
    if not data:
        return pl.DataFrame()
        
    df = pl.DataFrame(data)
    # Convert 't' to datetime (already UTC epoch)
    df = df.with_columns(
        time = pl.from_epoch("t", time_unit="s")
    )
    # Convert to IST for display and logic
    df = df.with_columns(
        time_ist = df["time"].dt.convert_time_zone("Asia/Kolkata")
    )
    return df

def calculate_crossovers(df: pl.DataFrame, fast: int, slow: int, timeframe_sec: int):
    """Resamples data and calculates crossovers."""
    if df.is_empty():
        return pl.DataFrame()

    # Resample to timeframe_sec
    # Polars 'group_by_dynamic' or 'upsample'
    # We'll use sort and then group_by_dynamic
    df = df.sort("time_ist")
    
    # Resample logic
    resampled = (
        df.group_by_dynamic("time_ist", every=f"{timeframe_sec}s")
        .agg([
            pl.col("o").first().alias("open"),
            pl.col("h").max().alias("high"),
            pl.col("l").min().alias("low"),
            pl.col("c").last().alias("close"),
            pl.col("v").sum().alias("volume")
        ])
    )
    
    # Calculate EMAs
    resampled = resampled.with_columns([
        resampled["close"].ewm_mean(span=fast, adjust=False).alias("ema_fast"),
        resampled["close"].ewm_mean(span=slow, adjust=False).alias("ema_slow")
    ])
    
    # Shift to get previous values
    resampled = resampled.with_columns([
        pl.col("ema_fast").shift(1).alias("ema_fast_prev"),
        pl.col("ema_slow").shift(1).alias("ema_slow_prev")
    ])
    
    # Detect Crossover
    # Bullish: prev fast < prev slow AND curr fast > curr slow
    # Bearish: prev fast > prev slow AND curr fast < curr slow
    resampled = resampled.with_columns(
        is_bullish = (pl.col("ema_fast_prev") < pl.col("ema_slow_prev")) & (pl.col("ema_fast") > pl.col("ema_slow")),
        is_bearish = (pl.col("ema_fast_prev") > pl.col("ema_slow_prev")) & (pl.col("ema_fast") < pl.col("ema_slow"))
    )
    
    crossovers = resampled.filter(pl.col("is_bullish") | pl.col("is_bearish"))
    return crossovers, resampled

def main():
    parser = argparse.ArgumentParser(description="EMA Crossover Calculator using Polars")
    parser.add_argument("--instrument", type=str, help="Instrument description (e.g., NIFTY2630225400CE)")
    parser.add_argument("--date", type=str, help="ISO Date (YYYY-MM-DD)")
    parser.add_argument("--crossover", type=str, default="EMA-5-21", help="Crossover (e.g., EMA-5-21 or SMA-9-13)")
    parser.add_argument("--timeframe", type=int, default=180, help="Timeframe in seconds")
    
    args = parser.parse_args()
    
    db = MongoRepository.get_db()
    
    # 1. Defaults
    date_str = args.date
    if not date_str:
        available_dates = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        if available_dates:
            date_str = sorted(available_dates, reverse=True)[0]
        else:
            console.print("[red]Error: No data found in nifty_candle collection.[/red]")
            return

    # Parse Crossover
    parts = args.crossover.split("-")
    type_name = parts[0]
    fast_period = int(parts[1])
    slow_period = int(parts[2])
    
    if not args.instrument:
        console.print("[red]Error: Instrument description required.[/red]")
        return

    name1 = args.instrument.upper()
    # Derive twin instrument
    if name1.endswith("CE"):
        name2 = name1[:-2] + "PE"
    elif name1.endswith("PE"):
        name2 = name1[:-2] + "CE"
    else:
        console.print(f"[red]Error: Instrument '{name1}' must end with CE or PE to calculate counterpart.[/red]")
        return

    # Get IDs
    id1 = get_instrument_id(db, name1)
    if not id1:
        console.print(f"[red]Error: Instrument '{name1}' not found in master.[/red]")
        return
        
    id2 = get_instrument_id(db, name2)
    if not id2:
        console.print(f"[yellow]Warning: Twin instrument '{name2}' not found in master.[/yellow]")

    nifty_id = settings.NIFTY_EXCHANGE_INSTRUMENT_ID
    
    # 2. Fetch Data
    console.print(f"[blue]Fetching data for {date_str}...[/blue]")
    
    # Fetch NIFTY
    nifty_df = fetch_candles(db, nifty_id, date_str, is_index=True)
    if nifty_df.is_empty():
        console.print("[red]No NIFTY data found.[/red]")
        return
        
    # Fetch Instrument 1
    df1 = fetch_candles(db, id1, date_str)
    if df1.is_empty():
        console.print(f"[red]No data found for {name1}.[/red]")
        return

    # Fetch Instrument 2 if exists
    df2 = fetch_candles(db, id2, date_str) if id2 else pl.DataFrame()

    # 3. Calculate Crossovers for Instrument 1
    console.print(f"[blue]Calculating {args.crossover} crossovers for {name1} on {args.timeframe}s timeframe...[/blue]")
    cross_df, full_df1 = calculate_crossovers(df1, fast_period, slow_period, args.timeframe)

    if cross_df.is_empty():
        console.print(f"[yellow]No crossovers found for {name1} on {date_str}.[/yellow]")
        return

    # 4. Process NIFTY and Instrument 2 at crossover times
    def get_full_resampled(df, fast, slow, tf):
        if df.is_empty(): return pl.DataFrame()
        df = df.sort("time_ist")
        res = (
            df.group_by_dynamic("time_ist", every=f"{tf}s")
            .agg([
                pl.col("c").last().alias("close")
            ])
        )
        res = res.with_columns([
            res["close"].ewm_mean(span=fast, adjust=False).alias("ema_fast"),
            res["close"].ewm_mean(span=slow, adjust=False).alias("ema_slow")
        ])
        return res

    full_nifty = get_full_resampled(nifty_df, fast_period, slow_period, args.timeframe)
    full_df2 = get_full_resampled(df2, fast_period, slow_period, args.timeframe) if not df2.is_empty() else pl.DataFrame()

    # 5. Output Table
    table = Table(title=f"Crossovers for {name1} on {date_str} ({args.crossover}, {args.timeframe}s)")
    table.add_column("Time (IST)", style="cyan")
    table.add_column("Type", style="bold")
    table.add_column(f"Price ({name1})", justify="right")
    table.add_column(f"EMA {fast_period}-{slow_period} ({name1})", justify="right")
    table.add_column(f"EMA {fast_period}-{slow_period} (NIFTY)", justify="right")
    
    if id2:
        table.add_column(f"EMA {fast_period}-{slow_period} ({name2})", justify="right")

    for row in cross_df.iter_rows(named=True):
        t_ist = row["time_ist"].strftime("%Y-%m-%d %H:%M:%S")
        ctype = "BULLISH" if row["is_bullish"] else "BEARISH"
        color = "green" if row["is_bullish"] else "red"
        
        def get_ema_indicator_str(fast, slow):
            if fast > slow: return "🟢 "
            if fast < slow: return "🔴 "
            return "🟠 "

        # Primary EMA and indicator
        p_indicator = get_ema_indicator_str(row['ema_fast'], row['ema_slow'])
        p_ema_vals = f"{p_indicator}{row['ema_fast']:.1f} - {row['ema_slow']:.1f}"

        # Get NIFTY values at this time
        n_row = full_nifty.filter(pl.col("time_ist") == row["time_ist"])
        nifty_vals = "N/A"
        if not n_row.is_empty():
            n_data = n_row.to_dicts()[0]
            n_indicator = get_ema_indicator_str(n_data['ema_fast'], n_data['ema_slow'])
            nifty_vals = f"{n_indicator}{n_data['ema_fast']:.1f} - {n_data['ema_slow']:.1f}"

        # Get Inst 2 values at this time
        inst2_vals = "N/A"
        if id2 and not full_df2.is_empty():
            i2_row = full_df2.filter(pl.col("time_ist") == row["time_ist"])
            if not i2_row.is_empty():
                i2_data = i2_row.to_dicts()[0]
                i2_indicator = get_ema_indicator_str(i2_data['ema_fast'], i2_data['ema_slow'])
                inst2_vals = f"{i2_indicator}{i2_data['ema_fast']:.1f} - {i2_data['ema_slow']:.1f}"

        row_data = [
            t_ist,
            f"[{color}]{ctype}[/{color}]",
            f"{row['close']:.2f}",
            p_ema_vals,
            nifty_vals
        ]
        if id2:
            row_data.append(inst2_vals)
            
        table.add_row(*row_data)


    console.print(table)

if __name__ == "__main__":
    main()

