/* ============================================================
   SmartFarm AI – Frontend JavaScript (Redesigned & Expanded)
   Tabs, localStorage Farm Profile, Recent Questions, Simple Mode,
   PDF Download, Crop Calendar, Government Schemes, TTS, Caching
   ============================================================ */

"use strict";

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  chatHistory:          [],
  darkMode:             false,
  msgCounter:           0,          // unique ID for each bot message
  ttsUtterance:         null,       // currently speaking SpeechSynthesisUtterance
  feedback:             {},         // { msgId: "up"|"down" } stored in localStorage
  weatherCache:         {},         // { "State:Jan": responseData }
  currentWeatherState:  "Maharashtra",
  currentWeatherMonth:  null,
  
  // New State variables
  farmProfile:          null,       // { location, soil_type, farm_size }
  recentQuestions:      [],         // array of strings
  simpleMode:           false,      // toggle state
  activeTab:            "tab-chat"
};

// ── Utility helpers ───────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function now() {
  return new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}

/** Very small markdown → HTML renderer */
function mdToHtml(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/^[-•]\s+(.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]+?<\/li>)/g, "<ul>$1</ul>")
    .split(/\n{2,}/)
    .map(p => p.trim() ? `<p>${p.replace(/\n/g, "<br>")}</p>` : "")
    .join("") || `<p>${text}</p>`;
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function showLoading(id, msg = "Loading…") {
  const placeholder = `<div class="loading-skeleton" aria-label="Loading content">
    <div class="skeleton-block tall"></div>
    <div class="skeleton-block short"></div>
    <div class="skeleton-block medium"></div>
    <div class="skeleton-block large"></div>
  </div>`;
  const target = $(id);
  if (target) target.innerHTML = placeholder;
}

function showToast(title, message, type = "info") {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-notification ${type}`;
  toast.innerHTML = `<div class="toast-title">${escapeHtml(title)}</div><div class="toast-message">${escapeHtml(message)}</div>`;
  container.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add('show'));

  window.setTimeout(() => {
    toast.classList.remove('show');
    toast.classList.add('hide');
    window.setTimeout(() => toast.remove(), 220);
  }, 3000);
}

function markInvalid(el) {
  if (!el) return;
  el.classList.remove('is-invalid');
  void el.offsetWidth;
  el.classList.add('is-invalid');
  window.setTimeout(() => el.classList.remove('is-invalid'), 600);
}

function showError(id, msg) {
  $(id).innerHTML = `<div class="error-box"><i class="bi bi-exclamation-triangle-fill"></i><span>${escapeHtml(msg)}</span></div>`;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Tab Navigation Switching ──────────────────────────────────────────────────
let _tabSwitching = false;

window.switchTab = function(tabId) {
  if (state.activeTab === tabId && !_tabSwitching) return; // no-op on same tab
  state.activeTab = tabId;

  document.querySelectorAll('.quick-nav-card').forEach(card => {
    const isActive = (card.dataset.tab === tabId || card.getAttribute('href') === `#${tabId}`);
    card.classList.toggle('active', isActive);
    card.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    if (isActive) {
      card.animate([
        { transform: 'translateY(-1px) scale(1.02)', opacity: 0.96 },
        { transform: 'translateY(0) scale(1)', opacity: 1 }
      ], { duration: 220, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' });
    }
  });

  const panels = document.querySelectorAll(".tab-content-panel");
  const targetPanel = $(tabId);
  if (!targetPanel) return;

  // Step 1: Apply .leaving to all currently active panels (outgoing)
  panels.forEach(panel => {
    if (panel.classList.contains("active") && panel !== targetPanel) {
      panel.classList.add("leaving");
      panel.classList.remove("active");
      // Clean up leaving class after transition
      panel.addEventListener("transitionend", function cleanup() {
        panel.classList.remove("leaving");
        panel.removeEventListener("transitionend", cleanup);
      }, { once: true });
    }
  });

  // Step 2: Animate the incoming panel in on the next frame
  requestAnimationFrame(() => {
    targetPanel.classList.remove("leaving");
    requestAnimationFrame(() => {
      targetPanel.classList.add("active");
    });
  });

  // ── Sync Navbar link active indicator ──────────────────────────────────────
  document.querySelectorAll(".navbar-nav .nav-link").forEach(link => {
    const href = link.getAttribute("href");
    const isActive = (href === `#${tabId}`);
    link.classList.toggle("active", isActive);
    link.setAttribute("aria-current", isActive ? "page" : "");
  });

  // ── Sync Mobile bottom nav ──────────────────────────────────────────────────
  document.querySelectorAll(".mobile-bottom-nav .mobile-nav-item").forEach(item => {
    const href = item.getAttribute("href");
    item.classList.toggle("active", href === `#${tabId}`);
  });

  // ── Smooth scroll to content area (below hero + nav bar) ───────────────────
  const mainContent = document.querySelector(".main-content");
  if (mainContent) {
    const nav = document.querySelector("#mainNav");
    const chips = document.querySelector(".chips-section");
    const offset = (nav?.offsetHeight || 0) + (chips?.offsetHeight || 0) + 8;
    const top = mainContent.getBoundingClientRect().top + window.scrollY - offset;
    window.scrollTo({ top: Math.max(top, 0), behavior: "smooth" });
  }
};

