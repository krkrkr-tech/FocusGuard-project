"""
Focus Guard Pro — Exam proctoring system.

Run:
    python3.10 -m streamlit run app.py
Still have a bug with sending the message through telegram bot
"""

import os
import io
import sys
import time
import queue
import threading
from collections import deque

import cv2
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from scipy.spatial import distance as dist


def _import_mediapipe_face_mesh():
    errors = []
    try:
        from mediapipe.python.solutions import face_mesh as fm
        return fm
    except Exception as e:
        errors.append(f"strategy 1: {e}")
    try:
        import importlib
        return importlib.import_module("mediapipe.python.solutions.face_mesh")
    except Exception as e:
        errors.append(f"strategy 2: {e}")
    try:
        import mediapipe as mp
        return mp.solutions.face_mesh
    except Exception as e:
        errors.append(f"strategy 3: {e}")

    diagnostic = (
        "Could not import mediapipe.solutions.face_mesh.\n\n"
        f"Python: {sys.version}\n"
        f"Path: {sys.executable}\n"
    )
    try:
        import mediapipe as mp
        diagnostic += f"Mediapipe: {getattr(mp, '__version__', '?')} at {getattr(mp, '__file__', '?')}\n"
    except Exception as e:
        diagnostic += f"Mediapipe import failed: {e}\n"
    diagnostic += (
        "\nFix:\n"
        "  python3.10 -m pip uninstall -y mediapipe\n"
        "  python3.10 -m pip install --no-cache-dir \"mediapipe==0.10.18\"\n\n"
        "Errors:\n  " + "\n  ".join(errors)
    )
    raise RuntimeError(diagnostic)


mp_face_mesh = _import_mediapipe_face_mesh()


# =====================================================================
# CONFIG
# =====================================================================
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
CAMERA_INDEX = 0

EAR_THRESHOLD = 0.21
EAR_CONSEC_FRAMES = 3
GAZE_THRESHOLD = 0.20
MAX_BLINK_RATE = 25

YOLO_MODEL = "yolov8n.pt"
YOLO_EVERY_N_FRAMES = 5
YOLO_IMG_SIZE = 416
YOLO_CONF = 0.45
SUSPICIOUS_OBJECTS = {"cell phone", "book", "remote", "laptop", "tv"}

VIOLATION_COOLDOWN = 15.0
NO_FACE_GRACE_SEC = 3.0
GAZE_GRACE_SEC = 2.5

CHART_HISTORY = 300

try:
    from secrets_local import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# =====================================================================
# CAMERA STREAM
# =====================================================================
class CameraStream:
    def __init__(self, src=0, width=640, height=480):
        self.src = src
        self.width = width
        self.height = height
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.thread = None

    def start(self):
        if hasattr(cv2, 'CAP_AVFOUNDATION'):
            self.cap = cv2.VideoCapture(self.src, cv2.CAP_AVFOUNDATION)
        elif hasattr(cv2, 'CAP_DSHOW'):
            self.cap = cv2.VideoCapture(self.src, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(self.src)

        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.src)
        if not self.cap.isOpened():
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        return True

    def _update(self):
        while self.running and self.cap is not None:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.005)

    def read(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None


# =====================================================================
# FACE ANALYZER
# =====================================================================
LEFT_EYE_EAR = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_EAR = [362, 385, 387, 263, 373, 380]
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]
LEFT_EYE_CORNERS = (33, 133)
RIGHT_EYE_CORNERS = (362, 263)


