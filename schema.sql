DROP DATABASE IF EXISTS school_clinic;
CREATE DATABASE school_clinic;
USE school_clinic;

-- 1. Appointments Table (Merged with Student Info)
CREATE TABLE appointments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- [NEW] Student Info stored directly here
    student_name VARCHAR(255) NOT NULL,
    -- Removed student_id_number as requested
    student_email VARCHAR(255), 
    
    service_type VARCHAR(100) NOT NULL,
    urgency ENUM('Normal', 'Urgent') DEFAULT 'Normal',
    
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    reason TEXT NOT NULL,
    
    booking_mode ENUM('standard', 'ai_chatbot') DEFAULT 'standard',
    status ENUM('pending', 'approved', 'rejected', 'canceled', 'completed', 'noshow') DEFAULT 'pending',
    admin_note TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 2. Chat History
CREATE TABLE chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    message TEXT NOT NULL,
    sender ENUM('user', 'bot') NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);