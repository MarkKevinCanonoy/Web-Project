from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict
from datetime import datetime, timedelta, time as dt_time
import mysql.connector
from mysql.connector import Error
import bcrypt
import jwt
import os
import json
import time 
import re
import google.generativeai as genai
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage  

# --- configuration setup ---

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

if not API_KEY:
    print("warning: google_api_key not found in .env file")
else:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemma-3-12b-it')

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'kurt_cobain', 
    'database': 'school_clinic'
}

# --- OPTIMIZATION: REAL RECEPTIONIST PERSONA ---

BASE_INSTRUCTION = """
SYSTEM: You are the School Clinic Receptionist (Nurse Joy).
PERSONA: Warm, caring, efficient, and professional.
GOAL: Book appointments, but ONLY when you have ALL necessary details.

RULES:
1. **Be Human:** Use natural language. Say "Oh no, I hope you feel better!" if they are sick.

2. **CHECK AVAILABILITY (CRITICAL):** - I (the System) will check the database for you.
   - Look for a line starting with "[SYSTEM INFO]" at the bottom of this prompt.
   - **IF [SYSTEM INFO] IS PRESENT:** You MUST list ONLY the times shown there. Do not add or guess other times.
   - **IF [SYSTEM INFO] IS MISSING/EMPTY:** It means you (the AI) or the System could not understand the date. **DO NOT GUESS TIMES.** Instead, ask the user: "Could you please type the date in YYYY-MM-DD format (e.g. 2025-12-20) so I can check the schedule?"

3. **MANDATORY CHECKLIST:** Before generating the booking JSON, you MUST verify you have ALL 5 items:
   - [ ] Date (e.g., tomorrow, next monday)
   - [ ] Time (e.g., 2pm)
   - [ ] Service Type (Medical Consultation OR Medical Clearance)
   - [ ] Urgency (Normal OR Urgent)
   - [ ] Reason (e.g., headache, fever, enrollment)

4. **One-Liner Exception:** ONLY output JSON immediately if the user provided EVERYTHING in one sentence. 

5. **Context:** Check "EXISTING APPOINTMENTS" below. If they say "Cancel it", use the ID from there.

🔴 CRITICAL: FOR ACTIONS, OUTPUT RAW JSON ONLY. NO MARKDOWN.

[BOOKING FORMAT]
{
  "action": "book_appointment",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:00",
  "reason": "short reason",
  "service_type": "Medical Consultation", 
  "urgency": "Normal",
  "ai_advice": "Short friendly advice."
}

[CANCEL FORMAT]
{
  "action": "cancel_appointment",
  "appointment_id": 123
}
"""

# --- helper functions ---

def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        raise HTTPException(status_code=500, detail=f"database connection failed: {str(e)}")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def parse_relative_date(date_str):
    today = datetime.now()
    date_str = date_str.lower().strip()

    if date_str == "today":
        return today.strftime("%Y-%m-%d")
    
    if date_str == "tomorrow":
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    for i, day in enumerate(weekdays):
        if day in date_str:
            days_ahead = (i - today.weekday() + 7) % 7
            if days_ahead == 0: 
                days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            return target_date.strftime("%Y-%m-%d")

    return date_str

# [NEW] CENTRALIZED SLOT CALCULATOR
def calculate_available_slots(conn, date_str):
    cursor = conn.cursor(dictionary=True)
    try:
        now = datetime.now()
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return [] 

        is_today = (req_date == now.date())
        current_time = now.time()

        # 8 AM to 5 PM
        possible_hours = [8, 9, 10, 11, 13, 14, 15, 16] 
        
        cursor.execute("""
            SELECT appointment_time FROM appointments 
            WHERE appointment_date = %s 
            AND status IN ('pending', 'approved')
        """, (date_str,))
        
        taken_start_times = []
        for row in cursor.fetchall():
            seconds = int(row['appointment_time'].total_seconds())
            h = seconds // 3600
            m = (seconds % 3600) // 60
            taken_dt = datetime.combine(req_date, dt_time(h, m, 0))
            taken_start_times.append(taken_dt)

        available = []

        for h in possible_hours:
            for m in [0, 30]:
                slot_time = dt_time(h, m, 0)
                slot_dt = datetime.combine(req_date, slot_time)
                
                # Check Overlap (1 hour gap)
                is_blocked = False
                for taken_dt in taken_start_times:
                    taken_end = taken_dt + timedelta(hours=1)
                    if taken_dt <= slot_dt < taken_end:
                        is_blocked = True
                        break
                
                if is_blocked:
                    continue 

                # Check Past Time
                if is_today:
                    if slot_time <= current_time:
                        continue 
                
                # Format: "08:30 AM" (Single AM/PM)
                ampm = "AM" if h < 12 else "PM"
                display_h = h if h <= 12 else h - 12
                display_h = 12 if display_h == 0 else display_h
                
                # Ensure clean formatting
                nice_time = f"{display_h:02d}:{m:02d} {ampm}"
                available.append(nice_time)

        return available
    finally:
        cursor.close()

