const API_URL = 'http://localhost:8000/api';
let allAppointments = [];

// check auth
const token = localStorage.getItem('token');
const role = localStorage.getItem('role');
if (!token || role !== 'student') {
    window.location.href = 'index.html';
}

// display user name - trying both keys just in case
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
    
    document.getElementById(`${tabName}-tab`).classList.add('active');
    event.currentTarget.classList.add('active'); 
    
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
    const timeRaw = document.getElementById('book-time').value;
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
async function loadAppointments() {
    const container = document.getElementById('appointments-list');
    container.innerHTML = '<p>Loading...</p>';

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
        container.innerHTML = '<p>Error loading appointments</p>';
    }
}

function displayAppointments(appointments) {
    const container = document.getElementById('appointments-list');
    
    if (!appointments || appointments.length === 0) {
        container.innerHTML = '<p>No appointments found</p>';
        return;
    }
    
    container.innerHTML = appointments.map(apt => {
        // format date nice
        const niceDate = new Date(apt.appointment_date).toDateString();
        // format time nice
        const niceTime = formatTime(apt.appointment_time);
        
        // capitalize status
        const statusLabel = apt.status.charAt(0).toUpperCase() + apt.status.slice(1);

        // admin note logic
        let adminNoteHtml = '';
        if (apt.status === 'rejected' && apt.admin_note) {
            adminNoteHtml = `
                <div class="admin-note-box">
                    <i class="fas fa-exclamation-circle"></i> 
                    <strong>Reason for Rejection:</strong><br> 
                    ${apt.admin_note}
                </div>
            `;
        }

        // --- fixed button logic here ---
        let actionButtonsHtml = '';
        
        if (apt.status === 'pending') {
            // pending: cancel only
            actionButtonsHtml = `<button onclick="cancelAppointment(${apt.id})" class="btn-cancel">Cancel Request</button>`;
        } 
        else if (apt.status === 'approved') {
            // approved: download ticket AND delete (cancel) button
            actionButtonsHtml = `
                <div style="display:flex; flex-direction:column; gap:5px; width:100%;">
                    <button onclick='generateTicket(${JSON.stringify(apt)})' class="btn-primary" style="background-color:#2ecc71;">
                        <i class="fas fa-download"></i> Download Ticket
                    </button>
                    <button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Cancel Appointment</button>
                </div>`;
        } 
        else if (apt.status === 'completed') {
             // completed: text AND delete history
             actionButtonsHtml = `
                <div style="display:flex; flex-direction:column; gap:5px; width:100%;">
                    <span style="color:green; font-weight:bold; text-align:left; padding:5px;">Visit Completed ✅</span>
                    <button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Delete History</button>
                </div>`;
        } 
        else {
            // rejected or canceled: delete only
            actionButtonsHtml = `<button onclick="deleteHistory(${apt.id})" class="btn-cancel" style="background-color: #ffcdd2; color: #c62828;">Delete History</button>`;
        }

        return `
        <div class="appointment-card status-${apt.status}">
            <div class="apt-header">
                <span class="apt-date">${niceDate}</span>
                <span class="status-pill ${apt.status}">${statusLabel}</span>
            </div>
            <div class="apt-body">
                <p><strong>Time:</strong> ${niceTime}</p>
                <p><strong>Service:</strong> ${apt.service_type || 'General'}</p>
                <p><strong>Urgency:</strong> ${apt.urgency || 'Low'}</p>
                <p><strong>Reason:</strong> ${apt.reason}</p>
                <p><strong>Mode:</strong> ${apt.booking_mode === 'ai_chatbot' ? 'AI Chatbot' : 'Standard'}</p>
                
                ${adminNoteHtml}
            </div>
            <div class="apt-actions">
                ${actionButtonsHtml}
            </div>
        </div>
        `;
    }).join('');
}

// generate ticket png
function generateTicket(apt) {
    // 1. fill data
    document.getElementById('pdf-name').textContent = apt.student_name || 'Student'; 
    document.getElementById('pdf-date').textContent = apt.appointment_date;
    // use helper to show am/pm on ticket
    document.getElementById('pdf-time').textContent = formatTime(apt.appointment_time);
    document.getElementById('pdf-service').textContent = apt.service_type;
    document.getElementById('pdf-id').textContent = `#${apt.id}`;

    // 2. generate qr code
    const qrContainer = document.getElementById('pdf-qr-code');
    qrContainer.innerHTML = ""; 
    new QRCode(qrContainer, {
        text: String(apt.id),
        width: 120,
        height: 120,
        colorDark : "#000000",
        colorLight : "#ffffff",
        correctLevel : QRCode.CorrectLevel.H
    });

    // 3. create image using html2canvas
    Swal.fire({
        title: 'Generating Ticket...',
        text: 'Please wait a moment.',
        didOpen: () => { Swal.showLoading() }
    });

    // wait for qr code to fully render
    setTimeout(() => {
        const element = document.getElementById('ticket-template');
        
        html2canvas(element).then(canvas => {
            // convert canvas to image url
            const imgData = canvas.toDataURL("image/png");
            
            // create temporary link to download
            const link = document.createElement('a');
            link.download = `Ticket_${apt.id}.png`;
            link.href = imgData;
            link.click();
            
            Swal.close();
            
            Swal.fire({
                icon: 'success',
                title: 'Downloaded!',
                text: 'Your ticket has been saved as an image.',
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
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, proceed'
    }).then(async (result) => {
        if (result.isConfirmed) {
            await deleteOrCancel(id, 'Appointment removed.');
        }
    });
}

async function cancelAppointment(id) {
    Swal.fire({
        title: 'Cancel Request?',
        text: "Are you sure you want to cancel?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, cancel it'
    }).then(async (result) => {
        if (result.isConfirmed) {
            await deleteOrCancel(id, 'Appointment canceled successfully.');
        }
    });
}

async function deleteOrCancel(id, successMsg) {
    try {
        const response = await fetch(`${API_URL}/appointments/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (response.ok) {
            Swal.fire('Done!', successMsg, 'success');
            loadAppointments();
        } else {
            Swal.fire('Error', 'Failed to update.', 'error');
        }
    } catch (error) {
        console.error(error);
        Swal.fire('Error', 'Connection failed.', 'error');
    }
}

function filterAppointments() {
    const filter = document.getElementById('status-filter').value;
    if (filter === 'all') {
        displayAppointments(allAppointments);
    } else {
        const filtered = allAppointments.filter(apt => apt.status === filter);
        displayAppointments(filtered);
    }
}

// chatbot logic
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
    messageDiv.textContent = message;
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// logic ai chat function
async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    
    if (!message) return;
    
    addChatMessage('user', message);
    input.value = '';
    
    try {
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ message }) 
        });
        
        const data = await response.json();
        addChatMessage('bot', data.response);
        
        // logic ai refresh trigger
        if (data.response.includes("booked") || data.response.includes("confirmed")) {
            loadAppointments();
        }

    } catch (error) {
        console.error('Chat error:', error);
        addChatMessage('bot', 'Sorry, I encountered an error. Please try again.');
    }
}

const chatInput = document.getElementById('chat-input');
if(chatInput) {
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendChatMessage();
        }
    });
}

function handleEnter(e) {
    if (e.key === 'Enter') sendChatMessage();
}

// helper to convert 24h to 12h am/pm
function formatTime(timeStr) {
    if (!timeStr) return "";
    
    const [hours, minutes] = timeStr.split(':');
    let hour = parseInt(hours);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    
    hour = hour % 12;
    hour = hour ? hour : 12; 
    
    return `${hour}:${minutes} ${ampm}`;
}

loadAppointments();