// ── Farm Profile localStorage ────────────────────────────────────────────────
function initFarmProfile() {
  // Load saved profile
  const saved = localStorage.getItem("sf_profile");
  if (saved) {
    try {
      state.farmProfile = JSON.parse(saved);
      applyProfileToUI();
    } catch (e) {
      state.farmProfile = null;
    }
  }

  // Save profile button click listener
  $("saveProfileBtn")?.addEventListener("click", () => {
    const location = $("profLocation").value;
    const soil_type = $("profSoil").value;
    const farm_size = $("profSize").value.trim() || "2 acres";

    state.farmProfile = { location, soil_type, farm_size };
    localStorage.setItem("sf_profile", JSON.stringify(state.farmProfile));
    
    // Auto-fill forms & update badges
    applyProfileToUI();

    // Close Bootstrap Modal
    const modalEl = $("profileModal");
    const modal = bootstrap.Modal.getInstance(modalEl);
    if (modal) modal.hide();
  });
}

function applyProfileToUI() {
  if (!state.farmProfile) return;

  const { location, soil_type, farm_size } = state.farmProfile;

  // 1. Update navbar setup badge
  const label = $("profileNavLabel");
  if (label) label.textContent = location;

  // 2. Pre-fill crop recommendation page inputs
  const cropLoc = $("cropLocation");
  if (cropLoc) cropLoc.value = location;
  
  const cropSoil = $("cropSoil");
  if (cropSoil) cropSoil.value = soil_type;

  const cropSize = $("cropFarmSize");
  if (cropSize) cropSize.value = farm_size;

  // 3. Update profile widget on chat page
  const widget = $("activeProfileContent");
  if (widget) {
    widget.innerHTML = `
      <div class="mb-1">📍 <strong>Region:</strong> ${location}</div>
      <div class="mb-1">🪨 <strong>Soil:</strong> ${soil_type}</div>
      <div class="mb-0">📏 <strong>Size:</strong> ${farm_size}</div>
      <button class="btn btn-xs btn-outline-custom mt-2 w-100" data-bs-toggle="modal" data-bs-target="#profileModal">
        <i class="bi bi-pencil"></i> Edit Profile
      </button>
    `;
  }

  // Pre-fill fields in the form inside the modal
  const modalLoc = $("profLocation");
  if (modalLoc) modalLoc.value = location;

  const modalSoil = $("profSoil");
  if (modalSoil) modalSoil.value = soil_type;

  const modalSize = $("profSize");
  if (modalSize) modalSize.value = farm_size;
}

// ── Recent Questions Panel ──────────────────────────────────────────────────
function initRecentQuestions() {
  const saved = localStorage.getItem("sf_recent_questions");
  if (saved) {
    try { state.recentQuestions = JSON.parse(saved); }
    catch (_) { state.recentQuestions = []; }
  }
  renderRecentQuestions();

  $("clearRecentBtn")?.addEventListener("click", () => {
    state.recentQuestions = [];
    localStorage.removeItem("sf_recent_questions");
    renderRecentQuestions();
  });
}

function saveQuestion(q) {
  if (!q) return;
  // Remove existing duplicate
  state.recentQuestions = state.recentQuestions.filter(item => item.toLowerCase() !== q.toLowerCase());
  // Insert at front
  state.recentQuestions.unshift(q);
  // Keep last 8
  if (state.recentQuestions.length > 8) {
    state.recentQuestions.pop();
  }
  localStorage.setItem("sf_recent_questions", JSON.stringify(state.recentQuestions));
  renderRecentQuestions();
}

function renderRecentQuestions() {
  const container = $("recentQuestionsList");
  if (!container) return;

  if (state.recentQuestions.length === 0) {
    container.innerHTML = `<div class="text-muted small text-center py-2">No recent queries yet</div>`;
    return;
  }

  container.innerHTML = state.recentQuestions.map(q => `
    <button class="recent-question-item" title="${escapeHtml(q)}">
      ${escapeHtml(q)}
    </button>
  `).join("");

  // Add click listeners to re-ask questions
  container.querySelectorAll(".recent-question-item").forEach((btn, i) => {
    btn.addEventListener("click", () => {
      const q = state.recentQuestions[i];
      const input = $("chatInput");
      if (input) {
        input.value = q;
        sendMessage();
      }
    });
  });
}

// ── Simple Mode Toggle ───────────────────────────────────────────────────────
function initSimpleMode() {
  const toggle = $("simpleModeToggle");
  if (!toggle) return;

  const saved = localStorage.getItem("sf_simple_mode");
  state.simpleMode = (saved === "1");
  toggle.checked = state.simpleMode;

  toggle.addEventListener("change", (e) => {
    state.simpleMode = e.target.checked;
    localStorage.setItem("sf_simple_mode", state.simpleMode ? "1" : "0");
  });
}

