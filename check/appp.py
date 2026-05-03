import cv2
import numpy as np
from scipy.spatial import distance as dist
import streamlit as st
import time
from collections import deque
import plotly.graph_objects as go
import threading
import queue
import io
import av
from streamlit_webrtc import (
    RTCConfiguration,
    VideoProcessorBase,
    WebRtcMode,
    webrtc_streamer,
)
import os
import hashlib

# Configure Streamlit - MUST be first!
st.set_page_config(page_title="Focus Guard", page_icon="🧠", layout="wide")

# Simple Password-based Authentication
USERS = {
    'student1': hashlib.sha256('password123'.encode()).hexdigest(),
    'student2': hashlib.sha256('password456'.encode()).hexdigest(),
    'admin': hashlib.sha256('admin123'.encode()).hexdigest()
}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_user():
    """Render login form"""
    st.markdown("### 🔐 Login")
    username = st.text_input("Username", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")
    
    if st.button("Login"):
        if username in USERS and USERS[username] == hash_password(password):
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.user_name = username.title()
            st.success(f"Welcome, {username}!")
            st.rerun()
        else:
            st.error("Invalid username or password")

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.user_name = None

# Authentication check
if not st.session_state.authenticated:
    col1, col2 = st.columns([1, 2])
    with col1:
        login_user()
    st.stop()

# User is authenticated - show logout button in sidebar
with st.sidebar:
    st.success(f"✅ Logged in as: **{st.session_state.user_name}**")
    if st.button("🚪 Logout"):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.user_name = None
        st.rerun()

TELEGRAM_BOT_TOKEN = "8702324957:AAE45czlrbs5nt9q7uxxwgukArUpNjoZ-j0"
TELEGRAM_CHAT_ID   = "-1003964944926"

RTC_CONFIGURATION = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)
METRICS_QUEUE = queue.Queue(maxsize=30)


# settings
EAR_THRESHOLD = 0.23
EAR_CONSEC_FRAMES = 4
GAZE_THRESHOLD = 0.28
MAX_BLINK_RATE = 25

YOLO_MODEL = "yolov8n.pt"
YOLO_EVERY_N_FRAMES = 5
YOLO_IMG_SIZE = 416
YOLO_CONF = 0.45
SUSPICIOUS_OBJECTS = {"cell phone", "book", "remote", "laptop", "tv"}

VIOLATION_COOLDOWN = 15.0
GAZE_GRACE_SEC = 2.5
ABSENCE_GRACE_SEC = 3.0


def eye_aspect_ratio(eye_landmarks):
    """Calculate EAR from 6 eye landmarks (normalized coordinates)"""
    points = eye_landmarks  # Already in (x, y) format
    A = dist.euclidean(points[1], points[5])
    B = dist.euclidean(points[2], points[4])
    C = dist.euclidean(points[0], points[3])
    return (A + B) / (2.0 * C) if C != 0 else 0


def get_bounding_box(eye_landmarks):
    """Get bounding box from 6 eye landmarks"""
    x_coords = [p[0] for p in eye_landmarks]
    y_coords = [p[1] for p in eye_landmarks]
    return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))


def get_iris_center(eye_frame):
    if eye_frame is None or eye_frame.size == 0:
        return None
    gray = cv2.cvtColor(eye_frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    _, thresh = cv2.threshold(gray, 35, 255, cv2.THRESH_BINARY_INV)
    thresh = cv2.erode(thresh, None, iterations=2)
    thresh = cv2.dilate(thresh, None, iterations=2)
    moments = cv2.moments(thresh)
    if moments["m00"] != 0:
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        return (cx, cy)
    return None


# YOLO OBJECT DETECTOR
@st.cache_resource
def load_object_detector():
    try:
        from ultralytics import YOLO
        model = YOLO(YOLO_MODEL)
        return model
    except Exception as e:
        st.warning(f"YOLO не загружен: {e}. Детекция объектов отключена.")
        return None


# VIOLATION MANAGER
class ViolationManager:
    def __init__(self, cooldown_sec=15.0, gaze_grace=2.5):
        self.cooldown_sec = cooldown_sec
        self.gaze_grace = gaze_grace
        self.last_sent = {}
        self.first_seen = {}

    def _grace_for(self, vio_type):
        if vio_type == "person_absent":
            return ABSENCE_GRACE_SEC
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


# TELEGRAM NOTIFIER
try:
    import requests as _requests
except ImportError:
    _requests = None


class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self._queue = queue.Queue(maxsize=20)
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        self.last_error = None
        self.total_sent = 0

    def is_configured(self):
        return (
            bool(self.token and self.chat_id)
            and self.token != "YOUR_BOT_TOKEN_HERE"
            and self.chat_id != "YOUR_CHAT_ID_HERE"
            and _requests is not None
        )

    def send_async(self, frame_bgr, caption):
        if not self.is_configured():
            return
        try:
            self._queue.put_nowait((frame_bgr.copy(), caption))
        except queue.Full:
            pass

    def _loop(self):
        while True:
            frame, caption = self._queue.get()
            try:
                self._send(frame, caption)
            except Exception as e:
                self.last_error = str(e)
            finally:
                self._queue.task_done()

    def _send(self, frame_bgr, caption):
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        files = {"photo": ("violation.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")}
        data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "Markdown"}
        r = _requests.post(url, data=data, files=files, timeout=15)
        if r.status_code == 200:
            self.total_sent += 1
            self.last_error = None
        else:
            self.last_error = f"HTTP {r.status_code}: {r.text[:200]}"


