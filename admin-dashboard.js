const API_URL = 'http://localhost:8000/api';
let allAppointments = [];
let currentAppointmentId = null;
let html5QrcodeScanner = null; // scanner variable

// authentication check
const token = localStorage.getItem('token');
const role = localStorage.getItem('role');
const fullName = localStorage.getItem('full_name') || 'Admin';

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
    
    // scanner logic
    if (tabName === 'scanner') {
        startScanner();
    } else {
        stopScanner();
    }

    if (tabName === 'appointments') loadAppointments();
    if (tabName === 'users') loadUsers();
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

// --- scanner logic ---

function startScanner() {
    if (html5QrcodeScanner) return; 

    // start camera
    html5QrcodeScanner = new Html5QrcodeScanner(
        "reader", { fps: 10, qrbox: 250 }
    );
    html5QrcodeScanner.render(onScanSuccess, onScanFailure);
}

function stopScanner() {
    if (html5QrcodeScanner) {
        html5QrcodeScanner.clear().catch(error => {
            console.error("Failed to clear scanner", error);
        });
        html5QrcodeScanner = null;
    }
}

async function onScanSuccess(decodedText, decodedResult) {
    stopScanner(); // stop scanning once found
    
    const appointmentId = decodedText;
    document.getElementById('scan-result').innerHTML = `Processing ID: ${appointmentId}...`;

    try {
        // update status to completed
        const response = await fetch(`${API_URL}/appointments/${appointmentId}`, {
            method: 'PUT',
            headers: { 
                'Content-Type': 'application/json', 
                'Authorization': `Bearer ${token}` 
            },
            body: JSON.stringify({ 
                status: 'completed', 
                admin_note: 'Verified via QR Scan' 
            })
        });

        const data = await response.json();

        // check if success
        if (response.ok) {
            Swal.fire({
                icon: 'success',
                title: 'Verified!',
                text: `Student is cleared for entry. (ID: ${appointmentId})`,
                timer: 2500,
                showConfirmButton: false
            }).then(() => {
                document.getElementById('scan-result').innerHTML = "Ready for next student.";
                startScanner(); // restart
            });
        } 
        // check for specific "already scanned" error
        else if (data.detail === "ALREADY_SCANNED") {
            Swal.fire({
                icon: 'warning',
                title: 'ALREADY USED',
                text: 'This ticket has already been scanned!',
                confirmButtonColor: '#f39c12'
            }).then(() => {
                startScanner(); // restart so admin can scan the next one
            });
        }
        else {
            // generic error
            Swal.fire('Error', data.detail || 'Server Error', 'error');
            setTimeout(startScanner, 2000); 
        }

    } catch (e) {
        console.error(e);
        Swal.fire('Error', 'Connection Error', 'error');
        setTimeout(startScanner, 2000);
    }
}

function onScanFailure(error) {
    // console.warn(`code scan error = ${error}`);
}

// --- appointment logic ---

async function loadAppointments() {
    try {
        const response = await fetch(`${API_URL}/appointments`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) throw new Error("Failed to fetch");
        allAppointments = await response.json();
        applyFiltersAndSort(); 
    } catch (error) {
        console.error(error);
        document.getElementById('appointments-list').innerHTML = `<tr><td colspan="6" style="text-align:center; color:red;">Error loading data.</td></tr>`;
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

        if (sortChoice === 'clearance-urgent') {
            matchesType = service.includes('clearance') && (urgency === 'urgent' || urgency === 'high');
        } else if (sortChoice === 'consultation-urgent') {
            matchesType = service.includes('consultation') && (urgency === 'urgent' || urgency === 'high');
        } else if (sortChoice === 'clearance-normal') {
            matchesType = service.includes('clearance') && (urgency === 'normal' || urgency === 'low');
        } else if (sortChoice === 'consultation-normal') {
            matchesType = service.includes('consultation') && (urgency === 'normal' || urgency === 'low');
        }

        return matchesStatus && matchesSearch && matchesType;
    });

    // --- smart sort logic ---
    const statusPriority = {
        'pending': 1,
        'approved': 2,
        'completed': 3,
        'rejected': 3,
        'canceled': 3
    };

    filtered.sort((a, b) => {
        const priorityA = statusPriority[a.status] || 99;
        const priorityB = statusPriority[b.status] || 99;

        if (priorityA !== priorityB) {
            return priorityA - priorityB; 
        }
        return new Date(b.appointment_date) - new Date(a.appointment_date);
    });

    displayAppointments(filtered);
}

