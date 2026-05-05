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

# Tokens — read from secrets if available, otherwise use hardcoded value
def _get_secret(key, default=""):
    try:
        return st.secrets.get(key, default) or default
    except Exception:
        return os.getenv(key, default)

TELEGRAM_BOT_TOKEN = _get_secret("TELEGRAM_BOT_TOKEN", "8702324957:AAE45czlrbs5nt9q7uxxwgukArUpNjoZ-j0")
TELEGRAM_CHAT_ID   = _get_secret("TELEGRAM_CHAT_ID",   "-1003964944926")
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
YOLO_EVERY_N_FRAMES = 15   # less frequent = less CPU
YOLO_IMG_SIZE       = 224   # smaller = faster
YOLO_CONF           = 0.50
SUSPICIOUS_OBJECTS  = {"cell phone", "book", "remote", "laptop", "tv"}
VIOLATION_COOLDOWN  = 8.0
GAZE_GRACE_SEC      = 1.5
ABSENCE_GRACE_SEC   = 2.0

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
            tok = TELEGRAM_BOT_TOKEN
            return bool(tok) and tok not in ("YOUR_BOT_TOKEN_HERE", "") and _req is not None
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
                        data={"chat_id": TELEGRAM_CHAT_ID, "caption": cap},
                        files={"photo": ("v.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
                        timeout=15)
                    if r.status_code == 200: self.total_sent += 1
                    else: self.last_error = f"HTTP {r.status_code}"
                except Exception as e:
                    self.last_error = f"Photo send failed: {e}"
                    # Try text-only as fallback
                    try:
                        _req.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            data={"chat_id": TELEGRAM_CHAT_ID, "text": cap},
                            timeout=10)
                    except Exception:
                        pass
                finally:
                    self._q.task_done()
    return _N()


