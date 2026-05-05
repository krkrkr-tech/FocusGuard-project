import os
os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
os.environ["MESA_GL_VERSION_OVERRIDE"] = "3.3"

import cv2
import mediapipe as mp
import numpy as np
import streamlit as st
import time
from collections import deque
import plotly.graph_objects as go
import threading
import queue
import io
import av
from streamlit_webrtc import (
    RTCConfiguration, VideoProcessorBase, WebRtcMode, webrtc_streamer,
)

TELEGRAM_BOT_TOKEN = "8702324957:AAE45czlrbs5nt9q7uxxwgukArUpNjoZ-j0"
TELEGRAM_CHAT_ID   = "-1003964944926"
def _get_rtc_config():
    """Build RTC config using Metered TURN credentials from secrets."""
    try:
        username   = st.secrets.get("METERED_USERNAME", "") or os.getenv("METERED_USERNAME", "")
        credential = st.secrets.get("METERED_CREDENTIAL", "") or os.getenv("METERED_CREDENTIAL", "")
    except Exception:
        username, credential = "", ""

    if username and credential:
        ice_servers = [
            {"urls": ["stun:stun.relay.metered.ca:80"]},
            {"urls": ["turn:global.relay.metered.ca:80"],
             "username": username, "credential": credential},
            {"urls": ["turn:global.relay.metered.ca:80?transport=tcp"],
             "username": username, "credential": credential},
            {"urls": ["turn:global.relay.metered.ca:443"],
             "username": username, "credential": credential},
            {"urls": ["turn:global.relay.metered.ca:443?transport=tcp"],
             "username": username, "credential": credential},
        ]
    else:
        # Fallback — STUN only (works on local network)
        ice_servers = [
            {"urls": ["stun:stun.l.google.com:19302"]},
            {"urls": ["stun:stun1.l.google.com:19302"]},
        ]
    return RTCConfiguration({"iceServers": ice_servers})

# Evaluated lazily inside pages so st.secrets is available
RTC_CONFIGURATION = None  # will be set on first use

EAR_THRESHOLD       = 0.20
EAR_CONSEC_FRAMES   = 3
GAZE_THRESHOLD      = 0.12   # iris offset ratio to trigger left/right
MAX_BLINK_RATE      = 25
YOLO_MODEL          = "yolov8n.pt"
YOLO_EVERY_N_FRAMES = 5
YOLO_IMG_SIZE       = 416
YOLO_CONF           = 0.45
SUSPICIOUS_OBJECTS  = {"cell phone", "book", "remote", "laptop", "tv"}
VIOLATION_COOLDOWN  = 15.0
GAZE_GRACE_SEC      = 2.5
ABSENCE_GRACE_SEC   = 3.0

# ── MediaPipe landmark indices ─────────────────────────────────────────────────
# EAR — 6 points per eye (P1..P6 in the standard formula)
L_EAR_IDX = [33,  160, 158, 133, 153, 144]
R_EAR_IDX = [362, 385, 387, 263, 373, 380]
# Iris centers (requires refine_landmarks=True)
L_IRIS_IDX = 468
R_IRIS_IDX = 473
# Eye horizontal corners for gaze ratio
L_EYE_LEFT  = 33;  L_EYE_RIGHT  = 133
R_EYE_LEFT  = 362; R_EYE_RIGHT  = 263


def ear(lm, indices, w, h):
    """Eye aspect ratio from mediapipe normalized landmarks."""
    pts = np.array([(lm[i].x * w, lm[i].y * h) for i in indices])
    A = np.linalg.norm(pts[1] - pts[5])
    B = np.linalg.norm(pts[2] - pts[4])
    C = np.linalg.norm(pts[0] - pts[3])
    return (A + B) / (2.0 * C)


def iris_ratio(lm, iris_idx, eye_left_idx, eye_right_idx, w, h):
    """Horizontal iris position ratio within the eye (0=left, 1=right)."""
    ix = lm[iris_idx].x * w
    ex_l = lm[eye_left_idx].x * w
    ex_r = lm[eye_right_idx].x * w
    width = ex_r - ex_l
    if abs(width) < 1:
        return 0.5
    return (ix - ex_l) / width


