"""
Walk-Forward XGBoost Training Script.

Trains a 3-class classifier (LONG / NEUTRAL / SHORT) on features built by FeatureBuilder.
Uses Walk-Forward validation to avoid look-ahead bias.
Supports class balancing via sample weights to combat NEUTRAL dominance.
"""

import os
import sys
import logging
from datetime import datetime

import numpy as np
import joblib
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score

import polars as pl

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.ml.feature_builder import FeatureBuilder, get_feature_columns, ALL_FEATURE_GROUPS

logger = logging.getLogger(__name__)

# Label mapping: internal label → XGBoost class index
# XGBoost needs 0-indexed classes
LABEL_TO_CLASS = {-1: 0, 0: 1, 1: 2}    # SHORT=0, NEUTRAL=1, LONG=2
CLASS_TO_LABEL = {0: -1, 1: 0, 2: 1}
CLASS_NAMES = ["SHORT", "NEUTRAL", "LONG"]


def _compute_sample_weights(y: np.ndarray) -> np.ndarray:
    """
    Compute per-sample weights inversely proportional to class frequency.
    This forces the model to pay equal attention to rare LONG/SHORT signals.
    
    Example: if NEUTRAL is 93%, LONG is 3.5%, SHORT is 3.5%:
      - NEUTRAL weight ≈ 1.0
      - LONG weight ≈ 27.0
      - SHORT weight ≈ 27.0
    """
    classes, counts = np.unique(y, return_counts=True)
    total = len(y)
    n_classes = len(classes)
    
    # balanced weight = total / (n_classes * count_per_class)
    class_weights = {}
    for cls, cnt in zip(classes, counts):
        class_weights[cls] = total / (n_classes * cnt)
    
    sample_weights = np.array([class_weights[yi] for yi in y])
    
    # Log the computed weights
    for cls in sorted(class_weights):
        logger.info(f"  Class {CLASS_NAMES[cls]}: count={dict(zip(classes, counts))[cls]}, "
                    f"weight={class_weights[cls]:.2f}")
    
    return sample_weights