# ── Video Processor ────────────────────────────────────────────────────────────
class FocusProcessor(VideoProcessorBase):
    def __init__(self):
        self._lock       = threading.Lock()
        self.settings    = {
            "track_absence": True, "track_gaze": True, "track_extra": True,
            "track_phone":   True, "track_book":  True, "track_objects": True,
            "enable_yolo":   True, "enable_telegram": True,
            "student_name":  "Student",
        }
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
                     "active_violations": [], "focus_scores": [],
                     "gaze_cv": "", "yolo_objects": []}

        # Background processing thread — recv() stays non-blocking
        self._frame_queue = queue.Queue(maxsize=1)
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self):
        """Heavy processing in background — MediaPipe + YOLO + score calc."""
        while True:
            try:
                img = self._frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._run_analysis(img)
            except Exception as e:
                # Store error so we can debug
                with self._lock:
                    self.last["_last_error"] = str(e)

    def _run_analysis(self, img):
        h, w = img.shape[:2]
        with self._lock: settings = self.settings.copy()

        scale = min(1.0, 480 / max(h, w))
        proc  = cv2.resize(img, (int(w*scale), int(h*scale))) if scale < 1.0 else img
        ph, pw = proc.shape[:2]

        rgb     = cv2.cvtColor(proc, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        faces_count   = len(results.multi_face_landmarks) if results.multi_face_landmarks else 0
        person_absent = faces_count == 0
        gaze_cv, gaze_ui = ("No person", "🚫 None") if person_absent else ("Center", "👀 Center")

        if results.multi_face_landmarks:
            for face_lm in results.multi_face_landmarks:
                lm = face_lm.landmark
                avg_ear = (ear(lm, L_EAR_IDX, pw, ph) + ear(lm, R_EAR_IDX, pw, ph)) / 2.0
                if avg_ear < EAR_THRESHOLD:
                    self.frame_counter += 1
                    if self.frame_counter >= EAR_CONSEC_FRAMES and time.time() - self.last_blink_time > 0.4:
                        self.total_blinks   += 1
                        self.last_blink_time = time.time()
                else:
                    self.frame_counter = 0

                lr = iris_ratio(lm, L_IRIS_IDX, L_EYE_LEFT, L_EYE_RIGHT, pw, ph)
                rr = iris_ratio(lm, R_IRIS_IDX, R_EYE_LEFT, R_EYE_RIGHT, pw, ph)
                self._gaze_buf.append((lr + rr) / 2.0)
                smooth = sum(self._gaze_buf) / len(self._gaze_buf)
                if smooth < 0.5 - GAZE_THRESHOLD:
                    gaze_cv, gaze_ui = "Left",  "👈 Left"
                elif smooth > 0.5 + GAZE_THRESHOLD:
                    gaze_cv, gaze_ui = "Right", "👉 Right"
                else:
                    dev = abs(smooth - 0.5)
                    if dev > GAZE_THRESHOLD * 0.6:
                        side = "Left" if smooth < 0.5 else "Right"
                        icon = "👈"   if smooth < 0.5 else "👉"
                        gaze_cv, gaze_ui = f"Slight {side}", f"{icon} Slight {side}"
                    else:
                        gaze_cv, gaze_ui = "Center", "👀 Center"
        else:
            self._gaze_buf.clear()

        yolo_objects = []
        if settings.get("enable_yolo") and self.yolo:
            self.yolo_cnt += 1
            if self.yolo_cnt >= YOLO_EVERY_N_FRAMES:
                self.yolo_cnt = 0
                try:
                    res = self.yolo.predict(proc, imgsz=YOLO_IMG_SIZE, conf=YOLO_CONF, verbose=False)
                    if res and res[0].boxes is not None:
                        for box, cf, cid in zip(res[0].boxes.xyxy.cpu().numpy(),
                                                 res[0].boxes.conf.cpu().numpy(),
                                                 res[0].boxes.cls.cpu().numpy().astype(int)):
                            name = self.yolo.names.get(int(cid), str(cid))
                            if name in SUSPICIOUS_OBJECTS:
                                bx1,by1,bx2,by2 = box.astype(int)
                                if scale < 1.0:
                                    bx1,by1,bx2,by2 = int(bx1/scale),int(by1/scale),int(bx2/scale),int(by2/scale)
                                yolo_objects.append({"class":name,"conf":float(cf),"box":(bx1,by1,bx2,by2)})
                except Exception:
                    pass
            else:
                with self._lock:
                    yolo_objects = self.last.get("yolo_objects", [])

        session_time = max(1, time.time() - self.session_start)
        blink_rate   = (self.total_blinks / session_time) * 60
        score = max(15, min(100,
            92 - (77 if person_absent else 0)
               - (35 if gaze_cv not in ("Center",) and not person_absent else 0)
               - max(0, (blink_rate - MAX_BLINK_RATE) * 0.8)
               - (40 if faces_count > 1 else 0)
               - len(yolo_objects) * 25))
        self.focus_scores.append(score)

        active = []
        if settings.get("track_absence") and person_absent:
            active.append(("person_absent", "🚫 Person absent"))
        if settings.get("track_gaze") and not person_absent and gaze_cv not in ("Center", ""):
            active.append(("gaze_away", gaze_ui))
        if settings.get("track_extra") and faces_count > 1:
            active.append(("extra_face", f"👥 {faces_count} faces"))
        for obj in yolo_objects:
            cls = obj["class"]
            if settings.get("track_phone") and cls in ("cell phone","remote"):
                active.append(("phone", f"📱 Phone ({obj['conf']:.2f})"))
            elif settings.get("track_book") and cls == "book":
                active.append(("book", f"📚 Book ({obj['conf']:.2f})"))
            elif settings.get("track_objects") and cls in ("laptop","tv"):
                active.append((cls, f"💻 {cls.capitalize()} ({obj['conf']:.2f})"))

        # ── Violation logging + Telegram ──────────────────────────────────────
        ann = img.copy()
        confirmed = self._vio_check(active)

        for _, vtext in confirmed:
            ts = time.strftime("%H:%M:%S")
            log_entry = f"[{ts}] {vtext}"
            self.violations_log.appendleft(log_entry)

            # Telegram
            if settings.get("enable_telegram", True) and self.notifier.ok():
                caption = (
    f"🚨 Violation Detected\n"
    f"👤 Student: {settings.get('student_name', 'Unknown')}\n"
    f"⏰ Time: {ts}\n"
    f"📋 Type: {vtext}\n"
    f"📉 Focus: {int(score)}%"
)
                self.notifier.send(ann, caption)

        if person_absent:   status, color = "🔴 No person",  "#ff4444"
        elif active:        status, color = "🔴 Violation",  "#ff4444"
        elif score > 78:    status, color = "🟢 Focused",    "#00ff9d"
        elif score > 55:    status, color = "🟡 Drifting",   "#ffcc00"
        else:               status, color = "🔴 Not focused","#ff4444"

        with self._lock:
            self.last = {
                "focus_score": score, "gaze": gaze_ui, "gaze_cv": gaze_cv,
                "blink_rate": blink_rate, "session_time": session_time,
                "status": status, "color": color,
                "active_violations": [t for _,t in active],
                "focus_scores": list(self.focus_scores),
                "yolo_objects": yolo_objects,
            }

    def update_settings(self, s):
        with self._lock: self.settings = s.copy()

    def _vio_check(self, active):
        """
        Returns violations ready to LOG and SEND to Telegram.
        - First seen: start grace period timer
        - After grace period: add to log (once per VIOLATION_COOLDOWN)
        - Telegram: same cooldown
        """
        now = time.time()
        active_types = {v[0] for v in active}

        # Clear timers for violations no longer active
        for t in list(self._vio_first):
            if t not in active_types:
                del self._vio_first[t]

        confirmed = []
        for vtype, vtext in active:
            # Start timer on first occurrence
            if vtype not in self._vio_first:
                self._vio_first[vtype] = now
                continue

            grace = {
                "person_absent": ABSENCE_GRACE_SEC,
                "gaze_away":     GAZE_GRACE_SEC,
                "extra_face":    1.0,
            }.get(vtype, 0.5)

            # Not enough time passed yet
            if now - self._vio_first[vtype] < grace:
                continue

            # Already logged recently (cooldown)
            if now - self._vio_sent.get(vtype, 0) < VIOLATION_COOLDOWN:
                continue

            self._vio_sent[vtype] = now
            confirmed.append((vtype, vtext))

        return confirmed

    def recv(self, frame):
        """Non-blocking recv — push frame to worker, draw last known overlay."""
        img = cv2.flip(frame.to_ndarray(format="bgr24"), 1)

        # Send to background thread (drop if busy — keeps video smooth)
        try:
            self._frame_queue.put_nowait(img.copy())
        except queue.Full:
            pass

        # Read last known results instantly
        with self._lock:
            d = self.last.copy()

        score   = int(d["focus_score"])
        gaze_cv = d.get("gaze_cv", "")
        col     = (80,255,140) if score > 78 else ((0,200,255) if score > 55 else (80,80,255))
        font    = cv2.FONT_HERSHEY_SIMPLEX

        # Draw YOLO boxes
        for obj in d.get("yolo_objects", []):
            x1,y1,x2,y2 = obj["box"]
            cv2.rectangle(img,(x1,y1),(x2,y2),(0,0,255),2)
            cv2.putText(img,f"{obj['class']} {obj['conf']:.2f}",(x1+2,y1-6),
                        font,0.5,(255,255,255),1)

        # Minimal text overlay
        def put(txt, y, c):
            cv2.putText(img, txt, (12,y), font, 0.48, (0,0,0), 3, cv2.LINE_AA)
            cv2.putText(img, txt, (12,y), font, 0.48, c,       1, cv2.LINE_AA)

        put(f"Focus {score}%", 24, col)
        put(f"Gaze  {gaze_cv}", 44, (220,220,220))

        return av.VideoFrame.from_ndarray(img, format="bgr24")

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE  (JSON-file backed — persists across rerenders and reboots)
# ══════════════════════════════════════════════════════════════════════════════
import hashlib, uuid, json
from pathlib import Path

DB_PATH = Path("/tmp/focus_guard_db.json")

def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def _default_db() -> dict:
    return {
        "users": {
            "admin":   {"name": "Administrator", "password": _hash("admin"),   "role": "admin"},
            "teacher": {"name": "Teacher",        "password": _hash("teacher"), "role": "teacher"},
            "student": {"name": "Student",        "password": _hash("student"), "role": "student"},
        },
        "exams": {},
    }

def _load_db() -> dict:
    try:
        if DB_PATH.exists():
            data = json.loads(DB_PATH.read_text())
            # Merge: keep default users if db is empty
            if not data.get("users"):
                data["users"] = _default_db()["users"]
            if "exams" not in data:
                data["exams"] = {}
            return data
    except Exception:
        pass
    return _default_db()

def save_db(db: dict):
    """Call after every write operation."""
    try:
        DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2))
    except Exception:
        pass

