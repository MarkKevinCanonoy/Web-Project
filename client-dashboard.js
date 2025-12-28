const API_URL = 'http://localhost:8000/api';
let allAppointments = [];
let chatHistory = []; 

// --- identity management ---
let clientName = localStorage.getItem('client_name');
let clientEmail = localStorage.getItem('client_email');

function checkIdentity() {
    clientName = localStorage.getItem('client_name');
    clientEmail = localStorage.getItem('client_email');

    if (clientName && clientEmail) {
        document.getElementById('welcome-overlay').style.display = 'none';
        document.getElementById('user-name').textContent = clientName;
        loadAppointments();
    } else {
        document.getElementById('welcome-overlay').style.display = 'flex';
    }
}

function saveIdentity() {
    const nameInput = document.getElementById('overlay-name');
    const emailInput = document.getElementById('overlay-email');
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();

    if (!name || !email) {
        Swal.fire('Missing Info', 'Please fill in both fields.', 'warning');
        return;
    }
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(email)) {
        Swal.fire('Invalid Email', 'Please enter a valid email.', 'warning');
        return;
    }
    localStorage.setItem('client_name', name);
    localStorage.setItem('client_email', email);
    location.reload();
}

function logout() {
    Swal.fire({
        title: 'Exit Portal?',
        text: "You will need to enter your name again next time.",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#e74c3c',
        confirmButtonText: 'Yes, exit'
    }).then((result) => {
        if (result.isConfirmed) {
            localStorage.clear();
            location.reload(); 
        }
    });
}

checkIdentity();

const dateInput = document.getElementById('book-date'); 
if(dateInput) {
    dateInput.min = new Date().toISOString().split('T')[0];
    if (dateInput.value) loadTimeSlots();
}

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.sidebar-btn').forEach(btn => btn.classList.remove('active'));
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    document.querySelectorAll('button').forEach(btn => {
        if(btn.onclick && btn.onclick.toString().includes(tabName)) btn.classList.add('active');
    });
    
    if (tabName === 'appointments') loadAppointments();
    if (tabName === 'chatbot') initChatbot();
}