@st.cache_resource
def get_notifier():
    return TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)


@st.cache_resource
def load_models():
    """Load OpenCV face cascade classifier"""
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )
    return face_cascade


face_cascade = load_models()


class FocusVideoProcessor(VideoProcessorBase):
    def __init__(self, face_cascade, yolo_model, notifier, settings, session_start=None):
        self.face_cascade = face_cascade
        self.yolo_model = yolo_model
        self.notifier = notifier
        self.settings = settings
        self.violation_mgr = ViolationManager(VIOLATION_COOLDOWN, GAZE_GRACE_SEC)

        self.session_start = session_start if session_start is not None else time.time()
        self.total_blinks = 0
        self.frame_counter = 0
        self.last_blink_time = time.time()
        self.focus_scores = deque(maxlen=400)
        self.yolo_frame_cnt = 0
        self.last_yolo_objects = []
        self.last_ear_valid = False  # Track if last frame had valid EAR (iris detected)

    def _push_metrics(self, data):
        try:
            METRICS_QUEUE.put_nowait(data)
        except queue.Full:
            try:
                METRICS_QUEUE.get_nowait()
                METRICS_QUEUE.put_nowait(data)
            except queue.Empty:
                pass

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1)
        h, w, c = img.shape
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detect faces using OpenCV cascade classifier
        faces = self.face_cascade.detectMultiScale(
            gray, 
            scaleFactor=1.1, 
            minNeighbors=5, 
            minSize=(30, 30)
        )
        
        faces_count = len(faces)
        current_ear = 1.0  # Default to "eyes open" when no face detected (> EAR_THRESHOLD of 0.23)
        ear_valid = False  # No valid iris detected by default
        gaze_direction = "👀 Looking Center"
        person_absent = faces_count == 0

        if person_absent:
            gaze_direction = "🚫 No person detected"
            self.frame_counter = 0  # Reset blink counter when person absent

        # Process detected faces
        for (x, y, w_face, h_face) in faces:
            # Draw face rectangle
            cv2.rectangle(img, (x, y), (x + w_face, y + h_face), (0, 255, 120), 3)
            
            # Estimate eye regions (approximate positions)
            eye_y = y + int(h_face * 0.3)
            eye_h = int(h_face * 0.2)
            left_eye_x = x + int(w_face * 0.2)
            right_eye_x = x + int(w_face * 0.65)
            eye_w = int(w_face * 0.15)
            
            # Extract eye regions
            left_eye_region = img[eye_y:eye_y+eye_h, left_eye_x:left_eye_x+eye_w]
            right_eye_region = img[eye_y:eye_y+eye_h, right_eye_x:right_eye_x+eye_w]
            
            # Draw eye rectangles
            cv2.rectangle(img, (left_eye_x, eye_y), (left_eye_x+eye_w, eye_y+eye_h), (255, 100, 255), 2)
            cv2.rectangle(img, (right_eye_x, eye_y), (right_eye_x+eye_w, eye_y+eye_h), (255, 100, 255), 2)
            
            # Detect iris/pupil in eyes
            left_iris = get_iris_center(left_eye_region)
            right_iris = get_iris_center(right_eye_region)
            
            # Blink detection: eye is closed when iris cannot be detected
            both_eyes_open = left_iris is not None and right_iris is not None
            
            if both_eyes_open:
                left_ratio = left_iris[0] / max(1, left_eye_region.shape[1])
                right_ratio = right_iris[0] / max(1, right_eye_region.shape[1])
                avg_ratio = (left_ratio + right_ratio) / 2.0
                current_ear = 0.9  # Eyes open
                ear_valid = True  # Valid iris detection
                
                # Gaze direction
                if avg_ratio < (0.5 - GAZE_THRESHOLD):
                    gaze_direction = "👈 Looking Left"
                elif avg_ratio > (0.5 + GAZE_THRESHOLD):
                    gaze_direction = "👉 Looking Right"
                else:
                    gaze_direction = "👀 Looking Center"
                
                # Draw iris centers
                lx = left_eye_x + left_iris[0]
                ly = eye_y + left_iris[1]
                rx = right_eye_x + right_iris[0]
                ry = eye_y + right_iris[1]
                cv2.circle(img, (int(lx), int(ly)), 6, (0, 255, 255), -1)
                cv2.circle(img, (int(rx), int(ry)), 6, (0, 255, 255), -1)
            else:
                current_ear = 0.1  # Eyes closed/not detected
                ear_valid = False  # Iris not detected

        # Blink detection: count blinks ONLY on valid iris transitions (open → closed → open)
        # This avoids false blinks from iris detection failures
        if ear_valid and self.last_ear_valid:
            # Both this frame and last frame have valid iris: eyes staying open
            self.frame_counter = 0
        elif not ear_valid and self.last_ear_valid:
            # Transition from valid (open) to invalid (closed): eyes starting to close
            self.frame_counter = 1
        elif ear_valid and not self.last_ear_valid:
            # Transition from invalid (closed) to valid (open): eyes reopening
            self.frame_counter += 1
            if self.frame_counter >= 1 and time.time() - self.last_blink_time > 0.2:
                self.total_blinks += 1
                self.last_blink_time = time.time()
                self.frame_counter = 0
        else:
            # Both invalid: eyes staying closed, keep counting
            self.frame_counter += 1
        
        self.last_ear_valid = ear_valid  # Remember for next frame

        if self.settings["enable_yolo"] and self.yolo_model is not None:
            self.yolo_frame_cnt += 1
            if self.yolo_frame_cnt >= YOLO_EVERY_N_FRAMES:
                self.yolo_frame_cnt = 0
                try:
                    results = self.yolo_model.predict(img, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF, verbose=False)
                    self.last_yolo_objects = []
                    if results and results[0].boxes is not None:
                        result = results[0]
                        for box, conf, cid in zip(
                            result.boxes.xyxy.cpu().numpy(),
                            result.boxes.conf.cpu().numpy(),
                            result.boxes.cls.cpu().numpy().astype(int),
                        ):
                            cname = self.yolo_model.names.get(int(cid), str(cid))
                            if cname in SUSPICIOUS_OBJECTS:
                                x1, y1, x2, y2 = box.astype(int)
                                self.last_yolo_objects.append({
                                    "class": cname,
                                    "conf": float(conf),
                                    "box": (int(x1), int(y1), int(x2), int(y2)),
                                })
                except Exception:
                    pass

            for obj in self.last_yolo_objects:
                x1, y1, x2, y2 = obj["box"]
                label = f"{obj['class']} {obj['conf']:.2f}"
                cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(img, label, (x1 + 2, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        session_time = max(1, time.time() - self.session_start)
        blink_rate_per_min = (self.total_blinks / session_time) * 60
        absence_penalty = 77 if person_absent else 0
        gaze_penalty = 35 if (not person_absent and gaze_direction != "👀 Looking Center") else 0
        blink_penalty = max(0, (blink_rate_per_min - MAX_BLINK_RATE) * 0.8)
        extra_face_penalty = 40 if faces_count > 1 else 0
        object_penalty = len(self.last_yolo_objects) * 25
        focus_score = max(15, min(100, 92 - absence_penalty - gaze_penalty - blink_penalty - extra_face_penalty - object_penalty))
        self.focus_scores.append(focus_score)

        active_violations = []
        if self.settings["track_absence"] and person_absent:
            active_violations.append(("person_absent", "🚫 Человек отсутствует в кадре"))
        if self.settings["track_gaze"] and not person_absent and gaze_direction != "👀 Looking Center":
            active_violations.append(("gaze_away", f"👀 {gaze_direction}"))
        if self.settings["track_extra"] and faces_count > 1:
            active_violations.append(("extra_face", f"👥 {faces_count} человека в кадре"))
        for obj in self.last_yolo_objects:
            cls = obj["class"]
            if self.settings["track_phone"] and cls in ("cell phone", "remote"):
                active_violations.append(("phone", f"📱 Телефон (conf {obj['conf']:.2f})"))
            elif self.settings["track_book"] and cls == "book":
                active_violations.append(("book", f"📚 Книга (conf {obj['conf']:.2f})"))
            elif self.settings["track_objects"] and cls in ("laptop", "tv"):
                active_violations.append((cls, f"💻 {cls} (conf {obj['conf']:.2f})"))

        confirmed_log = []
        confirmed = self.violation_mgr.check(active_violations)
        for _, vio_text in confirmed:
            ts = time.strftime("%H:%M:%S")
            confirmed_log.append(f"[{ts}] {vio_text}")
            if self.settings["enable_telegram"] and self.notifier.is_configured():
                caption = (
                    f"🚨 *Нарушение*\n"
                    f"👤 Студент: {self.settings['student_name']}\n"
                    f"⏰ Время: {ts}\n"
                    f"📋 Тип: {vio_text}\n"
                    f"📉 Фокус: {int(focus_score)}%"
                )
                self.notifier.send_async(img, caption)

        if person_absent:
            status, color = "🔴 ЧЕЛОВЕКА НЕТ В КАДРЕ", "#ff4444"
            cv2.rectangle(img, (0, 0), (img.shape[1], img.shape[0]), (0, 0, 255), 6)
        elif active_violations:
            status, color = "🔴 НАРУШЕНИЕ", "#ff4444"
            cv2.rectangle(img, (0, 0), (img.shape[1], img.shape[0]), (0, 0, 255), 6)
        elif focus_score > 78:
            status, color = "🟢 Всё хорошо!", "#00ff9d"
        elif focus_score > 55:
            status, color = "🟡 Держи взгляд на экране", "#ffcc00"
        else:
            status, color = "🔴 Вернись к экрану", "#ff4444"

        cv2.putText(img, f"Focus: {int(focus_score)}%", (30, 55), cv2.FONT_HERSHEY_DUPLEX, 1.25, (255, 255, 255), 3)
        cv2.putText(img, gaze_direction, (30, 95), cv2.FONT_HERSHEY_DUPLEX, 0.95, (0, 255, 255), 2)
        cv2.putText(img, f"Faces: {faces_count}", (30, 130), cv2.FONT_HERSHEY_DUPLEX, 0.8, (0, 255, 120), 2)

        self._push_metrics({
            "focus_score": focus_score,
            "gaze_direction": gaze_direction,
            "blink_rate_per_min": blink_rate_per_min,
            "session_time": session_time,
            "status": status,
            "color": color,
            "active_violations": [text for _, text in active_violations],
            "confirmed_log": confirmed_log,
            "focus_scores": list(self.focus_scores),
        })

        return av.VideoFrame.from_ndarray(img, format="bgr24")

# STREAMLIT APP
# STREAMLIT APP
# STREAMLIT APP
st.markdown("""
    <style>
    /* Force adaptive colors for metrics based on Streamlit theme */
    .metric-box {
        padding: 16px;
        border-radius: 8px;
        margin: 8px 0;
        font-weight: bold;
    }
    
    .metric-label {
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 8px;
    }
    
    .metric-value {
        font-size: 28px;
        font-weight: bold;
        letter-spacing: 1px;
    }
    
    /* Light mode styling */
    @media (prefers-color-scheme: light) {
        .metric-box {
            background: linear-gradient(135deg, #e8f0ff 0%, #f0e8ff 100%);
            border: 2px solid #0066cc;
        }
        .metric-label {
            color: #333;
        }
        .metric-value {
            color: #0066cc;
        }
        
        .metric-alert {
            background: linear-gradient(135deg, #ffe8e8 0%, #fff0e8 100%);
            border: 2px solid #dc3545;
        }
        .metric-alert .metric-value {
            color: #dc3545;
        }
        
        .metric-success {
            background: linear-gradient(135deg, #e8ffe8 0%, #f0ffe8 100%);
            border: 2px solid #28a745;
        }
        .metric-success .metric-value {
            color: #28a745;
        }
    }
    
    /* Dark mode styling */
    @media (prefers-color-scheme: dark) {
        .metric-box {
            background: linear-gradient(135deg, #1a1f2e 0%, #161b28 100%);
            border: 2px solid #00d46a;
        }
        .metric-label {
            color: #e0e0e0;
        }
        .metric-value {
            color: #00ff9d;
        }
        
        .metric-alert {
            background: linear-gradient(135deg, #2a1a1a 0%, #1a2020 100%);
            border: 2px solid #ff4444;
        }
        .metric-alert .metric-value {
            color: #ff6b6b;
        }
        
        .metric-success {
            background: linear-gradient(135deg, #1a2a1a 0%, #182018 100%);
            border: 2px solid #51cf66;
        }
        .metric-success .metric-value {
            color: #69db7c;
        }
    }
    
    /* Violation row styling */
    .violation-row {
        padding: 10px 12px;
        margin: 6px 0;
        border-radius: 6px;
        border-left: 4px solid;
        font-weight: 500;
    }
    
    @media (prefers-color-scheme: light) {
        .violation-row {
            background: #f8d7da;
            border-left-color: #dc3545;
            color: #721c24;
        }
    }
    
    @media (prefers-color-scheme: dark) {
        .violation-row {
            background: #2a1a1a;
            border-left-color: #ff4444;
            color: #ffcccc;
        }
    }
    
    /* Heading adaptive color */
    h1 {
        font-size: 2.5rem !important;
    }
    
    @media (prefers-color-scheme: light) {
        h1, h2, h3 {
            color: #0066cc !important;
        }
    }
    
    @media (prefers-color-scheme: dark) {
        h1, h2, h3 {
            color: #00ff9d !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

st.title("🧠 Focus Guard")
st.markdown("**Система мониторинга** с отправкой нарушений в Telegram")

# Sidebar
with st.sidebar:
    st.header("⚙️ Настройки")
    student_name = st.text_input("Имя студента", value="Student")
    enable_telegram = st.checkbox("📨 Отправлять в Telegram", value=True)
    enable_yolo = st.checkbox("🔍 Детекция объектов (YOLO)", value=True)
    st.divider()
    st.subheader("Типы нарушений:")
    track_absence = st.checkbox("🚫 Нет человека в кадре", value=True)
    track_gaze    = st.checkbox("👀 Взгляд в сторону", value=True)
    track_extra   = st.checkbox("👥 Лишние люди", value=True)
    track_phone   = st.checkbox("📱 Телефон", value=True)
    track_book    = st.checkbox("📚 Книга", value=True)
    track_objects = st.checkbox("💻 Прочие предметы (ноутбук, TV)", value=True)
    st.divider()

    notifier = get_notifier()
    st.subheader("📨 Telegram")
    if notifier.is_configured():
        st.success("✅ Настроен")
        st.caption(f"Отправлено: {notifier.total_sent}")
        if notifier.last_error:
            st.error(notifier.last_error)
    else:
        st.warning("⚠️ Укажи TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в коде")

    if st.button("🔄 Сбросить сессию"):
        for k in ["session_start", "violations_log", "chart_counter"]:
            st.session_state.pop(k, None)
        st.rerun()

col_video, col_side = st.columns([2.2, 1])

with col_video:
    st.subheader("🎥 Камера")

with col_side:
    st.subheader("📊 Текущее состояние")
    focus_placeholder  = st.empty()
    gaze_placeholder   = st.empty()
    blink_placeholder  = st.empty()
    timer_placeholder  = st.empty()
    status_placeholder = st.empty()
    st.subheader("🚨 Журнал нарушений")
    violations_placeholder = st.empty()

if "session_start" not in st.session_state:
    st.session_state.session_start = time.time()
_session_start = st.session_state.session_start
if "violations_log" not in st.session_state:
    st.session_state.violations_log = deque(maxlen=20)
if "chart_counter" not in st.session_state:
    st.session_state.chart_counter = 0

settings = {
    "student_name": student_name,
    "enable_telegram": enable_telegram,
    "enable_yolo": enable_yolo,
    "track_absence": track_absence,
    "track_gaze": track_gaze,
    "track_extra": track_extra,
    "track_phone": track_phone,
    "track_book": track_book,
    "track_objects": track_objects,
}
yolo_model = load_object_detector() if enable_yolo else None

with col_video:
    webrtc_ctx = webrtc_streamer(
        key="focus-guard-camera",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=RTC_CONFIGURATION,
        media_stream_constraints={"video": True, "audio": False},
        video_processor_factory=lambda: FocusVideoProcessor(
            face_cascade, yolo_model, notifier, settings,
            session_start=_session_start,
        ),
        async_processing=True,
    )
    chart_placeholder = st.empty()

focus_placeholder.markdown(
    '<div class="metric-box"><div class="metric-label">🧠 Уровень фокуса</div><div class="metric-value">0%</div></div>',
    unsafe_allow_html=True
)
gaze_placeholder.markdown("**👀 Взгляд:** Ожидание...")
blink_placeholder.markdown(
    '<div class="metric-box"><div class="metric-label">👁️ Моргания/мин</div><div class="metric-value">0</div></div>',
    unsafe_allow_html=True
)
timer_placeholder.markdown(
    '<div class="metric-box"><div class="metric-label">⏱️ Время сессии</div><div class="metric-value">0 с</div></div>',
    unsafe_allow_html=True
)
status_placeholder.markdown("<h3 style='text-align: center; color: #888; margin:0;'>⏳ Ожидание камеры...</h3>", unsafe_allow_html=True)

if not webrtc_ctx.state.playing:
    violations_placeholder.markdown("<div style='text-align: center; padding: 12px; color: #666; font-style: italic;'>⬆️ Нажми START выше и разреши доступ к камере</div>", unsafe_allow_html=True)

while webrtc_ctx.state.playing:
    try:
        data = METRICS_QUEUE.get(timeout=1.0)
    except queue.Empty:
        continue

    for log_item in data["confirmed_log"]:
        st.session_state.violations_log.appendleft(log_item)

    # Determine metric box styling based on focus score and violations
    focus_score = data['focus_score']
    has_violations = len(data["active_violations"]) > 0
    
    if has_violations or focus_score < 40:
        focus_box_class = "metric-box metric-alert"
    elif focus_score > 70:
        focus_box_class = "metric-box metric-success"
    else:
        focus_box_class = "metric-box"
    
    if has_violations:
        blink_box_class = "metric-box metric-alert"
        timer_box_class = "metric-box metric-alert"
    elif focus_score > 70:
        blink_box_class = "metric-box metric-success"
        timer_box_class = "metric-box metric-success"
    else:
        blink_box_class = "metric-box"
        timer_box_class = "metric-box"
    
    # Update metrics with adaptive styling and real-time changes
    focus_placeholder.markdown(
        f'<div class="{focus_box_class}"><div class="metric-label">🧠 Уровень фокуса</div><div class="metric-value">{int(focus_score)}%</div></div>',
        unsafe_allow_html=True
    )
    gaze_placeholder.markdown(f"**👀 Взгляд:** {data['gaze_direction']}")
    blink_placeholder.markdown(
        f'<div class="{blink_box_class}"><div class="metric-label">👁️ Моргания/мин</div><div class="metric-value">{data["blink_rate_per_min"]:.1f}</div></div>',
        unsafe_allow_html=True
    )
    timer_placeholder.markdown(
        f'<div class="{timer_box_class}"><div class="metric-label">⏱️ Время сессии</div><div class="metric-value">{int(data["session_time"])} с</div></div>',
        unsafe_allow_html=True
    )
    status_placeholder.markdown(
        f"<h3 style='text-align: center; color:{data['color']}; margin:0; font-size: 1.3em;'>{data['status']}</h3>",
        unsafe_allow_html=True,
    )

    if st.session_state.violations_log:
        violations_html = "".join(
            f"<div class='violation-row'>{v}</div>"
            for v in list(st.session_state.violations_log)[:10]
        )
    elif data["active_violations"]:
        violations_html = "".join(
            f"<div class='violation-row'>{v}</div>"
            for v in data["active_violations"][:10]
        )
    else:
        violations_html = "<div style='text-align: center; padding: 12px; color: #28a745; font-weight: bold;'>✅ Нарушений нет</div>"
    violations_placeholder.markdown(violations_html, unsafe_allow_html=True)

    st.session_state.chart_counter += 1
    focus_scores = data["focus_scores"]
    if len(focus_scores) > 1 and st.session_state.chart_counter % 15 == 0:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=focus_scores,
            mode="lines",
            line=dict(color="#00ff9d", width=4),
            fill="tozeroy",
            fillcolor="rgba(0,255,157,0.1)",
        ))
        fig.update_layout(
            title="Фокус по времени",
            yaxis_range=[0, 100],
            height=280,
            template="plotly_dark",
            margin=dict(l=10, r=10, t=40, b=10),
        )
        chart_placeholder.plotly_chart(
            fig,
            use_container_width=True,
            key=f"fc_{st.session_state.chart_counter}",
        )

    time.sleep(0.05)

st.caption("Focus Guard • OpenCV + YOLOv8 + Telegram")
