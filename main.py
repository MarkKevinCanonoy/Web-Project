from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict
from datetime import datetime, timedelta, time as dt_time
import mysql.connector
from mysql.connector import Error
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
import qrcode
import io

# --- configuration setup ---

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

TIMEZONE_OFFSET = 8 

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


BASE_INSTRUCTION = """
SYSTEM: You are the School Clinic Receptionist.
PERSONA: Warm, caring, efficient, and professional.
GOAL: Manage appointments (Book, Cancel, Reschedule) for the client.

RULES:
1. **Be Human:** Use natural language. Say "Oh no, I hope you feel better!" if they are sick.

2. **CHECK AVAILABILITY:**
   - I (the System) will check the database for you.
   - Look for [SYSTEM INFO] at the bottom.
   - If it lists slots, offer ONLY those.
   - If [SYSTEM INFO] is missing, ask: "Which date would you like to check?"

3. **HANDLING REQUESTS:**
   - **Booking:** Need Date, Time, Service, Urgency, Reason. 
   - **[CRITICAL] URGENCY LEVELS:** "Normal" or "Urgent" only.
   - **Output:** Only when you have Date, Time, Service, Urgency, and Reason -> Output `book_appointment` JSON.
   
   - **Canceling:** User says "cancel". -> Output `cancel_appointment` JSON (Marks as canceled).
   - **Rescheduling:** 1. Ask for ID (if not provided). 2. Ask for New Date & Time. -> Output `reschedule_appointment` JSON.

4. **ADVICE:** If you give advice, start it with "Tip: ".

🔴 CRITICAL: FOR ACTIONS, OUTPUT RAW JSON ONLY. NO MARKDOWN.

[BOOKING FORMAT]
{
  "action": "book_appointment",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:00",
  "reason": "short reason",
  "service_type": "Medical Consultation", 
  "urgency": "Normal",
  "ai_advice": "Tip: Short friendly advice."
}

[CANCEL FORMAT]
{
  "action": "cancel_appointment",
  "appointment_id": 123
}

[RESCHEDULE FORMAT]
{
  "action": "reschedule_appointment",
  "appointment_id": 123,
  "new_date": "YYYY-MM-DD",
  "new_time": "HH:MM:00"
}
"""

# --- helper functions ---

def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        raise HTTPException(status_code=500, detail=f"database connection failed: {str(e)}")

def get_local_now():
    utc_now = datetime.utcnow()
    return utc_now + timedelta(hours=TIMEZONE_OFFSET)

def parse_relative_date(date_str):
    if not date_str: return None
    today = get_local_now()
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
        now = get_local_now()
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return [] 

        is_today = (req_date == now.date())
        current_time = now.time()

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
                
                is_blocked = False
                for taken_dt in taken_start_times:
                    taken_end = taken_dt + timedelta(hours=1)
                    if taken_dt <= slot_dt < taken_end:
                        is_blocked = True
                        break
                
                if is_blocked: continue 

                if is_today:
                    if slot_time <= current_time: continue 
                
                ampm = "AM" if h < 12 else "PM"
                display_h = h if h <= 12 else h - 12
                display_h = 12 if display_h == 0 else display_h
                nice_time = f"{display_h:02d}:{m:02d} {ampm}"
                available.append(nice_time)

        return available
    finally:
        cursor.close()

def validate_booking_rules(cursor, date_str, time_str):
    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        now_date = get_local_now().date()
        
        if booking_date < now_date: return "You cannot book appointments in the past."
        if booking_date.weekday() == 6: return "The clinic is closed on Sundays."
    except ValueError: return "Invalid date format. Please use YYYY-MM-DD."

    try:
        if "AM" in time_str.upper() or "PM" in time_str.upper():
             t = datetime.strptime(time_str, "%I:%M %p").time()
        else:
             if len(time_str) == 5: time_str += ":00"
             t = datetime.strptime(time_str, "%H:%M:%S").time()
        booking_time = t
    except ValueError: return "Invalid time format."

    if booking_time.hour == 12: return "Clinic is closed for lunch from 12:00 PM to 1:00 PM."
    if booking_time.hour >= 17: return "Clinic is closed. Operations end at 5:00 PM."
    if booking_time.hour < 8: return "Clinic opens at 8:00 AM."

    sql_time_str = booking_time.strftime("%H:%M:%S")

    cursor.execute("""
        SELECT id FROM appointments 
        WHERE appointment_date = %s 
        AND status IN ('pending', 'approved')
        AND (
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) > -3600 
            AND 
            TIME_TO_SEC(TIMEDIFF(appointment_time, %s)) < 3600
        )
    """, (date_str, sql_time_str, sql_time_str))
    
    if cursor.fetchone(): return "Time slot conflict! Please select a different time."
    return None 

