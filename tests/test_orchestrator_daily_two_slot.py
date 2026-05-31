from __future__ import annotations

import json
from pathlib import Path

from extras import daily_two_slot as dts


def test_plan_morning_window(tmp_path: Path) -> None:
    plan = dts._plan(
        minutes=9 * 60 + 30,
        morning_start_minutes=9 * 60,
        afternoon_start_minutes=15 * 60,
        morning_done_today=False,
        afternoon_done_today=False,
        catch_up_morning=True,
    )
    assert plan.run_morning
    assert not plan.run_afternoon


def test_plan_afternoon_window(tmp_path: Path) -> None:
    plan = dts._plan(
        minutes=16 * 60,
        morning_start_minutes=9 * 60,
        afternoon_start_minutes=15 * 60,
        morning_done_today=True,
        afternoon_done_today=False,
        catch_up_morning=True,
    )
    assert not plan.run_morning
    assert plan.run_afternoon


def test_catch_up_morning_after_sleep(tmp_path: Path) -> None:
    plan = dts._plan(
        minutes=16 * 60,
        morning_start_minutes=9 * 60,
        afternoon_start_minutes=15 * 60,
        morning_done_today=False,
        afternoon_done_today=False,
        catch_up_morning=True,
    )
    assert plan.run_morning
    assert plan.run_afternoon
