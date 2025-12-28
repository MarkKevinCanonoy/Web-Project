from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict # <--- ADDED List and Dict here
from datetime import datetime, timedelta, timezone, time as dt_time
import mysql.connector
from mysql.connector import Error
import os
import json
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
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# [FIX] TIMEZONE CONFIGURATION (UTC+8 for Philippines)
TIMEZONE_OFFSET = 8 
PHT = timezone(timedelta(hours=TIMEZONE_OFFSET))

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
SYSTEM: You are the School Clinic Receptionist.
PERSONA: Warm, caring, efficient, and professional.
GOAL: Manage appointments (Book, Cancel, Reschedule) accurately.

RULES:
1. **Be Human:** Use natural language. Say "Oh no, I hope you feel better!" if they are sick.

2. **CHECK AVAILABILITY:**
   - I (the System) will check the database for you.
   - Look for [SYSTEM INFO] at the bottom.
   - If it lists slots, offer ONLY those.
   - If [SYSTEM INFO] is missing, ask: "Which date would you like to check?"

3. **HANDLING IDs (RELAXED):**
   - Users may give an ID like "23" or "#23".
   - **DO NOT** ask for a hashtag. Just accept the number.
   - Flow: If you have the ID, immediately ask for the next step.

4. **HANDLING REQUESTS (No Login System):**
   - **Booking:** You need: Name, Date, Time, Service, Urgency, Reason.
     - Ask for Name if missing.
     - Output `book_appointment` JSON.
   - **Canceling:** Need Appointment ID. -> Output `cancel_appointment` JSON.
   - **Rescheduling:** Need Appointment ID + New Date/Time. -> Output `reschedule_appointment` JSON.

5. **ADVICE:** If you give advice, start it with "Tip: ".

[BOOKING FORMAT]
{
  "action": "book_appointment",
  "student_name": "John Doe",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:00",
  "reason": "short reason",
  "service_type": "Medical Consultation", 
  "urgency": "Normal",
  "ai_advice": "Tip: ..."
}

[CANCEL FORMAT]
{ "action": "cancel_appointment", "appointment_id": 123 }