async function handleBooking(e) {
    e.preventDefault(); 
    
    const serviceType = document.getElementById('book-type').value;
    const date = document.getElementById('book-date').value;
    const timeRaw = document.getElementById('selected-time').value;
    const urgency = document.getElementById('book-urgency').value;
    const reason = document.getElementById('book-reason').value;

    if(!serviceType || !date || !timeRaw || !reason || !urgency) {
        Swal.fire('Missing Details', 'Please fill in all required fields.', 'warning');
        return;
    }

    const hasActiveSameType = allAppointments.some(apt => 
        (apt.status === 'pending' || apt.status === 'approved') && 
        apt.urgency === urgency
    );

    if (hasActiveSameType) {
        Swal.fire({
            icon: 'warning',
            title: 'Limit Reached',
            text: `You already have an active ${urgency} appointment. Please complete or cancel it first.`
        });
        return; 
    }

    const time = timeRaw.length === 5 ? timeRaw + ":00" : timeRaw;

    try {
        const response = await fetch(`${API_URL}/appointments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                client_name: clientName,    
                client_email: clientEmail,  
                appointment_date: date,
                appointment_time: time,
                service_type: serviceType,
                urgency: urgency,
                reason: reason,
                booking_mode: 'standard'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            Swal.fire('Booking Failed', data.detail || 'Could not book appointment.', 'error');
            return;
        }

        Swal.fire({
            icon: 'success',
            title: 'Request Sent!',
            text: 'Please check your email for the ticket once approved.',
            confirmButtonColor: '#1E88E5'
        });

        document.getElementById('booking-form').reset();
        document.getElementById('slots-container').innerHTML = '<p style="color:#888; font-style:italic;">Please select a date first.</p>';
        document.getElementById('selected-time').value = '';
        await loadAppointments();

    } catch (error) {
        Swal.fire('Error', 'Connection error. Please try again.', 'error');
    }
}

async function loadAppointments() {
    if(!clientEmail) return; 

    try {
        const response = await fetch(`${API_URL}/appointments?client_email=${encodeURIComponent(clientEmail)}`);
        allAppointments = await response.json();

        const statusOrder = { 
            'pending': 1, 
            'approved': 2, 
            'completed': 3, 
            'noshow': 4,
            'rejected': 5, 
            'canceled': 6 
        };

        allAppointments.sort((a, b) => {
            const statusDiff = (statusOrder[a.status] || 99) - (statusOrder[b.status] || 99);
            if (statusDiff !== 0) return statusDiff;
            return b.id - a.id; 
        });

        filterAppointments();
    } catch (error) {
        console.error('Error loading appointments:', error);
    }
}

function filterAppointments() {
    const filter = document.getElementById('status-filter').value;
    let filtered = allAppointments;
    if (filter !== 'all') {
        filtered = allAppointments.filter(apt => apt.status === filter);
    }
    displayAppointments(filtered);
}

function formatDiagnosis(text) {
    if (!text) return '';
    if (!text.includes('[VITALS]')) return `<div style="padding:10px;">${text}</div>`;

    let html = text
        .replace('[VITALS]', '<div class="diag-header"><i class="fas fa-heartbeat"></i> Vital Signs</div><div class="diag-content">')
        .replace('[DIAGNOSIS]', '</div><div class="diag-header"><i class="fas fa-stethoscope"></i> Diagnosis</div><div class="diag-content">')
        .replace('[TREATMENT]', '</div><div class="diag-header"><i class="fas fa-pills"></i> Treatment</div><div class="diag-content">')
        .replace('[RECOMMENDATION]', '</div><div class="diag-header"><i class="fas fa-clipboard-check"></i> Recommendation</div><div class="diag-content">');
    
    return `<div class="diagnosis-box">${html}</div></div>`;
}

function displayAppointments(appointments) {
    const container = document.getElementById('appointments-list');
    
    if (!appointments || appointments.length === 0) {
        container.innerHTML = '<p style="text-align:center; color:#777; padding:20px;">No history found.</p>';
        return;
    }
    
    const htmlContent = appointments.map(apt => {
        const niceDate = new Date(apt.appointment_date).toDateString();
        const niceTime = formatTime(apt.appointment_time);
        
        let statusLabel = apt.status.toUpperCase();
        if(apt.status === 'noshow') statusLabel = 'NO SHOW';

        let noteHtml = '';
        if (apt.status === 'rejected' && apt.admin_note) {
            noteHtml = `<div style="margin-top:10px; background:#fff5f5; border-left:3px solid #ff5252; padding:10px; font-size:0.9rem; color:#c62828;">
                <i class="fas fa-exclamation-circle"></i> <strong>Admin Reason:</strong><br>${apt.admin_note}
            </div>`;
        } 
        else if (apt.status === 'completed' && apt.diagnosis) {
            noteHtml = formatDiagnosis(apt.diagnosis);
        } 
        else if (apt.status === 'approved') {
            noteHtml = `<div style="font-size:0.85rem; color:green; margin-top:8px; background:#e8f5e9; padding:5px; border-radius:5px;"><i class="fas fa-check-circle"></i> Ticket sent to ${clientEmail}</div>`;
        }

        const modeBadge = apt.booking_mode === 'ai_chatbot' ? `<span style="font-size:0.8rem; background:#f3e5f5; color:#8e44ad; padding:2px 6px; border-radius:4px;"><i class="fas fa-robot"></i> AI</span>` : '';

        let buttonsHtml = '';
        if (apt.status === 'pending') {
            buttonsHtml = `
                <button onclick="openRescheduleModal(${apt.id})" class="btn-primary" style="background:#f39c12; margin-bottom:0;">Reschedule</button>
                <button onclick="cancelAppointment(${apt.id})" class="btn-cancel" style="margin-bottom:0;">Cancel</button>
            `;
        } else if (apt.status === 'approved') {
            buttonsHtml = `<button onclick="openRescheduleModal(${apt.id})" class="btn-primary" style="background:#f39c12; margin-bottom:0;">Reschedule</button>`;
        }

        return `
        <div class="appointment-card">
            <div class="apt-header">
                <div><span style="font-weight:bold; color:#333;">#${apt.id}</span> <span style="color:#777; margin-left:5px; font-size:0.9rem;">${niceDate}</span></div>
                <span class="status-pill ${apt.status}">${statusLabel}</span>
            </div>
            <div class="apt-body">
                <p><strong><i class="far fa-clock"></i> Time:</strong> ${niceTime} ${modeBadge}</p>
                <p><strong><i class="fas fa-stethoscope"></i> Service:</strong> ${apt.service_type}</p>
                <p style="font-style:italic; color:#666; margin-top:5px; background:#f9f9f9; padding:8px; border-radius:5px;">"${apt.reason}"</p>
                ${noteHtml}
            </div>
            ${buttonsHtml ? `<div class="apt-actions">${buttonsHtml}</div>` : ''}
        </div>`;
    }).join('');

    container.innerHTML = htmlContent;
}

// --- utils ---
function initChatbot() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages && chatMessages.children.length === 0) {
        addChatMessage('bot', `Hello ${clientName}! I can help you book an appointment.`);
    }
}
function addChatMessage(sender, message) {
    const chatMessages = document.getElementById('chat-messages');
    if(!chatMessages) return;
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${sender}`;
    messageDiv.innerHTML = message.replace(/\n/g, '<br>');
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}
function showTypingIndicator() {
    const chatMessages = document.getElementById('chat-messages');
    const typingDiv = document.createElement('div');
    typingDiv.id = 'ai-typing-indicator';
    typingDiv.className = 'chat-message bot typing-indicator';
    typingDiv.innerHTML = 'Thinking...';
    chatMessages.appendChild(typingDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}
function removeTypingIndicator() {
    const typingDiv = document.getElementById('ai-typing-indicator');
    if (typingDiv) typingDiv.remove();
}
async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;
    
    addChatMessage('user', message);
    input.value = '';
    chatHistory.push({ role: "user", message: message });
    showTypingIndicator();

    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_email: clientEmail, message: message, history: chatHistory }) 
        });
        const data = await response.json();
        removeTypingIndicator();
        chatHistory.push({ role: "model", message: data.response });
        addChatMessage('bot', data.response);
        if (data.refresh === true) loadAppointments();
    } catch (error) {
        removeTypingIndicator();
        addChatMessage('bot', 'System offline.');
    }
}
function handleEnter(e) { if (e.key === 'Enter') sendChatMessage(); }

