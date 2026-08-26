# Policy alignment — the planner and the manual now agree

## The problem you spotted

The rest planner and `data/company_policy.txt` were describing two different
companies. On the Plan a Trip tab the app scheduled one thing; on the Ask Ijmam
tab the policy bot quoted another. Both were on screen at the same time.

| The manual says | The old planner did |
|---|---|
| §1 maximum continuous driving is **4 hours** | solo driver got a break every **2.0 hours** |
| §1 break of at least **30 minutes** after every 4 hours | **no duration** attached to any stop |
| §1 no more than **9 hours** driving in any 24-hour period | **not enforced** — a 14 h solo trip planned silently |
| §2 night is **23:00–05:00**, 20-minute break every 2 hours | **no notion of time of day at all** |
| §3 heavy vehicles capped at 90 km/h, 80 at night | never surfaced |

The 2-hour interval was not random — it is the manual's **night** rule applied
around the clock. So the planner was too strict during the day, unable to say
why, and the 3.5-hour swap interval had no basis in the manual at all.

This is the kind of gap a panel finds in one question: *"your chatbot says four
hours, why does your planner say two?"* There is no good answer to that on the
day.

## What changed

`ijmam/policy_rules.py` is now the single source of truth. Every constant cites
the section it came from, and every scheduled stop carries that citation
through to the screen — each stop in the list shows the rule that produced it.

The planner walks the trip forward in clock time rather than dividing it into
equal parts. That is what makes the night rule possible: a driver leaving
Jeddah at 18:00 gets 4-hour legs with 30-minute breaks until 23:00, then
2-hour legs with 20-minute breaks after it, from one code path.

**The planner gained a departure-time input.** You cannot apply a night rule
without knowing whether the driver is out at night — and for a fatigue product
whose entire thesis is that the dark hours are the dangerous ones, that input
being missing was the real hole.

**The 9-hour daily cap is now enforced**, and it is what finally makes the
driver-count field mean something. It does not just change break style; it
changes whether the trip is legal.

## The demo this unlocks

Jeddah → Tabuk, 10 hours, departing 18:00 — the route from your own problem
statement:

| Drivers | Result |
|---|---|
| 1 | **Not permitted.** 10 h exceeds the 9 h daily cap (§1) |
| 2 | **Compliant.** 5 h each, swaps every 4 h |

And the schedule shifts mid-trip on its own:

```
4.0h  22:00  Rest 30 min  →  Aldrees Station - Yanbu Junction   §1 day rule
6.0h  00:30  Rest 20 min  →  SASCO Rest Area - Umluj            §2 night rule
8.0h  02:50  Rest 20 min  →  SASCO Rest Area - Duba             §2 night rule
```

The planner also volunteers this, unprompted:

> Departing 6 h earlier would cut night driving from 5 h to 1.7 h — 3.3 h less
> time on the road in the window where this fleet's violations cluster.

That line is the product. Anyone can print break times. Telling a dispatcher
that moving departure removes four hours of night exposure is the thing that
changes a decision, and it ties the three components together: the CV data
shows violations cluster at night, the manual defines the night window, and the
planner acts on both.

## One honesty note in the code

A driver swap is **not in the manual** — §1 is written for a single driver.
Treating a swap as satisfying the continuous-driving limit is our own
extension. It is labelled as such in the UI rather than dressed up as a quoted
rule, and it is worth saying out loud in the defence: knowing which of your
rules are cited and which are yours is the difference between a compliance tool
and a guess.

## What was left alone

`core/rest_stops.py` is untouched and still in the repo. It is no longer what
the app calls. If you want it back, `ijmam/trip.py` is the only import to
change.

## Routes added

`core/rest_stop_suggestions.py` had six routes, and **Jeddah ↔ Tabuk — the
corridor in your own problem statement — was not one of them.** Added, along
with Madinah ↔ Tabuk and Jeddah ↔ NEOM, following the real towns on Highway 5
north: Rabigh, Yanbu, Umluj, Al Wajh, Duba.

The file's original caveat still applies and is worth repeating: the town
positions are real, the specific station names are illustrative. Do one Google
Maps pass on Jeddah–Tabuk before you present — someone on that panel has driven
that road.