@st.cache_resource
def get_db() -> dict:
    """Load once, shared across all sessions. Backed by JSON file."""
    return _load_db()


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
                    save_db(db)
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
                    save_db(db)
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
        students = {u: info["name"] for u, info in db["users"].items()
                    if info["role"] == "student"}
        if not students:
            st.warning("No students registered yet. Ask admin to add students.")
        else:
            st.subheader("Exam settings")
            c1, c2, c3 = st.columns(3)
            title      = c1.text_input("Exam title", placeholder="e.g. Midterm — Math")
            duration   = c2.number_input("Duration (minutes)", min_value=5,
                                         max_value=180, value=30, step=5)
            student_un = st.selectbox("Assign to student",
                                      options=list(students.keys()),
                                      format_func=lambda u: f"{students[u]} ({u})")

            # Deadline
            dl_col1, dl_col2 = st.columns(2)
            use_deadline = dl_col1.checkbox("📅 Set deadline")
            deadline_str = None
            if use_deadline:
                import datetime
                dl_date = dl_col1.date_input("Deadline date",
                                             value=datetime.date.today() + datetime.timedelta(days=1))
                dl_time = dl_col2.time_input("Deadline time",
                                             value=datetime.time(23, 59))
                deadline_str = f"{dl_date} {dl_time.strftime('%H:%M')}"

            enable_tg  = st.checkbox("📨 Send violations to Telegram", value=True)

            # ── Questions builder ──────────────────────────────────────────
            st.divider()
            st.subheader("📝 Test questions")
            st.caption("Add multiple-choice questions for the student to answer during the exam.")

            q_key = f"draft_questions_{uname}"
            if q_key not in st.session_state:
                st.session_state[q_key] = []

            # Show existing questions
            for i, q in enumerate(st.session_state[q_key]):
                with st.expander(f"Q{i+1}. {q['text'][:60]}...", expanded=False):
                    st.markdown(f"**{q['text']}**")
                    for j, opt in enumerate(q["options"]):
                        mark = "✅" if j == q["answer"] else f"{chr(65+j)}."
                        st.markdown(f"{mark} {opt}")
                    if st.button("🗑 Remove", key=f"rmq_{i}"):
                        st.session_state[q_key].pop(i)
                        st.rerun()

            # Add new question form
            with st.expander("➕ Add question", expanded=len(st.session_state[q_key]) == 0):
                q_text = st.text_area("Question text", key="nq_text", height=80)
                cols   = st.columns(2)
                opt_a  = cols[0].text_input("Option A", key="nq_a")
                opt_b  = cols[1].text_input("Option B", key="nq_b")
                opt_c  = cols[0].text_input("Option C", key="nq_c")
                opt_d  = cols[1].text_input("Option D", key="nq_d")
                correct = st.selectbox("Correct answer", ["A","B","C","D"], key="nq_ans")
                ans_map = {"A":0,"B":1,"C":2,"D":3}

                if st.button("Add question", type="secondary"):
                    opts = [opt_a, opt_b, opt_c, opt_d]
                    if q_text and all(opts):
                        st.session_state[q_key].append({
                            "text":    q_text,
                            "options": opts,
                            "answer":  ans_map[correct],
                        })
                        st.rerun()
                    else:
                        st.warning("Fill in the question and all 4 options")

            st.divider()
            n_q = len(st.session_state[q_key])
            st.caption(f"{n_q} question{'s' if n_q != 1 else ''} added")

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
                        "duration":   int(duration),
                        "deadline":   deadline_str,
                        "questions":  list(st.session_state[q_key]),
                        "result":     None,
                    }
                    save_db(db)
                    st.session_state[q_key] = []
                    dl_info = f" · deadline {deadline_str}" if deadline_str else ""
                    st.success(f"✅ **{title}** — {int(duration)} min — {n_q} questions{dl_info}")
                    st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    with tab_results:
        # Always reload from file so submitted results appear immediately
        fresh = _load_db()
        db.update(fresh)

        col_r1, col_r2 = st.columns([4,1])
        col_r1.markdown("### 📊 Exam Results")
        if col_r2.button("🔄 Refresh", use_container_width=True):
            st.rerun()

        my_exams = {eid: ex for eid, ex in db["exams"].items()
                    if ex["teacher"] == uname}
        if not my_exams:
            st.info("You haven't created any exams yet")
        else:
            for eid, ex in my_exams.items():
                badge_cls = f"badge-{ex['status']}"
                n_q = len(ex.get("questions", []))
                dl  = f" · ⏰ Deadline: {ex['deadline']}" if ex.get("deadline") else ""
                st.markdown(f"""<div class="exam-card">
                    <b>{ex['title']}</b> &nbsp;
                    <span class="{badge_cls}">{ex['status'].upper()}</span><br>
                    <small>Student: <b>{ex['student']}</b> ·
                    {ex.get('duration', '?')} min · {n_q} questions ·
                    {ex['created_at']}{dl}</small>
                </div>""", unsafe_allow_html=True)

                if ex["status"] == "submitted" and ex.get("result"):
                    r = ex["result"]
                    # Score
                    q_score = ""
                    if r.get("answers") and ex.get("questions"):
                        correct = sum(
                            1 for i,q in enumerate(ex["questions"])
                            if r["answers"].get(str(i)) == q["answer"]
                        )
                        total = len(ex["questions"])
                        q_score = f"  ·  Test: {correct}/{total}"

                    m1,m2,m3,m4,m5 = st.columns(5)
                    m1.metric("Avg Focus",  f"{r['avg_focus']:.0f}%")
                    m2.metric("Min Focus",  f"{r['min_focus']:.0f}%")
                    m3.metric("Blinks/min", f"{r['blink_rate']:.1f}")
                    m4.metric("Violations", r["violations"])
                    if r.get("answers") and ex.get("questions"):
                        correct = sum(1 for i,q in enumerate(ex["questions"])
                                      if r["answers"].get(str(i)) == q["answer"])
                        m5.metric("Test score", f"{correct}/{len(ex['questions'])}")

                    # Show answers
                    if ex.get("questions"):
                        qs = ex["questions"]
                        answers = r.get("answers", {})
                        correct_count = sum(
                            1 for i,q in enumerate(qs)
                            if answers.get(str(i)) == q["answer"]
                        )
                        st.markdown(f"**📝 Test score: {correct_count}/{len(qs)}**")
                        with st.expander("View detailed answers"):
                            for i, q in enumerate(qs):
                                ans_given   = answers.get(str(i))
                                ans_correct = q["answer"]
                                ok   = (ans_given == ans_correct)
                                icon = "✅" if ok else ("❌" if ans_given is not None else "⬜")
                                st.markdown(f"**{icon} Q{i+1}. {q['text']}**")
                                for j, opt in enumerate(q["options"]):
                                    if j == ans_correct and j == ans_given:
                                        st.markdown(f"&nbsp;&nbsp;&nbsp;✅ **{opt}** ← correct, chosen")
                                    elif j == ans_correct:
                                        st.markdown(f"&nbsp;&nbsp;&nbsp;✅ **{opt}** ← correct answer")
                                    elif j == ans_given:
                                        st.markdown(f"&nbsp;&nbsp;&nbsp;❌ ~~{opt}~~ ← student chose")
                                    else:
                                        st.markdown(f"&nbsp;&nbsp;&nbsp;{chr(65+j)}. {opt}")
                                st.markdown("")
                    st.divider()

                elif ex["status"] == "pending":
                    st.caption("⏳ Waiting for student to start")
                elif ex["status"] == "active":
                    st.caption("🟢 In progress...")


