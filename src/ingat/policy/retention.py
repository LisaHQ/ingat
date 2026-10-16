"""Bundle retention (LIFECYCLE §5.6): restic-style calendar windows in UTC plus the always-keep rules."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ingat.model import records
from ingat.model.errors import Refused


@dataclass(frozen=True, slots=True)
class BundleInfo:
    id: str
    created_at: datetime
    klass: str
    verified: bool
    restore_tested: bool
    pinned: bool  # paired with the current or previous deployment, or referenced by an open operation


_PERIODS: tuple[Callable[[datetime], tuple[int, ...]], ...] = (
    lambda t: (t.year, t.month, t.day),
    lambda t: t.isocalendar()[:2],
    lambda t: (t.year, t.month),
)


def select(
    bundles: list[BundleInfo],
    now: datetime,
    *,
    keep_daily: int,
    keep_weekly: int,
    keep_monthly: int,
    pin_pre_change_days: int,
) -> tuple[list[str], list[str]]:
    """(keep ids, delete ids), newest first. Unverified bundles are always kept and never fill a window."""
    late = sorted(b.id for b in bundles if b.created_at > now)
    if late:
        raise Refused(f"bundles dated after the host clock {records.iso(now)}: {', '.join(late)}", code="clock")
    ordered = sorted(bundles, key=lambda b: (b.created_at, b.id), reverse=True)
    verified = [b for b in ordered if b.verified]
    keep = {
        b.id
        for b in ordered
        if not b.verified or b.pinned or (b.klass == "pre-change" and (now - b.created_at).days < pin_pre_change_days)
    }
    restore_tested = [b for b in ordered if b.restore_tested]
    keep.update(group[0].id for group in (ordered, verified, restore_tested) if group)  # the newest of each
    for period, count in zip(_PERIODS, (keep_daily, keep_weekly, keep_monthly), strict=True):
        last: tuple[int, ...] | None = None
        for b in verified:
            if count <= 0:
                break
            key = period(b.created_at.astimezone(UTC))
            if key != last:
                keep.add(b.id)
                count -= 1
                last = key
    return [b.id for b in ordered if b.id in keep], [b.id for b in ordered if b.id not in keep]
