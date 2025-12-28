const API_URL = 'http://localhost:8000/api';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadNurseAppointments();
    setInterval(loadNurseAppointments, 5000); // Auto-refresh
});

async function loadNurseAppointments() {
    try {
        const response = await fetch(`${API_URL}/appointments`);
        const allAppointments = await response.json();
        
        const tbody = document.getElementById('nurse-list');
        tbody.innerHTML = '';

        // Filter: Only Pending
        const pending = allAppointments.filter(a => a.status === 'pending');
        
        // Sort: Urgent first, then by ID
        pending.sort((a, b) => {
            if (a.urgency === 'Urgent' && b.urgency !== 'Urgent') return -1;
            if (a.urgency !== 'Urgent' && b.urgency === 'Urgent') return 1;
            return a.id - b.id;
        });

        if (pending.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:20px; color:#777;">No pending requests.</td></tr>';
            return;
        }

        pending.forEach(apt => {
            const isUrgent = apt.urgency === 'Urgent';
            const urgencyBadge = isUrgent ? '<span style="color:red; font-weight:bold;">URGENT</span>' : 'Normal';
            
            const row = `
                <tr style="${isUrgent ? 'background:#fff5f5' : ''}">
                    <td>${apt.appointment_date}<br><small>${formatTime(apt.appointment_time)}</small></td>
                    <td><strong>${apt.client_name}</strong><br><small>${apt.client_email}</small></td>
                    <td>${apt.service_type}</td>
                    
                    <td style="max-width: 250px; font-size: 0.9rem; color: #555;">${apt.reason}</td>
                    
                    <td>${urgencyBadge}</td>
                    <td><span class="status-pill pending">PENDING</span></td>
                    <td>
                        <div style="display:flex; gap:5px;">
                            <button onclick="approve(${apt.id})" class="btn-primary" style="padding:5px 10px; font-size:0.8rem; background:#2ecc71;">Approve</button>
                            <button onclick="reject(${apt.id})" class="btn-delete" style="padding:5px 10px; font-size:0.8rem;">Reject</button>
                        </div>
                    </td>
                </tr>
            `;
            tbody.insertAdjacentHTML('beforeend', row);
        });

    } catch (error) {
        console.error("Error:", error);
    }
}

async function approve(id) {
    Swal.fire({
        title: 'Approve & Send Ticket?',
        text: "The patient will receive an email with their ticket.",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#2ecc71',
        confirmButtonText: 'Yes, Approve'
    }).then(async (res) => {
        if (res.isConfirmed) {
            // [ADDED] Loading alert for Approval
            Swal.fire({
                title: 'Sending Ticket...',
                text: 'Please wait while we email the patient.',
                allowOutsideClick: false,
                didOpen: () => Swal.showLoading()
            });

            await updateStatus(id, 'approved');
            loadNurseAppointments();
        }
    });
}

async function reject(id) {
    const { value: reason } = await Swal.fire({
        title: 'Reject Request',
        input: 'text',
        inputPlaceholder: 'Reason for rejection...',
        inputValidator: (value) => {
            if (!value) {
                return 'You must write a reason for rejection!';
            }
        },
        showCancelButton: true,
        confirmButtonColor: '#e74c3c',
        confirmButtonText: 'Reject & Email'
    });

    if (reason) {
        // [ADDED] Loading alert for Rejection
        Swal.fire({
            title: 'Sending Rejection Email...',
            text: 'Notifying the patient.',
            allowOutsideClick: false,
            didOpen: () => Swal.showLoading()
        });

        await updateStatus(id, 'rejected', reason);
        loadNurseAppointments();
    }
}

async function updateStatus(id, status, note = '') {
    try {
        const response = await fetch(`${API_URL}/appointments/${id}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: status, admin_note: note })
        });

        if (response.ok) {
            // Close the loading alert and show success
            Swal.fire({
                icon: 'success',
                title: status === 'approved' ? 'Ticket Sent!' : 'Rejection Sent',
                timer: 2000,
                showConfirmButton: false
            });
        } else {
            Swal.fire('Error', 'Something went wrong.', 'error');
        }

    } catch (e) { 
        console.error(e);
        Swal.fire('Error', 'Network Error', 'error');
    }
}

function formatTime(timeStr) {
    if (!timeStr) return "";
    const parts = timeStr.split(':');
    let hour = parseInt(parts[0]);
    const minutes = parts[1];
    const ampm = hour >= 12 ? 'PM' : 'AM';
    hour = hour % 12; hour = hour ? hour : 12; 
    return `${hour}:${minutes} ${ampm}`;
}