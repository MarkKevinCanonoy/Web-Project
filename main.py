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
import google.generativeai as genai
from dotenv import load_dotenv

# --- configuration setup ---

# 1. load the variables from .env file
load_dotenv()

# 2. get keys safely
API_KEY = os.getenv("GOOGLE_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")

# 3. configure google ai
if not API_KEY:
    print("warning: google_api_key not found in .env file")
else:
    genai.configure(api_key=API_KEY)
    # Keeping your preferred model
    model = genai.GenerativeModel('gemma-3-12b-it')

# 4. database config
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
GOAL: Book appointments or give basic home-remedy advice.

RULES:
1. **Be Human:** Use natural language. Say "Oh no, I hope you feel better!" if they are sick.
2. **One-Liner:** If user says "Book checkup tomorrow 2pm", output JSON immediately.
3. **Time:** Convert "2pm" -> "14:00:00".
4. **Context:** Check "EXISTING APPOINTMENTS" below. If they say "Cancel it", use the ID from there.

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

# jwt configuration
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
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    return decode_token(token)

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
                print(f"created default user: {user['email']}")
        conn.commit()
    except Error as e:
        print(f"error seeding database: {e}")
    finally:
        cursor.close()
        conn.close()

# --- [FIXED] VALIDATION FUNCTION ---
# Used by both Manual Booking and AI.
def validate_booking_rules(cursor, date_str, time_str):
    """
    Returns None if valid.
    Returns error message string if invalid.
    """
    
    # 1. Parse Time
    try:
        if len(time_str) == 5:
            time_str += ":00"
        booking_time = datetime.strptime(time_str, "%H:%M:%S").time()
    except ValueError:
        return "Invalid time format."

    # 2. Clinic Hours Logic
    # 12:00 PM is Lunch (Closed)
    if booking_time.hour == 12:
        return "Clinic is closed for lunch from 12:00 PM to 1:00 PM."
    
    # 7:00 PM (19:00) onwards is Closed
    if booking_time.hour >= 19:
        return "Clinic is closed. Operations end at 7:00 PM."

    # Optional: Start Time (e.g., 8:00 AM)
    if booking_time.hour < 8:
        return "Clinic opens at 8:00 AM."

    # 3. The 1-Hour Gap Logic (SQL)
    # We check if the requested time matches any existing appointment within +/- 59 minutes.
    # We only check 'pending' or 'approved' statuses.
    cursor.execute("""
        SELECT id, appointment_time FROM appointments 
        WHERE appointment_date = %s 
        AND status IN ('pending', 'approved')
        AND (
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) > -3600 
            AND 
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) < 3600
        )
    """, (date_str, time_str, time_str))
    
    conflict = cursor.fetchone()
    if conflict:
        return f"Time slot conflict! There is already an appointment around {conflict['appointment_time']}. Please leave a 1-hour gap."

    return None # No errors

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

# --- pydantic models ---
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

# --- api routes ---

@app.post("/api/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="email already registered")
        
        hashed_pw = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, 'student')",
            (user.full_name, user.email, hashed_pw)
        )
        conn.commit()
        return {"message": "registration successful"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/api/admin/create-user")
def create_admin_user(user: AdminCreateUser, current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin':
        raise HTTPException(status_code=403, detail="only super admins can create admin accounts")
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="email already registered")
        
        hashed_pw = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)",
            (user.full_name, user.email, hashed_pw, user.role)
        )
        conn.commit()
        return {"message": f"user created successfully as {user.role}"}
    finally:
        cursor.close()
        conn.close()

@app.post("/api/login")
def login(user: UserLogin):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE email = %s", (user.email,))
        db_user = cursor.fetchone()
        
        if not db_user or not verify_password(user.password, db_user['password']):
            raise HTTPException(status_code=401, detail="invalid email or password")
        
        token = create_token(db_user['id'], db_user['role'], db_user['full_name'])
        
        return {
            "token": token,
            "role": db_user['role'],
            "user_id": db_user['id'],
            "full_name": db_user['full_name']
        }
    finally:
        cursor.close()
        conn.close()