// ── PDF Client-Side Generation ──────────────────────────────────────────────
function downloadAdvisoryPDF(markdownContent, title) {
  if (typeof html2pdf === "undefined") {
    showToast("PDF library", "The PDF library is still loading. Please try again in a moment.", "warning");
    return;
  }

  // Create temporary offscreen print container styled in white
  const printEl = document.createElement("div");
  printEl.className = "pdf-export-container";

  const dateStr = new Date().toLocaleDateString("en-IN", { dateStyle: "long" });

  printEl.innerHTML = `
    <div class="pdf-export-header">
      <div>
        <h2 class="pdf-export-title">🌾 KisanAI Smart Farming Advisory</h2>
        <p style="margin:2px 0 0;font-size:11px;color:#10b981;font-weight:600;">Your AI-Powered Agriculture Companion</p>
      </div>
      <div class="pdf-export-meta">
        <p style="margin:0;"><strong>Date:</strong> ${dateStr}</p>
        <p style="margin:2px 0 0;"><strong>Document:</strong> ${title}</p>
      </div>
    </div>
    <div class="pdf-export-content">
      ${mdToHtml(markdownContent)}
    </div>
    <div class="pdf-export-footer">
      <p style="margin:0;">📋 Note: This advice is based on general best practices. Always consult your local Krishi Vigyan Kendra (KVK) or Agriculture Officer for region-specific guidance.</p>
      <p style="margin:6px 0 0;font-size:9px;color:#9ca3af;">Generated using IBM watsonx.ai Granite LLM RAG System.</p>
    </div>
  `;

  const opt = {
    margin:       12,
    filename:     `kisanai_${title.toLowerCase().replace(/\s+/g, '_')}_${new Date().getTime()}.pdf`,
    image:        { type: 'jpeg', quality: 0.98 },
    html2canvas:  { scale: 2, useCORS: true, letterRendering: true },
    jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
  };

  html2pdf().from(printEl).set(opt).save();
}

// ── Persist feedback to localStorage ─────────────────────────────────────────
function loadFeedback() {
  try { state.feedback = JSON.parse(localStorage.getItem("sf_feedback") || "{}"); }
  catch (_) { state.feedback = {}; }
}

function saveFeedback(msgId, vote) {
  state.feedback[msgId] = vote;
  try { localStorage.setItem("sf_feedback", JSON.stringify(state.feedback)); } catch (_) {}
}

// ── Dark Mode ─────────────────────────────────────────────────────────────────
function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  const icon = $("darkModeIcon");
  if (icon) icon.className = dark ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
  state.darkMode = dark;
  localStorage.setItem("sf_dark", dark ? "1" : "0");
}

function initDarkMode() {
  const saved = localStorage.getItem("sf_dark");
  // Default to Dark Mode now as requested by user ("data-theme='dark'")
  applyTheme(saved !== null ? saved === "1" : true);
  $("darkModeToggle")?.addEventListener("click", () => applyTheme(!state.darkMode));
}

// ── Health / KB status ────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const data = await fetch("/api/health").then(r => r.json());
    const dot = $("kbStatusDot");
    if (!dot) return;
    const chunks = data?.kb?.chunk_count ?? 0;
    dot.className = "kb-status-dot" + (chunks > 0 ? " ready" : "");
    dot.title = chunks > 0 ? `KB ready – ${chunks} chunks` : "KB indexing…";
  } catch (_) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// CHAT – with TTS, PDF and thumbs feedback
// ══════════════════════════════════════════════════════════════════════════════

/** Strip markdown for TTS so it sounds natural */
function stripMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`(.+?)`/g, "$1")
    .replace(/^[-•]\s+/gm, "")
    .replace(/<[^>]+>/g, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\n/g, " ")
    .trim();
}

const TTS_SUPPORTED = "speechSynthesis" in window;

function speakText(text, btnEl) {
  if (!TTS_SUPPORTED) { showToast("Speech", "Text-to-speech is not supported in your browser.", "warning"); return; }

  // Stop any current speech
  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    if (btnEl.classList.contains("speaking")) {
      btnEl.classList.remove("speaking");
      btnEl.innerHTML = '<i class="bi bi-volume-up"></i> Listen';
      return;
    }
  }

  // Reset all TTS buttons
  document.querySelectorAll(".btn-tts.speaking").forEach(b => {
    b.classList.remove("speaking");
    b.innerHTML = '<i class="bi bi-volume-up"></i> Listen';
  });

  const clean = stripMarkdown(text);
  const utterance = new SpeechSynthesisUtterance(clean);
  utterance.lang  = /[\u0900-\u097F]/.test(text) ? "hi-IN" : "en-IN";
  utterance.rate  = 0.88;
  utterance.pitch = 1.0;

  utterance.onstart = () => {
    btnEl.classList.add("speaking");
    btnEl.innerHTML = '<i class="bi bi-stop-circle"></i> Stop';
  };
  utterance.onend = utterance.onerror = () => {
    btnEl.classList.remove("speaking");
    btnEl.innerHTML = '<i class="bi bi-volume-up"></i> Listen';
  };

  window.speechSynthesis.speak(utterance);
}

