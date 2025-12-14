const API_URL = "http://localhost:8000/api";

document.getElementById("register-form").addEventListener("submit", async function(event) {
    event.preventDefault();

    const fullName = document.getElementById("full-name").value;
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const confirmPassword = document.getElementById("confirm-password").value;

    // 1. Password Mismatch Alert
    if (password !== confirmPassword) {
        Swal.fire({
            icon: 'error',
            title: 'Password Mismatch',
            text: 'Your passwords do not match. Please try again.',
            confirmButtonColor: '#e74c3c'
        });
        return;
    }

    try {
        const response = await fetch(`${API_URL}/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ full_name: fullName, email: email, password: password })
        });

        const data = await response.json();

        if (response.ok) {
            // 2. Success Alert
            Swal.fire({
                icon: 'success',
                title: 'Registration Successful!',
                text: 'You can now login to your account.',
                confirmButtonColor: '#1E88E5'
            }).then(() => {
                window.location.href = "index.html";
            });
        } else {
            // 3. API Error Alert (e.g. Email exists)
            Swal.fire({
                icon: 'warning',
                title: 'Registration Failed',
                text: data.detail || 'Something went wrong.',
                confirmButtonColor: '#e74c3c'
            });
        }
    } catch (error) {
        Swal.fire({
            icon: 'error',
            title: 'Connection Error',
            text: 'Could not connect to server. Is it running?',
            confirmButtonColor: '#e74c3c'
        });
    }
});