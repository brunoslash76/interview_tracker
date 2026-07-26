#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class ClassList {
  constructor() {
    this.values = new Set();
  }
  add(value) {
    this.values.add(value);
  }
  remove(value) {
    this.values.delete(value);
  }
  contains(value) {
    return this.values.has(value);
  }
  toggle(value, force) {
    if (force === true) this.values.add(value);
    else if (force === false) this.values.delete(value);
    else if (this.values.has(value)) this.values.delete(value);
    else this.values.add(value);
  }
}

class Element {
  constructor(id = "") {
    this.id = id;
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.hidden = false;
    this.dataset = {};
    this.options = [];
    this.classList = new ClassList();
    this.attributes = new Map();
    this.listeners = new Map();
    this.onclick = null;
  }
  set innerHTML(value) {
    this._innerHTML = value;
  }
  get innerHTML() {
    return this._innerHTML || "";
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.get(name) || null;
  }
  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }
  dispatch(name, event = {}) {
    const callback = this.listeners.get(name);
    if (callback) callback(event);
  }
  insertAdjacentHTML() {}
  querySelector() {
    return new Element();
  }
  scrollIntoView() {}
  remove(index) {
    this.options.splice(index, 1);
  }
}

function extractDashboardScript(html) {
  const matches = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  assert.ok(matches.length >= 1, "expected an inline application script");
  return matches[matches.length - 1][1];
}

function createHarness() {
  const html = fs
    .readFileSync(process.argv[2], "utf8")
    .replace("__DATA_JSON__", "[]")
    .replace("__CSRF_TOKEN__", "component-test-token")
    .replaceAll("__MAX_SCAN_TIMES__", "5");
  const elements = new Map();
  const getElement = (id) => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  getElement("interview-data").textContent = "[]";
  getElement("csrfToken").value = "component-test-token";
  getElement("fPer").value = "10";

  const documentElement = new Element("html");
  const document = {
    documentElement,
    getElementById: getElement,
    querySelectorAll: () => [],
    querySelector: () => new Element(),
    createElement: () => new Element(),
    addEventListener: () => {},
  };

  const requests = [];
  let statusReads = 0;
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === "/api/scan") {
      return { ok: true, status: 202, json: async () => ({ status: { state: "running" } }) };
    }
    if (url === "/api/scan/status") {
      statusReads += 1;
      const state = statusReads === 1 ? "idle" : "running";
      return { ok: true, status: 200, json: async () => ({ state, phase: state }) };
    }
    if (url === "/api/dashboard-data") {
      return { ok: true, status: 200, json: async () => ({ records: [] }) };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  let intervalId = 0;
  const context = {
    console,
    document,
    fetch,
    window: {
      matchMedia: () => ({ matches: false }),
      scrollTo: () => {},
      open: () => {},
    },
    setInterval: () => ++intervalId,
    clearInterval: () => {},
    Date,
    Math,
    JSON,
    Promise,
  };
  vm.runInNewContext(extractDashboardScript(html), context, {
    filename: "dashboard_template.inline.js",
  });
  return { getElement, requests, documentElement };
}

async function flushPromises() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  const scenario = process.argv[3];
  const { getElement, requests, documentElement } = createHarness();
  await flushPromises();

  if (scenario === "theme") {
    const theme = getElement("theme");
    assert.equal(typeof theme.onclick, "function", "theme click handler should be wired");
    assert.equal(getElement("themeLabel").textContent, "Dark");
    theme.onclick();
    assert.equal(getElement("themeLabel").textContent, "Light");
    assert.equal(documentElement.getAttribute("data-theme"), "dark");
    assert.equal(
      getElement("themeIcon").textContent,
      "☀️",
      "theme icon should reflect dark mode"
    );
    assert.equal(
      getElement("themeLabel").textContent,
      "Light",
      "theme label should offer the opposite mode"
    );
    return;
  }

  if (scenario === "scan") {
    const button = getElement("scanNow");
    assert.equal(typeof button.onclick, "function", "scan click handler should be wired");
    button.onclick();
    await flushPromises();

    const post = requests.find(
      (request) => request.url === "/api/scan" && request.options.method === "POST"
    );
    assert.ok(post, "scan click should POST /api/scan");
    assert.equal(post.options.headers["X-CSRF-Token"], "component-test-token");
    assert.equal(getElement("scanModal").classList.contains("open"), true);
    assert.equal(button.disabled, true);
    return;
  }

  if (scenario === "settings-theme") {
    const theme = getElement("theme");
    assert.equal(theme.listeners.has("click"), true, "settings theme handler should be wired");
    assert.equal(getElement("themeLabel").textContent, "Dark");
    theme.dispatch("click");
    assert.equal(documentElement.getAttribute("data-theme"), "dark");
    assert.equal(getElement("themeIcon").textContent, "☀️");
    assert.equal(getElement("themeLabel").textContent, "Light");
    return;
  }

  throw new Error(`unknown scenario: ${scenario}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
