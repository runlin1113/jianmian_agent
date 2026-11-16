/* A4 预览与真实版面测量。
 *
 * 这里做的是"真的排版"而不是等比缩放截图：
 * 每页 794×1123px（96dpi 的 A4），按块高流式分页，
 * 结果（页数、溢出像素、块高、最小字号）回传给服务端做压缩判断。
 */

import { el } from "./util.js";

const PAGE_W = 794;
const PAGE_H = 1123;
const PAD_TOP = 46;
const PAD_BOTTOM = 44;
const HEADER_GAP = 14;
const INNER_H = PAGE_H - PAD_TOP - PAD_BOTTOM;

const SPLIT_RE = /[、,，;；/|\n]+/;

export class Preview {
  constructor(container, { specs }) {
    this.container = container;
    this.specs = specs;
    this.themes = new Map();
    this.measurePage = null;
    this.zoomOverride = null;
  }

  setThemes(themes) {
    for (const theme of themes) this.themes.set(theme.id, theme);
  }

  applyTheme(themeId) {
    const theme = this.themes.get(themeId);
    if (!theme) return;
    document.documentElement.style.setProperty("--accent", theme.accent);
    document.documentElement.style.setProperty("--accent-soft", hexToSoft(theme.accent));
  }

  /** 渲染并测量，返回回传给服务端的版面数据 */
  render(doc) {
    const template = doc.appearance?.template || "executive";
    const twoColumn = template === "executive";
    this.applyTheme(doc.appearance?.theme);

    const modules = [...doc.modules].sort((a, b) => a.order - b.order);
    const header = this._header(doc, modules);
    const mainBlocks = [];
    const sideBlocks = [];
    for (const module of modules) {
      const spec = this.specs[module.type];
      if (!spec) continue;
      if (module.type === "basic" || module.type === "portrait") continue;
      if (this._isEmpty(module)) continue;
      const node = this._block(module, spec, template);
      if (!node) continue;
      const bucket = twoColumn && spec.slot === "side" ? sideBlocks : mainBlocks;
      bucket.push({ moduleId: module.id, node });
    }

    // ---- 测量 ----
    const measure = this._ensureMeasure();
    measure.className = `page template-${template}`;
    const pad = measure.querySelector(".page-pad");
    pad.replaceChildren();
    const headerProbe = header.cloneNode(true);
    pad.append(headerProbe);
    const headerH = headerProbe.getBoundingClientRect().height + HEADER_GAP;

    const body = el("div", { class: "doc-body" }, [
      el("div", { class: "col col-main" }),
      el("div", { class: "col col-side" }),
    ]);
    pad.append(body);
    const mainCol = body.querySelector(".col-main");
    const sideCol = body.querySelector(".col-side");
    if (!twoColumn) sideCol.style.display = "none";

    const heights = {};
    for (const block of [...mainBlocks, ...sideBlocks]) {
      const probe = block.node.cloneNode(true);
      (mainBlocks.includes(block) ? mainCol : sideCol).append(probe);
      const rect = probe.getBoundingClientRect();
      heights[block.moduleId] = Math.round(rect.height * 10) / 10;
      probe.remove();
    }
    const firstFont = mainCol.querySelector(".blk-text, .blk-title");
    const probeFont = document.createElement("div");
    probeFont.className = "blk-text";
    probeFont.textContent = "字";
    mainCol.append(probeFont);
    const minFontPt = Math.round(parseFloat(getComputedStyle(probeFont).fontSize) * 0.75 * 10) / 10;
    probeFont.remove();
    pad.replaceChildren();  // 清空测量页

    // ---- 分页 ----
    const mainPages = flow(mainBlocks, headerH, heights);
    const sidePages = twoColumn ? flow(sideBlocks, headerH, heights) : [];
    const pageCount = Math.max(mainPages.pages.length, sidePages.pages?.length || 0, 1);

    // ---- 真正绘制 ----
    const pages = [];
    for (let i = 0; i < pageCount; i += 1) {
      const page = el("div", { class: `page template-${template}` });
      const pagePad = el("div", { class: "page-pad" });
      if (i === 0) pagePad.append(header.cloneNode(true));
      const pageBody = el("div", { class: "doc-body" }, [
        el("div", { class: "col col-main" }, (mainPages.pages[i] || []).map((b) => b.node.cloneNode(true))),
        el("div", { class: "col col-side" }, twoColumn ? (sidePages.pages[i] || []).map((b) => b.node.cloneNode(true)) : []),
      ]);
      if (!twoColumn) pageBody.querySelector(".col-side").style.display = "none";
      pagePad.append(pageBody);
      page.append(pagePad);
      pages.push(page);
    }

    const zoom = this.zoomOverride ?? Number(doc.appearance?.zoom) ?? 0.75;
    this.container.replaceChildren(...pages);
    this.container.style.transform = `scale(${zoom})`;
    const totalH = pageCount * PAGE_H + (pageCount - 1) * 26;
    this.container.style.marginBottom = `${Math.round(-(1 - zoom) * totalH)}px`;

    const overflowPx = Math.round(Math.max(mainPages.overflow, sidePages.overflow || 0));
    return {
      pageCount,
      overflowPx,
      blockHeights: heights,
      minFontPt,
      zoom,
    };
  }

