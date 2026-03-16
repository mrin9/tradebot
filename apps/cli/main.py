import os
import subprocess
import sys
from typing import Annotated

import questionary
import typer

# Enforce project root in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from packages.data.age_out import age_out_history as do_age_out_history
from packages.data.contracts import ContractManager
from packages.data.data_gaps import check_data_gaps as do_check_data_gaps
from packages.data.data_gaps import fill_data_gaps as do_fill_data_gaps
from packages.data.sync_history import HistoricalDataCollector
from packages.data.sync_master import MasterDataCollector
from packages.db.seed_strategy_indicators import seed_strategy_indicators
from packages.livetrade.live_trader import LiveTradeEngine
from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository, get_db

app = typer.Typer(help="Trade Bot V2 Management CLI")

# --- Helper Functions ---


def run_pytest(test_path: str):
    """Runs a pytest file and handles output."""
    cmd = [sys.executable, "-m", "pytest", test_path, "-v"]
    typer.secho(f"\nRunning Test: {test_path}...", fg=typer.colors.BLUE, bold=True)
    try:
        subprocess.run(cmd, check=True)
        typer.secho("\n✅ Test Passed!", fg=typer.colors.GREEN, bold=True)
    except subprocess.CalledProcessError:
        typer.secho("\n❌ Test Failed!", fg=typer.colors.RED, bold=True)
    except Exception as e:
        typer.secho(f"\n⚠️ Error running test: {e}", fg=typer.colors.RED)

    typer.echo("\nPress Enter to return to menu...")
    input()


