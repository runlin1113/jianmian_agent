/* 档案与记忆：候选 → 确认 → 可更正 → 可遗忘（三种删除语义分开）。 */

import { el, toast } from "./util.js";

export class Profile {
  constructor({ api, store, els }) {
    this.api = api;
    this.store = store;
    this.els = els;
    this.profile = { facts: [] };
    this.candidates = [];
    this.bind();
  }

  bind() {
    this.els.extractBtn.addEventListener("click", () => this.extract());
    this.els.exportBtn.addEventListener("click", () => this.exportJson());
    this.els.importJsonBtn.addEventListener("click", () => this.els.jsonInput.click());
    this.els.jsonInput.addEventListener("change", () => this.importJson());
  }

  async refresh() {
    try {
      this.profile = await this.api.get("/api/profile");
      this.renderFacts();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  facts() {
    return (this.profile.facts || []).map((fact) => fact.text);
  }

  async extract() {
    const text = this.els.memoryText.value.trim();
    if (text.length < 6) {
      toast("多写一点再提取", "warn");
      return;
    }
    this.els.extractBtn.disabled = true;
    try {
      const result = await this.api.post("/api/profile/extract", { text });
      this.candidates = result.candidates || [];
      this.renderCandidates(result.note);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      this.els.extractBtn.disabled = false;
    }
  }

  renderCandidates(note) {
    this.els.candidates.replaceChildren();
    if (note) this.els.candidates.append(el("p", { class: "hint", text: note }));
    const checks = [];
    this.candidates.forEach((candidate) => {
      const checkbox = el("input", { type: "checkbox", checked: true });
      checks.push(checkbox);
      const spec = el("div", { class: "candidate-main" }, [
        el("div", { class: "candidate-head" }, [
          el("span", { text: kindText(candidate.kind) }),
          el("span", { class: "conf", text: `把握度 ${Math.round((candidate.confidence || 0) * 100)}%` }),
        ]),
        el("pre", { text: candidate.text }),
        candidate.reason ? el("div", { class: "candidate-note", text: candidate.reason }) : null,
      ]);
      this.els.candidates.append(el("label", { class: "candidate" }, [checkbox, spec]));
    });
    if (!this.candidates.length) return;
    this.els.candidates.append(
      el("div", { class: "row-actions" }, [
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "确认保存选中项",
          onclick: () => this.confirm(checks),
        }),
      ])
    );
  }

  async confirm(checks) {
    const chosen = this.candidates.filter((_, index) => checks[index].checked);
    if (!chosen.length) {
      toast("至少选一条", "warn");
      return;
    }
    try {
      this.profile = await this.api.post("/api/profile/facts", { candidates: chosen });
      this.renderFacts();
      this.els.candidates.replaceChildren();
      this.els.memoryText.value = "";
      toast("已保存到本次会话档案");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  renderFacts() {
    const facts = this.profile.facts || [];
    this.els.factList.replaceChildren();
    if (!facts.length) {
      this.els.factList.append(el("li", { class: "muted", text: "还没有确认过的事实。" }));
      return;
    }
    for (const fact of facts) {
      this.els.factList.append(
        el("li", {}, [
          el("span", { text: fact.text }),
          el("button", {
            class: "btn btn-danger",
            type: "button",
            text: "忘记",
            onclick: () => this.forget(fact.id),
          }),
        ])
      );
    }
  }

  async forget(factId) {
    if (!window.confirm("停止记住这条事实？简历里已有的文字不会被删除。")) return;
    try {
      const result = await this.api.del(`/api/profile/facts/${factId}`);
      this.profile = result;
      this.renderFacts();
      const steps = result.plan?.steps || [];
      if (steps.length) {
        toast("已停止记忆；说明：" + steps[0], "info");
      }
    } catch (err) {
      toast(err.message, "error");
    }
  }

  exportJson() {
    const blob = new Blob([this.store.exportJson()], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = el("a", { href: url, download: `jianmian-backup-${Date.now()}.json` });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async importJson() {
    const file = this.els.jsonInput.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      this.store.importJson(text);
      toast("已恢复备份");
    } catch (err) {
      toast("恢复失败：" + err.message, "error");
    } finally {
      this.els.jsonInput.value = "";
    }
  }
}

function kindText(kind) {
  return {
    fact: "事实",
    project: "项目",
    skill: "技能",
    preference: "偏好",
    interest: "兴趣",
    job_preference: "岗位偏好",
  }[kind] || "事实";
}
