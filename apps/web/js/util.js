/* 小工具：DOM、哈希、提示。没有框架依赖，保持可读。 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export const uid = (prefix = "m") =>
  `${prefix}-${Math.random().toString(16).slice(2, 8)}${Date.now().toString(16).slice(-4)}`;

export function debounce(fn, wait = 220) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function toast(message, kind = "info") {
  const host = $("#toastHost");
  if (!host) return;
  const node = el("div", { class: `toast${kind === "info" ? "" : " is-" + kind}`, text: message });
  host.append(node);
  setTimeout(() => node.remove(), kind === "error" ? 6000 : 3200);
}

/** 与 Python `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` 对齐 */
export function canonicalJson(value) {
  if (value === null) return "null";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(",")}}`;
  }
  return "null";
}

export async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** 与服务端 ResumeDocument.content_hash() 同算法：sha256: + 前 32 位 */
export async function contentHash(doc, specs) {
  const modules = [...(doc.modules || [])]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || String(a.id).localeCompare(String(b.id)))
    .map((m) => ({ id: m.id, type: m.type, order: m.order ?? 0, data: normalizeData(m, specs) }));
  const appearance = {
    template: doc.appearance?.template ?? "executive",
    theme: doc.appearance?.theme ?? "navy",
    density: doc.appearance?.density ?? "balanced",
    zoom: doc.appearance?.zoom ?? 0.75,
  };
  const payload = {
    schemaVersion: doc.schemaVersion ?? "1.1",
    targetJob: doc.targetJob ?? "",
    appearance,
    modules,
  };
  const hex = await sha256Hex(canonicalJson(payload));
  return "sha256:" + hex.slice(0, 32);
}

/** 字段补全：服务端会补齐所有声明字段，前端必须一致，否则哈希不同 */
export function normalizeData(module, specs) {
  const spec = specs?.[module.type];
  const out = {};
  if (!spec) {
    for (const [k, v] of Object.entries(module.data || {})) out[k] = v == null ? "" : String(v);
    return out;
  }
  for (const field of spec.fields) {
    const raw = module.data?.[field.name];
    out[field.name] = raw == null ? "" : String(raw);
  }
  return out;
}

export function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** "想投 X" 这类句式：抓出来直接写进 targetJob，省掉一次反问 */
const JOB_AFTER = /(?:想投|投递|应聘|目标岗位|求职意向|求职方向|想做|想找|找一份)[：:\s]*([^，。；;、\n]{2,20})/;
const JOB_KNOWN =
  /(Python\s*后端|Java\s*后端|Go\s*后端|C\+\+\s*后端|前端开发|后端开发|全栈开发|算法工程师|数据分析|数据开发|测试开发|运维开发|产品经理|机器学习|深度学习|嵌入式|客户端开发|UI\s*设计|交互设计)/i;

export function guessTargetJob(text) {
  const hit = String(text || "").match(JOB_AFTER);
  if (hit) return hit[1].trim().slice(0, 20);
  const known = String(text || "").match(JOB_KNOWN);
  return known ? known[0].replace(/\s+/g, " ").trim() : "";
}