function displayAppointments(data) {
    const tbody = document.getElementById('appointments-list');
    tbody.innerHTML = '';

    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 20px;">No appointments found matching these criteria.</td></tr>`;
        return;
    }

    data.forEach(apt => {
        const urgency = apt.urgency || 'Low';
        const urgencyClass = (urgency.toLowerCase() === 'urgent' || urgency.toLowerCase() === 'high') ? 'color: var(--danger); font-weight:bold;' : 'color: var(--success);';
        
        const statusLabel = apt.status.charAt(0).toUpperCase() + apt.status.slice(1);
        const showDelete = true; 
        const niceTime = formatTime(apt.appointment_time);

        const row = `
            <tr>
                <td>${formatDate(apt.appointment_date)}<br><small>${niceTime}</small></td>
                <td>
                    <span style="font-weight:bold">${apt.student_name}</span><br>
                    <small style="color:#666">${apt.student_email || ''}</small>
                </td>
                <td>${apt.service_type || 'General'}</td>
                <td><span style="${urgencyClass}">${urgency}</span></td>
                <td><span class="status-pill ${apt.status}">${statusLabel}</span></td>
                
                <td>
                    <div class="action-buttons">
                        <button class="btn-primary" style="padding: 5px 10px; font-size: 0.8rem;" onclick="openAppointmentModal(${apt.id})">View</button>
                        ${showDelete ? `<button class="btn-delete" onclick="deleteAppointment(${apt.id})"><i class="fas fa-trash"></i></button>` : ''}
                    </div>
                </td>
            </tr>
        `;
        tbody.insertAdjacentHTML('beforeend', row);
    });
}