ALGORITHM = "HS256"
security = HTTPBearer()

def create_token(user_id: int, role: str, full_name: str) -> str:
    payload = {
        'user_id': user_id,
        'role': role,
        'full_name': full_name,
        'exp': datetime.utcnow() + timedelta(days=7)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    return decode_token(credentials.credentials)

def create_default_users():
    conn = get_db()
    cursor = conn.cursor()
    try:
        default_users = [
            {"full_name": "Super Admin", "email": "superadmin@clinic.com", "password": "admin123", "role": "super_admin"},
            {"full_name": "Clinic Admin", "email": "admin@clinic.com", "password": "admin123", "role": "admin"}
        ]
        for user in default_users:
            cursor.execute("SELECT id FROM users WHERE email = %s", (user['email'],))
            if not cursor.fetchone():
                hashed_pw = hash_password(user['password'])
                cursor.execute(
                    "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)",
                    (user['full_name'], user['email'], hashed_pw, user['role'])
                )
        conn.commit()
    except: pass
    finally:
        cursor.close()
        conn.close()

def validate_booking_rules(cursor, date_str, time_str):
    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if booking_date < datetime.now().date():
            return "You cannot book appointments in the past."
        if booking_date.weekday() == 6: 
            return "The clinic is closed on Sundays."
    except ValueError:
        return "Invalid date format. Please use YYYY-MM-DD."

    try:
        # Clean up time string if it has AM/PM
        clean_time = time_str.upper().replace(" AM", "").replace(" PM", "").strip()
        
        # If it was "8:00 AM", clean_time is "8:00". Now parse it.
        if "AM" in time_str.upper() or "PM" in time_str.upper():
             t = datetime.strptime(time_str, "%I:%M %p").time()
        else:
             if len(time_str) == 5: time_str += ":00"
             t = datetime.strptime(time_str, "%H:%M:%S").time()
        
        booking_time = t
    except ValueError:
        return "Invalid time format."

    if booking_time.hour == 12:
        return "Clinic is closed for lunch from 12:00 PM to 1:00 PM."
    if booking_time.hour >= 19:
        return "Clinic is closed. Operations end at 7:00 PM."
    if booking_time.hour < 8:
        return "Clinic opens at 8:00 AM."

    # Convert back to HH:MM:SS for SQL comparison
    sql_time_str = booking_time.strftime("%H:%M:%S")

    cursor.execute("""
        SELECT id, appointment_time FROM appointments 
        WHERE appointment_date = %s 
        AND status IN ('pending', 'approved')
        AND (
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) > -3600 
            AND 
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) < 3600
        )
    """, (date_str, sql_time_str, sql_time_str))
    
    if cursor.fetchone():
        return f"Time slot conflict! Please select a different time."

    return None 

def send_email_notification(to_email: str, student_name: str, status: str, date: str, time: str, note: str = ""):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return

    subject = f"Appointment Update: {status.upper()}"
    if status == 'approved':
        color, msg_body = "#2ecc71", f"Your appointment on <strong>{date}</strong> at <strong>{time}</strong> is <strong>APPROVED</strong>."
    elif status == 'rejected':
        color, msg_body = "#e74c3c", f"Your appointment request for {date} was <strong>REJECTED</strong>."
    elif status == 'noshow':
        color, msg_body = "#607d8b", f"You missed your appointment on {date}. Marked as <strong>NO SHOW</strong>."
    else: return 

    html_content = f"""
    <html><body>
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #eee; border-radius: 10px; max-width: 500px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <img src="cid:clinic_logo" alt="Clinic Logo" style="width: 80px; height: 80px; border-radius: 50%;">
            </div>
            <h2 style="color: {color}; text-align: center;">{subject}</h2>
            <p>Hello <strong>{student_name}</strong>,</p>
            <p>{msg_body}</p>
            {f'<div style="background: #f9f9f9; padding: 10px; border-left: 4px solid {color}; margin: 15px 0;"><strong>Note:</strong><br>{note}</div>' if note else ''}
            <p style="font-size: 0.9rem; color: #888; margin-top: 20px; text-align: center;">School Clinic Portal</p>
        </div>
    </body></html>
    """

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))

        if os.path.exists("images/logo.jpg"):
            with open("images/logo.jpg", 'rb') as f:
                image = MIMEImage(f.read())
                image.add_header('Content-ID', '<clinic_logo>') 
                image.add_header('Content-Disposition', 'inline', filename='logo.jpg')
                msg.attach(image)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Email error: {e}")