class FaceAnalyzer:
    def __init__(self):
        self.face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=2, refine_landmarks=True,
            min_detection_confidence=0.5, min_tracking_confidence=0.5,
        )

    @staticmethod
    def _ear(landmarks, indices, w, h):
        pts = [(landmarks[i].x * w, landmarks[i].y * h) for i in indices]
        A = dist.euclidean(pts[1], pts[5])
        B = dist.euclidean(pts[2], pts[4])
        C = dist.euclidean(pts[0], pts[3])
        return (A + B) / (2.0 * C) if C != 0 else 0.0

    @staticmethod
    def _iris_ratio(landmarks, iris_idx, corner_idx, w):
        iris_x = np.mean([landmarks[i].x for i in iris_idx]) * w
        outer_x = landmarks[corner_idx[0]].x * w
        inner_x = landmarks[corner_idx[1]].x * w
        eye_w = abs(inner_x - outer_x)
        if eye_w == 0:
            return 0.5
        ratio = (iris_x - min(outer_x, inner_x)) / eye_w
        return float(np.clip(ratio, 0.0, 1.0))

    def analyze(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return {'faces_count': 0, 'ear': 0.0, 'gaze': '—', 'landmarks': None}

        primary = results.multi_face_landmarks[0].landmark
        avg_ear = (self._ear(primary, LEFT_EYE_EAR, w, h)
                   + self._ear(primary, RIGHT_EYE_EAR, w, h)) / 2.0

        try:
            avg_ratio = (self._iris_ratio(primary, LEFT_IRIS, LEFT_EYE_CORNERS, w)
                         + self._iris_ratio(primary, RIGHT_IRIS, RIGHT_EYE_CORNERS, w)) / 2.0
            if avg_ratio < (0.5 - GAZE_THRESHOLD):
                gaze = "Right"
            elif avg_ratio > (0.5 + GAZE_THRESHOLD):
                gaze = "Left"
            else:
                gaze = "Center"
        except Exception:
            gaze = "—"

        return {
            'faces_count': len(results.multi_face_landmarks),
            'ear': avg_ear, 'gaze': gaze,
            'landmarks': results.multi_face_landmarks,
        }

    def draw(self, frame, multi_landmarks):
        h, w = frame.shape[:2]
        for face_landmarks in multi_landmarks:
            xs = [lm.x for lm in face_landmarks.landmark]
            ys = [lm.y for lm in face_landmarks.landmark]
            x1, y1 = int(min(xs) * w), int(min(ys) * h)
            x2, y2 = int(max(xs) * w), int(max(ys) * h)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 120), 2)
            for idx_set in (LEFT_EYE_EAR, RIGHT_EYE_EAR):
                pts = np.array([(int(face_landmarks.landmark[i].x * w),
                                 int(face_landmarks.landmark[i].y * h)) for i in idx_set])
                cv2.polylines(frame, [pts], True, (0, 255, 255), 1)
            for idx_set in (LEFT_IRIS, RIGHT_IRIS):
                cx = int(np.mean([face_landmarks.landmark[i].x for i in idx_set]) * w)
                cy = int(np.mean([face_landmarks.landmark[i].y for i in idx_set]) * h)
                cv2.circle(frame, (cx, cy), 3, (0, 200, 255), -1)


# =====================================================================
# YOLO OBJECT DETECTOR
# =====================================================================
class ObjectDetector:
    def __init__(self):
        self.model = None
        self.names = {}
        self._load()

    def _load(self):
        try:
            from ultralytics import YOLO
            self.model = YOLO(YOLO_MODEL)
            self.names = self.model.names
        except ImportError:
            print("ultralytics not installed: pip install ultralytics")
        except Exception as e:
            print(f"YOLO load error: {e}")

    def detect(self, frame_bgr, target_classes=None, imgsz=416):
        if self.model is None:
            return []
        try:
            results = self.model.predict(frame_bgr, imgsz=imgsz, conf=YOLO_CONF, verbose=False)
        except Exception as e:
            print(f"YOLO error: {e}")
            return []
        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return []

        r = results[0]
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        cls_ids = r.boxes.cls.cpu().numpy().astype(int)
        out = []
        for box, conf, cid in zip(boxes, confs, cls_ids):
            cname = self.names.get(int(cid), str(cid))
            if target_classes is not None and cname not in target_classes:
                continue
            x1, y1, x2, y2 = box.astype(int)
            out.append({'class': cname, 'conf': float(conf),
                        'box': (int(x1), int(y1), int(x2), int(y2))})
        return out

    @staticmethod
    def draw(frame, objects):
        for obj in objects:
            x1, y1, x2, y2 = obj['box']
            label = f"{obj['class']} {obj['conf']:.2f}"
            color = (0, 0, 255)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


# =====================================================================
# VIOLATION MANAGER
# =====================================================================
class ViolationManager:
    def __init__(self, cooldown_sec=15.0, no_face_grace=3.0, gaze_grace=2.5):
        self.cooldown_sec = cooldown_sec
        self.no_face_grace = no_face_grace
        self.gaze_grace = gaze_grace
        self.last_sent = {}
        self.first_seen = {}

    def _grace_for(self, vio_type):
        if vio_type == "no_face":
            return self.no_face_grace
        if vio_type == "gaze_away":
            return self.gaze_grace
        if vio_type == "extra_face":
            return 1.0
        return 0.6

    def check(self, active_violations):
        now = time.time()
        active_types = {v[0] for v in active_violations}
        for t in list(self.first_seen.keys()):
            if t not in active_types:
                del self.first_seen[t]
        confirmed = []
        for vio_type, vio_text in active_violations:
            if vio_type not in self.first_seen:
                self.first_seen[vio_type] = now
                continue
            if now - self.first_seen[vio_type] < self._grace_for(vio_type):
                continue
            if now - self.last_sent.get(vio_type, 0) < self.cooldown_sec:
                continue
            self.last_sent[vio_type] = now
            confirmed.append((vio_type, vio_text))
        return confirmed