  // ------------------------------------------------------------------
  _ensureMeasure() {
    if (this.measurePage && this.measurePage.isConnected) return this.measurePage;
    const page = el("div", { class: "page" });
    const pad = el("div", { class: "page-pad" });
    page.append(pad);
    page.style.position = "fixed";
    page.style.left = "-10000px";
    page.style.top = "0";
    page.style.visibility = "hidden";
    document.body.append(page);
    this.measurePage = page;
    return page;
  }

  _isEmpty(module) {
    const spec = this.specs[module.type];
    if (!spec) return true;
    return !spec.fields.some((f) => f.kind !== "image" && String(module.data?.[f.name] || "").trim());
  }

  _header(doc, modules) {
    const basic = modules.find((m) => m.type === "basic");
    const portrait = modules.find((m) => m.type === "portrait");
    const d = basic?.data || {};
    const contacts = [
      d.phone ? `电话 ${d.phone}` : "",
      d.email ? `邮箱 ${d.email}` : "",
      d.github || "",
    ].filter(Boolean);

    const top = el("div", { class: "doc-header-top" }, [
      el("div", {}, [
        el("div", { class: "doc-name", text: (d.name || "未命名").trim() }),
        d.job ? el("div", { class: "doc-job", text: d.job }) : null,
      ]),
      portrait?.data?.avatar
        ? el("img", { class: "doc-avatar", src: portrait.data.avatar, alt: "个人肖像" })
        : null,
    ]);
    const header = el("div", { class: "doc-header" }, [top]);
    if (contacts.length) {
      header.append(el("div", { class: "doc-contact" }, contacts.map((c) => el("span", { text: c }))));
    }
    return header;
  }

  _block(module, spec, template) {
    const d = module.data || {};
    const title = (text, when) =>
      el("div", { class: "blk-title" }, [el("span", { text }), when ? el("span", { class: "when", text: when }) : null]);

    let node = null;
    switch (module.type) {
      case "education": {
        node = el("div", { class: "blk" }, [
          title(spec.zh, d.time),
          [d.school, d.major, d.degree].filter(Boolean).length
            ? el("div", { class: "blk-sub", text: [d.school, d.major, d.degree].filter(Boolean).join(" · ") })
            : null,
          d.course ? el("div", { class: "blk-text", text: d.course }) : null,
        ]);
        break;
      }
      case "project": {
        node = el("div", { class: "blk" }, [
          title(d.proj_name || spec.zh, d.time),
          [d.role, d.tech].filter(Boolean).length
            ? el("div", { class: "blk-sub", text: [d.role, d.tech].filter(Boolean).join(" ｜ ") })
            : null,
          d.desc ? el("div", { class: "blk-text", text: d.desc }) : null,
        ]);
        break;
      }
      case "internship": {
        node = el("div", { class: "blk" }, [
          title(d.company || spec.zh, d.time),
          d.position ? el("div", { class: "blk-sub", text: d.position }) : null,
          d.desc ? el("div", { class: "blk-text", text: d.desc }) : null,
        ]);
        break;
      }
      case "honor": {
        node = el("div", { class: "blk" }, [
          title(d.honor_name || spec.zh, d.time),
          d.level ? el("div", { class: "blk-text", text: d.level }) : null,
        ]);
        break;
      }
      case "skills": {
        const items = String(d.skills || "").split(SPLIT_RE).map((s) => s.trim()).filter(Boolean);
        node = el("div", { class: "blk" }, [
          title(spec.zh),
          el("div", { class: "blk-skill" }, items.map((item) => el("span", { text: item }))),
        ]);
        break;
      }
      case "summary": {
        node = el("div", { class: "blk" }, [title(spec.zh), el("div", { class: "blk-text", text: d.eval || "" })]);
        break;
      }
      default:
        return null;
    }
    return node;
  }
}

/** 流式分页：块不拆分，整块推到下一页 */
function flow(blocks, headerH, heights) {
  const pages = [];
  let current = [];
  let used = 0;
  let overflow = 0;
  let firstPage = true;

  for (const block of blocks) {
    const h = heights[block.moduleId] || 0;
    const avail = firstPage ? INNER_H - headerH : INNER_H;
    if (used > 0 && used + h > avail) {
      pages.push(current);
      current = [];
      used = 0;
      firstPage = false;
    }
    current.push(block);
    used += h;
    const limit = firstPage ? INNER_H - headerH : INNER_H;
    if (used > limit) overflow = Math.max(overflow, used - limit);
  }
  if (current.length) pages.push(current);
  if (!pages.length) pages.push([]);
  return { pages, overflow };
}

function hexToSoft(hex) {
  const clean = String(hex).replace("#", "");
  const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const value = parseInt(full.slice(0, 6), 16);
  if (Number.isNaN(value)) return "rgba(20,54,90,0.09)";
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, 0.10)`;
}

export const PAGE = { width: PAGE_W, height: PAGE_H, inner: INNER_H };
