/* 工作台的两块面板：左边「模块库 + 已编辑」，右边「编辑 · 某一段」。
 *
 * 全部由模块注册表驱动：加一种模块类型只改后端 MODULE_SPECS，
 * 这里的序号、名称、字段、权限标签都会自己长出来。
 */

import { el, toast } from "./util.js";

const POLICY_TEXT = { locked: "硬事实", guarded: "可改写", open: "可表达", asset: "人工上传" };

export class Editor {
  constructor({ paletteEl, listEl, emptyEl, inspFields, inspTitle, inspSub, specs, store, onSelect }) {
    this.paletteEl = paletteEl;
    this.listEl = listEl;
    this.emptyEl = emptyEl;
    this.inspFields = inspFields;
    this.inspTitle = inspTitle;
    this.inspSub = inspSub;
    this.specs = specs;
    this.store = store;
    this.onSelect = onSelect;
    this.selectedId = null;
    this.renderPalette();
  }

  get selected() {
    return this.store.doc.modules.find((m) => m.id === this.selectedId) || null;
  }

  select(id) {
    this.selectedId = id;
    this.onSelect?.(id);
  }

  // ------------------------------------------------------------------ 模块库
  renderPalette() {
    const entries = Object.values(this.specs);
    this.paletteEl.replaceChildren(
      ...entries.map((spec, index) => {
        const present = this.store.doc.modules.some((m) => m.type === spec.type);
        const item = el("button", {
          class: `pal-item${present ? " is-present" : ""}`,
          type: "button",
          title: spec.multiple ? `添加${spec.zh}` : `${spec.zh}（同类只能有一段）`,
          dataset: { type: spec.type },
        }, [
          el("span", { class: "pal-num", text: String(index + 1).padStart(2, "0") }),
          el("span", { class: "pal-name", text: spec.zh }),
        ]);
        item.addEventListener("click", () => this.addOrFocus(spec.type));
        return item;
      })
    );
  }

  addOrFocus(type) {
    const spec = this.specs[type];
    const existing = this.store.doc.modules.filter((m) => m.type === type);
    if (existing.length && !spec.multiple) {
      this.select(existing[0].id);
      return;
    }
    const id = this.store.addModule(type);
    if (id) this.select(id);
  }

  // ------------------------------------------------------------------ 已编辑
  renderList(doc) {
    const modules = [...doc.modules].sort((a, b) => a.order - b.order);
    this.emptyEl.hidden = modules.length > 0;
    if (!modules.length) {
      this.listEl.replaceChildren();
      return;
    }
    if (!modules.some((m) => m.id === this.selectedId)) {
      // 默认选"最值得改"的那一段：叙述类优先，姓名电话没什么可润色的
      const order = ["project", "internship", "summary", "education"];
      const preferred =
        order.map((type) => modules.find((m) => m.type === type)).find(Boolean) ||
        modules.find((m) => m.type !== "basic") ||
        modules[0];
      this.selectedId = preferred.id;
    }

    this.listEl.replaceChildren(
      ...modules.map((module, index) => {
        const spec = this.specs[module.type];
        const row = el("div", {
          class: `pal-row${module.id === this.selectedId ? " is-active" : ""}`,
          dataset: { module: module.id },
        }, [
          el("span", { class: "pal-index", text: String(index + 1).padStart(2, "0") }),
          el("span", { class: "pal-row-main" }, [
            el("div", { class: "pal-row-title", text: this.titleOf(module) }),
            el("div", { class: "pal-row-type", text: spec?.zh || module.type }),
          ]),
          el("span", { class: "pal-acts" }, [
            act("↑", "上移", () => this.store.moveModule(module.id, -1), index === 0),
            act("↓", "下移", () => this.store.moveModule(module.id, 1), index === modules.length - 1),
            act("✕", "删除", () => {
              if (window.confirm(`删除「${this.titleOf(module)}」？可以用撤销恢复。`)) {
                const nextId = modules[index + 1]?.id || modules[index - 1]?.id || null;
                this.store.removeModule(module.id);
                this.selectedId = nextId;
                this.onSelect?.(nextId);
              }
            }, false, "is-danger"),
          ]),
        ]);
        row.addEventListener("click", (event) => {
          if (event.target.closest(".pal-act")) return;
          this.select(module.id);
        });
        return row;
      })
    );
  }