# ── Cached resources ───────────────────────────────────────────────────────────
# FaceMesh создаётся в потоке webrtc — НЕ используем st.cache_resource
def make_face_mesh():
    try:
        # mediapipe 0.10.x — solutions API
        return mp.solutions.face_mesh.FaceMesh(
            max_num_faces=4,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    except AttributeError:
        # mediapipe 0.11+ — new API
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions
        raise RuntimeError(
            "mediapipe >= 0.11 is not supported. "
            "Pin to mediapipe==0.10.9 in requirements.txt"
        )

@st.cache_resource
def load_yolo():
    try:
        from ultralytics import YOLO
        import os
        # Pre-download model to avoid timeout during WebRTC handshake
        model = YOLO(YOLO_MODEL)
        return model
    except Exception:
        return None

# Pre-download YOLO at app startup (not inside webrtc thread)
_yolo_preload = load_yolo()

try:
    import requests as _req
except ImportError:
    _req = None

@st.cache_resource
def get_notifier():
    class _N:
        def __init__(self):
            self._q = queue.Queue(maxsize=20)
            self.total_sent = 0
            self.last_error = None
            threading.Thread(target=self._loop, daemon=True).start()
        def ok(self):
            return bool(TELEGRAM_BOT_TOKEN) and TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE" and _req is not None
        def send(self, img, cap):
            if not self.ok(): return
            try: self._q.put_nowait((img.copy(), cap))
            except queue.Full: pass
        def _loop(self):
            while True:
                img, cap = self._q.get()
                try:
                    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if not ok: continue
                    r = _req.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto",
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": cap, "parse_mode": "Markdown"},
                        files={"photo": ("v.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
                        timeout=15)
                    if r.status_code == 200: self.total_sent += 1
                    else: self.last_error = f"HTTP {r.status_code}"
                except Exception as e: self.last_error = str(e)
                finally: self._q.task_done()
    return _N()


# ── Video Processor ────────────────────────────────────────────────────────────
class FocusProcessor(VideoProcessorBase):
    def __init__(self):
        self._lock       = threading.Lock()
        self.settings    = {}
        self.face_mesh   = make_face_mesh()
        self.yolo        = load_yolo()
        self.notifier    = get_notifier()
        self.session_start   = time.time()
        self.total_blinks    = 0
        self.frame_counter   = 0
        self.last_blink_time = time.time()
        self.focus_scores    = deque(maxlen=400)
        self.yolo_cnt        = 0
        self.yolo_objects    = []
        self.violations_log  = deque(maxlen=20)
        self._vio_first      = {}
        self._vio_sent       = {}
        self._gaze_buf       = deque(maxlen=6)
        self.last = {"focus_score": 0, "gaze": "—", "blink_rate": 0.0,
                     "session_time": 0, "status": "INIT", "color": "#aaaaaa",
                     "active_violations": [], "focus_scores": []}

    def update_settings(self, s):
        with self._lock: self.settings = s.copy()

    def _vio_check(self, active):
        now = time.time()
        active_types = {v[0] for v in active}
        for t in list(self._vio_first):
            if t not in active_types: del self._vio_first[t]
        grace = {"person_absent": ABSENCE_GRACE_SEC, "gaze_away": GAZE_GRACE_SEC, "extra_face": 1.0}
        out = []
        for vtype, vtext in active:
            if vtype not in self._vio_first: self._vio_first[vtype] = now; continue
            if now - self._vio_first[vtype] < grace.get(vtype, 0.6): continue
            if now - self._vio_sent.get(vtype, 0) < VIOLATION_COOLDOWN: continue
            self._vio_sent[vtype] = now
            out.append((vtype, vtext))
        return out

    def recv(self, frame):
        img = cv2.flip(frame.to_ndarray(format="bgr24"), 1)
        h, w = img.shape[:2]
        with self._lock: settings = self.settings.copy()

        # MediaPipe работает с RGB
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        faces_count  = len(results.multi_face_landmarks) if results.multi_face_landmarks else 0
        person_absent = faces_count == 0
        gaze_cv = "No person" if person_absent else "Center"
        gaze_ui = "🚫 None"   if person_absent else "👀 Center"

        # Аннотированная копия — только для Telegram скриншотов
        ann = img.copy()

        if results.multi_face_landmarks:
            for face_lm in results.multi_face_landmarks:
                lm = face_lm.landmark

                # ── Bounding box (только в ann) ────────────────────────────
                xs = [int(l.x * w) for l in lm]
                ys = [int(l.y * h) for l in lm]
                x1, y1, x2, y2 = max(0,min(xs)-8), max(0,min(ys)-8), \
                                  min(w,max(xs)+8), min(h,max(ys)+8)
                cv2.rectangle(ann, (x1,y1), (x2,y2), (0,255,120), 2)

                # ── Точки глаз (только в ann) ──────────────────────────────
                for idx in L_EAR_IDX + R_EAR_IDX:
                    px, py = int(lm[idx].x*w), int(lm[idx].y*h)
                    cv2.circle(ann, (px,py), 2, (0,255,255), -1)

                # ── Радужки (только в ann) ─────────────────────────────────
                for iris_idx in [L_IRIS_IDX, R_IRIS_IDX]:
                    ix = int(lm[iris_idx].x * w)
                    iy = int(lm[iris_idx].y * h)
                    cv2.circle(ann, (ix,iy), 5, (255,80,80), -1)

                # ── EAR / blink ────────────────────────────────────────────
                l_ear = ear(lm, L_EAR_IDX, w, h)
                r_ear = ear(lm, R_EAR_IDX, w, h)
                avg_ear = (l_ear + r_ear) / 2.0
                if avg_ear < EAR_THRESHOLD:
                    self.frame_counter += 1
                    if (self.frame_counter >= EAR_CONSEC_FRAMES
                            and time.time() - self.last_blink_time > 0.4):
                        self.total_blinks += 1
                        self.last_blink_time = time.time()
                else:
                    self.frame_counter = 0

                # ── Gaze ───────────────────────────────────────────────────
                l_ratio = iris_ratio(lm, L_IRIS_IDX, L_EYE_LEFT, L_EYE_RIGHT, w, h)
                r_ratio = iris_ratio(lm, R_IRIS_IDX, R_EYE_LEFT, R_EYE_RIGHT, w, h)
                avg_ratio = (l_ratio + r_ratio) / 2.0
                self._gaze_buf.append(avg_ratio)
                smooth = sum(self._gaze_buf) / len(self._gaze_buf)

                if smooth < 0.5 - GAZE_THRESHOLD:
                    gaze_cv, gaze_ui = "Left",  "👈 Left"
                elif smooth > 0.5 + GAZE_THRESHOLD:
                    gaze_cv, gaze_ui = "Right", "👉 Right"
                else:
                    dev = abs(smooth - 0.5)
                    if dev > GAZE_THRESHOLD * 0.6:
                        side  = "Left" if smooth < 0.5 else "Right"
                        arrow = "👈"   if smooth < 0.5 else "👉"
                        gaze_cv, gaze_ui = f"Slight {side}", f"{arrow} Slight {side}"
                    else:
                        gaze_cv, gaze_ui = "Center", "👀 Center"
        else:
            self._gaze_buf.clear()

        # ── YOLO ───────────────────────────────────────────────────────────
        if settings.get("enable_yolo") and self.yolo:
            self.yolo_cnt += 1
            if self.yolo_cnt >= YOLO_EVERY_N_FRAMES:
                self.yolo_cnt = 0
                try:
                    res = self.yolo.predict(img, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF, verbose=False)
                    self.yolo_objects = []
                    if res and res[0].boxes is not None:
                        for box, cf, cid in zip(res[0].boxes.xyxy.cpu().numpy(),
                                                 res[0].boxes.conf.cpu().numpy(),
                                                 res[0].boxes.cls.cpu().numpy().astype(int)):
                            name = self.yolo.names.get(int(cid), str(cid))
                            if name in SUSPICIOUS_OBJECTS:
                                bx1,by1,bx2,by2 = box.astype(int)
                                self.yolo_objects.append({"class":name,"conf":float(cf),
                                                          "box":(int(bx1),int(by1),int(bx2),int(by2))})
                except Exception: pass
            for obj in self.yolo_objects:
                bx1,by1,bx2,by2 = obj["box"]
                cv2.rectangle(img,(bx1,by1),(bx2,by2),(0,0,255),2)
                cv2.putText(img,f"{obj['class']} {obj['conf']:.2f}",(bx1+2,by1-6),
                            cv2.FONT_HERSHEY_SIMPLEX,0.55,(255,255,255),2)

        # ── Score ──────────────────────────────────────────────────────────
        session_time = max(1, time.time() - self.session_start)
        blink_rate   = (self.total_blinks / session_time) * 60
        score = max(15, min(100,
            92 - (77 if person_absent else 0)
               - (35 if not person_absent and gaze_cv not in ("Center",) else 0)
               - max(0, (blink_rate - MAX_BLINK_RATE) * 0.8)
               - (40 if faces_count > 1 else 0)
               - len(self.yolo_objects) * 25))
        self.focus_scores.append(score)

        # ── Violations ─────────────────────────────────────────────────────
        active = []
        if settings.get("track_absence") and person_absent:
            active.append(("person_absent", "🚫 Person absent"))
        if settings.get("track_gaze") and not person_absent and gaze_cv not in ("Center",):
            active.append(("gaze_away", gaze_ui))
        if settings.get("track_extra") and faces_count > 1:
            active.append(("extra_face", f"👥 {faces_count} faces detected"))
        for obj in self.yolo_objects:
            cls = obj["class"]
            if settings.get("track_phone") and cls in ("cell phone","remote"):
                active.append(("phone", f"📱 Phone detected ({obj['conf']:.2f})"))
            elif settings.get("track_book") and cls == "book":
                active.append(("book", f"📚 Book detected ({obj['conf']:.2f})"))
            elif settings.get("track_objects") and cls in ("laptop","tv"):
                active.append((cls, f"💻 {cls.capitalize()} detected ({obj['conf']:.2f})"))

        for _, vtext in self._vio_check(active):
            ts = time.strftime("%H:%M:%S")
            self.violations_log.appendleft(f"[{ts}] {vtext}")
            if settings.get("enable_telegram"):
                self.notifier.send(ann,
                    f"🚨 *Violation*\n👤 {settings.get('student_name','?')}\n"
                    f"⏰ {ts}\n📋 {vtext}\n📉 Focus: {int(score)}%")

        # ── Status ─────────────────────────────────────────────────────────
        if person_absent:
            status, color = "🔴 No person",  "#ff4444"
            cv2.rectangle(ann,(0,0),(w,h),(0,0,200),4)
        elif active:
            status, color = "🔴 Violation",  "#ff4444"
            cv2.rectangle(ann,(0,0),(w,h),(0,0,200),4)
        elif score > 78: status, color = "🟢 Focused",     "#00ff9d"
        elif score > 55: status, color = "🟡 Drifting",    "#ffcc00"
        else:            status, color = "🔴 Not focused", "#ff4444"

        # Аннотации на ann для Telegram
        font = cv2.FONT_HERSHEY_SIMPLEX
        score_col = (80,255,140) if score > 78 else ((0,200,255) if score > 55 else (80,80,255))
        def put_ann(text, y, col):
            cv2.putText(ann, text, (12,y), font, 0.48, (0,0,0), 3, cv2.LINE_AA)
            cv2.putText(ann, text, (12,y), font, 0.48, col,     1, cv2.LINE_AA)
        put_ann(f"Focus {int(score)}%", 24, score_col)
        put_ann(f"Gaze  {gaze_cv}",     44, (220,220,220))
        put_ann(f"Faces {faces_count}", 64, (220,220,220))

        # Минимальный оверлей на чистом кадре — только фокус
        def put(text, y, col):
            cv2.putText(img, text, (12,y), font, 0.48, (0,0,0), 3, cv2.LINE_AA)
            cv2.putText(img, text, (12,y), font, 0.48, col,     1, cv2.LINE_AA)
        put(f"Focus {int(score)}%", 24, score_col)
        put(f"Gaze  {gaze_cv}",     44, (220,220,220))
        put(f"Faces {faces_count}", 64, (220,220,220))

        with self._lock:
            self.last = {"focus_score": score, "gaze": gaze_ui, "blink_rate": blink_rate,
                         "session_time": session_time, "status": status, "color": color,
                         "active_violations": [t for _,t in active],
                         "focus_scores": list(self.focus_scores)}
        return av.VideoFrame.from_ndarray(img, format="bgr24")


# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE  (in-memory, survives rerenders via cache_resource)
# ══════════════════════════════════════════════════════════════════════════════
import hashlib, uuid

def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

@st.cache_resource
def get_db():
    """Shared in-memory DB. Returns dict with users and exams."""
    return {
        "users": {
            # username -> {name, password_hash, role}
            "admin":   {"name": "Administrator", "password": _hash("admin"),   "role": "admin"},
            "teacher": {"name": "Teacher",        "password": _hash("teacher"), "role": "teacher"},
            "student": {"name": "Student",        "password": _hash("student"), "role": "student"},
        },
        "exams": {
            # exam_id -> {title, teacher, student, created_at, status, result}
            # status: pending | active | submitted
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  STYLES  (shared across all pages)
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Focus Guard", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e1117; }
[data-testid="stMetric"] {
    background: #1c2333; border-radius: 10px;
    padding: 12px 16px; border: 1px solid #2a3550;
}
.vrow {
    background: #1f1318; border-left: 3px solid #ff4444;
    border-radius: 0 6px 6px 0; padding: 7px 12px;
    margin: 4px 0; color: #ffaaaa; font-size: 0.88rem;
}
.exam-card {
    background: #1c2333; border-radius: 10px;
    padding: 16px 20px; border: 1px solid #2a3550; margin-bottom: 10px;
}
.badge-pending  { background:#2a2000; color:#ffd60a; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.badge-active   { background:#002a0a; color:#00ff9d; border-radius:4px; padding:2px 8px; font-size:.78rem; }
.badge-submitted{ background:#00152a; color:#00b4ff; border-radius:4px; padding:2px 8px; font-size:.78rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
def login_page():
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🧠 Focus Guard")
        st.caption("AI Proctoring System · Please sign in")
        st.divider()
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Sign in", use_container_width=True, type="primary"):
            db = get_db()
            u = db["users"].get(username)
            if u and u["password"] == _hash(password):
                st.session_state.update({
                    "authenticated": True,
                    "username": username,
                    "display_name": u["name"],
                    "role": u["role"],
                })
                st.rerun()
            else:
                st.error("Invalid username or password")

if not st.session_state.get("authenticated"):
    login_page()
    st.stop()

# ── Shared sidebar header ──────────────────────────────────────────────────────
role    = st.session_state.get("role", "")
uname   = st.session_state.get("username", "")
display = st.session_state.get("display_name", "")
ROLE_ICON = {"admin": "🛡️", "teacher": "👨‍🏫", "student": "🎓"}

with st.sidebar:
    st.markdown(f"### {ROLE_ICON.get(role,'👤')} {display}")
    st.caption(f"Role: **{role}** · `{uname}`")
    if st.button("🚪 Sign out", use_container_width=True):
        st.session_state.clear(); st.rerun()
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PAGE
# ══════════════════════════════════════════════════════════════════════════════
def admin_page():
    db = get_db()
    st.title("🛡️ Admin Panel")
    st.caption("Manage users and monitor the system")
    st.divider()

    tab_users, tab_exams = st.tabs(["👥 Users", "📋 All Exams"])

    # ── Users tab ─────────────────────────────────────────────────────────────
    with tab_users:
        st.subheader("Current users")
        for un, info in list(db["users"].items()):
            c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1])
            c1.markdown(f"**{info['name']}**")
            c2.markdown(f"`{un}`")
            c3.markdown(f"{ROLE_ICON.get(info['role'],'')} {info['role']}")
            if un != "admin":
                if c4.button("🗑️", key=f"del_{un}"):
                    del db["users"][un]
                    st.rerun()

        st.divider()
        st.subheader("➕ Add new user")
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1.5])
        new_name  = c1.text_input("Full name",  key="nu_name")
        new_user  = c2.text_input("Username",   key="nu_user")
        new_pass  = c3.text_input("Password",   key="nu_pass", type="password")
        new_role  = c4.selectbox("Role",        ["teacher", "student"], key="nu_role")
        if st.button("Add user", type="primary"):
            if new_user and new_pass and new_name:
                if new_user in db["users"]:
                    st.error("Username already exists")
                else:
                    db["users"][new_user] = {
                        "name": new_name, "password": _hash(new_pass), "role": new_role
                    }
                    st.success(f"User **{new_user}** created")
                    st.rerun()
            else:
                st.warning("Fill in all fields")

    # ── Exams tab ─────────────────────────────────────────────────────────────
    with tab_exams:
        if not db["exams"]:
            st.info("No exams yet")
        else:
            for eid, ex in db["exams"].items():
                badge_cls = f"badge-{ex['status']}"
                with st.container():
                    st.markdown(f"""<div class="exam-card">
                        <b>{ex['title']}</b> &nbsp;
                        <span class="{badge_cls}">{ex['status'].upper()}</span><br>
                        <small>Teacher: {ex['teacher']} &nbsp;·&nbsp; Student: {ex['student']}
                        &nbsp;·&nbsp; Created: {ex['created_at']}</small>
                    </div>""", unsafe_allow_html=True)
                    if ex["status"] == "submitted" and ex.get("result"):
                        r = ex["result"]
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Avg Focus",    f"{r['avg_focus']:.0f}%")
                        m2.metric("Blinks/min",   f"{r['blink_rate']:.1f}")
                        m3.metric("Violations",   r['violations'])


# ══════════════════════════════════════════════════════════════════════════════
#  TEACHER PAGE
# ══════════════════════════════════════════════════════════════════════════════
def teacher_page():
    db = get_db()
    st.title("👨‍🏫 Teacher Panel")
    st.divider()

    tab_create, tab_results = st.tabs(["➕ Create Exam", "📊 Results"])

    # ── Create exam ───────────────────────────────────────────────────────────
    with tab_create:
        st.subheader("Create new exam session")

        students = {u: info["name"] for u, info in db["users"].items()
                    if info["role"] == "student"}
        if not students:
            st.warning("No students registered yet. Ask admin to add students.")
        else:
            title      = st.text_input("Exam title", placeholder="e.g. Midterm Exam — Math")
            student_un = st.selectbox("Assign to student",
                                      options=list(students.keys()),
                                      format_func=lambda u: f"{students[u]} ({u})")
            enable_tg  = st.checkbox("📨 Send violations to Telegram", value=True)

            if st.button("📋 Create exam", type="primary", use_container_width=True):
                if not title:
                    st.warning("Enter exam title")
                else:
                    eid = str(uuid.uuid4())[:8]
                    db["exams"][eid] = {
                        "title":      title,
                        "teacher":    uname,
                        "student":    student_un,
                        "created_at": time.strftime("%Y-%m-%d %H:%M"),
                        "status":     "pending",
                        "telegram":   enable_tg,
                        "result":     None,
                    }
                    st.success(f"✅ Exam **{title}** created for **{students[student_un]}**")
                    st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    with tab_results:
        my_exams = {eid: ex for eid, ex in db["exams"].items()
                    if ex["teacher"] == uname}
        if not my_exams:
            st.info("You haven't created any exams yet")
        else:
            for eid, ex in my_exams.items():
                badge_cls = f"badge-{ex['status']}"
                st.markdown(f"""<div class="exam-card">
                    <b>{ex['title']}</b> &nbsp;
                    <span class="{badge_cls}">{ex['status'].upper()}</span><br>
                    <small>Student: <b>{ex['student']}</b>
                    &nbsp;·&nbsp; {ex['created_at']}</small>
                </div>""", unsafe_allow_html=True)

                if ex["status"] == "submitted" and ex.get("result"):
                    r = ex["result"]
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Avg Focus",    f"{r['avg_focus']:.0f}%")
                    m2.metric("Min Focus",    f"{r['min_focus']:.0f}%")
                    m3.metric("Blinks/min",   f"{r['blink_rate']:.1f}")
                    m4.metric("Violations",   r['violations'])

                    if r.get("focus_scores"):
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            y=r["focus_scores"], mode="lines",
                            line=dict(color="#00ff9d", width=2),
                            fill="tozeroy", fillcolor="rgba(0,255,157,0.08)"))
                        fig.update_layout(
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            height=160, showlegend=False,
                            margin=dict(l=0,r=0,t=4,b=0),
                            yaxis=dict(range=[0,100], ticksuffix="%",
                                       gridcolor="rgba(255,255,255,0.05)",
                                       tickfont=dict(color="#aaa")),
                            xaxis=dict(showgrid=False, showticklabels=False),
                        )
                        st.plotly_chart(fig, use_container_width=True,
                                        key=f"r_{eid}")
                    st.divider()

                elif ex["status"] == "pending":
                    st.caption("⏳ Waiting for student to start")
                elif ex["status"] == "active":
                    st.caption("🟢 Exam in progress...")