def train(
    start_date: str,
    end_date: str,
    model_output_dir: str = "models",
    model_name: str = "",
    resample_seconds: int = 300,
    forward_bars: int = 6,
    threshold_pct: float = 0.15,
    n_folds: int = 3,
    class_balance: bool = True,
    n_estimators: int = 300,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    min_child_weight: int = 5,
    feature_sets: list = None,
    model_type: str = "xgboost",
) -> str:
    """
    End-to-end training pipeline.

    Args:
        start_date: ISO date, e.g. "2025-08-01".
        end_date:   ISO date, e.g. "2026-02-20".
        model_output_dir: Directory to save the .joblib model.
        resample_seconds: Candle interval in seconds.
        forward_bars: Bars ahead for labeling.
        model_name: Custom filename for the model (without extension). If empty, auto-generates nifty_xgb_YYYYMMDD.
        n_folds: Number of Walk-Forward folds.
        class_balance: If True, apply inverse-frequency sample weighting.
        n_estimators: Number of boosting rounds.
        max_depth: Max tree depth (lower = less overfit).
        learning_rate: Learning rate (XGBoost only).
        min_child_weight: Min samples per leaf (XGBoost min_child_weight / RF min_samples_leaf).
        feature_sets: List of feature groups to use.
        model_type: "xgboost" or "random_forest".
    Returns:
        Path to the saved model file.
    """
    if feature_sets is None:
        feature_sets = ALL_FEATURE_GROUPS
    FEATURE_COLUMNS = get_feature_columns(feature_sets)

    # ── 1. Build Features ───────────────────────────────────────────────
    builder = FeatureBuilder(
        resample_seconds=resample_seconds,
        forward_bars=forward_bars,
        threshold_pct=threshold_pct,
        feature_sets=feature_sets,
    )
    df = builder.build(start_date, end_date)

    if df.is_empty() or len(df) < 100:
        logger.error(f"Insufficient data: {len(df)} rows. Need at least 100.")
        return ""

    # ── 2. Prepare X, y ─────────────────────────────────────────────────
    X = df.select(FEATURE_COLUMNS).to_numpy()
    y_raw = df["label"].to_numpy()

    # Map labels to 0-indexed classes
    y = np.array([LABEL_TO_CLASS[int(v)] for v in y_raw])

    logger.info(f"Dataset: {len(X)} samples")
    logger.info(f"  Class distribution: "
                f"SHORT={np.sum(y == 0)}, NEUTRAL={np.sum(y == 1)}, LONG={np.sum(y == 2)}")

    # ── 2b. Class Balancing ─────────────────────────────────────────────
    sample_weights = None
    if class_balance:
        logger.info("\n⚖️  Class balancing ENABLED (inverse-frequency weighting)")
        sample_weights = _compute_sample_weights(y)
    else:
        logger.info("\n⚖️  Class balancing DISABLED")

    # ── 3. Model Config ─────────────────────────────────────────────────
    model_type = model_type.lower()
    if model_type == "xgboost":
        model_params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_child_weight=min_child_weight,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            use_label_encoder=False,
            random_state=42,
            verbosity=0,
        )
        logger.info(f"\n📐 XGBoost Config: trees={n_estimators}, depth={max_depth}, "
                    f"lr={learning_rate}, min_child={min_child_weight}")
    elif model_type == "random_forest":
        model_params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_child_weight,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced" if class_balance else None,
        )
        logger.info(f"\n📐 Random Forest Config: trees={n_estimators}, depth={max_depth}, "
                    f"min_samples_leaf={min_child_weight}")
    else:
        logger.error(f"Unsupported model_type: {model_type}")
        return ""

    # ── 4. Walk-Forward Validation ──────────────────────────────────────
    total_size = len(X)
    fold_size = total_size // (n_folds + 1)

    fold_reports = []

    logger.info(f"\n{'='*60}")
    logger.info(f"Walk-Forward Validation ({n_folds} folds, ~{fold_size} samples/fold)")
    logger.info(f"{'='*60}")

    for fold in range(n_folds):
        train_end = fold_size * (fold + 1)
        test_start = train_end
        test_end = min(test_start + fold_size, total_size)

        if test_end <= test_start:
            break

        X_train, y_train = X[:train_end], y[:train_end]
        X_test, y_test = X[test_start:test_end], y[test_start:test_end]
        w_train = sample_weights[:train_end] if sample_weights is not None else None

        if model_type == "xgboost":
            model = XGBClassifier(**model_params)
            model.fit(
                X_train, y_train,
                sample_weight=w_train,
                eval_set=[(X_test, y_test)],
                verbose=False,
            )
        else:
            # For Random Forest, class_weight is already in model_params if balanced
            # But we can also pass sample_weight if manually computed
            model = RandomForestClassifier(**model_params)
            model.fit(X_train, y_train, sample_weight=w_train)

        y_pred = model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)

        report = classification_report(
            y_test, y_pred,
            target_names=CLASS_NAMES,
            output_dict=True,
            zero_division=0,
        )
        fold_reports.append({"fold": fold + 1, "accuracy": acc, "report": report})

        logger.info(f"\n── Fold {fold + 1}/{n_folds} ──")
        logger.info(f"  Train: 0–{train_end} ({train_end} samples)")
        logger.info(f"  Test:  {test_start}–{test_end} ({test_end - test_start} samples)")
        logger.info(f"  Accuracy: {acc:.4f}")

        # Print per-class metrics
        for cls_name in CLASS_NAMES:
            if cls_name in report:
                p = report[cls_name]["precision"]
                r = report[cls_name]["recall"]
                f1 = report[cls_name]["f1-score"]
                sup = int(report[cls_name]["support"])
                logger.info(f"  {cls_name:>8s}: P={p:.3f}  R={r:.3f}  F1={f1:.3f}  (n={sup})")

    # ── 5. Aggregate Results ────────────────────────────────────────────
    avg_acc = np.mean([f["accuracy"] for f in fold_reports])
    logger.info(f"\n{'='*60}")
    logger.info(f"Average Walk-Forward Accuracy: {avg_acc:.4f}")
    logger.info(f"{'='*60}")

    # ── 6. Final Model (train on ALL data) ──────────────────────────────
    logger.info("\nTraining final model on full dataset...")

    if model_type == "xgboost":
        final_model = XGBClassifier(**model_params)
    else:
        final_model = RandomForestClassifier(**model_params)
        
    final_model.fit(X, y, sample_weight=sample_weights)

    # ── 7. Save Model ──────────────────────────────────────────────────
    os.makedirs(model_output_dir, exist_ok=True)
    algo_tag = "xgb" if model_type == "xgboost" else "rf"
    
    if not model_name:
        model_name = datetime.now().strftime("%Y%m%d")
    
    # Ensure prefix (e.g., xgb_20260223 or xgb_my_model)
    if not model_name.startswith(f"{algo_tag}_"):
        final_filename = f"{algo_tag}_{model_name}"
    else:
        final_filename = model_name

    if not final_filename.endswith(".joblib"):
        final_filename += ".joblib"
        
    model_path = os.path.join(model_output_dir, final_filename)
    joblib.dump(final_model, model_path)

    logger.info(f"\n✅ Model saved to: {model_path}")
    logger.info(f"   Features: {FEATURE_COLUMNS}")

    # ── 8. Feature Importance ───────────────────────────────────────────
    importances = final_model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]

    logger.info("\n📊 Feature Importance:")
    for idx in sorted_idx:
        logger.info(f"  {FEATURE_COLUMNS[idx]:>15s}: {importances[idx]:.4f}")

    return model_path


