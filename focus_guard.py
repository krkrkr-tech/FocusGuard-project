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
RTC_CONFIGURATION  = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})

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
@st.cache_resource
def load_face_mesh():
    return mp.solutions.face_mesh.FaceMesh(
        max_num_faces=4,
        refine_landmarks=True,   # включает радужку (468-477)
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

@st.cache_resource
def load_yolo():
    try:
        from ultralytics import YOLO
        return YOLO(YOLO_MODEL)
    except Exception:
        return None

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
        self.face_mesh   = load_face_mesh()
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
#  UI
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Focus Guard", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e1117; }
[data-testid="stMetric"] {
    background: #1c2333;
    border-radius: 10px;
    padding: 12px 16px;
    border: 1px solid #2a3550;
}
.vrow {
    background: #1f1318;
    border-left: 3px solid #ff4444;
    border-radius: 0 6px 6px 0;
    padding: 7px 12px;
    margin: 4px 0;
    color: #ffaaaa;
    font-size: 0.88rem;
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    student_name    = st.text_input("👤 Student name", value="Student")
    enable_telegram = st.checkbox("📨 Telegram alerts", value=True)
    enable_yolo     = st.checkbox("🔍 YOLO detection", value=True)
    st.divider()
    st.subheader("Violations to track")
    track_absence = st.checkbox("🚫 Person absent",     value=True)
    track_gaze    = st.checkbox("👀 Gaze away",         value=True)
    track_extra   = st.checkbox("👥 Extra people",      value=True)
    track_phone   = st.checkbox("📱 Phone",             value=True)
    track_book    = st.checkbox("📚 Book / cheatsheet", value=True)
    track_objects = st.checkbox("💻 Laptop / TV",       value=True)
    st.divider()
    notifier = get_notifier()
    if notifier.ok():
        st.success(f"✅ Telegram connected · sent: {notifier.total_sent}")
    else:
        st.warning("⚠️ Telegram not configured")
    if notifier.last_error:
        st.error(notifier.last_error)
    st.divider()
    if st.button("🔄 Reset session", use_container_width=True):
        st.session_state.clear(); st.rerun()

# ── Header ─────────────────────────────────────────────────────────────────────
st.title("🧠 Focus Guard")
st.caption("Student attention monitoring · MediaPipe + YOLOv8 + Telegram")
st.divider()

settings = dict(student_name=student_name, enable_telegram=enable_telegram,
                enable_yolo=enable_yolo, track_absence=track_absence,
                track_gaze=track_gaze, track_extra=track_extra,
                track_phone=track_phone, track_book=track_book,
                track_objects=track_objects)

# ── Layout ─────────────────────────────────────────────────────────────────────
col_cam, col_side = st.columns([2.2, 1])

with col_cam:
    st.subheader("🎥 Camera feed")
    ctx = webrtc_streamer(
        key="fg",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=RTC_CONFIGURATION,
        media_stream_constraints={"video": True, "audio": False},
        video_processor_factory=FocusProcessor,
        async_processing=True,
    )
    st.divider()
    st.subheader("📈 Focus over time")
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
    st.subheader("🚨 Violation log")
    ph_viol = st.empty()

if ctx.video_processor:
    ctx.video_processor.update_settings(settings)

# ── Render ─────────────────────────────────────────────────────────────────────
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
        ph_viol.markdown("".join(f'<div class="vrow">{v}</div>' for v in vlog[:10]),
                         unsafe_allow_html=True)
    elif d["active_violations"]:
        ph_viol.markdown("".join(f'<div class="vrow">{v}</div>' for v in d["active_violations"][:10]),
                         unsafe_allow_html=True)
    else:
        ph_viol.success("No violations detected ✅")

    fs = d["focus_scores"]
    if len(fs) > 2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=fs, mode="lines",
            line=dict(color="#00ff9d", width=2.5),
            fill="tozeroy", fillcolor="rgba(0,255,157,0.08)",
        ))
        fig.add_hline(y=78, line_color="rgba(0,255,157,0.3)", line_dash="dot")
        fig.add_hline(y=55, line_color="rgba(255,204,0,0.3)",  line_dash="dot")
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=220, showlegend=False,
            margin=dict(l=0,r=0,t=8,b=0),
            yaxis=dict(range=[0,100], gridcolor="rgba(255,255,255,0.05)",
                       ticksuffix="%", tickfont=dict(color="#aaa")),
            xaxis=dict(showgrid=False, showticklabels=False),
        )
        chart_ph.plotly_chart(fig, use_container_width=True, key=f"c{int(time.time()*4)}")

else:
    ph_focus.metric("🎯 Focus",      "—")
    ph_time.metric( "⏱ Session",    "—")
    ph_blink.metric("👁 Blinks/min","—")
    ph_gaze.metric( "👀 Gaze",      "—")
    ph_status.markdown("<h3 style='color:#555;margin:0'>⏸ Waiting for camera</h3>",
                       unsafe_allow_html=True)
    ph_viol.info("Press START and allow camera access")

st.caption("Focus Guard · MediaPipe FaceMesh + YOLOv8 + Telegram")

if ctx.state.playing:
    time.sleep(0.2)
    st.rerun()
