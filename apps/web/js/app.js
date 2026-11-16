/* 应用装配：左侧栏（任务 + 历史）、对话页、工作台、三个工具页。
 * 这里只做"接线"：业务规则在各模块与后端，样式在 app.css。 */

import { $, $$, debounce, el, toast } from "./util.js";
import { Api } from "./api.js";
import { Store } from "./state.js";
import { Preview } from "./preview.js";
import { Editor } from "./editor.js";
import { Chat } from "./chat.js";
import { Imports } from "./imports.js";
import { Jobs } from "./jobs.js";
import { Interview } from "./interview.js";
import { Profile } from "./profile.js";
import { History, historyTime } from "./history.js";
import { SAMPLE_DOCUMENT, SAMPLE_INSTRUCTION } from "./sample.js";

const UI_KEY = "jianmian_ui_v1";

const api = new Api();
let store = null;
let preview = null;
let editor = null;
let chat = null;
let profile = null;
let imports = null;
let history = null;
let jobs = null;
let interview = null;
let meta = null;
let ui = loadUi();
let lastReport = { pageCount: 1, overflowPx: 0, minFontPt: 10.5 };

function loadUi() {
  try {
    return JSON.parse(localStorage.getItem(UI_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function saveUi(patch) {
  ui = { ...ui, ...patch };
  try {
    localStorage.setItem(UI_KEY, JSON.stringify(ui));
  } catch {
    /* UI 偏好存不下不影响使用 */
  }
}

// ------------------------------------------------------------------ 启动
async function boot() {
  let config;
  try {
    config = await api.init();
    meta = await api.get("/api/meta/modules");
  } catch (err) {
    document.querySelector(".main").innerHTML =
      `<div style="padding:48px;font-family:sans-serif;line-height:1.9">
        <h2 style="font-weight:600">连不上后端</h2>
        <p>请确认服务已经启动（默认 http://127.0.0.1:8000），然后刷新页面。</p>
        <p style="color:#8b8b8b">${err.message}</p>
      </div>`;
    return;
  }

  const specs = Object.fromEntries(meta.modules.map((spec) => [spec.type, spec]));

  store = new Store(specs);
  history = new History();

  preview = new Preview($("#previewStack"), { specs });
  preview.setThemes(meta.themes);
  preview.zoomOverride = Number(ui.zoom) || 0.75;

  fillSelects(meta, store.doc);

  editor = new Editor({
    paletteEl: $("#paletteGrid"),
    listEl: $("#moduleList"),
    emptyEl: $("#moduleEmpty"),
    inspFields: $("#inspFields"),
    inspTitle: $("#inspTitle"),
    inspSub: $("#inspSub"),
    specs,
    store,
    onSelect: () => {
      editor.renderList(store.doc);
      editor.renderInspector(store.doc);
    },
  });

  profile = new Profile({
    api,
    store,
    els: {
      extractBtn: $("#extractBtn"),
      exportBtn: $("#exportBtn"),
      importJsonBtn: $("#importJsonBtn"),
      jsonInput: $("#jsonInput"),
      memoryText: $("#memoryText"),
      candidates: $("#memoryCandidates"),
      factList: $("#factList"),
    },
  });

  chat = new Chat({
    api,
    store,
    specs,
    preview,
    elements: {
      view: document.querySelector('.view[data-page="chat"]'),
      chatScroll: $("#chatScroll"),
      composer: $("#composer"),
      input: $("#composerInput"),
      box: $("#composerBox"),
      sendBtn: $("#sendBtn"),
      stopBtn: $("#stopBtn"),
      status: $("#chatStatus"),
    },
    getMemoryFacts: () => profile.facts(),
    getPageCount: () => lastReport.pageCount,
    onLayout: (doc, report) => updatePageInfo(report),
    onDone: () => renderAll(store.doc, "refresh"),
    onMessage: (message) => {
      history.append(message);
      renderHistory();
    },
    onOpenWorkspace: () => go("workspace"),
  });

  imports = new Imports({
    api,
    store,
    specs,
    els: {
      dropzone: $("#dropzone"),
      fileInput: $("#fileInput"),
      meta: $("#importMeta"),
      candidates: $("#importCandidates"),
      actions: $("#importActions"),
      mergeBtn: $("#mergeImportBtn"),
      discardBtn: $("#discardImportBtn"),
    },
  });

  jobs = new Jobs({
    api,
    store,
    els: { jobInput: $("#jobInput"), cityInput: $("#cityInput"), matchBtn: $("#matchBtn"), result: $("#jobResult") },
  });

  interview = new Interview({
    api,
    store,
    els: {
      jobInput: $("#ivJobInput"),
      startBtn: $("#ivStartBtn"),
      thread: $("#ivThread"),
      progress: $("#ivProgress"),
      answerBox: $("#ivAnswerBox"),
      answer: $("#ivAnswer"),
      sendBtn: $("#ivSendBtn"),
      report: $("#ivReport"),
    },
  });

  store.subscribe((doc, reason) => renderAll(doc, reason));
  renderAll(store.doc, "boot");
  profile.refresh();
  wireShell(config);
  wireWorkbench();
  wireModals();

  $("#settingsModel").textContent =
    config.modelProvider === "mock" ? "离线确定性模式（无需 Key）" : `云端模型：${config.modelName}`;

  history.onChange(() => renderHistory());
  renderHistory();

  // 恢复最近一段对话
  chat.restore(history.messages());
  if (!history.messages().length) chat.setFlow(false);

  for (const warning of store.warnings || []) toast(warning, "warn");

  // -------------------------------------------------- 演示 / 直达参数
  const params = new URLSearchParams(location.search);
  if (params.get("demo") === "1") {
    store.replace(structuredClone(SAMPLE_DOCUMENT), "demo");
    const landing = params.get("nav") || "chat";
    go(["workspace", "interview", "research", "archive"].includes(landing) ? landing : "chat");
    if (params.get("auto") === "1") {
      setTimeout(() => chat.send(SAMPLE_INSTRUCTION), 400);
    }
    return;
  }
  const nav = params.get("nav");
  go(nav && ["workspace", "interview", "research", "archive"].includes(nav) ? nav : "chat");

  const seed = params.get("q") || "";
  if (seed) {
    chat.setInput(seed);
    if (params.get("go") === "1") setTimeout(() => $("#composer").requestSubmit(), 320);
  }
}

// ------------------------------------------------------------------ 导航
function go(page) {
  document.body.dataset.nav = page;
  $$(".view").forEach((view) => view.classList.toggle("is-active", view.dataset.page === page));
  $$(".rail-item").forEach((item) => item.classList.toggle("is-active", item.dataset.nav === page));
  if (page === "workspace") {
    renderAll(store.doc, "nav");
    chat.setFlow(history.messages().length > 0);
  }
  if (page === "chat") {
    chat.setFlow(history.messages().length > 0);
    setTimeout(() => chat.focus(), 80);
  }
  if (page === "research") $("#jobInput").value = store.doc.targetJob || "";
  if (page === "interview") $("#ivJobInput").value = store.doc.targetJob || "";
}

// ------------------------------------------------------------------ 侧栏
function wireShell(config) {
  $$(".rail-item[data-nav]").forEach((item) => {
    item.addEventListener("click", () => go(item.dataset.nav));
  });
  $("#logoBtn").addEventListener("click", () => go("chat"));
  $("#backToChatBtn").addEventListener("click", () => go("chat"));

  $("#newChatBtn").addEventListener("click", () => {
    history.start();
    chat.restore([]);
    chat.setFlow(false);
    go("chat");
  });

  $("#sampleBtn").addEventListener("click", () => {
    store.replace(structuredClone(SAMPLE_DOCUMENT), "sample");
    go("workspace");
    toast("已载入一份示例简历，直接在左边改就行");
  });

  $("#attachBtn").addEventListener("click", () => openModal("#importModal"));

  $("#meBtn").addEventListener("click", () => {
    $("#settingsZoom").textContent = `${Math.round((preview.zoomOverride || 0.75) * 100)}%`;
    openModal("#settingsModal");
  });
}

function renderHistory() {
  const list = $("#historyList");
  if (!history.items.length) {
    list.replaceChildren(el("div", { class: "hist-empty", text: "还没有对话。说一句你的经历，就能开始。" }));
    return;
  }
  const nodes = history.items.map((item) => {
    const node = el("button", {
      class: `hist-item${item.id === history.activeId ? " is-active" : ""}`,
      type: "button",
      title: item.title || "新对话",
    }, [
      el("span", { class: "hist-title", text: item.title || "新对话" }),
      el("span", { class: "hist-time", text: historyTime(item.updatedAt) }),
    ]);
    node.addEventListener("click", () => {
      const messages = history.open(item.id);
      chat.restore(messages);
      go("chat");
    });
    return node;
  });
  list.replaceChildren(el("div", { class: "hist-label", text: "对话" }), ...nodes);
}

// ------------------------------------------------------------------ 工作台
function wireWorkbench() {
  $("#agentModifyBtn").addEventListener("click", () => {
    const module = editor.selected;
    const raw = $("#agentInput").value.trim();
    const fallback = "写得更专业，突出我负责的部分和结果";
    const text = raw || fallback;
    // 已经是完整指令就原样发，不要套两层"把…"
    const whole = /^(把|帮|请|删|加|改|换|压缩|精简|重写|调整)/.test(text);
    const instruction = whole || !module ? text : `把「${editor.titleOf(module)}」这一段${text}`;
    $("#agentInput").value = "";
    go("chat");
    chat.send(instruction);
  });

  $("#agentInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      $("#agentModifyBtn").click();
    }
  });

  $("#zoomIn").addEventListener("click", () => setZoom((preview.zoomOverride || 0.75) + 0.05));
  $("#zoomOut").addEventListener("click", () => setZoom((preview.zoomOverride || 0.75) - 0.05));

  $("#templateSelect").addEventListener("change", (event) => store.setAppearance({ template: event.target.value }));
  $("#themeSelect").addEventListener("change", (event) => store.setAppearance({ theme: event.target.value }));
  $("#densitySelect").addEventListener("change", (event) => store.setAppearance({ density: event.target.value }));
  $("#undoBtn").addEventListener("click", () => store.undo());
  $("#redoBtn").addEventListener("click", () => store.redo());
  $("#printBtn").addEventListener("click", () => window.print());

  document.addEventListener("keydown", (event) => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) return;
    const key = event.key.toLowerCase();
    if (key === "z") {
      event.preventDefault();
      if (event.shiftKey) store.redo();
      else store.undo();
    }
    if (key === "p") {
      event.preventDefault();
      window.print();
    }
  });
  window.addEventListener("beforeprint", () => {
    if (preview.container) preview.container.style.transform = "none";
  });
  window.addEventListener("afterprint", () => renderAll(store.doc, "afterprint"));
}