# ══════════════════════════════════════════════════════════════════════════════
#  STUDENT PAGE
# ══════════════════════════════════════════════════════════════════════════════
def student_page():
    db = get_db()

    my_exams = {eid: ex for eid, ex in db["exams"].items()
                if ex["student"] == uname and ex["status"] in ("pending", "active")}

    st.title("🎓 Student Panel")
    st.divider()

    # ── No exam assigned ───────────────────────────────────────────────────────
    if not my_exams:
        st.info("📭 No active exams assigned to you.")
        submitted = {eid: ex for eid, ex in db["exams"].items()
                     if ex["student"] == uname and ex["status"] == "submitted"}
        if submitted:
            st.subheader("Completed exams")
            for eid, ex in submitted.items():
                n_q = len(ex.get("questions", []))
                r   = ex.get("result") or {}
                score_str = ""
                if r.get("answers") and ex.get("questions"):
                    correct = sum(1 for i,q in enumerate(ex["questions"])
                                  if r["answers"].get(str(i)) == q["answer"])
                    score_str = f" · Test: {correct}/{n_q}"
                st.markdown(f"""<div class="exam-card">
                    <b>{ex['title']}</b> &nbsp;
                    <span class="badge-submitted">SUBMITTED</span><br>
                    <small>Teacher: {ex['teacher']} · {ex['created_at']}
                    {score_str}</small>
                </div>""", unsafe_allow_html=True)
        return

    import datetime as dt
    now_str    = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    active_key = f"active_exam_{uname}"

    # ── Exam selection if multiple ─────────────────────────────────────────────
    if len(my_exams) > 1 and active_key not in st.session_state:
        st.subheader("Select an exam to start:")
        options = {}
        for eid_opt, ex_opt in my_exams.items():
            label = ex_opt["title"]
            dl    = ex_opt.get("deadline")
            if dl:
                label += f"  ·  deadline {dl}"
                if dl < now_str:
                    label += " ⚠️ EXPIRED"
            options[eid_opt] = label

        chosen = st.radio("Available exams", list(options.keys()),
                           format_func=lambda e: options[e])
        if st.button("Open →", type="primary"):
            st.session_state[active_key] = chosen
            st.rerun()
        st.stop()   # halt here — don't render exam UI yet

    # ── Resolve which exam to open ─────────────────────────────────────────────
    if active_key in st.session_state:
        eid  = st.session_state[active_key]
        exam = my_exams.get(eid)
        if exam is None:            # exam no longer available
            del st.session_state[active_key]
            st.rerun()
    else:
        eid, exam = next(iter(my_exams.items()))

    # ── Check deadline ─────────────────────────────────────────────────────────
    if exam.get("deadline") and exam["deadline"] < now_str:
        st.error(f"⏰ Deadline passed: **{exam['deadline']}**. Contact your teacher.")
        if st.button("← Back to exam list"):
            st.session_state.pop(active_key, None)
            st.rerun()
        st.stop()

    if exam["status"] == "pending":
        db["exams"][eid]["status"] = "active"
        save_db(db)
        st.rerun()

    # ── Onboarding screen ──────────────────────────────────────────────────────
    ready_key = f"ready_{eid}"
    if not st.session_state.get(ready_key):
        _, col, _ = st.columns([1, 2, 1])
        with col:
            duration_min = exam.get("duration", 30)
            n_questions  = len(exam.get("questions", []))
            st.markdown(f"### 📋 {exam['title']}")
            st.caption(f"Teacher: {exam['teacher']}  ·  {exam['created_at']}")
            st.markdown("")
            ic1, ic2, ic3 = st.columns(3)
            ic1.metric("⏱ Duration",   f"{duration_min} min")
            ic2.metric("📝 Questions", str(n_questions))
            dl = exam.get("deadline")
            ic3.metric("📅 Deadline",  dl if dl else "None")
            st.divider()

            st.markdown("**Before you begin, confirm the following:**")
            c1 = st.checkbox("My camera is working")
            c2 = st.checkbox("I am alone in the room")
            c3 = st.checkbox("My face is clearly visible")
            c4 = st.checkbox("I understand that my session is being monitored")

            st.divider()
            st.caption("Once you start, your session will be recorded. Do not close this tab.")

            all_checked = c1 and c2 and c3 and c4
            if st.button("▶ Start exam",
                         type="primary",
                         use_container_width=True,
                         disabled=not all_checked):
                st.session_state[ready_key]          = True
                st.session_state[f"start_{eid}"]     = time.time()
                st.rerun()

            if not all_checked:
                st.caption("✦ Check all boxes to continue")
        return

    # ── Exam start time ────────────────────────────────────────────────────────
    exam_start = st.session_state.get(f"start_{eid}", time.time())

    settings = dict(
        student_name=display,
        enable_telegram=exam.get("telegram", True),
        enable_yolo=True,
        track_absence=True, track_gaze=True, track_extra=True,
        track_phone=True,   track_book=True, track_objects=True,
    )

    duration_min = exam.get("duration", 30)
    duration_sec = duration_min * 60
    questions    = exam.get("questions", [])

    # ── Submit helper — defined BEFORE tabs so button can call it ─────────────
    def _do_submit():
        ans_key = f"answers_{eid}"
        # Snapshot processor state
        if ctx.video_processor:
            with ctx.video_processor._lock:
                d_f  = ctx.video_processor.last.copy()
                vlog = list(ctx.video_processor.violations_log)
            fs = d_f["focus_scores"]
        else:
            d_f  = {"focus_scores": [], "blink_rate": 0}
            vlog = []
            fs   = []
        db["exams"][eid]["result"] = {
            "avg_focus":    sum(fs)/len(fs) if fs else 0,
            "min_focus":    min(fs) if fs else 0,
            "blink_rate":   d_f["blink_rate"],
            "violations":   len(vlog),
            "focus_scores": fs[-100:],
            "answers":      dict(st.session_state.get(ans_key, {})),
            "duration_s":   int(time.time() - exam_start),
            "submitted_at": time.strftime("%H:%M:%S"),
        }
        db["exams"][eid]["status"] = "submitted"
        save_db(db)
        # Reload db from file so all sessions see the update
        fresh = _load_db()
        db.update(fresh)
        st.session_state.pop(ready_key, None)
        st.session_state.pop(f"active_exam_{uname}", None)
        st.success("✅ Exam submitted! Your teacher will see the results.")
        st.rerun()

    # Determine which tabs to show
    tab_labels = ["🎥 Camera", "📝 Test", "📊 Metrics"]
    tabs = st.tabs(tab_labels)

    tab_cam     = tabs[0]
    tab_test    = tabs[1]
    tab_metrics = tabs[2]

    with tab_cam:
        col_vid, col_info = st.columns([2.4, 1])

        with col_vid:
            ctx = webrtc_streamer(
                key=f"exam_{eid}",
                mode=WebRtcMode.SENDRECV,
                rtc_configuration=_get_rtc_config(),
                media_stream_constraints={
                    "video": {"width":  {"ideal": 640},
                              "height": {"ideal": 480},
                              "frameRate": {"ideal": 15}},
                    "audio": False,
                },
                video_processor_factory=FocusProcessor,
                async_processing=True,
            )

        with col_info:
            st.markdown("#### ⏱ Time left")
            timer_ph = st.empty()
            st.markdown("---")
            st.markdown("#### Status")
            status_ph = st.empty()
            st.markdown("---")
            st.markdown("#### Violations")
            viol_ph = st.empty()

        st.divider()
        st.caption("⚠️ Do not close or refresh this tab until you submit.")
        if st.button("✅ Submit exam", type="primary", use_container_width=True):
            _do_submit()

    # ── Test tab ───────────────────────────────────────────────────────────────
    with tab_test:
        ans_key = f"answers_{eid}"
        if ans_key not in st.session_state:
            st.session_state[ans_key] = {}

        if not questions:
            st.info("📭 No questions were added to this exam.")
        elif not ctx.state.playing:
            st.warning("⚠️ Start your camera first — go to the Camera tab and press START.")
        else:
            st.subheader("📝 Answer the questions")
            st.caption(f"{len(questions)} questions · answers are saved automatically")
            st.divider()

            for i, q in enumerate(questions):
                st.markdown(f"**Q{i+1}. {q['text']}**")
                opts   = [f"{chr(65+j)}. {opt}" for j, opt in enumerate(q["options"])]
                saved  = st.session_state[ans_key].get(str(i), 0)
                choice = st.radio("", opts, index=saved,
                                  key=f"q_{eid}_{i}", horizontal=True,
                                  label_visibility="collapsed")
                st.session_state[ans_key][str(i)] = opts.index(choice)
                st.divider()

            answered = len(st.session_state[ans_key])
            st.caption(f"Answered: {answered}/{len(questions)}")

    with tab_metrics:
        metrics_ph = st.empty()



    # ── Fragment: timer + metrics, never touches webrtc ───────────────────────
    @st.fragment(run_every=2)
    def _tick():
        elapsed   = int(time.time() - exam_start)
        remaining = max(0, duration_sec - elapsed)
        rm, rs    = remaining // 60, remaining % 60

        # Countdown color: green → yellow → red
        if remaining > duration_sec * 0.5:   tcol = "#00e5ff"
        elif remaining > duration_sec * 0.2: tcol = "#ffd60a"
        else:                                tcol = "#ff3b5c"

        timer_ph.markdown(
            f"<div style='font-size:1.8rem;font-weight:700;color:{tcol}'>"
            f"{rm:02d}:{rs:02d}</div>", unsafe_allow_html=True)

        # Also compute elapsed for metrics tab
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60

        # Deadline check
        dl = exam.get("deadline")
        if dl:
            import datetime as dt
            if dt.datetime.now().strftime("%Y-%m-%d %H:%M") >= dl:
                timer_ph.markdown(
                    "<div style='font-size:1rem;color:#ff3b5c'>⏰ Deadline reached — auto-submitting</div>",
                    unsafe_allow_html=True)
                _do_submit()
                return

        # Auto-submit when countdown hits zero
        if remaining == 0:
            _do_submit()
            return

        if not ctx.video_processor:
            status_ph.caption("Start camera")
            viol_ph.caption("—")
            metrics_ph.info("Start the camera to see metrics")
            return

        with ctx.video_processor._lock:
            d    = ctx.video_processor.last.copy()
            vlog = list(ctx.video_processor.violations_log)

        # Side panel — status
        status_ph.markdown(
            f"<div style='color:{d['color']};font-weight:600'>{d['status']}</div>",
            unsafe_allow_html=True)

        # Violations panel:
        # - active_violations = happening RIGHT NOW (show immediately)
        # - vlog = confirmed + logged (shown in metrics tab)
        if d["active_violations"]:
            html = "".join(
                f'<div class="vrow">⚠️ {v}</div>'
                for v in d["active_violations"][:4]
            )
            viol_ph.markdown(html, unsafe_allow_html=True)
        elif vlog:
            # Show last confirmed violation
            viol_ph.markdown(
                f'<div class="vrow">{vlog[0]}</div>',
                unsafe_allow_html=True)
        else:
            viol_ph.success("Clean ✅")

        # Metrics tab
        with metrics_ph.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("🎯 Focus",      f"{int(d['focus_score'])}%")
            c2.metric("⏱ Session",    f"{h:02d}:{m:02d}:{s:02d}")
            c3.metric("👁 Blinks/min", f"{d['blink_rate']:.1f}")
            c4.metric("👀 Gaze",       d["gaze"])
            st.divider()
            # Current active violations
            if d["active_violations"]:
                st.markdown("**⚠️ Active now:**")
                st.markdown(
                    "".join(f'<div class="vrow">⚠️ {v}</div>' for v in d["active_violations"]),
                    unsafe_allow_html=True)

            # Confirmed violation log
            if vlog:
                st.markdown("**📋 Violation log:**")
                st.markdown(
                    "".join(f'<div class="vrow">{v}</div>' for v in vlog),
                    unsafe_allow_html=True)
            elif not d["active_violations"]:
                st.success("No violations detected ✅")

    _tick()


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
