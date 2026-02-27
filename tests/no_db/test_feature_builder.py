"""
Tests for the FeatureBuilder, verifying technical indicator calculation on synthetic data.
"""
import pytest
import polars as pl
from packages.ml.feature_builder import (
    FeatureBuilder, FEATURE_COLUMNS,
    BASE_FEATURES, INDICATOR_FEATURES, CANDLE_FEATURES,
    get_feature_columns, ALL_FEATURE_GROUPS,
)

def _make_synthetic_candles(n: int = 200) -> pl.DataFrame:
    """Create a fake OHLCV DataFrame with n rows."""
    import random
    random.seed(42)

    base_price = 24000.0
    rows = []
    ts = 1700000000  # arbitrary epoch

    for i in range(n):
        o = base_price + random.uniform(-50, 50)
        h = o + random.uniform(0, 30)
        l = o - random.uniform(0, 30)
        c = l + random.uniform(0, h - l)
        v = random.randint(100, 5000)
        rows.append({
            "open": o, "high": h, "low": l, "close": c,
            "volume": v, "timestamp": ts + i * 60  # 1-min candles
        })

    return pl.DataFrame(rows)

@pytest.fixture
def builder():
    return FeatureBuilder(
        resample_seconds=300,  # 5-min bars
        forward_bars=3,
        threshold_pct=0.3,
        feature_sets=ALL_FEATURE_GROUPS,
    )

@pytest.fixture
def raw_df():
    return _make_synthetic_candles(300)  # more data for indicator warm-up

def test_feature_columns_defined():
    """FEATURE_COLUMNS should be a non-empty list of strings."""
    assert isinstance(FEATURE_COLUMNS, list)
    assert len(FEATURE_COLUMNS) > 0
    for col in FEATURE_COLUMNS:
        assert isinstance(col, str)

def test_feature_groups_complete():
    """All feature groups should be present and non-empty."""
    assert len(BASE_FEATURES) > 0
    assert len(INDICATOR_FEATURES) > 0
    assert len(CANDLE_FEATURES) > 0
    # Combined should equal FEATURE_COLUMNS
    combined = get_feature_columns(ALL_FEATURE_GROUPS)
    assert len(combined) == len(BASE_FEATURES) + len(INDICATOR_FEATURES) + len(CANDLE_FEATURES)

def test_build_from_dataframe_returns_all_features(builder, raw_df):
    """Output should contain all canonical feature columns + label."""
    result = builder.build_from_dataframe(raw_df)
    if result.is_empty():
        pytest.skip("Not enough data after warm-up/label drop")

    for col in builder.feature_columns:
        assert col in result.columns, f"Missing feature: {col}"
    assert "label" in result.columns

def test_labels_are_valid(builder, raw_df):
    """Labels should only be -1, 0, or 1."""
    result = builder.build_from_dataframe(raw_df)
    if result.is_empty():
        pytest.skip("Not enough data")

    labels = set(result["label"].to_list())
    assert labels.issubset({-1, 0, 1}), f"Unexpected labels: {labels}"

def test_no_nulls_after_build(builder, raw_df):
    """After build_from_dataframe, there should be no null values."""
    result = builder.build_from_dataframe(raw_df)
    if result.is_empty():
        pytest.skip("Not enough data")

    null_counts = result.null_count()
    total_nulls = sum(null_counts.row(0))
    assert total_nulls == 0, f"Found nulls: {null_counts}"

def test_resample_reduces_row_count(builder, raw_df):
    """Resampling 300 1-min candles into 5-min bars should reduce row count."""
    resampled = builder._resample(raw_df)
    assert len(resampled) < len(raw_df)
    assert len(resampled) > 30

def test_add_all_features_adds_all_columns(builder, raw_df):
    """_add_all_features should add all feature columns to the DataFrame."""
    resampled = builder._resample(raw_df)
    featured = builder._add_all_features(resampled)

    for col in builder.feature_columns:
        assert col in featured.columns, f"Missing after _add_all_features: {col}"

def test_base_only_builder(raw_df):
    """Building with base features only should produce BASE_FEATURES columns."""
    base_builder = FeatureBuilder(
        resample_seconds=300,
        forward_bars=3,
        threshold_pct=0.3,
        feature_sets=["base"],
    )
    result = base_builder.build_from_dataframe(raw_df)
    if result.is_empty():
        pytest.skip("Not enough data")

    for col in BASE_FEATURES:
        assert col in result.columns, f"Missing base feature: {col}"
    # Should NOT have indicator/candle columns
    for col in INDICATOR_FEATURES:
        assert col not in result.columns, f"Unexpected indicator feature: {col}"

def test_selective_feature_sets(raw_df):
    """Building with specific feature sets should include only those."""
    builder = FeatureBuilder(
        resample_seconds=300,
        forward_bars=3,
        threshold_pct=0.3,
        feature_sets=["base", "candles"],
    )
    result = builder.build_from_dataframe(raw_df)
    if result.is_empty():
        pytest.skip("Not enough data")

    for col in BASE_FEATURES + CANDLE_FEATURES:
        assert col in result.columns, f"Missing feature: {col}"
