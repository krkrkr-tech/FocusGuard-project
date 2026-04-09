import cv2
import dlib
import numpy as np
from scipy.spatial import distance as dist
import streamlit as st
import time
from collections import deque
import plotly.graph_objects as go

# settings
EAR_THRESHOLD = 0.23          # When we consider eyes closed
EAR_CONSEC_FRAMES = 4         # How many frames eyes need to be "closed" to count as blink
GAZE_THRESHOLD = 0.28         # How far from center we consider "looking away"
MAX_BLINK_RATE = 25           # Blinks per minute - above this we start gentle penalty (normal humans blink ~15-20)

# Helper function to calculate Eye Aspect Ratio (EAR)
def eye_aspect_ratio(eye):
    """Calculate Eye Aspect Ratio (EAR) to detect blinking"""
    points = [(p.x, p.y) for p in eye]
    A = dist.euclidean(points[1], points[5])
    B = dist.euclidean(points[2], points[4])
    C = dist.euclidean(points[0], points[3])
    return (A + B) / (2.0 * C)


def get_bounding_box(eye):
    """Get bounding box coordinates from eye landmarks"""
    x = [p.x for p in eye]
    y = [p.y for p in eye]
    return (min(x), min(y), max(x), max(y))


def get_iris_center(eye_frame):
    """Simple but effective way to find the center of the iris/pupil"""
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


# Load AI models (only once thanks to caching)
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
    </style>
""", unsafe_allow_html=True)

st.title("🧠 Focus Guard")
st.markdown("**A gentle focus tracker** that understands you’re human")

col_video, col_side = st.columns([2.2, 1])

with col_video:
    video_placeholder = st.empty()

with col_side:
    st.subheader("📊 Your Current State")
    focus_placeholder = st.empty()
    gaze_placeholder = st.empty()
    blink_placeholder = st.empty()
    timer_placeholder = st.empty()
    status_placeholder = st.empty()

    st.subheader("📈 Focus Over Time")
    chart_placeholder = st.empty()

# Initialize session
if 'session_start' not in st.session_state:
    st.session_state.session_start = time.time()
    st.session_state.total_blinks = 0

total_blinks = 0
frame_counter = 0
last_blink_time = time.time()
focus_scores = deque(maxlen=400)

run = st.checkbox("🎥 Start Webcam (Mirrored)", value=True)

if run:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        st.error("❌ Could not access your camera. Please make sure it's not being used by another app.")
        st.stop()

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

    while run:
        ret, frame = cap.read()
        if not ret:
            st.error("Failed to read camera frame")
            break

        frame = cv2.flip(frame, 1)  # Mirror - feels more natural
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)

        current_ear = 0.0
        gaze_direction = "Center"
        face_detected = len(faces) > 0

        for face in faces:
            cv2.rectangle(frame, (face.left(), face.top()), (face.right(), face.bottom()), (0, 255, 120), 3)

            landmarks = predictor(gray, face).parts()

            left_eye_pts = landmarks[36:42]
            right_eye_pts = landmarks[42:48]

            current_ear = (eye_aspect_ratio(left_eye_pts) + eye_aspect_ratio(right_eye_pts)) / 2.0

            left_bbox = get_bounding_box(left_eye_pts)
            right_bbox = get_bounding_box(right_eye_pts)

            left_eye_frame = frame[left_bbox[1]:left_bbox[3], left_bbox[0]:left_bbox[2]]
            right_eye_frame = frame[right_bbox[1]:right_bbox[3], right_bbox[0]:right_bbox[2]]

            left_iris = get_iris_center(left_eye_frame)
            right_iris = get_iris_center(right_eye_frame)

            # Visual feedback
            cv2.rectangle(frame, (left_bbox[0], left_bbox[1]), (left_bbox[2], left_bbox[3]), (255, 100, 255), 2)
            cv2.rectangle(frame, (right_bbox[0], right_bbox[1]), (right_bbox[2], right_bbox[3]), (255, 100, 255), 2)

            for pt in list(left_eye_pts) + list(right_eye_pts):
                cv2.circle(frame, (pt.x, pt.y), 2, (0, 255, 255), -1)

            # Gentle gaze detection
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

                # Draw iris centers
                lx = left_bbox[0] + left_iris[0]
                ly = left_bbox[1] + left_iris[1]
                rx = right_bbox[0] + right_iris[0]
                ry = right_bbox[1] + right_iris[1]
                cv2.circle(frame, (int(lx), int(ly)), 6, (0, 255, 255), -1)
                cv2.circle(frame, (int(rx), int(ry)), 6, (0, 255, 255), -1)

            # Blink detection - very forgiving
            if current_ear < EAR_THRESHOLD:
                frame_counter += 1
                if frame_counter >= EAR_CONSEC_FRAMES and time.time() - last_blink_time > 0.4:
                    total_blinks += 1
                    last_blink_time = time.time()
            else:
                frame_counter = 0

        #  FOCUS CALCULATION

        session_time = max(1, time.time() - st.session_state.session_start)
        blink_rate_per_min = (total_blinks / session_time) * 60

        gaze_penalty = 35 if gaze_direction != "👀 Looking Center" else 0
        blink_penalty = max(0, (blink_rate_per_min - MAX_BLINK_RATE) * 0.8)

        focus_score = max(15, min(100, 92 - gaze_penalty - blink_penalty))

        focus_scores.append(focus_score)

        # Friendly status messages
        if focus_score > 78:
            status = "🟢 You're in the flow — great job!"
            color = "#00ff9d"
        elif focus_score > 55:
            status = "🟡 Doing well — just keep your eyes on the screen"
            color = "#ffcc00"
        else:
            status = "🔴 Hey, come back to the screen when you can"
            color = "#ff4444"

        # Draw info on video
        cv2.putText(frame, f"Focus: {int(focus_score)}%", (30, 55), cv2.FONT_HERSHEY_DUPLEX, 1.25, (255, 255, 255), 3)
        cv2.putText(frame, gaze_direction, (30, 95), cv2.FONT_HERSHEY_DUPLEX, 0.95, (0, 255, 255), 2)

        # Show video feed
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_placeholder.image(frame_rgb, channels="RGB", use_column_width=True)

        # Update metrics
        focus_placeholder.metric("Focus Level", f"{int(focus_score)}%")
        gaze_placeholder.markdown(f"**Gaze:** {gaze_direction}")
        blink_placeholder.metric("Blinks per minute", f"{blink_rate_per_min:.1f}")
        timer_placeholder.metric("Session Time", f"{int(session_time)} s")

        status_placeholder.markdown(f"<h3 style='color:{color}; margin:0;'>{status}</h3>", unsafe_allow_html=True)

        # Focus trend chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=list(focus_scores), mode='lines', line=dict(color='#00ff9d', width=4)))
        fig.update_layout(title="Focus Level Over Time", yaxis_range=[0, 100], height=280,
                          template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10))
        chart_placeholder.plotly_chart(fig, use_container_width=True)

        time.sleep(0.03)

    cap.release()

else:
    st.info("👈 Click the checkbox above to begin tracking your focus gently")

st.caption("Focus Guard — Built with care • Understands that humans blink and sometimes look away")
