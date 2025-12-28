const API_URL = 'http://localhost:8000/api';
let allAppointments = [];
let html5QrcodeScanner = null;
let pendingDiagnosisData = null; 

document.addEventListener('DOMContentLoaded', () => {
    loadDoctorQueue();
    setInterval(loadDoctorQueue, 5000);
});

async function loadDoctorQueue() {
    try {
        const response = await fetch(`${API_URL}/appointments`);
        allAppointments = await response.json();
        
        const container = document.getElementById('doctor-queue');
        
        // filter: approved only (people waiting)
        const queue = allAppointments.filter(a => a.status === 'approved');

        // sorting: strict chronological order
        queue.sort((a, b) => {
            const timeA = parseDateTime(a.appointment_date, a.appointment_time);
            const timeB = parseDateTime(b.appointment_date, b.appointment_time);
            return timeA - timeB; 
        });

        container.innerHTML = '';

        if (queue.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 50px; color: #aaa;">
                    <i class="fas fa-mug-hot" style="font-size: 3rem; margin-bottom: 15px;"></i>
                    <h3>No patients in queue.</h3>
                    <p>Enjoy your break!</p>
                </div>
            `;
            return;
        }

        // hero card logic
        const nextPatient = queue[0]; 
        const waitingList = queue.slice(1); 

        const niceTime = formatTime(nextPatient.appointment_time);
        const niceDate = new Date(nextPatient.appointment_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

        let html = `
            <div class="hero-card">
                <div class="hero-time">${niceTime}</div>
                
                <div class="hero-name">
                    <span style="opacity:0.6; font-size:0.5em; display:block; margin-bottom:5px;">#${nextPatient.id}</span>
                    ${nextPatient.client_name}
                </div>
                
                <div class="hero-details">
                    <i class="fas fa-calendar-day"></i> ${niceDate} &nbsp;|&nbsp; 
                    <i class="fas fa-stethoscope"></i> ${nextPatient.service_type} &nbsp;|&nbsp;
                    <span style="color:${nextPatient.urgency === 'Urgent' ? 'red' : 'green'}; font-weight:bold;">${nextPatient.urgency}</span>
                </div>
                
                <div style="background: #e3f2fd; color: #1565c0; padding: 10px; border-radius: 8px; margin-bottom: 20px; font-style: italic; display:inline-block;">
                    "${nextPatient.reason}"
                </div>
                
                <div class="hero-actions">
                    <button onclick="markNoShow(${nextPatient.id})" class="btn-noshow">
                        <i class="fas fa-user-slash"></i> No Show
                    </button>
                    <button onclick="openDiagnosisForm(${nextPatient.id})" class="btn-complete-hero">
                        <i class="fas fa-stethoscope"></i> Start Consultation
                    </button>
                </div>
            </div>
        `;

        if (waitingList.length > 0) {
            html += `<div class="queue-list-header">Up Next (${waitingList.length})</div>`;
            waitingList.forEach(apt => {
                const wTime = formatTime(apt.appointment_time);
                const wDate = new Date(apt.appointment_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                
                html += `
                    <div class="queue-item">
                        <div>
                            <h4>${apt.client_name}</h4>
                            <p>${apt.service_type} • <span style="color:${apt.urgency==='Urgent'?'red':'#666'}">${apt.urgency}</span></p>
                            <p style="font-size: 0.85rem; color: #666; margin-top: 2px;"><em>"${apt.reason}"</em></p>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-size:0.8rem; color:#888;">${wDate}</div>
                            <div class="queue-time">${wTime}</div>
                        </div>
                    </div>
                `;
            });
        }

        container.innerHTML = html;

    } catch (error) {
        console.error("Error:", error);
    }
}

// helper: parse date and time safely
function parseDateTime(dateStr, timeStr) {
    if (!timeStr) return new Date(dateStr);

    let hours = 0;
    let minutes = 0;

    if (timeStr.toLowerCase().includes('m')) { 
        const parts = timeStr.match(/(\d+):(\d+)\s*(am|pm)/i);
        if (parts) {
            hours = parseInt(parts[1]);
            minutes = parseInt(parts[2]);
            const amp = parts[3].toLowerCase();
            
            if (amp === 'pm' && hours < 12) hours += 12;
            if (amp === 'am' && hours === 12) hours = 0;
        }
    } else {
        const parts = timeStr.split(':');
        if (parts.length >= 2) {
            hours = parseInt(parts[0]);
            minutes = parseInt(parts[1]);
        }
    }

    const d = new Date(dateStr);
    d.setHours(hours, minutes, 0, 0);
    return d;
}

// --- actions ---

function markNoShow(id) {
    Swal.fire({
        title: 'Mark as No Show?',
        text: "This will remove the client from the queue and notify them via email.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#607d8b',
        confirmButtonText: 'Yes, remove'
    }).then(async (result) => {
        if (result.isConfirmed) {
            // show Loading Alert
            Swal.fire({
                title: 'Processing...',
                text: 'Sending notification email.',
                allowOutsideClick: false,
                didOpen: () => Swal.showLoading()
            });

            try {
                const res = await fetch(`${API_URL}/appointments/${id}/status`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status: 'noshow', admin_note: 'Doctor marked as No Show' })
                });
                
                if (res.ok) {
                    const Toast = Swal.mixin({ toast: true, position: 'top-end', showConfirmButton: false, timer: 3000 });
                    Toast.fire({ icon: 'info', title: 'Marked as No Show' });
                    loadDoctorQueue();
                } else {
                    Swal.fire('Error', 'Failed to update status.', 'error');
                }
            } catch (e) {
                console.error(e);
                Swal.fire('Error', 'Network error.', 'error');
            }
        }
    });
}

// --- form logic ---

function openDiagnosisForm(id) {
    const apt = allAppointments.find(a => a.id === id);
    if (!apt) return;

    document.getElementById('diag-id').value = id;
    document.getElementById('diag-patient-info').innerHTML = `
        <strong>Patient:</strong> ${apt.client_name}<br>
        <strong>Service:</strong> ${apt.service_type}<br>
        <strong>Complaint:</strong> ${apt.reason}
    `;

    // clear form
    document.getElementById('vital-temp').value = '';
    document.getElementById('vital-bp').value = '';
    document.getElementById('vital-pulse').value = '';
    document.getElementById('vital-weight').value = '';
    document.getElementById('diag-findings').value = '';
    document.querySelector('input[name="recommendation"][value="Back to Class"]').checked = true;

    // reset medicine list to show 1 empty row
    const medContainer = document.getElementById('medicine-list-container');
    medContainer.innerHTML = ''; 
    addMedicineRow(); // add the first empty row

    document.getElementById('diagnosis-modal').style.display = 'flex';
}

function closeModal() {
    document.getElementById('diagnosis-modal').style.display = 'none';
}

// function to add a medicine row dynamically
function addMedicineRow() {
    const container = document.getElementById('medicine-list-container');
    
    // create a div to hold the inputs
    const row = document.createElement('div');
    row.className = 'medicine-row';
    row.style.display = 'flex';
    row.style.gap = '10px';
    row.style.marginBottom = '10px';

    // html for the row
    row.innerHTML = `
        <div style="flex: 1;">
            <input type="text" class="med-name" placeholder="Medicine Name (e.g. Paracetamol)" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
        </div>
        <div style="flex: 1;">
            <input type="text" class="med-instruct" placeholder="Instruction (e.g. 1 tab after meal)" style="width:100%; padding:8px; border:1px solid #ccc; border-radius:4px;">
        </div>
        <button onclick="this.parentElement.remove()" style="background:#ff5252; color:white; border:none; border-radius:4px; cursor:pointer; padding:0 10px;">
            <i class="fas fa-times"></i>
        </button>
    `;

    container.appendChild(row);
}

// --- gather data & start scan ---
function initiateCompletion() {
    const id = document.getElementById('diag-id').value;
    
    // gather vital signs
    const findings = document.getElementById('diag-findings').value || 'No specific findings recorded.';
    const temp = document.getElementById('vital-temp').value || 'N/A';
    const bp = document.getElementById('vital-bp').value || 'N/A';
    const pulse = document.getElementById('vital-pulse').value || 'N/A';
    const weight = document.getElementById('vital-weight').value || 'N/A';
    const recommend = document.querySelector('input[name="recommendation"]:checked').value;

    // gather all medicines from the list
    let medicineList = [];
    const rows = document.querySelectorAll('.medicine-row');
    
    rows.forEach(row => {
        const medName = row.querySelector('.med-name').value.trim();
        const medInstruct = row.querySelector('.med-instruct').value.trim();
        
        // only add if the doctor typed a medicine name
        if (medName) {
            let item = medName;
            if (medInstruct) item += ` (${medInstruct})`;
            medicineList.push(item);
        }
    });

    // join them with commas (e.g. "Paracetamol (1 tab), Vitamin C (once a day)")
    const finalMedsString = medicineList.length > 0 ? medicineList.join(', ') : 'None';

    const finalDiagnosisText = `
[VITALS] Temp: ${temp}°C | BP: ${bp} | Pulse: ${pulse} | Wt: ${weight}kg
[DIAGNOSIS] ${findings}
[TREATMENT] ${finalMedsString}
[RECOMMENDATION] ${recommend}
    `.trim();

    pendingDiagnosisData = {
        id: id,
        text: finalDiagnosisText
    };

    startScanner();
}

// --- scanner logic ---
function startScanner() {
    document.getElementById('scanner-modal').style.display = 'flex';
    if (!html5QrcodeScanner) {
        html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: 250 });
        html5QrcodeScanner.render(onScanSuccess);
    }
}

function stopScanner() {
    document.getElementById('scanner-modal').style.display = 'none';
    if (html5QrcodeScanner) {
        html5QrcodeScanner.clear().catch(err => console.error(err));
        html5QrcodeScanner = null;
    }
}

async function onScanSuccess(decodedText) {
    stopScanner(); 
    
    const scannedId = parseInt(decodedText.replace(/\D/g, ''));
    const targetId = parseInt(pendingDiagnosisData.id);

    if (scannedId === targetId) {
        await saveToDatabase();
    } else {
        Swal.fire({
            icon: 'error',
            title: 'Wrong Ticket!',
            text: `Scanned ID #${scannedId} does not match Current Patient #${targetId}.`,
            confirmButtonText: 'Try Again'
        });
    }
}

async function saveToDatabase() {
    try {
        const { id, text } = pendingDiagnosisData;

        const res = await fetch(`${API_URL}/appointments/${id}/diagnosis`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ diagnosis: text })
        });

        if (res.ok) {
            closeModal();
            Swal.fire({
                icon: 'success',
                title: 'Consultation Complete',
                text: 'Record saved successfully.',
                timer: 2000,
                showConfirmButton: false
            });
            loadDoctorQueue();
        } else {
            Swal.fire('Error', 'Failed to save record.', 'error');
        }
    } catch (e) {
        console.error(e);
        Swal.fire('Error', 'Network error.', 'error');
    }
}

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