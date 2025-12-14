from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
import bcrypt
import jwt
import os
import re 

# --- GLOBAL STATE STORAGE (In-Memory) ---
#chat_states: Dict[int, Dict] = {}

app = FastAPI()

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'kurt_cobain', 
    'database': 'school_clinic'
}

def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

# --- Helper Functions ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

# JWT conf
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
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
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    return decode_token(token)

def create_default_users():
    """Seed default admins"""
    print("Checking for default admin accounts...")
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
                print(f"Created default user: {user['email']} ({user['role']})")
        conn.commit()
    except Error as e:
        print(f"Error seeding database: {e}")
    finally:
        cursor.close()
        conn.close()

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

# --- Pydantic Models ---
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

# --- API routes ---

@app.post("/api/register")
def register(user: UserRegister):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")
        
        hashed_pw = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, 'student')",
            (user.full_name, user.email, hashed_pw)
        )
        conn.commit()
        return {"message": "Registration successful"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.post("/api/admin/create-user")
def create_admin_user(user: AdminCreateUser, current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin':
        raise HTTPException(status_code=403, detail="Only Super Admins can create admin accounts")
    
    if user.role not in ['admin', 'super_admin']:
        raise HTTPException(status_code=400, detail="Invalid role specified")

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (user.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already registered")
        
        hashed_pw = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)",
            (user.full_name, user.email, hashed_pw, user.role)
        )
        conn.commit()
        return {"message": f"User created successfully as {user.role}"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
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
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
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
    if current_user['role'] != 'student':
        raise HTTPException(status_code=403, detail="Only students can book appointments")
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        # INSERT matches schema ENUM('Normal', 'Urgent')
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
        return {"message": "Appointment booked successfully", "id": cursor.lastrowid}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.put("/api/appointments/{appointment_id}")
def update_appointment(appointment_id: int, update: AppointmentUpdate, current_user = Depends(get_current_user)):
    if current_user['role'] not in ['admin', 'super_admin']:
        raise HTTPException(status_code=403, detail="Only admins can update appointments")
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. check current status first
        cursor.execute("SELECT status FROM appointments WHERE id = %s", (appointment_id,))
        current_appt = cursor.fetchone()
        
        if not current_appt:
            raise HTTPException(status_code=404, detail="Appointment not found")

        # 2. plot hole fix: if already completed, stop!
        if update.status == 'completed' and current_appt['status'] == 'completed':
            raise HTTPException(status_code=400, detail="ALREADY_SCANNED")

        # 3. otherwise, update normally
        cursor.execute("""
            UPDATE appointments 
            SET status = %s, admin_note = %s, updated_at = NOW()
            WHERE id = %s
        """, (update.status, update.admin_note, appointment_id))
        conn.commit()
        
        return {"message": "Appointment updated successfully"}
    finally:
        cursor.close()
        conn.close()

@app.delete("/api/appointments/{appointment_id}")
def delete_or_cancel_appointment(appointment_id: int, current_user = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT student_id, status FROM appointments WHERE id = %s", (appointment_id,))
        appt = cursor.fetchone()
        
        if not appt:
            raise HTTPException(status_code=404, detail="Appointment not found")

        if current_user['role'] == 'student' and appt['student_id'] != current_user['user_id']:
            raise HTTPException(status_code=403, detail="Not authorized")

        if appt['status'] == 'pending':
             cursor.execute("UPDATE appointments SET status = 'canceled', updated_at = NOW() WHERE id = %s", (appointment_id,))
             message = "Appointment canceled successfully"
        else:
             cursor.execute("DELETE FROM appointments WHERE id = %s", (appointment_id,))
             message = "Appointment record deleted successfully"
        
        conn.commit()
        return {"message": message}
    finally:
        cursor.close()
        conn.close()

@app.get("/api/users")
def get_users(current_user = Depends(get_current_user)):
    if current_user['role'] != 'super_admin':
        raise HTTPException(status_code=403, detail="Only super admins can view users")
    
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
        raise HTTPException(status_code=403, detail="Only Super Admins can delete users")
    if current_user['user_id'] == user_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return {"message": "User deleted successfully"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ==========================================
#   logic based chatbot for booking appointments
# ==========================================
# global dictionary to store user states in memory
# --- helper: smart date calculator ---
def get_next_weekday(day_name):
    """
    Calculates the date for 'next monday', 'this friday', etc.
    """
    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, 
        "friday": 4, "saturday": 5, "sunday": 6,
        "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
    }
    
    target_day = days.get(day_name)
    if target_day is None: return None
    
    today = datetime.now()
    current_day = today.weekday()
    
    # calculate days to add
    days_ahead = target_day - current_day
    if days_ahead <= 0: # if today is Tuesday and user asks for Monday, go to next week
        days_ahead += 7
        
    future_date = today + timedelta(days=days_ahead)
    return future_date.strftime("%Y-%m-%d")

# global dictionary for memory
chat_states = {}

@app.post("/api/chat")
async def chat_booking(chat: ChatMessage, current_user = Depends(get_current_user)):
    """
    Smart Logic-Based Chatbot V2.
    Fixed: 'Medical Clearance' bug, Casual Chit-Chat, and robust extraction.
    """
    
    # 1. Access Control
    if current_user['role'] != 'student':
        return {"response": "Sorry, only students can book appointments.", "requires_action": False}

    user_id = current_user['user_id']
    message = chat.message.strip().lower()

    # 2. Initialize State
    if user_id not in chat_states:
        chat_states[user_id] = {"step": "idle", "data": {}}

    state = chat_states[user_id]
    current_data = state["data"]
    
    # --- Reset/Cancel Logic (High Priority) ---
    if any(w in message for w in ["cancel", "stop", "reset", "wrong", "change"]):
        chat_states[user_id] = {"step": "idle", "data": {}}
        return {"response": "Okay, I've reset everything. 🔄 \n\nHow can I help you?", "requires_action": False}

    # --- Casual Chit-Chat Logic (High Priority) ---
    # Only if we are not in the middle of saving or deep in a flow
    if state["step"] == "idle" or len(current_data) == 0:
        if any(w in message for w in ["thank", "thanks", "salamat", "arigato"]):
            return {"response": "You're very welcome! 💙 Stay healthy!", "requires_action": False}
        
        if any(w in message for w in ["bye", "goodbye", "see you"]):
            return {"response": "Goodbye! Take care! 👋", "requires_action": False}
        
        greetings = ["good morning", "good afternoon", "good evening", "hi", "hello", "hey", "musta"]
        if any(g in message for g in greetings):
             # If they just said "Good morning", greet them. 
             # If they said "Good morning I need a checkup", we continue to extraction.
            intent_keywords = ["book", "appointment", "schedule", "clearance", "consultation", "medical"]
            if not any(k in message for k in intent_keywords):
                return {"response": "Hello! 👋 How can I help you today? \n\nYou can say 'I need a medical clearance' or 'Book a consultation'.", "requires_action": False}

    # ==================================================
    # STEP 1: SMART EXTRACTION (The Brain 🧠)
    # ==================================================

    # A. Service Detection (FIXED: Check 'clearance' BEFORE 'medical')
    if "clearance" in message:
        current_data["service_type"] = "Medical Clearance"
    elif "consultation" in message or "checkup" in message or "check-up" in message:
        current_data["service_type"] = "Medical Consultation"
    elif "medical" in message and "service_type" not in current_data:
        # If they just say "medical appointment", assume consultation but it's weak
        current_data["service_type"] = "Medical Consultation"

    # B. Urgency Detection
    if "urgent" in message or "emergency" in message or "pain" in message or "asap" in message:
        current_data["urgency"] = "Urgent"
    elif "normal" in message or "routine" in message:
        current_data["urgency"] = "Normal"

    # C. Date Detection
    if "tomorrow" in message:
        current_data["appointment_date"] = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "today" in message:
        current_data["appointment_date"] = datetime.now().strftime("%Y-%m-%d")
    else:
        # Regex for YYYY-MM-DD
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', message)
        if date_match:
            current_data["appointment_date"] = date_match.group(1)
        else:
            # Day names (Monday, Tuesday...)
            days_list = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            for day in days_list:
                if day in message:
                    smart_date = get_next_weekday(day)
                    if smart_date:
                        current_data["appointment_date"] = smart_date
                    break

    # D. Time Detection
    # 12-hour format (e.g., 2:30pm, 2pm, 2 pm)
    ampm_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', message)
    # 24-hour format (e.g., 14:00)
    military_match = re.search(r'(\d{1,2}):(\d{2})(?!\s*(?:am|pm))', message)

    if ampm_match:
        h, m = int(ampm_match.group(1)), int(ampm_match.group(2) or 0)
        p = ampm_match.group(3)
        if 1 <= h <= 12 and 0 <= m <= 59:
            if p == "pm" and h != 12: h += 12
            elif p == "am" and h == 12: h = 0
            current_data["appointment_time"] = f"{h:02d}:{m:02d}:00"
    elif military_match:
        h, m = int(military_match.group(1)), int(military_match.group(2))
        if 0 <= h <= 23 and 0 <= m <= 59:
            current_data["appointment_time"] = f"{h:02d}:{m:02d}:00"

    # E. Reason Detection
    if "because" in message:
        parts = message.split("because", 1)
        if len(parts) > 1: current_data["reason"] = parts[1].strip()
    elif state["step"] == "asking_reason" and "reason" not in current_data:
        current_data["reason"] = chat.message # If explicitly asked, take the whole input

    # Save updates back to state
    chat_states[user_id]["data"] = current_data

    # ==================================================
    # STEP 2: DETERMINE NEXT ACTION (The Flow 🌊)
    # ==================================================
    
    # If idle, check if we should start
    if state["step"] == "idle":
        if len(current_data) > 0 or any(w in message for w in ["book", "schedule", "visit"]):
            state["step"] = "check_requirements"

    # ==================================================
    # STEP 3: TRAFFIC CONTROLLER (What is missing?)
    # ==================================================
    
    if state["step"] not in ["idle", "saving"]:
        data = state["data"]
        
        # 1. Missing Service
        if "service_type" not in data:
            chat_states[user_id]["step"] = "asking_service"
            return {"response": "I can help! 🩺\n\nIs this for a **Medical Consultation** or **Medical Clearance**?", "requires_action": False}
        
        # 2. Missing Date
        if "appointment_date" not in data:
            chat_states[user_id]["step"] = "asking_date"
            return {"response": f"Okay, a {data['service_type']}. 🗓️\n\nWhen would you like to come? (e.g., 'Tomorrow', 'Next Monday', or '2025-10-20')", "requires_action": False}

        # 3. Missing Time
        if "appointment_time" not in data:
            chat_states[user_id]["step"] = "asking_time"
            return {"response": f"Got it: {data['appointment_date']}. 🕒\n\nWhat time? (e.g., '2pm' or '10:00 am')", "requires_action": False}

        # 4. Missing Urgency
        if "urgency" not in data:
            chat_states[user_id]["step"] = "asking_urgency"
            return {"response": "Is this condition **Normal** or **Urgent**?", "requires_action": False}

        # 5. Missing Reason
        if "reason" not in data:
            chat_states[user_id]["step"] = "asking_reason"
            return {"response": "Last step! 📝\n\nPlease briefly describe the **reason** for your visit.", "requires_action": False}

        # All data present -> Move to Saving
        state["step"] = "saving"

    # ==================================================
    # STEP 4: SAVE TO DATABASE (With Conflict Check)
    # ==================================================
    if state["step"] == "saving":
        data = state["data"]
        conn = get_db()
        cursor = conn.cursor(buffered=True)
        
        try:
            # 1. Availability Check
            cursor.execute("""
                SELECT id FROM appointments 
                WHERE appointment_date = %s AND appointment_time = %s AND status != 'canceled'
            """, (data['appointment_date'], data['appointment_time']))
            
            if cursor.fetchone():
                # Slot is taken
                del chat_states[user_id]["data"]["appointment_time"]
                chat_states[user_id]["step"] = "asking_time"
                cursor.close()
                conn.close()
                return {
                    "response": f"⚠️ **Slot Taken!**\n\nThe time {data['appointment_time']} on {data['appointment_date']} is already booked.\n\nPlease choose a different time.", 
                    "requires_action": False
                }

            # 2. Insert Appointment
            cursor.execute("""
                INSERT INTO appointments (student_id, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'ai_chatbot', 'pending')
            """, (
                user_id, data['appointment_date'], data['appointment_time'], 
                data['service_type'], data['urgency'], data['reason']
            ))
            conn.commit()
            
            # Format time nicely for display
            display_time = datetime.strptime(data['appointment_time'], "%H:%M:%S").strftime("%I:%M %p")

            final_response = (
                f"🎉 **Booked Successfully!**\n\n"
                f"🩺 **Service:** {data['service_type']}\n"
                f"📅 **Date:** {data['appointment_date']}\n"
                f"🕒 **Time:** {display_time}\n"
                f"📝 **Reason:** {data['reason']}\n\n"
                "See you at the clinic! 💙"
            )
            
            # Reset state for next interaction
            chat_states[user_id] = {"step": "idle", "data": {}}
            return {"response": final_response, "requires_action": False}

        except Exception as e:
            print(f"DB Error: {e}")
            return {"response": "System error. Please try again later.", "requires_action": False}
        finally:
            if 'cursor' in locals() and cursor: cursor.close()
            if 'conn' in locals() and conn: conn.close()

    return {"response": "I didn't quite catch that. Try saying 'reset' if you're stuck.", "requires_action": False}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)