function appendMessage(role, content, sources = []) {
  const chatWindow = $("chatWindow");
  if (!chatWindow) return;

  const isUser  = role === "user";
  const avatar  = isUser ? "👨‍🌾" : "🌾";
  const msgId   = isUser ? null : `msg-${++state.msgCounter}`;

  // Source badge (bot only)
  const srcHtml = (!isUser && sources.length)
    ? `<span class="sources-badge" title="${escapeHtml(sources.map(s=>s.source).join(', '))}">
         <i class="bi bi-database-check me-1"></i>${sources.length} KB source${sources.length>1?"s":""}
       </span>`
    : "";

  // Action row: TTS + PDF + feedback (bot only)
  const ttsSupport = TTS_SUPPORTED ? `<button class="btn-msg-action btn-tts" data-text="${escapeHtml(content)}"><i class="bi bi-volume-up"></i> Listen</button>` : "";
  const pdfBtn = !isUser ? `<button class="btn-msg-action btn-download-pdf" data-id="${msgId}"><i class="bi bi-file-earmark-pdf"></i> PDF</button>` : "";
  const fbHtml = !isUser
    ? `<button class="btn-msg-action btn-feedback-up"   data-id="${msgId}" title="Helpful">👍</button>
       <button class="btn-msg-action btn-feedback-down" data-id="${msgId}" title="Not helpful">👎</button>
       <span class="feedback-thanks d-none" id="fb-thanks-${msgId}">Thanks!</span>`
    : "";
  const actionsHtml = !isUser
    ? `<div class="msg-actions">${ttsSupport}${pdfBtn}${fbHtml}</div>`
    : "";

  const bubbleContent = isUser
    ? `<p class="mb-0">${escapeHtml(content)}</p>`
    : `${mdToHtml(content)}${srcHtml ? `<div class="mt-1">${srcHtml}</div>` : ""}`;

  const html = `
    <div class="chat-msg ${isUser ? "user" : "bot"}" id="${msgId || ""}">
      <div class="msg-avatar">${avatar}</div>
      <div>
        <div class="msg-bubble">${bubbleContent}</div>
        ${actionsHtml}
        <div class="msg-time">${now()}</div>
      </div>
    </div>`;

  chatWindow.insertAdjacentHTML("beforeend", html);

  // Wire TTS button
  if (!isUser && TTS_SUPPORTED) {
    const msgEl = $(`${msgId}`);
    const ttsBtn = msgEl?.querySelector(".btn-tts");
    if (ttsBtn) {
      ttsBtn.addEventListener("click", () => speakText(content, ttsBtn));
    }
  }

  // Wire PDF Download button
  if (!isUser && msgId) {
    const msgEl = $(`${msgId}`);
    const pdfBtnEl = msgEl?.querySelector(".btn-download-pdf");
    if (pdfBtnEl) {
      pdfBtnEl.addEventListener("click", () => downloadAdvisoryPDF(content, "Chat Advisory"));
    }
  }

  // Wire feedback buttons
  if (!isUser && msgId) {
    const msgEl = $(`${msgId}`);
    if (msgEl) {
      msgEl.querySelector(".btn-feedback-up")?.addEventListener("click", e => handleFeedback(msgId, "up", e.currentTarget));
      msgEl.querySelector(".btn-feedback-down")?.addEventListener("click", e => handleFeedback(msgId, "down", e.currentTarget));
    }
  }

  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function handleFeedback(msgId, vote, btnEl) {
  if (state.feedback[msgId] === vote) {
    delete state.feedback[msgId];
    saveFeedback(msgId, null);
    const el = $(`${msgId}`);
    el?.querySelectorAll(".btn-feedback-up,.btn-feedback-down").forEach(b => b.classList.remove("active"));
    const thanks = $(`fb-thanks-${msgId}`);
    if (thanks) thanks.classList.add("d-none");
    return;
  }

  saveFeedback(msgId, vote);
  const el = $(`${msgId}`);
  if (el) {
    el.querySelectorAll(".btn-feedback-up,.btn-feedback-down").forEach(b => b.classList.remove("active"));
    btnEl.classList.add("active");
    const thanks = $(`fb-thanks-${msgId}`);
    if (thanks) { thanks.classList.remove("d-none"); thanks.textContent = vote === "up" ? "Thanks! 😊" : "Sorry to hear. We'll improve."; }
  }
}

async function sendMessage() {
  const input   = $("chatInput");
  const sendBtn = $("sendBtn");
  const typing  = $("typingIndicator");
  const query   = input.value.trim();
  if (!query) return;

  input.value = "";
  input.style.height = "auto";
  sendBtn.disabled = true;

  appendMessage("user", query);
  state.chatHistory.push({ user: query, assistant: "" });

  typing?.classList.remove("d-none");

  // Save to recent questions list
  saveQuestion(query);

  try {
    const payload = {
      message: query,
      history: state.chatHistory.slice(0, -1),
      simple_mode: state.simpleMode,
      profile: state.farmProfile
    };

    const data = await postJSON("/api/chat", payload);
    typing?.classList.add("d-none");
    const answer = data.answer || "Sorry, I could not generate a response.";
    appendMessage("bot", answer, data.sources || []);
    state.chatHistory[state.chatHistory.length - 1].assistant = answer;
  } catch (err) {
    typing?.classList.add("d-none");
    appendMessage("bot", `⚠️ Error: ${err.message}. Please try again.`);
    state.chatHistory.pop();
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

function initChat() {
  const input   = $("chatInput");
  const sendBtn = $("sendBtn");

  input?.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 120) + "px";
  });

  input?.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); sendMessage(); }
  });

  sendBtn?.addEventListener("click", sendMessage);

  document.querySelectorAll(".btn-suggestion").forEach(btn => {
    btn.addEventListener("click", () => {
      if (input) input.value = btn.dataset.q;
      sendMessage();
    });
  });

  $("clearChatBtn")?.addEventListener("click", () => {
    const cw = $("chatWindow");
    const welcome = $("welcomeMsg");
    if (!cw) return;
    cw.innerHTML = "";
    if (welcome) cw.appendChild(welcome);
    state.chatHistory = [];
    if (TTS_SUPPORTED) window.speechSynthesis.cancel();
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// SEASONAL WEATHER  (static JSON via /api/weather)
// ══════════════════════════════════════════════════════════════════════════════

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function renderWeatherCard(data) {
  const w   = data.weather;
  const card = $("weatherCurrentCard");
  if (!card) return;

  card.innerHTML = `
    <div class="weather-current-main">
      <div>
        <div class="weather-city"><i class="bi bi-geo-alt me-1"></i>${data.state} <span style="opacity:.7;font-size:.8em">(${data.region})</span></div>
        <div class="weather-temp">${w.temp_max}°<span style="font-size:1.5rem;font-weight:400;opacity:.75"> / ${w.temp_min}°C</span></div>
        <div class="weather-desc">${w.weather}</div>
      </div>
      <div style="font-size:3.5rem;line-height:1">${w.icon}</div>
    </div>
    <div class="weather-details-row">
      <div class="weather-detail-item"><i class="bi bi-droplet-fill me-1"></i>${w.humidity}% humidity</div>
      <div class="weather-detail-item"><i class="bi bi-cloud-rain me-1"></i>${w.rainfall} mm rain</div>
    </div>`;

  const advBox  = $("weatherFarmingAdvice");
  const advText = $("weatherAdviceText");
  if (advBox && advText && w.farming_tip) {
    advText.textContent = w.farming_tip;
    advBox.classList.remove("d-none");
  }
}

function renderMonthStrip(allMonths, selectedMonth) {
  const container = $("forecastContainer");
  if (!container) return;
  container.className = "month-strip mt-3";
  container.innerHTML = Object.entries(allMonths).map(([mon, d]) => `
    <div class="month-pill ${mon === selectedMonth ? "active" : ""}" data-month="${mon}">
      <span class="pill-icon">${d.icon}</span>
      <span class="pill-name">${mon}</span>
      <span class="pill-temp">${d.temp_max}°</span>
    </div>`).join("");

  container.querySelectorAll(".month-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const mon = pill.dataset.month;
      const sel = $("weatherMonth");
      if (sel) sel.value = mon;
      loadWeather(state.currentWeatherState, mon);
    });
  });
}

