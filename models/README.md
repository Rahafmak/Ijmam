# Trained model weights go here

The app looks for these filenames, in this order:

| Detector | Filenames tried | Source |
|---|---|---|
| Phone | `bestphonenew.pt`, `phone_best.pt`, `phone.pt` | in-cab training run |
| Seatbelt | `besttt.pt`, `seatbelt_best.pt`, `belt_best.pt`, `seatbelt.pt` | seatbelt training run |

The live script loads these from `C:\Users\NOURA\Downloads\`. Copy them here
instead — a hardcoded Downloads path works on exactly one laptop.

`yolov8n.pt` is fetched automatically on first use for road-facing vehicle
detection. Needs internet once, then it is cached.

Drowsiness and yawning need **no weights** — MediaPipe FaceMesh ships its own
model with the pip package.

## If weights are missing

The app still runs, and each detector degrades independently:

- No phone weights → falls back to stock YOLOv8n's COCO `cell phone` class
- No seatbelt weights → seatbelt detection disabled
- No mediapipe → drowsiness and yawning disabled
- No ultralytics → phone and seatbelt disabled, road lane analysis still works

Every one of those prints a warning above the results. That warning is the
important part: a run with no seatbelt model reports zero seatbelt violations,
which on screen looks identical to a compliant driver.

## A note on the seatbelt model's classes

The app checks the *class label* of each detection, not just whether a box
exists. If your model has two classes (`seatbelt` and `no_seatbelt`), a
confident `no_seatbelt` box must not be read as evidence the belt is on. Check
what `belt_model.names` prints — the app shows the class list in the run notes
so you can verify it on screen.

Weights are gitignored. Do not commit them.
