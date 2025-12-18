const API_URL = 'http://localhost:8000/api';
let allAppointments = [];
let chatHistory = []; 

// check auth
const token = localStorage.getItem('token');
const role = localStorage.getItem('role');
if (!token || role !== 'student') {
    window.location.href = 'index.html';
}

// display user name
const storedName = localStorage.getItem('full_name') || localStorage.getItem('fullName') || 'Student';
document.getElementById('user-name').textContent = storedName;

// set minimum date to today
const dateInput = document.getElementById('book-date'); 
if(dateInput) {
    dateInput.min = new Date().toISOString().split('T')[0];
}

// tab switching
function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    
    // sidebar handling
    document.querySelectorAll('.sidebar-btn').forEach(btn => btn.classList.remove('active'));
    
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    // highlight button
    const buttons = document.querySelectorAll('button');
    buttons.forEach(btn => {
        if(btn.onclick && btn.onclick.toString().includes(tabName)) {
            btn.classList.add('active');
        }
    });
    
    if (tabName === 'appointments') {
        loadAppointments();
    } else if (tabName === 'chatbot') {
        initChatbot();
    }
}

function logout() {
    Swal.fire({
        title: 'Sign out?',
        text: "You will need to login again.",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#e74c3c',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, logout'
    }).then((result) => {
        if (result.isConfirmed) {
            localStorage.clear();
            window.location.href = 'index.html';
        }
    });
}

// manual booking logic
async function handleBooking(e) {
    e.preventDefault(); 
    
    const form = document.getElementById('booking-form');

    // getting values
    const serviceType = document.getElementById('book-type').value;
    const date = document.getElementById('book-date').value;
    // const timeRaw = document.getElementById('book-time').value;
    const timeRaw = document.getElementById('selected-time').value;
    const urgency = document.getElementById('book-urgency').value;
    const reason = document.getElementById('book-reason').value;

    // validation
    if(!serviceType || !date || !timeRaw || !reason || !urgency) {
        Swal.fire('Missing Details', 'Please fill in all required fields.', 'warning');
        return;
    }

    const time = timeRaw.length === 5 ? timeRaw + ":00" : timeRaw;

    try {
        const response = await fetch(`${API_URL}/appointments`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
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
            title: 'Booked!',
            text: 'Your appointment has been scheduled.',
            confirmButtonColor: '#1E88E5'
        });

        form.reset();
        await loadAppointments();

    } catch (error) {
        console.error('Booking error:', error);
        Swal.fire('Error', 'Connection error. Please try again.', 'error');
    }
}