def send_status_email(to_email, client_name, date, time, status, appointment_id, admin_note=None):
    if not EMAIL_SENDER or not EMAIL_PASSWORD: return

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        
        
        html_body = ""
        subject_line = ""

        if status == 'approved':
            subject_line = "Appointment Confirmed - School Clinic"
            html_body = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #ccc; max-width: 500px; text-align: center;">
                <h2 style="color: #2ecc71;">APPOINTMENT APPROVED</h2>
                <p>Hello <strong>{client_name}</strong>,</p>
                <p>Your appointment has been confirmed.</p>
                <div style="background:#f9f9f9; padding:15px; border-radius:10px; margin:20px 0;">
                    <p><strong>Appointment ID:</strong> #{appointment_id}</p>
                    <p><strong>Date:</strong> {date}</p>
                    <p><strong>Time:</strong> {time}</p>
                </div>
                <p>Please present this QR code at the clinic:</p>
                <img src="cid:qrcode_image" alt="QR Ticket" style="width: 200px; height: 200px;">
                <br><br>
                <p style="color: #777; font-size: 12px;">School Clinic Portal</p>
            </div>
            """
        
        elif status == 'rejected':
            subject_line = "Update on your Appointment Request"
            html_body = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #eee; max-width: 500px; text-align: center;">
                <h2 style="color: #e74c3c;">REQUEST DECLINED</h2>
                <p>Hello <strong>{client_name}</strong>,</p>
                <p>We are unable to approve your appointment request for {date} at {time}.</p>
                
                <div style="background:#fff5f5; border-left: 4px solid #e74c3c; padding:15px; margin:20px 0; text-align:left;">
                    <p style="color:#c0392b; margin:0;"><strong>Reason:</strong></p>
                    <p style="margin:5px 0 0 0;">{admin_note}</p>
                </div>
                
                <p>Please log in to the portal to book a different time.</p>
                <p style="color: #777; font-size: 12px;">School Clinic Portal</p>
            </div>
            """

        elif status == 'noshow':
            subject_line = "Missed Appointment Notification"
            html_body = f"""
            <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #eee; max-width: 500px; text-align: center;">
                <h2 style="color: #607d8b;">MISSED APPOINTMENT</h2>
                <p>Hello <strong>{client_name}</strong>,</p>
                <p>We missed you today for your appointment (ID #{appointment_id}).</p>
                <p>Since you did not arrive, this appointment has been marked as a <strong>No Show</strong>.</p>
                <p>If you still need medical attention, please log in to the portal and book a new schedule.</p>
                <br>
                <p style="color: #777; font-size: 12px;">School Clinic Portal</p>
            </div>
            """
        
        else:
            return 

        msg['Subject'] = subject_line
        msg.attach(MIMEText(html_body, 'html'))

        if status == 'approved':
            qr_data = str(appointment_id)
            qr = qrcode.make(qr_data)
            img_byte_arr = io.BytesIO()
            qr.save(img_byte_arr, format='PNG')
            img_byte_arr = img_byte_arr.getvalue()

            image = MIMEImage(img_byte_arr, name="ticket.png")
            image.add_header('Content-ID', '<qrcode_image>')
            image.add_header('Content-Disposition', 'inline', filename='ticket.png')
            msg.attach(image)

        # Send
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to_email} ({status})")

    except Exception as e:
        print(f"Email error: {e}")

# --- main app setup ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- MODELS ---
class AppointmentCreate(BaseModel):
    client_name: str
    client_email: str
    appointment_date: str
    appointment_time: str
    service_type: str
    urgency: str
    reason: str
    booking_mode: str = "standard"

class StatusUpdate(BaseModel):
    status: str
    admin_note: Optional[str] = None

class DiagnosisUpdate(BaseModel):
    diagnosis: str

class ChatMessage(BaseModel):
    client_email: str 
    message: str
    history: List[dict] = []

class AppointmentReschedule(BaseModel):
    appointment_date: str
    appointment_time: str     

