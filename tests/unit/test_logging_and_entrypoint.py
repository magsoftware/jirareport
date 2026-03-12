from __future__ import annotations

import runpy
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from jirareport.infrastructure.logging_config import (
    MAX_LOC_LENGTH,
    _format_location,
    configure_logging,
)


def test_configure_logging_runs_for_debug_and_info_levels() -> None:
    configure_logging(debug=False)
    configure_logging(debug=True)


def test_format_location_populates_and_truncates_extra_field() -> None:
    record: dict[str, Any] = {
        "name": "jirareport.infrastructure.logging_config",
        "function": "configure_logging",
        "line": 123,
        "extra": {},
    }

    assert _format_location(record) is True
    assert "location" in record["extra"]
    assert len(record["extra"]["location"]) == MAX_LOC_LENGTH


def test_format_location_pads_short_location() -> None:
    record: dict[str, Any] = {
        "name": "mod",
        "function": "fn",
        "line": 1,
        "extra": {},
    }

    assert _format_location(record) is True
    assert record["extra"]["location"] == "mod:fn:1".ljust(MAX_LOC_LENGTH)


def test_module_entrypoint_calls_cli_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cli_app = cast(Any, ModuleType("jirareport.interfaces.cli.app"))
    called: dict[str, bool] = {"value": False}

    def fake_main() -> int:
        called["value"] = True
        return 0

    fake_cli_app.main = fake_main
    monkeypatch.setitem(sys.modules, "jirareport.interfaces.cli.app", fake_cli_app)

    with pytest.raises(SystemExit) as error:
        runpy.run_module("jirareport.main", run_name="__main__")

    assert error.value.code == 0
    assert called["value"] is True
