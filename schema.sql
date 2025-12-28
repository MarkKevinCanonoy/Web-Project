CREATE DATABASE IF NOT EXISTS school_clinic;
USE school_clinic;

CREATE TABLE appointments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    client_name VARCHAR(255) NOT NULL,
    client_email VARCHAR(255) NOT NULL,  
    
    service_type VARCHAR(100) NOT NULL,
    urgency ENUM('Normal', 'Urgent') DEFAULT 'Normal',
    
    appointment_date DATE NOT NULL,
    appointment_time TIME NOT NULL,
    reason TEXT NOT NULL,
    
    booking_mode ENUM('standard', 'ai_chatbot') DEFAULT 'standard',
    status ENUM('pending', 'approved', 'rejected', 'canceled', 'completed', 'noshow') DEFAULT 'pending',
    
    admin_note TEXT,       
    diagnosis TEXT,        
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    client_email VARCHAR(255) NOT NULL, 
    
    message TEXT NOT NULL,
    sender ENUM('user', 'bot') NOT NULL,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    
);

