var els = {};
var latestState = null;
var pollingTimer = null;
var eventsBound = false;

function bindElements() {
  var ids = [
    "usernameInput",
    "apikeyInput",
    "intervalInput",
    "timeoutInput",
    "profileCheck",
    "gamepageCheck",
    "achievementCheck",
    "devModeCheck",
    "discordDot",
    "discordStatus",
    "raDot",
    "raStatus",
    "roleBadge",
    "roleIcon",
    "roleLabel",
    "connectButton",
    "exitButton",
    "versionButton",
    "versionText",
    "updateButton",
    "logsButton",
    "messageModal",
    "messageTitle",
    "messageBody",
    "messageClose",
  ];
  for (var i = 0; i < ids.length; i += 1) {
    els[ids[i]] = document.getElementById(ids[i]);
  }
}

function setText(node, value) {
  if (node) {
    node.textContent = value == null ? "" : String(value);
  }
}

function showMessage(title, body) {
  setText(els.messageTitle, title || "CheevoPresence");
  setText(els.messageBody, body || "");
  if (els.messageModal) {
    els.messageModal.classList.remove("hidden");
  }
}

function hideMessage() {
  if (els.messageModal) {
    els.messageModal.classList.add("hidden");
  }
}

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
    if (xhr.readyState !== 4) {
      return;
    }
    try {
      payload = JSON.parse(xhr.responseText || "{}");
    } catch (_err) {
      payload = { ok: false, error: "Invalid settings response." };
    }
    if (xhr.status >= 200 && xhr.status < 300 && payload.ok) {
      if (onSuccess) {
        onSuccess(payload.result);
      }
      return;
    }
    if (onError) {
      onError(payload.error || "Settings request failed.");
    }
  };
  xhr.send(JSON.stringify(params || {}));
}

function valueOr(value, fallback) {
  return value === undefined || value === null ? fallback : value;
}