async function loadWeather(stateVal, monthVal) {
  const card = $("weatherCurrentCard");
  if (!card) return;
  state.currentWeatherState = stateVal;
  state.currentWeatherMonth = monthVal;

  const cacheKey = `${stateVal}:${monthVal}`;
  card.classList.add('reveal-on-scroll');

  if (state.weatherCache[cacheKey]) {
    const cached = state.weatherCache[cacheKey];
    renderWeatherCard(cached);
    renderMonthStrip(cached.all_months, monthVal);
    return;
  }

  card.innerHTML = `<div class="loading-skeleton" aria-label="Loading weather data">
    <div class="skeleton-block tall"></div>
    <div class="skeleton-block short"></div>
    <div class="skeleton-block medium"></div>
    <div class="skeleton-block large"></div>
  </div>`;
  $("weatherFarmingAdvice")?.classList.add("d-none");

  try {
    const data = await postJSON("/api/weather", { state: stateVal, month: monthVal });
    if (data.error) {
      card.innerHTML = `<div class="weather-loading"><i class="bi bi-exclamation-triangle me-2"></i>${data.error}</div>`;
      return;
    }
    state.weatherCache[cacheKey] = data;
    renderWeatherCard(data);
    renderMonthStrip(data.all_months, data.month);
  } catch (err) {
    card.innerHTML = `<div class="weather-loading"><i class="bi bi-exclamation-triangle me-2"></i>${err.message}</div>`;
  }
}

