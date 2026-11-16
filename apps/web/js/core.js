/* 本地命令应用（与 domain/proposals.py 的闭集操作一一对应）。
 * 只用于"按候选测量版面"和乐观预览；真正落地前必须由服务端校验。 */

import { normalizeData, uid } from "./util.js";

export function applyOps(doc, ops, specs) {
  const out = structuredClone(doc);
  for (const op of ops) {
    switch (op.op) {
      case "replace_field": {
        const module = out.modules.find((m) => m.id === op.moduleId);
        if (module) module.data[op.field] = op.after;
        break;
      }
      case "add_module": {
        const order = out.modules.length ? Math.max(...out.modules.map((m) => m.order || 0)) + 1 : 1;
        out.modules.push({
          id: uid("mod"),
          type: op.moduleType,
          order,
          collapsed: true,
          data: normalizeData({ type: op.moduleType, data: op.data || {} }, specs),
        });
        break;
      }
      case "remove_module":
        out.modules = out.modules.filter((m) => m.id !== op.moduleId).map((m, i) => ({ ...m, order: i + 1 }));
        break;
      case "reorder_modules": {
        const map = new Map(out.modules.map((m) => [m.id, m]));
        const ordered = (op.order || []).map((id) => map.get(id)).filter(Boolean);
        ordered.forEach((m, i) => { m.order = i + 1; });
        out.modules = ordered;
        break;
      }
      case "change_appearance":
        Object.assign(out.appearance, op.changes || {});
        break;
      default:
        break;
    }
  }
  return out;
}

export function opLabel(op, doc, specs) {
  const moduleTitle = (id) => {
    const module = doc.modules.find((m) => m.id === id);
    if (!module) return id;
    const spec = specs[module.type];
    const titleField = spec?.titleField ? module.data[spec.titleField] : "";
    return String(titleField || spec?.zh || module.type);
  };
  const fieldLabel = (moduleId, field) => {
    const module = doc.modules.find((m) => m.id === moduleId);
    const spec = module ? specs[module.type] : null;
    return spec?.fields?.find((f) => f.name === field)?.label || field;
  };

  switch (op.op) {
    case "replace_field":
      return `改写 ${moduleTitle(op.moduleId)} · ${fieldLabel(op.moduleId, op.field)}`;
    case "add_module":
      return `新增模块：${specs[op.moduleType]?.zh || op.moduleType}`;
    case "remove_module":
      return `删除模块：${moduleTitle(op.moduleId)}`;
    case "reorder_modules":
      return "调整模块顺序";
    case "change_appearance":
      return `切换外观：${Object.entries(op.changes || {}).map(([k, v]) => `${k}=${v}`).join("，")}`;
    default:
      return op.op;
  }
}
