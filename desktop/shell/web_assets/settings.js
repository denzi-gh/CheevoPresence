/* Sidebar settings UI over the local web_settings.py API. */

var els = {};
var latestState = null;
var pollingTimer = null;
var logsTimer = null;
var eventsBound = false;
var activeScreen = "status";
var saveTimer = null;
var apiKeyVisible = false;

function bindElements() {
  var ids = [
    "usernameInput", "apikeyInput", "revealKey",
    "intervalInput", "timeoutInput",
    "profileCheck", "gamepageCheck", "achievementCheck", "bootCheck",
    "devActivityCheck",
    "discordDot", "discordStatus", "raDot", "raStatus",
    "roleBadge", "roleIcon", "roleLabel",
    "roleBadgeDev", "roleIconDev", "roleLabelDev",
    "mirrorCard", "mirrorTitle", "mirrorSub",
    "connectButton", "exitButton",
    "versionText", "versionTextAbout", "versionPill",
    "updateButton", "updateLabel",
    "navRadev", "devGroupLabel",
    "logPane", "logPath", "logLevel", "openLogsBtn", "copyDiagBtn", "aboutLogsBtn",
    "messageModal", "messageTitle", "messageBody", "messageClose"
  ];
  for (var i = 0; i < ids.length; i += 1) {
    els[ids[i]] = document.getElementById(ids[i]);
  }
  els.navItems = document.querySelectorAll(".nav-item");
  els.screens = document.querySelectorAll(".screen");
  els.linkButtons = document.querySelectorAll("[data-link]");
}

/* Small DOM helpers. */
function setText(node, value) {
  if (node) { node.textContent = value == null ? "" : String(value); }
}
function show(node) { if (node) { node.classList.remove("hidden"); } }
function hide(node) { if (node) { node.classList.add("hidden"); } }

function showMessage(title, body) {
  setText(els.messageTitle, title || "CheevoPresence");
  setText(els.messageBody, body || "");
  show(els.messageModal);
}
function hideMessage() { hide(els.messageModal); }
function handleError(title, err) {
  var message = err && err.message ? err.message : String(err || "The requested action could not be completed.");
  showMessage(title, message);
}

function request(method, params, onSuccess, onError) {
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/" + method, true);
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.setRequestHeader("X-Cheevo-Token", window.CHEEVO_API_TOKEN || "");
  xhr.onreadystatechange = function () {
    var payload;
    if (xhr.readyState !== 4) { return; }
    try { payload = JSON.parse(xhr.responseText || "{}"); }
    catch (_err) { payload = { ok: false, error: "Invalid settings response." }; }
    if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
      if (onSuccess) { onSuccess(payload.result); }
      return;
    }
    if (onError) { onError(payload.error || "Settings request failed."); }
  };
  xhr.send(JSON.stringify(params || {}));
}

function valueOr(value, fallback) {
  return value === undefined || value === null ? fallback : value;
}

/* Sidebar navigation. */
function showScreen(name) {
  activeScreen = name;
  var i;
  for (i = 0; i < els.screens.length; i += 1) {
    els.screens[i].classList.toggle("active", els.screens[i].getAttribute("data-screen") === name);
  }
  for (i = 0; i < els.navItems.length; i += 1) {
    els.navItems[i].classList.toggle("active", els.navItems[i].getAttribute("data-screen") === name);
  }
  if (name === "logs") { loadLogs(); startLogsPolling(); }
  else { stopLogsPolling(); }
}

/* Config form mapping. */
function formPayload() {
  return {
    username: els.usernameInput.value,
    apikey: els.apikeyInput.value,
    interval: parseInt(els.intervalInput.value, 10),
    timeout: parseInt(els.timeoutInput.value, 10),
    show_profile_button: els.profileCheck.checked,
    show_gamepage_button: els.gamepageCheck.checked,
    show_achievement_progress: els.achievementCheck.checked,
    start_on_boot: els.bootCheck.checked,
    /* Reuses the existing developer-title setting. */
    use_retroachievements_developer_titles: els.devActivityCheck.checked
  };
}

function applyConfig(config) {
  config = config || {};
  els.usernameInput.value = config.username || "";
  els.apikeyInput.value = config.apikey || "";
  els.intervalInput.value = valueOr(config.interval, 5);
  els.timeoutInput.value = valueOr(config.timeout, 130);
  els.profileCheck.checked = !!config.show_profile_button;
  els.gamepageCheck.checked = !!config.show_gamepage_button;
  els.achievementCheck.checked = !!config.show_achievement_progress;
  els.bootCheck.checked = !!config.start_on_boot;
  els.devActivityCheck.checked = !!config.use_retroachievements_developer_titles;
}

/* Debounce autosave so toggles feel instant. */
function scheduleSave() {
  if (saveTimer) { window.clearTimeout(saveTimer); }
  saveTimer = window.setTimeout(function () {
    request("save_config", { payload: formPayload() }, null, function () { /* Keep the UI moving. */ });
  }, 400);
}