@app.get("/api/appointments")
def get_appointments(current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if current_user['role'] == 'student':
            cursor.execute("""
                SELECT a.*, u.full_name as student_name
                FROM appointments a
                JOIN users u ON a.student_id = u.id
                WHERE a.student_id = %s
                ORDER BY a.appointment_date DESC, a.appointment_time DESC
            """, (current_user['user_id'],))
        else:
            cursor.execute("""
                SELECT a.*, u.full_name as student_name, u.email as student_email
                FROM appointments a
                JOIN users u ON a.student_id = u.id
                ORDER BY a.appointment_date DESC, a.appointment_time DESC
            """)
        
        results = cursor.fetchall()
        for row in results:
            row['appointment_date'] = str(row['appointment_date'])
            row['appointment_time'] = str(row['appointment_time'])
            
        return results
    finally:
        cursor.close()
        conn.close()

@app.post("/api/appointments")
def create_appointment(appointment: AppointmentCreate, current_user = Depends(get_current_user)):
    # 1. check if user is a student
    if current_user['role'] != 'student':
        raise HTTPException(status_code=403, detail="only students can book appointments")
    
    conn = get_db()
    # [FIX] Added buffered=True to prevent "Unread result found" error
    cursor = conn.cursor(dictionary=True, buffered=True) 
    try:
        # 2. Call Validation
        error_message = validate_booking_rules(cursor, appointment.appointment_date, appointment.appointment_time)
        
        if error_message:
            # We don't need to close cursor here because 'finally' block handles it
            raise HTTPException(status_code=400, detail=error_message)

        # 3. insert
        cursor.execute("""
            INSERT INTO appointments (student_id, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (
            current_user['user_id'], 
            appointment.appointment_date, 
            appointment.appointment_time, 
            appointment.service_type, 
            appointment.urgency, 
            appointment.reason, 
            appointment.booking_mode
        ))
        conn.commit()
        return {"message": "appointment booked successfully", "id": cursor.lastrowid}

    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/api/appointments/{appointment_id}")
def update_appointment(appointment_id: int, update: AppointmentUpdate, current_user = Depends(get_current_user)):
    if current_user['role'] not in ['admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="only admins can update appointments")
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT status FROM appointments WHERE id = %s", (appointment_id,))
        current_appt = cursor.fetchone()
        
        if not current_appt:
            raise HTTPException(status_code=404, detail="appointment not found")

        if update.status == 'completed' and current_appt['status'] == 'completed':
            raise HTTPException(status_code=400, detail="already_scanned")

        cursor.execute("""
            UPDATE appointments 
            SET status = %s, admin_note = %s, updated_at = NOW()
            WHERE id = %s
        """, (update.status, update.admin_note, appointment_id))
        conn.commit()
        
        return {"message": "appointment updated successfully"}
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/appointments/{appointment_id}")
def delete_or_cancel_appointment(appointment_id: int, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT student_id, status FROM appointments WHERE id = %s", (appointment_id,))
        appt = cursor.fetchone()
        
        if not appt:
            raise HTTPException(status_code=404, detail="appointment not found")

        if current_user['role'] in ['admin', 'super_admin']:
             cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
             message = "appointment permanently deleted."
        elif current_user['role'] == 'student':
            if appt['student_id'] != current_user['user_id']:
                raise HTTPException(status_code=403, detail="not authorized")

            if appt['status'] == 'pending':
                 cursor.execute("UPDATE appointments SET status = 'canceled', updated_at = NOW() WHERE id = %s", (appointment_id,))
                 message = "appointment canceled successfully"
            else:
                 cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
                 message = "appointment record deleted successfully"
        else:
             raise HTTPException(status_code=403, detail="action not allowed")
        
        conn.commit()
        return {"message": message}
    finally:
        cursor.close()
        conn.close()

@app.get("/api/users")
def get_users(current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin':
        raise HTTPException(status_code=403, detail="only super admins can view users")
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, full_name, email, role, created_at FROM users ORDER BY created_at DESC")
        results = cursor.fetchall()
        for row in results:
            row['created_at'] = str(row['created_at'])
        return results
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin':
        raise HTTPException(status_code=403, detail="only super admins can delete users")
    if current_user['user_id'] == user_id:
        raise HTTPException(status_code=400, detail="you cannot delete your own account")

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return {"message": "user deleted successfully"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
#  SMART AI CHATBOT V2 (OPTIMIZED)
# ==========================================

@app.post("/api/chat")
async def chat_booking(chat: ChatMessage, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)

    # step 1: get appointments context
    try:
        cursor.execute("""
            SELECT id, appointment_date, appointment_time, reason 
            FROM appointments 
            WHERE student_id = %s AND status IN ('pending', 'approved')
            ORDER BY appointment_date ASC
        """, (current_user['user_id'],))
        active_appts = cursor.fetchall()
        
        appt_list_text = ""
        if active_appts:
            for appt in active_appts:
                appt_list_text += f"- ID {appt['id']}: {appt['appointment_date']} at {appt['appointment_time']} (Reason: {appt['reason']})\n"
        else:
            appt_list_text = "None."
            
    finally:
        cursor.close()
        conn.close()

    # step 2: dynamic prompt
    final_instruction = f"""
    {BASE_INSTRUCTION}
    
    Student Name: {current_user['full_name']}
    Current Date: {datetime.now().strftime("%Y-%m-%d")}

    EXISTING APPOINTMENTS:
    {appt_list_text}
    """

    try:
        # step 3: build history
        # [OPTIMIZATION] Only take the last 6 messages to prevent 504 Timeouts
        history_for_google = [
            {"role": "user", "parts": [final_instruction]},
            {"role": "model", "parts": ["Understood. I'm Nurse Joy! How can I help? 😊"]}
        ]

        # Only use recent history to save tokens
        recent_msgs = chat.history[-6:] 
        for msg in recent_msgs:
            role = "user" if msg.get("role") == "user" else "model"
            history_for_google.append({
                "role": role,
                "parts": [msg.get("message", "")]
            })

        # step 4: generate response with RETRY LOGIC
        ai_text = "Sorry, I am busy."
        
        for attempt in range(3):
            try:
                chat_session = model.start_chat(history=history_for_google)
                response = chat_session.send_message(chat.message)
                ai_text = response.text
                break 
            except Exception as e:
                if "503" in str(e) or "504" in str(e) or "Timeout" in str(e):
                    print(f"Model overloaded (Attempt {attempt+1}/3). Retrying...")
                    time.sleep(1) 
                    continue
                else:
                    raise e 

        # step 5: check for json actions
        if "{" in ai_text and "}" in ai_text:
            try:
                # find the json part
                start = ai_text.find('{')
                end = ai_text.rfind('}') + 1
                json_str = ai_text[start:end]
                data = json.loads(json_str)

                # --- ACTION A: BOOKING ---
                if data.get("action") == "book_appointment":
                    conn = get_db()
                    # [FIX] Buffered here too
                    cursor = conn.cursor(dictionary=True, buffered=True)
                    
                    # Call Validation
                    error_message = validate_booking_rules(cursor, data['date'], data['time'])
                    
                    if error_message:
                        cursor.close()
                        conn.close()
                        return {"response": error_message, "requires_action": False}

                    # insert
                    cursor.execute("""
                        INSERT INTO appointments (student_id, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'ai_chatbot', 'pending')
                    """, (current_user['user_id'], data['date'], data['time'], data['service_type'], data['urgency'], data['reason']))
                    
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    success_msg = f"Booked for {data['date']} at {data['time']}!"
                    if data.get("ai_advice"):
                        success_msg += f"\n\n🩺 Nurse Joy says: {data['ai_advice']}"
                        
                    return {"response": success_msg, "requires_action": False}

                # --- ACTION B: CANCELING ---
                elif data.get("action") == "cancel_appointment":
                    appt_id = data.get("appointment_id")
                    
                    conn = get_db()
                    cursor = conn.cursor(buffered=True)
                    
                    cursor.execute("SELECT id FROM appointments WHERE id = %s AND student_id = %s", (appt_id, current_user['user_id']))
                    
                    if cursor.fetchone():
                        cursor.execute("UPDATE appointments SET status = 'canceled' WHERE id = %s", (appt_id,))
                        conn.commit()
                        msg = f"Appointment #{appt_id} canceled. Take care!"
                    else:
                        msg = f"I couldn't find Appointment #{appt_id}. Please check your list."
                        
                    cursor.close()
                    conn.close()
                    return {"response": msg, "requires_action": False}

            except Exception as e:
                print(f"json processing error: {e}")
                pass

        # normal reply
        return {"response": ai_text, "requires_action": False}

    except Exception as e:
        error_msg = str(e)
        print(f"ai error: {error_msg}")
        return {"response": "I'm having a little trouble connecting to the system. Please try again in a moment!", "requires_action": False}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)