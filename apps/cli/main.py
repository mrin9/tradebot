
import sys
import os
import subprocess
import typer
import questionary
from typing import Optional, Annotated
from datetime import datetime

# Enforce project root in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from packages.data.managers.sync_master import MasterDataCollector
from packages.data.managers.contracts import ContractManager
from packages.data.managers.sync_history import HistoricalDataCollector
from packages.data.managers.age_out import age_out_history as do_age_out_history
from packages.data.managers.fix_data_gaps import check_data_gaps as do_check_data_gaps, fill_data_gaps as do_fill_data_gaps
from packages.tradeflow.fund_manager import FundManager
from packages.livetrade.live_trader import LiveTradeEngine
from packages.utils.mongo import MongoRepository, get_db
from packages.utils.date_utils import DateUtils

from packages.utils.market_utils import MarketUtils
from packages.utils.log_utils import setup_logger
from packages.utils.seed_strategy_rules import seed_strategy_rules
from packages.config import settings

app = typer.Typer(help="Trade Bot V2 Management CLI")
PID_FILE = "simulator_service.pid"

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
def update_master():
    """Sync the internal instrument database with XTS."""
    typer.echo("Syncing Master Instruments...")
    try:
        MasterDataCollector().update_master_db()
        typer.secho("✅ Master Database Updated.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def sync_history(
    date_range: Annotated[str, typer.Option(help="Date range (e.g., 2dago|now or YYYY-MM-DD|YYYY-MM-DD)")] = "2dago|now"
):
    """Perform a bulk sync of historical OHLC data for NIFTY and all active options."""
    dr = date_range
    try:
        s_dt, e_dt = DateUtils.parse_date_range(dr)
        typer.echo(f"Syncing NIFTY and Options history from {s_dt} to {e_dt}...")
        HistoricalDataCollector().sync_nifty_and_options_history(s_dt, e_dt)
        typer.secho("✅ Sync Complete.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def age_out(
    days: Annotated[int, typer.Option(help="Delete tick data older than X days")] = 60
):
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
def check_gaps(
    date_range: Annotated[str, typer.Option(help="Date Range for Gap Check")] = "5dago|now"
):
    """Identify missing periods in NIFTY/Options history compared to the expected data."""
    dr = date_range
    try:
        start_str = dr
        end_str = dr
        if "|" in dr:
            start_str, end_str = dr.split("|")
        do_check_data_gaps(start_str, end_str)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def fill_gaps(
    date_range: Annotated[str, typer.Option(help="Date Range to fill gaps")] = "today"
):
    """Automatically fetch and repair missing data identifying in the gap check."""
    dr = date_range
    try:
        do_fill_data_gaps(dr)
        typer.secho("✅ Gap filling process finished.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def simulator(
    action: Annotated[str, typer.Argument(help="Action: start, stop, status")]
):
    """Manage the background Socket.IO simulator (Start/Stop/Status)."""
    if action == "start":
        if os.path.exists(PID_FILE):
            typer.secho("Already running.", fg=typer.colors.YELLOW)
            return
        cmd = [sys.executable, "-m", "packages.simulator.socket_server"]
        try:
            # Create logs dir if not exists
            if not os.path.exists("logs"): os.makedirs("logs")
            proc = subprocess.Popen(cmd, stdout=open("logs/simulator_stdout.log", "a"), stderr=open("logs/simulator_stderr.log", "a"))
            with open(PID_FILE, "w") as f: f.write(str(proc.pid))
            typer.secho(f"✅ Started. PID: {proc.pid}", fg=typer.colors.GREEN)
        except Exception as e: typer.secho(f"❌ Failed: {e}", fg=typer.colors.RED)
        
    elif action == "stop":
        if not os.path.exists(PID_FILE):
            typer.secho("Not running.", fg=typer.colors.RED)
            return
        with open(PID_FILE, "r") as f: pid = int(f.read().strip())
        try:
            import signal
            os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
            typer.secho(f"✅ Stopped process {pid}.", fg=typer.colors.GREEN)
        except Exception as e:
            typer.secho(f"⚠️ Error: {e}. Removing stale PID file.", fg=typer.colors.YELLOW)
            if os.path.exists(PID_FILE): os.remove(PID_FILE)
            
    elif action == "status":
        if not os.path.exists(PID_FILE):
             typer.secho("Service is NOT running.", fg=typer.colors.RED)
        else:
             with open(PID_FILE, "r") as f: pid = int(f.read().strip())
             try:
                 os.kill(pid, 0)
                 typer.secho(f"✅ Running (PID: {pid}).", fg=typer.colors.GREEN)
             except ProcessLookupError:
                 typer.secho("⚠️ Stale PID file found.", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"❌ Unknown action: {action}", fg=typer.colors.RED)

