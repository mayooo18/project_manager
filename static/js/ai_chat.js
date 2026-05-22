// ── State ──────────────────────────────────────────────────────────────────
const conversationHistory = [];

// ── Helpers ────────────────────────────────────────────────────────────────
function getCsrfToken() {
  const el = document.querySelector('meta[name="csrf-token"]') ||
             document.querySelector('input[name="csrf_token"]');
  return el ? (el.content || el.value) : '';
}

function post(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify(body)
  }).then(r => r.json());
}

// ── Panel open/close ───────────────────────────────────────────────────────
function openChat() {
  document.getElementById('ai-chat-panel').classList.remove('ai-hidden');
  document.getElementById('ai-chat-btn').classList.add('ai-hidden');
  document.getElementById('ai-chat-input').focus();
}

function closeChat() {
  document.getElementById('ai-chat-panel').classList.add('ai-hidden');
  document.getElementById('ai-chat-btn').classList.remove('ai-hidden');
}

// ── Messages ───────────────────────────────────────────────────────────────
function appendMessage(role, text) {
  const box = document.getElementById('ai-messages');
  const div = document.createElement('div');
  div.className = role === 'user' ? 'ai-msg ai-msg-user' : 'ai-msg ai-msg-bot';
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function showTyping() {
  const box = document.getElementById('ai-messages');
  const div = document.createElement('div');
  div.id = 'ai-typing';
  div.className = 'ai-msg ai-msg-bot';
  div.textContent = 'Thinking…';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('ai-typing');
  if (el) el.remove();
}

// ── Confirmation card ──────────────────────────────────────────────────────
function showConfirmationCard(actionId, tool, data) {
  const box = document.getElementById('ai-messages');

  const card = document.createElement('div');
  card.className = 'ai-card';
  card.id = 'ai-card-' + actionId;

  const title = document.createElement('div');
  title.className = 'ai-card-title';
  title.textContent = '📋 ' + tool.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  card.appendChild(title);

  const table = document.createElement('div');
  table.className = 'ai-card-body';
  Object.entries(data).forEach(([k, v]) => {
    const row = document.createElement('div');
    row.className = 'ai-card-row';
    row.innerHTML = `<span class="ai-card-key">${k.replace(/_/g, ' ')}</span>
                     <span class="ai-card-val">${v}</span>`;
    table.appendChild(row);
  });
  card.appendChild(table);

  const btns = document.createElement('div');
  btns.className = 'ai-card-btns';

  const confirm = document.createElement('button');
  confirm.className = 'ai-btn-confirm';
  confirm.textContent = 'Confirm';
  confirm.onclick = () => confirmAction(actionId, card);

  const reject = document.createElement('button');
  reject.className = 'ai-btn-reject';
  reject.textContent = 'Cancel';
  reject.onclick = () => rejectAction(actionId, card);

  btns.appendChild(confirm);
  btns.appendChild(reject);
  card.appendChild(btns);

  box.appendChild(card);
  box.scrollTop = box.scrollHeight;
}

function showSuggestions(suggestions) {
  const box = document.getElementById('ai-messages');
  const div = document.createElement('div');
  div.className = 'ai-suggestions';

  const label = document.createElement('div');
  label.className = 'ai-suggest-label';
  label.textContent = 'Did you mean:';
  div.appendChild(label);

  suggestions.forEach(name => {
    const btn = document.createElement('button');
    btn.className = 'ai-suggest-btn';
    btn.textContent = name;
    btn.onclick = () => {
      document.getElementById('ai-chat-input').value = name;
      div.remove();
    };
    div.appendChild(btn);
  });

  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

// ── Send message ───────────────────────────────────────────────────────────
async function sendMessage() {
  const input = document.getElementById('ai-chat-input');
  const message = input.value.trim();
  if (!message) return;

  input.value = '';
  appendMessage('user', message);
  showTyping();

  conversationHistory.push({ role: 'user', content: message });

  try {
    const res = await post('/ai/chat', {
      message,
      conversation_history: conversationHistory
    });

    removeTyping();

    if (res.clarification_needed) {
      appendMessage('bot', res.clarification_needed);
      conversationHistory.push({ role: 'assistant', content: res.clarification_needed });
      return;
    }

    if (res.validation_errors && res.validation_errors.length > 0) {
      const errMsg = res.validation_errors.join('\n');
      appendMessage('bot', '⚠️ ' + errMsg);
      if (res.suggestions && res.suggestions.length > 0) {
        showSuggestions(res.suggestions);
      }
      return;
    }

    if (res.tool && res.action_id) {
      appendMessage('bot', 'Here\'s what I found — please confirm:');
      showConfirmationCard(res.action_id, res.tool, res.data);
    }

  } catch (err) {
    removeTyping();
    appendMessage('bot', 'Something went wrong. Please try again.');
  }
}

// ── Confirm / Reject ───────────────────────────────────────────────────────
async function confirmAction(actionId, card) {
  try {
    const res = await post('/ai/confirm', { action_id: actionId });
    card.remove();
    appendMessage('bot', res.success ? '✅ ' + res.message : '❌ ' + res.message);
  } catch (err) {
    appendMessage('bot', 'Error confirming action.');
  }
}

async function rejectAction(actionId, card) {
  try {
    await post('/ai/reject', { action_id: actionId });
    card.remove();
    appendMessage('bot', '🚫 Cancelled. Nothing was saved.');
  } catch (err) {
    appendMessage('bot', 'Error cancelling action.');
  }
}

// ── Voice input ────────────────────────────────────────────────────────────
let recognition = null;
let isRecording = false;

function toggleVoice() {
  if (isRecording) {
    stopVoice();
  } else {
    startVoice();
  }
}

function startVoice() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    appendMessage('bot', 'Voice not supported in this browser. Please use Chrome.');
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onresult = (e) => {
    let transcript = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      transcript += e.results[i][0].transcript;
    }
    document.getElementById('ai-chat-input').value = transcript;
  };

  recognition.onend = () => {
    isRecording = false;
    document.getElementById('ai-mic-btn').classList.remove('ai-mic-active');
  };

  recognition.start();
  isRecording = true;
  document.getElementById('ai-mic-btn').classList.add('ai-mic-active');
}

function stopVoice() {
  if (recognition) recognition.stop();
  isRecording = false;
  document.getElementById('ai-mic-btn').classList.remove('ai-mic-active');
}

// ── Enter key to send ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('ai-chat-input');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }
});