# ── CLI entry point ─────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Train ML Model for NIFTY")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", type=str, default="models", help="Model output directory")
    parser.add_argument("--model-name", type=str, default="", help="Output filename (without .joblib)")
    parser.add_argument("--resample", type=int, default=300, help="Candle interval in seconds")
    parser.add_argument("--forward-bars", type=int, default=6, help="Bars ahead for labeling")
    parser.add_argument("--threshold", type=float, default=0.15, help="%% move threshold for labels")
    parser.add_argument("--folds", type=int, default=3, help="Walk-Forward folds")
    parser.add_argument("--no-balance", action="store_true", help="Disable class balancing")
    parser.add_argument("--trees", type=int, default=300, help="XGBoost n_estimators")
    parser.add_argument("--depth", type=int, default=4, help="XGBoost max_depth")
    parser.add_argument("--lr", type=float, default=0.05, help="XGBoost learning_rate")
    parser.add_argument("--min-child", type=int, default=5, help="XGBoost min_child_weight")
    parser.add_argument("--features", type=str, default="base,indicators,candles",
                        help="Comma-separated feature groups: base,indicators,candles")
    parser.add_argument("--model-type", type=str, default="xgboost", choices=["xgboost", "random_forest"],
                        help="ML algorithm to use")

    args = parser.parse_args()

    model_path = train(
        start_date=args.start,
        end_date=args.end,
        model_output_dir=args.output_dir,
        model_name=args.model_name,
        resample_seconds=args.resample,
        forward_bars=args.forward_bars,
        threshold_pct=args.threshold,
        n_folds=args.folds,
        class_balance=not args.no_balance,
        n_estimators=args.trees,
        max_depth=args.depth,
        learning_rate=args.lr,
        min_child_weight=args.min_child,
        feature_sets=[s.strip() for s in args.features.split(',')],
        model_type=args.model_type,
    )

    if model_path:
        print(f"\n🎉 Training complete! Model: {model_path}")
    else:
        print("\n❌ Training failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