/* Status rendering. */
function statusClass(status, connected) {
  if (connected || status === "connected") { return "connected"; }
  if (status === "connecting") { return "connecting"; }
  if (status === "error") { return "error"; }
  return "";
}
function applyDot(dot, valueClass) {
  dot.className = "dot";
  if (valueClass) { dot.classList.add(valueClass); }
}
function applyStatusText(wrapper, valueClass) {
  wrapper.classList.remove("connected");
  wrapper.classList.remove("error");
  if (valueClass === "connected" || valueClass === "error") { wrapper.classList.add(valueClass); }
}

function setControlsEnabled(enabled) {
  var inputs = [
    els.usernameInput, els.apikeyInput, els.intervalInput, els.timeoutInput,
    els.profileCheck, els.gamepageCheck, els.achievementCheck, els.bootCheck,
    els.devActivityCheck
  ];
  for (var i = 0; i < inputs.length; i += 1) { inputs[i].disabled = !enabled; }
}

function applyRoleBadge(badge, icon, label, worker, style) {
  var text = worker.ra_role_label || "";
  if (!worker.ra_connected || !text) { hide(badge); return; }
  style = style || {};
  setText(label, text);
  badge.style.color = style.accent || "#f0b450";
  badge.style.background = style.fill || "rgba(231,163,58,.13)";
  badge.style.borderColor = style.border || "rgba(231,163,58,.4)";
  icon.className = "role-icon " + (style.icon || "code");
  show(badge);
}

/* RA dev settings unlock from the account role. */
function devUnlocked(worker) {
  if (!worker) { return false; }
  if (typeof worker.ra_permissions === "number") { return worker.ra_permissions > 1; }
  return !!worker.ra_role_tier;
}

function applyDevGating(worker) {
  var unlocked = devUnlocked(worker);
  els.navRadev.classList.toggle("hidden", !unlocked);
  els.devGroupLabel.classList.toggle("hidden", !unlocked);
  if (!unlocked && activeScreen === "radev") { showScreen("status"); }
}

function applyMirror(worker) {
  /* Prefer richer fields if the backend adds them later. */
  if (worker.running && worker.game_title) {
    setText(els.mirrorTitle, worker.game_title);
    var parts = [];
    if (worker.console) { parts.push(worker.console); }
    if (typeof worker.total === "number") {
      parts.push((worker.earned || 0) + " / " + worker.total + " achievements");
    }
    setText(els.mirrorSub, parts.join(" \u00b7 "));
    show(els.mirrorCard);
  } else if (worker.running && worker.status_text) {
    setText(els.mirrorTitle, worker.status_text);
    setText(els.mirrorSub, "");
    show(els.mirrorCard);
  } else {
    hide(els.mirrorCard);
  }
}

function applyConnectionButton(state) {
  var worker = state.worker || {};
  if (state.is_connecting) {
    setText(els.connectButton, "Connecting..."); els.connectButton.disabled = true;
  } else if (worker.is_stopping) {
    setText(els.connectButton, "Stopping..."); els.connectButton.disabled = true;
  } else if (worker.running) {
    setText(els.connectButton, "Disconnect"); els.connectButton.disabled = false;
  } else {
    setText(els.connectButton, "Connect"); els.connectButton.disabled = false;
  }
}

function applyUpdate(state) {
  var update = state.update_status || {};
  setText(els.versionText, state.app_version || "");
  setText(els.versionTextAbout, state.app_version || "");
  if (update.available) {
    setText(els.updateLabel, update.can_self_install ? "Update available" : "New version available");
    show(els.updateButton);
    els.versionPill.classList.add("update");
  } else {
    hide(els.updateButton);
    els.versionPill.classList.remove("update");
  }
}

function applyState(state) {
  latestState = state;
  var worker = state.worker || {};
  var discordClass = statusClass(worker.current_status, false);
  var raClass = statusClass(worker.ra_connected ? "connected" : "error", worker.ra_connected);

  setText(els.discordStatus, worker.status_text || "Not running");
  setText(els.raStatus, worker.ra_status_text || "Not connected to RetroAchievements");
  applyDot(els.discordDot, discordClass);
  applyDot(els.raDot, raClass);
  applyStatusText(els.discordStatus.parentElement, discordClass);
  applyStatusText(els.raStatus.parentElement, raClass);

  applyRoleBadge(els.roleBadge, els.roleIcon, els.roleLabel, worker, state.role_style);
  applyRoleBadge(els.roleBadgeDev, els.roleIconDev, els.roleLabelDev, worker, state.role_style);
  applyDevGating(worker);
  applyMirror(worker);
  applyConnectionButton(state);
  applyUpdate(state);
  setControlsEnabled(!worker.is_busy && !state.is_connecting);
}

/* Poll app state. */
function refreshState() {
  request("get_state", {}, function (state) { applyState(state); }, function () {
    window.clearInterval(pollingTimer);
    showMessage("Connection Lost", "The CheevoPresence background app is no longer available.");
  });
}

function loadConfig() {
  request("load_config", {}, function (payload) {
    applyConfig(payload.config || {});
    applyState(payload.state || {});
  }, function (err) { handleError("Startup Failed", err); });
}

