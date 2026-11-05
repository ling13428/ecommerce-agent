(() => {
  "use strict";

  const STORAGE_KEY = "yunshang.session_id";
  const STORAGE_BUYER = "yunshang.buyer_id";
  const STORAGE_BUYER_TOKEN = "yunshang.buyer_token";
  const STORAGE_ADMIN_TOKEN = "yunshang.admin_token";
  const $ = (selector) => document.querySelector(selector);

  const els = {
    roleBuyer: $("#roleBuyer"),
    roleMerchant: $("#roleMerchant"),
    buyerView: $("#buyerView"),
    merchantView: $("#merchantView"),
    connDot: $("#connDot"),
    connText: $("#connText"),
    buyerMessages: $("#buyerMessages"),
    buyerInput: $("#buyerInput"),
    buyerForm: $("#buyerForm"),
    buyerSend: $("#buyerSend"),
    buyerSubtitle: $("#buyerSubtitle"),
    buyerPhoneInput: $("#buyerPhoneInput"),
    buyerOtpInput: $("#buyerOtpInput"),
    buyerSendCodeBtn: $("#buyerSendCodeBtn"),
    buyerLoginBtn: $("#buyerLoginBtn"),
    buyerOptions: $("#buyerOptions"),
    buyerNameHint: $("#buyerNameHint"),
    restartBtn: $("#restartBtn"),
    quickPrompts: $("#quickPrompts"),
    humanBanner: $("#humanBanner"),
    humanBannerText: $("#humanBannerText"),
    sessionLabel: $("#sessionLabel"),
    sessionItems: $("#sessionItems"),
    sessionCount: $("#sessionCount"),
    refreshSessions: $("#refreshSessions"),
    kpiPanel: $("#kpiPanel"),
    kpiMeta: $("#kpiMeta"),
    refreshKpi: $("#refreshKpi"),
    kpiSessions: $("#kpiSessions"),
    kpiResolution: $("#kpiResolution"),
    kpiHandoff: $("#kpiHandoff"),
    kpiFirstResponse: $("#kpiFirstResponse"),
    kpiFirstResponseP95: $("#kpiFirstResponseP95"),
    kpiRoutes: $("#kpiRoutes"),
    kpiReasons: $("#kpiReasons"),
    adminTokenInput: $("#adminTokenInput"),
    adminLoginBtn: $("#adminLoginBtn"),
    merchantEmpty: $("#merchantEmpty"),
    merchantPanel: $("#merchantPanel"),
    merchantSessionLabel: $("#merchantSessionLabel"),
    merchantSessionMeta: $("#merchantSessionMeta"),
    merchantModeBadge: $("#merchantModeBadge"),
    takeoverBtn: $("#takeoverBtn"),
    merchantMessages: $("#merchantMessages"),
    merchantForm: $("#merchantForm"),
    merchantInput: $("#merchantInput"),
    merchantHint: $("#merchantHint"),
    traceToggleBtn: $("#traceToggleBtn"),
    tracePanel: $("#tracePanel"),
    traceCloseBtn: $("#traceCloseBtn"),
    traceSubtitle: $("#traceSubtitle"),
    traceBody: $("#traceBody"),
  };

  const state = {
    role: "buyer",
    sessionId: loadSessionId(),
    buyerId: loadBuyerId(),
    buyerToken: loadBuyerToken(),
    buyerInfo: null,
    buyers: [],
    adminToken: loadAdminToken(),
    lastHumanId: 0,
    humanMode: false,
    streaming: false,
    abortController: null,
    pollTimer: null,
    healthText: "",
    merchant: {
      sessions: [],
      selected: null,
      messagesKey: "",
      tracesKey: "",
      traces: [],
      tracesSupported: null,
      traceId: null,
      traceOpen: false,
      detail: null,
    },
  };

  function loadSessionId() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function saveSessionId(value) {
    try {
      if (value) {
        localStorage.setItem(STORAGE_KEY, value);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (error) {
      /* ignore */
    }
  }

  function loadBuyerId() {
    try {
      return localStorage.getItem(STORAGE_BUYER) || "";
    } catch (error) {
      return "";
    }
  }

  function saveBuyerId(value) {
    try {
      if (value) {
        localStorage.setItem(STORAGE_BUYER, value);
      } else {
        localStorage.removeItem(STORAGE_BUYER);
      }
    } catch (error) {
      /* ignore */
    }
  }

  function loadBuyerToken() {
    try {
      return sessionStorage.getItem(STORAGE_BUYER_TOKEN) || "";
    } catch (error) {
      return "";
    }
  }

  function saveBuyerToken(value) {
    try {
      if (value) {
        sessionStorage.setItem(STORAGE_BUYER_TOKEN, value);
      } else {
        sessionStorage.removeItem(STORAGE_BUYER_TOKEN);
      }
    } catch (error) {
      /* ignore */
    }
  }

  function loadAdminToken() {
    try {
      return sessionStorage.getItem(STORAGE_ADMIN_TOKEN) || "";
    } catch (error) {
      return "";
    }
  }

  function saveAdminToken(value) {
    try {
      if (value) {
        sessionStorage.setItem(STORAGE_ADMIN_TOKEN, value);
      } else {
        sessionStorage.removeItem(STORAGE_ADMIN_TOKEN);
      }
    } catch (error) {
      /* ignore */
    }
  }

  function buyerHeaders() {
    return state.buyerToken
      ? { Authorization: `Bearer ${state.buyerToken}` }
      : {};
  }

  function adminHeaders() {
    return state.adminToken
      ? { "X-Admin-Token": state.adminToken }
      : {};
  }

  function updateBuyerHint() {
    if (!state.buyerToken) {
      els.buyerNameHint.textContent = "未登录";
      return;
    }
    const buyer =
      state.buyerInfo ||
      state.buyers.find((item) => item.buyer_id === state.buyerId);
    if (!buyer) {
      els.buyerNameHint.textContent = state.buyerId || "已登录";
      return;
    }
    const count =
      buyer.order_count !== undefined ? ` · ${buyer.order_count} 笔订单` : "";
    els.buyerNameHint.textContent = `${buyer.nickname}${count}`;
  }

  async function loadBuyerOptions() {
    try {
      const response = await fetch("/api/demo/buyers");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.buyers = Array.isArray(data.buyers) ? data.buyers : [];
      els.buyerOptions.innerHTML = state.buyers
        .map(
          (buyer) =>
            `<option value="${escapeHtml(
              buyer.login_phone || ""
            )}">${escapeHtml(buyer.nickname)} · ${escapeHtml(
              buyer.buyer_id
            )}</option>`
        )
        .join("");

      if (!state.buyerId && state.buyers.length) {
        state.buyerId = state.buyers[0].buyer_id;
        saveBuyerId(state.buyerId);
      }
      const currentBuyer = state.buyers.find(
        (item) => item.buyer_id === state.buyerId
      );
      if (currentBuyer && !els.buyerPhoneInput.value) {
        els.buyerPhoneInput.value = currentBuyer.login_phone || "";
      }
      updateBuyerHint();
    } catch (error) {
      els.buyerNameHint.textContent = "买家数据加载失败";
    }
  }

  async function sendBuyerCode() {
    const phone = els.buyerPhoneInput.value.trim();
    if (!/^1\d{10}$/.test(phone)) {
      addNote(els.buyerMessages, "请输入 11 位手机号。");
      return;
    }

    els.buyerSendCodeBtn.disabled = true;
    try {
      const response = await fetch("/api/auth/buyer/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone }),
      });
      const data = await response.json();
      if (!response.ok) {
        addNote(
          els.buyerMessages,
          data.detail || "验证码发送失败，请稍后重试。"
        );
        return;
      }
      if (data.debug_code) {
        els.buyerOtpInput.value = data.debug_code;
        addNote(els.buyerMessages, "验证码已发送，演示环境已自动填入。");
      } else {
        addNote(els.buyerMessages, "验证码已发送，请查收短信。");
      }
    } catch (error) {
      addNote(els.buyerMessages, "验证码发送失败，请稍后重试。");
    } finally {
      els.buyerSendCodeBtn.disabled = false;
    }
  }

  async function loginBuyer() {
    const phone = els.buyerPhoneInput.value.trim();
    const code = els.buyerOtpInput.value.trim();
    if (!/^1\d{10}$/.test(phone)) {
      addNote(els.buyerMessages, "请输入 11 位手机号。");
      return;
    }
    if (!/^\d{4,8}$/.test(code)) {
      addNote(els.buyerMessages, "请输入短信验证码。");
      return;
    }

    els.buyerLoginBtn.disabled = true;
    try {
      const response = await fetch("/api/auth/buyer/otp/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, code }),
      });
      const data = await response.json();
      if (!response.ok) {
        addNote(els.buyerMessages, data.detail || "登录失败，请检查验证码。");
        return;
      }
      state.buyerToken = data.token;
      state.buyerInfo = data.buyer;
      state.buyerId = data.buyer.buyer_id;
      saveBuyerToken(data.token);
      saveBuyerId(state.buyerId);
      els.buyerOtpInput.value = "";
      updateBuyerHint();
      restartConversation();
      addNote(
        els.buyerMessages,
        `已登录买家 ${state.buyerId}（${data.buyer.nickname}），可以查询订单了。`
      );
    } catch (error) {
      addNote(els.buyerMessages, "登录请求失败，请稍后重试。");
    } finally {
      els.buyerLoginBtn.disabled = false;
    }
  }

  async function validateBuyerToken() {
    if (!state.buyerToken) {
      updateBuyerHint();
      return;
    }
    try {
      const response = await fetch("/api/auth/buyer/me", {
        headers: buyerHeaders(),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.buyerInfo = data.buyer;
      state.buyerId = data.buyer.buyer_id;
      const currentBuyer = state.buyers.find(
        (item) => item.buyer_id === state.buyerId
      );
      if (currentBuyer && !els.buyerPhoneInput.value) {
        els.buyerPhoneInput.value = currentBuyer.login_phone || "";
      }
      updateBuyerHint();
    } catch (error) {
      state.buyerToken = "";
      state.buyerInfo = null;
      saveBuyerToken("");
      updateBuyerHint();
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => {
      const map = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      };
      return map[char];
    });
  }

  function formatText(value) {
    const html = escapeHtml(value)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
    return html;
  }

  function timeText(timestamp) {
    const date = new Date(timestamp);
    return `${String(date.getHours()).padStart(2, "0")}:${String(
      date.getMinutes()
    ).padStart(2, "0")}`;
  }

  function relativeTime(seconds) {
    const diff = Date.now() / 1000 - seconds;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    const date = new Date(seconds * 1000);
    return `${date.getMonth() + 1}-${date.getDate()}`;
  }

  function shortId(sessionId) {
    return sessionId.length > 10 ? `${sessionId.slice(0, 10)}…` : sessionId;
  }

  function formatDuration(ms) {
    const value = Math.max(0, Number(ms) || 0);
    if (value < 1000) return `${Math.round(value)}ms`;
    return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
  }

  function prettyJson(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value);
    }
  }

  const TRACE_STATUS = {
    ok: { label: "已完成", tone: "ok" },
    running: { label: "处理中", tone: "" },
    handoff: { label: "已转人工", tone: "warn" },
    confirm_required: { label: "等待确认", tone: "warn" },
    cancelled: { label: "已取消", tone: "warn" },
    fallback: { label: "规则降级", tone: "warn" },
    human_mode: { label: "人工接管", tone: "warn" },
    error: { label: "处理失败", tone: "error" },
    empty: { label: "无回复", tone: "error" },
  };

  const TRACE_STEP_LABEL = {
    receive: "接收",
    route: "路由",
    llm: "模型",
    tool_call: "工具",
    handoff: "转人工",
    confirm_required: "确认",
    confirmation_cancelled: "取消",
    fallback: "降级",
    human_mode: "人工",
    error: "异常",
    reply: "回复",
  };

  function traceStatusPill(status) {
    const meta = TRACE_STATUS[status] || { label: status || "未知", tone: "" };
    return `<span class="trace-pill ${meta.tone}">${escapeHtml(meta.label)}</span>`;
  }

  function traceKv(label, value) {
    if (value === null || value === undefined || value === "") return "";
    return `<div class="trace-kv"><strong>${escapeHtml(
      label
    )}</strong><span>${escapeHtml(String(value))}</span></div>`;
  }

  function scrollToBottom(container) {
    container.scrollTop = container.scrollHeight;
  }

  function setConnection(ok, text) {
    els.connDot.classList.toggle("online", ok);
    els.connDot.classList.toggle("error", !ok);
    els.connText.textContent = text;
  }

  function createRow(container, options) {
    const row = document.createElement("div");
    row.className = `message-row ${options.role}`;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = options.avatar || "AI";
    row.appendChild(avatar);

    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";

    const meta = document.createElement("div");
    meta.className = "bubble-meta";
    const name = document.createElement("span");
    name.textContent = options.name || "";
    meta.appendChild(name);
    if (options.badge) {
      const badge = document.createElement("span");
      badge.className = `badge ${options.badgeType || ""}`;
      badge.textContent = options.badge;
      meta.appendChild(badge);
    }
    const time = document.createElement("span");
    time.textContent = options.time || timeText(Date.now());
    meta.appendChild(time);
    wrap.appendChild(meta);

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = options.html !== undefined ? options.html : "";
    wrap.appendChild(bubble);

    row.appendChild(wrap);
    container.appendChild(row);
    scrollToBottom(container);
    return { row, bubble, wrap };
  }

  function addNote(container, text) {
    const note = document.createElement("div");
    note.className = "note";
    note.textContent = text;
    container.appendChild(note);
    scrollToBottom(container);
    return note;
  }

  function addToolChip(container, name, ok) {
    const chip = document.createElement("div");
    chip.className = `tool-chip${ok ? "" : " fail"}`;
    const dot = document.createElement("span");
    dot.className = "dot";
    chip.appendChild(dot);
    const label = document.createElement("span");
    label.textContent = ok
      ? `工具调用 · ${name}`
      : `工具调用失败 · ${name}`;
    chip.appendChild(label);
    container.appendChild(chip);
    scrollToBottom(container);
  }

  function addConfirmActions(container) {
    const row = document.createElement("div");
    row.className = "confirm-actions";

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.textContent = "确认执行";
    confirmBtn.addEventListener("click", () => {
      row.remove();
      sendBuyerMessage("确认");
    });

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "secondary";
    cancelBtn.textContent = "取消";
    cancelBtn.addEventListener("click", () => {
      row.remove();
      sendBuyerMessage("取消");
    });

    row.append(confirmBtn, cancelBtn);
    container.appendChild(row);
    scrollToBottom(container);
  }

  function welcome() {
    els.buyerMessages.innerHTML = "";
    createRow(els.buyerMessages, {
      role: "assistant",
      avatar: "AI",
      name: "云裳智能客服",
      html: formatText(
        "你好，我是云裳智能客服，可以帮你查商品价格、库存和发货时效，也能回答商品参数、使用保养与售后政策。\n如果需要人工协助，直接说「转人工」即可。"
      ),
    });
  }

  function updateSessionLabel() {
    els.sessionLabel.textContent = state.sessionId
      ? `会话 ${shortId(state.sessionId)}`
      : "尚未创建会话";
  }

  function setHumanMode(enabled, reason) {
    state.humanMode = enabled;
    els.humanBanner.hidden = !enabled;
    els.quickPrompts.hidden = enabled;
    els.buyerSubtitle.textContent = enabled
      ? "人工客服服务中"
      : "售前咨询 · 订单物流 · 售后处理";
    if (enabled) {
      els.humanBannerText.textContent = reason
        ? `已转接人工客服（${reason}），请稍候。`
        : "人工客服已接管会话，请耐心等待回复。";
    }
  }

  function setBuyerBusy(busy) {
    state.streaming = busy;
    els.buyerSend.disabled = busy;
    els.buyerSend.textContent = busy ? "回复中…" : "发送";
  }

  async function sendBuyerMessage(rawText) {
    const message = String(rawText || "").trim();
    if (!message || state.streaming) return;

    createRow(els.buyerMessages, {
      role: "user",
      name: "我",
      html: formatText(message),
    });

    els.buyerInput.value = "";
    autoGrow(els.buyerInput);
    setBuyerBusy(true);

    const assistant = createRow(els.buyerMessages, {
      role: "assistant",
      avatar: "AI",
      name: "云裳智能客服",
      html: '<span class="typing"><i></i><i></i><i></i></span>',
    });

    const ctx = {
      text: "",
      bubble: assistant.bubble,
      row: assistant.row,
      finished: false,
    };
    const controller = new AbortController();
    state.abortController = controller;

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...buyerHeaders(),
        },
        body: JSON.stringify({
          message,
          session_id: state.sessionId || null,
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        if (response.status === 401 && state.buyerToken) {
          state.buyerToken = "";
          state.buyerInfo = null;
          saveBuyerToken("");
          updateBuyerHint();
        }
        let detail = `请求失败（${response.status}）`;
        try {
          const payload = await response.json();
          if (payload && payload.detail) detail = payload.detail;
        } catch (error) {
          /* ignore */
        }
        throw new Error(detail);
      }

      await consumeStream(response, (event) => {
        handleBuyerEvent(event, ctx);
      });
      setConnection(true, state.healthText || "服务在线");
    } catch (error) {
      if (error.name === "AbortError") return;
      ctx.bubble.classList.add("error");
      ctx.bubble.textContent = `消息发送失败：${error.message}`;
      setConnection(false, "服务连接异常");
    } finally {
      if (state.abortController === controller) {
        state.abortController = null;
      }
      setBuyerBusy(false);
      if (!ctx.text) {
        ctx.row.remove();
      } else {
        ctx.bubble.innerHTML = formatText(ctx.text);
      }
      scrollToBottom(els.buyerMessages);
    }
  }

  async function consumeStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const dataLine = raw
          .split("\n")
          .find((line) => line.startsWith("data:"));
        if (dataLine) {
          try {
            onEvent(JSON.parse(dataLine.slice(5).trim()));
          } catch (error) {
            /* ignore malformed event */
          }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  }

  function handleBuyerEvent(event, ctx) {
    switch (event.type) {
      case "start":
        if (event.session_id) {
          state.sessionId = event.session_id;
          saveSessionId(state.sessionId);
          updateSessionLabel();
        }
        break;
      case "delta":
        ctx.text += event.content || "";
        ctx.bubble.innerHTML = formatText(ctx.text);
        scrollToBottom(els.buyerMessages);
        break;
      case "tool_call":
        addToolChip(els.buyerMessages, event.name, !!event.ok);
        break;
      case "confirm_required":
        ctx.finished = true;
        addConfirmActions(els.buyerMessages);
        break;
      case "confirmation_cancelled":
        addNote(els.buyerMessages, "已取消该操作");
        break;
      case "handoff":
        setHumanMode(true, event.reason || "");
        break;
      case "human_mode":
        setHumanMode(true);
        addNote(
          els.buyerMessages,
          event.message || "消息已发送给人工客服，请稍候。"
        );
        break;
      case "fallback":
        addNote(els.buyerMessages, event.message || "已切换基础模式");
        break;
      case "error":
        ctx.finished = true;
        addNote(els.buyerMessages, event.message || "服务暂时不可用");
        break;
      default:
        break;
    }
  }

  async function pollBuyerMessages() {
    if (!state.sessionId) return;
    try {
      const response = await fetch(
        `/api/chat/messages?session_id=${encodeURIComponent(
          state.sessionId
        )}&after_id=${state.lastHumanId}`,
        { headers: buyerHeaders() }
      );
      if (!response.ok) return;
      const data = await response.json();
      if (typeof data.human_mode === "boolean" && data.human_mode !== state.humanMode) {
        setHumanMode(data.human_mode);
      }
      (data.messages || []).forEach((message) => {
        state.lastHumanId = Math.max(state.lastHumanId, message.id);
        createRow(els.buyerMessages, {
          role: "human",
          avatar: "客",
          name: "人工客服",
          badge: "人工",
          badgeType: "human",
          html: formatText(message.content),
        });
      });
    } catch (error) {
      /* polling is best-effort */
    }
  }

  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }

  function switchRole(role) {
    state.role = role;
    els.roleBuyer.classList.toggle("active", role === "buyer");
    els.roleMerchant.classList.toggle("active", role === "merchant");
    els.buyerView.hidden = role !== "buyer";
    els.merchantView.hidden = role !== "merchant";
    if (role === "merchant") {
      if (window.location.hash !== "#merchant") {
        window.history.replaceState(null, "", "#merchant");
      }
      refreshMerchant();
    } else {
      if (window.location.hash) {
        window.history.replaceState(null, "", window.location.pathname);
      }
      scrollToBottom(els.buyerMessages);
    }
  }

  function requireAdminLogin(message = "请输入管理 Token 后查看会话。") {
    els.sessionCount.textContent = "未登录";
    els.sessionItems.innerHTML = "";
    els.kpiPanel.hidden = true;
    els.merchantPanel.hidden = true;
    els.merchantEmpty.hidden = false;
    const hint = els.merchantEmpty.querySelector("p");
    if (hint) hint.textContent = message;
  }

  async function loginAdmin() {
    const token = els.adminTokenInput.value.trim();
    state.adminToken = token;
    if (!token) {
      saveAdminToken("");
      requireAdminLogin("请输入管理 Token。");
      return;
    }
    saveAdminToken(token);
    await loadSessions();
    await loadDashboard();
  }

  function formatPercent(value) {
    return `${Math.round((value || 0) * 100)}%`;
  }

  function formatMs(value) {
    if (value === undefined || value === null) return "-";
    if (value === 0) return "<1 ms";
    if (value < 10) return `${value.toFixed(1)} ms`;
    return `${Math.round(value)} ms`;
  }

  function renderKpiBars(container, items, key) {
    container.innerHTML = "";
    if (!items || !items.length) {
      const empty = document.createElement("span");
      empty.className = "kpi-empty";
      empty.textContent = "暂无数据";
      container.appendChild(empty);
      return;
    }
    const max = Math.max(...items.map((item) => item.count || 0), 1);
    items.slice(0, 6).forEach((item) => {
      const row = document.createElement("div");
      row.className = "kpi-bar";
      const label = document.createElement("span");
      label.textContent = item[key] || "未知";
      const count = document.createElement("span");
      count.textContent = item.count;
      const track = document.createElement("span");
      track.className = "kpi-bar-track";
      const fill = document.createElement("span");
      fill.className = "kpi-bar-fill";
      fill.style.width = `${Math.round(((item.count || 0) / max) * 100)}%`;
      track.appendChild(fill);
      row.append(label, count, track);
      container.appendChild(row);
    });
  }

  async function loadDashboard() {
    if (!state.adminToken) return;
    try {
      const response = await fetch("/api/admin/dashboard?days=7", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        els.kpiPanel.hidden = true;
        return;
      }
      const data = await response.json();
      const totals = data.totals || {};
      const rates = data.rates || {};
      const latency = data.latency || {};
      els.kpiSessions.textContent = totals.sessions || 0;
      els.kpiResolution.textContent = formatPercent(rates.resolution);
      els.kpiHandoff.textContent = formatPercent(rates.handoff);
      const firstCount = latency.first_response_count || 0;
      els.kpiFirstResponse.textContent = firstCount
        ? formatMs(latency.first_response_avg_ms)
        : "-";
      els.kpiFirstResponseP95.textContent = firstCount
        ? formatMs(latency.first_response_p95_ms)
        : "-";
      els.kpiMeta.textContent = `最近 ${data.window_days || 7} 天 · ${
        totals.traces || 0
      } 轮对话`;
      renderKpiBars(els.kpiRoutes, data.routes, "route");
      renderKpiBars(els.kpiReasons, data.handoff_reasons, "reason");
      els.kpiPanel.hidden = false;
    } catch (error) {
      els.kpiPanel.hidden = true;
    }
  }

  async function refreshMerchant() {
    if (state.role !== "merchant") return;
    if (!state.adminToken) {
      requireAdminLogin();
      return;
    }
    await loadSessions();
    const now = Date.now();
    if (now - (state.lastKpiAt || 0) > 15000) {
      state.lastKpiAt = now;
      await loadDashboard();
    }
    if (state.merchant.selected) {
      await loadSessionDetail(state.merchant.selected);
    }
  }

  async function loadSessions() {
    try {
      const response = await fetch("/api/admin/sessions", {
        headers: adminHeaders(),
      });
      if (!response.ok) {
        if ([401, 403, 503].includes(response.status)) {
          requireAdminLogin(
            response.status === 503
              ? "管理接口未配置 ADMIN_TOKEN。"
              : "管理 Token 无效，请重新登录。"
          );
          return;
        }
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      const sessions = data.sessions || [];
      state.merchant.sessions = sessions;
      els.sessionCount.textContent = `${sessions.length} 个会话`;
      renderSessionList();
      if (sessions.length === 0) {
        state.merchant.selected = null;
        showMerchantEmpty();
        return;
      }
      const stillExists = sessions.some(
        (session) => session.session_id === state.merchant.selected
      );
      if (!state.merchant.selected || !stillExists) {
        await selectSession(sessions[0].session_id);
      }
    } catch (error) {
      els.sessionCount.textContent = "加载失败";
    }
  }

  function renderSessionList() {
    els.sessionItems.innerHTML = "";
    state.merchant.sessions.forEach((session) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `session-item${
        session.session_id === state.merchant.selected ? " active" : ""
      }`;

      const avatar = document.createElement("span");
      avatar.className = "item-avatar";
      avatar.textContent = "买";
      button.appendChild(avatar);

      const body = document.createElement("span");
      body.className = "item-body";

      const top = document.createElement("span");
      top.className = "item-top";
      const title = document.createElement("strong");
      title.textContent = shortId(session.session_id);
      const time = document.createElement("time");
      time.textContent = relativeTime(session.updated_at);
      top.append(title, time);
      body.appendChild(top);

      const preview = document.createElement("span");
      preview.className = "item-preview";
      preview.textContent = session.last_message || "暂无消息";
      body.appendChild(preview);

      const tags = document.createElement("span");
      tags.className = "item-tags";
      const modeTag = document.createElement("span");
      modeTag.className = `tag ${session.human_mode ? "human" : "bot"}`;
      modeTag.textContent = session.human_mode ? "人工" : "机器人";
      tags.appendChild(modeTag);

      const countTag = document.createElement("span");
      countTag.className = "tag";
      countTag.textContent = `${session.message_count} 条`;
      tags.appendChild(countTag);

      if (session.trace_count) {
        const traceTag = document.createElement("span");
        traceTag.className = "tag";
        traceTag.textContent = `${session.trace_count} 轮轨迹`;
        tags.appendChild(traceTag);
      }

      if (
        session.last_role === "user" &&
        session.session_id !== state.merchant.selected
      ) {
        const dot = document.createElement("span");
        dot.className = "unread-dot";
        tags.appendChild(dot);
      }
      body.appendChild(tags);
      button.appendChild(body);

      button.addEventListener("click", () => selectSession(session.session_id));
      els.sessionItems.appendChild(button);
    });
  }

  async function selectSession(sessionId) {
    state.merchant.selected = sessionId;
    state.merchant.messagesKey = "";
    state.merchant.traces = [];
    state.merchant.tracesKey = "";
    state.merchant.traceId = null;
    renderSessionList();
    await loadSessionDetail(sessionId);
  }

  async function loadSessionDetail(sessionId) {
    try {
      const response = await fetch(
        `/api/admin/sessions/${encodeURIComponent(sessionId)}`,
        { headers: adminHeaders() }
      );
      if (!response.ok) {
        if ([401, 403].includes(response.status)) {
          requireAdminLogin("管理 Token 已失效，请重新登录。");
          return;
        }
        if (response.status === 404) {
          state.merchant.selected = null;
          showMerchantEmpty();
          await loadSessions();
        }
        return;
      }
      const data = await response.json();
      if (state.merchant.selected !== sessionId) return;
      state.merchant.detail = data;
      renderMerchantPanel(data);
    } catch (error) {
      /* best-effort polling */
    }
  }

  function showMerchantEmpty() {
    els.merchantEmpty.hidden = false;
    els.merchantPanel.hidden = true;
  }

  function updateMerchantTraces(traces) {
    const previousKey = state.merchant.tracesKey;
    const previousList = state.merchant.traces;
    const previousLatestId = previousList.length
      ? previousList[previousList.length - 1].id
      : null;
    const previousSelected = state.merchant.traceId;

    state.merchant.tracesSupported = Array.isArray(traces);
    state.merchant.traces = Array.isArray(traces) ? traces : [];
    state.merchant.tracesKey = state.merchant.traces
      .map((trace) => `${trace.id}:${trace.status}:${trace.finished_at || 0}`)
      .join("|");
    const latest = state.merchant.traces[state.merchant.traces.length - 1];
    if (
      state.merchant.traceId === null ||
      !state.merchant.traces.some(
        (trace) => trace.id === state.merchant.traceId
      )
    ) {
      state.merchant.traceId = latest ? latest.id : null;
    } else if (
      state.merchant.traceOpen &&
      previousSelected === previousLatestId &&
      latest &&
      latest.id !== previousSelected
    ) {
      state.merchant.traceId = latest.id;
    }
    els.traceToggleBtn.textContent = state.merchant.traces.length
      ? `运行轨迹 · ${state.merchant.traces.length}`
      : "运行轨迹";
    if (state.merchant.traceOpen && state.merchant.tracesKey !== previousKey) {
      renderTracePanel();
    }
  }

  function openTrace(traceId) {
    if (traceId !== undefined && traceId !== null) {
      state.merchant.traceId = traceId;
    }
    state.merchant.traceOpen = true;
    els.tracePanel.hidden = false;
    els.traceToggleBtn.classList.add("active");
    renderTracePanel();
    if (typeof els.tracePanel.scrollIntoView === "function") {
      els.tracePanel.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "nearest",
      });
    }
  }

  function closeTracePanel() {
    state.merchant.traceOpen = false;
    els.tracePanel.hidden = true;
    els.traceToggleBtn.classList.remove("active");
  }

  function toggleTracePanel() {
    if (state.merchant.traceOpen) {
      closeTracePanel();
      return;
    }
    const latest = state.merchant.traces[state.merchant.traces.length - 1];
    openTrace(latest ? latest.id : state.merchant.traceId);
  }

  function renderTracePanel() {
    const traces = state.merchant.traces;
    let trace = traces.find(
      (item) => item.id === state.merchant.traceId
    );
    if (!trace && traces.length) {
      trace = traces[traces.length - 1];
      state.merchant.traceId = trace.id;
    }
    if (!trace) {
      els.traceSubtitle.textContent = state.merchant.selected
        ? "当前会话暂无运行轨迹"
        : "请选择会话";
      const emptyText =
        state.merchant.tracesSupported === false
          ? "服务端没有返回运行轨迹，可能是后端服务还在运行旧代码。请重启后端服务并强制刷新页面（Ctrl+F5）。"
          : "买家发送消息后，这里会展示后端处理链路：模型轮次、工具参数与结果，以及 RAG 召回的文档和引用来源。";
      els.traceBody.innerHTML = `<div class="trace-empty">${escapeHtml(
        emptyText
      )}</div>`;
      return;
    }

    const index = traces.indexOf(trace) + 1;
    els.traceSubtitle.textContent = `第 ${index}/${traces.length} 轮 · ${
      state.merchant.selected ? shortId(state.merchant.selected) : ""
    }`;

    const pills = [traceStatusPill(trace.status)];
    pills.push(
      `<span class="trace-pill">${escapeHtml(trace.model || "mock")}</span>`
    );
    if (trace.tool_calls) {
      pills.push(`<span class="trace-pill">${trace.tool_calls} 个工具</span>`);
    }
    if (trace.rag_hits) {
      pills.push(`<span class="trace-pill">${trace.rag_hits} 篇文档</span>`);
    }
    if (trace.duration_ms !== null && trace.duration_ms !== undefined) {
      pills.push(
        `<span class="trace-pill">${formatDuration(trace.duration_ms)}</span>`
      );
    }

    const turns = traces
      .map(
        (item, itemIndex) =>
          `<button type="button" class="trace-turn${
            item.id === trace.id ? " active" : ""
          }" data-trace-id="${item.id}" title="${escapeHtml(
            item.user_message || ""
          )}">第 ${itemIndex + 1} 轮</button>`
      )
      .join("");

    els.traceBody.innerHTML = `
      <div class="trace-turns">${turns}</div>
      <div class="trace-summary">
        <div class="trace-summary-user">${escapeHtml(
          trace.user_message || ""
        )}</div>
        <div class="trace-summary-meta">${pills.join("")}</div>
      </div>
      ${(trace.steps || []).map(renderTraceStep).join("")}
    `;
  }

  function renderTraceStep(step) {
    const label = TRACE_STEP_LABEL[step.type] || step.type || "步骤";
    const time =
      step.at_ms !== null && step.at_ms !== undefined
        ? `+${formatDuration(step.at_ms)}`
        : "";
    let body = "";

    if (step.type === "receive") {
      body =
        traceKv("用户消息", step.message) +
        traceKv("会话模式", step.human_mode ? "人工接管" : "机器人") +
        traceKv("模型", step.model);
    } else if (step.type === "route") {
      const slots =
        step.slots && Object.keys(step.slots).length
          ? JSON.stringify(step.slots)
          : "";
      body =
        traceKv("意图", step.sub_intent) +
        traceKv("动作", step.action) +
        traceKv("置信度", step.confidence) +
        traceKv("可用工具", (step.allowed_tools || []).join("、")) +
        traceKv("槽位", slots);
    } else if (step.type === "llm") {
      body =
        traceKv("轮次", `第 ${step.step} 轮`) +
        traceKv("本轮工具调用", step.tool_call_count) +
        traceKv("本轮文本", step.has_text ? "有" : "无");
    } else if (step.type === "tool_call") {
      body = renderToolDetail(step);
    } else if (step.type === "handoff") {
      body = traceKv("原因", step.reason) + traceKv("摘要", step.summary);
    } else if (
      step.type === "confirm_required" ||
      step.type === "confirmation_cancelled"
    ) {
      body =
        traceKv("工具", step.name) +
        traceKv("说明", step.summary || step.reason);
    } else if (step.type === "fallback" || step.type === "error") {
      body = traceKv("说明", step.message) + traceKv("错误", step.error);
    } else if (step.type === "human_mode") {
      body = traceKv("说明", step.message);
    } else if (step.type === "reply") {
      body = `<div class="trace-pre">${escapeHtml(step.content || "")}</div>`;
    }

    return `<div class="trace-step">
      <div class="trace-step-head">
        <span class="trace-step-kind">${escapeHtml(label)}</span>
        <span class="trace-step-title">${escapeHtml(step.label || "")}</span>
        <time>${time}</time>
      </div>
      ${body ? `<div class="trace-step-body">${body}</div>` : ""}
    </div>`;
  }

  function renderToolDetail(step) {
    const detail = step.detail;
    const parts = [];
    parts.push(traceKv("工具", step.name));
    parts.push(
      traceKv(
        "结果",
        step.ok
          ? step.confirmed
            ? "已确认执行"
            : "成功"
          : "失败"
      )
    );
    if (step.args && Object.keys(step.args).length) {
      parts.push(
        '<div class="trace-kv"><strong>参数</strong></div>',
        `<div class="trace-pre">${escapeHtml(prettyJson(step.args))}</div>`
      );
    }
    if (!detail) {
      return parts.join("");
    }
    if (detail.kind === "rag") {
      parts.push(renderRagDetail(detail));
    } else if (detail.kind === "product") {
      parts.push(renderProductDetail(detail.result));
    } else if (detail.kind === "handoff") {
      parts.push(
        traceKv("原因", detail.reason) + traceKv("摘要", detail.summary)
      );
    } else if (detail.kind === "confirm") {
      parts.push(traceKv("确认说明", detail.summary));
    } else if (detail.kind === "error") {
      parts.push(traceKv("错误", detail.error));
    } else {
      parts.push(
        `<div class="trace-pre">${escapeHtml(prettyJson(detail.result))}</div>`
      );
    }
    return parts.join("");
  }

  function renderRagDetail(detail) {
    const hits = Array.isArray(detail.hits) ? detail.hits : [];
    const meta = [
      detail.query ? `查询：${detail.query}` : "",
      detail.product_id
        ? `商品过滤：${detail.product_id}`
        : "商品过滤：未指定",
      detail.top_score !== null && detail.top_score !== undefined
        ? `最高分：${detail.top_score}`
        : "",
      detail.abstained ? "低于阈值，已拒答" : "",
    ]
      .filter(Boolean)
      .map((text) => `<div>${escapeHtml(text)}</div>`)
      .join("");
    const rejected = detail.rejected
      ? '<div class="trace-kv"><strong>结论</strong><span>知识库无可靠答案，转人工</span></div>'
      : "";
    const hitHtml = hits.length
      ? hits.map(renderRagHit).join("")
      : '<div class="trace-empty">未召回到文档</div>';
    return `<div class="trace-rag-title">RAG 召回 ${hits.length} 篇</div>
      <div class="trace-hit-meta">${meta}</div>
      ${rejected}
      <div class="trace-hit-list">${hitHtml}</div>`;
  }

  function renderRagHit(hit, index) {
    const metaParts = [
      hit.doc_id,
      hit.section,
      hit.source ? `来源 ${hit.source}` : "",
      hit.version ? `版本 ${hit.version}` : "",
      hit.effective_date ? `生效 ${hit.effective_date}` : "",
    ].filter(Boolean);
    const meta = metaParts.map(escapeHtml).join(" · ");
    const deprecated = hit.deprecated
      ? ' · <span class="trace-deprecated">旧版</span>'
      : "";
    const score =
      hit.score !== null && hit.score !== undefined
        ? `<span class="trace-score">${escapeHtml(String(hit.score))}</span>`
        : "";
    return `<div class="trace-hit">
      <div class="trace-hit-head">
        <strong>${index + 1}. ${escapeHtml(
      hit.title || hit.doc_id || "未命名文档"
    )}</strong>
        ${score}
      </div>
      <div class="trace-hit-meta">${meta}${deprecated}</div>
      <details>
        <summary>查看召回原文</summary>
        <div class="trace-pre">${escapeHtml(hit.content || "")}</div>
      </details>
    </div>`;
  }

  function renderProductDetail(product) {
    if (!product || typeof product !== "object") {
      return `<div class="trace-pre">${escapeHtml(prettyJson(product))}</div>`;
    }
    if (product.found === false) {
      return traceKv("结果", product.message || "未找到商品");
    }
    const data = product.product || product;
    if (!data || typeof data !== "object") {
      return `<div class="trace-pre">${escapeHtml(prettyJson(product))}</div>`;
    }
    return [
      traceKv("商品", `${data.id || ""} ${data.model || ""}`.trim()),
      traceKv("名称", data.name),
      traceKv("价格", data.price !== undefined ? `¥${data.price}` : ""),
      traceKv("库存", data.stock !== undefined ? `${data.stock} 件` : ""),
      traceKv("活动", data.activity),
      traceKv("发货时效", data.shipping),
      `<details><summary>查看完整商品数据</summary><div class="trace-pre">${escapeHtml(
        prettyJson(data)
      )}</div></details>`,
    ].join("");
  }

  function renderMerchantPanel(detail) {
    els.merchantEmpty.hidden = true;
    els.merchantPanel.hidden = false;

    els.merchantSessionLabel.textContent = detail.session_id;
    els.merchantSessionMeta.textContent = detail.human_mode
      ? "人工客服服务中"
      : "机器人服务中";
    els.merchantModeBadge.className = `mode-badge ${
      detail.human_mode ? "human" : "bot"
    }`;
    els.merchantModeBadge.textContent = detail.human_mode ? "人工" : "机器人";
    els.takeoverBtn.textContent = detail.human_mode ? "转回机器人" : "人工接管";
    els.merchantHint.textContent = detail.pending_action
      ? `待确认操作：${detail.pending_action}`
      : "";

    updateMerchantTraces(detail.traces);

    const messages = detail.messages || [];
    const key = `${detail.human_mode}|${messages
      .map((message) => message.id)
      .join(",")}`;
    if (key === state.merchant.messagesKey) return;
    state.merchant.messagesKey = key;

    const nearBottom =
      els.merchantMessages.scrollHeight -
        els.merchantMessages.scrollTop -
        els.merchantMessages.clientHeight <
      100;

    const traceByUser = new Map();
    state.merchant.traces.forEach((trace) => {
      if (trace.user_message_id !== null && trace.user_message_id !== undefined) {
        traceByUser.set(trace.user_message_id, trace);
      }
    });

    let currentUserId = null;
    els.merchantMessages.innerHTML = "";
    messages.forEach((message) => {
      if (message.role === "user") {
        currentUserId = message.id;
        createRow(els.merchantMessages, {
          role: "user",
          avatar: "买",
          name: "买家",
          html: formatText(message.content),
        });
      } else if (message.source === "human") {
        createRow(els.merchantMessages, {
          role: "human",
          avatar: "客",
          name: "人工客服",
          badge: "人工",
          badgeType: "human",
          html: formatText(message.content),
        });
      } else {
        const row = createRow(els.merchantMessages, {
          role: "assistant",
          avatar: "AI",
          name: "机器人",
          html: formatText(message.content),
        });
        const trace = traceByUser.get(currentUserId);
        if (trace) {
          addTraceLink(row.wrap, trace);
        }
      }
    });
    if (nearBottom) {
      scrollToBottom(els.merchantMessages);
    }
  }

  function addTraceLink(wrap, trace) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trace-link";
    const parts = ["查看运行轨迹"];
    if (trace.tool_calls) {
      parts.push(`${trace.tool_calls} 个工具`);
    }
    if (trace.rag_hits) {
      parts.push(`${trace.rag_hits} 篇文档`);
    }
    if (trace.duration_ms !== null && trace.duration_ms !== undefined) {
      parts.push(formatDuration(trace.duration_ms));
    }
    button.textContent = parts.join(" · ");
    button.addEventListener("click", () => openTrace(trace.id));
    wrap.appendChild(button);
  }

  async function sendMerchantReply(rawText) {
    const message = String(rawText || "").trim();
    const sessionId = state.merchant.selected;
    if (!message || !sessionId) return;

    els.merchantInput.value = "";
    autoGrow(els.merchantInput);

    try {
      const response = await fetch(
        `/api/admin/sessions/${encodeURIComponent(sessionId)}/reply`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...adminHeaders() },
          body: JSON.stringify({ message }),
        }
      );
      if (!response.ok) {
        let detail = `回复失败（${response.status}）`;
        try {
          const payload = await response.json();
          if (payload && payload.detail) detail = payload.detail;
        } catch (error) {
          /* ignore */
        }
        throw new Error(detail);
      }
      await loadSessionDetail(sessionId);
      await loadSessions();
    } catch (error) {
      addNote(els.merchantMessages, error.message);
    }
  }

  async function toggleTakeover() {
    const sessionId = state.merchant.selected;
    if (!sessionId) return;
    const enabled = !(state.merchant.detail && state.merchant.detail.human_mode);
    els.takeoverBtn.disabled = true;
    try {
      await fetch(
        `/api/admin/sessions/${encodeURIComponent(sessionId)}/takeover`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...adminHeaders() },
          body: JSON.stringify({ enabled }),
        }
      );
      await loadSessionDetail(sessionId);
      await loadSessions();
      setHumanMode(enabled);
    } catch (error) {
      /* ignore */
    } finally {
      els.takeoverBtn.disabled = false;
    }
  }

  function restartConversation() {
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
    state.sessionId = "";
    state.lastHumanId = 0;
    state.merchant.messagesKey = "";
    saveSessionId("");
    updateSessionLabel();
    setHumanMode(false);
    welcome();
    setBuyerBusy(false);
  }

  async function checkHealth() {
    try {
      const response = await fetch("/health");
      const data = await response.json();
      state.healthText =
        data.llm === "configured" ? "在线 · 模型已接入" : "在线 · Mock 模式";
      setConnection(true, state.healthText);
    } catch (error) {
      setConnection(false, "服务未连接");
    }
  }

  function bindEvents() {
    els.roleBuyer.addEventListener("click", () => switchRole("buyer"));
    els.roleMerchant.addEventListener("click", () => switchRole("merchant"));
    els.restartBtn.addEventListener("click", restartConversation);

    els.buyerForm.addEventListener("submit", (event) => {
      event.preventDefault();
      sendBuyerMessage(els.buyerInput.value);
    });

    els.buyerInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendBuyerMessage(els.buyerInput.value);
      }
    });
    els.buyerInput.addEventListener("input", () => autoGrow(els.buyerInput));

    els.buyerLoginBtn.addEventListener("click", loginBuyer);
    els.buyerSendCodeBtn.addEventListener("click", sendBuyerCode);
    els.buyerPhoneInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        sendBuyerCode();
      }
    });
    els.buyerOtpInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        loginBuyer();
      }
    });

    els.quickPrompts.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-prompt]");
      if (!button) return;
      sendBuyerMessage(button.dataset.prompt);
    });

    els.merchantForm.addEventListener("submit", (event) => {
      event.preventDefault();
      sendMerchantReply(els.merchantInput.value);
    });
    els.merchantInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMerchantReply(els.merchantInput.value);
      }
    });
    els.merchantInput.addEventListener("input", () =>
      autoGrow(els.merchantInput)
    );

    els.takeoverBtn.addEventListener("click", toggleTakeover);
    els.traceToggleBtn.addEventListener("click", toggleTracePanel);
    els.traceCloseBtn.addEventListener("click", closeTracePanel);
    els.traceBody.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-trace-id]");
      if (!button) return;
      state.merchant.traceId = Number(button.dataset.traceId);
      renderTracePanel();
    });
    els.refreshSessions.addEventListener("click", refreshMerchant);
    els.refreshKpi.addEventListener("click", loadDashboard);
    els.adminLoginBtn.addEventListener("click", loginAdmin);
    els.adminTokenInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.isComposing) {
        event.preventDefault();
        loginAdmin();
      }
    });
  }

  function init() {
    bindEvents();
    welcome();
    els.adminTokenInput.value = state.adminToken || "";
    updateSessionLabel();
    loadBuyerOptions();
    validateBuyerToken();
    if (window.location.hash === "#merchant") {
      switchRole("merchant");
    }
    checkHealth();
    pollBuyerMessages();
    state.pollTimer = window.setInterval(() => {
      if (state.role === "buyer") {
        pollBuyerMessages();
      }
    }, 3000);
    window.setInterval(refreshMerchant, 4000);
  }

  init();
})();