@app.command()
def crossover(
    instrument: Annotated[str, typer.Option(help="Instrument description (e.g., NIFTY2630225400CE)")] = "",
    date: Annotated[Optional[str], typer.Option(help="ISO Date (YYYY-MM-DD)")] = None,
    crossover_type: Annotated[str, typer.Option("--crossover", help="Crossover (e.g., EMA-5-21)")] = "EMA-5-21",
    timeframe: Annotated[int, typer.Option(help="Timeframe in seconds")] = 180
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
    rule_id: Annotated[Optional[str], typer.Option(help="Strategy Rule ID")] = None,
    start: Annotated[Optional[str], typer.Option(help="Start Date (YYYY-MM-DD)")] = None,
    end: Annotated[Optional[str], typer.Option(help="End Date (YYYY-MM-DD)")] = None,
    mode: Annotated[Optional[str], typer.Option(help="Backtest mode: db or socket")] = None,
    budget: Annotated[Optional[float], typer.Option(help="Initial Capital")] = None,
    invest_mode: Annotated[Optional[str], typer.Option(help="ReInvest Type: fixed or compound")] = None,
    sl: Annotated[Optional[float], typer.Option(help="Stop Loss at")] = None,
    no_break_even: Annotated[Optional[bool], typer.Option(help="Disable Break-Even trailing")] = None,
    trailing_sl: Annotated[Optional[float], typer.Option(help="Trailing Stop Loss Points")] = None,
    option_type: Annotated[Optional[str], typer.Option(help="Option Strike Type (ATM, ITM, OTM)")] = None,
    strategy_mode: Annotated[Optional[str], typer.Option(help="Strategy Mode: rule, ml, or python_code")] = None,
    python_strategy_path: Annotated[Optional[str], typer.Option(help="Path to custom python strategy file")] = None,
    ml_model_path: Annotated[Optional[str], typer.Option(help="Path to ML model")] = None,
    pyramid_steps: Annotated[Optional[str], typer.Option(help="Pyramid entry percentages (e.g., 25,50,25 or 100)")] = None,
    pyramid_confirm_pts: Annotated[Optional[float], typer.Option(help="Pyramid confirmation points")] = None,
    target_steps: Annotated[Optional[str], typer.Option(help="Target steps (comma separated, e.g. 15,25,50)")] = None,
    warmup_candles: Annotated[Optional[int], typer.Option(help="Warmup candles for indicators")] = None
):
    """Execute a strategy against historical data (Interactive)."""
    db = get_db()
    
    # 1. Mode
    if not mode:
        mode = questionary.select("Select Backtest Mode:", choices=["db", "socket"]).ask()
    if not mode: return

    # 2. Dates
    if not start or not end:
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        latest_10 = sorted(available_days, reverse=True)[:10]
        
        date_choices = [questionary.Choice(title=d, value=d) for d in latest_10]
        date_choices.append(questionary.Choice(title="Manual Entry", value="MANUAL"))
        
        if not start:
            start = questionary.select("Select Start Date:", choices=date_choices).ask()
            if start == "MANUAL":
                start = questionary.text("Enter Start Date (YYYY-MM-DD):", default=latest_10[0] if latest_10 else "").ask()
        
        if not end:
            end = questionary.select("Select End Date:", choices=date_choices).ask()
            if end == "MANUAL":
                end = questionary.text("Enter End Date (YYYY-MM-DD):", default=start).ask()

    if not start or not end: return

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
    if not invest_mode: return

    # 6. Enable Trailing Stop Loss
    trailing_choice = None
    if trailing_sl is None:
        trailing_choice = questionary.select("Enable Trailing Stop Loss?", choices=["Yes", "No"]).ask()
    
    # 7. Stop Loss
    if sl is None:
        sl_str = questionary.text("Stop Loss Points:", default="15").ask()
        sl = float(sl_str) if sl_str else 15.0

    # 8. Trailing SL Points (Conditional)
    if trailing_sl is None:
        if trailing_choice == "Yes":
            tsl_str = questionary.text("Trailing SL Points:", default="10").ask()
            trailing_sl = float(tsl_str) if tsl_str else 10.0
        else:
            trailing_sl = 0.0

    # 8. Targets
    if not target_steps:
        target_steps = questionary.text("Targets:", default="15,25,50").ask()
    if not target_steps: target_steps = "15,25,50"

    # 9. Break Even
    if no_break_even is None:
        be_choice = questionary.select("Enable Break Even at First Target?", choices=["Yes", "No"]).ask()
        no_break_even = (be_choice == "No")

    # 10. Option Type
    if not option_type:
        option_type = questionary.select("Option Strike Type:", choices=["ATM", "ITM", "OTM"]).ask()
    if not option_type: return

    # 11. Strategy Mode
    if not strategy_mode:
        strategy_mode = questionary.select("Strategy Mode:", choices=["rule", "ml", "python_code"]).ask()
    if not strategy_mode: return

    # 11a. ML / Python Model Path
    if strategy_mode == "ml" and not ml_model_path:
        ml_model_path = questionary.text("Path to ML Model (.joblib):", default="models/model.joblib").ask()
    elif strategy_mode == "python_code" and not python_strategy_path:
        python_strategy_path = questionary.text("Path to Python Strategy (e.g. packages/tradeflow/python_strategies.py:Strategy):", default="packages/tradeflow/python_strategies.py:TripleLockStrategy").ask()

    # 12. rule-id
    if not rule_id:
        rules = list(db['strategy_rules'].find({}, {"ruleId": 1, "name": 1}))
        if not rules:
            typer.secho("❌ No strategy rules found in database. Seed them first.", fg=typer.colors.RED)
            return
        
        choices = [
            questionary.Choice(
                title=f"{r.get('name', 'Unnamed')} ({r['ruleId']})",
                value=r['ruleId']
            ) for r in rules
        ]
        
        if strategy_mode in ["ml", "python_code"]:
            choices.insert(0, questionary.Choice(title="Skip (Use Default Generated Feature Stub)", value="SKIP"))
            
        choices.append(questionary.Choice(title="Back", value="BACK"))
        rule_id = questionary.select(f"Select Strategy Rule (Optional for {strategy_mode}):", choices=choices).ask()
    
    if not rule_id or rule_id == "BACK": return
    if rule_id == "SKIP": rule_id = ""

    # 13. Default Warmup
    if warmup_candles is None:
        warmup_candles = 200

    # Construct and run the command
    cmd = [
        sys.executable, "-m", "tests.backtest.backtest_runner",
        "--mode", mode,
        "--rule-id", rule_id,
        "--start", start,
        "--end", end,
        "--budget", str(budget),
        "--invest-mode", invest_mode,
        "--sl", str(sl),
        "--target-steps", target_steps,
        "--trailing-sl", str(trailing_sl),
        "--option-type", option_type,
        "--strategy-mode", strategy_mode,
        "--pyramid-steps", pyramid_steps,
    ]
    if ml_model_path:
        cmd.extend(["--ml-model-path", ml_model_path])
    if python_strategy_path:
        cmd.extend(["--python-strategy-path", python_strategy_path])
    cmd.extend([
        "--pyramid-confirm-pts", str(pyramid_confirm_pts),
        "--warmup-candles", str(warmup_candles)
    ])
    if no_break_even:
        cmd.append("--no-break-even")

    typer.secho(f"\n🧪 Starting {mode.upper()} Backtest for {rule_id}...", fg=typer.colors.BLUE, bold=True)
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
            "Tests:",
            choices=["Unit Tests", "Integration Tests", "Connectivity", "Back"]
        ).ask()
        
        if category == "Back": break
        
        if category == "Unit Tests":
            test = questionary.select(
                "Select Unit Test:",
                choices=[
                    "Collectors", "Fund Manager", "Position Manager", 
                    "Indicator Calculator", "Strategy Logic", "ML Strategy", "Candle Resampler", "Back"
                ]
            ).ask()
            if test == "Back": continue
            
            mapping = {
                "Collectors": "tests/test_collectors.py",
                "Fund Manager": "tests/test_fund_manager.py",
                "Position Manager": "tests/test_position_manager.py",
                "Indicator Calculator": "tests/test_indicator_calculator.py",
                "Strategy Logic": "tests/test_strategy.py",
                "ML Strategy": "tests/test_ml_strategy.py",
                "Candle Resampler": "tests/test_candle_resampler.py"
            }
            run_pytest(mapping[test])
            
        elif category == "Integration Tests":
            test = questionary.select(
                "Select Integration Test:",
                choices=["Full Strategy Flow", "Market Utils", "Back"]
            ).ask()
            if test == "Back": continue
            
            mapping = {
                "Full Strategy Flow": "tests/test_strategy_integration.py",
                "Market Utils": "tests/test_market_utils_parsing.py"
            }
            run_pytest(mapping[test])
            
        elif category == "Connectivity":
            test = questionary.select(
                "Select Connectivity Test:",
                choices=["XTS API Connection", "Market Stream Test", "Back"]
            ).ask()
            if test == "Back": continue
            
            mapping = {
                "XTS API Connection": "tests/test_xts_connection.py",
                "Market Stream Test": "tests/test_stream.py"
            }
            run_pytest(mapping[test])

