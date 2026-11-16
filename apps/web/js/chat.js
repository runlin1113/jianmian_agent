/* 对话：从一句话到一份简历，以及之后每一轮修改。
 *
 * 契约不变（架构书第 9、10、12 章）：
 * - 文本增量只用于展示，绝不边流边写进简历；
 * - 提案未确认前不改文档，确认时把当前文档回传，服务端重查版本与哈希；
 * - 版面测量由浏览器真实排版后回传。
 *
 * 这一版新增两件事：每轮说完把消息记进本地历史；改完之后给一张"简历卡"，
 * 点它进工作台——而不是把简历藏在侧边预览里。
 */

import { el, toast, guessTargetJob } from "./util.js";
import { applyOps, opLabel } from "./core.js";

export class Chat {
  constructor({ api, store, specs, preview, elements, getMemoryFacts, onLayout, onDone, onMessage, onOpenWorkspace, getPageCount }) {
    this.api = api;
    this.store = store;
    this.specs = specs;
    this.preview = preview;
    this.els = elements;
    this.getMemoryFacts = getMemoryFacts;
    this.onLayout = onLayout;
    this.onDone = onDone;
    this.onMessage = onMessage;
    this.onOpenWorkspace = onOpenWorkspace;
    this.getPageCount = getPageCount || (() => 1);

    this.run = null;
    this.pendingClarification = null;
    this.busy = false;
    this.shownClarifications = new Set();
    this.shownProposals = new Set();
    this.bind();
  }

