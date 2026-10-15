"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

let state = null;
let dirty = false;
let selectedTask = 0;
let currentFileName = null;
let currentTmpPath = null;
let currentSavedPath = null;
let activeTab = "settings";
let runRunning = false;
let runOffset = 0;
let runPending = "";
let runPollTimer = null;

function newConfig() {
  return normalizeConfig({
    name: "my-run",
    version: "1.0",
    llm: {
      openAiCompatibleServerUrl: "http://localhost:8080/v1",
      model: "",
      "api-key": "not-needed",
      mcpTools: [],
    },
    tasks: [{ name: "task-01", prompt: "", tools: [] }],
  });
}

const SAMPLING_NUMERIC_FIELDS = [
  "temperature",
  "top_p",
  "top_k",
  "min_p",
  "repeat_penalty",
  "presence_penalty",
];
const SAMPLING_FIELDS = [...SAMPLING_NUMERIC_FIELDS, "reasoning_effort"];
const REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh"];

function normalizeSampling(raw) {
  const s = raw || {};
  const out = {};
  SAMPLING_FIELDS.forEach((k) => {
    const v = s[k];
    out[k] =
      v === null || v === undefined || v === ""
        ? null
        : k === "reasoning_effort"
          ? String(v)
          : Number(v);
  });
  return out;
}

function normalizeConfig(raw) {
  const llm = raw.llm || {};
  return {
    name: raw.name ?? "",
    version: raw.version ?? "",
    llm: {
      openAiCompatibleServerUrl: llm.openAiCompatibleServerUrl ?? "",
      model: llm.model ?? "",
      apiKey: llm["api-key"] ?? "not-needed",
      systemMessage: llm.systemMessage ?? "",
      stream: llm.stream !== false,
      maxToolResultLength: Number(llm.maxToolResultLength ?? 120000),
      mcpTools: (llm.mcpTools || []).map((t) => ({
        name: t.name ?? "",
        endpoint: t.endpoint ?? "",
      })),
      sampling: normalizeSampling(llm.sampling),
    },
    tasks: (raw.tasks || []).map((t) => ({
      name: t.name ?? "",
      prompt: t.prompt ?? "",
      tools: [...(t.tools || [])],
    })),
  };
}

function serialize() {
  const out = {};
  if (state.name) out.name = state.name;
  if (state.version) out.version = state.version;
  const llm = {
    openAiCompatibleServerUrl: state.llm.openAiCompatibleServerUrl,
    model: state.llm.model,
  };
  if (state.llm.apiKey) llm["api-key"] = state.llm.apiKey;
  if (state.llm.systemMessage) llm.systemMessage = state.llm.systemMessage;
  llm.stream = state.llm.stream;
  llm.maxToolResultLength = state.llm.maxToolResultLength;
  llm.mcpTools = state.llm.mcpTools.map((t) => ({
    name: t.name,
    endpoint: t.endpoint,
  }));
  const sampling = {};
  SAMPLING_FIELDS.forEach((k) => {
    const v = state.llm.sampling[k];
    if (v !== null && v !== "" && !(typeof v === "number" && Number.isNaN(v))) {
      sampling[k] = v;
    }
  });
  if (Object.keys(sampling).length) llm.sampling = sampling;
  out.llm = llm;
  out.tasks = state.tasks.map((t) => ({
    name: t.name,
    prompt: t.prompt,
    tools: [...t.tools],
  }));
  return out;
}

function markDirty() {
  dirty = true;
  renderPreview();
}

function setStatus(msg, kind) {
  const el = $("#status");
  el.textContent = msg;
  el.className = "status" + (kind ? " " + kind : "");
}

function validate() {
  const errors = [];
  const warnings = [];
  if (!state.llm.openAiCompatibleServerUrl.trim())
    errors.push("LLM server URL is required.");
  if (!state.llm.model.trim()) errors.push("LLM model is required.");
  SAMPLING_NUMERIC_FIELDS.forEach((k) => {
    const v = state.llm.sampling[k];
    if (v !== null && Number.isNaN(v)) errors.push(`Sampling "${k}" must be a number.`);
  });
  const effort = state.llm.sampling.reasoning_effort;
  if (effort !== null && !REASONING_EFFORTS.includes(effort)) {
    errors.push(`Sampling "reasoning_effort" must be one of: ${REASONING_EFFORTS.join(", ")}.`);
  }
  const names = [];
  state.llm.mcpTools.forEach((t, i) => {
    if (!t.name.trim()) errors.push(`MCP server #${i + 1}: name is required.`);
    if (!t.endpoint.trim()) errors.push(`MCP server #${i + 1}: endpoint is required.`);
    if (names.includes(t.name)) errors.push(`MCP server name "${t.name}" is duplicated.`);
    names.push(t.name);
  });
  const seenTaskNames = new Set();
  state.tasks.forEach((t, i) => {
    if (!t.name.trim()) errors.push(`Task ${i + 1}: name is required.`);
    if (seenTaskNames.has(t.name)) errors.push(`Task name "${t.name}" is duplicated.`);
    seenTaskNames.add(t.name);
    if (!t.prompt.trim()) errors.push(`Task ${i + 1}: prompt is required.`);
    t.tools.forEach((tool) => {
      if (!names.includes(tool))
        warnings.push(`Task ${i + 1} enables unknown tool "${tool}".`);
    });
  });
  if (!state.tasks.length) warnings.push("No tasks defined.");
  return { errors, warnings };
}

