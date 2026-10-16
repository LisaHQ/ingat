import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from ingat.model.errors import Refused
from ingat.policy.retention import BundleInfo, select

NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
NONE = {"keep_daily": 0, "keep_weekly": 0, "keep_monthly": 0, "pin_pre_change_days": 0}


def at(text: str) -> datetime:
    t = datetime.fromisoformat(text)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def b(
    when: str,
    *,
    id: str | None = None,
    klass: str = "scheduled",
    verified: bool = True,
    restore_tested: bool = False,
    pinned: bool = False,
) -> BundleInfo:
    return BundleInfo(
        id=id or when,
        created_at=at(when),
        klass=klass,
        verified=verified,
        restore_tested=restore_tested,
        pinned=pinned,
    )


def keep(bundles: list[BundleInfo], now: datetime = NOW, **policy: Any) -> list[str]:
    kept, deleted = select(bundles, now, **{**NONE, **policy})
    assert set(kept).isdisjoint(deleted) and set(kept) | set(deleted) == {x.id for x in bundles}
    return kept


def daily_series(first: str, last: str, hour: int = 2) -> list[BundleInfo]:
    day, end, out = at(first), at(last), []
    while day <= end:
        out.append(b((day + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%S")))
        day += timedelta(days=1)
    return out


class Basics(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(select([], NOW, **NONE), ([], []))

    def test_result_is_newest_first_and_partitions_input(self) -> None:
        bundles = [b("2026-10-01T02:00:00"), b("2026-10-03T02:00:00"), b("2026-10-02T02:00:00")]
        kept, deleted = select(bundles, NOW, **NONE)
        self.assertEqual(kept, ["2026-10-03T02:00:00"])
        self.assertEqual(deleted, ["2026-10-02T02:00:00", "2026-10-01T02:00:00"])

    def test_same_second_is_ordered_by_id(self) -> None:
        bundles = [b("2026-10-01T02:00:00", id="a"), b("2026-10-01T02:00:00", id="b")]
        self.assertEqual(select(bundles, NOW, **NONE), (["b"], ["a"]))


class Clock(unittest.TestCase):
    def test_bundle_after_now_refuses_the_whole_run(self) -> None:
        bundles = [b("2026-10-01T02:00:00"), b("2026-10-15T12:00:01", id="future")]
        with self.assertRaises(Refused) as ctx:
            select(bundles, NOW, **NONE)
        self.assertEqual(ctx.exception.code, "clock")
        self.assertEqual(ctx.exception.exit_code, 1)
        self.assertIn("future", ctx.exception.message)

    def test_bundle_at_now_is_accepted(self) -> None:
        self.assertEqual(keep([b("2026-10-15T12:00:00")]), ["2026-10-15T12:00:00"])

    def test_future_check_uses_instants_not_wall_clock(self) -> None:
        # 18:30 at +07:00 is 11:30 UTC, before NOW.
        self.assertEqual(keep([b("2026-10-15T18:30:00+07:00", id="x")]), ["x"])
        with self.assertRaises(Refused):
            keep([b("2026-10-15T20:00:00+07:00", id="y")], keep_daily=1)


class AlwaysKept(unittest.TestCase):
    def test_newest_is_kept_with_no_windows(self) -> None:
        bundles = daily_series("2026-10-01", "2026-10-05")
        self.assertEqual(keep(bundles), ["2026-10-05T02:00:00"])

    def test_newest_verified_is_kept_when_newest_is_unverified(self) -> None:
        bundles = [
            b("2026-10-05T02:00:00", verified=False),
            b("2026-10-04T02:00:00"),
            b("2026-10-03T02:00:00"),
        ]
        self.assertEqual(keep(bundles), ["2026-10-05T02:00:00", "2026-10-04T02:00:00"])

    def test_newest_restore_tested_is_kept(self) -> None:
        bundles = daily_series("2026-10-01", "2026-10-05")
        bundles[1] = b("2026-10-02T02:00:00", restore_tested=True)
        bundles[3] = b("2026-10-04T02:00:00", restore_tested=True)
        self.assertEqual(keep(bundles), ["2026-10-05T02:00:00", "2026-10-04T02:00:00"])

    def test_pinned_is_kept_whatever_its_class(self) -> None:
        bundles = daily_series("2026-10-01", "2026-10-05")
        bundles[0] = b("2026-10-01T02:00:00", pinned=True, klass="pre-change")
        bundles[2] = b("2026-10-03T02:00:00", pinned=True, klass="manual")  # referenced by an open operation
        self.assertEqual(keep(bundles), ["2026-10-05T02:00:00", "2026-10-03T02:00:00", "2026-10-01T02:00:00"])

    def test_very_long_pin_window_keeps_old_pre_change(self) -> None:
        bundles = [b("2026-10-15T02:00:00"), b("1990-01-01T00:00:00", klass="pre-change", id="pc")]
        for days in (800_000, 10**12):
            with self.subTest(days=days):
                self.assertEqual(keep(bundles, pin_pre_change_days=days), ["2026-10-15T02:00:00", "pc"])

    def test_unverified_is_never_deleted(self) -> None:
        bundles = [
            b("2025-01-01T02:00:00", verified=False, id="old-unverified"),
            *daily_series("2026-10-01", "2026-10-03"),
        ]
        self.assertEqual(keep(bundles, keep_daily=1), ["2026-10-03T02:00:00", "old-unverified"])

    def test_pre_change_younger_than_pin_days_is_kept(self) -> None:
        bundles = [
            b("2026-10-15T02:00:00"),
            b("2026-10-01T12:00:01", klass="pre-change", id="young"),
            b("2026-10-01T12:00:00", klass="pre-change", id="exactly-14-days"),
            b("2026-09-30T12:00:00", klass="pre-change", id="old"),
            b("2026-10-10T12:00:00", klass="manual", id="manual"),
        ]
        self.assertEqual(keep(bundles, pin_pre_change_days=14), ["2026-10-15T02:00:00", "young"])

    def test_pin_days_zero_pins_nothing(self) -> None:
        bundles = [b("2026-10-15T02:00:00"), b("2026-10-15T01:00:00", klass="pre-change", id="pc")]
        self.assertEqual(keep(bundles), ["2026-10-15T02:00:00"])


class Daily(unittest.TestCase):
    def test_newest_per_day_for_the_last_n_days_with_bundles(self) -> None:
        bundles = [
            b("2026-10-14T23:00:00"),
            b("2026-10-14T02:00:00"),
            b("2026-10-12T02:00:00"),
            b("2026-10-12T01:00:00"),
            b("2026-10-09T02:00:00"),
            b("2026-10-08T02:00:00"),
        ]
        self.assertEqual(
            keep(bundles, keep_daily=3),
            ["2026-10-14T23:00:00", "2026-10-12T02:00:00", "2026-10-09T02:00:00"],
        )

    def test_windows_count_days_with_bundles_not_calendar_days_before_now(self) -> None:
        bundles = daily_series("2026-01-01", "2026-01-10")
        self.assertEqual(len(keep(bundles, keep_daily=7)), 7)

    def test_day_boundary_is_utc_midnight(self) -> None:
        bundles = [b("2026-10-14T00:00:00"), b("2026-10-13T23:59:59")]
        self.assertEqual(keep(bundles, keep_daily=2), ["2026-10-14T00:00:00", "2026-10-13T23:59:59"])

    def test_offset_timestamps_are_bucketed_in_utc(self) -> None:
        # 06:00 at +07:00 on the 14th is 23:00 UTC on the 13th: same UTC day as the 13th's bundle.
        bundles = [b("2026-10-14T06:00:00+07:00", id="late-13th"), b("2026-10-13T10:00:00", id="13th")]
        self.assertEqual(keep(bundles, keep_daily=2), ["late-13th"])
        # 20:00 at -05:00 on the 12th is 01:00 UTC on the 13th: same UTC day too.
        bundles = [b("2026-10-13T10:00:00", id="13th"), b("2026-10-12T20:00:00-05:00", id="early-13th")]
        self.assertEqual(keep(bundles, keep_daily=2), ["13th"])

    def test_year_boundary_splits_days(self) -> None:
        bundles = [b("2026-01-01T00:00:00"), b("2025-12-31T23:59:59"), b("2025-12-31T00:00:00")]
        now = at("2026-01-01T01:00:00")
        self.assertEqual(keep(bundles, now, keep_daily=2), ["2026-01-01T00:00:00", "2025-12-31T23:59:59"])

    def test_more_slots_than_days_keeps_one_per_day(self) -> None:
        bundles = [b("2026-10-14T02:00:00"), b("2026-10-14T01:00:00"), b("2026-10-13T02:00:00")]
        self.assertEqual(keep(bundles, keep_daily=30), ["2026-10-14T02:00:00", "2026-10-13T02:00:00"])


class Weekly(unittest.TestCase):
    def test_iso_week_53_spans_the_new_year(self) -> None:
        # 2020-12-28 (Mon) .. 2021-01-03 (Sun) is ISO 2020-W53; 2021-01-04 starts 2021-W01.
        bundles = [
            b("2021-01-04T02:00:00"),
            b("2021-01-03T02:00:00"),
            b("2021-01-01T02:00:00"),
            b("2020-12-28T02:00:00"),
        ]
        now = at("2021-01-05T00:00:00")
        self.assertEqual(keep(bundles, now, keep_weekly=2), ["2021-01-04T02:00:00", "2021-01-03T02:00:00"])
        self.assertEqual(keep(bundles, now, keep_weekly=3), ["2021-01-04T02:00:00", "2021-01-03T02:00:00"])

    def test_iso_week_1_starts_in_the_previous_year(self) -> None:
        # 2024-12-30 (Mon) belongs to ISO 2025-W01; 2024-12-29 (Sun) to 2024-W52.
        bundles = [b("2025-01-02T02:00:00"), b("2024-12-30T02:00:00"), b("2024-12-29T02:00:00")]
        now = at("2025-01-03T00:00:00")
        self.assertEqual(keep(bundles, now, keep_weekly=2), ["2025-01-02T02:00:00", "2024-12-29T02:00:00"])

    def test_week_boundary_is_monday_utc(self) -> None:
        bundles = [b("2026-10-05T00:00:00"), b("2026-10-04T23:59:59"), b("2026-09-28T00:00:00")]
        self.assertEqual(keep(bundles, keep_weekly=2), ["2026-10-05T00:00:00", "2026-10-04T23:59:59"])

    def test_same_week_number_in_different_years_are_different_weeks(self) -> None:
        bundles = [b("2026-10-14T02:00:00"), b("2025-10-15T02:00:00")]  # both ISO week 42
        self.assertEqual(keep(bundles, keep_weekly=2), ["2026-10-14T02:00:00", "2025-10-15T02:00:00"])


class Monthly(unittest.TestCase):
    def test_month_boundary(self) -> None:
        bundles = [b("2026-02-01T00:00:00"), b("2026-01-31T23:59:59"), b("2026-01-01T00:00:00")]
        now = at("2026-02-02T00:00:00")
        self.assertEqual(keep(bundles, now, keep_monthly=2), ["2026-02-01T00:00:00", "2026-01-31T23:59:59"])

    def test_across_the_year_boundary(self) -> None:
        bundles = [
            b("2026-01-01T02:00:00"),
            b("2025-12-31T02:00:00"),
            b("2025-12-01T02:00:00"),
            b("2025-11-30T02:00:00"),
        ]
        now = at("2026-01-02T00:00:00")
        self.assertEqual(
            keep(bundles, now, keep_monthly=3),
            ["2026-01-01T02:00:00", "2025-12-31T02:00:00", "2025-11-30T02:00:00"],
        )

    def test_leap_day(self) -> None:
        bundles = [b("2024-03-01T00:00:00"), b("2024-02-29T23:00:00"), b("2024-02-28T23:00:00")]
        now = at("2024-03-02T00:00:00")
        self.assertEqual(keep(bundles, now, keep_monthly=2), ["2024-03-01T00:00:00", "2024-02-29T23:00:00"])

    def test_months_without_bundles_are_skipped(self) -> None:
        bundles = [b("2026-10-01T02:00:00"), b("2026-06-01T02:00:00"), b("2026-01-15T02:00:00")]
        self.assertEqual(len(keep(bundles, keep_monthly=3)), 3)


class Combined(unittest.TestCase):
    def test_daily_and_weekly_over_six_weeks(self) -> None:
        bundles = daily_series("2026-09-01", "2026-10-14")
        kept = keep(bundles, keep_daily=7, keep_weekly=4)
        days = [f"2026-10-{d:02d}T02:00:00" for d in range(14, 7, -1)]
        # ISO weeks 42..39: newest are Wed 10-14 and Sun 10-11 (already daily), Sun 10-04, Sun 09-27.
        self.assertEqual(kept, [*days, "2026-10-04T02:00:00", "2026-09-27T02:00:00"])

    def test_monthly_adds_the_newest_of_each_month(self) -> None:
        bundles = daily_series("2026-09-01", "2026-10-14")
        kept = keep(bundles, keep_daily=7, keep_weekly=4, keep_monthly=2)
        self.assertIn("2026-09-30T02:00:00", kept)
        self.assertEqual(len(kept), 10)

    def test_rules_count_independently(self) -> None:
        # The newest bundle fills the daily, weekly and monthly slot at once (restic semantics).
        bundles = [b("2026-10-14T02:00:00"), b("2026-10-13T02:00:00"), b("2026-10-12T02:00:00")]
        self.assertEqual(keep(bundles, keep_daily=1, keep_weekly=1, keep_monthly=1), ["2026-10-14T02:00:00"])

    def test_unverified_bundles_do_not_fill_windows(self) -> None:
        bundles = [
            b("2026-10-14T02:00:00"),
            b("2026-10-13T12:00:00", verified=False, id="bad"),
            b("2026-10-13T02:00:00", id="good-13th"),
            b("2026-10-12T02:00:00"),
        ]
        self.assertEqual(keep(bundles, keep_daily=2), ["2026-10-14T02:00:00", "bad", "good-13th"])

    def test_scheduled_run_with_typical_defaults(self) -> None:
        bundles = [*daily_series("2026-08-01", "2026-10-15"), b("2026-10-10T09:00:00", klass="pre-change", id="pc")]
        kept = keep(bundles, keep_daily=7, keep_weekly=4, keep_monthly=0, pin_pre_change_days=14)
        self.assertIn("pc", kept)
        self.assertEqual(kept[0], "2026-10-15T02:00:00")
        self.assertNotIn("2026-08-01T02:00:00", kept)


if __name__ == "__main__":
    unittest.main()
