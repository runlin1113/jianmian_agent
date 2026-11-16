/* 模拟面试：逐轮问答 + 可解释复盘。 */

import { el, toast } from "./util.js";

const STATE_TEXT = {
  preparing: "准备中",
  questioning: "提问中",
  awaiting_answer: "等你回答",
  probing: "追问中",
  summarizing: "总结中",
  finished: "已完成",
};

export class Interview {
  constructor({ api, store, els }) {
    this.api = api;
    this.store = store;
    this.els = els;
    this.session = null;
    this.els.startBtn.addEventListener("click", () => this.start());
    this.els.sendBtn.addEventListener("click", () => this.send());
  }

  async start() {
    const job = this.els.jobInput.value.trim() || this.store.doc.targetJob || "目标岗位";
    this.els.startBtn.disabled = true;
    try {
      const session = await this.api.post("/api/interviews", {
        document: this.store.doc,
        targetJob: job,
      });
      this.session = session;
      this.els.thread.replaceChildren();
      this.els.report.replaceChildren();
      this.renderSession(session);
      this.appendQuestion(session.question || session.turns?.at(-1)?.question || "");
      this.els.answerBox.hidden = false;
      this.els.answer.focus();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      this.els.startBtn.disabled = false;
    }
  }

  renderSession(session) {
    const progress = session.progress || {};
    this.els.progress.hidden = false;
    this.els.progress.textContent = [
      `状态：${STATE_TEXT[progress.state] || progress.state}`,
      `主题 ${Math.min((progress.topicIndex || 0) + 1, progress.topicTotal || 1)} / ${progress.topicTotal || 1}`,
      `已回答 ${progress.answered || 0} 题`,
      `评分规则版本 ${progress.rubricVersion || "-"}`,
    ].join(" · ");
  }

  appendQuestion(question) {
    if (!question) return;
    this.els.thread.append(
      el("div", { class: "iv-turn" }, [
        el("div", { class: "iv-topic", text: "面试官" }),
        el("div", { class: "iv-q", text: question }),
      ])
    );
  }

  appendAnswer(question, answer) {
    this.els.thread.append(
      el("div", { class: "iv-turn" }, [
        el("div", { class: "iv-topic", text: "面试官" }),
        el("div", { class: "iv-q", text: question }),
        el("div", { class: "iv-a", text: "你的回答：" + answer }),
      ])
    );
  }

  async send() {
    if (!this.session) return;
    const answer = this.els.answer.value.trim();
    if (!answer) {
      toast("先写点内容", "warn");
      return;
    }
    const turn = this.session.turns?.at(-1);
    if (!turn) return;
    this.els.sendBtn.disabled = true;
    try {
      const result = await this.api.post(`/api/interviews/${this.session.interviewId}/turns`, {
        turnId: turn.turnId,
        answer,
      });
      this.appendAnswer(turn.question, answer);
      this.els.answer.value = "";
      this.session = result.session;
      this.renderSession(result.session);
      if (result.finished) {
        this.els.answerBox.hidden = true;
        this.renderReport(result.report);
        toast("面试完成，已生成复盘");
      } else {
        this.appendQuestion(result.question || result.session.turns?.at(-1)?.question || "");
        this.els.answer.focus();
      }
    } catch (err) {
      if (err.code === "turn_conflict") {
        toast("这一题已经在别处提交过了", "warn");
      } else {
        toast(err.message, "error");
      }
    } finally {
      this.els.sendBtn.disabled = false;
    }
  }

  renderReport(report) {
    if (!report) return;
    const scores = (report.scores || report.items || []).map((item) =>
      el("div", { class: "hit" }, [
        el("div", { class: "hit-head" }, [
          el("strong", { text: item.dimension || item.name || item.topicId || "维度" }),
          el("span", { class: "badge badge-partial", text: `${item.score ?? "-"} 分` }),
        ]),
        item.evidence ? el("span", { class: "evidence", text: "依据：" + item.evidence }) : null,
        item.advice ? el("div", { class: "op-reason", text: item.advice }) : null,
      ])
    );
    this.els.report.replaceChildren(
      el("h3", { class: "sub-head", text: "复盘" }),
      el("p", { class: "hint", text: report.summary || "以下评分是规则基线，不是模型主观打分。" }),
      el("div", { class: "hit-list" }, scores),
      ...(report.suggestions || []).map((text) => el("p", { class: "disclaimer", text: "· " + text }))
    );
  }
}
