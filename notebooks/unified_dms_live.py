"""
In-cab driver monitoring, live version.

Norah's standalone script. Runs on a local video file or a webcam, with a
live dashboard panel and spoken alerts. The app in ijmam/cv_incab.py uses
the same detection logic for offline analysis of uploaded footage.
"""

import os
import cv2
import time
import threading
import tkinter as tk
from tkinter import filedialog
import numpy as np
import pandas as pd
import pyttsx3
from datetime import datetime
import mediapipe as mp
from ultralytics import YOLO

# ==========================================================
# 1.     
# ==========================================================
root = tk.Tk()
root.withdraw()

MODELS_DIR = r'C:\\\\'
DOWNLOADS_DIR = r'C:\\\'

phone_path = os.path.join(MODELS_DIR, 'bestphonenew.pt') if os.path.exists(os.path.join(MODELS_DIR, 'bestphonenew.pt')) else os.path.join(DOWNLOADS_DIR, 'bestphonenew.pt')
belt_path  = os.path.join(MODELS_DIR, 'besttt.pt') if os.path.exists(os.path.join(MODELS_DIR, 'besttt.pt')) else os.path.join(DOWNLOADS_DIR, 'besttt.pt')

print("    ...")
video_source = filedialog.askopenfilename(
    title="   ",
    filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv")]
)

if not video_source:
    print("       ...")
    video_source = 0

phone_model = YOLO(phone_path)
belt_model  = YOLO(belt_path)

# ==========================================================
# 2.  MediaPipe Face Mesh
# ==========================================================
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.35,
    min_tracking_confidence=0.35
)

LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
MOUTH = [78, 81, 13, 312, 308, 178, 14, 402]

#   
EAR_THRESHOLD = 0.22      
EAR_CONSEC_FRAMES = 8     
MAR_THRESHOLD = 0.58      
MAR_CONSEC_FRAMES = 12    

PHONE_COOLDOWN_SEC = 8.0
DROWSY_COOLDOWN_SEC = 5.0
YAWN_COOLDOWN_SEC = 6.0
BELT_COOLDOWN_SEC = 20.0  #       20 

last_phone_time = 0
last_drowsy_time = 0
last_yawn_time = 0
last_belt_time = 0

counter_ear = 0
counter_mar = 0
unbuckled_start_time = None
belt_currently_violating = False

total_phone = 0
total_belt = 0
total_drowsy = 0
total_yawn = 0
safety_score = 100

recent_logs = []
violations_history = []
timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
CURRENT_TRIP_ID = f"TRIP_\timestamp_suffix\"
csv_save_path = rf'C:\\\\_dms_violations_\timestamp_suffix\.csv'

# ==========================================================
# 3.    
# ==========================================================
def speak_alert(text):
    def _speak():
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', 170)
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
    threading.Thread(target=_speak, daemon=True).start()

def euclidean_dist(pt1, pt2):
    return np.linalg.norm(pt1 - pt2)

def calculate_ear(landmarks, eye_indices, img_w, img_h):
    pts = [np.array([landmarks[i].x * img_w, landmarks[i].y * img_h]) for i in eye_indices]
    v1 = euclidean_dist(pts[1], pts[5])
    v2 = euclidean_dist(pts[2], pts[4])
    h = euclidean_dist(pts[0], pts[3])
    return (v1 + v2) / (2.0 * (h + 1e-6))

def calculate_mar(landmarks, mouth_indices, img_w, img_h):
    pts = [np.array([landmarks[i].x * img_w, landmarks[i].y * img_h]) for i in mouth_indices]
    v1 = euclidean_dist(pts[1], pts[7])
    v2 = euclidean_dist(pts[2], pts[6])
    v3 = euclidean_dist(pts[3], pts[5])
    h = euclidean_dist(pts[0], pts[4])
    return (v1 + v2 + v3) / (2.0 * (h + 1e-6))

