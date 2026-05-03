import cv2
import dlib
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
import os, urllib.request, bz2

DAT_PATH = "shape_predictor_68_face_landmarks.dat"
if not os.path.exists(DAT_PATH):
    url = "https://github.com/davisking/dlib-models/raw/master/shape_predictor_68_face_landmarks.dat.bz2"
    urllib.request.urlretrieve(url, DAT_PATH + ".bz2")
    with bz2.open(DAT_PATH + ".bz2") as f_in, open(DAT_PATH, "wb") as f_out:
        f_out.write(f_in.read())
    os.remove(DAT_PATH + ".bz2")

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


def eye_aspect_ratio(eye):
    points = [(p.x, p.y) for p in eye]
    A = dist.euclidean(points[1], points[5])
    B = dist.euclidean(points[2], points[4])
    C = dist.euclidean(points[0], points[3])
    return (A + B) / (2.0 * C)


def get_bounding_box(eye):
    x = [p.x for p in eye]
    y = [p.y for p in eye]
    return (min(x), min(y), max(x), max(y))


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
    detector = dlib.get_frontal_face_detector()
    predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")
    return detector, predictor


detector, predictor = load_models()


class FocusVideoProcessor(VideoProcessorBase):
    def __init__(self, detector, predictor, yolo_model, notifier, settings, session_start=None):
        self.detector = detector
        self.predictor = predictor
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
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self.detector(gray, 0)

        current_ear = 0.0
        gaze_direction = "👀 Looking Center"
        faces_count = len(faces)
        person_absent = faces_count == 0

        if person_absent:
            gaze_direction = "🚫 No person detected"

        for face in faces:
            cv2.rectangle(img, (face.left(), face.top()), (face.right(), face.bottom()), (0, 255, 120), 3)
            landmarks = self.predictor(gray, face).parts()

            left_eye_pts = landmarks[36:42]
            right_eye_pts = landmarks[42:48]
            current_ear = (eye_aspect_ratio(left_eye_pts) + eye_aspect_ratio(right_eye_pts)) / 2.0

            left_bbox = get_bounding_box(left_eye_pts)
            right_bbox = get_bounding_box(right_eye_pts)

            left_eye_frame = img[left_bbox[1]:left_bbox[3], left_bbox[0]:left_bbox[2]]
            right_eye_frame = img[right_bbox[1]:right_bbox[3], right_bbox[0]:right_bbox[2]]

            left_iris = get_iris_center(left_eye_frame)
            right_iris = get_iris_center(right_eye_frame)

            cv2.rectangle(img, (left_bbox[0], left_bbox[1]), (left_bbox[2], left_bbox[3]), (255, 100, 255), 2)
            cv2.rectangle(img, (right_bbox[0], right_bbox[1]), (right_bbox[2], right_bbox[3]), (255, 100, 255), 2)

            for pt in list(left_eye_pts) + list(right_eye_pts):
                cv2.circle(img, (pt.x, pt.y), 2, (0, 255, 255), -1)

            if left_iris and right_iris:
                left_ratio = left_iris[0] / max(1, left_eye_frame.shape[1])
                right_ratio = right_iris[0] / max(1, right_eye_frame.shape[1])
                avg_ratio = (left_ratio + right_ratio) / 2.0

                if avg_ratio < (0.5 - GAZE_THRESHOLD):
                    gaze_direction = "👈 Looking Left"
                elif avg_ratio > (0.5 + GAZE_THRESHOLD):
                    gaze_direction = "👉 Looking Right"
                else:
                    gaze_direction = "👀 Looking Center"

                lx = left_bbox[0] + left_iris[0]
                ly = left_bbox[1] + left_iris[1]
                rx = right_bbox[0] + right_iris[0]
                ry = right_bbox[1] + right_iris[1]
                cv2.circle(img, (int(lx), int(ly)), 6, (0, 255, 255), -1)
                cv2.circle(img, (int(rx), int(ry)), 6, (0, 255, 255), -1)

            if current_ear < EAR_THRESHOLD:
                self.frame_counter += 1
                if self.frame_counter >= EAR_CONSEC_FRAMES and time.time() - self.last_blink_time > 0.4:
                    self.total_blinks += 1
                    self.last_blink_time = time.time()
            else:
                self.frame_counter = 0

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
st.set_page_config(page_title="Focus Guard", page_icon="🧠", layout="wide")

st.markdown("""
    <style>
    .main {background-color: #0e1117;}
    h1 {color: #00ff9d; font-size: 3rem;}
    .stMetric {background-color: #1a1f2e; border-radius: 12px;}
    .violation-row {background:#2a1a1a;border-left:4px solid #ff4444;padding:8px 12px;
                    margin:4px 0;border-radius:6px;color:#ffcccc;font-size:13px;}
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
            detector, predictor, yolo_model, notifier, settings,
            session_start=_session_start,
        ),
        async_processing=True,
    )
    chart_placeholder = st.empty()

focus_placeholder.metric("Уровень фокуса", "—")
gaze_placeholder.markdown("**Взгляд:** —")
blink_placeholder.metric("Моргания/мин", "—")
timer_placeholder.metric("Время сессии", "0 с")
status_placeholder.markdown("<h3 style='color:#888; margin:0;'>Ожидание камеры</h3>", unsafe_allow_html=True)

if not webrtc_ctx.state.playing:
    violations_placeholder.markdown("<div style='color:#888'>Нажми START и разреши доступ к камере</div>", unsafe_allow_html=True)

while webrtc_ctx.state.playing:
    try:
        data = METRICS_QUEUE.get(timeout=1.0)
    except queue.Empty:
        continue

    for log_item in data["confirmed_log"]:
        st.session_state.violations_log.appendleft(log_item)

    focus_placeholder.metric("Уровень фокуса", f"{int(data['focus_score'])}%")
    gaze_placeholder.markdown(f"**Взгляд:** {data['gaze_direction']}")
    blink_placeholder.metric("Моргания/мин", f"{data['blink_rate_per_min']:.1f}")
    timer_placeholder.metric("Время сессии", f"{int(data['session_time'])} с")
    status_placeholder.markdown(
        f"<h3 style='color:{data['color']}; margin:0;'>{data['status']}</h3>",
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
        violations_html = "<div style='color:#888'>Нарушений нет ✅</div>"
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

st.caption("Focus Guard • dlib + YOLOv8 + Telegram")
