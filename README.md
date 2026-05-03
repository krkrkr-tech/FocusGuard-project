<div align="center">

<img src="https://img.shields.io/badge/Focus%20Guard-AI%20Proctoring-00e5ff?style=for-the-badge&logo=eye&logoColor=white"/>

# 🧠 Focus Guard
### AI-Powered Real-Time Student Attention Monitoring System

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-FaceMesh-0097A7?style=flat-square&logo=google&logoColor=white)](https://mediapipe.dev)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Object%20Detection-00B16A?style=flat-square)](https://ultralytics.com)
[![Telegram](https://img.shields.io/badge/Telegram-Bot%20API-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

> *Ensuring academic integrity through intelligent, real-time behavioral analysis.*

</div>

---

## 📌 1. Project Title

**Focus Guard** — AI-Powered Real-Time Student Attention Monitoring & Proctoring System

---

## 🗂️ 2. Topic Area

**Education Technology (EdTech) · Artificial Intelligence · Computer Vision**

Focus Guard sits at the intersection of AI-driven surveillance, academic integrity tooling, and remote learning infrastructure — addressing a critical gap in modern online education.

---

## ❗ 3. Problem Statement

- **Remote and hybrid exams lack reliable supervision**, making it trivially easy for students to cheat using phones, books, or other devices without detection.
- **Manual proctoring is expensive and unscalable** — human invigilators cannot monitor multiple students simultaneously with consistent attention.
- **Existing automated proctoring tools are costly, privacy-invasive, or require heavy infrastructure**, making them inaccessible for smaller institutions and individual educators.
- **There is no lightweight, open-source solution** that combines real-time gaze tracking, blink analysis, object detection, and instant violation alerts in a single deployable web application.

---

## 💡 4. Proposed Solution

Focus Guard is a browser-based proctoring system built with **Streamlit + WebRTC** that uses the device's webcam to continuously monitor a student during an exam session. It leverages:

- **MediaPipe FaceMesh** for precise iris tracking (478 facial landmarks) and blink detection via Eye Aspect Ratio (EAR)
- **YOLOv8n** for real-time detection of suspicious objects (phone, book, laptop, TV)
- **Gaze estimation** to detect when a student looks away from the screen
- **Telegram Bot API** to instantly notify teachers with annotated screenshots on violation detection
- A **role-based web interface** (Admin / Teacher / Student) with session management and results dashboard

The system runs entirely in-browser with no client-side installation required.

---

## 👥 5. Target Users

| Role | Description |
|------|-------------|
| 🎓 **Students** | Take monitored exams through their browser; submit results when done |
| 👨‍🏫 **Teachers** | Create exam sessions, assign them to students, review focus reports |
| 🛡️ **Administrators** | Manage user accounts, monitor all exams across the platform |

---

## 🛠️ 6. Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Streamlit 1.x · streamlit-webrtc · Plotly |
| **Backend** | Python 3.10+ · OpenCV · MediaPipe · Ultralytics YOLOv8 |
| **Computer Vision** | MediaPipe FaceMesh (iris landmarks) · YOLOv8n |
| **Real-time Video** | WebRTC (aiortc) · PyAV |
| **Notifications** | Telegram Bot API |
| **Authentication** | SHA-256 password hashing · Streamlit session state |
| **Database** | In-memory cache (`st.cache_resource`) — extendable to SQLite/PostgreSQL |
| **Cloud / Hosting** | Streamlit Community Cloud · Docker (optional) |
| **Other Tools** | Git · GitHub · NumPy · SciPy |

---

## ✨ 7. Key Features

### 👁️ Real-Time Attention Analysis
- **Iris gaze tracking** using MediaPipe FaceMesh with 478 landmarks and built-in iris refinement
- Detects gaze direction: `Center` / `Slight Left` / `Left` / `Slight Right` / `Right`
- 6-frame rolling average for smooth, noise-free gaze output

### 😑 Blink Rate Monitoring
- Eye Aspect Ratio (EAR) algorithm with consecutive-frame validation
- Flags abnormal blink rates that may indicate fatigue or distraction
- Configurable threshold and grace period

### 📱 Suspicious Object Detection
- YOLOv8n inference every 5 frames for performance efficiency
- Detects: `cell phone`, `book`, `remote`, `laptop`, `TV`
- Bounding boxes and confidence scores rendered on annotated violation screenshots

### 🚨 Instant Violation Alerts
- Violations are confirmed only after a grace period (avoids false positives)
- Annotated screenshot (with landmarks, boxes, and overlay data) sent via **Telegram Bot**
- 15-second cooldown per violation type to prevent alert flooding
- Clean video stream shown to student — annotations only appear in Telegram photos

### 🔐 Role-Based Authentication
- Three roles: **Admin**, **Teacher**, **Student**
- SHA-256 hashed passwords
- Admin can add/remove users; Teacher creates exam sessions; Student submits results

### 📊 Focus Score & Dashboard
- Real-time focus score (0–100%) computed from absence, gaze, blink rate, extra faces, and objects
- Live Plotly chart with color-coded zones (green ≥ 78%, yellow ≥ 55%, red < 55%)
- Per-exam result report: avg focus, min focus, blinks/min, total violations

---

## 👨‍💻 8. Team Members

| Name | Role | Email |
|------|------|-------|
| — | Project Lead · Backend Developer | — |
| — | Computer Vision Engineer | — |
| — | Frontend / UI Developer | — |

---

## 🎯 9. Expected Outcome

By the end of the capstone, the following deliverables will be produced:

- ✅ **Fully functional web application** deployable via `streamlit run focus_guard.py`
- ✅ **Role-based multi-user system** with Admin, Teacher, and Student portals
- ✅ **Real-time proctoring engine** with gaze tracking, blink detection, and object detection
- ✅ **Telegram integration** for instant violation notifications with annotated screenshots
- ✅ **Session management** — teachers create exams, students complete and submit them
- ✅ **Post-exam analytics dashboard** with focus graphs and violation summary
- ✅ **Source code** with documentation on GitHub

---

## 🔗 10. Git Repository

```
URL: https://github.com/your-username/focus-guard
```

---

## 🚀 Getting Started

### Prerequisites

```bash
pip install streamlit streamlit-webrtc mediapipe ultralytics opencv-python \
            plotly numpy scipy requests aiortc av
```

### Run

```bash
streamlit run focus_guard.py
```

### Default Credentials

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin` | 🛡️ Administrator |
| `teacher` | `teacher` | 👨‍🏫 Teacher |
| `student` | `student` | 🎓 Student |

> ⚠️ Change default passwords before deployment.

---

## 📐 System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (Student)                     │
│   WebRTC Camera Stream ──► streamlit-webrtc             │
└──────────────────────────┬──────────────────────────────┘
                           │ video frames
┌──────────────────────────▼──────────────────────────────┐
│                  FocusProcessor (Thread)                 │
│                                                         │
│  MediaPipe FaceMesh ──► Gaze Ratio + EAR (blinks)       │
│  YOLOv8n           ──► Suspicious Object Detection      │
│  Focus Score       ──► Weighted penalty formula          │
│  Violation Manager ──► Grace period + cooldown          │
└─────┬───────────────────────────────────┬───────────────┘
      │ clean frame → stream              │ violation
      │                                   ▼
      │                        Annotated screenshot
      │                        Telegram Bot API ──► Teacher
      ▼
┌─────────────────┐    ┌──────────────────────────────────┐
│  Streamlit UI   │    │         Role Router               │
│  (rerun loop)   │◄───│  Admin / Teacher / Student Page  │
│  Metrics panel  │    │  Exam Sessions · Results DB      │
└─────────────────┘    └──────────────────────────────────┘
```

---

## 📊 Focus Score Formula

```
score = 92
      − 77  (if person absent)
      − 35  (if gaze not centered)
      − max(0, (blink_rate − 25) × 0.8)
      − 40  (if extra faces detected)
      − 25  (per suspicious object)

clamped to [15, 100]
```

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with ❤️ for the Capstone Project · Focus Guard Team

</div>

Team members:
Kairat Gaziz 230103270
Koshamet Alikhan 230103117