  refreshTitle(moduleId) {
    const module = this.store.doc.modules.find((m) => m.id === moduleId);
    const node = this.listEl.querySelector(`[data-module="${moduleId}"] .pal-row-title`);
    if (module && node) node.textContent = this.titleOf(module);
    if (module && module.id === this.selectedId) this.inspTitle.textContent = this.titleOf(module);
  }

  titleOf(module) {
    const spec = this.specs[module.type];
    if (!spec) return module.type;
    const field = spec.titleField ? module.data[spec.titleField] : "";
    if (field && String(field).trim()) return String(field).trim();
    const firstText = spec.fields.find((f) => f.kind !== "image" && String(module.data[f.name] || "").trim());
    if (firstText) return String(module.data[firstText.name]).trim().slice(0, 20);
    return spec.zh;
  }

  // ------------------------------------------------------------------ 右侧编辑
  renderInspector(doc) {
    const module = this.selected;
    this.inspFields.replaceChildren();
    if (!module) {
      this.inspTitle.textContent = "简历";
      this.inspSub.textContent = "没有选中任何一段";
      this.inspFields.append(
        el("p", {
          class: "insp-empty",
          text: "在左边选一段开始改。也可以直接说一句「把项目写得更专业」，让智能体先出一版提案。",
        })
      );
      return;
    }
    const spec = this.specs[module.type];
    this.inspTitle.textContent = this.titleOf(module);
    this.inspSub.textContent = spec.zh;
    for (const field of spec.fields) {
      this.inspFields.append(this.fieldNode(module, field));
    }
  }

  fieldNode(module, field) {
    const value = module.data[field.name] ?? "";
    const label = el("span", {}, [
      field.label,
      el("span", {
        class: `chip chip-${field.policy}`,
        text: POLICY_TEXT[field.policy] || field.policy,
        title: field.aiEditable ? "AI 可以改写这个字段" : "AI 不能写入这个字段",
      }),
    ]);

    if (field.kind === "image") {
      const wrap = el("label", { class: "field" }, [label]);
      if (value) {
        wrap.append(
          el("img", {
            src: value,
            alt: field.label,
            style: "width:60px;height:76px;object-fit:cover;border-radius:6px;border:1px solid #eee",
          }),
          el("button", {
            class: "tool",
            type: "button",
            text: "移除肖像",
            onclick: (event) => {
              event.preventDefault();
              this.store.updateField(module.id, field.name, "");
            },
          })
        );
      }
      const input = el("input", { type: "file", accept: "image/*" });
      input.addEventListener("change", async () => {
        const file = input.files?.[0];
        if (!file) return;
        if (file.size > field.maxLength * 1024) {
          toast("图片过大，请换一张更小的（头像上限约 2.7MB）", "warn");
          return;
        }
        const dataUrl = await readAsDataURL(file);
        this.store.updateField(module.id, field.name, dataUrl);
      });
      wrap.append(input);
      return wrap;
    }

    const control =
      field.kind === "text"
        ? el("textarea", {
            rows: field.maxLength > 600 ? 6 : 3,
            maxlength: field.maxLength,
            placeholder: `填写${field.label}`,
          })
        : el("input", { type: "text", maxlength: field.maxLength, placeholder: `填写${field.label}` });
    control.value = value;
    control.addEventListener("input", () => {
      this.store.updateField(module.id, field.name, control.value);
    });
    return el("label", { class: "field" }, [label, control]);
  }
}

function act(text, title, onClick, disabled = false, extra = "") {
  const button = el("button", {
    class: `pal-act ${extra}`.trim(),
    type: "button",
    title,
    text,
    disabled,
  });
  if (disabled) button.style.opacity = "0.3";
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!disabled) onClick();
  });
  return button;
}

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
