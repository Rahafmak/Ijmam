# Ijmam — إجمام

Driver safety and fleet management for long-distance driving in Saudi Arabia.

Four screens: **plan a trip → check footage → read the insights → ask the bots.**

---

## Run it

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python check.py
python app.py
```

macOS or Linux: `python3.12 -m venv .venv` then `source .venv/bin/activate`.

Then open **http://localhost:8080**. No API keys or model weights needed for
the planner, the insights and both chatbots.

**Python 3.10 or newer.** 3.12 is the safe choice — MediaPipe, which the
drowsiness and yawning detectors need, does not always have wheels for the
newest release.

---

## The four screens

### Plan a trip
Pick two cities, how many hours the drive takes, how many drivers, and roughly
when you are leaving. You get a verdict against the company rules, a schedule
of stops with real station names, a timeline, and a map with each stop numbered
in order.

Departure time is a dropdown, not a date field, but it matters: the manual
tightens breaks from 4 h to 2 h between 23:00 and 05:00, so the same route
gives a different schedule depending on when it starts.

Try Jeddah → Tabuk, 10 hours, leaving in the evening:

| Drivers | Result |
|---|---|
| 1 | Not allowed — over the 9 h daily limit |
| 2 | Fine — 5 h each |

Every stop can be traced back to the rule that produced it, under
*Which rule produced each stop*.

### Check footage
Upload a video, pick which camera it came from, press the button.

Driver-facing footage is checked for phone use, seatbelts, drowsiness and
yawning. Road-facing footage is checked for drifting out of lane, weaving and
following too closely.

You get a progress bar, the annotated video, a photo of the moment each problem
was caught, a results table, a CSV download, and a button that carries the
results to the Insights screen.

Detector settings are tucked away under an expander. The defaults match how the
models were trained; nobody has to touch them.

### Insights
One sentence at the top saying what the data actually shows, four numbers, a
chart of what time of day problems happen, and a breakdown by type. Trip-by-trip
and event-by-event tables are behind expanders for anyone who wants them.

Two datasets ship with the app. **A real in-cab session** is Norah's own
recorded run, 34 violations from about six minutes of footage — real model
output, useful for showing the pipeline works end to end.
**A week of fleet data** (`data/fleet_violations.csv`) is synthetic: six
drivers, 26 trips, 95 violations over seven days, with fatigue weighted toward
the small hours and one driver clearly worse than the rest. Say plainly that it
is synthetic. It exists to show what the dashboard does with a fleet's worth of
data, which a six-minute clip cannot.

Regenerate it any time with `python scripts/make_demo_violations.py`, or upload
any CSV or Excel file with `trip_id`, `violation_type` and `timestamp` columns.
A `driver` column is optional and adds a per-driver breakdown.

### Ask Ijmam
**Drivers** ask about company rules in Arabic or English, and the answer comes
back in the language they asked in.

With `GEMINI_API_KEY` set, the assistant runs the Gemini chat in
`core/policy_chat.py`, which injects the full manual into the system
instructions and answers in the user's language at temperature zero. That is
the preferred path and it reads better in Arabic than any prepared text.

Without a key it falls back to offline retrieval over `data/company_policy.txt`
and `data/company_policy_ar.txt`, returning the matching section in the
language of the question. Either way, a question the manual does not cover is
declined rather than answered.

**Managers** ask about drivers, violations and shift changes. Counts come from
the trip records, not from the model.

Trip records are stored per driver segment rather than per trip, so a trip with
two drivers produces two documents and each driver is credited only with the
events attributed to their own stretch behind the wheel. Seven violation types
are tracked: fatigue, speeding, phone, tailgating, seatbelt, lane drift and
rest compliance.

*
If `chromadb` and `ollama` are installed, the full pipeline in
`core/query_router.py` and `core/llm_answer.py` runs, with Llama 3.1 phrasing
the routed result and a short conversation memory that resolves pronouns, so
"did he speed as well?" follows on from the previous question. Without them the
same routing logic runs over BM25 retrieval, so the assistant works either way.
Install `requirements-rag.txt` for the full stack.
