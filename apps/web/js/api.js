/* 与后端通信：统一带上 CSRF、统一解析错误体、SSE 用 fetch 流式读取。 */

export class ApiError extends Error {
  constructor({ code, message, status, requestId, retryable, details }) {
    super(message || "请求失败");
    this.code = code || "unknown";
    this.status = status || 0;
    this.requestId = requestId || "";
    this.retryable = Boolean(retryable);
    this.details = details || null;
  }
}

export class Api {
  constructor() {
    this.csrf = "";
    this.config = null;
    this.byok = null;
  }

  setByok(key) {
    // 只存内存，不写 localStorage
    this.byok = key && key.trim() ? key.trim() : null;
  }

  async init() {
    this.config = await this.get("/api/config", { retry: false });
    this.csrf = this.config.csrfToken;
    return this.config;
  }

  headers(extra = {}, withCsrf = true) {
    const headers = { accept: "application/json", ...extra };
    if (withCsrf && this.csrf) headers["x-jm-csrf"] = this.csrf;
    if (this.byok) headers["x-jm-byok"] = this.byok;
    return headers;
  }

  async request(path, { method = "GET", body, form, retry = true } = {}) {
    const options = { method, credentials: "same-origin", headers: this.headers() };
    if (form) {
      options.body = form;
      delete options.headers["content-type"];
    } else if (body !== undefined) {
      options.headers["content-type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (err) {
      throw new ApiError({ code: "network_error", message: "网络连接失败，请检查服务是否在运行", retryable: true });
    }
    if (response.status === 403) {
      const payload = await this._payload(response);
      const code = payload?.error?.code;
      if (retry && (code === "csrf_failed" || code === "session_missing")) {
        await this.init();  // 会话被刷新（例如清过 Cookie），续一次
        return this.request(path, { method, body, form, retry: false });
      }
      throw this._error(payload, response.status);
    }
    if (!response.ok) {
      const payload = await this._payload(response);
      throw this._error(payload, response.status);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async _payload(response) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  _error(payload, status) {
    const err = payload?.error || {};
    return new ApiError({
      code: err.code || "http_" + status,
      message: err.message || `请求失败（${status}）`,
      status,
      requestId: err.requestId,
      retryable: err.retryable,
      details: err.details,
    });
  }

  get(path, opts = {}) { return this.request(path, { ...opts, method: "GET" }); }
  post(path, body, opts = {}) { return this.request(path, { ...opts, method: "POST", body }); }
  del(path, opts = {}) { return this.request(path, { ...opts, method: "DELETE" }); }

  async upload(path, file) {
    const form = new FormData();
    form.append("file", file);
    return this.request(path, { method: "POST", form });
  }

  /**
   * 读取 SSE。返回 Promise，在服务端正常结束（含"等用户操作"）时 resolve。
   * onEvent 收到 {type, seq, data}。
   */
  async streamRun(runId, { after = 0, onEvent, signal } = {}) {
    const url = `/api/runs/${encodeURIComponent(runId)}/events?after=${after}`;
    const response = await fetch(url, {
      headers: { accept: "text/event-stream" },
      credentials: "same-origin",
      signal,
    });
    if (!response.ok) {
      const payload = await this._payload(response);
      throw this._error(payload, response.status);
    }
    if (!response.body) return;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let lastSeq = after;

    const handle = (chunk) => {
      const lines = chunk.split("\n");
      let type = "message";
      const dataLines = [];
      let seq = 0;
      for (const line of lines) {
        if (line.startsWith("event:")) type = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        else if (line.startsWith("id:")) seq = Number(line.slice(3).trim()) || 0;
      }
      if (!dataLines.length) return;
      let parsed = {};
      try {
        parsed = JSON.parse(dataLines.join("\n"));
      } catch {
        return;
      }
      lastSeq = seq || parsed.seq || lastSeq;
      onEvent?.({ type: parsed.type || type, seq: lastSeq, data: parsed.data || {} });
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        handle(buffer.slice(0, index));
        buffer = buffer.slice(index + 2);
      }
    }
    return lastSeq;
  }
}