function formPayload() {
  return {
    username: els.usernameInput.value,
    apikey: els.apikeyInput.value,
    interval: parseInt(els.intervalInput.value, 10),
    timeout: parseInt(els.timeoutInput.value, 10),
    show_profile_button: els.profileCheck.checked,
    show_gamepage_button: els.gamepageCheck.checked,
    show_achievement_progress: els.achievementCheck.checked,
    dev_mode: els.devModeCheck.checked,
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
  els.devModeCheck.checked = !!config.dev_mode;
}

function statusClass(status, connected) {
  if (connected || status === "connected") {
    return "connected";
  }
  if (status === "connecting") {
    return "connecting";
  }
  if (status === "error") {
    return "error";
  }
  return "";
}

function applyDot(dot, valueClass) {
  dot.className = "dot";
  if (valueClass) {
    dot.classList.add(valueClass);
  }
}

function applyStatusText(wrapper, valueClass) {
  wrapper.classList.remove("connected");
  wrapper.classList.remove("error");
  if (valueClass === "connected" || valueClass === "error") {
    wrapper.classList.add(valueClass);
  }
}

function setControlsEnabled(enabled) {
  var inputs = [
    els.usernameInput,
    els.apikeyInput,
    els.intervalInput,
    els.timeoutInput,
    els.profileCheck,
    els.gamepageCheck,
    els.achievementCheck,
    els.devModeCheck,
  ];
  for (var i = 0; i < inputs.length; i += 1) {
    inputs[i].disabled = !enabled;
  }
}

function applyRole(worker, style) {
  var label = worker.ra_role_label || "";
  if (!worker.ra_connected || !label) {
    els.roleBadge.classList.add("hidden");
    return;
  }
  style = style || {};
  setText(els.roleLabel, label);
  els.roleBadge.style.color = style.accent || "#f0b450";
  els.roleBadge.style.background = style.fill || "rgba(231,163,58,.13)";
  els.roleBadge.style.borderColor = style.border || "rgba(231,163,58,.4)";
  els.roleIcon.className = "role-icon " + (style.icon || "code");
  els.roleBadge.classList.remove("hidden");
}

function applyConnectionButton(state) {
  var worker = state.worker || {};
  if (worker.running) {
    els.connectButton.classList.add("disconnect");
  } else {
    els.connectButton.classList.remove("disconnect");
  }
  if (state.is_connecting) {
    setText(els.connectButton, "Connecting...");
    els.connectButton.disabled = true;
  } else if (worker.is_stopping) {
    setText(els.connectButton, "Stopping...");
    els.connectButton.disabled = true;
  } else if (worker.running) {
    setText(els.connectButton, "Disconnect");
    els.connectButton.disabled = false;
  } else {
    setText(els.connectButton, "Connect");
    els.connectButton.disabled = false;
  }
}

function applyUpdate(state) {
  var update = state.update_status || {};
  setText(els.versionText, state.app_version || "");
  if (update.available) {
    setText(els.updateButton, update.can_self_install ? "Update available" : "New version available");
    els.updateButton.classList.remove("hidden");
    els.versionButton.classList.add("update");
  } else {
    els.updateButton.classList.add("hidden");
    els.versionButton.classList.remove("update");
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
  applyRole(worker, state.role_style);
  applyConnectionButton(state);
  applyUpdate(state);
  setControlsEnabled(!worker.is_busy && !state.is_connecting);
}

function refreshState() {
  request(
    "get_state",
    {},
    function (state) {
      applyState(state);
    },
    function () {
      window.clearInterval(pollingTimer);
      showMessage("Connection Lost", "The CheevoPresence background app is no longer available.");
    }
  );
}

function loadConfig() {
  request(
    "load_config",
    {},
    function (payload) {
      applyConfig(payload.config || {});
      applyState(payload.state || {});
    },
    function (err) {
      handleError("Startup Failed", err);
    }
  );
}

function toggleConnection() {
  if (latestState && latestState.worker && latestState.worker.running) {
    request(
      "disconnect",
      {},
      function (result) {
        if (result.state) {
          applyState(result.state);
        } else {
          refreshState();
        }
      },
      function (err) {
        handleError("Disconnect Failed", err);
      }
    );
    return;
  }

  els.connectButton.disabled = true;
  setText(els.connectButton, "Connecting...");
  request(
    "connect",
    { payload: formPayload() },
    function (result) {
      if (result.warning_message) {
        showMessage(result.warning_title || "Warning", result.warning_message);
      }
      if (!result.success) {
        showMessage(result.error_title || "Connection Failed", result.error_message || "Could not connect.");
      }
      if (result.config) {
        applyConfig(result.config);
      }
      if (result.state) {
        applyState(result.state);
      } else {
        refreshState();
      }
    },
    function (err) {
      handleError("Connection Failed", err);
      els.connectButton.disabled = false;
    }
  );
}

function installUpdate() {
  if (!latestState || !latestState.update_status || !latestState.update_status.available) {
    return;
  }
  var update = latestState.update_status;
  if (!update.can_self_install && update.release_url) {
    request("open_url", { target: "github" });
    return;
  }
  setText(els.updateButton, "Downloading update...");
  request(
    "install_update",
    {},
    function (result) {
      if (result && !result.success) {
        showMessage(result.error_title || "Update Failed", result.error_message || "Could not install the update.");
        if (result.state) {
          applyState(result.state);
        }
      }
    },
    function (err) {
      handleError("Update Failed", err);
    }
  );
}

function bindEvents() {
  if (eventsBound) {
    return;
  }
  eventsBound = true;
  els.connectButton.addEventListener("click", toggleConnection);
  els.exitButton.addEventListener("click", function () {
    request("exit_app", {});
  });
  els.logsButton.addEventListener("click", function () {
    request(
      "open_logs",
      {},
      function (result) {
        if (!result.success) {
          showMessage("Logs", "Log folder:\n" + (result.path || ""));
        }
      },
      function (err) {
        handleError("Logs", err);
      }
    );
  });
  els.updateButton.addEventListener("click", installUpdate);
  els.versionButton.addEventListener("click", installUpdate);
  els.messageClose.addEventListener("click", hideMessage);

  var linkButtons = document.querySelectorAll("[data-link]");
  for (var i = 0; i < linkButtons.length; i += 1) {
    linkButtons[i].addEventListener("click", function () {
      request("open_url", { target: this.getAttribute("data-link") });
    });
  }
}

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