# ══════════════════════════════════════════════════════════════════════════════
#  STUDENT PAGE
# ══════════════════════════════════════════════════════════════════════════════
def student_page():
    db = get_db()

    # Ищем активный или pending экзамен для этого студента
    my_exams = {eid: ex for eid, ex in db["exams"].items()
                if ex["student"] == uname and ex["status"] in ("pending", "active")}

    st.title("🎓 Student Panel")
    st.divider()

    if not my_exams:
        st.info("📭 No active exams assigned to you. Wait for your teacher to create one.")
        submitted = {eid: ex for eid, ex in db["exams"].items()
                     if ex["student"] == uname and ex["status"] == "submitted"}
        if submitted:
            st.subheader("✅ Completed exams")
            for eid, ex in submitted.items():
                st.markdown(f"""<div class="exam-card">
                    <b>{ex['title']}</b> &nbsp;
                    <span class="badge-submitted">SUBMITTED</span><br>
                    <small>Teacher: {ex['teacher']} &nbsp;·&nbsp; {ex['created_at']}</small>
                </div>""", unsafe_allow_html=True)
        return

    # Берём первый доступный экзамен
    eid, exam = next(iter(my_exams.items()))

    st.subheader(f"📋 {exam['title']}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Teacher",    exam["teacher"])
    c2.metric("Started",    exam["created_at"])
    c3.metric("Status",     exam["status"].upper())
    st.divider()

    # Отмечаем как active при первом открытии
    if exam["status"] == "pending":
        db["exams"][eid]["status"] = "active"
        st.rerun()

    # ── Мониторинг ────────────────────────────────────────────────────────────
    settings = dict(
        student_name=display,
        enable_telegram=exam.get("telegram", True),
        enable_yolo=True,
        track_absence=True, track_gaze=True, track_extra=True,
        track_phone=True,   track_book=True, track_objects=True,
    )

    col_cam, col_side = st.columns([2.2, 1])

    with col_cam:
        st.subheader("🎥 Camera")
        ctx = webrtc_streamer(
            key=f"student_{eid}",
            mode=WebRtcMode.SENDRECV,
            rtc_configuration=_get_rtc_config(),
            media_stream_constraints={"video": True, "audio": False},
            video_processor_factory=FocusProcessor,
            async_processing=True,
        )
        st.divider()
        chart_ph = st.empty()

    with col_side:
        st.subheader("📊 Metrics")
        c1, c2 = st.columns(2)
        ph_focus = c1.empty()
        ph_time  = c2.empty()
        c3, c4 = st.columns(2)
        ph_blink = c3.empty()
        ph_gaze  = c4.empty()
        st.divider()
        ph_status = st.empty()
        st.divider()
        st.subheader("🚨 Violations")
        ph_viol = st.empty()

        st.divider()
        st.warning("⚠️ Do not close this tab until you submit!")
        if st.button("✅ Submit exam", type="primary", use_container_width=True):
            # Сохраняем результат
            if ctx.video_processor:
                with ctx.video_processor._lock:
                    d_final = ctx.video_processor.last.copy()
                    vlog    = list(ctx.video_processor.violations_log)
                fs = d_final["focus_scores"]
                db["exams"][eid]["result"] = {
                    "avg_focus":   sum(fs)/len(fs) if fs else 0,
                    "min_focus":   min(fs) if fs else 0,
                    "blink_rate":  d_final["blink_rate"],
                    "violations":  len(vlog),
                    "focus_scores": fs[-100:],
                    "submitted_at": time.strftime("%H:%M:%S"),
                }
            else:
                db["exams"][eid]["result"] = {
                    "avg_focus": 0, "min_focus": 0,
                    "blink_rate": 0, "violations": 0,
                    "focus_scores": [], "submitted_at": time.strftime("%H:%M:%S"),
                }
            db["exams"][eid]["status"] = "submitted"
            st.success("✅ Exam submitted successfully!")
            st.rerun()

    if ctx.video_processor:
        ctx.video_processor.update_settings(settings)

    if ctx.video_processor:
        with ctx.video_processor._lock:
            d    = ctx.video_processor.last.copy()
            vlog = list(ctx.video_processor.violations_log)

        ph_focus.metric("🎯 Focus",      f"{int(d['focus_score'])}%")
        ph_time.metric( "⏱ Session",    f"{int(d['session_time'])} s")
        ph_blink.metric("👁 Blinks/min", f"{d['blink_rate']:.1f}")
        ph_gaze.metric( "👀 Gaze",       d["gaze"])
        ph_status.markdown(
            f"<h3 style='color:{d['color']};margin:0'>{d['status']}</h3>",
            unsafe_allow_html=True)

        if vlog:
            ph_viol.markdown("".join(f'<div class="vrow">{v}</div>' for v in vlog[:8]),
                             unsafe_allow_html=True)
        elif d["active_violations"]:
            ph_viol.markdown("".join(f'<div class="vrow">{v}</div>' for v in d["active_violations"][:8]),
                             unsafe_allow_html=True)
        else:
            ph_viol.success("No violations ✅")

        fs = d["focus_scores"]
        if len(fs) > 2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                y=fs, mode="lines",
                line=dict(color="#00ff9d", width=2.5),
                fill="tozeroy", fillcolor="rgba(0,255,157,0.08)"))
            fig.add_hline(y=78, line_color="rgba(0,255,157,0.3)", line_dash="dot")
            fig.add_hline(y=55, line_color="rgba(255,204,0,0.3)",  line_dash="dot")
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=200, showlegend=False,
                margin=dict(l=0,r=0,t=8,b=0),
                yaxis=dict(range=[0,100], ticksuffix="%",
                           gridcolor="rgba(255,255,255,0.05)",
                           tickfont=dict(color="#aaa")),
                xaxis=dict(showgrid=False, showticklabels=False),
            )
            chart_ph.plotly_chart(fig, use_container_width=True,
                                  key=f"sc_{int(time.time()*4)}")
    else:
        ph_focus.metric("🎯 Focus",      "—")
        ph_time.metric( "⏱ Session",    "—")
        ph_blink.metric("👁 Blinks/min","—")
        ph_gaze.metric( "👀 Gaze",      "—")
        ph_status.markdown("<h3 style='color:#555;margin:0'>⏸ Start camera</h3>",
                           unsafe_allow_html=True)
        ph_viol.info("Allow camera access to begin")

    if ctx.state.playing:
        time.sleep(0.2)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════════════════
if role == "admin":
    admin_page()
elif role == "teacher":
    teacher_page()
elif role == "student":
    student_page()
else:
    st.error("Unknown role")

st.caption("Focus Guard · MediaPipe FaceMesh + YOLOv8 + Telegram")
