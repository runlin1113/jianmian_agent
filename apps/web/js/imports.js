/* 导入：文件 → 暂存区 → 逐条合并。
 * 抽不到的内容保持空白，绝不用模型补一个"看起来合理"的学校名。 */

import { el, toast } from "./util.js";

export class Imports {
  constructor({ api, store, specs, els }) {
    this.api = api;
    this.store = store;
    this.specs = specs;
    this.els = els;
    this.draft = null;
    this.checked = new Set();
    this.bind();
  }

  bind() {
    this.els.dropzone.addEventListener("click", () => this.els.fileInput.click());
    this.els.fileInput.addEventListener("change", () => {
      const file = this.els.fileInput.files?.[0];
      if (file) this.upload(file);
      this.els.fileInput.value = "";
    });
    ["dragenter", "dragover"].forEach((type) =>
      this.els.dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        this.els.dropzone.classList.add("is-over");
      })
    );
    ["dragleave", "drop"].forEach((type) =>
      this.els.dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        this.els.dropzone.classList.remove("is-over");
      })
    );
    this.els.dropzone.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) this.upload(file);
    });
    this.els.mergeBtn.addEventListener("click", () => this.merge());
    this.els.discardBtn.addEventListener("click", () => this.clear());
  }

  async upload(file) {
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      toast("只支持 PDF 与 DOCX", "warn");
      return;
    }
    this.els.dropzone.classList.add("is-busy");
    try {
      const draft = await this.api.upload("/api/imports", file);
      this.draft = draft;
      this.checked = new Set(draft.candidates.map((_, index) => index));
      this.render(draft);
      if (draft.meta?.needsOcr) toast("这份文件文字很少，可能是扫描件，请逐条核对", "warn");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      this.els.dropzone.classList.remove("is-busy");
    }
  }

  render(draft) {
    const meta = draft.meta || {};
    this.els.meta.hidden = false;
    const bits = [
      `解析引擎：${meta.engine}`,
      `页数：${meta.pageCount || 1}`,
      `文本覆盖率：${Math.round((meta.textCoverage || 0) * 100)}%`,
      `候选模块：${draft.candidates.length}`,
    ];
    if (meta.twoColumnSuspected) bits.push("检测到疑似双栏，顺序可能需要手动调整");
    if (meta.needsOcr) bits.push("文字覆盖率低，建议直接粘贴或手工补全");
    this.els.meta.textContent = bits.join(" · ");

    this.els.candidates.replaceChildren();
    if (!draft.candidates.length) {
      this.els.candidates.append(
        el("p", { class: "hint", text: "没有识别出可用的模块。可以把原文粘到右侧对话框，我按内容整理。" })
      );
    }
    draft.candidates.forEach((candidate, index) => {
      const checkbox = el("input", { type: "checkbox", checked: true });
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) this.checked.add(index);
        else this.checked.delete(index);
      });
      const spec = this.specs[candidate.moduleType];
      const rows = Object.entries(candidate.data || {})
        .filter(([, value]) => String(value).trim())
        .map(([key, value]) => {
          const label = spec?.fields?.find((f) => f.name === key)?.label || key;
          return `${label}：${value}`;
        });
      this.els.candidates.append(
        el("label", { class: "candidate" }, [
          checkbox,
          el("div", { class: "candidate-main" }, [
            el("div", { class: "candidate-head" }, [
              spec?.zh || candidate.moduleType,
              el("span", { class: "conf", text: `把握度 ${Math.round((candidate.confidence || 0) * 100)}%` }),
            ]),
            el("pre", { text: rows.join("\n") }),
            candidate.note ? el("div", { class: "candidate-note", text: candidate.note }) : null,
          ]),
        ])
      );
    });
    this.els.actions.hidden = !draft.candidates.length;
  }

  merge() {
    if (!this.draft) return;
    const chosen = this.draft.candidates.filter((_, index) => this.checked.has(index));
    if (!chosen.length) {
      toast("至少选一条", "warn");
      return;
    }
    let added = 0;
    let filled = 0;
    this.store.commit((doc) => {
      for (const candidate of chosen) {
        const spec = this.specs[candidate.moduleType];
        if (!spec) continue;
        if (!spec.multiple) {
          const existing = doc.modules.find((m) => m.type === candidate.moduleType);
          if (existing) {
            for (const [key, value] of Object.entries(candidate.data)) {
              if (!String(value).trim()) continue;
              if (!String(existing.data[key] || "").trim()) {
                existing.data[key] = value;
                filled += 1;
              }
            }
            continue;
          }
        }
        const order = doc.modules.length ? Math.max(...doc.modules.map((m) => m.order || 0)) + 1 : 1;
        const data = {};
        for (const field of spec.fields) data[field.name] = String(candidate.data[field.name] || "");
        if (!Object.values(data).some((v) => v.trim())) continue;
        doc.modules.push({
          id: `mod-${Math.random().toString(16).slice(2, 9)}`,
          type: candidate.moduleType,
          order,
          collapsed: true,
          data,
        });
        added += 1;
      }
    }, "import-merge");

    toast(`已合并：新增 ${added} 个模块，补全 ${filled} 个字段`, "info");
    this.clear();
  }

  clear() {
    this.draft = null;
    this.checked.clear();
    this.els.candidates.replaceChildren();
    this.els.meta.hidden = true;
    this.els.actions.hidden = true;
  }
}