# =====================================================================
# TELEGRAM NOTIFIER (with diagnostic logging)
# =====================================================================
try:
    import requests
except ImportError:
    requests = None


class TelegramNotifier:
    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.queue = queue.Queue(maxsize=20)
        self.running = True
        self.last_error = None
        self.last_success = None
        self.total_sent = 0
        self.total_failed = 0
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def is_configured(self):
        return bool(self.bot_token and self.chat_id and requests is not None)

    def send_screenshot_async(self, frame_bgr, caption):
        if not self.is_configured():
            self.last_error = "Not configured (no token / chat_id / requests)"
            return False
        try:
            self.queue.put_nowait((frame_bgr, caption))
            return True
        except queue.Full:
            self.last_error = "Queue full — sender can't keep up"
            return False

    def _worker_loop(self):
        while self.running:
            try:
                frame_bgr, caption = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._send(frame_bgr, caption)
            except Exception as e:
                self.last_error = f"Worker exception: {e}"
                self.total_failed += 1
                print(f"[Telegram] {self.last_error}")
            finally:
                self.queue.task_done()

    def _send(self, frame_bgr, caption):
        if not self.is_configured():
            return
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            self.last_error = "Failed to encode JPEG"
            self.total_failed += 1
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        files = {'photo': ('violation.jpg', io.BytesIO(buf.tobytes()), 'image/jpeg')}
        data = {'chat_id': self.chat_id, 'caption': caption, 'parse_mode': 'Markdown'}
        try:
            r = requests.post(url, data=data, files=files, timeout=15)
            if r.status_code == 200:
                self.total_sent += 1
                self.last_success = time.strftime("%H:%M:%S")
                self.last_error = None
                print(f"[Telegram] ✅ Sent at {self.last_success}")
            else:
                self.last_error = f"HTTP {r.status_code}: {r.text[:300]}"
                self.total_failed += 1
                print(f"[Telegram] ❌ {self.last_error}")
        except requests.RequestException as e:
            self.last_error = f"Network error: {e}"
            self.total_failed += 1
            print(f"[Telegram] ❌ {self.last_error}")

    def send_test_message(self):
        """Synchronous test — returns (success, message)."""
        if not self.is_configured():
            return False, "Not configured"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {'chat_id': self.chat_id, 'text': '🧪 Focus Guard test message — connection OK'}
        try:
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                self.total_sent += 1
                self.last_success = time.strftime("%H:%M:%S")
                return True, "✅ Test sent successfully"
            else:
                err = f"HTTP {r.status_code}: {r.text[:300]}"
                self.last_error = err
                return False, f"❌ {err}"
        except requests.RequestException as e:
            err = f"Network error: {e}"
            self.last_error = err
            return False, f"❌ {err}"


# =====================================================================
# RESOURCE CACHING
# =====================================================================
@st.cache_resource
def load_face_analyzer():
    return FaceAnalyzer()


@st.cache_resource
def load_object_detector():
    return ObjectDetector()


@st.cache_resource
def get_telegram_notifier():
    return TelegramNotifier()


# =====================================================================
# STREAMLIT UI
# =====================================================================
st.set_page_config(page_title="Focus Guard Pro", page_icon="🛡️", layout="wide")

