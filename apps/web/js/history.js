/* 对话历史（本地）。
 *
 * 简历主数据在 Store 里，这里只存"说过什么"，不动简历本身：
 * 换一段对话不会换一份简历——产品上就是"一个人，一份简历，很多次讨论"。
 * 只存纯文本与卡片标记，不存提案快照（提案本来就有 30 分钟有效期）。
 */

const KEY = "jianmian_chats_v1";
const MAX_CHATS = 40;
const MAX_MESSAGES = 240;

const uid = () => `c-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export class History {
  constructor() {
    this.items = load();
    this.activeId = this.items[0]?.id || null;
    this.listeners = [];
  }

  onChange(fn) {
    this.listeners.push(fn);
  }

  notify() {
    this.save();
    for (const fn of this.listeners) fn(this.items, this.activeId);
  }

  get active() {
    return this.items.find((item) => item.id === this.activeId) || null;
  }

  messages() {
    return this.active?.messages || [];
  }

  start() {
    const current = this.active;
    // 当前这段还是空的：复用它，避免连点"新对话"塞一串空条目
    if (current && !current.messages.length) return current;
    const chat = { id: uid(), title: "新对话", updatedAt: Date.now(), messages: [] };
    this.items.unshift(chat);
    this.activeId = chat.id;
    this.items = this.items.slice(0, MAX_CHATS);
    this.notify();
    return chat;
  }

  open(id) {
    this.activeId = id;
    this.notify();
    return this.messages();
  }

  remove(id) {
    this.items = this.items.filter((item) => item.id !== id);
    if (this.activeId === id) this.activeId = this.items[0]?.id || null;
    this.notify();
  }

  /** 记录一条消息：{role:'user'|'assistant'|'error'|'card', text} */
  append(message) {
    let chat = this.active;
    if (!chat) chat = this.start();
    chat.messages.push({ ...message, at: Date.now() });
    if (chat.messages.length > MAX_MESSAGES) chat.messages = chat.messages.slice(-MAX_MESSAGES);
    if (message.role === "user" && (chat.title === "新对话" || !chat.title)) {
      chat.title = String(message.text || "").replace(/\s+/g, " ").slice(0, 22) || "新对话";
    }
    chat.updatedAt = Date.now();
    // 最近说过的排在最前
    this.items.sort((a, b) => b.updatedAt - a.updatedAt);
    this.notify();
    return chat;
  }

  /** 清空全部历史（"个人设置"里的危险动作，调用方负责二次确认） */
  clear() {
    this.items = [];
    this.activeId = null;
    this.notify();
  }

  save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.items.slice(0, MAX_CHATS)));
    } catch {
      /* 存不下不影响使用，只是下次打开看不到历史 */
    }
  }
}

function load() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "[]");
    if (!Array.isArray(raw)) return [];
    return raw.filter((item) => item && item.id && Array.isArray(item.messages));
  } catch {
    return [];
  }
}

/** 侧栏时间：今天给时刻，更早给日期，不写"几秒前"（跳来跳去反而吵） */
export function historyTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    d.getFullYear() === yesterday.getFullYear() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getDate() === yesterday.getDate()
  ) {
    return "昨天";
  }
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}
