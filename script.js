// ================= SESSION MANAGEMENT =================
let currentUser = null;
let userToken = null;
let userCredits = 0;

// ================= INITIALIZATION =================
document.addEventListener('DOMContentLoaded', function() {
  checkSession();
});

// ================= AUTH FUNCTIONS =================
async function checkSession() {
  const savedUsername = localStorage.getItem('dtx_username');
  const savedToken = localStorage.getItem('dtx_token');
  
  if (savedUsername && savedToken) {
    // Verify session with backend
    try {
      const response = await fetch('/api/auth/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
        'X-KEY': 'Radha@2024' },
        body: JSON.stringify({
          username: savedUsername,
          token: savedToken
        })
      });
      
      const data = await response.json();
      
      if (data.success) {
        if (data.banned) {
          showBannedMessage();
          return;
        }
        
        // Valid session
        currentUser = data.username;
        userToken = savedToken;
        userCredits = data.credits;
        showMainPanel();
        updateTopBar();
        return;
      }
    } catch (error) {
      console.error('Session check failed:', error);
    }
  }
  
  // No valid session - show auth popup
  showAuthPopup(false);
}

function showAuthPopup(isLogin) {
  document.getElementById('authPopup').style.display = 'flex';
  document.getElementById('mainPanel').style.display = 'none';
  
  if (isLogin) {
    document.getElementById('authTitle').textContent = 'Login to DeepTraceX';
    document.getElementById('authSubtitle').textContent = 'Enter your username to continue';
  } else {
    document.getElementById('authTitle').textContent = 'Welcome to DeepTraceX';
    document.getElementById('authSubtitle').textContent = 'Enter a username to access the panel';
  }
  
  document.getElementById('authUsername').value = '';
  document.getElementById('authError').textContent = '';
}

function showMainPanel() {
  document.getElementById('authPopup').style.display = 'none';
  document.getElementById('mainPanel').style.display = 'block';
}

function showBannedMessage() {
  document.getElementById('authTitle').textContent = 'Account Banned';
  document.getElementById('authSubtitle').textContent = 'Your account has been permanently banned';
  document.getElementById('authUsername').style.display = 'none';
  document.getElementById('authButton').style.display = 'none';
  document.getElementById('authError').style.display = 'none';
}

async function handleAuth() {
  const username = document.getElementById('authUsername').value.trim();
  const errorDiv = document.getElementById('authError');
  const button = document.getElementById('authButton');
  
  errorDiv.textContent = '';
  
  if (!username) {
    errorDiv.textContent = 'Please enter a username';
    return;
  }
  
  if (username.length < 3) {
    errorDiv.textContent = 'Username must be at least 3 characters';
    return;
  }
  
  if (!/^[a-zA-Z0-9_]+$/.test(username)) {
    errorDiv.textContent = 'Username can only contain letters, numbers, and underscores';
    return;
  }
  
  // Show loading
  button.classList.add('loading');
  
  try {
    const response = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
      'X-KEY': 'Radha@2024'
       },
      body: JSON.stringify({ username })
    });
    
    const data = await response.json();
    
    if (data.success) {
      // Save session
      localStorage.setItem('dtx_username', data.username);
      localStorage.setItem('dtx_token', data.token);
      
      currentUser = data.username;
      userToken = data.token;
      userCredits = data.credits;
      
      // Show main panel
      showMainPanel();
      updateTopBar();
      
      // Show welcome message for new users
      if (data.is_new) {
        showNotification('Welcome! You have 10 free credits to start.', 'success');
      } else {
        showNotification('Welcome back!', 'success');
      }
    } else {
      errorDiv.textContent = data.error || 'Registration failed';
    }
  } catch (error) {
    errorDiv.textContent = 'Connection error. Please try again.';
    console.error('Auth error:', error);
  } finally {
    button.classList.remove('loading');
  }
}

function handleLogout() {
  if (!confirm('Are you sure you want to logout?')) {
    return;
  }
  
  localStorage.removeItem('dtx_username');
  localStorage.removeItem('dtx_token');
  
  currentUser = null;
  userToken = null;
  userCredits = 0;
  
  showAuthPopup(true);
}