def create_dashboard_panel(width=380, height=480):
    panel = np.zeros((height, width, 3), dtype=np.uint8)
    panel[:] = (25, 25, 25)

    cv2.putText(panel, "AI DRIVER SAFETY", (20, 35), cv2.FONT_HERSHEY_DUPLEX, 0.7, (255, 255, 255), 2)
    score_color = (0, 255, 120) if safety_score >= 80 else ((0, 165, 255) if safety_score >= 50 else (0, 0, 255))
    cv2.putText(panel, f"SAFETY SCORE: \max(0, safety_score)\%", (20, 60), cv2.FONT_HERSHEY_DUPLEX, 0.6, score_color, 2)
    cv2.line(panel, (20, 72), (width - 20, 72), (60, 60, 60), 1)

    metrics = [
        ("Phone Violations", total_phone, (0, 0, 255), 85),
        ("Seatbelt Violations", total_belt, (0, 140, 255), 140),
        ("Drowsiness Events", total_drowsy, (255, 0, 180), 195),
        ("Yawning Count", total_yawn, (0, 220, 255), 250)
    ]

    for title, count, color, y in metrics:
        cv2.rectangle(panel, (20, y), (width - 20, y + 45), (40, 40, 40), -1)
        cv2.rectangle(panel, (20, y), (28, y + 45), color, -1)
        cv2.putText(panel, title, (38, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        cv2.putText(panel, str(count), (38, y + 40), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 2)

    cv2.putText(panel, "REAL-TIME LOGS:", (20, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.line(panel, (20, 328), (width - 20, 328), (60, 60, 60), 1)

    y_log = 350
    for item in recent_logs[-4:]:
        cv2.putText(panel, f"[\item['time']\] \item['type']\", (20, y_log), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1)
        y_log += 25

    cv2.putText(panel, "Press 'q' to Save & Exit", (20, height - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
    return panel

# ==========================================================
# 4.    
# ==========================================================
cap = cv2.VideoCapture(video_source)
fps = cap.get(cv2.CAP_PROP_FPS) or 25
wait_ms = max(1, int(1000 / fps)) if isinstance(video_source, str) else 1

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.resize(frame, (640, 480))
    h, w, _ = frame.shape
    current_time = time.time()
    display_time_str = datetime.now().strftime("%H:%M:%S")
    iso_timestamp_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    annotated_frame = frame.copy()

    # .   
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_results = face_mesh.process(rgb_frame)
    face_detected = mp_results.multi_face_landmarks is not None

    chin_y = h * 0.40
    face_cx = w * 0.5
    if face_detected:
        chin_y = mp_results.multi_face_landmarks[0].landmark[152].y * h
        face_cx = mp_results.multi_face_landmarks[0].landmark[1].x * w

    # .      (   0.55  )
    phone_results = phone_model.predict(source=frame, conf=0.55, verbose=False)
    has_phone = False
    if phone_results[0].boxes is not None and len(phone_results[0].boxes) > 0:
        for box, conf, cls in zip(phone_results[0].boxes.xyxy, phone_results[0].boxes.conf, phone_results[0].boxes.cls):
            cls_name = phone_model.names[int(cls)].lower()
            if "phone" in cls_name or "cell" in cls_name or int(cls) == 0:
                x1, y1, x2, y2 = map(int, box.tolist())
                bw, bh = x2 - x1, y2 - y1
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0

                #            /
                aspect_ratio = bh / float(bw + 1e-6)
                if 40 < bw < 180 and 60 < bh < 220 and aspect_ratio > 0.9:
                    #   /    
                    if cy < (h * 0.85) and y1 > (h * 0.15):
                        has_phone = True
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(annotated_frame, f"Phone \conf:.2f\", (x1, max(65, y1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

    # .   
    belt_results = belt_model.predict(source=frame, conf=0.45, verbose=False)
    has_belt = False

    if belt_results[0].boxes is not None and len(belt_results[0].boxes) > 0:
        for box, conf, cls in zip(belt_results[0].boxes.xyxy, belt_results[0].boxes.conf, belt_results[0].boxes.cls):
            cls_name = belt_model.names[int(cls)].lower()
            if "no" not in cls_name:
                x1, y1, x2, y2 = map(int, box.tolist())
                bw, bh = x2 - x1, y2 - y1
                aspect_ratio = bw / float(bh + 1e-6)
                cy = (y1 + y2) / 2.0
                
                #       
                if aspect_ratio < 0.75 and cy > (chin_y * 0.70):
                    has_belt = True
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(annotated_frame, f"Seatbelt \conf:.2f\", (x1, max(65, y1 - 5)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    if not has_belt and belt_results[0].obb is not None and len(belt_results[0].obb) > 0:
        for obb_box, conf in zip(belt_results[0].obb.xyxyxyxy, belt_results[0].obb.conf):
            pts = obb_box.cpu().numpy().astype(np.int32)
            cy = np.mean(pts[:, 1])
            if cy > (chin_y * 0.70):
                has_belt = True
                cv2.polylines(annotated_frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                cv2.putText(annotated_frame, f"Seatbelt \conf:.2f\", (pts[0][0], max(65, pts[0][1] - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    status_text = "STATUS: SAFE DRIVING"
    status_color = (0, 200, 0)

    # 1.  
    if has_phone:
        status_text = "ALERT: PHONE IN USE!"
        status_color = (0, 0, 255)
        if (current_time - last_phone_time) > PHONE_COOLDOWN_SEC:
            total_phone += 1
            safety_score -= 10
            recent_logs.append(\'time': display_time_str, 'type': 'Phone Violation'\)
            violations_history.append(\
                'trip_id': CURRENT_TRIP_ID,
                'violation_type': 'phone_use',
                'timestamp': iso_timestamp_str
            \)
            speak_alert("Focus on the road")
            last_phone_time = current_time

    # 2.      (Single Latch + Cooldown)
    if not has_belt:
        if unbuckled_start_time is None:
            unbuckled_start_time = current_time
        
        #     3 
        if (current_time - unbuckled_start_time >= 3.0):
            if status_color == (0, 200, 0):
                status_text = "ALERT: NO SEATBELT!"
                status_color = (0, 140, 255)

            #              Cooldown
            if not belt_currently_violating and (current_time - last_belt_time > BELT_COOLDOWN_SEC):
                total_belt += 1
                safety_score -= 15
                recent_logs.append(\'time': display_time_str, 'type': 'No Seatbelt'\)
                violations_history.append(\
                    'trip_id': CURRENT_TRIP_ID,
                    'violation_type': 'no_seatbelt',
                    'timestamp': iso_timestamp_str
                \)
                speak_alert("Fasten seatbelt")
                belt_currently_violating = True
                last_belt_time = current_time
    else:
        #      
        unbuckled_start_time = None
        belt_currently_violating = False

    # 3.   
    if face_detected:
        landmarks = mp_results.multi_face_landmarks[0].landmark
        ear_left = calculate_ear(landmarks, LEFT_EYE, w, h)
        ear_right = calculate_ear(landmarks, RIGHT_EYE, w, h)
        ear = max(ear_left, ear_right)
        mar = calculate_mar(landmarks, MOUTH, w, h)

        cv2.putText(annotated_frame, f"EAR: \ear:.2f\ | MAR: \mar:.2f\", (15, 465), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

        if ear < EAR_THRESHOLD:
            counter_ear += 1
            if counter_ear >= EAR_CONSEC_FRAMES:
                status_text = "CRITICAL: DROWSINESS DETECTED!"
                status_color = (255, 0, 180)
                if (current_time - last_drowsy_time) > DROWSY_COOLDOWN_SEC:
                    total_drowsy += 1
                    safety_score -= 20
                    recent_logs.append(\'time': display_time_str, 'type': 'Drowsiness Alert'\)
                    violations_history.append(\
                        'trip_id': CURRENT_TRIP_ID,
                        'violation_type': 'drowsiness',
                        'timestamp': iso_timestamp_str
                    \)
                    speak_alert("Wake up! Drowsiness alert")
                    last_drowsy_time = current_time
        else:
            counter_ear = 0

        if mar > MAR_THRESHOLD:
            counter_mar += 1
            if counter_mar >= MAR_CONSEC_FRAMES:
                if status_color == (0, 200, 0):
                    status_text = "WARNING: YAWNING DETECTED"
                    status_color = (0, 220, 255)
                if (current_time - last_yawn_time) > YAWN_COOLDOWN_SEC:
                    total_yawn += 1
                    safety_score -= 5
                    recent_logs.append(\'time': display_time_str, 'type': 'Yawn Detected'\)
                    violations_history.append(\
                        'trip_id': CURRENT_TRIP_ID,
                        'violation_type': 'yawning',
                        'timestamp': iso_timestamp_str
                    \)
                    speak_alert("Take a break")
                    last_yawn_time = current_time
        else:
            counter_mar = 0

    #   
    cv2.rectangle(annotated_frame, (0, 0), (640, 50), (15, 15, 15), -1)
    cv2.line(annotated_frame, (0, 50), (640, 50), status_color, 2)
    cv2.putText(annotated_frame, status_text, (20, 34), cv2.FONT_HERSHEY_DUPLEX, 0.65, status_color, 2)

    #       
    dashboard_panel = create_dashboard_panel(width=380, height=480)
    combined = np.hstack((annotated_frame, dashboard_panel))

    cv2.imshow("Unified AI Driver Monitoring System", combined)
    if cv2.waitKey(wait_ms) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

# ==========================================================
# 5.    CSV
# ==========================================================
if violations_history:
    df = pd.DataFrame(violations_history)
    df = df[['trip_id', 'violation_type', 'timestamp']]
    df.to_csv(csv_save_path, index=False)
    print(f"\[+]     : \csv_save_path\")
else:
    print(f"\[!] 
ÞíÇÏÉ
 
ÂãäÉ
 
ÈäÓÈÉ
 100%: 
áã
 
íÊã
 
ÊÓÌíá
 
Ãí
 
ãÎÇáÝÇÊ
 (Safety Score: 100%).")