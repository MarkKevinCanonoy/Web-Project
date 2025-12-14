const API_URL = "http://localhost:8000/api";

document.getElementById("login-form").addEventListener("submit", async function(event) {
    event.preventDefault();

    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;

    try {
        const response = await fetch(`${API_URL}/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: email, password: password })
        });

        const data = await response.json();

        if (response.ok) {
            localStorage.setItem("token", data.token);
            localStorage.setItem("role", data.role);
            localStorage.setItem("user_id", data.user_id);
            localStorage.setItem("full_name", data.full_name || "User"); 

            // success animation (toast)
            const Toast = Swal.mixin({
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 1500,
                timerProgressBar: true,
                didOpen: (toast) => {
                    toast.addEventListener('mouseenter', Swal.stopTimer)
                    toast.addEventListener('mouseleave', Swal.resumeTimer)
                }
            });

            Toast.fire({
                icon: 'success',
                title: 'Signed in successfully'
            }).then(() => {
                // redirect based on role
                if (data.role === "student") {
                    window.location.href = "student-dashboard.html";
                } else if (data.role === "admin" || data.role === "super_admin") {
                    window.location.href = "admin-dashboard.html";
                }
            });

        } else {
            let errorText = 'Invalid email or password.';

            // if status is 422, it means the input format is wrong
            if (response.status === 422) {
                errorText = "Please enter a valid email address format.";
            } 
            // otherwise, use the server message if it's a simple string
            else if (data.detail && typeof data.detail === 'string') {
                errorText = data.detail;
            }

            Swal.fire({
                icon: 'error',
                title: 'Login Failed',
                text: errorText,
                confirmButtonColor: '#e74c3c'
            });
        }
    } catch (error) {
        console.error(error);
        Swal.fire({
            icon: 'error',
            title: 'Server Error',
            text: 'Cannot connect to the server.',
            confirmButtonColor: '#e74c3c'
        });
    }
});
/*
async function forgotPassword() {
    const { value: email } = await Swal.fire({
        title: 'Reset Password',
        input: 'email',
        inputLabel: 'Enter your email address',
        inputPlaceholder: 'student@evsu.edu.ph',
        showCancelButton: true,
        confirmButtonText: 'Send Request',
        confirmButtonColor: '#1E88E5',
        cancelButtonColor: '#d33',
        inputValidator: (value) => {
            if (!value) {
                return 'You need to write your email!'
            }
        }
    });

    if (email) {
        // Since we don't have a real email server, we simulate the success
        Swal.fire({
            icon: 'success',
            title: 'Request Sent',
            text: `If an account exists for ${email}, please contact the System Administrator to complete your password reset.`,
            confirmButtonColor: '#1E88E5'
        });
    }
}

*/