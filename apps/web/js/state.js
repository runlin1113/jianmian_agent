/* 简历文档模型（本地优先）。
 *
 * 服务端不存简历主数据，所以这里的 Store 就是"主数据"：
 * - 每次修改 revision+1，提案要基于同一 revision 才能采纳；
 * - 撤销是恢复快照，不是"让模型改回去"；
 * - 旧版 jianmian_studio_v1 会被迁移，密钥直接丢弃而不是复制。
 */

import { normalizeData, uid } from "./util.js";

export const KEY_V2 = "jianmian_studio_v2";
export const KEY_V1 = "jianmian_studio_v1";
export const SCHEMA_VERSION = "1.1";

const LEGACY_LABEL_ALIAS = {
  project: { proj_name: ["项目名称", "项目名"], role: ["担任角色", "角色"], desc: ["项目详情", "项目描述", "内容"] },
  internship: { company: ["公司名称", "公司"], position: ["职位名称", "职位"], desc: ["工作内容", "工作内容及产出", "内容"] },
  education: { school: ["学校名称", "学校", "院校"], major: ["专业名称", "专业"], degree: ["学历"], course: ["主修课程", "课程", "GPA"] },
  honor: { honor_name: ["奖项名称", "奖项"], level: ["获奖级别", "级别", "说明"] },
  basic: { name: ["姓名"], phone: ["电话"], email: ["邮箱"], job: ["求职意向"], github: ["个人主页", "主页", "GitHub"] },
  skills: { skills: ["技能清单", "技能"] },
  summary: { eval: ["自我评价", "内容"] },
};

export function emptyDocument() {
  return {
    id: `r-${Math.random().toString(16).slice(2, 10)}`,
    schemaVersion: SCHEMA_VERSION,
    revision: 0,
    targetJob: "",
    modules: [],
    appearance: { template: "executive", theme: "navy", density: "balanced", zoom: 0.75 },
    recovery: [],
  };
}

export class Store {
  constructor(specs) {
    this.specs = specs;
    this.listeners = [];
    this.history = [];
    this.future = [];
    this.doc = this._load();
    this.warnings = [];
  }

  subscribe(fn) {
    this.listeners.push(fn);
    return () => {
      this.listeners = this.listeners.filter((f) => f !== fn);
    };
  }

  emit(reason = "change") {
    for (const fn of this.listeners) fn(this.doc, reason);
  }

  // ------------------------------------------------------------------
  // 读取与迁移
  // ------------------------------------------------------------------
  _load() {
    try {
      const rawV2 = localStorage.getItem(KEY_V2);
      if (rawV2) {
        const parsed = JSON.parse(rawV2);
        return this._normalize(parsed);
      }
      const rawV1 = localStorage.getItem(KEY_V1);
      if (rawV1) {
        const migrated = this._migrateLegacy(JSON.parse(rawV1));
        localStorage.setItem(KEY_V2, JSON.stringify(migrated));
        this.warnings.push("已把旧版数据迁移到新结构；旧版 API Key 没有被复制。");
        return migrated;
      }
    } catch (err) {
      this.warnings.push("本地数据读取失败，已新建空白简历（旧数据仍保留在浏览器里）");
    }
    return emptyDocument();
  }

  _normalize(doc) {
    const base = emptyDocument();
    const out = {
      ...base,
      ...doc,
      id: doc.id || base.id,
      schemaVersion: doc.schemaVersion || SCHEMA_VERSION,
      revision: Number.isFinite(doc.revision) ? doc.revision : 0,
      targetJob: doc.targetJob || "",
      appearance: { ...base.appearance, ...(doc.appearance || {}) },
      recovery: Array.isArray(doc.recovery) ? doc.recovery : [],
    };
    out.modules = (Array.isArray(doc.modules) ? doc.modules : [])
      .filter((m) => m && this.specs[m.type])
      .map((m, index) => ({
        id: m.id || uid("mod"),
        type: m.type,
        order: Number.isFinite(m.order) ? m.order : index + 1,
        collapsed: Boolean(m.collapsed),
        data: normalizeData(m, this.specs),
      }));
    return out;
  }

  /** 旧版：{resumeId, modules:[{type:"教育背景", ...}], template, theme, density, api:{apiKey}} */
  _migrateLegacy(raw) {
    const doc = emptyDocument();
    if (!raw || typeof raw !== "object") return doc;
    doc.id = String(raw.resumeId || doc.id);
    doc.targetJob = String(raw.targetJob || "").slice(0, 120);
    for (const key of ["template", "theme", "density", "zoom"]) {
      if (raw[key] !== undefined) doc.appearance[key] = raw[key];
    }
    const byZh = new Map(Object.values(this.specs).map((s) => [s.zh, s]));
    const modules = [];
    const recovery = [];
    const seen = new Set();

    for (const legacy of Array.isArray(raw.modules) ? raw.modules : []) {
      if (!legacy || typeof legacy !== "object") {
        recovery.push({ reason: "旧模块不是对象", raw: legacy });
        continue;
      }
      const type = this.specs[legacy.type] ? legacy.type : byZh.get(legacy.type)?.type;
      const spec = type ? this.specs[type] : null;
      if (!spec) {
        recovery.push({ reason: `未知模块类型：${legacy.type}`, raw: legacy });
        continue;
      }
      if (!spec.multiple && seen.has(type)) {
        recovery.push({ reason: `重复的单例模块：${spec.zh}`, raw: legacy });
        continue;
      }
      const data = {};
      const consumed = new Set();
      for (const field of spec.fields) {
        const alias = LEGACY_LABEL_ALIAS[type]?.[field.name] || [];
        const candidates = [field.name, field.label, ...alias];
        for (const key of candidates) {
          if (legacy[key] !== undefined && legacy[key] !== null && !consumed.has(key)) {
            data[field.name] = String(legacy[key]);
            consumed.add(key);
            break;
          }
        }
        if (data[field.name] === undefined) data[field.name] = "";
      }
      if (!Object.values(data).some((v) => String(v).trim())) {
        recovery.push({ reason: "旧模块没有可识别的字段", raw: legacy });
        continue;
      }
      seen.add(type);
      modules.push({ id: uid("mod"), type, order: modules.length + 1, collapsed: true, data });
    }

    doc.modules = modules;
    doc.recovery = recovery.slice(0, 20);
    if (raw.api?.apiKey) {
      doc.recovery.push({ reason: "旧版曾把 API Key 写入本地存储，迁移时已丢弃", raw: { apiKey: "已丢弃" } });
    }
    return doc;
  }

