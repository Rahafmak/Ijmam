# Code review — unified in-cab DMS

Reviewed against the live script and against its own output
(`data/sample_incab_violations.csv`, 34 violations from a real ~6-minute
session). Ordered by how much each one would cost you.

The pipeline itself is good. Four detectors, two of them free of any trained
weights, running together in one loop at interactive speed, with a live panel
and a clean CSV export. Adding MediaPipe EAR/MAR is the single biggest upgrade
the project has had — drowsiness is the thing Ijmam is named after, and until
now nothing measured it directly.

---

## 1 · Sustained violations are counted many times — fixed

**The evidence is in your own export.** Consecutive `phone_use` rows sit at
gaps of exactly 8.0, 8.0, 8.0 seconds. `drowsiness` rows sit at 5.0 and 6.0.
Those are the cooldown values, not driver behaviour — one continuous phone use
re-logs every 8 seconds for as long as the phone is visible.

Effect on the numbers: 14 phone rows and 11 drowsiness rows in six minutes.
The dashboard picks "most common violation" by count, so a single long phone
call becomes the headline finding.

The earlier version of your code had a `phone_in_violation` latch that
prevented this; the rewrite dropped it. The app version restores the latch and
adds a `duration_s` column, so a four-minute phone call is one row that says
four minutes. That is better data than either version: you keep the severity
information without inflating the count.

`PHONE_LATCH` and `DROWSY_LATCH` at the top of `ijmam/cv_incab.py` turn it back
off if you disagree.

## 2 · Any seatbelt detection counts as "belt worn" — fixed

```python
has_belt = has_belt_obb or has_belt_box
```

This is safe if `besttt.pt` has exactly one class. The moment it has two —
`seatbelt` and `no_seatbelt`, which is how most Roboflow seatbelt datasets are
labelled — a confident `no_seatbelt` box is read as proof the belt IS on, and
the violation never fires.

Worth checking before you present: print `belt_model.names`. If it returns two
classes, the live script has a silent false-negative on the exact violation it
is meant to catch. The app checks labels instead of box counts and prints the
class list in the run notes so you can see it on screen.

## 3 · Wall-clock time breaks on recorded video — fixed

`time.time()` for cooldowns and `datetime.now()` for timestamps are exactly
right at a webcam, where processing time and real time are the same. On a
recorded file they are not. A 10-minute clip processed in 90 seconds compresses
every cooldown to a ninth of its intended length and stamps every violation
with the time you ran the analysis.

The app runs everything on `frame_index / fps`, offset from a footage start
time you enter. Nothing to change in your live script — this only matters for
offline processing.

## 4 · Thresholds worth re-tuning before submission — your call

These are not bugs, but a judge may ask, and the honest answer should be ready.

**Drowsiness at 8 consecutive frames** is about 0.4 seconds of closed eyes at a
20fps webcam. A normal blink is 0.1–0.4s and a micro-sleep is usually defined
as 1–3s, so 0.4s sits right on the boundary — which is consistent with 11
drowsiness events in six minutes. If those were real micro-sleeps that driver
should not be driving. Consider 1.5s (30 frames at 20fps), and say which
definition you chose and why.

**Yawning at MAR > 0.50 for 10 frames** will also fire on talking and on
singing. Eight yawns in six minutes is high for a genuinely alert person. If
your test session included talking, that is the explanation.

**EAR 0.25** is the standard literature value and is fine. Say so — it is a
citable choice, and citable choices are worth more than tuned ones.

The deeper point: your frame-count constants are hardware-dependent. `8 frames`
is 0.4s at 20fps and 0.27s at 30fps, so the same code becomes a different rule
on a different camera. The app converts them to seconds and back using the
actual fps of the file. Worth doing in the live script too.

## 5 · Smaller things

- **Hardcoded `C:\Users\NOURA\Downloads\` paths.** Runs on one laptop. Move the
  weights into the repo and use a relative path.
- **`safety_score` can go negative** in the data and is only floored at zero for
  display. Your session hit 0% — worth showing the raw penalty total separately,
  because "0%" cannot distinguish a bad session from a catastrophic one.
- **A new `pyttsx3` engine per alert.** `pyttsx3.init()` inside a thread, once
  per violation, leaks engines and blocks on some platforms. Initialise once and
  push text onto a queue.
- **`face_mesh` is never closed** and the CSV is silently not written when there
  are zero violations — the one run where you most want a file confirming it ran.
- **No `min_face_detection` guard.** If the driver's face is out of frame the
  EAR/MAR detectors go quiet and the log looks clean. The app reports what
  percentage of frames contained a face and warns below 50%.

## 6 · One thing to say out loud in the defence

Your session ran 00:30–00:36 and produced 34 violations, 19 of them fatigue
indicators. Do not present that as a finding — it is you testing at midnight,
and a panel that spots it will discount everything else you say.

Present it as what it is: **proof the pipeline works end to end on real
footage**, with a session that happens to sit inside the 23:00–05:00 window
your own policy manual defines as the night shift. That framing is honest and
still makes the point.

---

## What did not change

Every threshold value: EAR 0.25, MAR 0.50, belt trigger 2.5s, cooldowns
8/5/6s, confidences 0.30 and 0.55, penalties 10/15/20/5. The EAR and MAR
formulas, the landmark index sets, and the detection order. Anyone reading
`ijmam/cv_incab.py` next to the live script should recognise it immediately.