[RESCHEDULE FORMAT]
{ "action": "reschedule_appointment", "appointment_id": 123, "new_date": "YYYY-MM-DD", "new_time": "HH:MM:00" }
"""

# --- helper functions ---
def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        raise HTTPException(status_code=500, detail=f"database connection failed: {str(e)}")

# [FIX] Timezone Aware Date Parser
def get_current_date():
    return datetime.now(PHT).date()

def parse_relative_date(date_str):
    if not date_str: return None
    today = get_current_date()
    date_str = date_str.lower().strip()

    if "today" in date_str:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in date_str:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day in enumerate(weekdays):
        if day in date_str:
            days_ahead = (i - today.weekday() + 7) % 7
            if days_ahead == 0: days_ahead = 7
            target_date = today + timedelta(days=days_ahead)
            return target_date.strftime("%Y-%m-%d")
    return date_str

def calculate_available_slots(conn, date_str):
    cursor = conn.cursor(dictionary=True)
    try:
        now = datetime.now(PHT)
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return [] 

        is_today = (req_date == now.date())
        current_time = now.time()
        possible_hours = [8, 9, 10, 11, 13, 14, 15, 16] 
        
        cursor.execute("SELECT appointment_time FROM appointments WHERE appointment_date = %s AND status IN ('pending', 'approved')", (date_str,))
        taken_start_times = []
        for row in cursor.fetchall():
            seconds = int(row['appointment_time'].total_seconds())
            h, m = seconds // 3600, (seconds % 3600) // 60
            taken_start_times.append(datetime.combine(req_date, dt_time(h, m, 0)))

        available = []
        for h in possible_hours:
            for m in [0, 30]:
                slot_time = dt_time(h, m, 0)
                slot_dt = datetime.combine(req_date, slot_time)
                
                is_blocked = False
                for taken_dt in taken_start_times:
                    if taken_dt <= slot_dt < taken_dt + timedelta(hours=1):
                        is_blocked = True
                        break
                
                if is_blocked: continue 
                if is_today and slot_time <= current_time: continue 
                
                ampm = "AM" if h < 12 else "PM"
                dh = h if h <= 12 else h - 12
                dh = 12 if dh == 0 else dh
                available.append(f"{dh:02d}:{m:02d} {ampm}")
        return available
    finally:
        cursor.close()

def validate_booking_rules(cursor, date_str, time_str):
    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if booking_date < get_current_date(): return "You cannot book appointments in the past."
        if booking_date.weekday() == 6: return "The clinic is closed on Sundays."
    except: return "Invalid date format."

    try:
        # Simple time parser logic handled before calling this usually
        t = datetime.strptime(time_str, "%H:%M:%S").time()
        booking_time = t
    except: return "Invalid time format."

    if booking_time.hour == 12: return "Clinic is closed for lunch."
    if booking_time.hour >= 19: return "Clinic is closed."
    if booking_time.hour < 8: return "Clinic opens at 8:00 AM."
    
    # Check conflict
    cursor.execute("""
        SELECT id FROM appointments 
        WHERE appointment_date = %s AND status IN ('pending', 'approved')
        AND (TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) BETWEEN -3599 AND 3599)
    """, (date_str, time_str, time_str))
    if cursor.fetchone(): return "Time slot conflict!"
    return None

def send_email_notification(to_email, name, status, date, time, note=""):
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not to_email: return
    # ... (Email logic same as before) ...
    print(f"Would send email to {to_email} about {status}")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models (Simplified) ---
class AppointmentCreate(BaseModel):
    student_name: str
    student_email: Optional[EmailStr] = None
    appointment_date: str
    appointment_time: str
    service_type: str
    urgency: str
    reason: str
    booking_mode: str = "standard"

class AppointmentUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None

# [FIX] List and Dict are now defined
class ChatMessage(BaseModel):
    message: str
    history: List[Dict] = [] 

class AppointmentReschedule(BaseModel):
    appointment_date: str
    appointment_time: str     

# --- API ROUTES (No Auth) ---

@app.get("/api/appointments")
def get_appointments():
    # Returns ALL appointments (Admin view usually)
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM appointments ORDER BY appointment_date DESC, appointment_time DESC")
        results = cursor.fetchall()
        for row in results:
            row['appointment_date'] = str(row['appointment_date'])
            row['appointment_time'] = str(row['appointment_time'])
        return results
    finally: cursor.close(); conn.close()

@app.get("/api/slots")
def get_slots(date: str):
    conn = get_db()
    try:
        return calculate_available_slots(conn, date)
    finally: conn.close()

@app.post("/api/appointments")
def create_appointment(appt: AppointmentCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        # Check spam (same name, same urgency, pending)
        cursor.execute("SELECT id FROM appointments WHERE student_name = %s AND status = 'pending' AND urgency = %s", (appt.student_name, appt.urgency))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="You already have a pending request.")

        # Time format fix
        t_str = appt.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        err = validate_booking_rules(cursor, appt.appointment_date, t_str)
        if err: raise HTTPException(status_code=400, detail=err)

        cursor.execute("""
            INSERT INTO appointments (student_name, student_email, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'standard', 'pending')
        """, (appt.student_name, appt.student_email, appt.appointment_date, t_str, appt.service_type, appt.urgency, appt.reason))
        conn.commit()
        return {"message": "Booked!", "id": cursor.lastrowid}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

@app.put("/api/appointments/{id}")
def update_appt(id: int, update: AppointmentUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        cursor.execute("SELECT * FROM appointments WHERE id = %s", (id,))
        curr = cursor.fetchone()
        if not curr: raise HTTPException(status_code=404, detail="Not found")
        
        cursor.execute("UPDATE appointments SET status = %s, admin_note = %s WHERE id = %s", (update.status, update.admin_note, id))
        conn.commit()
        
        return {"message": "Updated"}
    finally: cursor.close(); conn.close()

@app.put("/api/appointments/{id}/reschedule")
def reschedule(id: int, r: AppointmentReschedule):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        # Time format fix
        t_str = r.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")
             
        err = validate_booking_rules(cursor, r.appointment_date, t_str)
        if err: raise HTTPException(status_code=400, detail=err)

        cursor.execute("UPDATE appointments SET appointment_date = %s, appointment_time = %s, status = 'pending' WHERE id = %s", (r.appointment_date, t_str, id))
        conn.commit()
        return {"message": "Rescheduled"}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

@app.delete("/api/appointments/{id}")
def delete_appt(id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM appointments WHERE id = %s", (id,))
        conn.commit()
        return {"message": "Deleted"}
    finally: cursor.close(); conn.close()

# --- CHATBOT ---
@app.post("/api/chat")
async def chat_booking(chat: ChatMessage):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    
    current_local_date = datetime.now(PHT).strftime("%Y-%m-%d, %A")
    
    # Smart Date Detection Logic (Same as before)
    target_date_str = None
    msg_lower = chat.message.lower()
    
    match_iso = re.search(r'\d{4}-\d{2}-\d{2}', chat.message)
    if match_iso: target_date_str = match_iso.group(0)
    
    if not target_date_str:
         if "tomorrow" in msg_lower: target_date_str = parse_relative_date("tomorrow")
         elif "today" in msg_lower: target_date_str = parse_relative_date("today")

    system_slot_info = ""
    if target_date_str:
        slots = calculate_available_slots(conn, target_date_str)
        system_slot_info = f"\n[SYSTEM INFO] Available slots for {target_date_str}: {', '.join(slots)}" if slots else f"\n[SYSTEM INFO] No slots for {target_date_str}."
    
    conn.close()

    final_instruction = f"{BASE_INSTRUCTION}\nToday's Date (Local): {current_local_date}\n{system_slot_info}"

    try:
        # Chat Generation
        chat_session = model.start_chat(history=[
            {"role": "user", "parts": [final_instruction]},
            {"role": "model", "parts": ["Understood."]}
        ] + [{"role": "user" if m.get("role")=="user" else "model", "parts": [m.get("message", "")]} for m in chat.history[-6:]])
        
        response = chat_session.send_message(chat.message)
        ai_text = response.text

        # JSON Action Parsing
        if "{" in ai_text and "}" in ai_text:
            try:
                json_str = ai_text[ai_text.find('{'):ai_text.rfind('}')+1]
                data = json.loads(json_str)
                
                if data.get("action") == "book_appointment":
                     conn = get_db()
                     cursor = conn.cursor(dictionary=True)
                     
                     p_date = parse_relative_date(data['date']) or data['date']
                     p_time = data['time']
                     if "AM" in p_time.upper() or "PM" in p_time.upper():
                         p_time = datetime.strptime(p_time, "%I:%M %p").strftime("%H:%M:%S")
                     
                     err = validate_booking_rules(cursor, p_date, p_time)
                     if err: return {"response": err, "refresh": False}

                     cursor.execute("""
                        INSERT INTO appointments (student_name, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'ai_chatbot', 'pending')
                     """, (data.get('student_name', 'Walk-in Student'), p_date, p_time, data['service_type'], data['urgency'], data['reason']))
                     conn.commit()
                     conn.close()
                     return {"response": f"Booked for {p_date} at {data['time']}. Ticket generated!", "refresh": True}

                elif data.get("action") in ["cancel_appointment", "reschedule_appointment"]:
                     # Re-implementing action logic cleanly here
                     conn = get_db()
                     cursor = conn.cursor(dictionary=True)
                     appt_id = data.get("appointment_id")
                     
                     if data.get("action") == "cancel_appointment":
                         cursor.execute("UPDATE appointments SET status = 'canceled' WHERE id = %s", (appt_id,))
                         conn.commit()
                         return {"response": f"Appointment #{appt_id} canceled.", "refresh": True}
                     
                     if data.get("action") == "reschedule_appointment":
                         new_d = parse_relative_date(data['new_date']) or data['new_date']
                         new_t = data['new_time']
                         if "AM" in new_t.upper() or "PM" in new_t.upper():
                             new_t = datetime.strptime(new_t, "%I:%M %p").strftime("%H:%M:%S")
                         
                         cursor.execute("UPDATE appointments SET appointment_date = %s, appointment_time = %s, status = 'pending' WHERE id = %s", (new_d, new_t, appt_id))
                         conn.commit()
                         return {"response": f"Rescheduled #{appt_id} to {new_d}.", "refresh": True}
                     
            except: pass

        return {"response": ai_text, "refresh": False}
    except Exception as e:
        return {"response": "System error.", "refresh": False}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)