st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1 {color: #00ff9d;}
    .stMetric {background-color: #1a1f2e; border-radius: 12px; padding: 8px;}
    .violation-row {background:#2a1a1a;border-left:4px solid #ff4444;padding:8px 12px;
                    margin:4px 0;border-radius:6px;color:#ffcccc;font-size:13px;}
    </style>
""", unsafe_allow_html=True)

st.title("🛡️ Focus Guard Pro")
st.markdown("**Exam proctoring system** — detects violations and sends them to Telegram")

with st.sidebar:
    st.header("⚙️ Settings")
    student_name = st.text_input("Student name", value="Student")
    enable_telegram = st.checkbox("📨 Send to Telegram", value=True)
    enable_yolo = st.checkbox("🔍 Object detection (YOLO)", value=True)
    st.divider()
    st.subheader("Violation types:")
    track_phone = st.checkbox("📱 Phone", value=True)
    track_book = st.checkbox("📚 Book", value=True)
    track_extra_face = st.checkbox("👥 Extra person", value=True)
    track_no_face = st.checkbox("🚪 Missing face", value=True)
    track_gaze = st.checkbox("👀 Looking away", value=True)
    st.divider()
    if st.button("🔄 Reset session"):
        for key in ['session_start', 'violations_log']:
            st.session_state.pop(key, None)
        st.rerun()
    st.divider()

    st.subheader("📨 Telegram status")
    tg = get_telegram_notifier()
    if tg.is_configured():
        st.success("✅ Configured")
        if st.button("🧪 Send test message"):
            ok, msg = tg.send_test_message()
            if ok:
                st.success(msg)
            else:
                st.error(msg)
        st.caption(f"Sent: {tg.total_sent} | Failed: {tg.total_failed}")
        if tg.last_success:
            st.caption(f"Last sent: {tg.last_success}")
        if tg.last_error:
            st.error(f"Last error:\n{tg.last_error}")
    else:
        st.warning("⚠️ Not configured. Create secrets_local.py or set env vars.")

col_video, col_side = st.columns([2.2, 1])
with col_video:
    video_placeholder = st.empty()
    chart_placeholder = st.empty()
with col_side:
    st.subheader("📊 Current state")
    focus_placeholder = st.empty()
    status_placeholder = st.empty()
    metric_col1, metric_col2 = st.columns(2)
    gaze_placeholder = metric_col1.empty()
    blink_placeholder = metric_col2.empty()
    timer_placeholder = metric_col1.empty()
    faces_placeholder = metric_col2.empty()
    st.subheader("🚨 Violations log")
    violations_placeholder = st.empty()

if 'session_start' not in st.session_state:
    st.session_state.session_start = time.time()
if 'violations_log' not in st.session_state:
    st.session_state.violations_log = deque(maxlen=20)

face_analyzer = load_face_analyzer()
object_detector = load_object_detector() if enable_yolo else None
telegram = get_telegram_notifier() if enable_telegram else None
violation_mgr = ViolationManager(VIOLATION_COOLDOWN, NO_FACE_GRACE_SEC, GAZE_GRACE_SEC)

run = st.checkbox("🎥 Start camera", value=False)


if run:
    cam = CameraStream(src=CAMERA_INDEX, width=FRAME_WIDTH, height=FRAME_HEIGHT)
    if not cam.start():
        st.error("❌ Could not open camera. Close other apps that might be using it.")
        st.stop()

    focus_scores = deque(maxlen=CHART_HISTORY)
    total_blinks = 0
    blink_frame_counter = 0
    last_blink_time = time.time()
    yolo_frame_counter = 0
    last_yolo_objects = []
    fps_history = deque(maxlen=30)

    try:
        while run:
            t_start = time.time()
            frame = cam.read()
            if frame is None:
                time.sleep(0.01)
                continue

            frame = cv2.flip(frame, 1)
            display_frame = frame.copy()

            face_data = face_analyzer.analyze(frame)
            faces_count = face_data['faces_count']
            current_ear = face_data['ear']
            gaze_direction = face_data['gaze']
            face_landmarks = face_data['landmarks']

            if face_landmarks is not None:
                face_analyzer.draw(display_frame, face_landmarks)

            if enable_yolo and object_detector is not None:
                yolo_frame_counter += 1
                if yolo_frame_counter >= YOLO_EVERY_N_FRAMES:
                    yolo_frame_counter = 0
                    last_yolo_objects = object_detector.detect(
                        frame, target_classes=SUSPICIOUS_OBJECTS, imgsz=YOLO_IMG_SIZE)
                object_detector.draw(display_frame, last_yolo_objects)

            if current_ear > 0:
                if current_ear < EAR_THRESHOLD:
                    blink_frame_counter += 1
                    if blink_frame_counter >= EAR_CONSEC_FRAMES and time.time() - last_blink_time > 0.4:
                        total_blinks += 1
                        last_blink_time = time.time()
                else:
                    blink_frame_counter = 0

            session_time = max(1, time.time() - st.session_state.session_start)
            blink_rate = (total_blinks / session_time) * 60
            gaze_penalty = 30 if (gaze_direction not in ("Center", "—")) else 0
            blink_penalty = max(0, (blink_rate - MAX_BLINK_RATE) * 0.8)
            no_face_penalty = 50 if faces_count == 0 else 0
            extra_face_penalty = 40 if faces_count > 1 else 0
            object_penalty = len(last_yolo_objects) * 25
            focus_score = max(0, min(100, 92 - gaze_penalty - blink_penalty
                                              - no_face_penalty - extra_face_penalty - object_penalty))
            focus_scores.append(focus_score)

            active_violations = []
            if track_no_face and faces_count == 0:
                active_violations.append(("no_face", "🚪 No face detected"))
            if track_extra_face and faces_count > 1:
                active_violations.append(("extra_face", f"👥 {faces_count} people detected"))
            if track_gaze and gaze_direction not in ("Center", "—"):
                active_violations.append(("gaze_away", f"👀 Looking {gaze_direction}"))
            for obj in last_yolo_objects:
                cls = obj['class']
                if track_phone and cls in ("cell phone", "remote"):
                    active_violations.append(("phone", f"📱 Phone (conf {obj['conf']:.2f})"))
                elif track_book and cls == "book":
                    active_violations.append(("book", f"📚 Book (conf {obj['conf']:.2f})"))

            confirmed = violation_mgr.check(active_violations)
            for vio_type, vio_text in confirmed:
                ts = time.strftime("%H:%M:%S")
                st.session_state.violations_log.appendleft(f"[{ts}] {vio_text}")
                if enable_telegram and telegram is not None:
                    caption = (f"🚨 *Violation detected*\n👤 Student: {student_name}\n"
                               f"⏰ Time: {ts}\n📋 Type: {vio_text}\n📉 Focus: {int(focus_score)}%")
                    queued = telegram.send_screenshot_async(display_frame.copy(), caption)
                    if not queued:
                        print(f"[Telegram] Could not queue: {telegram.last_error}")

            if active_violations:
                status_text, status_color = "🔴 VIOLATION", "#ff4444"
            elif focus_score > 75:
                status_text, status_color = "🟢 All good", "#00ff9d"
            elif focus_score > 50:
                status_text, status_color = "🟡 Stay focused", "#ffcc00"
            else:
                status_text, status_color = "🟠 Pay attention", "#ff8c00"

            cv2.putText(display_frame, f"Focus: {int(focus_score)}%", (20, 40),
                        cv2.FONT_HERSHEY_DUPLEX, 1.0, (255, 255, 255), 2)
            cv2.putText(display_frame, f"Faces: {faces_count} | Gaze: {gaze_direction}",
                        (20, 75), cv2.FONT_HERSHEY_DUPLEX, 0.6, (0, 255, 255), 1)
            if active_violations:
                cv2.rectangle(display_frame, (0, 0),
                              (display_frame.shape[1], display_frame.shape[0]),
                              (0, 0, 255), 6)

            dt = time.time() - t_start
            if dt > 0:
                fps_history.append(1.0 / dt)
            fps_avg = sum(fps_history) / len(fps_history) if fps_history else 0
            cv2.putText(display_frame, f"FPS: {fps_avg:.1f}",
                        (display_frame.shape[1] - 110, 30),
                        cv2.FONT_HERSHEY_DUPLEX, 0.6, (200, 200, 200), 1)

            frame_rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            video_placeholder.image(frame_rgb, channels="RGB", use_container_width=True)

            focus_placeholder.metric("Focus level", f"{int(focus_score)}%")
            status_placeholder.markdown(
                f"<h3 style='color:{status_color}; margin:0;'>{status_text}</h3>",
                unsafe_allow_html=True)
            gaze_placeholder.metric("Gaze", gaze_direction)
            blink_placeholder.metric("Blinks/min", f"{blink_rate:.1f}")
            timer_placeholder.metric("Time", f"{int(session_time)}s")
            faces_placeholder.metric("Faces", faces_count)

            if st.session_state.violations_log:
                violations_html = "".join(
                    f"<div class='violation-row'>{v}</div>"
                    for v in list(st.session_state.violations_log)[:10])
            else:
                violations_html = "<div style='color:#888'>No violations yet ✅</div>"
            violations_placeholder.markdown(violations_html, unsafe_allow_html=True)

            if 'chart_counter' not in st.session_state:
                st.session_state.chart_counter = 0
            st.session_state.chart_counter += 1

            if len(focus_scores) > 1 and st.session_state.chart_counter % 15 == 0:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    y=list(focus_scores), mode='lines',
                    line=dict(color='#00ff9d', width=3),
                    fill='tozeroy', fillcolor='rgba(0,255,157,0.1)'))
                fig.update_layout(
                    title="Focus over time", yaxis_range=[0, 100], height=220,
                    template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10))
                with chart_placeholder.container():
                    st.plotly_chart(fig, use_container_width=True,
                                    key=f"fc_{st.session_state.chart_counter}")

            time.sleep(0.005)
    finally:
        cam.stop()
else:
    st.info("👆 Click 'Start camera' to begin")

st.caption("Focus Guard Pro • MediaPipe + YOLOv8 + Telegram")
