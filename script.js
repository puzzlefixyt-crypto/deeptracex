// ==================== CONFIGURATION ====================
const API_KEY = "Radha@2024";
const BASE_URL = window.location.origin;

// ==================== SESSION STORAGE ====================
function saveSession(username, token, credits) {
  localStorage.setItem("dtx_username", username);
  localStorage.setItem("dtx_token", token);
  localStorage.setItem("dtx_credits", credits);
}

function getSession() {
  return {
    username: localStorage.getItem("dtx_username"),
    token: localStorage.getItem("dtx_token"),
    credits: localStorage.getItem("dtx_credits")
  };
}

function clearSession() {
  localStorage.removeItem("dtx_username");
  localStorage.removeItem("dtx_token");
  localStorage.removeItem("dtx_credits");
}

// ==================== UI HELPERS ====================
function showNotification(message, type = "success") {
  const notif = document.createElement("div");
  notif.className = `notification notification-${type} show`;
  notif.textContent = message;
  document.body.appendChild(notif);

  setTimeout(() => {
    notif.classList.remove("show");
    setTimeout(() => notif.remove(), 300);
  }, 3000);
}

function setLoading(btnId, loading) {
  const btn = document.getElementById(btnId);
  if (loading) {
    btn.classList.add("loading");
    btn.disabled = true;
  } else {
    btn.classList.remove("loading");
    btn.disabled = false;
  }
}

function showTelegramVerification(bindCode) {
  // Hide username input and button
  document.getElementById("authUsername").style.display = "none";
  document.getElementById("authButton").style.display = "none";
  
  // Update header
  document.getElementById("authTitle").textContent = "Telegram Verification";
  document.getElementById("authSubtitle").textContent = "Secure your account with Telegram";
  
  // Show Telegram box
  const telegramBox = document.getElementById("telegramBox");
  telegramBox.style.display = "block";
  document.getElementById("tgBindCode").textContent = bindCode;
  
  // Start polling for verification
  startVerificationPolling();
}

function hideTelegramVerification() {
  document.getElementById("telegramBox").style.display = "none";
  document.getElementById("authUsername").style.display = "block";
  document.getElementById("authButton").style.display = "block";
  document.getElementById("authTitle").textContent = "Welcome to DeepTraceX";
  document.getElementById("authSubtitle").textContent = "Enter a username to access the panel";
}

// ==================== TELEGRAM VERIFICATION POLLING ====================
let verificationPollInterval = null;

function startVerificationPolling() {
  // Poll every 3 seconds
  verificationPollInterval = setInterval(checkVerificationStatus, 3000);
}

function stopVerificationPolling() {
  if (verificationPollInterval) {
    clearInterval(verificationPollInterval);
    verificationPollInterval = null;
  }
}

async function checkVerificationStatus() {
  const session = getSession();
  if (!session.username || !session.token) {
    stopVerificationPolling();
    return;
  }

  try {
    const response = await fetch(`${BASE_URL}/api/auth/check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: session.username,
        token: session.token
      })
    });

    const data = await response.json();

    if (data.success) {
      // Verified! Stop polling and show main panel
      stopVerificationPolling();
      saveSession(data.username, session.token, data.credits);
      showMainPanel(data.username, data.credits);
      showNotification("✅ Telegram verification successful!");
    } else if (data.telegram_required) {
      // Still waiting for verification
      // Continue polling
    } else {
      // Some error occurred
      stopVerificationPolling();
      showNotification("Verification failed. Please try again.", "error");
      hideTelegramVerification();
      clearSession();
    }
  } catch (error) {
    console.error("Verification check error:", error);
  }
}

function copyBindCode() {
  const code = document.getElementById("tgBindCode").textContent;
  navigator.clipboard.writeText(`/start ${code}`).then(() => {
    showNotification("✅ Copied to clipboard!");
  }).catch(() => {
    showNotification("Failed to copy. Please copy manually.", "error");
  });
}

// ==================== AUTH FUNCTIONS ====================
async function handleAuth() {
  const username = document.getElementById("authUsername").value.trim();
  const errorDiv = document.getElementById("authError");

  errorDiv.textContent = "";

  if (!username) {
    errorDiv.textContent = "Please enter a username";
    return;
  }

  if (username.length < 3) {
    errorDiv.textContent = "Username must be at least 3 characters";
    return;
  }

  if (!/^[a-zA-Z0-9_]+$/.test(username)) {
    errorDiv.textContent = "Username can only contain letters, numbers, and underscores";
    return;
  }

  setLoading("authButton", true);

  try {
    const response = await fetch(`${BASE_URL}/api/auth/register`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ username })
    });

    const data = await response.json();

    if (data.success) {
      saveSession(data.username, data.token, data.credits);

      if (data.telegram_required) {
        // Show Telegram verification UI
        showTelegramVerification(data.bind_code);
      } else {
        // Already verified, show main panel
        showMainPanel(data.username, data.credits);
        if (data.is_new) {
          showNotification("🎉 Welcome to DeepTraceX!");
        } else {
          showNotification("✅ Welcome back!");
        }
      }
    } else {
      if (data.telegram_required) {
        // User needs to verify
        showTelegramVerification(data.bind_code);
      } else {
        errorDiv.textContent = data.error || "Registration failed";
      }
    }
  } catch (error) {
    errorDiv.textContent = "Connection error. Please try again.";
  } finally {
    setLoading("authButton", false);
  }
}

async function checkAuth() {
  const session = getSession();

  if (!session.username || !session.token) {
    return false;
  }

  try {
    const response = await fetch(`${BASE_URL}/api/auth/check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: session.username,
        token: session.token
      })
    });

    const data = await response.json();

    if (data.success) {
      saveSession(data.username, session.token, data.credits);
      showMainPanel(data.username, data.credits);
      return true;
    } else if (data.telegram_required) {
      // Show Telegram verification
      showTelegramVerification(data.bind_code);
      return false;
    } else if (data.banned) {
      showNotification("❌ Your account has been banned", "error");
      clearSession();
      return false;
    } else {
      clearSession();
      return false;
    }
  } catch (error) {
    console.error("Auth check error:", error);
    return false;
  }
}

