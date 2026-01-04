# School Clinic Appointment System

A smart, web-based application designed to streamline school clinic operations. It features an AI Chatbot for easy appointment booking, a real-time live queue for doctors, and an automated email notification system with QR code tickets.

## Features

### For Students (Client)
* **AI Chatbot Assistant:** Book appointments naturally by chatting with a smart AI.
* **Manual Booking:** Simple form to schedule Medical Consultations or Clearances.
* **Appointment History:** View status of requests (Pending, Approved, Completed) in real-time.
* **Reschedule/Cancel:** Manage appointments easily with a single click.

### For Nurses
* **Dashboard Overview:** View a centralized list of all pending requests.
* **Triage System:** Approve or reject appointments efficiently.
* **Email Notifications:** Automatically sends QR Code tickets to students upon approval.

### For Doctors
* **Live Queue (Hero Card):** Shows the patient currently being served and who is up next.
* **QR Code Scanner:** Verify patient tickets instantly using the camera.
* **Digital Diagnosis:** Fill out Vital Signs, Findings, Treatment, and Recommendations.
* **No-Show Management:** Quickly remove students from the queue if they fail to appear.

---

## Technologies Used
* **Frontend:** HTML5, CSS3, JavaScript (Vanilla)
* **Backend:** Python (FastAPI)
* **Database:** MySQL
* **AI:** Google Gemini API
* **Other:** SMTP (Email), QR Code Generation

---

## How to Run the Project

### 1. Prerequisites
Make sure you have executed the setup script:
* make sure you have internet connection
* install python version 3.12
* Run the `run_server.bat` file. It will also install the requirements.

### 2. Database Setup
1.  Open your MySQL Command Line.
2.  Run the schema file using the `source` command.
    * *Example:* `source C:\Users\ASUS\Documents\SCHOOLZ\3rd Year\web\FINAL-NAJUD\Web-Project\schema.sql`

### 3. How to view
* use live server from vscode on client-dashboard.html, doctor-dashboard.html, nurse-dashboard.html