  // ------------------------------------------------------------------
  // 修改
  // ------------------------------------------------------------------
  commit(mutator, reason = "edit") {
    const next = structuredClone(this.doc);
    const result = mutator(next);
    if (result === false) return false;
    next.revision = (this.doc.revision || 0) + 1;
    this.history.push(structuredClone(this.doc));
    if (this.history.length > 60) this.history.shift();
    this.future = [];
    this.doc = this._normalize(next);
    this._save();
    this.emit(reason);
    return true;
  }

  /** 采纳服务端返回的文档（服务端已完成事实守卫与原子应用） */
  replace(doc, reason = "server") {
    this.history.push(structuredClone(this.doc));
    this.future = [];
    this.doc = this._normalize(doc);
    this._save();
    this.emit(reason);
  }

  undo() {
    const prev = this.history.pop();
    if (!prev) return false;
    this.future.push(structuredClone(this.doc));
    this.doc = this._normalize(prev);
    this._save();
    this.emit("undo");
    return true;
  }

  redo() {
    const next = this.future.pop();
    if (!next) return false;
    this.history.push(structuredClone(this.doc));
    this.doc = this._normalize(next);
    this._save();
    this.emit("redo");
    return true;
  }

  canUndo() { return this.history.length > 0; }
  canRedo() { return this.future.length > 0; }

  // ------------------------------------------------------------------
  addModule(type, data = {}) {
    const spec = this.specs[type];
    if (!spec) return null;
    const id = uid("mod");
    const ok = this.commit((doc) => {
      const order = doc.modules.length ? Math.max(...doc.modules.map((m) => m.order || 0)) + 1 : 1;
      doc.modules.push({ id, type, order, collapsed: false, data: { ...normalizeData({ type, data }, this.specs), ...data } });
    }, "add-module");
    return ok ? id : null;
  }

  updateField(id, field, value) {
    return this.commit((doc) => {
      const module = doc.modules.find((m) => m.id === id);
      if (!module) return false;
      if (module.data[field] === value) return false;
      module.data[field] = value;
    }, `field:${id}`);
  }

  removeModule(id) {
    return this.commit((doc) => {
      const before = doc.modules.length;
      doc.modules = doc.modules.filter((m) => m.id !== id).map((m, i) => ({ ...m, order: i + 1 }));
      if (doc.modules.length === before) return false;
    }, "remove-module");
  }

  moveModule(id, delta) {
    return this.commit((doc) => {
      const sorted = [...doc.modules].sort((a, b) => a.order - b.order);
      const index = sorted.findIndex((m) => m.id === id);
      const target = index + delta;
      if (index < 0 || target < 0 || target >= sorted.length) return false;
      [sorted[index], sorted[target]] = [sorted[target], sorted[index]];
      sorted.forEach((m, i) => { m.order = i + 1; });
      doc.modules = sorted;
    }, "reorder");
  }

  toggleCollapsed(id) {
    return this.commit((doc) => {
      const module = doc.modules.find((m) => m.id === id);
      if (!module) return false;
      module.collapsed = !module.collapsed;
    }, "collapse");
  }

  setAppearance(patch) {
    return this.commit((doc) => {
      let changed = false;
      for (const [key, value] of Object.entries(patch)) {
        if (doc.appearance[key] !== value) {
          doc.appearance[key] = value;
          changed = true;
        }
      }
      if (!changed) return false;
    }, "appearance");
  }

  setTargetJob(job) {
    if ((this.doc.targetJob || "") === (job || "")) return false;
    return this.commit((doc) => { doc.targetJob = (job || "").slice(0, 120); }, "target-job");
  }

  // ------------------------------------------------------------------
  exportJson() {
    // 只导出文档与档案；不含 Key 与会话凭证
    return JSON.stringify({ kind: "jianmian-backup", version: 1, exportedAt: new Date().toISOString(), document: this.doc }, null, 2);
  }

  importJson(text) {
    const parsed = JSON.parse(text);
    const doc = parsed?.document || parsed;
    if (!doc || !Array.isArray(doc.modules)) throw new Error("文件结构不是简面导出的备份");
    this.replace(doc, "import");
  }

  _save() {
    try {
      localStorage.setItem(KEY_V2, JSON.stringify(this.doc));
    } catch (err) {
      this.warnings.push("本地保存失败（可能超出存储上限），请先导出 JSON 备份");
    }
  }
}