@app.command()
def ensure_indexes():
    """Verify and create all necessary MongoDB indexes for performance."""
    try:
        from packages.db.db_init import DatabaseManager

        DatabaseManager.ensure_all_indexes()
        typer.secho("✅ Index synchronization complete.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def update_master():
    """Sync the internal instrument database with XTS."""
    typer.echo("Syncing Master Instruments...")
    try:
        collector = MasterDataCollector()
        collector.update_master_db()
        typer.secho("✅ Master Database Updated.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def sync_history(
    date_range: Annotated[
        str, typer.Option(help="Date range (e.g., 2dago|now or YYYY-MM-DD|YYYY-MM-DD)")
    ] = "2dago|now",
):
    """Perform a bulk sync of historical OHLC data for NIFTY and all active options."""
    dr = date_range
    try:
        s_dt, e_dt = DateUtils.parse_date_range(dr)
        typer.echo(f"Syncing NIFTY and Options history from {s_dt} to {e_dt}...")
        collector = HistoricalDataCollector()
        collector.sync_nifty_and_options_history(s_dt, e_dt)
        typer.secho("✅ Sync Complete.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def age_out(days: Annotated[int, typer.Option(help="Delete tick data older than X days")] = 60):
    """Prune old historical tick data to maintain database performance."""
    try:
        d = int(days)
        if typer.confirm(f"Are you sure you want to delete data older than {d} days?"):
            do_age_out_history(d)
            typer.secho(f"✅ Data older than {d} days pruned.", fg=typer.colors.GREEN)
    except ValueError:
        typer.secho("❌ Invalid number.", fg=typer.colors.RED)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def check_gaps(date_range: Annotated[str, typer.Option(help="Date Range for Gap Check")] = "2dago|now"):
    """Identify missing periods in NIFTY/Options history compared to the expected data."""
    dr = date_range
    try:
        s_dt, e_dt = DateUtils.parse_date_range(dr)
        from packages.utils.date_utils import FMT_ISO_DATE

        do_check_data_gaps(s_dt.strftime(FMT_ISO_DATE), e_dt.strftime(FMT_ISO_DATE))
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def fill_gaps(date_range: Annotated[str, typer.Option(help="Date Range to fill gaps")] = "today"):
    """Automatically fetch and repair missing data identifying in the gap check."""
    dr = date_range
    try:
        do_fill_data_gaps(dr)
        typer.secho("✅ Gap filling process finished.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def crossover(
    instrument: Annotated[str, typer.Option(help="Instrument description (e.g., NIFTY2630225400CE)")] = "",
    date: Annotated[str | None, typer.Option(help="ISO Date (YYYY-MM-DD)")] = None,
    crossover_type: Annotated[str, typer.Option("--crossover", help="Crossover (e.g., EMA-5-21)")] = "EMA-5-21",
    timeframe: Annotated[int, typer.Option(help="Timeframe in seconds")] = 180,
):
    """Calculate EMA crossovers and compare with counterpart (CE/PE)."""
    cmd = [sys.executable, "scripts/crossover_calculator.py"]
    if instrument:
        cmd.extend(["--instrument", instrument])
    if date:
        cmd.extend(["--date", date])
    cmd.extend(["--crossover", crossover_type])
    cmd.extend(["--timeframe", str(timeframe)])

    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        typer.secho(f"❌ Crossover calculation failed: {e}", fg=typer.colors.RED)


@app.command()
def backtest(
    strategy_id: Annotated[
        str, typer.Option("--strategy-id", "-s", help="Strategy Indicator ID")
    ] = "triple-confirmation",
    start: Annotated[str | None, typer.Option(help="Start Date (YYYY-MM-DD)")] = None,
    end: Annotated[str | None, typer.Option(help="End Date (YYYY-MM-DD). Defaults to --start if omitted.")] = None,
    mode: Annotated[str | None, typer.Option(help="Backtest mode: db or socket")] = None,
    budget: Annotated[float | None, typer.Option("--budget", "-b", help="Initial Capital")] = None,
    invest_mode: Annotated[
        str | None, typer.Option("--invest-mode", "-i", help="ReInvest Type: fixed or compound")
    ] = None,
    sl_points: Annotated[float | None, typer.Option("--sl-points", "-l", help="Stop Loss Points")] = None,
    use_be: Annotated[bool | None, typer.Option("--use-be", "-e", help="Enable Break-Even trailing")] = None,
    tsl_points: Annotated[float | None, typer.Option("--tsl-points", "-L", help="Trailing Stop Loss Points")] = 0.0,
    strike_selection: Annotated[
        str | None, typer.Option("--strike-selection", "-S", help="Option Strike Type (ATM, ITM, OTM)")
    ] = None,
    pyramid_steps: Annotated[
        str | None, typer.Option(help="Pyramid entry percentages (e.g., 25,50,25 or 100)")
    ] = None,
    pyramid_confirm_pts: Annotated[float | None, typer.Option(help="Pyramid confirmation points")] = None,
    target_points: Annotated[
        str | None, typer.Option("--target-points", "-t", help="Target steps (comma separated, e.g. 15,25,50)")
    ] = None,
):
    """Execute a strategy against historical data (Interactive)."""
    db = get_db()

    # Initialize variables to avoid UnboundLocalError
    python_strategy_path = None
    tsl_id = None

    # 1. Strategy ID (Primary selection first)
    if not strategy_id or strategy_id == "SKIP":
        strat_coll = settings.STRATEGY_INDICATORS_COLLECTION
        strategies = list(db[strat_coll].find({"enabled": True}, {"strategyId": 1, "name": 1}))
        choices = [
            questionary.Choice(title=f"{s.get('name', 'Unnamed')} ({s['strategyId']})", value=s["strategyId"])
            for s in strategies
        ]
        choices.append(questionary.Choice(title="Back", value="BACK"))

        strategy_id = questionary.select(
            "Select Strategy for indicators:",
            choices=choices,
            default="triple-confirmation"
            if any(s["strategyId"] == "triple-confirmation" for s in strategies)
            else None,
        ).ask()

    if not strategy_id or strategy_id == "BACK":
        return

    # Fetch configuration
    try:
        from packages.services.trade_config_service import TradeConfigService

        strat_doc = TradeConfigService.fetch_strategy_config(strategy_id)
        python_strategy_path = strat_doc.get("python_strategy_path")
        tsl_id = strat_doc.get("tslIndicatorId") or "active-ema-5"
    except Exception as e:
        typer.secho(f"❌ Error fetching strategy: {e}", fg=typer.colors.RED)
        return

    # 2. Mode
    if not mode:
        mode = questionary.select("Select Backtest Mode:", choices=["db", "socket"]).ask()
    if not mode:
        return

    # 2. Dates
    if not start or not end:
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        latest_10 = sorted(available_days, reverse=True)[:10]

        date_choices = [questionary.Choice(title=d, value=d) for d in latest_10]
        date_choices.append(questionary.Choice(title="Manual Entry", value="MANUAL"))

        if not start:
            start = questionary.select("Select Start Date:", choices=date_choices).ask()
            if start == "MANUAL":
                start = questionary.text(
                    "Enter Start Date (YYYY-MM-DD):", default=latest_10[0] if latest_10 else ""
                ).ask()

        if not end:
            end = questionary.select("Select End Date:", choices=date_choices).ask()
            if end == "MANUAL":
                end = questionary.text("Enter End Date (YYYY-MM-DD):", default=start).ask()

    if not start or not end:
        return

    # 3. Budget
    if budget is None:
        budget_str = questionary.text("Enter Initial Budget:", default="200000").ask()
        budget = float(budget_str) if budget_str else 200000.0

    # 4. Pyramiding
    if not pyramid_steps:
        enable_pyramid = questionary.select("Enable Pyramiding?", choices=["No", "Yes"]).ask()
        if enable_pyramid == "Yes":
            pyramid_steps = questionary.text("Pyramid Steps (% per step, comma separated):", default="25,50,25").ask()
            if not pyramid_confirm_pts:
                pts_str = questionary.text("Pyramid Confirm Points:", default="10").ask()
                pyramid_confirm_pts = float(pts_str) if pts_str else 10.0
        else:
            pyramid_steps = "100"
    if not pyramid_confirm_pts:
        pyramid_confirm_pts = 10.0

    # 5. ReInvest Type
    if not invest_mode:
        invest_mode = questionary.select("ReInvest Type:", choices=["fixed", "compound"]).ask()
    if not invest_mode:
        return

    # 7. Stop Loss & Trailing SL
    if sl_points is None:
        sl_str = questionary.text("SL Points:", default="15").ask()
        sl_points = float(sl_str) if sl_str else 15.0

    if tsl_points is None:
        tsl_choice = questionary.select("Enable Trailing Stop Loss?", choices=["No", "Yes"]).ask()
        if tsl_choice == "Yes":
            tsl_type = questionary.select("TSL Type:", choices=["Indicator", "Fixed Points"]).ask()
            if tsl_type == "Indicator":
                tsl_id = questionary.text("TSL Indicator ID:", default=tsl_id or "active-ema-5").ask()
                tsl_points = 1.0  # Minimal value to signal TSL is active if points aren't used
            else:
                pts_str = questionary.text("TSL Points:", default="15").ask()
                tsl_points = float(pts_str) if pts_str else 15.0
                tsl_id = None
        else:
            tsl_points = 0.0
            tsl_id = None

    # 9. Targets
    if not target_points:
        target_points = questionary.text("Targets:", default="15,25,50").ask()
    if not target_points:
        target_points = "15,25,50"

    # 10. Break Even
    if use_be is None:
        be_choice = questionary.select("Enable Break Even at First Target?", choices=["Yes", "No"]).ask()
        use_be = be_choice == "Yes"

    # 11. Option Type
    if not strike_selection:
        strike_selection = questionary.select("Option Strike Type:", choices=["ATM", "ITM", "OTM"]).ask()
    if not strike_selection:
        return

    # 11. Python strategy path
    if not python_strategy_path:
        python_strategy_path = questionary.text(
            "Path to Python Strategy (file:ClassName):",
            default="packages/tradeflow/python_strategies.py:TripleLockStrategy",
        ).ask()

    # Construct and run the command
    cmd = [
        sys.executable,
        "-m",
        "tests.backtest.backtest_runner",
        "--mode",
        mode,
        "--start",
        start,
        "--end",
        end,
        "--budget",
        str(budget),
        "--invest-mode",
        invest_mode,
        "--sl-points",
        str(sl_points),
        "--target-points",
        f'"{target_points}"',
        "--tsl-points",
        str(tsl_points),
        "--strike-selection",
        strike_selection,
        "--strategy-id",
        strategy_id,
        "--pyramid_steps",
        pyramid_steps,
        "--pyramid-confirm-pts",
        str(pyramid_confirm_pts),
    ]
    if tsl_id:
        cmd.extend(["--tsl-id", tsl_id])
    if use_be:
        cmd.append("--use-be")

    typer.secho(f"\n🧪 Starting {mode.upper()} Backtest: {python_strategy_path}...", fg=typer.colors.BLUE, bold=True)
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        typer.secho(f"❌ Backtest failed: {e}", fg=typer.colors.RED)

    # Only wait if running in interactive-menu-like mode?
    # Actually, direct commands shouldn't pause.
    # But wait... if called from menu, it should.
    # We'll see.


def tests_menu():
    while True:
        category = questionary.select(
            "Tests:", choices=["Unit Tests", "Integration Tests", "Connectivity", "Back"]
        ).ask()

        if category == "Back":
            break

        if category == "Unit Tests":
            test = questionary.select(
                "Select Unit Test:",
                choices=[
                    "Collectors",
                    "Fund Manager",
                    "Position Manager",
                    "Indicator Calculator",
                    "Strategy Integration",
                    "Candle Resampler",
                    "Back",
                ],
            ).ask()
            if test == "Back":
                continue

            mapping = {
                "Collectors": "tests/readwrite_db/test_collectors.py",
                "Fund Manager": "tests/readwrite_db/test_fund_manager_ticks.py",
                "Position Manager": "tests/no_db/test_position_manager.py",
                "Indicator Calculator": "tests/no_db/test_indicator_calculator.py",
                "Strategy Integration": "tests/frozen_db/test_strategy_integration.py",
                "Candle Resampler": "tests/no_db/test_candle_resampler.py",
            }
            run_pytest(mapping[test])

        elif category == "Integration Tests":
            test = questionary.select(
                "Select Integration Test:", choices=["Full Strategy Flow", "Market Utils", "Back"]
            ).ask()
            if test == "Back":
                continue

            mapping = {
                "Full Strategy Flow": "tests/frozen_db/test_strategy_integration.py",
                "Market Utils": "tests/no_db/test_rolling_strikes.py",
            }
            run_pytest(mapping[test])

        elif category == "Connectivity":
            test = questionary.select(
                "Select Connectivity Test:", choices=["XTS API Connection", "Market Stream Test", "Back"]
            ).ask()
            if test == "Back":
                continue

            mapping = {
                "XTS API Connection": "tests/no_db/test_xts_connection.py",
                "Market Stream Test": "tests/read_db/test_xts_live_stream.py",
            }
            run_pytest(mapping[test])


def configuration_menu():
    action = questionary.select("Configuration:", choices=["Show Settings", "Environment Check", "Back"]).ask()

    if action == "Back":
        return

    if action == "Show Settings":
        typer.secho("\n--- Active Settings ---", bold=True)
        typer.echo(f"DB_NAME: {settings.DB_NAME}")
        typer.echo(f"XTS_API_BASE: {settings.XTS_ROOT_URL}")
        input("\nPress Enter to continue...")

    elif action == "Environment Check":
        typer.echo("Checking environment...")
        missing = []
        if not os.path.exists(".env"):
            missing.append(".env")
        if not os.path.exists("logs"):
            os.makedirs("logs")

        if missing:
            typer.secho(f"❌ Missing: {', '.join(missing)}", fg=typer.colors.RED)
        else:
            typer.secho("✅ Basic environment looks OK.", fg=typer.colors.GREEN)
        input("\nPress Enter to continue...")


@app.command()
def refresh_contracts(
    date_range: Annotated[str, typer.Option(help="Date Range (today, yesterday, or YYYY-MM-DD)")] = "today",
):
    """Determine which ATM/ITM/OTM contracts should be tracked for the current session."""
    dr = date_range
    try:
        typer.echo(f"Refreshing active contracts for {dr}...")
        manager = ContractManager()
        manager.refresh_active_contracts(dr)
        typer.secho("✅ Active contracts updated.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def seed_strategies():
    """Seed the database with predefined strategy indicators."""
    try:
        typer.echo("Seeding strategy indicators...")
        seed_strategy_indicators()
        typer.secho("✅ Seed complete.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)


@app.command()
def live_trade(
    strategy_id: Annotated[
        str, typer.Option("--strategy-id", "-s", help="Strategy ID for indicators and path")
    ] = "triple-confirmation",
    strike_selection: Annotated[
        str, typer.Option("--strike-selection", "-S", help="Option Selection Basis (ATM, ITM, OTM)")
    ] = "ATM",
    budget: Annotated[float, typer.Option("--budget", "-b", help="Initial Budget for Live Trading")] = 200000.0,
    sl_points: Annotated[float, typer.Option("--sl-points", "-l", help="Stop Loss Points")] = 15.0,
    target_points: Annotated[
        str, typer.Option("--target-points", "-t", help="Target Points (Comma separated)")
    ] = "15,25,45",
    tsl_points: Annotated[float, typer.Option("--tsl-points", "-L", help="Trailing Stop Loss Points")] = 0.0,
    use_be: Annotated[bool, typer.Option("--use-be", "-e", help="Enable Break-even Trailing")] = True,
    tsl_id: Annotated[
        str | None, typer.Option("--tsl-id", "-T", help="Indicator ID for Trailing SL (e.g. active-ema-5)")
    ] = "active-ema-5",
    record_papertrade: Annotated[
        bool, typer.Option(help="Record detailed trade logs in 'papertrade' collection")
    ] = True,
    debug: Annotated[bool, typer.Option(help="Enable Socket Debug Logging")] = False,
):
    """Starts the Live Trading Engine."""
    try:
        from packages.services.trade_config_service import TradeConfigService

        rule = TradeConfigService.fetch_strategy_config(strategy_id)
        python_strategy_path = rule.get("python_strategy_path") or rule.get("pythonStrategyPath")

        if not python_strategy_path:
            typer.secho(f"❌ No strategy path found for {strategy_id}.", fg=typer.colors.RED)
            return

        pos_cfg = {
            "budget": budget,
            "sl_points": sl_points,
            "target_points": target_points,
            "tsl_points": tsl_points,
            "strike_selection": strike_selection.upper(),
            "instrument_type": "OPTIONS",
            "use_be": use_be,
            "tsl_id": tsl_id,
            "record_papertrade_db": record_papertrade,
            "symbol": "NIFTY",
            "python_strategy_path": python_strategy_path,
        }

        engine = LiveTradeEngine(strategy_config=rule, position_config=pos_cfg, debug=debug)
        engine.start()

    except Exception as e:
        typer.secho(f"❌ Fatal Error in Live Trade: {e}", fg=typer.colors.RED)
        import traceback

        traceback.print_exc()


@app.command()
def interactive_backtest():
    """Starts the interactive backtest workflow."""
    backtest()


@app.command(name="menu")
def interactive_menu():
    """Starts the trade-bot-v2 interactive management console."""
    while True:
        choice = questionary.select(
            "Quick Select Menu:",
            choices=[
                "Update Master Instruments",
                "Sync History (Nifty and Options)",
                "Age Out History",
                "Check Data Gaps",
                "Fill Data Gaps",
                "Backtesting",
                "Live Trading",
                "Tests",
                "Configuration",
                "Refresh Active Contracts",
                "Seed Strategy Indicators",
                "EMA Crossover Analysis",
                "Ensure DB Indexes",
                "Exit",
            ],
        ).ask()

        if choice == "Exit":
            break
        elif choice == "Update Master Instruments":
            update_master()
        elif choice == "Sync History (Nifty and Options)":
            dr = questionary.text("Enter Date Range (e.g., 2dago|now):", default="2dago|now").ask()
            if dr:
                sync_history(date_range=dr)
        elif choice == "Age Out History":
            days = questionary.text("Delete tick data older than X days:", default="60").ask()
            if days:
                age_out(days=int(days))
        elif choice == "Check Data Gaps":
            dr = questionary.text("Date Range for Gap Check:", default="2dago|now").ask()
            if dr:
                check_gaps(date_range=dr)
        elif choice == "Fill Data Gaps":
            dr = questionary.text("Date Range to fill gaps:", default="today").ask()
            if dr:
                fill_gaps(date_range=dr)
        elif choice == "Backtesting":
            backtest()
        elif choice == "Live Trading":
            db = MongoRepository.get_db()
            strat_coll = settings.STRATEGY_INDICATORS_COLLECTION
            strategies = list(db[strat_coll].find({"enabled": True}, {"strategyId": 1, "name": 1}))
            if not strategies:
                typer.secho("❌ No enabled strategies found!", fg=typer.colors.RED)
                continue

            strat_choices = [
                questionary.Choice(title=f"{s.get('name')} ({s['strategyId']})", value=s["strategyId"])
                for s in strategies
            ]
            sid = questionary.select("Select Strategy:", choices=strat_choices).ask()

            if sid:
                budget = float(questionary.text("Budget:", default="200000").ask())
                sl_points = float(questionary.text("SL Points:", default="20").ask())
                target_points = questionary.text("Target Points:", default="5,10,15").ask()
                live_trade(
                    strategy_id=sid,
                    budget=budget,
                    sl_points=sl_points,
                    target_points=target_points,
                )
        elif choice == "Tests":
            tests_menu()
        elif choice == "Configuration":
            configuration_menu()
        elif choice == "Refresh Active Contracts":
            dr = questionary.text("Date Range (today, yesterday, or YYYY-MM-DD):", default="today").ask()
            if dr:
                refresh_contracts(date_range=dr)
        elif choice == "Seed Strategy Indicators":
            seed_strategies()
        elif choice == "EMA Crossover Analysis":
            inst = questionary.text("Enter instrument (e.g. NIFTY2630225400CE):").ask()
            if inst:
                db = MongoRepository.get_db()
                available_dates = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
                latest = sorted(available_dates, reverse=True)[0] if available_dates else ""

                date = questionary.text("Enter Trading Date (YYYY-MM-DD):", default=latest).ask()
                cross = questionary.text("Enter Crossover (e.g. EMA-5-21):", default="EMA-5-21").ask()
                tf_str = questionary.text("Enter Timeframe (seconds):", default="180").ask()
                tf = int(tf_str) if tf_str else 180

                crossover(instrument=inst, date=date, crossover_type=cross, timeframe=tf)
            input("\nPress Enter to return to menu...")
        elif choice == "Ensure DB Indexes":
            ensure_indexes()


if __name__ == "__main__":
    app()
