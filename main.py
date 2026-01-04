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

# load the hidden variables from .env file
load_dotenv()

# get the api keys and passwords
API_KEY = os.getenv("GOOGLE_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# adjust time to your local timezone (philippines is +8)
TIMEZONE_OFFSET = 8 

# check if google key is there
if not API_KEY:
    print("warning: google_api_key not found in .env file")
else:
    genai.configure(api_key=API_KEY)
    # using a smart model for better replies
    model = genai.GenerativeModel('gemma-3-12b-it') 

# database connection settings
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'kurt_cobain', 
    'database': 'school_clinic'
}

# instructions for the ai
BASE_INSTRUCTION = """
SYSTEM: You are the School Clinic Receptionist.
PERSONA: Warm, caring, efficient, and professional.
GOAL: Manage appointments (Book, Cancel, Reschedule) for the client.

RULES:
1. **Be Human:** Use natural language. Say "Oh no, I hope you feel better!" if they are sick.

2. **CHECK AVAILABILITY (CRITICAL):**
   - I (the System) will check the database and provide [SYSTEM INFO] below.
   - **YOU MUST ONLY OFFER SLOTS LISTED IN [SYSTEM INFO].** - **DO NOT HALLUCINATE OR GUESS TIMES.** If [SYSTEM INFO] says "No slots", say "I'm sorry, we are fully booked for that date."
   - If [SYSTEM INFO] is missing or doesn't mention a specific date, ask: "Which date would you like to check?"

3. **HANDLING REQUESTS:**
   - **Booking:** Need Date, Time, Service, Urgency, Reason. 
   - **[CRITICAL] URGENCY LEVELS:** "Standard" or "Urgent" only.
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
  "urgency": "Standard",
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

# this gets the current time in your timezone
def get_local_now():
    utc_now = datetime.utcnow()
    return utc_now + timedelta(hours=TIMEZONE_OFFSET)

# this function converts words like "tomorrow" into real dates like "2025-10-10"
def parse_relative_date(date_str):
    if not date_str: return None
    
    # make the input lowercase so it matches easily
    text = date_str.lower().strip()
    today = get_local_now()

    # strict check for "today"
    if "today" in text:
        return today.strftime("%Y-%m-%d")
    
    # strict check for "tomorrow"
    if "tomorrow" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # check for "next week" (default to 7 days later)
    if "next week" in text:
        return (today + timedelta(days=7)).strftime("%Y-%m-%d")
    
    # check for weekdays like "monday" or "next monday"
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    for i, day_name in enumerate(weekdays):
        if day_name in text:
            # 0 = monday, 6 = sunday
            today_day_index = today.weekday()
            
            # calculate days until the target day
            days_ahead = (i - today_day_index + 7) % 7
            
            # if days_ahead is 0 (it is today), usually "monday" means next week's monday
            if days_ahead == 0: 
                days_ahead = 7
            
            target_date = today + timedelta(days=days_ahead)
            return target_date.strftime("%Y-%m-%d")

    # if no keywords found, return original text
    return date_str

# this looks for dates inside a long message
def extract_date_from_text(text):
    if not text: return None
    msg_lower = text.lower()
    
    # 1. try to find strict date format yyyy-mm-dd
    match_iso = re.search(r'\d{4}-\d{2}-\d{2}', text)
    if match_iso:
        return match_iso.group(0)
    
    # 2. search for keywords like "next monday", "tomorrow"
    # order matters: check longer phrases first so "next monday" is found before "monday"
    keywords = [
        'next week', 'next monday', 'next tuesday', 'next wednesday', 
        'next thursday', 'next friday', 'next saturday', 'next sunday',
        'tomorrow', 'today', 
        'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'
    ]
    
    for w in keywords:
        if w in msg_lower:
            # call the parser to convert the word to a date
            return parse_relative_date(w)
            
    return None

# this checks which hours are free in the database
def calculate_available_slots(conn, date_str):
    cursor = conn.cursor(dictionary=True)
    try:
        now = get_local_now()
        
        # try to understand the date string
        try:
            req_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            # if date format is wrong, return empty list
            return [] 

        is_today = (req_date == now.date())
        current_time = now.time()

        # allowed clinic hours
        possible_hours = [8, 9, 10, 11, 13, 14, 15, 16] 
        
        # get all busy appointments for that day
        cursor.execute("""
            SELECT appointment_time FROM appointments 
            WHERE appointment_date = %s 
            AND status IN ('pending', 'approved')
        """, (date_str,))
        
        taken_start_times = []
        for row in cursor.fetchall():
            # convert time from database to python time
            seconds = int(row['appointment_time'].total_seconds())
            h = seconds // 3600
            m = (seconds % 3600) // 60
            taken_dt = datetime.combine(req_date, dt_time(h, m, 0))
            taken_start_times.append(taken_dt)

        available = []

        # loop through every hour to see if it is free
        for h in possible_hours:
            for m in [0, 30]:
                slot_time = dt_time(h, m, 0)
                slot_dt = datetime.combine(req_date, slot_time)
                
                is_blocked = False
                # check if this slot overlaps with any busy time
                for taken_dt in taken_start_times:
                    taken_end = taken_dt + timedelta(hours=1)
                    if taken_dt <= slot_dt < taken_end:
                        is_blocked = True
                        break
                
                if is_blocked: continue 

                # if it is today, do not show past hours
                if is_today:
                    if slot_time <= current_time: continue 
                
                # format the time nicely (e.g., 08:30 AM)
                ampm = "AM" if h < 12 else "PM"
                display_h = h if h <= 12 else h - 12
                display_h = 12 if display_h == 0 else display_h
                nice_time = f"{display_h:02d}:{m:02d} {ampm}"
                available.append(nice_time)

        return available
    finally:
        cursor.close()

# this checks the strict rules of the clinic
def validate_booking_rules(cursor, date_str, time_str):
    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        now_date = get_local_now().date()
        
        # cannot book in the past
        if booking_date < now_date: return "You cannot book appointments in the past."
        # cannot book on sunday
        if booking_date.weekday() == 6: return "The clinic is closed on Sundays."
    except ValueError: return "Invalid date format. Please use YYYY-MM-DD."

    try:
        # standardise time format
        if "AM" in time_str.upper() or "PM" in time_str.upper():
             t = datetime.strptime(time_str, "%I:%M %p").time()
        else:
             if len(time_str) == 5: time_str += ":00"
             t = datetime.strptime(time_str, "%H:%M:%S").time()
        booking_time = t
    except ValueError: return "Invalid time format."

    # check lunch break and closing time
    if booking_time.hour == 12: return "Clinic is closed for lunch from 12:00 PM to 1:00 PM."
    if booking_time.hour >= 17: return "Clinic is closed. Operations end at 5:00 PM."
    if booking_time.hour < 8: return "Clinic opens at 8:00 AM."

    sql_time_str = booking_time.strftime("%H:%M:%S")

    # check database for double booking
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

# this function sends emails with qr codes
def send_status_email(to_email, client_name, date, time, status, appointment_id, admin_note=None):
    if not EMAIL_SENDER or not EMAIL_PASSWORD: return

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        
        html_body = ""
        subject_line = ""

        # email for approved appointment
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
        
        # email for rejected appointment
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

        # email for missed appointment
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

        # attach qr code only if approved
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

        # send the email via gmail
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

# enable cors so frontend can talk to backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- data models ---
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

# --- routes ---

# get all appointments
@app.get("/api/appointments")
def get_appointments(client_email: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # if client_email is provided, filter for that specific client
        if client_email:
            sql = "SELECT * FROM appointments WHERE client_email = %s ORDER BY appointment_date DESC"
            cursor.execute(sql, (client_email,))
        else:
            # if no email, return all (for nurse/doctor views)
            sql = "SELECT * FROM appointments ORDER BY appointment_date DESC"
            cursor.execute(sql)
        
        results = cursor.fetchall()
        # convert date objects to strings for json
        for row in results:
            row['appointment_date'] = str(row['appointment_date'])
            row['appointment_time'] = str(row['appointment_time'])
        return results
    finally: cursor.close(); conn.close()

# check slots for a specific date
@app.get("/api/slots")
def get_available_slots_endpoint(date: str):
    conn = get_db()
    try:
        return calculate_available_slots(conn, date)
    finally: conn.close()

# create a new appointment manually
@app.post("/api/appointments")
def create_appointment(appointment: AppointmentCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True) 
    try:
        # fix: force convert 'normal' to 'standard' to prevent db error
        if appointment.urgency == "Normal":
            appointment.urgency = "Standard"

        # check if user already has a pending request
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

        # handle time formatting
        t_str = appointment.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        # save to database
        cursor.execute("""
            INSERT INTO appointments 
            (client_name, client_email, appointment_date, appointment_time, service_type, urgency, reason, booking_mode, status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'standard', 'pending')
        """, (appointment.client_name, appointment.client_email, appointment.appointment_date, t_str, appointment.service_type, appointment.urgency, appointment.reason))
        
        conn.commit()
        return {"message": "booked", "id": cursor.lastrowid}
    except Error as e: raise HTTPException(status_code=500, detail=str(e))
    finally: cursor.close(); conn.close()

# nurse route: update status (approve/reject)
@app.put("/api/appointments/{id}/status")
def update_status(id: int, update: StatusUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # update database
        sql = "UPDATE appointments SET status = %s, admin_note = %s WHERE id = %s"
        cursor.execute(sql, (update.status, update.admin_note, id))
        conn.commit()

        # fetch details for email
        cursor.execute("SELECT * FROM appointments WHERE id = %s", (id,))
        appt = cursor.fetchone()
        
        # send email for approved, rejected, and no show
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

# doctor route: add diagnosis (completes the visit)
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

# reschedule appointment
@app.put("/api/appointments/{id}/reschedule")
def reschedule_appointment(id: int, r: AppointmentReschedule):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    try:
        # check if appointment exists
        cursor.execute("SELECT id FROM appointments WHERE id = %s", (id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Appointment not found")

        # validate booking rules (time conflict, etc.)
        err = validate_booking_rules(cursor, r.appointment_date, r.appointment_time)
        if err: raise HTTPException(status_code=400, detail=err)

        # handle time format
        t_str = r.appointment_time
        if "AM" in t_str.upper() or "PM" in t_str.upper():
             t = datetime.strptime(t_str, "%I:%M %p").time()
             t_str = t.strftime("%H:%M:%S")

        # update database
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

# cancellation (no deletion for now)
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
#  smart ai chatbot 
# ==========================================

@app.post("/api/chat")
async def chat_booking(chat: ChatMessage):
    conn = get_db()
    cursor = conn.cursor(dictionary=True, buffered=True)
    
    # fetch previous appointments for context
    try:
        cursor.execute("SELECT id, appointment_date, appointment_time FROM appointments WHERE client_email = %s AND status IN ('pending', 'approved') ORDER BY appointment_date ASC", (chat.client_email,))
        active_appts = cursor.fetchall()
        appt_text = "\n".join([f"- ID {a['id']}: {a['appointment_date']} at {a['appointment_time']}" for a in active_appts]) if active_appts else "None."
    finally: cursor.close(); conn.close()

    system_slot_info = ""
    target_date_str = None
    context_hint = "" 
    
    # --- smart date detection (history + message) ---
    
    # 1. check current message for dates like "next monday"
    target_date_str = extract_date_from_text(chat.message)
    
    # 2. if not in current, check last 2 user messages (history context)
    if not target_date_str and chat.history:
        for h in reversed(chat.history[-2:]):
            if h.get('role') == 'user':
                found = extract_date_from_text(h.get('message', ''))
                if found:
                    target_date_str = found
                    break

    # 3. check availability if date found
    if target_date_str:
        conn = get_db()
        slots = calculate_available_slots(conn, target_date_str)
        conn.close()
        
        # update slot info text
        if slots:
            system_slot_info = f"\n[SYSTEM INFO] Available slots for {target_date_str}: {', '.join(slots)}"
        else:
            system_slot_info = f"\n[SYSTEM INFO] No slots available for {target_date_str}."
            
        # --- vital fix: tell the ai explicitly that the date is found ---
        # this forces the ai to accept the date instead of asking "which date?"
        context_hint = f"\n[IMPORTANT CONTEXT] The user is inquiring about date: {target_date_str}. Do not ask for the date again. Use the slots above."
    
    # 4. fallback: if user asks for "time/available" but no date found, check today and tomorrow
    elif any(x in chat.message.lower() for x in ['available', 'time', 'slot', 'schedule', 'free', 'when']):
        today_str = parse_relative_date('today')
        tomorrow_str = parse_relative_date('tomorrow')
        
        conn = get_db()
        slots_today = calculate_available_slots(conn, today_str)
        slots_tomorrow = calculate_available_slots(conn, tomorrow_str)
        conn.close()
        
        system_slot_info = f"\n[SYSTEM INFO]\n- Slots for TODAY ({today_str}): {', '.join(slots_today) if slots_today else 'None'}\n- Slots for TOMORROW ({tomorrow_str}): {', '.join(slots_tomorrow) if slots_tomorrow else 'None'}"

    # ------------------------------------------------

    current_local_date = get_local_now().strftime("%Y-%m-%d, %A")
    
    # combine instruction with the new hint
    final_instruction = f"{BASE_INSTRUCTION}\nClient Email: {chat.client_email}\nToday: {current_local_date}\nActive Appts: {appt_text}\n{system_slot_info}\n{context_hint}"

    try:
        # start chat with the system instruction
        chat_session = model.start_chat(history=[
            {"role": "user", "parts": [final_instruction]}, 
            {"role": "model", "parts": ["Understood. I am ready to help."]}
        ])
        
        response = chat_session.send_message(chat.message)
        ai_text = response.text

        # check if ai wants to perform an action (json)
        if "{" in ai_text and "}" in ai_text:
            try:
                json_str = ai_text[ai_text.find('{'):ai_text.rfind('}')+1]
                data = json.loads(json_str)
                
                if data.get("action") == "book_appointment":
                    conn = get_db()
                    cursor = conn.cursor(dictionary=True, buffered=True)
                    
                    # spam prevention: check matching urgency
                    requested_urgency = data.get('urgency', 'Standard')
                    cursor.execute("""
                        SELECT id FROM appointments 
                        WHERE client_email = %s 
                        AND status IN ('pending', 'approved') 
                        AND urgency = %s
                    """, (chat.client_email, requested_urgency))
                    
                    if cursor.fetchone():
                        return {"response": f"You already have a pending {requested_urgency} appointment.", "refresh": False}

                    # ensure date is parsed correctly from json
                    p_date = parse_relative_date(data['date']) or data['date']
                    p_time = data['time']
                    if "AM" in p_time.upper() or "PM" in p_time.upper():
                         p_time = datetime.strptime(p_time, "%I:%M %p").strftime("%H:%M:%S")
                    
                    err = validate_booking_rules(cursor, p_date, p_time)
                    if err: return {"response": err, "refresh": False}
                    
                    # look for existing name associated with this email
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