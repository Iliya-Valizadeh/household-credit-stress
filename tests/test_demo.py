"""`make demo` runs the real backtest on the committed data and prints a result.
No network: `evaluate.run_evaluation` only reads files already under `data/`.
"""

from __future__ import annotations

import pytest

from household_credit_stress import demo


def test_demo_prints_the_arx_result(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "arx" in out
    assert "h1" in out and "h3" in out
