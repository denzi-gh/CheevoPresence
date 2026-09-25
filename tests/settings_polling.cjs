const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const script = fs.readFileSync(path.join(__dirname, "../desktop/shell/web_assets/settings.js"), "utf8");

function element() {
  const classes = new Set();
  return {
    textContent: "", style: {}, children: [], validity: { valid: true },
    parentElement: { classList: { add() {}, remove() {} } },
    classList: {
      add(value) { classes.add(value); },
      remove(value) { classes.delete(value); },
      contains(value) { return classes.has(value); },
      toggle(value, enabled) { if (enabled) { classes.add(value); } else { classes.delete(value); } },
    },
    set innerHTML(_value) { this.children = []; },
    appendChild(child) { this.children.push(child); },
    setAttribute() {}, removeAttribute() {}, addEventListener() {},
  };
}

function state(title) {
  return {
    worker: {
      running: true, is_busy: true, ra_connected: true, current_status: "connected",
      status_text: "Playing: " + title,
      mirrored_presence: { title, details: "Playing", buttons: [], achievement_total: 10 },
    },
    update_status: {},
  };
}

function page() {
  const nodes = new Map();
  const timers = new Map();
  const calls = [];
  let nextTimer = 1;
  class XMLHttpRequest {
    open(_method, url) { this.url = url; }
    setRequestHeader() {}
    send() { calls.push(this); }
    respond(status, result) {
      this.status = status;
      this.responseText = JSON.stringify(status === 200 ? { ok: true, result } : { ok: false });
      this.readyState = 4;
      this.onreadystatechange();
    }
  }
  const context = vm.createContext({
    XMLHttpRequest,
    document: {
      readyState: "loading", addEventListener() {}, querySelectorAll() { return []; },
      getElementById(id) {
        if (!nodes.has(id)) { nodes.set(id, element()); }
        return nodes.get(id);
      },
      createElement: element,
    },
    window: {
      addEventListener() {},
      setInterval(callback) { const id = nextTimer++; timers.set(id, callback); return id; },
      clearInterval(id) { timers.delete(id); },
    },
  });
  vm.runInContext(script, context);
  context.init();
  calls.shift().respond(200, { config: {}, state: state("WarioWare") });
  return {
    context, nodes, calls,
    tick() { for (const callback of timers.values()) { callback(); } },
    reply(status, title) { calls.shift().respond(status, state(title)); },
  };
}

test("preview recovers after a failed local request and continues to track game changes", () => {
  const ui = page();
  assert.equal(ui.nodes.get("mirrorTitle").textContent, "WarioWare");
  ui.tick();
  ui.reply(500);
  assert.equal(ui.nodes.get("messageModal").classList.contains("hidden"), false);
  ui.tick();
  assert.equal(ui.calls.length, 1, "refresh must continue after failure");
  ui.reply(200, "Mario Kart Wii");
  assert.equal(ui.nodes.get("mirrorTitle").textContent, "Mario Kart Wii");
  assert.equal(ui.nodes.get("messageModal").classList.contains("hidden"), true);
  ui.tick();
  ui.reply(200, "Newer: Falling Leaf");
  assert.equal(ui.nodes.get("mirrorTitle").textContent, "Newer: Falling Leaf");
});

test("slow state requests do not overlap and a timeout permits another refresh", () => {
  const ui = page();
  ui.tick();
  ui.tick();
  ui.tick();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.calls[0].timeout, 5000);
  ui.reply(0);
  ui.tick();
  assert.equal(ui.calls.length, 1);
  ui.reply(200, "Recovered Game");
  assert.equal(ui.nodes.get("mirrorTitle").textContent, "Recovered Game");
});

test("repeated failures do not reopen a dismissed message", () => {
  const ui = page();
  ui.tick();
  ui.reply(500);
  ui.context.hideMessage();
  ui.tick();
  ui.reply(500);
  assert.equal(ui.nodes.get("messageModal").classList.contains("hidden"), true);
  ui.tick();
  ui.reply(200, "Recovered Game");
  ui.tick();
  ui.reply(500);
  assert.equal(ui.nodes.get("messageModal").classList.contains("hidden"), false);
});

test("recovery preserves an unrelated dialog and command requests have no polling timeout", () => {
  const ui = page();
  ui.tick();
  ui.reply(500);
  ui.context.showMessage("Diagnostics", "Keep this open");
  ui.tick();
  ui.reply(200, "Recovered Game");
  assert.equal(ui.nodes.get("messageTitle").textContent, "Diagnostics");
  assert.equal(ui.nodes.get("messageModal").classList.contains("hidden"), false);
  ui.context.request("connect", {});
  assert.equal(ui.calls[0].timeout, undefined);
});