# --- ROUTES ---

@app.get("/api/appointments")
def get_appointments(client_email: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # If client_email is provided, filter for that specific client
        if client_email:
            sql = "SELECT * FROM appointments WHERE client_email = %s ORDER BY appointment_date DESC"
            cursor.execute(sql, (client_email,))
        else:
            # If no email, return ALL (For Nurse/Doctor views)
            sql = "SELECT * FROM appointments ORDER BY appointment_date DESC"
            cursor.execute(sql)
        
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
def create_appointment(appointment: AppointmentCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True) 
    try:
        # CHECK BOTH PENDING AND APPROVED
        cursor.execute("""
            SELECT id FROM appointments 
            WHERE client_email = %s 
            AND status IN ('pending', 'approved') 
            AND urgency = %s
        """, (appointment.client_email, appointment.urgency))
        
        if cursor.fetchone():
             msg = "You already have a pending URGENT request." if appointment.urgency == 'Urgent' else "You have a pending request."
             raise HTTPException(status_code=400, detail=msg)
        
        error_message = validate_booking_rules(cursor, appointment.appointment_date, appointment.appointment_time)
        if error_message: raise HTTPException(status_code=400, detail=error_message)

        # Handle time
        t_str = appointment.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        cursor.execute("""
            INSERT INTO appointments 
            (client_name, client_email, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'standard', 'pending')
        """, (appointment.client_name, appointment.client_email, appointment.appointment_date, t_str, appointment.service_type, appointment.urgency, appointment.reason))
        
        conn.commit()
        return {"message": "booked", "id": cursor.lastrowid}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

# NURSE: Update Status (Approve/Reject)
@app.put("/api/appointments/{id}/status")
def update_status(id: int, update: StatusUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # Update DB
        sql = "UPDATE appointments SET status = %s, admin_note = %s WHERE id = %s"
        cursor.execute(sql, (update.status, update.admin_note, id))
        conn.commit()

        # Fetch details for Email
        cursor.execute("SELECT * FROM appointments WHERE id = %s", (id,))
        appt = cursor.fetchone()
        
        # Send Email for Approved, Rejected, AND No Show
        if appt and update.status in ['approved', 'rejected', 'noshow']:
             d_str = str(appt['appointment_date'])
             t_str = str(appt['appointment_time'])
             
             send_status_email(
                 to_email=appt['client_email'], 
                 client_name=appt['client_name'], 
                 date=d_str, 
                 time=t_str, 
                 status=update.status, 
                 appointment_id=appt['id'],
                 admin_note=update.admin_note
             )

        return {"message": "Status updated"}
    finally: cursor.close(); conn.close()

# Add Diagnosis (Completes the visit)
@app.put("/api/appointments/{id}/diagnosis")
def update_diagnosis(id: int, diag: DiagnosisUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        sql = "UPDATE appointments SET diagnosis = %s, status = 'completed' WHERE id = %s"
        cursor.execute(sql, (diag.diagnosis, id))
        conn.commit()
        return {"message": "Diagnosis saved"}
    finally: cursor.close(); conn.close()

# RESCHEDULE APPOINTMENT
@app.put("/api/appointments/{id}/reschedule")
def reschedule_appointment(id: int, r: AppointmentReschedule):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        # Check if appointment exists
        cursor.execute("SELECT id FROM appointments WHERE id = %s", (id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Appointment not found")

        # Validate Booking Rules (Time conflict, etc.)
        err = validate_booking_rules(cursor, r.appointment_date, r.appointment_time)
        if err: raise HTTPException(status_code=400, detail=err)

        # Handle Time Format
        t_str = r.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        # Update Database
        cursor.execute("""
            UPDATE appointments
            SET appointment_date = %s, appointment_time = %s, status = 'pending'
            WHERE id = %s
        """, (r.appointment_date, t_str, id))
        conn.commit()
        return {"message": "Rescheduled successfully"}
    except Error as e: 
        print(f"Reschedule Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally: 
        cursor.close(); conn.close()

# CANCELLATION (No deletion for now)
@app.delete("/api/appointments/{id}")
def cancel_appointment(id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        # only allow canceling pending appointments
        sql = "UPDATE appointments SET status = 'canceled' WHERE id = %s AND status = 'pending'"
        cursor.execute(sql, (id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=400, detail="Cannot cancel: Appointment not found or already processed.")
            
        return {"message": "canceled"}
    finally: cursor.close(); conn.close()

# ==========================================
#  SMART AI CHATBOT 
# ==========================================

@app.post("/api/chat")
async def chat_booking(chat: ChatMessage):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    
    # Fetch Context using EMAIL
    try:
        cursor.execute("SELECT id, appointment_date, appointment_time FROM appointments WHERE client_email = %s AND status IN ('pending', 'approved') ORDER BY appointment_date ASC", (chat.client_email,))
        active_appts = cursor.fetchall()
        appt_text = "\n".join([f"- ID {a['id']}: {a['appointment_date']} at {a['appointment_time']}" for a in active_appts]) if active_appts else "None."
    finally: cursor.close(); conn.close()

    system_slot_info = ""
    target_date_str = None
    msg_lower = chat.message.lower()
    
    match_iso = re.search(r'\d{4}-\d{2}-\d{2}', chat.message)
    if match_iso:
        target_date_str = match_iso.group(0)
    else:
        for w in ['today', 'tomorrow', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            if w in msg_lower:
                target_date_str = parse_relative_date(w)
                break
    
    if target_date_str:
        conn = get_db()
        slots = calculate_available_slots(conn, target_date_str)
        conn.close()
        system_slot_info = f"\n[SYSTEM INFO] Available slots for {target_date_str}: {', '.join(slots)}" if slots else f"\n[SYSTEM INFO] No slots for {target_date_str}."

    current_local_date = get_local_now().strftime("%Y-%m-%d, %A")
    final_instruction = f"{BASE_INSTRUCTION}\nClient Email: {chat.client_email}\nToday: {current_local_date}\nActive Appts: {appt_text}\n{system_slot_info}"

    try:
        chat_session = model.start_chat(history=[{"role": "user", "parts": [final_instruction]}, {"role": "model", "parts": ["Understood."]}])
        response = chat_session.send_message(chat.message)
        ai_text = response.text

        if "{" in ai_text and "}" in ai_text:
            try:
                json_str = ai_text[ai_text.find('{'):ai_text.rfind('}')+1]
                data = json.loads(json_str)
                
                if data.get("action") == "book_appointment":
                    conn = get_db()
                    cursor = conn.cursor(dictionary=True, buffered=True)
                    
                    # Spam Prevention: Check matching urgency
                    requested_urgency = data.get('urgency', 'Normal')
                    cursor.execute("""
                        SELECT id FROM appointments 
                        WHERE client_email = %s 
                        AND status IN ('pending', 'approved') 
                        AND urgency = %s
                    """, (chat.client_email, requested_urgency))
                    
                    if cursor.fetchone():
                        return {"response": f"You already have a pending {requested_urgency} appointment.", "refresh": False}

                    p_date = parse_relative_date(data['date']) or data['date']
                    p_time = data['time']
                    if "AM" in p_time.upper() or "PM" in p_time.upper():
                         p_time = datetime.strptime(p_time, "%I:%M %p").strftime("%H:%M:%S")
                    
                    err = validate_booking_rules(cursor, p_date, p_time)
                    if err: return {"response": err, "refresh": False}
                    
                    # Look for existing name associated with this email
                    client_name = "Client" 
                    cursor.execute("SELECT client_name FROM appointments WHERE client_email = %s ORDER BY id DESC LIMIT 1", (chat.client_email,))
                    existing_user = cursor.fetchone()
                    if existing_user:
                        client_name = existing_user['client_name']

                    cursor.execute("""
                        INSERT INTO appointments 
                        (client_name, client_email, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'ai_chatbot', 'pending')
                    """, (client_name, chat.client_email, p_date, p_time, data['service_type'], requested_urgency, data['reason']))
                    
                    conn.commit()
                    conn.close()
                    return {"response": f"Booked for {p_date}!", "refresh": True}
                
                elif data.get("action") == "cancel_appointment":
                    conn = get_db()
                    cursor = conn.cursor()
                    appt_id = int(data.get("appointment_id"))
                    cursor.execute("UPDATE appointments SET status = 'canceled' WHERE id = %s AND client_email = %s", (appt_id, chat.client_email))
                    conn.commit()
                    conn.close()
                    return {"response": "Appointment canceled.", "refresh": True}

            except Exception as e: print(e)

        return {"response": ai_text}
    except Exception as e:
        print(e)
        return {"response": "System busy."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)