/* 岗位对齐面板：结论 + 证据 + 免责说明三件套。 */

import { el, toast } from "./util.js";

const CATEGORY_TEXT = { matched: "已有证据", partial: "部分相关", missing: "暂无证据" };

export class Jobs {
  constructor({ api, store, els }) {
    this.api = api;
    this.store = store;
    this.els = els;
    this.els.matchBtn.addEventListener("click", () => this.match());
  }

  async match() {
    const job = this.els.jobInput.value.trim() || this.store.doc.targetJob;
    if (!job) {
      toast("先填一个目标岗位", "warn");
      return;
    }
    this.store.setTargetJob(job);
    this.els.matchBtn.disabled = true;
    this.els.result.replaceChildren(el("p", { class: "hint", text: "正在对照岗位样本与你的原文…" }));
    try {
      const report = await this.api.post("/api/jobs/match", {
        targetJob: job,
        city: this.els.cityInput.value.trim(),
        document: this.store.doc,
        limit: 5,
      });
      this.render(report);
    } catch (err) {
      this.els.result.replaceChildren(el("p", { class: "hint", text: "分析失败：" + err.message }));
    } finally {
      this.els.matchBtn.disabled = false;
    }
  }

  render(report) {
    const counts = { matched: 0, partial: 0, missing: 0 };
    for (const hit of report.hits || []) counts[hit.category] += 1;

    const stats = el("div", { class: "stat-row" }, [
      stat(counts.matched, "已有证据"),
      stat(counts.partial, "部分相关"),
      stat(counts.missing, "暂无证据"),
      stat((report.citations || []).length, "岗位样本"),
    ]);

    const hits = el("div", { class: "hit-list" }, (report.hits || []).map((hit) =>
      el("div", { class: "hit" }, [
        el("div", { class: "hit-head" }, [
          el("strong", { text: hit.skill }),
          el("span", { class: `badge badge-${hit.category}`, text: CATEGORY_TEXT[hit.category] || hit.category }),
        ]),
        hit.resumeSpans?.length
          ? el("span", { class: "evidence", text: "简历原文：" + hit.resumeSpans[0] })
          : el("span", { class: "evidence", text: "简历里还没有对应表述" }),
        hit.suggestion ? el("div", { class: "op-reason", text: hit.suggestion }) : null,
      ])
    ));

    const sources = (report.citations || []).length
      ? el("div", { class: "meta-line" }, [
          el("div", { text: "样本来源：" }),
          ...report.citations.map((citation) =>
            el("div", {
              text: `· ${citation.role}｜${citation.city || "城市未知"}｜${citation.sourceName}${citation.isSample ? "（课程样本）" : ""}`,
            })
          ),
        ])
      : el("p", { class: "hint", text: "没有检索到岗位样本。可以直接把 JD 文本粘到对话框里，我按原文对照。" });

    this.els.result.replaceChildren(
      stats,
      hits,
      sources,
      el("p", { class: "disclaimer", text: report.disclaimer || "" })
    );
  }
}

function stat(value, label) {
  return el("div", { class: "stat" }, [el("b", { text: String(value) }), el("span", { text: label })]);
}