async function deleteAppointment(id) {
    Swal.fire({
        title: 'Delete Record?',
        text: "This action cannot be undone.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, delete it'
    }).then(async (result) => {
        if (result.isConfirmed) {
            try {
                const response = await fetch(`${API_URL}/appointments/${id}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if(response.ok) {
                    Swal.fire('Deleted!', 'Record has been removed.', 'success');
                    loadAppointments();
                } else {
                    Swal.fire('Error', 'Failed to delete record.', 'error');
                }
            } catch(e) { console.error(e); }
        }
    });
}

function formatDate(d) {
    return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTime(timeStr) {
    if (!timeStr) return "";
    const [hours, minutes] = timeStr.split(':');
    let hour = parseInt(hours);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12;
    hour = hour ? hour : 12; 
    return `${hour}:${minutes} ${ampm}`;
}

// [UPDATED] logic to hide actions if not pending
function openAppointmentModal(id) {
    const apt = allAppointments.find(a => a.id === id);
    if(!apt) return;
    currentAppointmentId = id;
    const details = document.getElementById('appointment-details');
    details.innerHTML = `
        <p><strong>Student:</strong> ${apt.student_name}</p>
        <p><strong>Service:</strong> ${apt.service_type}</p>
        <p><strong>Urgency:</strong> ${apt.urgency}</p>
        <p><strong>Reason:</strong> ${apt.reason}</p>
        <p><strong>Status:</strong> ${apt.status.toUpperCase()}</p>
        <hr style="margin: 10px 0; border: 0; border-top: 1px solid #eee;">
        ${apt.admin_note ? `<div class="admin-note-box"><strong>Current Note:</strong> ${apt.admin_note}</div>` : ''}
    `;
    
    // --- fix is here ---
    const actionButtons = document.querySelector('.modal-actions');
    const rejectForm = document.getElementById('reject-form');
    
    // reset visibility
    rejectForm.style.display = 'none';

    // if status is NOT pending, hide the approve/reject buttons
    if (apt.status !== 'pending') {
        actionButtons.style.display = 'none';
    } else {
        actionButtons.style.display = 'flex'; // show them if pending
    }

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
    
    Swal.fire({
        icon: 'success',
        title: 'Updated!',
        text: `Appointment marked as ${status}.`,
        timer: 1500,
        showConfirmButton: false
    });
    
    loadAppointments();
}

// --- user management logic ---

async function loadUsers() {
    try {
        const response = await fetch(`${API_URL}/users`, { headers: { 'Authorization': `Bearer ${token}` } });
        let users = await response.json();
        
        const filterElement = document.getElementById('user-role-filter');
        const filter = filterElement ? filterElement.value : 'all';

        if (filter === 'student') {
            users = users.filter(u => u.role === 'student');
        } else if (filter === 'admin') {
            users = users.filter(u => u.role === 'admin' || u.role === 'super_admin');
        }

        const tbody = document.getElementById('users-list');
        tbody.innerHTML = '';
        
        if (users.length === 0) {
             tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 20px;">No users found.</td></tr>`;
             return;
        }

        users.forEach(u => {
            let roleColor = '#333';
            let roleLabel = 'Student';

            if (u.role === 'student') {
                roleColor = 'green';
                roleLabel = 'Student';
            } else if (u.role === 'super_admin') {
                roleColor = 'purple';
                roleLabel = 'Super Admin';
            } else {
                roleColor = 'blue';
                roleLabel = 'Admin';
            }

            tbody.insertAdjacentHTML('beforeend', `
                <tr>
                    <td>${u.full_name}</td>
                    <td>${u.email}</td>
                    <td><span style="color: ${roleColor}; font-weight:bold;">${roleLabel}</span></td>
                    <td>${new Date(u.created_at).toLocaleDateString()}</td>
                    <td><button onclick="deleteUser(${u.id})" class="btn-delete"><i class="fas fa-trash"></i></button></td>
                </tr>
            `);
        });
    } catch (e) { console.error(e); }
}

async function deleteUser(id) {
    Swal.fire({
        title: 'Delete User?',
        text: "This will also delete their appointments.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#3085d6',
        confirmButtonText: 'Yes, delete user'
    }).then(async (result) => {
        if (result.isConfirmed) {
            try {
                const response = await fetch(`${API_URL}/users/${id}`, { 
                    method: 'DELETE', 
                    headers: { 'Authorization': `Bearer ${token}` } 
                });
                
                if (response.ok) {
                    Swal.fire('Deleted!', 'User has been removed.', 'success');
                    loadUsers();
                } else {
                    const data = await response.json();
                    Swal.fire('Error', data.detail || "Failed to delete user.", 'error');
                }
            } catch(e) {
                Swal.fire('Error', "Server connection error.", 'error');
            }
        }
    });
}

function showAddUserModal() { document.getElementById('add-user-modal').style.display = 'flex'; }

async function handleNewUser(e) {
    e.preventDefault();
    const body = {
        full_name: document.getElementById('new-full-name').value,
        email: document.getElementById('new-email').value,
        password: document.getElementById('new-password').value,
        role: document.getElementById('new-role').value
    };
    const res = await fetch(`${API_URL}/admin/create-user`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(body)
    });
    if(res.ok) { 
        Swal.fire('Success', 'User created successfully.', 'success');
        closeModal('add-user-modal'); 
        loadUsers(); 
    } else { 
        Swal.fire('Error', 'Failed to create user. Email might exist.', 'error'); 
    }
}