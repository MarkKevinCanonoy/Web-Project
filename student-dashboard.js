const API_URL = 'http://localhost:8000/api';
let chatHistory = []; 

// [REMOVED] Auth check. No login needed.

// Initialize Date Input
const dateInput = document.getElementById('book-date'); 
if(dateInput) {
    dateInput.min = new Date().toISOString().split('T')[0];
}

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    // Highlight button
    const buttons = document.querySelectorAll('button');
    buttons.forEach(btn => {
        if(btn.onclick && btn.onclick.toString().includes(tabName)) {
            btn.classList.add('active');
        }
    });

    if (tabName === 'chatbot') {
        initChatbot();
    }
}

// 1. Load Slots
async function loadTimeSlots() {
    const date = document.getElementById('book-date').value;
    const container = document.getElementById('slots-container');
    const timeInput = document.getElementById('selected-time');
    timeInput.value = '';
    
    if(!date) return;
    container.innerHTML = '<p>Checking availability...</p>';

    try {
        const response = await fetch(`${API_URL}/slots?date=${date}`);
        const slots = await response.json();
        
        container.innerHTML = '';
        if(slots.length === 0) {
            container.innerHTML = '<p style="color:red;">Full for this day.</p>';
            return;
        }

        slots.forEach(time => {
            const btn = document.createElement('div');
            btn.className = 'slot-btn';
            btn.textContent = formatTime(time);
            btn.onclick = () => {
                document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
                btn.classList.add('selected');
                timeInput.value = time;
            };
            container.appendChild(btn);
        });
    } catch(error) {
        console.error(error);
        container.innerHTML = '<p style="color:red;">Error loading slots.</p>';
    }
}

// 2. Handle Booking (No Login)
async function handleBooking(e) {
    e.preventDefault(); 
    
    const name = document.getElementById('student-name').value;
    const serviceType = document.getElementById('book-type').value;
    const date = document.getElementById('book-date').value;
    const timeRaw = document.getElementById('selected-time').value;
    const urgency = document.getElementById('book-urgency').value;
    const reason = document.getElementById('book-reason').value;

    if(!name || !serviceType || !date || !timeRaw || !reason) {
        Swal.fire('Missing Details', 'Please fill in all fields.', 'warning');
        return;
    }

    const time = timeRaw.length === 5 ? timeRaw + ":00" : timeRaw;

    try {
        const response = await fetch(`${API_URL}/appointments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                student_name: name,
                appointment_date: date,
                appointment_time: time,
                service_type: serviceType,
                urgency: urgency,
                reason: reason
            })
        });

        const data = await response.json();

        if (!response.ok) {
            Swal.fire('Failed', data.detail || 'Error booking.', 'error');
            return;
        }

        // Generate Ticket immediately
        generateTicket({
            id: data.id,
            student_name: name,
            appointment_date: date,
            appointment_time: time,
            service_type: serviceType
        });

        document.getElementById('booking-form').reset();
        document.getElementById('slots-container').innerHTML = '';

    } catch (error) {
        console.error(error);
        Swal.fire('Error', 'Connection error.', 'error');
    }
}

// 3. Generate Ticket
function generateTicket(apt) {
    document.getElementById('pdf-name').textContent = apt.student_name; 
    document.getElementById('pdf-date').textContent = apt.appointment_date;
    document.getElementById('pdf-time').textContent = formatTime(apt.appointment_time);
    document.getElementById('pdf-service').textContent = apt.service_type;
    document.getElementById('pdf-id').textContent = `#${apt.id}`;

    const qrContainer = document.getElementById('pdf-qr-code');
    qrContainer.innerHTML = ""; 
    new QRCode(qrContainer, {
        text: String(apt.id),
        width: 150, height: 150
    });

    Swal.fire({
        icon: 'success',
        title: 'Booked!',
        text: 'Downloading your ticket...',
        timer: 2000,
        showConfirmButton: false
    });

    setTimeout(() => {
        html2canvas(document.getElementById('ticket-template')).then(canvas => {
            const link = document.createElement('a');
            link.download = `Ticket_${apt.id}.png`;
            link.href = canvas.toDataURL("image/png");
            link.click();
        });
    }, 1000); 
}

// 4. Chatbot
function initChatbot() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages && chatMessages.children.length === 0) {
        addChatMessage('bot', "Hello! I can help you book an appointment. What is your full name?");
    }
}

function addChatMessage(sender, message) {
    const chatMessages = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message ${sender}`;
    msgDiv.textContent = message;
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;
    
    addChatMessage('user', message);
    input.value = '';
    chatHistory.push({ role: "user", message: message });

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message, history: chatHistory }) 
        });
        const data = await response.json();
        chatHistory.push({ role: "model", message: data.response });
        addChatMessage('bot', data.response);
    } catch (error) {
        console.error(error);
        addChatMessage('bot', 'Error connecting to AI.');
    }
}

function handleEnter(e) { if (e.key === 'Enter') sendChatMessage(); }

function formatTime(timeStr) {
    if (!timeStr) return "";
    if (timeStr.includes('AM') || timeStr.includes('PM')) return timeStr;
    const [h, m] = timeStr.split(':');
    let hour = parseInt(h);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12 || 12;
    return `${hour}:${m} ${ampm}`;
}