  bind() {
    this.els.composer.addEventListener("submit", (event) => {
      event.preventDefault();
      this.submit();
    });
    this.els.input.addEventListener("input", () => this.autoGrow());
    this.els.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this.submit();
      }
    });
    this.els.stopBtn?.addEventListener("click", () => this.stop());
  }

  focus() {
    this.els.input.focus({ preventScroll: true });
  }

  autoGrow() {
    const input = this.els.input;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 168)}px`;
  }

  setInput(text) {
    this.els.input.value = text;
    this.autoGrow();
  }

  /** 由外部（工作台的"让智能体修改"、起始页的一句话）直接发一条 */
  send(text) {
    this.setInput(text || "");
    return this.submit();
  }

  setFlow(on) {
    this.els.view.dataset.state = on ? "flow" : "empty";
  }

  // ------------------------------------------------------------------
  async submit() {
    if (this.busy) return;
    const text = this.els.input.value.trim();
    if (!text) {
      const box = this.els.box;
      box.classList.remove("is-shake");
      void box.offsetWidth;
      box.classList.add("is-shake");
      this.setStatus("先说一句你的情况，或者告诉我这份简历要怎么改。");
      this.focus();
      return;
    }

    // 有待回答的问题时，直接把它当作回答，而不是新开一轮
    if (this.pendingClarification) {
      const clarification = this.pendingClarification;
      this.pendingClarification = null;
      this.els.input.value = "";
      this.autoGrow();
      this.appendUser(text);
      this.busy = true;
      this.setStatus("正在继续处理…");
      try {
        await this.api.post(`/api/runs/${clarification.runId}/decisions`, {
          kind: "clarification",
          promptId: clarification.promptId,
          answer: text,
        });
        await this.consume(clarification.runId, 0);
      } catch (err) {
        this.appendError(err);
        this.busy = false;
        this.setStatus("");
      }
      return;
    }

    // 这句话里已经说了想投什么，就别让他进去再回答一遍
    if (!(this.store.doc.targetJob || "")) {
      const job = guessTargetJob(text);
      if (job) this.store.setTargetJob(job);
    }

    this.appendUser(text);
    this.els.input.value = "";
    this.autoGrow();
    this.busy = true;
    this.replyBuffer = "";
    this.setStatus("正在准备工作副本…");
    try {
      const run = await this.api.post("/api/runs", {
        instruction: text,
        document: this.store.doc,
        targetJob: this.store.doc.targetJob || "",
        memoryFacts: (this.getMemoryFacts?.() || []).slice(0, 8),
        idempotencyKey: crypto.randomUUID(),
      });
      this.run = { id: run.runId };
      await this.consume(run.runId, 0);
    } catch (err) {
      this.appendError(err);
      this.busy = false;
      this.setStatus("");
    }
  }

  async stop() {
    if (!this.run) return;
    try {
      await this.api.post(`/api/runs/${this.run.id}/cancel`, {});
      this.appendAssistant("已按你的要求停止。已生成的内容没有写入简历。");
    } catch (err) {
      this.appendError(err);
    }
  }

  // ------------------------------------------------------------------
  async consume(runId, after) {
    this.setStatus("处理中…");
    this.els.sendBtn.disabled = true;
    if (this.els.stopBtn) this.els.stopBtn.hidden = false;
    const controller = new AbortController();
    this.controller = controller;
    let lastSeq = after;

    try {
      lastSeq = await this.api.streamRun(runId, {
        after,
        signal: controller.signal,
        onEvent: (event) => {
          if (typeof event.seq === "number") lastSeq = Math.max(lastSeq, event.seq);
          this.handleEvent(runId, event);
        },
      });
    } catch (err) {
      if (err.name !== "AbortError") this.appendError(err);
    }

    if (this.els.stopBtn) this.els.stopBtn.hidden = true;
    this.els.sendBtn.disabled = false;
    this.busy = false;
    this.setStatus("");

    if ((this.replyBuffer || "").trim()) {
      this.onMessage?.({ role: "assistant", text: this.replyBuffer.trim() });
      this.replyBuffer = "";
    }

    try {
      const snapshot = await this.api.get(`/api/runs/${runId}`);
      this.renderSnapshot(runId, snapshot);
    } catch (err) {
      this.appendError(err);
    }
    this.onDone?.();
  }

  handleEvent(runId, event) {
    const data = event.data || {};
    switch (event.type) {
      case "run.started":
        this.startSteps();
        break;
      case "step.started":
        this.addStep(data.step, data.label);
        this.setStatus(data.label || "处理中…");
        break;
      case "step.completed":
        this.finishStep(data.step, data);
        break;
      case "text.delta":
        this.appendAssistant(data.text || "");
        break;
      case "clarification.required":
        this.showClarification(runId, data);
        break;
      case "layout.required":
        this.handleLayout(runId, data);
        break;
      case "proposal.ready":
        this.showProposal(runId, data, data.operations || []);
        break;
      case "run.failed":
        this.appendError(data.error || { message: "处理失败" });
        break;
      case "run.cancelled":
        this.appendAssistant("任务已取消。");
        break;
      default:
        break;
    }
  }

  renderSnapshot(runId, snapshot) {
    if (snapshot.status === "failed" && snapshot.error) {
      this.appendError(snapshot.error);
      return;
    }
    if (snapshot.pending?.kind === "clarification") {
      this.showClarification(runId, {
        promptId: snapshot.pending.promptId,
        question: snapshot.pending.question,
        options: snapshot.pending.options || [],
      });
      return;
    }
    if (snapshot.pending?.kind === "layout") {
      this.handleLayout(runId, {
        promptId: snapshot.pending.promptId,
        candidateHash: snapshot.pending.candidateHash,
        minFontPt: snapshot.layout?.minFontPt || 10.5,
        operations: snapshot.proposal?.operations || [],
        attempt: snapshot.pending.attempts,
      });
      return;
    }
    if (snapshot.proposal && Array.isArray(snapshot.proposal.operations) && snapshot.proposal.operations.length) {
      this.showProposal(runId, snapshot.proposal, snapshot.proposal.operations);
      return;
    }
    // 跑完了却没有提案：不能只留一串步骤，必须说清楚为什么没改
    if (snapshot.status === "ready") {
      const warn = (snapshot.warnings || []).find((item) => item.kind === "no_change");
      this.sayOnce(snapshot.message || warn?.detail || "这次没有需要改动的地方，简历保持原样。");
    }
  }

  // ------------------------------------------------------------------
  // 步骤时间线
  // ------------------------------------------------------------------
  startSteps() {
    this.stepsEl = el("div", { class: "step-list" });
    this.stepsMap = new Map();
    this.els.chatScroll.append(this.stepsEl);
    this.scrollDown();
  }

  addStep(step, label) {
    if (!this.stepsEl || !this.stepsEl.isConnected) this.startSteps();
    const key = step || label;
    const row = el("div", { class: "step is-running" }, [
      el("span", { class: "step-dot" }),
      el("span", { text: label || step }),
    ]);
    this.stepsEl.append(row);
    this.stepsMap.set(key, row);
    this.scrollDown();
  }

  finishStep(step, data) {
    const row = this.stepsMap?.get(step);
    if (!row) return;
    row.classList.remove("is-running");
    row.classList.add("is-done");
    if (data?.error) row.append(el("span", { class: "muted", text: `（${data.error}）` }));
  }

  // ------------------------------------------------------------------
  // 澄清
  // ------------------------------------------------------------------
  showClarification(runId, data) {
    if (data.promptId && this.shownClarifications.has(data.promptId)) {
      this.pendingClarification = { runId, promptId: data.promptId };
      return;
    }
    if (data.promptId) this.shownClarifications.add(data.promptId);
    this.pendingClarification = { runId, promptId: data.promptId };
    const card = el("div", { class: "msg msg-assistant" }, [
      el("p", { text: data.question || "需要你补充一点信息" }),
    ]);
    const options = data.options || [];
    if (options.length) {
      const row = el("div", { class: "row-actions", style: "margin-top:8px" });
      for (const option of options) {
        const value = option.value || option.moduleId || option.label || option.intent || "";
        const label = option.label || option.moduleId || value;
        row.append(
          el("button", {
            class: "tool",
            type: "button",
            text: label,
            style: "border-color:#e0e0e0;color:#1a1a1a;background:#fff",
            onclick: () => this.answerClarification(runId, data.promptId, value, option.intent),
          })
        );
      }
      card.append(row);
    } else {
      card.append(el("p", { class: "muted", style: "margin-top:6px", text: "直接在下面输入框回答即可。" }));
    }
    this.els.chatScroll.append(card);
    this.scrollDown();
    this.focus();
  }

  async answerClarification(runId, promptId, value, intent) {
    if (this.busy) return;
    this.busy = true;
    this.pendingClarification = null;
    this.appendUser(value);
    this.setStatus("正在继续处理…");
    try {
      await this.api.post(`/api/runs/${runId}/decisions`, {
        kind: "clarification",
        promptId,
        optionValue: value,
        intent: intent || null,
      });
      await this.consume(runId, 0);
    } catch (err) {
      this.appendError(err);
      this.busy = false;
      this.setStatus("");
    }
  }

  // ------------------------------------------------------------------
  // 版面测量
  // ------------------------------------------------------------------
  async handleLayout(runId, data) {
    const ops = data.operations || [];
    const candidate = ops.length ? applyOps(this.store.doc, ops, this.specs) : this.store.doc;
    let report;
    try {
      report = this.preview.render(candidate);
    } catch (err) {
      this.appendError({ message: "版面测量失败：" + err.message });
      return;
    }
    this.onLayout?.(candidate, report);
    this.setStatus("已测量真实版面，正在判断是否需要压缩…");
    try {
      await this.api.post(`/api/runs/${runId}/decisions`, {
        kind: "layout",
        layout: {
          pageCount: report.pageCount,
          overflowPx: report.overflowPx,
          blockHeights: report.blockHeights,
          minFontPt: report.minFontPt,
          candidateHash: data.candidateHash || "",
          rendererVersion: "web-1",
          fontVersion: document.fonts?.status || "loaded",
          viewportWidth: 794,
        },
      });
      await this.consume(runId, 0);
    } catch (err) {
      this.appendError(err);
      this.onLayout?.(this.store.doc, this.preview.render(this.store.doc));
    }
  }

  // ------------------------------------------------------------------
  // 提案
  // ------------------------------------------------------------------
  showProposal(runId, proposal, operations) {
    const fingerprint = `${proposal.proposalId}:${(operations || []).length}`;
    if (proposal.proposalId && this.shownProposals.has(fingerprint)) return;
    if (proposal.proposalId) this.shownProposals.add(fingerprint);
    const state = { runId, proposalId: proposal.proposalId };
    const ops = operations || [];
    const checks = [];
    const list = el("div", { class: "msg-card-body" });

    ops.forEach((op) => {
      const checkbox = el("input", { type: "checkbox", checked: true });
      checks.push(checkbox);
      const diff = el("div", { class: "op-diff" }, [
        el("div", { class: "op-label", text: opLabel(op, this.store.doc, this.specs) }),
        op.before ? el("div", { class: "op-before", text: op.before }) : null,
        op.after ? el("div", { class: "op-after", text: op.after }) : null,
        op.op === "add_module" && op.data
          ? el("div", {
              class: "op-after",
              text: Object.entries(op.data)
                .filter(([, value]) => String(value).trim())
                .map(([key, value]) => `${this.labelOf(op.moduleType, key)}：${value}`)
                .join(" · "),
            })
          : null,
        op.reason ? el("div", { class: "op-reason", text: op.reason }) : null,
      ]);
      list.append(el("label", { class: "op" }, [checkbox, diff]));
    });
    if (!ops.length) list.append(el("p", { class: "muted", text: "本次没有需要改动的内容。" }));

    const foot = el("div", { class: "msg-card-foot" });
    foot.append(
      el("button", {
        class: "agent-btn",
        type: "button",
        text: ops.length ? "采纳选中项" : "知道了",
        onclick: () => this.acceptProposal(checks, ops, state),
      })
    );
    if (ops.length) {
      foot.append(
        el("button", {
          class: "tool",
          type: "button",
          text: "全部放弃",
          onclick: () => this.rejectProposal(state),
        })
      );
    }

    const card = el("div", { class: "msg-card" }, [
      el("div", { class: "msg-card-head", text: proposal.summary || "修改建议" }),
      list,
      foot,
    ]);
    this.els.chatScroll.append(card);
    this.scrollDown();
  }

  labelOf(moduleType, fieldName) {
    const spec = this.specs[moduleType];
    return spec?.fields?.find((field) => field.name === fieldName)?.label || fieldName;
  }

  async acceptProposal(checks, ops, state) {
    if (!state || this.busy) return;
    const indexes = ops.map((_, index) => index).filter((index) => checks[index].checked);
    if (ops.length && !indexes.length) {
      toast("至少选择一项", "warn");
      return;
    }
    this.busy = true;
    try {
      const result = await this.api.post(`/api/runs/${state.runId}/decisions`, {
        kind: "proposal",
        action: "accept",
        document: this.store.doc,
        opIndexes: ops.length ? indexes : null,
      });
      if (result.applied && result.document) {
        this.store.replace(result.document, "proposal-applied");
        const revision = result.revision ?? result.document.revision;
        this.appendAssistant(
          result.replayed
            ? "这批修改之前已经应用过了，简历没有重复改动。"
            : `已应用 ${ops.length ? indexes.length : 0} 处修改，版本 v${revision}。`
        );
        (result.warnings || []).forEach((warning) => toast(warning.detail || warning.kind, "warn"));
        this.showResumeCard();
      } else {
        this.appendAssistant("已放弃这批修改，简历没有变化。");
      }
    } catch (err) {
      if (err.code === "revision_conflict" || err.code === "candidate_mismatch") {
        this.appendError({ message: "简历在生成提案后又被改过，这份提案已失效。请重新发一次指令。" });
      } else if (err.code === "proposal_expired") {
        this.appendError({ message: "提案已过期（30 分钟），请重新生成。" });
      } else if (err.code === "fact_guard_failed") {
        this.appendError({ message: "这批修改会改动数字或日期，我已拒绝应用。请核对原始信息。" });
      } else {
        this.appendError(err);
      }
    } finally {
      this.busy = false;
    }
  }

  async rejectProposal(state) {
    if (!state) return;
    try {
      await this.api.post(`/api/runs/${state.runId}/decisions`, { kind: "proposal", action: "reject" });
      this.appendAssistant("已放弃这批修改。");
    } catch (err) {
      this.appendError(err);
    }
  }

  // ------------------------------------------------------------------
  // 简历卡：改完之后，点一下进工作台
  // ------------------------------------------------------------------
  showResumeCard() {
    const doc = this.store.doc;
    const count = doc.modules.length;
    if (!count) return;
    const pages = this.getPageCount() || 1;
    const card = el(
      "button",
      { class: "resume-card", type: "button" },
      [
        el("span", { class: "resume-thumb" }, [el("i"), el("i"), el("i"), el("i"), el("i")]),
        el("span", { class: "resume-main" }, [
          el("span", { class: "resume-title", text: this.resumeTitle() }),
          el("span", { class: "resume-meta", text: `${count} 段 · ${pages} 页 · 版本 v${doc.revision}` }),
        ]),
        el("span", { class: "resume-go", text: "打开工作台 →" }),
      ]
    );
    card.addEventListener("click", () => this.onOpenWorkspace?.());
    this.els.chatScroll.append(card);
    this.onMessage?.({ role: "card", text: `${count} 段 · ${pages} 页` });
    this.scrollDown();
  }

  resumeTitle() {
    const basic = this.store.doc.modules.find((m) => m.type === "basic");
    const name = String(basic?.data?.name || "").trim();
    const job = String(this.store.doc.targetJob || basic?.data?.job || "").trim();
    if (name && job) return `${name} · ${job}`;
    return name || job || "你的简历";
  }

  // ------------------------------------------------------------------
  appendUser(text) {
    this.setFlow(true);
    this.els.chatScroll.append(el("div", { class: "msg msg-user" }, [el("span", { text })]));
    this.onMessage?.({ role: "user", text });
    this.scrollDown();
  }

  appendAssistant(text) {
    if (!text) return;
    this.setFlow(true);
    const last = this.els.chatScroll.lastElementChild;
    if (last && last.dataset.streaming === "1") {
      last.querySelector("p").textContent += text;
      this.scrollDown();
      return;
    }
    const bubble = el("div", { class: "msg msg-assistant", dataset: { streaming: "1" } }, [
      el("p", { text }),
    ]);
    this.els.chatScroll.append(bubble);
    this.scrollDown();
    clearTimeout(this._streamTimer);
    this._streamTimer = setTimeout(() => {
      bubble.dataset.streaming = "0";
    }, 700);
    // 一轮里可能吐出好几段文本，攒到流结束再整条进历史，避免历史被碎片撑满
    this.replyBuffer = (this.replyBuffer || "") + text;
  }

  appendError(error) {
    this.setFlow(true);
    const message = error?.message || "处理失败";
    const code = error?.code ? `（${error.code}）` : "";
    const bubble = el("div", { class: "msg msg-error" }, [
      el("p", { text: message + code }),
      error?.requestId ? el("p", { class: "muted", text: "请求号：" + error.requestId }) : null,
      error?.retryable ? el("p", { class: "muted", text: "这个错误可以重试。" }) : null,
    ]);
    this.els.chatScroll.append(bubble);
    this.onMessage?.({ role: "error", text: message });
    this.scrollDown();
  }

  /** 同一句话不重复说（服务端可能已经流式说过一遍） */
  sayOnce(text) {
    if (!text) return;
    const bubbles = this.els.chatScroll.querySelectorAll(".msg-assistant > p");
    const last = bubbles[bubbles.length - 1];
    if (last && last.textContent.slice(0, 10) === String(text).slice(0, 10)) return;
    this.appendAssistant(text);
  }

  setStatus(text) {
    this.els.status.textContent = text || "";
  }

  scrollDown() {
    this.els.chatScroll.scrollTop = this.els.chatScroll.scrollHeight;
  }

  // ------------------------------------------------------------------
  /** 从历史里恢复一段对话：只回放纯文本与简历卡，提案与澄清不重放 */
  restore(messages) {
    this.els.chatScroll.replaceChildren();
    this.setFlow(false);
    if (!messages?.length) return;
    for (const message of messages) {
      if (message.role === "user") {
        this.els.chatScroll.append(el("div", { class: "msg msg-user" }, [el("span", { text: message.text })]));
      } else if (message.role === "assistant") {
        this.els.chatScroll.append(
          el("div", { class: "msg msg-assistant" }, [el("p", { text: message.text })])
        );
      } else if (message.role === "error") {
        this.els.chatScroll.append(
          el("div", { class: "msg msg-error" }, [el("p", { text: message.text })])
        );
      } else if (message.role === "card" && this.store.doc.modules.length) {
        const card = el("button", { class: "resume-card", type: "button" }, [
          el("span", { class: "resume-thumb" }, [el("i"), el("i"), el("i"), el("i"), el("i")]),
          el("span", { class: "resume-main" }, [
            el("span", { class: "resume-title", text: this.resumeTitle() }),
            el("span", { class: "resume-meta", text: message.text }),
          ]),
          el("span", { class: "resume-go", text: "打开工作台 →" }),
        ]);
        card.addEventListener("click", () => this.onOpenWorkspace?.());
        this.els.chatScroll.append(card);
      }
    }
    this.setFlow(true);
    this.scrollDown();
  }
}
