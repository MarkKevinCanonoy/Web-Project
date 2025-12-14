const API_URL = 'http://localhost:8000/api';
let currentAppointmentId = null;

// to check authentication
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user') || '{}');

if (!token) {
    window.location.href = 'index.html';
}

// display user name
document.getElementById('user-name').textContent = `Welcome, ${user.full_name}`;

if (user.role !== 'student') {
    document.getElementById('btn-new-appointment').style.display = 'none';
}

function logout() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = 'index.html';
}

function showAppointmentForm() {
    document.getElementById('appointment-form').style.display = 'block';
}

function hideAppointmentForm() {
    document.getElementById('appointment-form').style.display = 'none';
    document.getElementById('create-appointment-form').reset();
}

async function loadAppointments() {
    try {
        const response = await fetch(`${API_URL}/appointments`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (response.status === 401) {
            logout();
            return;
        }
        
        const appointments = await response.json();
        displayAppointments(appointments);
    } catch (error) {
        document.getElementById('appointments-list').innerHTML = '<p style="color: red;">Error loading appointments</p>';
    }
}

function displayAppointments(appointments) {
    const list = document.getElementById('appointments-list');
    
    if (appointments.length === 0) {
        list.innerHTML = '<p>No appointments found</p>';
        return;
    }
    
    list.innerHTML = appointments.map(apt => `
        <div class="appointment-card status-${apt.status}">
            <h4>Appointment #${apt.id}</h4>
            ${user.role !== 'student' ? `<p><strong>Student:</strong> ${apt.full_name}</p>` : ''}
            <p><strong>Date:</strong> ${apt.appointment_date}</p>
            <p><strong>Time:</strong> ${apt.appointment_time}</p>
            <p><strong>Reason:</strong> ${apt.reason}</p>
            <p><strong>Status:</strong> <span style="text-transform: uppercase; font-weight: bold;">${apt.status}</span></p>
            <div style="margin-top: 10px; display: flex; gap: 10px; flex-wrap: wrap;">
                ${user.role !== 'student' ? `
                    ${apt.status === 'pending' ? `
                        <button onclick="updateStatus(${apt.id}, 'approved')" style="padding: 5px 10px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer;">Approve</button>
                        <button onclick="updateStatus(${apt.id}, 'rejected')" style="padding: 5px 10px; background: #dc3545; color: white; border: none; border-radius: 4px; cursor: pointer;">Reject</button>
                    ` : ''}
                ` : ''}
                <button onclick="openChat(${apt.id})" style="padding: 5px 10px; background: #1E88E5; color: white; border: none; border-radius: 4px; cursor: pointer;">Chat</button>
            </div>
        </div>
    `).join('');
}

document.getElementById('create-appointment-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const date = document.getElementById('appointment-date').value;
    const time = document.getElementById('appointment-time').value;
    const reason = document.getElementById('reason').value;
    
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
                reason: reason
            })
        });
        
        if (response.ok) {
            hideAppointmentForm();
            loadAppointments();
            alert('Appointment created successfully!');
        } else {
            const data = await response.json();
            alert(data.detail || 'Failed to create appointment');
        }
    } catch (error) {
        alert('Error creating appointment');
    }
});

async function updateStatus(appointmentId, status) {
    try {
        const response = await fetch(`${API_URL}/appointments/${appointmentId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ status })
        });
        
        if (response.ok) {
            loadAppointments();
            alert(`Appointment ${status} successfully!`);
        } else {
            alert('Failed to update appointment');
        }
    } catch (error) {
        alert('Error updating appointment');
    }
}

async function openChat(appointmentId) {
    currentAppointmentId = appointmentId;
    document.getElementById('modal-appointment-id').textContent = appointmentId;
    document.getElementById('chat-modal').style.display = 'block';
    loadMessages();
}

function closeChatModal() {
    document.getElementById('chat-modal').style.display = 'none';
    currentAppointmentId = null;
}

async function loadMessages() {
    try {
        const response = await fetch(`${API_URL}/appointments/${currentAppointmentId}/messages`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        const messages = await response.json();
        displayMessages(messages);
    } catch (error) {
        document.getElementById('chat-messages').innerHTML = '<p style="color: red;">Error loading messages</p>';
    }
}

function displayMessages(messages) {
    const chatDiv = document.getElementById('chat-messages');
    
    if (messages.length === 0) {
        chatDiv.innerHTML = '<p style="color: #999;">No messages yet</p>';
        return;
    }
    
    chatDiv.innerHTML = messages.map(msg => `
        <div style="margin-bottom: 10px; padding: 10px; background: ${msg.user_id === user.id ? '#E3F2FD' : '#F5F5F5'}; border-radius: 8px;">
            <strong>${msg.full_name} (${msg.role}):</strong>
            <p style="margin: 5px 0 0 0;">${msg.message}</p>
            <small style="color: #666;">${new Date(msg.created_at).toLocaleString()}</small>
        </div>
    `).join('');
    
    chatDiv.scrollTop = chatDiv.scrollHeight;
}

document.getElementById('chat-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const message = document.getElementById('chat-input').value;
    
    try {
        const response = await fetch(`${API_URL}/appointments/${currentAppointmentId}/messages`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                appointment_id: currentAppointmentId,
                message: message
            })
        });
        
        if (response.ok) {
            document.getElementById('chat-input').value = '';
            loadMessages();
        } else {
            alert('Failed to send message');
        }
    } catch (error) {
        alert('Error sending message');
    }
});

loadAppointments();