function renderPreview() {
  const { errors, warnings } = validate();
  if (errors.length) {
    setStatus(`✖ ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1} more)` : ""}`, "error");
  } else if (warnings.length) {
    setStatus(`⚠ ${warnings[0]}${warnings.length > 1 ? ` (+${warnings.length - 1} more)` : ""}`, "warn");
  } else if (dirty) {
    setStatus("● Unsaved changes", "dirty");
  } else {
    setStatus("Valid", "ok");
  }
  updateRunButtons();
}

function bindSimple() {
  const bind = (id, set) => {
    $(id).addEventListener("input", (e) => {
      set(e.target);
      markDirty();
    });
  };
  bind("#f-name", (el) => (state.name = el.value));
  bind("#f-version", (el) => (state.version = el.value));
  bind("#f-url", (el) => (state.llm.openAiCompatibleServerUrl = el.value));
  bind("#f-model", (el) => (state.llm.model = el.value));
  bind("#f-apikey", (el) => (state.llm.apiKey = el.value));
  bind("#f-system", (el) => (state.llm.systemMessage = el.value));
  bind("#f-stream", (el) => (state.llm.stream = el.checked));
  bind("#f-maxlen", (el) => (state.llm.maxToolResultLength = Number(el.value) || 120000));
  SAMPLING_NUMERIC_FIELDS.forEach((k) => {
    bind("#f-sampling-" + k, (el) => {
      const raw = el.value.trim();
      state.llm.sampling[k] = raw === "" ? null : Number(raw);
    });
  });
  bind("#f-sampling-reasoning_effort", (el) => {
    state.llm.sampling.reasoning_effort = el.value === "" ? null : el.value;
  });
}

function fillSimple() {
  $("#f-name").value = state.name;
  $("#f-version").value = state.version;
  $("#f-url").value = state.llm.openAiCompatibleServerUrl;
  $("#f-model").value = state.llm.model;
  $("#f-apikey").value = state.llm.apiKey;
  $("#f-system").value = state.llm.systemMessage;
  $("#f-stream").checked = state.llm.stream;
  $("#f-maxlen").value = state.llm.maxToolResultLength;
  SAMPLING_FIELDS.forEach((k) => {
    const v = state.llm.sampling[k];
    const el = $("#f-sampling-" + k);
    if (el) el.value = v === null ? "" : String(v);
  });
}

function kv(labelText, valueText) {
  const p = document.createElement("div");
  p.className = "kv";
  const b = document.createElement("strong");
  b.textContent = labelText + ": ";
  p.append(b, document.createTextNode(String(valueText)));
  return p;
}

function openCheckModal(result) {
  const overlay = $("#modal-overlay");
  $("#modal-overlay .modal").classList.remove("wide");
  const title = $("#modal-title");
  const body = $("#modal-body");
  title.textContent = "";
  body.innerHTML = "";

  const info = result.serverInfo || {};
  if (result.alive) {
    title.textContent = `MCP server — ${info.name || "details"}`;
    const heading = document.createElement("div");
    heading.className = "modal-heading ok";
    heading.textContent = "● Connected";
    body.append(heading);
    if (info.version) body.append(kv("Version", info.version));
    if (result.protocolVersion) body.append(kv("Protocol", result.protocolVersion));
    if (result.endpoint) body.append(kv("Endpoint", result.endpoint));
    if (result.at) body.append(kv("Checked", result.at));

    const toolsTitle = document.createElement("h4");
    if (Array.isArray(result.tools)) {
      toolsTitle.textContent = `Tools (${result.tools.length})`;
      body.append(toolsTitle);
      if (!result.tools.length) {
        const none = document.createElement("p");
        none.className = "hint";
        none.textContent = "The server exposes no tools.";
        body.append(none);
      }
      result.tools.forEach((t) => {
        const item = document.createElement("div");
        item.className = "tool-item";
        const nameEl = document.createElement("code");
        nameEl.textContent = t.name || "(unnamed)";
        item.append(nameEl);
        const desc = document.createElement("div");
        desc.className = "tool-desc";
        desc.textContent = t.description || "No description.";
        item.append(desc);
        body.append(item);
      });
    } else {
      toolsTitle.textContent = "Tools";
      body.append(toolsTitle);
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = result.toolsError
        ? `Connected, but the tool list could not be retrieved: ${result.toolsError}`
        : "Connected, but the tool list could not be retrieved.";
      body.append(hint);
    }
  } else {
    title.textContent = "MCP check failed";
    const heading = document.createElement("div");
    heading.className = "modal-heading error";
    heading.textContent = "✖ Check failed";
    body.append(heading);
    const err = document.createElement("div");
    err.className = "modal-error";
    err.textContent = result.error || "MCP server unreachable";
    body.append(err);
    if (result.endpoint) body.append(kv("Endpoint", result.endpoint));
    if (result.at) body.append(kv("Checked", result.at));
  }

  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
}

function hideOverlay(sel) {
  const overlay = $(sel);
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
}

function showOverlay(sel) {
  const overlay = $(sel);
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
}

function closeModal() {
  stopConnectorPolling();
  ["#modal-overlay", "#open-overlay", "#save-overlay", "#conn-overlay"].forEach(hideOverlay);
}

function confirmDialog(options) {
  const opts = options || {};
  return new Promise((resolve) => {
    const overlay = $("#confirm-overlay");
    $("#confirm-title").textContent = opts.title || "Confirm";
    $("#confirm-message").textContent = opts.message || "";
    $("#confirm-yes").textContent = opts.yesLabel || "Yes";
    $("#confirm-no").textContent = opts.noLabel || "No";
    const yesBtn = $("#confirm-yes");
    const noBtn = $("#confirm-no");
    const closeBtn = $("#confirm-close");
    const buttons = [yesBtn, noBtn, closeBtn];
    buttons.forEach((b) => (b.disabled = true));

    function settle(value) {
      overlay.removeEventListener("click", onBackdrop);
      buttons.forEach((b) => b.removeEventListener("click", onClick));
      hideOverlay("#confirm-overlay");
      resolve(value);
    }
    function onClick(e) {
      settle(e.currentTarget === yesBtn);
    }
    function onBackdrop(e) {
      if (e.target === e.currentTarget) settle(false);
    }
    buttons.forEach((b) => b.addEventListener("click", onClick));
    overlay.addEventListener("click", onBackdrop);
    showOverlay("#confirm-overlay");
    buttons.forEach((b) => (b.disabled = false));
    noBtn.focus();
    overlay._settle = settle;
  });
}

function closeConfirmIfOpen() {
  const overlay = $("#confirm-overlay");
  if (!overlay.classList.contains("hidden") && overlay._settle) {
    const settle = overlay._settle;
    overlay._settle = null;
    settle(false);
    return true;
  }
  return false;
}

function openJsonModal() {
  if (!state) return;
  const overlay = $("#modal-overlay");
  $("#modal-overlay .modal").classList.add("wide");
  const title = $("#modal-title");
  const body = $("#modal-body");
  title.textContent = "JSON preview";
  body.innerHTML = "";
  const pre = document.createElement("pre");
  pre.className = "modal-json";
  pre.textContent = JSON.stringify(serialize(), null, 2);
  const actions = document.createElement("div");
  actions.className = "modal-actions start";
  const copyBtn = document.createElement("button");
  copyBtn.className = "small";
  copyBtn.textContent = "⧉";
  copyBtn.title = "Copy JSON to clipboard";
  copyBtn.setAttribute("aria-label", "Copy JSON to clipboard");
  copyBtn.addEventListener("click", doCopy);
  actions.append(copyBtn);
  body.append(actions, pre);
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
}

function renderMcp() {
  const list = $("#mcp-list");
  list.innerHTML = "";
  state.llm.mcpTools.forEach((tool, i) => {
    const row = document.createElement("div");
    row.className = "mcp-row";

    const name = document.createElement("input");
    name.type = "text";
    name.placeholder = "name";
    name.value = tool.name;
    name.addEventListener("input", () => {
      tool.name = name.value;
      renderTaskToolBoxes();
      markDirty();
    });

    const endpoint = document.createElement("input");
    endpoint.type = "text";
    endpoint.placeholder = "http://localhost:PORT/mcp";
    endpoint.value = tool.endpoint;
    endpoint.classList.add("grow");
    endpoint.addEventListener("input", () => {
      tool.endpoint = endpoint.value;
      tool.status = null;
      tool.lastCheck = null;
      paintStatus();
      markDirty();
    });

    const status = document.createElement("span");
    const paintStatus = () => {
      if (!tool.status) {
        status.textContent = "";
        status.title = "";
        status.className = "mcp-status";
        return;
      }
      status.textContent = "●";
      status.title = tool.status.tip || "";
      status.className = "mcp-status " + tool.status.cls;
    };
    status.addEventListener("click", () => {
      if (tool.lastCheck) openCheckModal(tool.lastCheck);
    });
    paintStatus();

    const check = document.createElement("button");
    check.className = "small";
    check.textContent = "Check";
    check.title = "Ping this MCP server and show its details";
    check.addEventListener("click", async () => {
      check.disabled = true;
      tool.status = { cls: "pending", tip: "checking…" };
      paintStatus();
      let result;
      try {
        let res;
        try {
          res = await fetch("/api/check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: tool.endpoint }),
          });
        } catch {
          throw new Error("Editor backend unreachable — is scripts/run_web.sh still running?");
        }
        const text = await res.text();
        let body;
        try {
          body = JSON.parse(text);
        } catch {
          if (res.status === 404) {
            throw new Error("Editor backend out of date — restart scripts/run_web.sh");
          }
          throw new Error(`Editor backend error (HTTP ${res.status})`);
        }
        result = body;
      } catch (e) {
        result = {
          alive: false,
          error: e.message || "MCP server unreachable",
          endpoint: tool.endpoint,
        };
      }
      result.at = new Date().toLocaleTimeString();
      tool.lastCheck = result;
      if (result.alive) {
        const info = result.serverInfo || {};
        const count = typeof result.toolCount === "number" ? ` — ${result.toolCount} tools` : "";
        tool.status = { cls: "ok", tip: `${info.name || "MCP server"} is alive${count}. Click for details.` };
      } else {
        tool.status = { cls: "error", tip: `${result.error} Click to see the error.` };
      }
      check.disabled = false;
      paintStatus();
      openCheckModal(result);
    });

    const del = document.createElement("button");
    del.className = "small danger";
    del.textContent = "✕";
    del.title = "Remove MCP server";
    del.addEventListener("click", () => {
      const removed = state.llm.mcpTools[i].name;
      state.llm.mcpTools.splice(i, 1);
      state.tasks.forEach((t) => (t.tools = t.tools.filter((x) => x !== removed)));
      renderMcp();
      renderTaskToolBoxes();
      markDirty();
    });

    row.append(name, endpoint, status, check, del);
    list.append(row);
  });
  if (!state.llm.mcpTools.length) {
    list.innerHTML = '<p class="hint">No MCP servers defined.</p>';
  }
}

function selTask() {
  return state.tasks[selectedTask] ?? null;
}

function uniqueTaskName(base) {
  const names = new Set(state.tasks.map((t) => t.name));
  if (!names.has(base)) return base;
  let n = 2;
  while (names.has(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
}

function renderTaskList() {
  const list = $("#task-list");
  list.innerHTML = "";
  state.tasks.forEach((task, i) => {
    const li = document.createElement("li");
    li.className = "task-row" + (i === selectedTask ? " selected" : "");
    li.textContent = task.name || "(unnamed)";
    li.title = `Task ${i + 1}: ${task.name}`;
    li.addEventListener("click", () => {
      selectedTask = i;
      renderTaskList();
      renderTaskEditor();
    });
    list.append(li);
  });
  if (!state.tasks.length) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "No tasks yet — click + Add.";
    list.append(hint);
  }
}

function renderTaskToolBoxes() {
  const task = selTask();
  const box = $("#task-tools");
  if (!box) return;
  box.innerHTML = "";
  if (!task) return;
  const names = [...new Set(state.llm.mcpTools.map((t) => t.name).filter(Boolean))];
  if (!names.length) {
    box.innerHTML = '<span class="hint">No MCP servers available</span>';
    return;
  }
  names.forEach((n) => {
    const label = document.createElement("label");
    label.className = "check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = task.tools.includes(n);
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (!task.tools.includes(n)) task.tools.push(n);
      } else {
        task.tools = task.tools.filter((x) => x !== n);
      }
      markDirty();
    });
    label.append(cb, document.createTextNode(" " + n));
    box.append(label);
  });
}

function renderTaskEditor() {
  const task = selTask();
  const nameEl = $("#task-name");
  const promptEl = $("#task-prompt");
  $("#task-editor-title").textContent = task
    ? `Task ${selectedTask + 1} of ${state.tasks.length}`
    : "Selected task";
  nameEl.disabled = !task;
  promptEl.disabled = !task;
  $("#btn-move-up").disabled = !task || selectedTask === 0;
  $("#btn-move-down").disabled = !task || selectedTask === state.tasks.length - 1;
  $("#btn-dup-task").disabled = !task;
  nameEl.value = task ? task.name : "";
  promptEl.value = task ? task.prompt : "";
  renderTaskToolBoxes();
}

function moveSelected(delta) {
  const j = selectedTask + delta;
  if (!selTask() || j < 0 || j >= state.tasks.length) return;
  [state.tasks[selectedTask], state.tasks[j]] = [state.tasks[j], state.tasks[selectedTask]];
  selectedTask = j;
  renderTaskList();
  renderTaskEditor();
  markDirty();
}

function wireTaskEditor() {
  const nameEl = $("#task-name");
  const promptEl = $("#task-prompt");
  let lastUnique = "";

  const syncListLabel = () => {
    const li = $("#task-list").children[selectedTask];
    const task = selTask();
    if (li && task) li.textContent = task.name || "(unnamed)";
  };

  nameEl.addEventListener("focus", () => (lastUnique = selTask() ? selTask().name : ""));
  nameEl.addEventListener("input", () => {
    const task = selTask();
    if (!task) return;
    task.name = nameEl.value;
    syncListLabel();
    markDirty();
  });
  nameEl.addEventListener("change", () => {
    const task = selTask();
    if (!task) return;
    if (state.tasks.some((t, i) => i !== selectedTask && t.name === task.name)) {
      task.name = lastUnique;
      nameEl.value = lastUnique;
      syncListLabel();
      setStatus(`Task name "${task.name}" is already used — change reverted.`, "error");
      markDirty();
    } else {
      lastUnique = task.name;
    }
  });

  promptEl.addEventListener("input", () => {
    const task = selTask();
    if (task) {
      task.prompt = promptEl.value;
      markDirty();
    }
  });

  $("#btn-move-up").addEventListener("click", () => moveSelected(-1));
  $("#btn-move-down").addEventListener("click", () => moveSelected(1));
  $("#btn-dup-task").addEventListener("click", () => {
    const task = selTask();
    if (!task) return;
    state.tasks.splice(selectedTask + 1, 0, {
      name: uniqueTaskName(task.name),
      prompt: task.prompt,
      tools: [...task.tools],
    });
    selectedTask += 1;
    renderTaskList();
    renderTaskEditor();
    markDirty();
  });
}

function renderAll() {
  if (selectedTask >= state.tasks.length) selectedTask = Math.max(0, state.tasks.length - 1);
  fillSimple();
  renderMcp();
  renderTaskList();
  renderTaskEditor();
  dirty = false;
  renderPreview();
}

function sanitizeName(name) {
  let n = String(name || "").trim().replace(/[/\\:*?"<>|]+/g, "_");
  if (!n) n = "config.json";
  if (!/\.json$/i.test(n)) n += ".json";
  return n;
}

function updateFileLabel() {
  const el = $("#file-label");
  el.textContent = currentFileName || "Untitled";
  el.title = currentTmpPath
    ? `${currentFileName}\nEditing temp copy: ${currentTmpPath}`
    : "No file opened yet — use Save… to write a file";
  el.classList.toggle("untitled", !currentFileName);
  document.title =
    (currentFileName ? currentFileName + " — " : "") + "agentic-tool — config editor";
}

let browseParent = null;
let saveBrowseDir = "";
let saveBrowseParent = null;
let lastBrowseDir = "";

async function apiBrowse(dir) {
  const res = await fetch(`/api/browse?dir=${encodeURIComponent(dir)}`);
  const body = await res.json().catch(() => null);
  if (!body || !body.ok) throw new Error((body && body.error) || "Cannot list directory");
  return body;
}

async function apiOpen(path) {
  const res = await fetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  const body = await res.json().catch(() => null);
  if (!body || !body.ok) throw new Error((body && body.error) || "Cannot open file");
  return body;
}

async function apiSave(dir, name, data) {
  const res = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dir, name, data }),
  });
  const body = await res.json().catch(() => null);
  if (!body || !body.ok) throw new Error((body && body.error) || "Cannot save file");
  return body;
}

function showBrowseError(msg) {
  const el = $("#browse-error");
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

async function browseTo(dir) {
  showBrowseError("");
  let body;
  try {
    body = await apiBrowse(dir);
  } catch (e) {
    showBrowseError(e.message);
    return;
  }
  browseParent = body.parent;
  lastBrowseDir = body.dir;
  $("#browse-path").value = body.dir;
  $("#browse-up").disabled = !body.parent;
  const list = $("#browse-list");
  list.innerHTML = "";
  if (body.entries.length === 0) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "No folders or .json files in this directory.";
    list.append(hint);
  }
  body.entries.forEach((entry) => {
    const item = document.createElement("button");
    const childPath = `${body.dir.replace(/[/\\]+$/, "")}/${entry.name}`;
    item.className = "browse-entry" + (entry.dir ? " dir" : "");
    item.textContent = entry.dir ? `📁 ${entry.name}/` : `📄 ${entry.name}`;
    if (!entry.dir && typeof entry.size === "number") {
      const size = document.createElement("span");
      size.className = "browse-size";
      size.textContent = `${Math.max(1, Math.round(entry.size / 1024))} KB`;
      item.append(size);
    }
    item.addEventListener("click", () => {
      if (entry.dir) browseTo(childPath);
      else openRemoteFile(childPath);
    });
    list.append(item);
  });
}

async function openRemoteFile(path) {
  const leaf = path.split(/[\\/]/).pop();
  if (dirty && !confirm(`Open "${leaf}"? Unsaved changes will be lost.`)) return;
  showBrowseError("");
  let body;
  try {
    body = await apiOpen(path);
  } catch (e) {
    showBrowseError(e.message);
    return;
  }
  state = normalizeConfig(body.data);
  currentFileName = body.name;
  currentTmpPath = body.tmpPath;
  currentSavedPath = null;
  selectedTask = 0;
  renderAll();
  updateFileLabel();
  closeModal();
  showTab("execute");
  setStatus(`Opened ${path} — editing temp copy ${body.tmpPath}`, "ok");
}

function openOpenModal() {
  showOverlay("#open-overlay");
  browseTo($("#browse-path").value.trim());
}

function showSaveBrowseError(msg) {
  const el = $("#save-browse-error");
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

async function saveBrowseTo(dir) {
  showSaveBrowseError("");
  let body;
  try {
    body = await apiBrowse(dir);
  } catch (e) {
    showSaveBrowseError(e.message);
    return;
  }
  saveBrowseDir = body.dir;
  saveBrowseParent = body.parent;
  lastBrowseDir = body.dir;
  $("#save-browse-path").value = body.dir;
  $("#save-browse-up").disabled = !body.parent;
  const list = $("#save-browse-list");
  list.innerHTML = "";
  if (body.entries.length === 0) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "No folders or .json files in this directory.";
    list.append(hint);
  }
  body.entries.forEach((entry) => {
    const item = document.createElement("button");
    const childPath = `${body.dir.replace(/[/\\]+$/, "")}/${entry.name}`;
    item.className = "browse-entry" + (entry.dir ? " dir" : "");
    item.textContent = entry.dir ? `📁 ${entry.name}/` : `📄 ${entry.name}`;
    if (!entry.dir && typeof entry.size === "number") {
      const size = document.createElement("span");
      size.className = "browse-size";
      size.textContent = `${Math.max(1, Math.round(entry.size / 1024))} KB`;
      item.append(size);
    }
    item.addEventListener("click", () => {
      if (entry.dir) saveBrowseTo(childPath);
      else $("#save-name").value = entry.name;
    });
    list.append(item);
  });
}

function openSaveModal(title) {
  const { errors } = validate();
  if (errors.length) {
    showTab(/Task \d/.test(errors[0]) ? "tasks" : "settings");
    setStatus(`Fix validation errors before saving: ${errors[0]}`, "error");
    return;
  }
  $("#save-modal-title").textContent = title;
  const input = $("#save-name");
  input.value = sanitizeName(currentFileName || state.name || "config");
  showOverlay("#save-overlay");
  saveBrowseTo(lastBrowseDir);
  input.focus();
  input.select();
}

async function doSaveHere() {
  if (!saveBrowseDir) {
    showSaveBrowseError("Choose a folder first.");
    return;
  }
  const name = sanitizeName($("#save-name").value);
  let body;
  try {
    body = await apiSave(saveBrowseDir, name, serialize());
  } catch (e) {
    showSaveBrowseError(e.message);
    return;
  }
  currentFileName = body.name;
  currentSavedPath = body.path;
  dirty = false;
  renderPreview();
  updateFileLabel();
  closeModal();
  setStatus(`Saved ${body.path}`, "ok");
}

function doSaveDownload() {
  const name = sanitizeName($("#save-name").value);
  const blob = new Blob([JSON.stringify(serialize(), null, 2) + "\n"], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
  currentFileName = name;
  currentSavedPath = null;
  dirty = false;
  renderPreview();
  updateFileLabel();
  closeModal();
  setStatus(`Saved ${name} (downloaded)`, "ok");
}

function doNew() {
  if (dirty && !confirm("Discard unsaved changes?")) return;
  state = newConfig();
  currentFileName = null;
  currentTmpPath = null;
  currentSavedPath = null;
  selectedTask = 0;
  renderAll();
  updateFileLabel();
  setStatus("New config — use Open… to load a file", "ok");
}

function doCopy() {
  navigator.clipboard
    .writeText(JSON.stringify(serialize(), null, 2))
    .then(() => setStatus("JSON copied to clipboard", "ok"))
    .catch(() => setStatus("Clipboard unavailable", "error"));
}

let connPollTimer = null;

function stopConnectorPolling() {
  if (connPollTimer) {
    clearInterval(connPollTimer);
    connPollTimer = null;
  }
}

function showConnError(msg) {
  const el = $("#conn-error");
  el.textContent = msg || "";
  el.classList.toggle("hidden", !msg);
}

async function apiConnectors(action, id) {
  const url = action ? `/api/connectors/${action}` : "/api/connectors";
  let res;
  try {
    res = await fetch(url, action
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id }),
        }
      : undefined);
  } catch {
    throw new Error("Editor backend unreachable — is scripts/run_web.sh still running?");
  }
  const body = await res.json().catch(() => null);
  if (!body || !body.ok) throw new Error((body && body.error) || "Connector request failed");
  return body;
}

function connectorInConfig(conn) {
  return state.llm.mcpTools.some((t) => t.name === conn.id);
}

function renderConnectors(connectors) {
  const list = $("#conn-list");
  list.innerHTML = "";
  connectors.forEach((conn) => {
    const row = document.createElement("div");
    row.className = "conn-row";

    const info = document.createElement("div");
    info.className = "conn-info";
    const head = document.createElement("div");
    head.className = "conn-head";
    const name = document.createElement("strong");
    name.textContent = conn.label;
    const endpoint = document.createElement("code");
    endpoint.textContent = conn.endpoint;
    head.append(name, endpoint);
    const desc = document.createElement("div");
    desc.className = "conn-desc";
    desc.textContent = conn.description;
    info.append(head, desc);

    const badge = document.createElement("span");
    const cls =
      conn.status === "running" ? "ok" : conn.status === "external" ? "external" : "stopped";
    badge.className = "conn-status " + cls;
    badge.textContent =
      conn.status === "running"
        ? `● running (pid ${conn.pid})`
        : conn.status === "external"
          ? "● port busy"
          : "○ stopped";
    const logTail = (conn.log || []).slice(-8).join("\n");
    if (logTail) badge.title = logTail;
    if (typeof conn.exitCode === "number" && conn.status === "stopped") {
      badge.title = `Last run exited with code ${conn.exitCode}\n${logTail}`;
    }

    const play = document.createElement("button");
    play.className = "small";
    play.textContent = "▶";
    play.title =
      conn.status === "external"
        ? `Port ${conn.port} is already in use`
        : "Start this connector server";
    play.disabled = conn.status !== "stopped";

    const stop = document.createElement("button");
    stop.className = "small danger";
    stop.textContent = "■";
    stop.title = "Stop this connector server";
    stop.disabled = conn.status !== "running";

    const add = document.createElement("button");
    add.className = "small";
    add.textContent = "+";
    const present = connectorInConfig(conn);
    add.disabled = present;
    add.title = present
      ? "Already in the current config"
      : `Add "${conn.id}" to the current config`;

    const run = async (action) => {
      [play, stop, add].forEach((b) => (b.disabled = true));
      showConnError("");
      try {
        await apiConnectors(action, conn.id);
      } catch (e) {
        showConnError(e.message);
      }
      await refreshConnectors(true);
    };
    play.addEventListener("click", () => run("start"));
    stop.addEventListener("click", () => run("stop"));
    add.addEventListener("click", () => {
      if (connectorInConfig(conn)) return;
      state.llm.mcpTools.push({ name: conn.id, endpoint: conn.endpoint });
      renderMcp();
      renderTaskToolBoxes();
      markDirty();
      renderConnectors(connectors);
      setStatus(`Added MCP server "${conn.id}" to the config`, "ok");
    });

    row.append(info, badge, play, stop, add);
    list.append(row);
  });
}

async function refreshConnectors(silent) {
  try {
    const body = await apiConnectors(null);
    renderConnectors(body.connectors);
    if (!silent) showConnError("");
  } catch (e) {
    if (!silent) showConnError(e.message);
  }
}

function openConnectorsModal() {
  showOverlay("#conn-overlay");
  showConnError("");
  refreshConnectors(true);
  stopConnectorPolling();
  connPollTimer = setInterval(() => refreshConnectors(true), 2000);
}

function activeConfigPath() {
  return currentSavedPath || currentTmpPath;
}

function runBlockReason() {
  if (!activeConfigPath()) return "Open or save a config file first.";
  const { errors } = validate();
  if (errors.length) return errors[0];
  if (dirty) return "Save changes before running.";
  return null;
}

function updateRunButtons() {
  const startBtn = $("#btn-run-start");
  const stopBtn = $("#btn-run-stop");
  if (!startBtn || !stopBtn) return;
  const blocked = runBlockReason();
  startBtn.disabled = activeTab !== "execute" || runRunning || blocked !== null;
  startBtn.title =
    activeTab !== "execute"
      ? "Switch to the Execute tab to run the project"
      : runRunning
        ? "A run is already in progress"
        : blocked || `Run agentic-tool.py --file ${activeConfigPath() || ""}`;
  stopBtn.disabled = activeTab !== "execute" || !runRunning;
  stopBtn.title =
    activeTab !== "execute"
      ? "Switch to the Execute tab to stop the run"
      : runRunning
        ? "Stop the running project"
        : "No run in progress";
}

function appendRunLines(lines) {
  if (!lines || !lines.length) return;
  const ta = $("#run-output");
  const nearBottom = ta.scrollHeight - ta.scrollTop - ta.clientHeight < 40;
  ta.value += lines.join("\n") + "\n";
  if (nearBottom) ta.scrollTop = ta.scrollHeight;
}

function setRunPending(text) {
  text = text || "";
  if (text === runPending) return;
  const ta = $("#run-output");
  if (runPending && ta.value.endsWith(runPending)) {
    ta.value = ta.value.slice(0, -runPending.length);
  }
  runPending = text;
  if (runPending) {
    const nearBottom = ta.scrollHeight - ta.scrollTop - ta.clientHeight < 40;
    ta.value += runPending;
    if (nearBottom) ta.scrollTop = ta.scrollHeight;
  }
}

function applyRunStatus(body) {
  if (body.reset) {
    $("#run-output").value = "";
    runPending = "";
    runOffset = 0;
  }
  setRunPending("");
  appendRunLines(body.lines);
  setRunPending(body.pending);
  if (typeof body.offset === "number") runOffset = body.offset;
}

async function pollRunStatus() {
  let body;
  try {
    const res = await fetch(`/api/run/status?offset=${runOffset}`);
    body = await res.json().catch(() => null);
    if (!body || !body.ok) throw new Error((body && body.error) || "Run status failed");
  } catch {
    return;
  }
  const wasRunning = runRunning;
  applyRunStatus(body);
  runRunning = !!body.running;
  if (wasRunning && !runRunning) {
    const code = typeof body.exitCode === "number" ? body.exitCode : "?";
    appendRunLines([`— process exited with code ${code} —`]);
    setStatus(`Run finished (exit code ${code})`, code === 0 ? "ok" : "error");
  }
  updateRunButtons();
}

function startRunPolling() {
  stopRunPolling();
  pollRunStatus();
  runPollTimer = setInterval(pollRunStatus, 1000);
}

function stopRunPolling() {
  if (runPollTimer) {
    clearInterval(runPollTimer);
    runPollTimer = null;
  }
}

async function doRunStart() {
  const path = activeConfigPath();
  if (!path || runBlockReason() || runRunning) return;
  $("#btn-run-start").disabled = true;
  let body;
  try {
    const res = await fetch("/api/run/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
    body = await res.json().catch(() => null);
    if (!body || !body.ok) throw new Error((body && body.error) || "Failed to start run");
  } catch (e) {
    setStatus(`Cannot start run: ${e.message}`, "error");
    updateRunButtons();
    return;
  }
  $("#run-output").value = "";
  runPending = "";
  runOffset = 0;
  if (Array.isArray(body.autoStarted) && body.autoStarted.length) {
    appendRunLines([`— auto-started MCP connector(s): ${body.autoStarted.join(", ")} —`]);
  }
  applyRunStatus(body);
  runRunning = true;
  setStatus(`Running ${path}`, "ok");
  updateRunButtons();
}

async function doRunStop() {
  if (!runRunning) return;
  const confirmed = await confirmDialog({
    title: "Stop run",
    message: "Do you really want to stop the running tasks?",
  });
  if (!confirmed) return;
  await executeRunStop();
}

async function executeRunStop() {
  if (!runRunning) return;
  $("#btn-run-stop").disabled = true;
  try {
    const res = await fetch("/api/run/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const body = await res.json().catch(() => null);
    if (!body || !body.ok) throw new Error((body && body.error) || "Failed to stop run");
    runRunning = false;
    setStatus("Run stopped", "ok");
  } catch (e) {
    setStatus(`Cannot stop run: ${e.message}`, "error");
  }
  updateRunButtons();
}

function showTab(name) {
  activeTab = name;
  const tabs = ["settings", "tasks", "execute"];
  tabs.forEach((tab) => {
    const active = tab === name;
    const btn = $("#tab-btn-" + tab);
    const panel = $("#tab-" + tab);
    if (btn) {
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    }
    if (panel) {
      panel.classList.toggle("active", active);
    }
  });
  maybeInitMarkdownEditors();
  if (name === "execute") startRunPolling();
  else stopRunPolling();
  updateRunButtons();
}

function wireToolbar() {
  wireTaskEditor();
  $("#tab-btn-settings").addEventListener("click", () => showTab("settings"));
  $("#tab-btn-tasks").addEventListener("click", () => showTab("tasks"));
  $("#tab-btn-execute").addEventListener("click", () => showTab("execute"));
  $("#btn-run-start").addEventListener("click", doRunStart);
  $("#btn-run-stop").addEventListener("click", doRunStop);
  $("#btn-run-clear").addEventListener("click", () => {
    $("#run-output").value = "";
    runPending = "";
  });
  $("#btn-new").addEventListener("click", doNew);
  $("#btn-open").addEventListener("click", openOpenModal);
  $("#btn-save").addEventListener("click", () => openSaveModal("Save config"));
  $("#btn-preview").addEventListener("click", openJsonModal);
  $("#btn-connectors").addEventListener("click", openConnectorsModal);
  $("#btn-add-mcp").addEventListener("click", () => {
    state.llm.mcpTools.push({ name: "", endpoint: "" });
    renderMcp();
    renderTaskToolBoxes();
    markDirty();
  });
  $("#btn-add-task").addEventListener("click", () => {
    state.tasks.push({ name: uniqueTaskName("New task..."), prompt: "", tools: [] });
    selectedTask = state.tasks.length - 1;
    renderTaskList();
    renderTaskEditor();
    markDirty();
    const nameEl = $("#task-name");
    nameEl.focus();
    nameEl.select();
  });
  $("#btn-remove-task").addEventListener("click", () => {
    if (!selTask()) return;
    state.tasks.splice(selectedTask, 1);
    if (selectedTask >= state.tasks.length) selectedTask = Math.max(0, state.tasks.length - 1);
    renderTaskList();
    renderTaskEditor();
    markDirty();
  });
  $("#modal-close").addEventListener("click", closeModal);
  ["#modal-overlay", "#open-overlay", "#save-overlay", "#conn-overlay"].forEach((sel) => {
    $(sel).addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeModal();
    });
  });
  $("#open-close").addEventListener("click", closeModal);
  $("#conn-close").addEventListener("click", closeModal);
  $("#save-close").addEventListener("click", closeModal);
  $("#save-cancel").addEventListener("click", closeModal);
  $("#save-download").addEventListener("click", doSaveDownload);
  $("#save-here").addEventListener("click", doSaveHere);
  $("#save-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doSaveHere();
  });
  $("#save-browse-go").addEventListener("click", () => saveBrowseTo($("#save-browse-path").value.trim()));
  $("#save-browse-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveBrowseTo($("#save-browse-path").value.trim());
  });
  $("#save-browse-up").addEventListener("click", () => {
    if (saveBrowseParent) saveBrowseTo(saveBrowseParent);
  });
  $("#browse-go").addEventListener("click", () => browseTo($("#browse-path").value.trim()));
  $("#browse-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") browseTo($("#browse-path").value.trim());
  });
  $("#browse-up").addEventListener("click", () => {
    if (browseParent) browseTo(browseParent);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (closeConfirmIfOpen()) return;
      closeModal();
    }
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      openSaveModal("Save config");
    }
  });
  window.addEventListener("beforeunload", (e) => {
    if (dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

let mteSystemDone = false;
let mtePromptDone = false;

function maybeInitMarkdownEditors() {
  if (typeof window.MarkdownEditor !== "function") return;
  document.documentElement.setAttribute("data-theme", "darkberry");
  const common = {
    theme: "darkberry",
    toolbar: [
      "bold", "italic", "strikethrough", "divider",
      "quote", "code", "codeBlock", "divider",
      "ul", "ol", "task", "divider",
      "link", "table", "divider",
      "undo", "redo", "divider",
      "preview", "fullscreen",
    ],
  };
  const systemEl = $("#f-system");
  if (!mteSystemDone && systemEl.offsetParent !== null) {
    new window.MarkdownEditor(systemEl, {
      ...common,
      minHeight: "260px",
      onChange(value) {
        if (!state) return;
        state.llm.systemMessage = value;
        markDirty();
      },
    });
    mteSystemDone = true;
  }
  const promptEl = $("#task-prompt");
  if (!mtePromptDone && promptEl.offsetParent !== null) {
    new window.MarkdownEditor(promptEl, {
      ...common,
      minHeight: "300px",
      onChange(value) {
        const task = selTask();
        if (!task) return;
        task.prompt = value;
        markDirty();
      },
    });
    mtePromptDone = true;
  }
}

function boot() {
  bindSimple();
  wireToolbar();
  maybeInitMarkdownEditors();
  state = newConfig();
  renderAll();
  updateFileLabel();
  setStatus("New config — use Open… to load a config file", "ok");
}

boot();