function updateTopBar() {
  document.getElementById('topUsername').textContent = currentUser;
  document.getElementById('topCredits').textContent = userCredits;
}

async function refreshCredits() {
  try {
    const response = await fetch('/api/credits/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json',
      'X-KEY': 'Radha@2024'
       },
      body: JSON.stringify({
        username: currentUser,
        token: userToken
      })
    });
    
    const data = await response.json();
    
    if (data.success) {
      userCredits = data.credits;
      updateTopBar();
    }
  } catch (error) {
    console.error('Credit refresh failed:', error);
  }
}

// ================= LOOKUP FUNCTIONS =================
const examples = {
  num: { placeholder: "e.g., 9876543210", pattern: /^[6-9]\d{9}$/ },
  aadhaar: { placeholder: "e.g., 123456789012", pattern: /^\d{12}$/ },
  gst: { placeholder: "e.g., 22AAAAA0000A1Z5", pattern: /^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$/ },
  ifsc: { placeholder: "e.g., SBIN0001234", pattern: /^[A-Z]{4}0[A-Z0-9]{6}$/ },
  upi: { placeholder: "e.g., username@upi", pattern: /.+@.+/ },
  fam: { placeholder: "e.g., username@fam", pattern: /.+@fam$/ },
  vehicle: { placeholder: "e.g., DL01AB1234", pattern: /.+/ }
};

function setExample() {
  const type = document.getElementById('type').value;
  const input = document.getElementById('input');
  
  if (!type) {
    input.disabled = true;
    input.placeholder = "Select lookup type first";
    return;
  }
  
  input.disabled = false;
  input.placeholder = examples[type].placeholder;
  input.value = '';
  document.getElementById('result').innerHTML = '';
}

async function lookup() {
  const type = document.getElementById('type').value;
  const query = document.getElementById('input').value.trim();
  const resultDiv = document.getElementById('result');
  const button = document.querySelector('.form-section button');
  
  // Validation
  if (!type) {
    showNotification('Please select a lookup type', 'error');
    return;
  }
  
  if (!query) {
    showNotification('Please enter a value to search', 'error');
    return;
  }
  
  // Pattern validation
  const pattern = examples[type].pattern;
  if (!pattern.test(query)) {
    showNotification('Invalid format for selected lookup type', 'error');
    return;
  }
  
  // Show loading
  button.classList.add('loading');
  resultDiv.innerHTML = '<div class="loading-card">Processing your request...</div>';
  
  try {
    const response = await fetch(`/api/${type}?q=${encodeURIComponent(query)}`, {
      headers: {
        'X-Username': currentUser,
        'X-Token': userToken,
        'X-KEY': 'Radha@2024'
      }
    });
    
    const html = await response.text();
    resultDiv.innerHTML = html;
    
    // Refresh credits after lookup
    await refreshCredits();
    
    // Scroll to result
    resultDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    
  } catch (error) {
    resultDiv.innerHTML = `
      <div class="error-card">
        <div class="error-icon">⚠</div>
        <div class="error-title">Request Failed</div>
        <div class="error-msg">Connection error. Please try again.</div>
      </div>
    `;
    console.error('Lookup error:', error);
  } finally {
    button.classList.remove('loading');
  }
}

// ================= UTILITY FUNCTIONS =================
function showNotification(message, type = 'info') {
  const notification = document.createElement('div');
  notification.className = `notification notification-${type}`;
  notification.textContent = message;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    notification.classList.add('show');
  }, 10);
  
  setTimeout(() => {
    notification.classList.remove('show');
    setTimeout(() => {
      notification.remove();
    }, 300);
  }, 3000);
}

// Enter key support for auth
document.addEventListener('DOMContentLoaded', function() {
  const authInput = document.getElementById('authUsername');
  if (authInput) {
    authInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        handleAuth();
      }
    });
  }
});

// Enter key support for lookup
document.addEventListener('DOMContentLoaded', function() {
  const lookupInput = document.getElementById('input');
  if (lookupInput) {
    lookupInput.addEventListener('keypress', function(e) {
      if (e.key === 'Enter') {
        lookup();
      }
    });
  }
});
