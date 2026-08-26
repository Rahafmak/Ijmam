"""Rest scheduling, derived from the rules in data/company_policy.txt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

# §1 Rest Periods & Driving Hours
DAY_MAX_CONTINUOUS_H = 4.0
DAY_BREAK_MINUTES = 30
DAILY_MAX_DRIVING_H = 9.0

# §2 Night Driving
NIGHT_START_HOUR = 23
NIGHT_END_HOUR = 5
NIGHT_MAX_CONTINUOUS_H = 2.0
NIGHT_BREAK_MINUTES = 20

# §3 Speed Limits
HEAVY_VEHICLE_MAX_KMH = 90
NIGHT_SPEED_REDUCTION_KMH = 10

CITATION = {
    "day_break": "§1 — break of at least 30 min after every 4 h of driving",
    "night_break": "§2 — 20-min break every 2 h during night operations (23:00–05:00)",
    "daily_cap": "§1 — no more than 9 h driving in any 24-hour period",
    "swap": "§1 — a swap keeps each driver inside the 4 h continuous limit",
}

# Driver swaps are our own extension - the manual is written for one driver.
# A swap resets the continuous-driving clock because the incoming driver has
# been resting.
SWAP_MINUTES = 15


def is_night(moment: datetime) -> bool:
    """The 23:00-05:00 window defined in §2."""
    hour = moment.hour
    return hour >= NIGHT_START_HOUR or hour < NIGHT_END_HOUR


def continuous_limit(moment: datetime) -> tuple[float, int, str]:
    """(max continuous hours, break minutes, citation) at a given moment."""
    if is_night(moment):
        return NIGHT_MAX_CONTINUOUS_H, NIGHT_BREAK_MINUTES, CITATION["night_break"]
    return DAY_MAX_CONTINUOUS_H, DAY_BREAK_MINUTES, CITATION["day_break"]


def speed_limit(moment: datetime) -> int:
    return (
        HEAVY_VEHICLE_MAX_KMH - NIGHT_SPEED_REDUCTION_KMH
        if is_night(moment)
        else HEAVY_VEHICLE_MAX_KMH
    )


@dataclass
class Stop:
    hour_mark: float      # driving hours elapsed when the stop begins
    clock: datetime       # wall-clock time the driver arrives
    type: str             # "break" or "driver_swap"
    minutes: int
    rule: str             # the manual section behind this stop
    night: bool

    @property
    def label(self) -> str:
        return "Swap" if self.type == "driver_swap" else "Rest"


@dataclass
class Schedule:
    stops: list[Stop] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    compliant: bool = True
    driving_hours: float = 0.0
    rest_minutes: int = 0
    night_hours: float = 0.0
    per_driver_hours: float = 0.0

    @property
    def total_hours(self) -> float:
        return round(self.driving_hours + self.rest_minutes / 60.0, 1)

    @property
    def longest_leg(self) -> float:
        marks = [0.0] + [s.hour_mark for s in self.stops] + [self.driving_hours]
        return round(max(b - a for a, b in zip(marks, marks[1:])), 1)

    def as_legacy_dicts(self) -> list[dict]:
        """The shape core/rest_stop_suggestions expects."""
        return [{"hour_mark": s.hour_mark, "type": s.type} for s in self.stops]


def compute_rest_schedule(
    duration_hours: float,
    num_drivers: int,
    departure: datetime,
    step_minutes: float = 5.0,
) -> Schedule:
    """Walk the trip forward in clock time, placing stops where the rules require.

    Stepping through rather than dividing into equal parts is what lets the
    schedule tighten mid-journey when the trip crosses into the night window.
    """
    schedule = Schedule()
    if duration_hours <= 0:
        return schedule

    num_drivers = max(1, int(num_drivers))
    step_h = step_minutes / 60.0

    driven = 0.0
    since_stop = 0.0
    per_driver = 0.0
    clock = departure
    night_hours = 0.0
    leg_limit = DAY_MAX_CONTINUOUS_H
    leg_rule = CITATION["day_break"]
    leg_break = DAY_BREAK_MINUTES

    while driven < duration_hours - 1e-9:
        driven += step_h
        since_stop += step_h
        per_driver += step_h
        clock += timedelta(hours=step_h)
        if is_night(clock):
            night_hours += step_h

        remaining = duration_hours - driven
        if remaining <= 0.25:      # never schedule a stop in the last 15 minutes
            break

        limit, break_minutes, rule = continuous_limit(clock)

        # The strictest limit that applied at any point in this leg is the one
        # that governs it. A driver who sets off at 04:45 is in the night
        # window, and finishing the stretch after sunrise does not buy back the
        # extra two hours.
        if limit < leg_limit:
            leg_limit, leg_break, leg_rule = limit, break_minutes, rule

        if since_stop < leg_limit - 1e-9:
            continue

        if num_drivers > 1:
            stop = Stop(
                hour_mark=round(driven, 1), clock=clock, type="driver_swap",
                minutes=SWAP_MINUTES, rule=CITATION["swap"], night=is_night(clock),
            )
            per_driver = 0.0
        else:
            stop = Stop(
                hour_mark=round(driven, 1), clock=clock, type="break",
                minutes=leg_break, rule=leg_rule, night=is_night(clock),
            )

        schedule.stops.append(stop)
        schedule.rest_minutes += stop.minutes
        clock += timedelta(minutes=stop.minutes)
        since_stop = 0.0
        leg_limit, leg_break, leg_rule = continuous_limit(clock)

    schedule.driving_hours = round(duration_hours, 1)
    schedule.night_hours = round(night_hours, 1)
    schedule.per_driver_hours = round(duration_hours / num_drivers, 1)
    _check_compliance(schedule, duration_hours, num_drivers, departure)
    return schedule


def _check_compliance(
    schedule: Schedule, duration_hours: float, num_drivers: int, departure: datetime
) -> None:
    per_driver = duration_hours / num_drivers

    if per_driver > DAILY_MAX_DRIVING_H:
        schedule.compliant = False
        if num_drivers == 1:
            schedule.warnings.append(
                f"⛔ {duration_hours:g} h exceeds the {DAILY_MAX_DRIVING_H:g} h daily "
                f"driving limit for one driver ({CITATION['daily_cap']}). Add a second "
                f"driver or split the trip across two days — this route cannot be run "
                f"as planned."
            )
        else:
            schedule.warnings.append(
                f"⛔ {duration_hours:g} h across {num_drivers} drivers is "
                f"{per_driver:.1f} h each, over the {DAILY_MAX_DRIVING_H:g} h limit "
                f"({CITATION['daily_cap']}). Add another driver or split the trip."
            )
    elif per_driver > DAILY_MAX_DRIVING_H * 0.85:
        schedule.warnings.append(
            f"⚠ {per_driver:.1f} h per driver is close to the "
            f"{DAILY_MAX_DRIVING_H:g} h daily limit. No margin for delays."
        )

    if schedule.night_hours > 0:
        share = schedule.night_hours / duration_hours * 100
        schedule.warnings.append(
            f"🌙 {schedule.night_hours:g} h of this trip ({share:.0f}%) falls inside the "
            f"23:00–05:00 night window. Break intervals tighten to "
            f"{NIGHT_MAX_CONTINUOUS_H:g} h and the speed limit drops to "
            f"{HEAVY_VEHICLE_MAX_KMH - NIGHT_SPEED_REDUCTION_KMH} km/h (§2)."
        )

    if not schedule.stops and duration_hours > DAY_MAX_CONTINUOUS_H:
        schedule.compliant = False
        schedule.warnings.append(
            "⛔ No stop was scheduled on a trip longer than the continuous-driving "
            "limit. This is a bug — report it."
        )


def departure_advice(duration_hours: float, departure: datetime) -> str | None:
    """Suggest a departure shift if it would cut time spent driving after dark."""
    current = compute_rest_schedule(duration_hours, 1, departure).night_hours
    if current <= 0:
        return None

    best_shift, best_night = None, current
    for shift in range(-6, 7):
        if shift == 0:
            continue
        candidate = compute_rest_schedule(
            duration_hours, 1, departure + timedelta(hours=shift)
        ).night_hours
        if candidate < best_night - 0.4:
            best_night, best_shift = candidate, shift

    if best_shift is None:
        return None

    direction = "earlier" if best_shift < 0 else "later"
    saved = current - best_night
    return (
        f"Departing {abs(best_shift)} h {direction} would cut night driving from "
        f"{current:g} h to {best_night:g} h — {saved:g} h less time on the road in "
        f"the window where this fleet's violations cluster."
    )
