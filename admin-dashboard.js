const API_URL = 'http://localhost:8000/api';
let allAppointments = [];
let allUsers = []; // [NEW] Store users globally for search
let currentAppointmentId = null;
let html5QrcodeScanner = null;

// authentication check
const token = localStorage.getItem('token');
const role = localStorage.getItem('role');
const fullName = localStorage.getItem('full_name') || 'Admin';

// [NEW] Get Current User ID from Token to prevent self-delete
let currentUserId = null;
if (token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        currentUserId = payload.user_id;
    } catch (e) {
        console.error("Error parsing token", e);
    }
}

if (!token || (role !== 'admin' && role !== 'super_admin')) {
    Swal.fire({
        icon: 'error',
        title: 'Unauthorized',
        text: 'Redirecting to login...',
        timer: 1500,
        showConfirmButton: false
    }).then(() => {
        window.location.href = 'index.html';
    });
}

document.getElementById('user-name').textContent = fullName;
document.getElementById('user-role').textContent = role === 'super_admin' ? 'Super Admin' : 'Admin';

document.addEventListener('DOMContentLoaded', () => {
    loadQueue();
    loadAppointments(); 
    if(role === 'super_admin') {
        loadUsers();
    } else {
        const userTabBtn = document.getElementById('manage-users-tab');
        if(userTabBtn) userTabBtn.style.display = 'none';
    }
});

function showTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(tabName + '-tab').style.display = 'block';
    event.currentTarget.classList.add('active');
    
    if (tabName === 'scanner') {
        startScanner();
    } else {
        stopScanner();
    }

    if (tabName === 'appointments') loadAppointments();
    if (tabName === 'users') loadUsers();
    if (tabName === 'queue') loadQueue();
}

