"""Tests for the template's worked example. Replace them along with the example."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from household_credit_stress import __version__, data, demo, evaluate, metrics, models

REPO = Path(__file__).resolve().parent.parent


def test_version_is_set() -> None:
    assert __version__


def test_dataset_is_seeded_and_shaped() -> None:
    x1, y1 = data.make_dataset(50, seed=1)
    x2, y2 = data.make_dataset(50, seed=1)
    assert x1.shape == (50, len(data.TRUE_COEFFICIENTS))
    assert y1.shape == (50,)
    assert np.array_equal(x1, x2) and np.array_equal(y1, y2)
    assert not np.array_equal(y1, data.make_dataset(50, seed=2)[1])


def test_dataset_rejects_tiny_sizes() -> None:
    with pytest.raises(ValueError):
        data.make_dataset(1, seed=0)


def test_split_keeps_every_row_once() -> None:
    x, y = data.make_dataset(100, seed=0)
    split = data.train_test_split(x, y, 0.2, seed=0)
    assert len(split.y_test) == 20 and len(split.y_train) == 80
    together = np.sort(np.concatenate([split.y_train, split.y_test]))
    assert np.array_equal(together, np.sort(y))


@pytest.mark.parametrize("fraction", [0.0, 1.0, 0.001])
def test_split_rejects_bad_fractions(fraction: float) -> None:
    x, y = data.make_dataset(10, seed=0)
    with pytest.raises(ValueError):
        data.train_test_split(x, y, fraction, seed=0)


def test_split_rejects_mismatched_rows() -> None:
    x, y = data.make_dataset(10, seed=0)
    with pytest.raises(ValueError):
        data.train_test_split(x, y[:5], 0.5, seed=0)


def test_linear_model_recovers_the_rule_without_noise() -> None:
    x, _ = data.make_dataset(200, seed=3)
    y = data.TRUE_INTERCEPT + x @ np.asarray(data.TRUE_COEFFICIENTS)
    pred = models.LinearModel().fit(x, y).predict(x)
    assert np.allclose(pred, y)


def test_baseline_predicts_the_training_mean() -> None:
    x = np.zeros((3, 2))
    pred = models.MeanBaseline().fit(x, np.array([1.0, 2.0, 6.0])).predict(np.zeros((4, 2)))
    assert np.array_equal(pred, np.full(4, 3.0))


@pytest.mark.parametrize("model", [models.MeanBaseline(), models.LinearModel()])
def test_predict_before_fit_fails(model: models.MeanBaseline | models.LinearModel) -> None:
    with pytest.raises(RuntimeError):
        model.predict(np.zeros((2, 5)))


def test_mae_by_hand() -> None:
    assert metrics.mae(np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 1.0])) == 1.0
    with pytest.raises(ValueError):
        metrics.mae(np.array([]), np.array([]))


def test_bootstrap_interval_contains_the_value() -> None:
    rng = np.random.default_rng(0)
    y, pred = rng.normal(size=300), rng.normal(size=300)
    est = metrics.bootstrap_mae(y, pred, n_resamples=500, level=0.95, seed=0)
    assert est.ci_low < est.value < est.ci_high
    gap = metrics.bootstrap_mae_gap(y, pred, y, n_resamples=500, level=0.95, seed=0)
    assert gap.value == pytest.approx(est.value)


@pytest.mark.parametrize(("n_resamples", "level"), [(0, 0.95), (100, 1.0)])
def test_bootstrap_rejects_bad_settings(n_resamples: int, level: float) -> None:
    y = np.ones(5)
    with pytest.raises(ValueError):
        metrics.bootstrap_mae(y, y, n_resamples, level, seed=0)


def test_evaluation_writes_metrics_and_chart(tmp_path: Path) -> None:
    assert evaluate.main(["--reports-dir", str(tmp_path)]) == 0
    written = json.loads((tmp_path / evaluate.METRICS_FILE).read_text(encoding="utf-8"))
    assert (tmp_path / evaluate.CHART_FILE).stat().st_size > 0
    assert written["model"]["value"] < written["baseline"]["value"]
    for key in ("baseline", "model", "mae_gap"):
        assert written[key]["ci_low"] <= written[key]["value"] <= written[key]["ci_high"]


def test_committed_metrics_match_a_fresh_run() -> None:
    """reports/metrics.json must be what the code makes. Run `make eval` if this fails."""
    committed = json.loads((REPO / "reports" / "metrics.json").read_text(encoding="utf-8"))
    fresh, _ = evaluate.run_evaluation()
    flat_committed, flat_fresh = _flatten(committed), _flatten(fresh)
    assert flat_committed.keys() == flat_fresh.keys()
    for key, value in flat_fresh.items():
        if isinstance(value, float):
            assert flat_committed[key] == pytest.approx(value, abs=10**-evaluate.DECIMALS), key
        else:
            assert flat_committed[key] == value, key


def _flatten(node: object, prefix: str = "") -> dict[str, object]:
    if isinstance(node, dict):
        out: dict[str, object] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): node}


def test_demo_prints_the_result(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "Linear model" in out and "Baseline" in out