// ------------------------------------------------------------------ 弹层
function openModal(selector) {
  const node = $(selector);
  node.hidden = false;
  node.dataset.open = "1";
}

function closeModal(selector) {
  const node = $(selector);
  node.hidden = true;
  delete node.dataset.open;
}

function wireModals() {
  $("#importCloseBtn").addEventListener("click", () => closeModal("#importModal"));
  $("#settingsCloseBtn").addEventListener("click", () => closeModal("#settingsModal"));

  // 合并 / 放弃之后自动收起，避免"改完了还挡着一层"
  $("#mergeImportBtn").addEventListener("click", () => setTimeout(() => closeModal("#importModal"), 0));
  $("#discardImportBtn").addEventListener("click", () => closeModal("#importModal"));

  $$(".modal").forEach((modal) => {
    modal.addEventListener("click", (event) => {
      if (event.target === modal) modal.hidden = true;
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    $$(".modal").forEach((modal) => {
      modal.hidden = true;
    });
  });

  const byokToggle = $("#byokToggle");
  const byokKey = $("#byokKey");
  byokToggle.addEventListener("change", () => {
    byokKey.hidden = !byokToggle.checked;
    if (!byokToggle.checked) {
      byokKey.value = "";
      api.setByok(null);
    } else {
      byokKey.focus();
    }
  });
  byokKey.addEventListener("input", () => api.setByok(byokKey.value));

  $("#clearLocalBtn").addEventListener("click", () => {
    if (!window.confirm("清空本地简历与全部对话历史？服务端没有备份，清空后无法恢复。")) return;
    localStorage.removeItem("jianmian_studio_v2");
    localStorage.removeItem("jianmian_chats_v1");
    location.reload();
  });
}

// ------------------------------------------------------------------ 渲染
function fillSelects(meta, doc) {
  const template = $("#templateSelect");
  template.replaceChildren(...meta.templates.map((t) => new Option(t.name, t.id)));
  template.value = doc.appearance.template;

  const theme = $("#themeSelect");
  theme.replaceChildren(...meta.themes.map((t) => new Option(t.name, t.id)));
  theme.value = doc.appearance.theme;

  $("#densitySelect").value = doc.appearance.density;
}

function setZoom(value) {
  const zoom = Math.min(1.2, Math.max(0.5, Math.round(value * 100) / 100));
  preview.zoomOverride = zoom;
  saveUi({ zoom });
  renderAll(store.doc, "zoom");
}

const setSaved = debounce(() => {}, 400);

function renderAll(doc, reason) {
  lastReport = preview.render(doc);
  updatePageInfo(lastReport);

  if (reason && reason.startsWith("field:")) {
    editor.refreshTitle(reason.slice(6));
  } else {
    editor.renderPalette();
    editor.renderList(doc);
    editor.renderInspector(doc);
  }

  const template = $("#templateSelect");
  if (template.value !== doc.appearance.template) template.value = doc.appearance.template;
  const theme = $("#themeSelect");
  if (theme.value !== doc.appearance.theme) theme.value = doc.appearance.theme;
  const density = $("#densitySelect");
  if (density.value !== doc.appearance.density) density.value = doc.appearance.density;

  $("#undoBtn").disabled = !store.canUndo();
  $("#redoBtn").disabled = !store.canRedo();
  $("#zoomLabel").textContent = `${Math.round((preview.zoomOverride || 0.75) * 100)}%`;
  $("#palCount").textContent = `${doc.modules.length}`;
  setSaved();
}

function updatePageInfo(report) {
  $("#pageInfo").textContent = `${report.pageCount} 页 · 最小字号 ${report.minFontPt}pt`;
  const warn = $("#overflowInfo");
  if (report.overflowPx > 1) {
    warn.hidden = false;
    warn.textContent = `超出约 ${report.overflowPx}px`;
  } else {
    warn.hidden = true;
  }
}

boot();