function handleLogout() {
  if (confirm("Are you sure you want to logout?")) {
    stopVerificationPolling();
    clearSession();
    document.getElementById("authPopup").style.display = "flex";
    document.getElementById("mainPanel").style.display = "none";
    document.getElementById("authUsername").value = "";
    document.getElementById("authError").textContent = "";
    hideTelegramVerification();
    showNotification("👋 Logged out successfully");
  }
}

function showMainPanel(username, credits) {
  stopVerificationPolling();
  document.getElementById("authPopup").style.display = "none";
  document.getElementById("mainPanel").style.display = "block";
  document.getElementById("topUsername").textContent = username;
  document.getElementById("topCredits").textContent = credits;
}

// ==================== LOOKUP HELPERS ====================
const examples = {
  num: "9876543210",
  aadhaar: "123456789012",
  gst: "27AAPFU0939F1ZV",
  ifsc: "SBIN0001234",
  upi: "username@paytm",
  fam: "phonenumber@fam",
  vehicle: "DL01AB1234"
};

function setExample() {
  const type = document.getElementById("type").value;
  const input = document.getElementById("input");

  if (type) {
    input.disabled = false;
    input.placeholder = `e.g. ${examples[type]}`;
    input.value = "";
  } else {
    input.disabled = true;
    input.placeholder = "Select lookup type first";
    input.value = "";
  }
}

async function lookup() {
  const type = document.getElementById("type").value;
  const query = document.getElementById("input").value.trim();
  const resultDiv = document.getElementById("result");
  const session = getSession();

  if (!type) {
    showNotification("Please select a lookup type", "error");
    return;
  }

  if (!query) {
    showNotification("Please enter a value to lookup", "error");
    return;
  }

  // Show loading
  resultDiv.innerHTML = '<div class="loading-card">🔍 Performing lookup...</div>';

  try {
    const response = await fetch(`${BASE_URL}/api/${type}?q=${encodeURIComponent(query)}`, {
      headers: {
        "X-KEY": API_KEY,
        "X-Username": session.username,
        "X-Token": session.token
      }
    });

    const html = await response.text();
    resultDiv.innerHTML = html;

    // Update credits
    await updateCredits();
  } catch (error) {
    resultDiv.innerHTML = `
      <div class="error-card">
        <div class="error-icon">⚠</div>
        <div class="error-title">Request Failed</div>
        <div class="error-msg">Connection error. Please try again.</div>
      </div>
    `;
  }
}

async function updateCredits() {
  const session = getSession();

  try {
    const response = await fetch(`${BASE_URL}/api/credits/check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: session.username,
        token: session.token
      })
    });

    const data = await response.json();

    if (data.success) {
      document.getElementById("topCredits").textContent = data.credits;
      saveSession(session.username, session.token, data.credits);
    }
  } catch (error) {
    console.error("Credit update error:", error);
  }
}

// ==================== ENTER KEY HANDLER ====================
document.addEventListener("DOMContentLoaded", () => {
  // Auth username input
  const authInput = document.getElementById("authUsername");
  authInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      handleAuth();
    }
  });

  // Lookup input
  const lookupInput = document.getElementById("input");
  lookupInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      lookup();
    }
  });

  // Check auth on load
  checkAuth();
});