// load appointments
// [UPDATED] Silent Load (No flashing "Loading..." text)
async function loadAppointments() {
    // We REMOVED the line that says "Loading..." so it doesn't blink
    const container = document.getElementById('appointments-list');

    try {
        const response = await fetch(`${API_URL}/appointments`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        allAppointments = await response.json();
        displayAppointments(allAppointments);
        
    } catch (error) {
        console.error('Error loading appointments:', error);
        // Only show error if the container is empty, otherwise keep old data
        if(container.children.length === 0) {
            container.innerHTML = '<p>Error loading appointments</p>';
        }
    }
}

// [UPDATED] Display Logic including No-Show CSS
function displayAppointments(appointments) {
    const container = document.getElementById('appointments-list');
    
    if (!appointments || appointments.length === 0) {
        container.innerHTML = '<p>No appointments found</p>';
        return;
    }
    
    container.innerHTML = appointments.map(apt => {
        const niceDate = new Date(apt.appointment_date).toDateString();
        const niceTime = formatTime(apt.appointment_time);
        
        // Capitalize status
        let statusLabel = apt.status.charAt(0).toUpperCase() + apt.status.slice(1);
        if(apt.status === 'noshow') statusLabel = 'No Show';

let adminNoteHtml = '';
        
        // 1. Rejected Note
        if (apt.status === 'rejected' && apt.admin_note) {
            adminNoteHtml = `
                <div class="admin-note-box">
                    <i class="fas fa-exclamation-circle"></i> 
                    <strong>Reason for Rejection:</strong><br> 
                    ${apt.admin_note}
                </div>
            `;
        } 
        // 2. No Show Note
        else if (apt.status === 'noshow' && apt.admin_note) {
             adminNoteHtml = `
                <div class="admin-note-box" style="background-color:#eceff1; border-color:#cfd8dc; color:#455a64;">
                    <i class="fas fa-user-clock"></i> 
                    <strong>Status:</strong> ${apt.admin_note}
                </div>
            `;
        }
        // [NEW] 3. Completed / Diagnosis Note
        else if (apt.status === 'completed' && apt.admin_note) {
             adminNoteHtml = `
                <div class="admin-note-box" style="background-color:#e8f5e9; border-color:#a5d6a7; color:#2e7d32;">
                    <i class="fas fa-user-md"></i> 
                    <strong>Diagnosis / Remarks:</strong><br> 
                    ${apt.admin_note}
                </div>
            `;
        }

        const modeBadge = apt.booking_mode === 'ai_chatbot' 
            ? `<span style="font-size:0.8rem; background:#f3e5f5; color:#8e44ad; padding:2px 6px; border-radius:4px;"><i class="fas fa-robot"></i> AI Booking</span>` 
            : '';

        let actionButtonsHtml = '';
        
if (apt.status === 'pending') {
    actionButtonsHtml = `
        <button onclick="openRescheduleModal(${apt.id})" class="btn-primary" style="background:#f39c12; margin-bottom:5px;">Reschedule</button>
        <button onclick="cancelAppointment(${apt.id})" class="btn-cancel">Cancel Request</button>
    `;
} 
else if (apt.status === 'approved') {
    actionButtonsHtml = `
        <div style="display:flex; flex-direction:column; gap:5px; width:100%;">
            <button onclick='generateTicket(${JSON.stringify(apt)})' class="btn-primary" style="background-color:#2ecc71;">
                <i class="fas fa-download"></i> Download Ticket
            </button>
            <button onclick="openRescheduleModal(${apt.id})" class="btn-primary" style="background:#f39c12;">Reschedule</button>
            <button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Cancel Appointment</button>
        </div>`;
}
        else if (apt.status === 'completed') {
             actionButtonsHtml = `
                <div style="display:flex; flex-direction:column; gap:5px; width:100%;">
                    <span style="color:green; font-weight:bold; text-align:left; padding:5px;">Visit Completed</span>
                    <button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Delete History</button>
                </div>`;
        } 
        else if (apt.status === 'noshow') {
             // [NEW] No Show Action
             actionButtonsHtml = `
                <div style="display:flex; flex-direction:column; gap:5px; width:100%;">
                    <span style="color:#607d8b; font-weight:bold; text-align:left; padding:5px;">Missed Appointment</span>
                    <button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #cfd8dc; color: #455a64; border-color:#b0bec5;">Delete History</button>
                </div>`;
        }
        else {
            actionButtonsHtml = `<button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Delete History</button>`;
        }

        // [NEW] Inline CSS to handle styling without editing CSS file
        let cardStyle = '';
        let pillStyle = '';
        
        if (apt.status === 'noshow') {
            cardStyle = 'border-left-color: #607d8b;';
            pillStyle = 'background-color: #cfd8dc; color: #455a64;';
        }

        return `
        <div class="appointment-card status-${apt.status}" style="${cardStyle}">
            <div class="apt-header">
                <span class="apt-date">${niceDate}</span>
                <span class="status-pill ${apt.status}" style="${pillStyle}">${statusLabel}</span>
            </div>
            <div class="apt-body">
                <p><strong>Time:</strong> ${niceTime} ${modeBadge}</p>
                <p><strong>Service:</strong> ${apt.service_type || 'General'}</p>
                <p><strong>Urgency:</strong> ${apt.urgency || 'Low'}</p>
                <p><strong>Reason:</strong> ${apt.reason}</p>
                
                ${adminNoteHtml}
            </div>
            <div class="apt-actions">
                ${actionButtonsHtml}
            </div>
        </div>
        `;
    }).join('');
}

// [FIX] BIGGER QR CODE LOGIC HERE
function generateTicket(apt) {
    // 1. Fill data
    document.getElementById('pdf-name').textContent = apt.student_name || 'Student'; 
    document.getElementById('pdf-date').textContent = apt.appointment_date;
    document.getElementById('pdf-time').textContent = formatTime(apt.appointment_time);
    document.getElementById('pdf-service').textContent = apt.service_type;
    document.getElementById('pdf-id').textContent = `#${apt.id}`;

    // 2. Generate QR code (BIGGER SIZE: 200x200)
    const qrContainer = document.getElementById('pdf-qr-code');
    qrContainer.innerHTML = ""; 
    new QRCode(qrContainer, {
        text: String(apt.id),
        width: 200,  // Increased from 120
        height: 200, // Increased from 120
        colorDark : "#000000",
        colorLight : "#ffffff",
        correctLevel : QRCode.CorrectLevel.H
    });

    Swal.fire({
        title: 'Generating Ticket...',
        text: 'Please wait a moment.',
        didOpen: () => { Swal.showLoading() }
    });

    setTimeout(() => {
        const element = document.getElementById('ticket-template');
        html2canvas(element).then(canvas => {
            const imgData = canvas.toDataURL("image/png");
            const link = document.createElement('a');
            link.download = `Ticket_${apt.id}.png`;
            link.href = imgData;
            link.click();
            Swal.close();
            Swal.fire({
                icon: 'success',
                title: 'Downloaded!',
                text: 'Your ticket has been saved.',
                confirmButtonColor: '#1E88E5'
            });
        });
    }, 500); 
}

async function deleteHistory(id) {
    Swal.fire({
        title: 'Are you sure?',
        text: "You are about to remove this appointment.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        confirmButtonText: 'Yes, proceed'
    }).then(async (result) => {
        if (result.isConfirmed) { await deleteOrCancel(id, 'Appointment removed.'); }
    });
}

async function cancelAppointment(id) {
    Swal.fire({
        title: 'Cancel Request?',
        text: "Are you sure you want to cancel?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        confirmButtonText: 'Yes, cancel it'
    }).then(async (result) => {
        if (result.isConfirmed) { await deleteOrCancel(id, 'Appointment canceled successfully.'); }
    });
}

async function deleteOrCancel(id, successMsg) {
    try {
        const response = await fetch(`${API_URL}/appointments/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (response.ok) { Swal.fire('Done!', successMsg, 'success'); loadAppointments(); } 
        else { Swal.fire('Error', 'Failed to update.', 'error'); }
    } catch (error) { console.error(error); Swal.fire('Error', 'Connection failed.', 'error'); }
}

function filterAppointments() {
    const filter = document.getElementById('status-filter').value;
    if (filter === 'all') { displayAppointments(allAppointments); } 
    else { const filtered = allAppointments.filter(apt => apt.status === filter); displayAppointments(filtered); }
}

function initChatbot() {
    const chatMessages = document.getElementById('chat-messages');
    if (chatMessages && chatMessages.children.length === 0) {
        addChatMessage('bot', "Hello! I'm here to help you book an appointment. Please tell me when you'd like to visit the clinic and what's the reason for your visit.");
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
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ message: message, history: chatHistory }) 
        });
        const data = await response.json();
        chatHistory.push({ role: "model", message: data.response });
        addChatMessage('bot', data.response);
        if (data.response.toLowerCase().includes("booked") || data.response.toLowerCase().includes("canceled")) {
            loadAppointments(); 
        }
    } catch (error) {
        console.error('Chat error:', error);
        addChatMessage('bot', 'Sorry, I encountered an error. Please try again.');
    }
}

function handleEnter(e) { if (e.key === 'Enter') sendChatMessage(); }

function formatTime(timeStr) {
    if (!timeStr) return "";

    // [FIX] Check if it's already formatted (Has AM or PM)
    // If yes, just return it as is. Do not format it again.
    if (timeStr.includes('AM') || timeStr.includes('PM')) {
        return timeStr;
    }

    // Otherwise, perform the standard 24h -> 12h conversion
    // (This handles "14:00:00" -> "2:00 PM")
    const parts = timeStr.split(':');
    let hour = parseInt(parts[0]);
    const minutes = parts[1];
    
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12; 
    hour = hour ? hour : 12; // convert 0 to 12
    
    return `${hour}:${minutes} ${ampm}`;
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    sidebar.classList.toggle('active');
    overlay.classList.toggle('active');
}


// 1. Function to load slots from the backend
async function loadTimeSlots() {
    const date = document.getElementById('book-date').value;
    const container = document.getElementById('slots-container');
    const timeInput = document.getElementById('selected-time');
    
    // Clear previous selection
    timeInput.value = '';
    
    if(!date) return;
    
    container.innerHTML = '<p style="font-size:0.9rem; color:#666;">Checking availability...</p>';

    try {
        const response = await fetch(`${API_URL}/slots?date=${date}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const slots = await response.json();
        
        container.innerHTML = ''; // Clear "Checking..." text

        if(slots.length === 0) {
            container.innerHTML = '<p style="color:red; font-size:0.9rem;">Full for this day. Please choose another date.</p>';
            return;
        }

        // Create a button for each available time
        slots.forEach(time => {
            const btn = document.createElement('div');
            btn.className = 'slot-btn';
            btn.textContent = formatTime(time); // Use your existing formatTime helper
            
            // When clicked
            btn.onclick = () => {
                // Remove 'selected' class from all other buttons
                document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
                // Add 'selected' class to this button
                btn.classList.add('selected');
                // Save the value to the hidden input
                timeInput.value = time;
            };
            
            container.appendChild(btn);
        });
    } catch(error) {
        console.error(error);
        container.innerHTML = '<p style="color:red;">Error loading slots.</p>';
    }
}

// 2. MODIFY your existing handleBooking function
// You need to change how it gets the time value.
/* Find: const timeRaw = document.getElementById('book-time').value;
   Replace it with: 
*/
// const timeRaw = document.getElementById('selected-time').value;

// --- RESCHEDULE LOGIC ---

function openRescheduleModal(id) {
    // 1. Find the appointment details from the list we already loaded
    const apt = allAppointments.find(a => a.id === id);
    if (!apt) return;

    document.getElementById('reschedule-id').value = id;
    document.getElementById('reschedule-modal').style.display = 'flex';
    
    // 2. Set min date to today (standard rule)
    const dateInput = document.getElementById('reschedule-date');
    dateInput.min = new Date().toISOString().split('T')[0];

    // 3. Pre-fill the input with the EXISTING appointment date
    // (This fixes the "date is assigned" part)
    dateInput.value = apt.appointment_date;

    // 4. [CRITICAL FIX] Manually trigger the slot loader immediately
    // This makes the time buttons appear without needing to change the date
    loadRescheduleSlots(); 
}

function closeRescheduleModal() {
    document.getElementById('reschedule-modal').style.display = 'none';
}

async function loadRescheduleSlots() {
    const date = document.getElementById('reschedule-date').value;
    const container = document.getElementById('reschedule-slots');
    const timeInput = document.getElementById('reschedule-time');

    if(!date) return;
    
    container.innerHTML = '<p>Loading...</p>';
    
    try {
        const response = await fetch(`${API_URL}/slots?date=${date}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const slots = await response.json();
        
        container.innerHTML = '';
        if(slots.length === 0) {
            container.innerHTML = '<p style="color:red">No slots available.</p>';
            return;
        }

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

    if(!date || !time) {
        Swal.fire('Error', 'Please select a new date and time', 'warning');
        return;
    }

    try {
        const res = await fetch(`${API_URL}/appointments/${id}/reschedule`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ appointment_date: date, appointment_time: time })
        });
        
        const data = await res.json();
        
        if(res.ok) {
            Swal.fire('Success', 'Appointment rescheduled!', 'success');
            closeRescheduleModal();
            loadAppointments();
        } else {
            Swal.fire('Error', data.detail, 'error');
        }
    } catch(e) { console.error(e); }
}


loadAppointments();

// Auto-refresh data every 2 seconds (2000 milliseconds)
setInterval(loadAppointments, 2000);