def configuration_menu():
    action = questionary.select(
        "Configuration:",
        choices=["Show Settings", "Environment Check", "Back"]
    ).ask()
    
    if action == "Back": return
    
    if action == "Show Settings":
        typer.secho("\n--- Active Settings ---", bold=True)
        typer.echo(f"DB_NAME: {settings.MONGO_DB_NAME}")
        typer.echo(f"XTS_API_BASE: {settings.XTS_INTERACTIVE_URL}")
        typer.echo(f"INDICES_SET: {settings.INDICES_SET}")
        typer.echo(f"LOG_LEVEL: {settings.LOG_LEVEL}")
        input("\nPress Enter to continue...")
        
    elif action == "Environment Check":
        typer.echo("Checking environment...")
        missing = []
        if not os.path.exists(".env"): missing.append(".env")
        if not os.path.exists("logs"): os.makedirs("logs")
        
        if missing:
             typer.secho(f"❌ Missing: {', '.join(missing)}", fg=typer.colors.RED)
        else:
             typer.secho("✅ Basic environment looks OK.", fg=typer.colors.GREEN)
        input("\nPress Enter to continue...")

@app.command()
def refresh_contracts(
    date_range: Annotated[str, typer.Option(help="Date Range (today, yesterday, or YYYY-MM-DD)")] = "today"
):
    """Determine which ATM/ITM/OTM contracts should be tracked for the current session."""
    dr = date_range
    try:
        typer.echo(f"Refreshing active contracts for {dr}...")
        ContractManager().refresh_active_contracts(dr)
        typer.secho("✅ Active contracts updated.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command()
def seed_rules():
    """Seed the database with predefined strategy rules."""
    try:
        typer.echo("Seeding strategy rules...")
        seed_strategy_rules()
        typer.secho("✅ Seed complete.", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"❌ Error: {e}", fg=typer.colors.RED)

@app.command(name="train-model")
def train_model(
    start: Annotated[Optional[str], typer.Option(help="Start Date (YYYY-MM-DD)")] = None,
    end: Annotated[Optional[str], typer.Option(help="End Date (YYYY-MM-DD)")] = None,
    forward_bars: Annotated[int, typer.Option(help="Bars ahead for labeling")] = 6,
    threshold: Annotated[float, typer.Option(help="% move threshold for labels")] = 0.15,
    folds: Annotated[int, typer.Option(help="Walk-Forward folds")] = 3,
    output_dir: Annotated[str, typer.Option(help="Model output directory")] = "models",
    model_name: Annotated[str, typer.Option(help="Output filename (without .joblib). Auto-generated if empty.")] = "",
    no_balance: Annotated[bool, typer.Option("--no-balance", help="Disable class balancing")] = False,
    trees: Annotated[int, typer.Option(help="XGBoost n_estimators")] = 300,
    depth: Annotated[int, typer.Option(help="XGBoost max_depth")] = 4,
    lr: Annotated[float, typer.Option(help="XGBoost learning_rate")] = 0.05,
    min_child: Annotated[int, typer.Option(help="Min samples per leaf")] = 5,
    features: Annotated[str, typer.Option(help="Feature groups: base,indicators,candles")] = "base,indicators,candles",
    model_type: Annotated[str, typer.Option(help="Model algorithm: xgboost, random_forest")] = "xgboost",
):
    """Train an XGBoost ML model on historical NIFTY data."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")

    db = get_db()

    if not start or not end:
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        latest_10 = sorted(available_days, reverse=True)[:10]
        oldest = sorted(available_days)[:1]

        if not start:
            default_start = oldest[0] if oldest else ""
            start = questionary.text("Training Start Date (YYYY-MM-DD):", default=default_start).ask()
        if not end:
            default_end = latest_10[0] if latest_10 else ""
            end = questionary.text("Training End Date (YYYY-MM-DD):", default=default_end).ask()

    if not start or not end:
        typer.secho("❌ Start and End dates required.", fg=typer.colors.RED)
        return

    typer.secho(f"\n🧠 Training ML Model: {start} → {end}", fg=typer.colors.BLUE, bold=True)
    typer.secho(f"   Threshold: {threshold}% | Forward: {forward_bars} bars | Folds: {folds}", fg=typer.colors.CYAN)
    typer.secho(f"   XGB: trees={trees}, depth={depth}, lr={lr}, min_child={min_child}", fg=typer.colors.CYAN)
    typer.secho(f"   Model Type: {model_type}", fg=typer.colors.CYAN)
    typer.secho(f"   Class Balance: {'OFF' if no_balance else 'ON'}", fg=typer.colors.CYAN)
    typer.secho(f"   Features: {features}", fg=typer.colors.CYAN)

    feature_list = [s.strip() for s in features.split(',')]

    try:
        from packages.ml.train import train
        model_path = train(
            start_date=start,
            end_date=end,
            model_output_dir=output_dir,
            model_name=model_name,
            forward_bars=forward_bars,
            threshold_pct=threshold,
            n_folds=folds,
            class_balance=not no_balance,
            n_estimators=trees,
            max_depth=depth,
            learning_rate=lr,
            min_child_weight=min_child,
            feature_sets=feature_list,
            model_type=model_type,
        )
        if model_path:
            typer.secho(f"\n🎉 Model saved to: {model_path}", fg=typer.colors.GREEN, bold=True)
        else:
            typer.secho("\n❌ Training failed — insufficient data.", fg=typer.colors.RED)
    except Exception as e:
        typer.secho(f"\n❌ Training failed: {e}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()

@app.command()
def live_trade(
    rule_id: Annotated[str, typer.Option(help="Strategy Rule ID (e.g. R001)")] = "R001",
    selection_basis: Annotated[str, typer.Option(help="Option Selection Basis (ATM, ITM, OTM)")] = "ATM",
    subscribe_to: Annotated[str, typer.Option(help="Broadcast Mode (Full, Partial)")] = "Full",
    break_even: Annotated[bool, typer.Option(help="Enable Break-even Trailing")] = True,
    debug: Annotated[bool, typer.Option(help="Enable Socket Debug Logging")] = False,
    strategy_mode: Annotated[str, typer.Option(help="Strategy Mode: rule, ml, or python_code")] = "rule",
    python_strategy_path: Annotated[Optional[str], typer.Option(help="Path to custom python strategy file")] = None,
    ml_model_path: Annotated[Optional[str], typer.Option(help="Path to ML model")] = None
):
    """Starts the Live Trading Engine."""
    try:
        db = MongoRepository.get_db()
        rule = db["strategy_rules"].find_one({"$or": [{"ruleId": rule_id}, {"name": rule_id}]})
        if not rule:
            typer.secho(f"❌ Strategy rule {rule_id} not found!", fg=typer.colors.RED)
            return

        pos_cfg = {
            "budget": budget,
            "stop_loss_points": sl,
            "target_points": target,
            "trailing_sl_points": trailing_sl,
            "option_type": selection_basis.upper(),
            "instrument_type": "OPTIONS", # Default for live trading in this context
            "use_break_even": break_even,
            "symbol": "NIFTY",
            "strategy_mode": strategy_mode,
            "python_strategy_path": python_strategy_path,
            "ml_model_path": ml_model_path
        }

        engine = LiveTradeEngine(
            strategy_config=rule,
            position_config=pos_cfg,
            subscribe_to=subscribe_to.capitalize(),
            debug=debug
        )
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
                "Simulator Control",
                "Backtesting",
                "Live Trading",
                "Tests",
                "Configuration",
                "Refresh Active Contracts",
                "Seed Strategy Rules",
                "Train ML Model",
                "EMA Crossover Analysis",
                "Exit"
            ]
        ).ask()
        
        if choice == "Exit": break
        elif choice == "Update Master Instruments": update_master()
        elif choice == "Sync History (Nifty and Options)":
             dr = questionary.text("Enter Date Range (e.g., 2dago|now):", default="2dago|now").ask()
             if dr: sync_history(date_range=dr)
        elif choice == "Age Out History":
             days = questionary.text("Delete tick data older than X days:", default="60").ask()
             if days: age_out(days=int(days))
        elif choice == "Check Data Gaps":
             dr = questionary.text("Date Range for Gap Check:", default="5dago|now").ask()
             if dr: check_gaps(date_range=dr)
        elif choice == "Fill Data Gaps":
             dr = questionary.text("Date Range to fill gaps:", default="today").ask()
             if dr: fill_gaps(date_range=dr)
        elif choice == "Simulator Control":
             action = questionary.select("Simulator Action:", choices=["start", "stop", "status", "back"]).ask()
             if action != "back": simulator(action=action)
        elif choice == "Backtesting":
             backtest()
        elif choice == "Live Trading":
             db = MongoRepository.get_db()
             rules = list(db["strategy_rules"].find({}, {"ruleId": 1, "name": 1}))
             if not rules:
                 typer.secho("❌ No strategy rules found!", fg=typer.colors.RED)
                 continue
                 
             rule_choices = [
                 questionary.Choice(title=f"{r.get('name')} ({r['ruleId']})", value=r['ruleId'])
                 for r in rules
             ]
             rid = questionary.select("Select Strategy Rule:", choices=rule_choices).ask()
             
             if rid:
                 strategy_mode = questionary.select("Strategy Mode:", choices=["rule", "ml"]).ask()
                 ml_path = None
                 if strategy_mode == "ml":
                     ml_path = questionary.text("ML Model Path:", default="models/model.joblib").ask()

                 budget = float(questionary.text("Budget:", default="200000").ask())
                 sl = float(questionary.text("Stop Loss Points:", default="20").ask())
                 target = questionary.text("Target Points:", default="5,10,15").ask()
                 mode = questionary.select("Subscribe To:", choices=["Full", "Partial"]).ask()
                 live_trade(
                     rule_id=rid, budget=budget, sl=sl, target=target, 
                     subscribe_to=mode, strategy_mode=strategy_mode, 
                     ml_model_path=ml_path
                 )
        elif choice == "Tests": tests_menu()
        elif choice == "Configuration": configuration_menu()
        elif choice == "Refresh Active Contracts":
             dr = questionary.text("Date Range (today, yesterday, or YYYY-MM-DD):", default="today").ask()
             if dr: refresh_contracts(date_range=dr)
        elif choice == "Seed Strategy Rules":
             seed_rules()
        elif choice == "Train ML Model":
              train_model()
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

if __name__ == "__main__":
    app()