function formatTime(timeStr) {
    if (!timeStr) return "";
    if (timeStr.toString().includes('AM') || timeStr.toString().includes('PM')) return timeStr;
    const parts = timeStr.split(':');
    let hour = parseInt(parts[0]);
    const minutes = parts[1];
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12; hour = hour ? hour : 12; 
    return `${hour}:${minutes} ${ampm}`;
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('active');
    document.getElementById('overlay').classList.toggle('active');
}

async function loadTimeSlots() {
    const date = document.getElementById('book-date').value;
    const container = document.getElementById('slots-container');
    const timeInput = document.getElementById('selected-time');
    timeInput.value = '';
    if(!date) return;
    container.innerHTML = 'Checking...';
    try {
        const response = await fetch(`${API_URL}/slots?date=${date}`);
        const slots = await response.json();
        container.innerHTML = ''; 
        if(slots.length === 0) { container.innerHTML = '<p style="color:red">Full.</p>'; return; }
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
    } catch(error) { console.error(error); }
}

function openRescheduleModal(id) {
    const apt = allAppointments.find(a => a.id === id);
    if (!apt) return;
    document.getElementById('reschedule-id').value = id;
    document.getElementById('reschedule-modal').style.display = 'flex';
    document.getElementById('reschedule-date').value = apt.appointment_date;
    loadRescheduleSlots(); 
}
function closeRescheduleModal() { document.getElementById('reschedule-modal').style.display = 'none'; }

async function loadRescheduleSlots() {
    const date = document.getElementById('reschedule-date').value;
    const container = document.getElementById('reschedule-slots');
    const timeInput = document.getElementById('reschedule-time');
    if(!date) return;
    container.innerHTML = 'Loading...';
    try {
        const response = await fetch(`${API_URL}/slots?date=${date}`);
        const slots = await response.json();
        container.innerHTML = '';
        if(slots.length === 0) return container.innerHTML = 'No slots.';
        slots.forEach(time => {
            const btn = document.createElement('div');
            btn.className = 'slot-btn';
            btn.textContent = formatTime(time);
            btn.onclick = () => {
                document.querySelectorAll('#reschedule-slots .slot-btn').forEach(b => b.classList.remove('selected'));
                btn.classList.add('selected');
                timeInput.value = time;
            };
            container.appendChild(btn);
        });
    } catch (e) { console.error(e); }
}

async function submitReschedule() {
    const id = document.getElementById('reschedule-id').value;
    const date = document.getElementById('reschedule-date').value;
    const time = document.getElementById('reschedule-time').value;
    if(!date || !time) return Swal.fire('Error', 'Select date and time', 'warning');
    try {
        const res = await fetch(`${API_URL}/appointments/${id}/reschedule`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ appointment_date: date, appointment_time: time })
        });
        if(res.ok) { Swal.fire('Success', 'Rescheduled!', 'success'); closeRescheduleModal(); loadAppointments(); } 
        else { Swal.fire('Error', 'Failed to reschedule.', 'error'); }
    } catch(e) { console.error(e); }
}

async function cancelAppointment(id) {
    Swal.fire({
        title: 'Cancel Request?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        confirmButtonText: 'Yes'
    }).then(async (result) => {
        if (result.isConfirmed) {
            try {
                const response = await fetch(`${API_URL}/appointments/${id}`, { method: 'DELETE' });
                if (response.ok) { Swal.fire('Canceled', 'Request canceled.', 'success'); loadAppointments(); } 
                else { Swal.fire('Error', 'Could not cancel.', 'error'); }
            } catch (e) { console.error(e); }
        }
    });
}

setInterval(loadAppointments, 5000);