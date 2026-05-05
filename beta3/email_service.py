"""
Email module for Focus Guard
Handles email verification and notifications via SendGrid
"""

import streamlit as st
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import os

def send_verification_email(recipient_email: str, verification_code: str, full_name: str) -> bool:
    """Send verification code via email"""
    try:
        api_key = st.secrets.get("sendgrid_api_key") or os.getenv("SENDGRID_API_KEY")
        
        if not api_key:
            st.error("SendGrid API key not configured")
            return False
        
        sg = SendGridAPIClient(api_key)
        
        subject = "🧠 Focus Guard - Email Verification"
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0e1117; color: #c9d1d9; padding: 20px;">
            <div style="max-width: 500px; margin: 0 auto; background-color: #1c2333; padding: 30px; border-radius: 10px; border: 1px solid #2a3550;">
                <h2 style="color: #58a6ff; text-align: center;">🧠 Focus Guard</h2>
                <p>Hello <strong>{full_name}</strong>,</p>
                
                <p>Thank you for registering! To complete your registration, please use the following verification code:</p>
                
                <div style="background-color: #0d1117; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0; border: 2px solid #58a6ff;">
                    <h1 style="color: #00ff9d; letter-spacing: 5px; margin: 0;">{verification_code}</h1>
                </div>
                
                <p style="color: #8b949e;">This code will expire in <strong>10 minutes</strong>.</p>
                
                <p style="margin-top: 30px; font-size: 12px; color: #6e7681;">
                    If you didn't register for Focus Guard, please ignore this email.
                </p>
                
                <hr style="border: none; border-top: 1px solid #2a3550; margin: 30px 0;">
                
                <p style="text-align: center; font-size: 12px; color: #6e7681;">
                    © 2026 Focus Guard · AI Proctoring System<br>
                    <a href="https://focusguard.local" style="color: #58a6ff; text-decoration: none;">Visit our website</a>
                </p>
            </div>
        </body>
        </html>
        """
        
        message = Mail(
            from_email=st.secrets.get("email_address", "noreply@focusguard.local"),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=html_content
        )
        
        response = sg.send(message)
        return response.status_code in [200, 202]
        
    except Exception as e:
        st.error(f"Email send error: {e}")
        return False

def send_violation_alert(recipient_email: str, student_name: str, exam_title: str, 
                         violation_type: str, timestamp: str) -> bool:
    """Send violation alert to teacher"""
    try:
        api_key = st.secrets.get("sendgrid_api_key") or os.getenv("SENDGRID_API_KEY")
        
        if not api_key:
            return False
        
        sg = SendGridAPIClient(api_key)
        
        subject = f"🚨 Focus Guard - Violation Alert: {exam_title}"
        
        violation_names = {
            "person_absent": "Person Absent",
            "gaze_away": "Looking Away",
            "extra_face": "Extra Face Detected",
            "phone_detected": "Phone Detected",
            "book_detected": "Book Detected",
            "suspicious_object": "Suspicious Object"
        }
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0e1117; color: #c9d1d9; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #1c2333; padding: 30px; border-radius: 10px; border-left: 4px solid #ff4444;">
                <h2 style="color: #ff4444; margin-top: 0;">🚨 Violation Alert</h2>
                
                <p><strong>Student:</strong> {student_name}</p>
                <p><strong>Exam:</strong> {exam_title}</p>
                <p><strong>Violation Type:</strong> {violation_names.get(violation_type, violation_type)}</p>
                <p><strong>Time:</strong> {timestamp}</p>
                
                <div style="background-color: #0d1117; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 3px solid #ff4444;">
                    <p style="margin: 0; color: #ff6b6b;">
                        A potential violation has been detected during the exam. 
                        Please review the session details for more information.
                    </p>
                </div>
                
                <p style="margin-top: 30px; font-size: 12px; color: #6e7681;">
                    Log in to Focus Guard to view full session details and take action if needed.
                </p>
            </div>
        </body>
        </html>
        """
        
        message = Mail(
            from_email=st.secrets.get("email_address", "noreply@focusguard.local"),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=html_content
        )
        
        response = sg.send(message)
        return response.status_code in [200, 202]
        
    except Exception as e:
        return False

def send_exam_completion_email(recipient_email: str, student_name: str, exam_title: str, 
                               final_score: float, avg_focus: float, violations: int) -> bool:
    """Send exam completion summary to student"""
    try:
        api_key = st.secrets.get("sendgrid_api_key") or os.getenv("SENDGRID_API_KEY")
        
        if not api_key:
            return False
        
        sg = SendGridAPIClient(api_key)
        
        subject = f"✅ Focus Guard - Exam Completed: {exam_title}"
        
        # Color code for score
        if final_score >= 85:
            score_color = "#00ff9d"  # Green
            score_status = "Excellent"
        elif final_score >= 70:
            score_color = "#ffd60a"  # Yellow
            score_status = "Good"
        else:
            score_color = "#ff4444"  # Red
            score_status = "Needs Improvement"
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #0e1117; color: #c9d1d9; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #1c2333; padding: 30px; border-radius: 10px; border: 1px solid #2a3550;">
                <h2 style="color: #58a6ff; text-align: center;">✅ Exam Completed</h2>
                
                <p>Hello <strong>{student_name}</strong>,</p>
                
                <p>Your exam has been successfully submitted and evaluated.</p>
                
                <div style="background-color: #0d1117; padding: 20px; border-radius: 8px; margin: 20px 0; border: 2px solid {score_color};">
                    <h3 style="color: {score_color}; text-align: center; margin-top: 0;">Exam: {exam_title}</h3>
                    
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #2a3550;">
                            <td style="padding: 12px 0; color: #8b949e;">Final Score</td>
                            <td style="padding: 12px 0; color: {score_color}; font-weight: bold; text-align: right;">{final_score:.1f}/100</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #2a3550;">
                            <td style="padding: 12px 0; color: #8b949e;">Status</td>
                            <td style="padding: 12px 0; color: {score_color}; font-weight: bold; text-align: right;">{score_status}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #2a3550;">
                            <td style="padding: 12px 0; color: #8b949e;">Average Focus</td>
                            <td style="padding: 12px 0; color: #00ff9d; font-weight: bold; text-align: right;">{avg_focus:.1f}%</td>
                        </tr>
                        <tr>
                            <td style="padding: 12px 0; color: #8b949e;">Violations Detected</td>
                            <td style="padding: 12px 0; color: #ff4444; font-weight: bold; text-align: right;">{violations}</td>
                        </tr>
                    </table>
                </div>
                
                <p style="margin-top: 30px; font-size: 12px; color: #6e7681;">
                    © 2026 Focus Guard · AI Proctoring System
                </p>
            </div>
        </body>
        </html>
        """
        
        message = Mail(
            from_email=st.secrets.get("email_address", "noreply@focusguard.local"),
            to_emails=To(recipient_email),
            subject=subject,
            html_content=html_content
        )
        
        response = sg.send(message)
        return response.status_code in [200, 202]
        
    except Exception as e:
        return False
