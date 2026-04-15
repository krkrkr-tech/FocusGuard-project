# 🧠 Focus Guard

A calm and human-friendly real-time focus tracker that monitors your gaze and blinking using your webcam.

It doesn't punish you for normal blinking — it only gently reminds you when you're looking away from the screen for too long.

### Features
- Real-time gaze direction detection (Center / Left / Right)
- Very forgiving blink detection (feels natural)
- Beautiful dark UI with live focus trend chart
- Mirrored camera (like Zoom/FaceTime)
- Session timer

### How it works
Focus Guard uses facial landmarks (dlib) and simple computer vision to estimate:
- Whether your eyes are open
- Where you're looking
- Your overall focus level

The algorithm is intentionally tuned to be kind to human behavior.

### Requirements

See `requirements.txt`

### How to Run

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/focus-guard.git
   cd focus-guard

pip install -r requirements.txt

Download the shape predictor model:
Download shape_predictor_68_face_landmarks.dat from:
https://github.com/italojs/facial-landmarks-recognition/raw/master/shape_predictor_68_face_landmarks.dat
Place it in the project root folder (same folder as focus_guard.py)

streamlit run focus_guard.py