function logout() {
    Swal.fire({
        title: 'Sign out?',
        text: "You will return to the login screen.",
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

// [NEW] Password Toggle Function
function togglePasswordVisibility(inputId, icon) {
    const input = document.getElementById(inputId);
    if (input.type === "password") {
        input.type = "text";
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
    } else {
        input.type = "password";
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
    }
}

// ==========================================
//  QUEUE LOGIC 
// ==========================================

// [UPDATED] Silent Queue Load
async function loadQueue() {
    const container = document.getElementById('queue-display-area');
    // Removed "Loading..." text to prevent blinking

    try {
        const response = await fetch(`${API_URL}/appointments`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json();

        let queue = data.filter(a => a.status === 'approved');

        queue.sort((a, b) => {
            const dateA = new Date(a.appointment_date + 'T' + a.appointment_time);
            const dateB = new Date(b.appointment_date + 'T' + b.appointment_time);
            return dateA - dateB;
        });

        renderQueue(queue);

    } catch (e) {
        console.error(e);
    }
}

function renderQueue(queue) {
    const container = document.getElementById('queue-display-area');
    
    if (queue.length === 0) {
        container.innerHTML = `
            <div class="empty-queue">
                <i class="fas fa-mug-hot"></i>
                <h3>No approved appointments in queue.</h3>
                <p>Enjoy your break!</p>
            </div>
        `;
        return;
    }

    const nextPatient = queue[0];
    const waitingList = queue.slice(1); 

    const niceTime = formatTime(nextPatient.appointment_time);
    const niceDate = formatDate(nextPatient.appointment_date);

    let html = `
        <div class="hero-card">
            <div class="hero-time">${niceTime}</div>
            
            <div class="hero-name">
                <span style="opacity:0.6; font-size:0.7em;">#${nextPatient.id}</span><br>
                ${nextPatient.student_name}
            </div>
            
            <div class="hero-details">
                <i class="fas fa-calendar-day"></i> ${niceDate} &nbsp;|&nbsp; 
                <i class="fas fa-stethoscope"></i> ${nextPatient.service_type}
            </div>
            
            <div style="background: #e3f2fd; color: #1565c0; padding: 10px; border-radius: 8px; margin-bottom: 20px; font-style: italic;">
                "${nextPatient.reason}"
            </div>
            
            <div class="hero-actions">
                <button onclick="handleNoShow(${nextPatient.id})" class="btn-noshow">
                    <i class="fas fa-user-slash"></i> No Show
                </button>
                <button onclick="handleCompleteQueue(${nextPatient.id})" class="btn-complete-hero">
                    <i class="fas fa-check-circle"></i> Complete Visit
                </button>
            </div>
        </div>
    `;

    if (waitingList.length > 0) {
        html += `<div class="queue-list-header">Up Next (${waitingList.length})</div>`;
        waitingList.forEach(apt => {
            html += `
                <div class="queue-item">
                    <div>
                        <h4><span style="color:#999; font-size:0.9em; font-weight:normal;">#${apt.id}</span> ${apt.student_name}</h4>
                        <p>${apt.service_type} • ${formatDate(apt.appointment_date)}</p>
                        <p style="font-size: 0.85rem; color: #666; margin-top: 2px;"><em>"${apt.reason}"</em></p>
                    </div>
                    <div class="queue-time">
                        ${formatTime(apt.appointment_time)}
                    </div>
                </div>
            `;
        });
    }

    container.innerHTML = html;
}
function handleNoShow(id) {
    Swal.fire({
        title: 'Mark as No Show?',
        text: "This will remove the time restriction and allow others to book.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#607d8b',
        confirmButtonText: 'Yes, No Show'
    }).then(async (result) => {
        if (result.isConfirmed) {
            await updateStatus(id, 'noshow', 'Student did not appear for appointment.');
            loadQueue(); 
        }
    });
}

function handleCompleteQueue(id) {
    Swal.fire({
        title: 'Complete Visit',
        input: 'textarea',
        inputLabel: 'Admin Notes / Diagnosis',
        inputPlaceholder: 'e.g., Given Paracetamol, advised rest, temperature 37.5C...',
        inputAttributes: {
            'aria-label': 'Type your notes here'
        },
        showCancelButton: true,
        confirmButtonColor: '#2ecc71',
        confirmButtonText: 'Complete Visit',
        cancelButtonText: 'Cancel'
    }).then(async (result) => {
        if (result.isConfirmed) {
            // Use the text they typed, or a default message if empty
            const note = result.value || 'Medical consultation completed.';
            
            await updateStatus(id, 'completed', note);
            
            // Reload to update UI
            loadQueue(); 
            loadAppointments();
        }
    });
}

async function updateStatus(id, status, note) {
    try {
        await fetch(`${API_URL}/appointments/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ status: status, admin_note: note })
        });
        const Toast = Swal.mixin({ toast: true, position: 'top-end', showConfirmButton: false, timer: 2000 });
        Toast.fire({ icon: 'success', title: 'Status updated' });
    } catch (e) { console.error(e); }
}

// ==========================================
//  EXISTING LOGIC
// ==========================================

function startScanner() {
    if (html5QrcodeScanner) return; 
    html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
    html5QrcodeScanner.render(onScanSuccess, onScanFailure);
}

function stopScanner() {
    if (html5QrcodeScanner) {
        html5QrcodeScanner.clear().catch(error => { console.error("Failed to clear scanner", error); });
        html5QrcodeScanner = null;
    }
}

async function onScanSuccess(decodedText, decodedResult) {
    stopScanner(); // Stop camera immediately so it doesn't scan twice
    const appointmentId = decodedText;
    
    document.getElementById('scan-result').innerHTML = `Scanned ID: ${appointmentId}. Waiting for remarks...`;

    // 1. Ask for Nurse Notes
    const { value: note, isConfirmed } = await Swal.fire({
        title: 'Ticket Scanned!',
        html: `Processing Appointment <strong>#${appointmentId}</strong>.<br>Enter diagnosis or remarks:`,
        input: 'textarea',
        inputPlaceholder: 'e.g. Temperature 36.5, given paracetamol...',
        inputAttributes: { 'aria-label': 'Type your notes here' },
        showCancelButton: true,
        confirmButtonColor: '#2ecc71',
        confirmButtonText: 'Complete Visit',
        cancelButtonText: 'Cancel'
    });

    // 2. If user clicked "Complete Visit"
    if (isConfirmed) {
        const finalNote = note || 'Verified via QR Scan'; // Default text if empty
        document.getElementById('scan-result').innerHTML = `Saving ID: ${appointmentId}...`;

        try {
            const response = await fetch(`${API_URL}/appointments/${appointmentId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ status: 'completed', admin_note: finalNote })
            });
            const data = await response.json();

            if (response.ok) {
                Swal.fire({
                    icon: 'success', 
                    title: 'Visit Completed', 
                    text: `Student cleared with remarks.`,
                    timer: 2000, 
                    showConfirmButton: false
                }).then(() => {
                    document.getElementById('scan-result').innerHTML = "Ready for next student.";
                    startScanner(); // Restart camera for next person
                });
            } else if (data.detail === "already_scanned") {
                Swal.fire({ 
                    icon: 'warning', 
                    title: 'ALREADY USED', 
                    text: 'This ticket was already completed.',
                    confirmButtonColor: '#f39c12' 
                }).then(() => startScanner());
            } else {
                Swal.fire('Error', data.detail || 'Server Error', 'error');
                setTimeout(startScanner, 2000); 
            }
        } catch (e) {
            console.error(e);
            Swal.fire('Error', 'Connection Error', 'error');
            setTimeout(startScanner, 2000);
        }
    } else {
        // 3. If user clicked "Cancel"
        document.getElementById('scan-result').innerHTML = "Scan cancelled. Ready.";
        startScanner(); // Restart camera immediately
    }
}

function onScanFailure(error) {}

async function loadAppointments() {
    try {
        const response = await fetch(`${API_URL}/appointments`, { headers: { 'Authorization': `Bearer ${token}` } });
        if (!response.ok) throw new Error("Failed to fetch");
        allAppointments = await response.json();
        applyFiltersAndSort(); 
    } catch (error) {
        console.error(error);
        document.getElementById('appointments-list').innerHTML = `<tr><td colspan="7" style="text-align:center; color:red;">Error loading data.</td></tr>`;
    }
}

function applyFiltersAndSort() {
    const statusFilter = document.getElementById('status-filter').value;
    const searchTerm = document.getElementById('search-input').value.toLowerCase();
    const sortChoice = document.getElementById('sort-order').value;

    let filtered = allAppointments.filter(apt => {
        const matchesStatus = statusFilter === 'all' || apt.status === statusFilter;
        const matchesSearch = apt.student_name.toLowerCase().includes(searchTerm);
        
        let matchesType = true;
        const service = (apt.service_type || '').toLowerCase();
        const urgency = (apt.urgency || '').toLowerCase();

        if (sortChoice === 'clearance-urgent') matchesType = service.includes('clearance') && urgency.includes('urgent');
        else if (sortChoice === 'consultation-urgent') matchesType = service.includes('consultation') && urgency.includes('urgent');
        else if (sortChoice === 'clearance-normal') matchesType = service.includes('clearance') && urgency.includes('normal');
        else if (sortChoice === 'consultation-normal') matchesType = service.includes('consultation') && urgency.includes('normal');

        return matchesStatus && matchesSearch && matchesType;
    });

    const statusPriority = { 'pending': 1, 'approved': 2, 'completed': 3, 'rejected': 3, 'canceled': 3, 'noshow': 3 };

    filtered.sort((a, b) => {
        const priorityA = statusPriority[a.status] || 99;
        const priorityB = statusPriority[b.status] || 99;
        if (priorityA !== priorityB) return priorityA - priorityB;

        const isUrgentA = (a.urgency || '').toLowerCase() === 'urgent';
        const isUrgentB = (b.urgency || '').toLowerCase() === 'urgent';
        
        if (isUrgentA && !isUrgentB) return -1; // A moves up
        if (!isUrgentA && isUrgentB) return 1;  // B moves up


        return new Date(b.appointment_date + 'T' + b.appointment_time) - new Date(a.appointment_date + 'T' + a.appointment_time);
    });

    displayAppointments(filtered);
}

function displayAppointments(data) {
    const tbody = document.getElementById('appointments-list');
    tbody.innerHTML = '';

    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px;">No appointments found.</td></tr>`;
        return;
    }

    data.forEach(apt => {
        const urgency = apt.urgency || 'Low';
        const urgencyClass = (urgency.toLowerCase() === 'urgent') ? 'color: var(--danger); font-weight:bold;' : 'color: var(--success);';
        const statusLabel = apt.status.toUpperCase();
        const niceTime = formatTime(apt.appointment_time);
        
        let statusColor = '';
        if(apt.status === 'noshow') statusColor = 'background:#607d8b; color:white;';
        
        const isAI = apt.booking_mode === 'ai_chatbot';
        const modeBadge = isAI ? '<i class="fas fa-robot" style="color:#9b59b6;"></i> AI' : '<i class="fas fa-user" style="color:#7f8c8d;"></i> Web';

        const row = `
            <tr>
                <td>${formatDate(apt.appointment_date)}<br><small>${niceTime}</small></td>
                <td><span style="font-weight:bold">${apt.student_name}</span><br><small style="color:#666">${apt.student_email || ''}</small></td>
                <td>${apt.service_type || 'General'}</td>
                <td><span style="${urgencyClass}">${urgency}</span></td>
                <td><span class="status-pill ${apt.status}" style="${statusColor}">${statusLabel}</span></td>
                <td style="text-align:center;">${modeBadge}</td>
                <td>
                    <div class="action-buttons">
                        <button class="btn-primary" style="padding: 5px 10px; font-size: 0.8rem;" onclick="openAppointmentModal(${apt.id})">View</button>
                        <button class="btn-delete" onclick="deleteAppointment(${apt.id})"><i class="fas fa-trash"></i></button>
                    </div>
                </td>
            </tr>
        `;
        tbody.insertAdjacentHTML('beforeend', row);
    });
}

async function deleteAppointment(id) {
    Swal.fire({
        title: 'Delete Record?', text: "Cannot be undone.", icon: 'warning',
        showCancelButton: true, confirmButtonColor: '#d33', confirmButtonText: 'Yes, delete it'
    }).then(async (result) => {
        if (result.isConfirmed) {
            try {
                const response = await fetch(`${API_URL}/appointments/${id}`, {
                    method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` }
                });
                if(response.ok) { Swal.fire('Deleted!', 'Removed.', 'success'); loadAppointments(); loadQueue(); } 
                else { Swal.fire('Error', 'Failed to delete.', 'error'); }
            } catch(e) { console.error(e); }
        }
    });
}

function formatDate(d) { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }); }

function formatTime(timeStr) {
    if (!timeStr) return "";
    const parts = timeStr.split(':');
    let hour = parseInt(parts[0]);
    const minutes = parts[1];
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12; hour = hour ? hour : 12; 
    return `${hour}:${minutes} ${ampm}`;
}

function openAppointmentModal(id) {
    const apt = allAppointments.find(a => a.id === id);
    if(!apt) return;
    currentAppointmentId = id;
    const modeLabel = apt.booking_mode === 'ai_chatbot' ? 'AI Assistant' : 'Standard Web Form';
    
    document.getElementById('appointment-details').innerHTML = `
        <p><strong>Student:</strong> ${apt.student_name}</p>
        <p><strong>Service:</strong> ${apt.service_type}</p>
        <p><strong>Urgency:</strong> ${apt.urgency}</p>
        <p><strong>Reason:</strong> ${apt.reason}</p>
        <p><strong>Booking Mode:</strong> ${modeLabel}</p>
        <p><strong>Status:</strong> <span class="status-pill ${apt.status}">${apt.status.toUpperCase()}</span></p>
        <hr style="margin: 10px 0; border: 0; border-top: 1px solid #eee;">
        ${apt.admin_note ? `<div class="admin-note-box"><strong>Current Note:</strong> ${apt.admin_note}</div>` : ''}
    `;
    
    const actionButtons = document.querySelector('.modal-actions');
    document.getElementById('reject-form').style.display = 'none';
    actionButtons.style.display = (apt.status === 'pending') ? 'flex' : 'none';
    document.getElementById('appointment-modal').style.display = 'flex';
}

function closeModal(id) { document.getElementById(id).style.display = 'none'; }
function showRejectForm() { document.getElementById('reject-form').style.display = 'block'; }

async function updateAppointmentStatus(status) {
    const note = document.getElementById('admin-note').value;
    await fetch(`${API_URL}/appointments/${currentAppointmentId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: status, admin_note: note })
    });
    closeModal('appointment-modal');
    Swal.fire({ icon: 'success', title: 'Updated!', timer: 1500, showConfirmButton: false });
    loadAppointments(); loadQueue();
}

// [UPDATED] Load Users with Self-Delete Protection & Search
async function loadUsers() {
    try {
        const response = await fetch(`${API_URL}/users`, { headers: { 'Authorization': `Bearer ${token}` } });
        allUsers = await response.json(); // Store in global variable
        renderUsers(); // Call filter & display function
    } catch (e) { console.error(e); }
}

// [NEW] Separate function to filter and render without re-fetching
function renderUsers() {
    const filter = document.getElementById('user-role-filter') ? document.getElementById('user-role-filter').value : 'all';
    const searchTerm = document.getElementById('user-search') ? document.getElementById('user-search').value.toLowerCase() : '';
    
    // Apply Filters
    let users = allUsers.filter(u => {
        const matchesRole = (filter === 'all') || 
                            (filter === 'student' && u.role === 'student') || 
                            (filter === 'admin' && (u.role === 'admin' || u.role === 'super_admin'));
        
        const matchesSearch = u.full_name.toLowerCase().includes(searchTerm) || 
                              u.email.toLowerCase().includes(searchTerm);
        
        return matchesRole && matchesSearch;
    });

    const tbody = document.getElementById('users-list');
    tbody.innerHTML = '';
    
    if (users.length === 0) { tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;">No users found.</td></tr>`; return; }
    
    users.forEach(u => {
        let roleLabel = u.role === 'student' ? 'Student' : (u.role === 'super_admin' ? 'Super Admin' : 'Admin');
        let roleColor = u.role === 'student' ? 'green' : 'blue';
        
        // CHECK: If this row is YOU, don't show the delete button
        let deleteBtn = `<button onclick="deleteUser(${u.id})" class="btn-delete"><i class="fas fa-trash"></i></button>`;
        
        if (u.id === currentUserId) {
            deleteBtn = `<span style="color:#aaa; font-size:0.8rem;">(You)</span>`;
        }

        tbody.insertAdjacentHTML('beforeend', `
            <tr>
                <td>${u.full_name}</td>
                <td>${u.email}</td>
                <td><span style="color:${roleColor};font-weight:bold;">${roleLabel}</span></td>
                <td>${new Date(u.created_at).toLocaleDateString()}</td>
                <td>${deleteBtn}</td>
            </tr>
        `);
    });
}

async function deleteUser(id) {
    Swal.fire({ title: 'Delete User?', showCancelButton: true, confirmButtonColor: '#d33', confirmButtonText: 'Yes' }).then(async (res) => {
        if (res.isConfirmed) {
            const response = await fetch(`${API_URL}/users/${id}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
            if (response.ok) { Swal.fire('Deleted!', 'Removed.', 'success'); loadUsers(); } 
            else Swal.fire('Error', 'Failed.', 'error');
        }
    });
}

function showAddUserModal() { document.getElementById('add-user-modal').style.display = 'flex'; }
async function handleNewUser(e) {
    e.preventDefault();
    const body = { full_name: document.getElementById('new-full-name').value, email: document.getElementById('new-email').value, password: document.getElementById('new-password').value, role: document.getElementById('new-role').value };
    const res = await fetch(`${API_URL}/admin/create-user`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }, body: JSON.stringify(body) });
    if(res.ok) { Swal.fire('Success', 'User created.', 'success'); closeModal('add-user-modal'); loadUsers(); } 
    else Swal.fire('Error', 'Failed.', 'error');
}

// Auto-refresh both Queue and Table every 2 seconds
setInterval(() => {
    loadQueue();
    loadAppointments(); // This function was already "silent" in your code, so it's fine
}, 2000);