# --- main app setup ---
app = FastAPI()

@app.on_event("startup")
def on_startup():
    create_default_users()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserRegister(BaseModel):
    full_name: str
    email: EmailStr
    password: str

class AdminCreateUser(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: str 

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class AppointmentCreate(BaseModel):
    appointment_date: str
    appointment_time: str
    service_type: str
    urgency: str
    reason: str
    booking_mode: str = "standard"

class AppointmentUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None

class ChatMessage(BaseModel):
    message: str
    history: List[dict] = []

class AppointmentReschedule(BaseModel):
    appointment_date: str
    appointment_time: str     

@app.post("/api/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone(): raise HTTPException(status_code=400, detail="email already registered")
        hashed_pw = hash_password(user.password)
        cursor.execute("INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, 'student')", (user.full_name, user.email, hashed_pw))
        conn.commit()
        return {"message": "success"}
    finally: cursor.close(); conn.close()

@app.post("/api/admin/create-user")
def create_admin_user(user: AdminCreateUser, current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin': raise HTTPException(status_code=403, detail="unauthorized")
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone(): raise HTTPException(status_code=400, detail="email already registered")
        hashed_pw = hash_password(user.password)
        cursor.execute("INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)", (user.full_name, user.email, hashed_pw, user.role))
        conn.commit()
        return {"message": "success"}
    finally: cursor.close(); conn.close()

@app.post("/api/login")
def login(user: UserLogin):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE email = %s", (user.email,))
        db_user = cursor.fetchone()
        if not db_user or not verify_password(user.password, db_user['password']): raise HTTPException(status_code=401, detail="invalid credentials")
        return {"token": create_token(db_user['id'], db_user['role'], db_user['full_name']), "role": db_user['role'], "user_id": db_user['id'], "full_name": db_user['full_name']}
    finally: cursor.close(); conn.close()

@app.get("/api/appointments")
def get_appointments(current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if current_user['role'] == 'student':
            cursor.execute("SELECT a.*, u.full_name as student_name FROM appointments a JOIN users u ON a.student_id = u.id WHERE a.student_id = %s ORDER BY a.appointment_date DESC", (current_user['user_id'],))
        else:
            cursor.execute("SELECT a.*, u.full_name as student_name, u.email as student_email FROM appointments a JOIN users u ON a.student_id = u.id ORDER BY a.appointment_date DESC")
        
        results = cursor.fetchall()
        for row in results:
            row['appointment_date'] = str(row['appointment_date'])
            row['appointment_time'] = str(row['appointment_time'])
        return results
    finally: cursor.close(); conn.close()

@app.get("/api/slots")
def get_available_slots_endpoint(date: str):
    conn = get_db()
    try:
        return calculate_available_slots(conn, date)
    finally: conn.close()

@app.post("/api/appointments")
def create_appointment(appointment: AppointmentCreate, current_user = Depends(get_current_user)):
    if current_user['role'] != 'student': raise HTTPException(status_code=403, detail="students only")
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True) 
    try:
        error_message = validate_booking_rules(cursor, appointment.appointment_date, appointment.appointment_time)
        if error_message: raise HTTPException(status_code=400, detail=error_message)

        # Handle time format conversion
        t_str = appointment.appointment_time
        if "AM" in t_str or "PM" in t_str:
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        cursor.execute("INSERT INTO appointments (student_id, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status) VALUES (%s, %s, %s, %s, %s, %s, 'standard', 'pending')", (current_user['user_id'], appointment.appointment_date, t_str, appointment.service_type, appointment.urgency, appointment.reason))
        conn.commit()
        return {"message": "booked", "id": cursor.lastrowid}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

@app.put("/api/appointments/{appointment_id}")
def update_appointment(appointment_id: int, update: AppointmentUpdate, current_user = Depends(get_current_user)):
    if current_user['role'] not in ['admin', 'super_admin']: raise HTTPException(status_code=403, detail="unauthorized")
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT a.status, a.appointment_date, a.appointment_time, u.email, u.full_name FROM appointments a JOIN users u ON a.student_id = u.id WHERE a.id = %s", (appointment_id,))
        current_appt = cursor.fetchone()
        if not current_appt: raise HTTPException(status_code=404, detail="not found")
        
        if update.status == 'completed' and current_appt['status'] == 'completed': raise HTTPException(status_code=400, detail="already_scanned")

        cursor.execute("UPDATE appointments SET status = %s, admin_note = %s, updated_at = NOW() WHERE id = %s", (update.status, update.admin_note, appointment_id))
        conn.commit()
        
        if update.status in ['approved', 'rejected', 'noshow']:
            d_str = current_appt['appointment_date'].strftime("%B %d, %Y")
            raw_time = current_appt['appointment_time']
            seconds = int(raw_time.total_seconds())
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            ampm = "AM"
            if hours >= 12:
                ampm = "PM"
                if hours > 12: hours -= 12
            if hours == 0: hours = 12
            t_str = f"{hours}:{minutes:02d} {ampm}"
            
            send_email_notification(current_appt['email'], current_appt['full_name'], update.status, d_str, t_str, update.admin_note)

        return {"message": "updated"}
    finally: cursor.close(); conn.close()

@app.put("/api/appointments/{appointment_id}/reschedule")
def reschedule_appointment(appointment_id: int, r: AppointmentReschedule, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT student_id FROM appointments WHERE id = %s", (appointment_id,))
        appt = cursor.fetchone()
        if not appt or appt['student_id'] != current_user['user_id']: raise HTTPException(status_code=403, detail="unauthorized")

        error_msg = validate_booking_rules(cursor, r.appointment_date, r.appointment_time)
        if error_msg: raise HTTPException(status_code=400, detail=error_msg)

        cursor.execute("UPDATE appointments SET appointment_date = %s, appointment_time = %s, status = 'pending', updated_at = NOW() WHERE id = %s", (r.appointment_date, r.appointment_time, appointment_id))
        conn.commit()
        return {"message": "rescheduled"}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

@app.delete("/api/appointments/{appointment_id}")
def delete_or_cancel_appointment(appointment_id: int, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT student_id, status FROM appointments WHERE id = %s", (appointment_id,))
        appt = cursor.fetchone()
        if not appt: raise HTTPException(status_code=404, detail="not found")

        if current_user['role'] in ['admin', 'super_admin']:
             cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
             message = "deleted"
        elif current_user['role'] == 'student':
            if appt['student_id'] != current_user['user_id']: raise HTTPException(status_code=403, detail="unauthorized")
            if appt['status'] == 'pending':
                 cursor.execute("UPDATE appointments SET status = 'canceled', updated_at = NOW() WHERE id = %s", (appointment_id,))
                 message = "canceled"
            else:
                 cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
                 message = "deleted"
        else: raise HTTPException(status_code=403, detail="unauthorized")
        
        conn.commit()
        return {"message": message}
    finally: cursor.close(); conn.close()

@app.get("/api/users")
def get_users(current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin': raise HTTPException(status_code=403, detail="unauthorized")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, full_name, email, role, created_at FROM users ORDER BY created_at DESC")
        results = cursor.fetchall()
        for row in results: row['created_at'] = str(row['created_at'])
        return results
    finally: cursor.close(); conn.close()

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin': raise HTTPException(status_code=403, detail="unauthorized")
    if current_user['user_id'] == user_id: raise HTTPException(status_code=400, detail="cannot delete self")
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return {"message": "deleted"}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

# ==========================================
#  SMART AI CHATBOT V2 (OPTIMIZED)
# ==========================================

@app.post("/api/chat")
async def chat_booking(chat: ChatMessage, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT id, appointment_date, appointment_time, reason FROM appointments WHERE student_id = %s AND status IN ('pending', 'approved') ORDER BY appointment_date ASC", (current_user['user_id'],))
        active_appts = cursor.fetchall()
        appt_text = "\n".join([f"- ID {a['id']}: {a['appointment_date']} at {a['appointment_time']}" for a in active_appts]) if active_appts else "None."
    finally: cursor.close(); conn.close()

    system_slot_info = ""
    target_date_str = None
    msg_lower = chat.message.lower()
    
    # 1. Regex for "December 20, 2025" or "Dec 20"
    # Matches: (FullMonth or 3-letter) (Space) (Day), (Optional Year)
    regex_verbose = r"([a-zA-Z]+)\s+(\d{1,2})(?:,\s*(\d{4}))?"
    match_verbose = re.search(regex_verbose, chat.message)
    
    # 2. Regex for standard "2025-12-20"
    match_iso = re.search(r'\d{4}-\d{2}-\d{2}', chat.message)

    if match_iso:
        target_date_str = match_iso.group(0)
    elif match_verbose:
        # Convert "December 20" to "2025-12-20"
        try:
            month_str = match_verbose.group(1)
            day_str = match_verbose.group(2)
            year_str = match_verbose.group(3) or str(datetime.now().year)
            
            # Parse using datetime
            dt_obj = datetime.strptime(f"{month_str} {day_str} {year_str}", "%B %d %Y")
            target_date_str = dt_obj.strftime("%Y-%m-%d")
        except:
            # Fallback for short months like "Dec"
            try:
                dt_obj = datetime.strptime(f"{month_str} {day_str} {year_str}", "%b %d %Y")
                target_date_str = dt_obj.strftime("%Y-%m-%d")
            except:
                pass # Failed to parse date string

    # 3. Check for keywords if regex failed
    if not target_date_str:
        if any(x in msg_lower for x in ['today', 'tomorrow', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday']):
            words = msg_lower.split()
            for w in words:
                if w in ['today', 'tomorrow', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    target_date_str = parse_relative_date(w)
                    break
    
    if target_date_str:
        conn = get_db()
        slots = calculate_available_slots(conn, target_date_str)
        conn.close()
        system_slot_info = f"\n[SYSTEM INFO] Available slots for {target_date_str}: {', '.join(slots)}" if slots else f"\n[SYSTEM INFO] No slots for {target_date_str}."

    final_instruction = f"{BASE_INSTRUCTION}\nStudent: {current_user['full_name']}\nDate: {datetime.now().strftime('%Y-%m-%d')}\nAppts: {appt_text}\n{system_slot_info}"

    try:
        history_for_google = [{"role": "user", "parts": [final_instruction]}, {"role": "model", "parts": ["Understood."]}]
        for msg in chat.history[-6:]:
            history_for_google.append({"role": "user" if msg.get("role")=="user" else "model", "parts": [msg.get("message", "")]})

        ai_text = "Sorry, busy."
        for _ in range(3):
            try:
                chat_session = model.start_chat(history=history_for_google)
                response = chat_session.send_message(chat.message)
                ai_text = response.text
                break
            except: time.sleep(1)

        if "{" in ai_text and "}" in ai_text:
            try:
                json_str = ai_text[ai_text.find('{'):ai_text.rfind('}')+1]
                data = json.loads(json_str)
                if data.get("action") == "book_appointment":
                    conn = get_db()
                    cursor = conn.cursor(dictionary=True, buffered=True)
                    p_date = parse_relative_date(data['date'])
                    p_time = data['time']
                    if "AM" in p_time or "PM" in p_time:
                        p_time = datetime.strptime(p_time, "%I:%M %p").strftime("%H:%M:%S")
                    
                    err = validate_booking_rules(cursor, p_date, p_time)
                    if err: return {"response": err, "requires_action": False}
                    
                    cursor.execute("INSERT INTO appointments (student_id, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status) VALUES (%s, %s, %s, %s, %s, %s, 'ai_chatbot', 'pending')", (current_user['user_id'], p_date, p_time, data['service_type'], data['urgency'], data['reason']))
                    conn.commit()
                    return {"response": f"✅ Booked for {p_date} at {data['time']}!"}
                
                elif data.get("action") == "cancel_appointment":
                    # ... cancellation logic ...
                    pass
            except: pass

        return {"response": ai_text}
    except Exception as e:
        print(e)
        return {"response": "System error."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)