function initWeather() {
  const curMonth = MONTHS[new Date().getMonth()];
  const monthSel = $("weatherMonth");
  if (monthSel) monthSel.value = curMonth;

  const stateVal = $("weatherState")?.value || "Maharashtra";
  loadWeather(stateVal, curMonth);

  $("weatherState")?.addEventListener("change", e => {
    loadWeather(e.target.value, $("weatherMonth")?.value || curMonth);
  });

  $("weatherMonth")?.addEventListener("change", e => {
    loadWeather($("weatherState")?.value || "Maharashtra", e.target.value);
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// MANDI PRICES  (static JSON via /api/mandi)
// ══════════════════════════════════════════════════════════════════════════════

function renderMandiResults(data) {
  const container = $("mandiResults");
  if (!container) return;

  if (data.error) { showError("mandiResults", data.error); return; }

  const disclaimer = `
    <div class="disclaimer-box mb-3">
      <i class="bi bi-info-circle-fill me-2"></i>
      <strong>Sample/Indicative prices</strong> — not live market data. Actual prices vary daily.
      ${data.disclaimer ? `<br><small class="text-muted">${data.disclaimer}</small>` : ""}
    </div>`;

  if (!data.success || !data.records?.length) {
    const avail = data.available?.length
      ? `<p class="mt-2 small text-muted">Available: ${data.available.join(", ")}</p>` : "";
    container.innerHTML = disclaimer + `<div class="error-box"><i class="bi bi-search me-2"></i>${data.message || "No records found."}</div>${avail}`;
    return;
  }

  const mspHtml = data.msp
    ? `<span class="msp-badge ms-2"><i class="bi bi-bank me-1"></i>MSP ₹${data.msp}/q</span>` : "";

  const seasonHtml = data.typical_season
    ? `<span class="text-muted small ms-2">• ${data.typical_season}</span>` : "";

  const s = data.stats || {};
  const statsHtml = s.avg_modal
    ? `<div class="mandi-stats-row mt-2">
         <div class="stat-chip"><div class="stat-value">₹${s.avg_modal}</div><div class="stat-label">Avg Modal</div></div>
         <div class="stat-chip"><div class="stat-value">₹${s.max_modal}</div><div class="stat-label">Highest</div></div>
         <div class="stat-chip"><div class="stat-value">₹${s.min_modal}</div><div class="stat-label">Lowest</div></div>
         <div class="stat-chip"><div class="stat-value">${data.record_count}</div><div class="stat-label">Markets</div></div>
       </div>` : "";

  const rows = data.records.map(r => `
    <tr>
      <td>${r.market}</td>
      <td>${r.district}, ${r.state}</td>
      <td>${r.variety || "—"}</td>
      <td>₹${r.min_price}</td>
      <td>₹${r.max_price}</td>
      <td><span class="price-badge">₹${r.modal_price}</span></td>
    </tr>`).join("");

  container.innerHTML = `
    ${disclaimer}
    <div class="mb-1 d-flex align-items-center flex-wrap gap-1">
      <strong>${data.commodity}</strong>${mspHtml}${seasonHtml}
    </div>
    ${statsHtml}
    <div class="mandi-table-wrapper mt-2">
      <table class="table-custom">
        <thead>
          <tr><th>Market</th><th>Location</th><th>Variety</th><th>Min (₹/q)</th><th>Max (₹/q)</th><th>Modal (₹/q)</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="disclaimer-box mt-2">
      <i class="bi bi-info-circle me-1"></i>Prices in ₹ per quintal (100 kg). For live prices visit <strong>enam.gov.in</strong> or your local APMC.
    </div>`;
}

function initMandi() {
  $("mandiSearchBtn")?.addEventListener("click", async () => {
    const commodity = $("mandiCommodity")?.value?.trim();
    const commodityInput = $("mandiCommodity");
    if (!commodity) {
      showToast("Missing selection", "Please select a commodity before looking up mandi prices.", "warning");
      markInvalid(commodityInput);
      return;
    }
    const stateVal = $("mandiState")?.value?.trim();

    showLoading("mandiResults", "Looking up prices…");
    try {
      const data = await postJSON("/api/mandi", { commodity, state: stateVal });
      renderMandiResults(data);
    } catch (err) {
      showError("mandiResults", err.message);
    }
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// CROP RECOMMENDATION (AI + PDF Download)
// ══════════════════════════════════════════════════════════════════════════════

function initCropRecommendation() {
  $("cropRecommendBtn")?.addEventListener("click", async () => {
    showLoading("cropResults", "Getting AI crop recommendation…");
    try {
      const data = await postJSON("/api/crop-recommendation", {
        season:    $("cropSeason")?.value,
        soil_type: $("cropSoil")?.value,
        location:  $("cropLocation")?.value,
        water:     $("cropWater")?.value,
        farm_size: $("cropFarmSize")?.value,
        simple_mode: state.simpleMode
      });
      
      const rec = data.recommendation || data.error || "No recommendation available.";
      
      $("cropResults").innerHTML = `
        <div class="result-panel">
          <div class="d-flex justify-content-between align-items-center mb-2 pb-2 border-bottom">
            <h6 class="mb-0 text-green"><i class="bi bi-stars me-2"></i>AI Crop Advisory</h6>
            <button class="btn btn-xs btn-msg-action btn-download-pdf" id="cropPdfBtn">
              <i class="bi bi-file-earmark-pdf"></i> Download PDF
            </button>
          </div>
          <div class="result-text">${mdToHtml(rec)}</div>
        </div>`;

      $("cropPdfBtn")?.addEventListener("click", () => {
        downloadAdvisoryPDF(rec, "Crop Recommendation");
      });
    } catch (err) {
      showError("cropResults", err.message);
    }
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// PEST & DISEASE HELP (AI + PDF Download)
// ══════════════════════════════════════════════════════════════════════════════

function initPestHelp() {
  document.querySelectorAll(".btn-symptom").forEach(btn => {
    btn.addEventListener("click", () => {
      const si = $("pestSymptoms");
      if (si) si.value = btn.dataset.symptom;
    });
  });

  $("pestDiagnoseBtn")?.addEventListener("click", async () => {
    const crop     = $("pestCrop")?.value?.trim();
    const symptoms = $("pestSymptoms")?.value?.trim();
    const cropInput = $("pestCrop");
    const symptomsInput = $("pestSymptoms");
    if (!crop && !symptoms) {
      showToast("Missing details", "Please enter at least the crop name or symptoms.", "warning");
      if (!crop) markInvalid(cropInput);
      if (!symptoms) markInvalid(symptomsInput);
      return;
    }

    showLoading("pestResults", "Diagnosing pest/disease…");
    try {
      const data = await postJSON("/api/pest-help", { crop, symptoms, simple_mode: state.simpleMode });
      const diagnosis = data.diagnosis || data.error || "No diagnosis available.";

      $("pestResults").innerHTML = `
        <div class="result-panel">
          <div class="d-flex justify-content-between align-items-center mb-2 pb-2 border-bottom">
            <h6 class="mb-0 text-green"><i class="bi bi-search-heart me-2"></i>IPM Diagnosis</h6>
            <button class="btn btn-xs btn-msg-action btn-download-pdf" id="pestPdfBtn">
              <i class="bi bi-file-earmark-pdf"></i> Download PDF
            </button>
          </div>
          <div class="result-text">${mdToHtml(diagnosis)}</div>
        </div>`;

      $("pestPdfBtn")?.addEventListener("click", () => {
        downloadAdvisoryPDF(diagnosis, "Pest & Disease Advisory");
      });
    } catch (err) {
      showError("pestResults", err.message);
    }
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// BUNDLED STATIC CROP CALENDAR
// ══════════════════════════════════════════════════════════════════════════════

let staticCropCalendar = [];

async function loadCropCalendar() {
  const container = $("cropCalendarContainer");
  if (!container) return;

  try {
    const res = await fetch("/static/data/crop_calendar.json");
    const data = await res.json();
    staticCropCalendar = data.crops || [];
    renderCropCalendar("all");
  } catch (err) {
    container.innerHTML = `<div class="text-danger small">Failed to load crop calendar: ${err.message}</div>`;
  }
}

function renderCropCalendar(seasonFilter = "all") {
  const container = $("cropCalendarContainer");
  if (!container) return;

  let crops = staticCropCalendar;
  if (seasonFilter !== "all") {
    crops = crops.filter(c => c.season.toLowerCase() === seasonFilter.toLowerCase());
  }

  if (crops.length === 0) {
    container.innerHTML = `<div class="text-muted small py-4 text-center">No crops found for the selected season.</div>`;
    return;
  }

  container.innerHTML = crops.map(c => {
    const mspText = c.msp ? `₹${c.msp}/qtl` : "No MSP support";
    return `
      <div class="crop-calendar-card">
        <div class="crop-header">
          <div class="crop-title-box">
            <span class="crop-emoji">${c.emoji || "🌱"}</span>
            <span class="crop-name">${c.name}</span>
          </div>
          <span class="crop-season-badge" style="background: rgba(16,185,129,0.12); color:#10b981;">
            ${c.season}
          </span>
        </div>
        <div class="crop-calendar-details">
          <div class="calendar-detail-item">
            <span class="calendar-detail-label">Sowing Period</span>
            <span class="calendar-detail-value text-green">${c.sow_label}</span>
          </div>
          <div class="calendar-detail-item">
            <span class="calendar-detail-label">Harvesting</span>
            <span class="calendar-detail-value text-amber">${c.harvest_label}</span>
          </div>
          <div class="calendar-detail-item">
            <span class="calendar-detail-label">MSP Rate</span>
            <span class="calendar-detail-value">${mspText}</span>
          </div>
          <div class="calendar-detail-item">
            <span class="calendar-detail-label">Best Soil</span>
            <span class="calendar-detail-value">${c.soil || "General loam"}</span>
          </div>
        </div>
        <div class="crop-timeline mt-2">
          <div class="crop-timeline-item">
            <span>States:</span>
            <strong class="text-secondary">${c.states}</strong>
          </div>
        </div>
        ${c.tip ? `<div class="crop-tip mt-2">💡 <strong>Tip:</strong> ${c.tip}</div>` : ""}
      </div>
    `;
  }).join("");
}

function initCropCalendarFilters() {
  document.querySelectorAll(".calendar-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".calendar-filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const season = btn.dataset.season;
      renderCropCalendar(season);
    });
  });
}

// ══════════════════════════════════════════════════════════════════════════════
// BUNDLED STATIC GOVERNMENT SCHEMES
// ══════════════════════════════════════════════════════════════════════════════

let staticSchemes = [];

async function loadGovernmentSchemes() {
  const container = $("schemesContainer");
  if (!container) return;

  try {
    const res = await fetch("/static/data/govt_schemes.json");
    const data = await res.json();
    staticSchemes = data.schemes || [];
    renderGovernmentSchemes("all");
  } catch (err) {
    container.innerHTML = `<div class="text-danger small">Failed to load government schemes: ${err.message}</div>`;
  }
}

function renderGovernmentSchemes(tagFilter = "all") {
  const container = $("schemesContainer");
  if (!container) return;

  let schemes = staticSchemes;
  if (tagFilter !== "all") {
    schemes = schemes.filter(s => s.tags.includes(tagFilter));
  }

  if (schemes.length === 0) {
    container.innerHTML = `<div class="text-muted small py-4 text-center">No government schemes found.</div>`;
    return;
  }

  container.innerHTML = schemes.map(s => {
    const portalUrl = s.portal ? `<a href="${s.portal}" target="_blank" class="btn btn-xs btn-outline-custom" style="text-decoration:none;"><i class="bi bi-box-arrow-up-right me-1"></i>Official Portal</a>` : "";
    return `
      <div class="scheme-card">
        <div class="scheme-icon-box">${s.icon || "🏛️"}</div>
        <div class="scheme-body">
          <div class="scheme-header-row">
            <h6 class="scheme-title">${s.name}</h6>
            <span class="scheme-ministry">${s.ministry}</span>
          </div>
          
          <!-- One-line Eligibility Summary highlighted as requested -->
          <div class="scheme-eligibility-summary">
            📋 Eligible: ${s.eligibility}
          </div>
          
          <div class="scheme-details-grid">
            <div class="scheme-detail-block">
              <div class="scheme-detail-title">🎁 Benefits</div>
              <div class="scheme-detail-content text-secondary">${s.benefit}</div>
            </div>
            <div class="scheme-detail-block">
              <div class="scheme-detail-title">📝 How to Apply &amp; Documents</div>
              <div class="scheme-detail-content text-secondary">${s.how_to_apply}</div>
            </div>
          </div>
          
          <div class="d-flex justify-content-between align-items-center mt-2 flex-wrap gap-2 pt-2 border-top border-secondary border-opacity-10">
            <div class="small text-muted">
              ${s.helpline ? `<i class="bi bi-telephone-outbound me-1"></i>Helpline: <strong>${s.helpline}</strong>` : ""}
            </div>
            <div>
              ${portalUrl}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function initSchemeFilters() {
  document.querySelectorAll(".scheme-tag").forEach(tag => {
    tag.addEventListener("click", () => {
      document.querySelectorAll(".scheme-tag").forEach(t => t.classList.remove("active"));
      tag.classList.add("active");
      const tagVal = tag.dataset.tag;
      renderGovernmentSchemes(tagVal);
    });
  });
}

function initRevealAnimations() {
  const revealItems = document.querySelectorAll('.reveal-on-scroll, .hero-reveal');
  if (!('IntersectionObserver' in window) || revealItems.length === 0) {
    revealItems.forEach(item => item.classList.add('is-visible'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.16, rootMargin: '0px 0px -20px 0px' });

  revealItems.forEach((item, index) => {
    item.style.transitionDelay = `${index * 70}ms`;
    observer.observe(item);
  });
}

function initHeroStagger() {
  const heroElements = document.querySelectorAll('.hero-badge, .hero-title, .hero-subtitle, .hero-greeting, .hero-quick-actions, .hero-stats-row');
  heroElements.forEach((element, index) => {
    element.classList.add('hero-reveal');
    element.style.transitionDelay = `${index * 80}ms`;
  });
  window.setTimeout(() => {
    heroElements.forEach(element => element.classList.add('is-visible'));
  }, 40);
}

function initSectionRevealEnhancements() {
  document.querySelectorAll('.panel-card, .scheme-card, .crop-calendar-card, .recent-questions-container, .result-panel').forEach((element, index) => {
    element.classList.add('reveal-on-scroll');
    element.style.transitionDelay = `${Math.min(index * 60, 240)}ms`;
  });
  initRevealAnimations();
}

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadFeedback();
  initDarkMode();
  initChat();
  initWeather();
  initMandi();
  initCropRecommendation();
  initPestHelp();
  checkHealth();
  
  // Initialize New Dashboard Features
  initFarmProfile();
  initRecentQuestions();
  initSimpleMode();
  
  // Load and render static datasets
  loadCropCalendar();
  initCropCalendarFilters();
  
  loadGovernmentSchemes();
  initSchemeFilters();

  initRevealAnimations();
  initHeroStagger();
  initSectionRevealEnhancements();

  // Make tabs sticky after scrolling past hero section
  const heroSection = document.querySelector('.hero-section');
  const tabsSection = document.querySelector('.chips-section');
  
  if (heroSection && tabsSection) {
    window.addEventListener('scroll', () => {
      const heroBottom = heroSection.getBoundingClientRect().bottom;
      if (heroBottom <= 70) {
        tabsSection.classList.add('sticky');
      } else {
        tabsSection.classList.remove('sticky');
      }
    });
  }

  // Ensure the correct initial tab panel is visible
  switchTab(state.activeTab);
  window.setTimeout(() => {
    if (state.activeTab === "tab-chat") {
      $("chatInput")?.focus({ preventScroll: true });
    }
  }, 220);

  setInterval(checkHealth, 30_000);
});