/* Connect and disconnect. */
function toggleConnection() {
  if (latestState && latestState.worker && latestState.worker.running) {
    request("disconnect", {}, function (result) {
      if (result.state) { applyState(result.state); } else { refreshState(); }
    }, function (err) { handleError("Disconnect Failed", err); });
    return;
  }
  els.connectButton.disabled = true;
  setText(els.connectButton, "Connecting...");
  request("connect", { payload: formPayload() }, function (result) {
    if (result.warning_message) { showMessage(result.warning_title || "Warning", result.warning_message); }
    if (!result.success) { showMessage(result.error_title || "Connection Failed", result.error_message || "Could not connect."); }
    if (result.config) { applyConfig(result.config); }
    if (result.state) { applyState(result.state); } else { refreshState(); }
  }, function (err) {
    handleError("Connection Failed", err);
    els.connectButton.disabled = false;
  });
}

/* Updates. */
function installUpdate() {
  if (!latestState || !latestState.update_status || !latestState.update_status.available) { return; }
  var update = latestState.update_status;
  if (!update.can_self_install && update.release_url) { request("open_url", { target: "github" }); return; }
  setText(els.updateLabel, "Downloading update...");
  request("install_update", {}, function (result) {
    if (result && !result.success) {
      showMessage(result.error_title || "Update Failed", result.error_message || "Could not install the update.");
      if (result.state) { applyState(result.state); }
    }
  }, function (err) { handleError("Update Failed", err); });
}

/* Logs screen. */
function renderLogLines(lines) {
  if (!lines || !lines.length) { els.logPane.textContent = "No log output yet."; return; }
  els.logPane.textContent = lines.join("\n");
  els.logPane.scrollTop = els.logPane.scrollHeight;
}

function loadLogs() {
  request("tail_logs", { lines: 200 }, function (result) {
    result = result || {};
    renderLogLines(result.lines);
    if (result.path) { setText(els.logPath, result.path); }
    if (result.level && els.logLevel) { els.logLevel.value = result.level; }
  }, function () {
    /* Older backend fallback. */
    els.logPane.textContent = "Live log tail is not available yet.\nUse \u201cOpen logs folder\u201d to view cheevo.log.";
  });
}

function startLogsPolling() {
  stopLogsPolling();
  logsTimer = window.setInterval(loadLogs, 2000);
}
function stopLogsPolling() {
  if (logsTimer) { window.clearInterval(logsTimer); logsTimer = null; }
}

function copyDiagnostics() {
  request("copy_diagnostics", {}, function (result) {
    var text = (result && result.text) || "";
    if (text && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showMessage("Diagnostics", "Diagnostics copied to clipboard.");
      }, function () {
        showMessage("Diagnostics", text);
      });
    } else if (result && result.copied) {
      showMessage("Diagnostics", "Diagnostics copied to clipboard.");
    } else {
      showMessage("Diagnostics", text || "Diagnostics are not available yet.");
    }
  }, function () {
    showMessage("Diagnostics", "Diagnostics are not available yet.");
  });
}

/* Wire events once. */
function bindEvents() {
  if (eventsBound) { return; }
  eventsBound = true;

  var i;
  for (i = 0; i < els.navItems.length; i += 1) {
    els.navItems[i].addEventListener("click", function () {
      showScreen(this.getAttribute("data-screen"));
    });
  }

  els.connectButton.addEventListener("click", toggleConnection);
  els.exitButton.addEventListener("click", function () { request("exit_app", {}); });

  els.revealKey.addEventListener("click", function () {
    apiKeyVisible = !apiKeyVisible;
    els.apikeyInput.type = apiKeyVisible ? "text" : "password";
    setText(els.revealKey, apiKeyVisible ? "Hide" : "Reveal");
  });

  /* Autosave non-credential settings. */
  var autosaveInputs = [
    els.intervalInput, els.timeoutInput, els.profileCheck, els.gamepageCheck,
    els.achievementCheck, els.bootCheck, els.devActivityCheck
  ];
  for (i = 0; i < autosaveInputs.length; i += 1) {
    autosaveInputs[i].addEventListener("change", scheduleSave);
  }

  els.openLogsBtn.addEventListener("click", openLogs);
  els.aboutLogsBtn.addEventListener("click", openLogs);
  els.copyDiagBtn.addEventListener("click", copyDiagnostics);
  els.logLevel.addEventListener("change", function () {
    request("set_log_level", { level: els.logLevel.value }, null, function () { /* Keep the UI moving. */ });
  });

  els.updateButton.addEventListener("click", installUpdate);
  els.versionPill.addEventListener("click", installUpdate);
  els.messageClose.addEventListener("click", hideMessage);

  for (i = 0; i < els.linkButtons.length; i += 1) {
    els.linkButtons[i].addEventListener("click", function () {
      request("open_url", { target: this.getAttribute("data-link") });
    });
  }
}

function openLogs() {
  request("open_logs", {}, function (result) {
    if (!result.success) { showMessage("Logs", "Log folder:\n" + (result.path || "")); }
  }, function (err) { handleError("Logs", err); });
}

/* Boot the page. */
function init() {
  bindElements();
  bindEvents();
  loadConfig();
  pollingTimer = window.setInterval(refreshState, 1000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
