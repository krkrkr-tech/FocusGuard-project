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


TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID   = ""


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
        for k in ["session_start", "violations_log"]:
            st.session_state.pop(k, None)
        st.rerun()

col_video, col_side = st.columns([2.2, 1])

with col_video:
    video_placeholder = st.empty()
    chart_placeholder = st.empty()

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
if "violations_log" not in st.session_state:
    st.session_state.violations_log = deque(maxlen=20)

violation_mgr = ViolationManager(VIOLATION_COOLDOWN, GAZE_GRACE_SEC)
yolo_model    = load_object_detector() if enable_yolo else None

run = st.checkbox("🎥 Запустить камеру", value=True)

if run:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        st.error("❌ Не удалось открыть камеру.")
        st.stop()

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

    total_blinks      = 0
    frame_counter     = 0
    last_blink_time   = time.time()
    focus_scores      = deque(maxlen=400)
    yolo_frame_cnt    = 0
    last_yolo_objects = []
    chart_counter     = 0

    while run:
        ret, frame = cap.read()
        if not ret:
            st.error("Ошибка чтения кадра")
            break

        frame = cv2.flip(frame, 1)
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)

        current_ear    = 0.0
        gaze_direction = "👀 Looking Center"
        faces_count    = len(faces)
        person_absent  = faces_count == 0

        if person_absent:
            gaze_direction = "🚫 No person detected"

        for face in faces:
            cv2.rectangle(frame, (face.left(), face.top()), (face.right(), face.bottom()), (0, 255, 120), 3)
            landmarks = predictor(gray, face).parts()

            left_eye_pts  = landmarks[36:42]
            right_eye_pts = landmarks[42:48]
            current_ear   = (eye_aspect_ratio(left_eye_pts) + eye_aspect_ratio(right_eye_pts)) / 2.0

            left_bbox  = get_bounding_box(left_eye_pts)
            right_bbox = get_bounding_box(right_eye_pts)

            left_eye_frame  = frame[left_bbox[1]:left_bbox[3], left_bbox[0]:left_bbox[2]]
            right_eye_frame = frame[right_bbox[1]:right_bbox[3], right_bbox[0]:right_bbox[2]]

            left_iris  = get_iris_center(left_eye_frame)
            right_iris = get_iris_center(right_eye_frame)

            cv2.rectangle(frame, (left_bbox[0], left_bbox[1]),  (left_bbox[2], left_bbox[3]),  (255, 100, 255), 2)
            cv2.rectangle(frame, (right_bbox[0], right_bbox[1]), (right_bbox[2], right_bbox[3]), (255, 100, 255), 2)

            for pt in list(left_eye_pts) + list(right_eye_pts):
                cv2.circle(frame, (pt.x, pt.y), 2, (0, 255, 255), -1)

            if left_iris and right_iris:
                left_ratio  = left_iris[0]  / max(1, left_eye_frame.shape[1])
                right_ratio = right_iris[0] / max(1, right_eye_frame.shape[1])
                avg_ratio   = (left_ratio + right_ratio) / 2.0

                if avg_ratio < (0.5 - GAZE_THRESHOLD):
                    gaze_direction = "👈 Looking Left"
                elif avg_ratio > (0.5 + GAZE_THRESHOLD):
                    gaze_direction = "👉 Looking Right"
                else:
                    gaze_direction = "👀 Looking Center"

                lx = left_bbox[0]  + left_iris[0];  ly = left_bbox[1]  + left_iris[1]
                rx = right_bbox[0] + right_iris[0]; ry = right_bbox[1] + right_iris[1]
                cv2.circle(frame, (int(lx), int(ly)), 6, (0, 255, 255), -1)
                cv2.circle(frame, (int(rx), int(ry)), 6, (0, 255, 255), -1)

            if current_ear < EAR_THRESHOLD:
                frame_counter += 1
                if frame_counter >= EAR_CONSEC_FRAMES and time.time() - last_blink_time > 0.4:
                    total_blinks += 1
                    last_blink_time = time.time()
            else:
                frame_counter = 0

        # YOLO
        if enable_yolo and yolo_model is not None:
            yolo_frame_cnt += 1
            if yolo_frame_cnt >= YOLO_EVERY_N_FRAMES:
                yolo_frame_cnt = 0
                try:
                    results = yolo_model.predict(frame, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF, verbose=False)
                    last_yolo_objects = []
                    if results and results[0].boxes is not None:
                        r = results[0]
                        for box, conf, cid in zip(
                            r.boxes.xyxy.cpu().numpy(),
                            r.boxes.conf.cpu().numpy(),
                            r.boxes.cls.cpu().numpy().astype(int)
                        ):
                            cname = yolo_model.names.get(int(cid), str(cid))
                            if cname in SUSPICIOUS_OBJECTS:
                                x1, y1, x2, y2 = box.astype(int)
                                last_yolo_objects.append({
                                    "class": cname, "conf": float(conf),
                                    "box": (int(x1), int(y1), int(x2), int(y2))
                                })
                except Exception:
                    pass

            for obj in last_yolo_objects:
                x1, y1, x2, y2 = obj["box"]
                label = f"{obj['class']} {obj['conf']:.2f}"
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(frame, label, (x1 + 2, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # FOCUS
        session_time       = max(1, time.time() - st.session_state.session_start)
        blink_rate_per_min = (total_blinks / session_time) * 60
        absence_penalty    = 77 if person_absent else 0
        gaze_penalty       = 35 if (not person_absent and gaze_direction != "👀 Looking Center") else 0
        blink_penalty      = max(0, (blink_rate_per_min - MAX_BLINK_RATE) * 0.8)
        extra_face_penalty = 40 if faces_count > 1 else 0
        object_penalty     = len(last_yolo_objects) * 25
        focus_score        = max(15, min(100, 92 - absence_penalty - gaze_penalty - blink_penalty - extra_face_penalty - object_penalty))
        focus_scores.append(focus_score)

        # VIOLATIONS
        active_violations = []
        if track_absence and person_absent:
            active_violations.append(("person_absent", "🚫 Человек отсутствует в кадре"))
        if track_gaze and not person_absent and gaze_direction != "👀 Looking Center":
            active_violations.append(("gaze_away", f"👀 {gaze_direction}"))
        if track_extra and faces_count > 1:
            active_violations.append(("extra_face", f"👥 {faces_count} человека в кадре"))
        for obj in last_yolo_objects:
            cls = obj["class"]
            if track_phone and cls in ("cell phone", "remote"):
                active_violations.append(("phone", f"📱 Телефон (conf {obj['conf']:.2f})"))
            elif track_book and cls == "book":
                active_violations.append(("book", f"📚 Книга (conf {obj['conf']:.2f})"))
            elif track_objects and cls in ("laptop", "tv"):
                active_violations.append((cls, f"💻 {cls} (conf {obj['conf']:.2f})"))

        confirmed = violation_mgr.check(active_violations)
        for vio_type, vio_text in confirmed:
            ts = time.strftime("%H:%M:%S")
            st.session_state.violations_log.appendleft(f"[{ts}] {vio_text}")
            if enable_telegram and notifier.is_configured():
                caption = (
                    f"🚨 *Нарушение*\n"
                    f"👤 Студент: {student_name}\n"
                    f"⏰ Время: {ts}\n"
                    f"📋 Тип: {vio_text}\n"
                    f"📉 Фокус: {int(focus_score)}%"
                )
                notifier.send_async(frame, caption)

        # STATUS
        if person_absent:
            status, color = "🔴 ЧЕЛОВЕКА НЕТ В КАДРЕ", "#ff4444"
            cv2.rectangle(frame, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 255), 6)
        elif active_violations:
            status, color = "🔴 НАРУШЕНИЕ", "#ff4444"
            cv2.rectangle(frame, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 255), 6)
        elif focus_score > 78:
            status, color = "🟢 Всё хорошо!", "#00ff9d"
        elif focus_score > 55:
            status, color = "🟡 Держи взгляд на экране", "#ffcc00"
        else:
            status, color = "🔴 Вернись к экрану", "#ff4444"

        cv2.putText(frame, f"Focus: {int(focus_score)}%", (30, 55),  cv2.FONT_HERSHEY_DUPLEX, 1.25, (255, 255, 255), 3)
        cv2.putText(frame, gaze_direction,                 (30, 95),  cv2.FONT_HERSHEY_DUPLEX, 0.95, (0, 255, 255),   2)
        cv2.putText(frame, f"Faces: {faces_count}",        (30, 130), cv2.FONT_HERSHEY_DUPLEX, 0.8,  (0, 255, 120),   2)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_placeholder.image(frame_rgb, channels="RGB", use_container_width=True)

        focus_placeholder.metric("Уровень фокуса", f"{int(focus_score)}%")
        gaze_placeholder.markdown(f"**Взгляд:** {gaze_direction}")
        blink_placeholder.metric("Моргания/мин", f"{blink_rate_per_min:.1f}")
        timer_placeholder.metric("Время сессии", f"{int(session_time)} с")
        status_placeholder.markdown(f"<h3 style='color:{color}; margin:0;'>{status}</h3>", unsafe_allow_html=True)

        if st.session_state.violations_log:
            violations_html = "".join(
                f"<div class='violation-row'>{v}</div>"
                for v in list(st.session_state.violations_log)[:10]
            )
        else:
            violations_html = "<div style='color:#888'>Нарушений нет ✅</div>"
        violations_placeholder.markdown(violations_html, unsafe_allow_html=True)

        chart_counter += 1
        if len(focus_scores) > 1 and chart_counter % 15 == 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                y=list(focus_scores), mode="lines",
                line=dict(color="#00ff9d", width=4),
                fill="tozeroy", fillcolor="rgba(0,255,157,0.1)"
            ))
            fig.update_layout(
                title="Фокус по времени", yaxis_range=[0, 100], height=280,
                template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10)
            )
            chart_placeholder.plotly_chart(fig, use_container_width=True, key=f"fc_{chart_counter}")

        time.sleep(0.03)

    cap.release()

else:
    st.info("👆 Нажми чекбокс выше, чтобы начать")

st.caption("Focus Guard • dlib + YOLOv8 + Telegram")
