"use strict";

const state = {
  gameId: null,
  roles: [],
  clues: [],
  pressure: {},
  currentNpcId: null,
  selectedClueId: null,
  seenClues: new Set(),
  busy: false,
  ended: false,
  accuseArmed: false,
  accuseTimer: null,
};

const reduceMotion = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;

const $ = (selector) => document.querySelector(selector);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function errorDetail(payload) {
  if (!payload) {
    return "";
  }
  const detail = payload.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item.msg || "")
      .filter(Boolean)
      .join("；");
  }
  return "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const message = errorDetail(payload) || `请求失败（${response.status}）`;
    const error = new Error(message);
    error.status = response.status;
    error.detail = message;
    throw error;
  }
  return payload;
}

function toast(message, kind = "info") {
  const box = $("#toasts");
  while (box.children.length >= 4) {
    box.firstElementChild.remove();
  }
  const item = element("div", `toast ${kind}`, message);
  box.appendChild(item);
  setTimeout(() => {
    item.classList.add("leaving");
    setTimeout(() => item.remove(), 220);
  }, 3200);
}

function scrollDialogue() {
  const box = $("#dialogue");
  box.scrollTop = box.scrollHeight;
}

function setDialogueHint(text) {
  $("#dialogue-hint").textContent = text;
}

function addSystem(text) {
  const message = element("div", "message system");
  message.appendChild(element("p", "system-text", text));
  $("#dialogue").appendChild(message);
  scrollDialogue();
  return message;
}

function addPlayerMessage(text) {
  const message = element("div", "message player");
  message.appendChild(element("div", "meta", "你"));
  const bubble = element("div", "bubble");
  bubble.appendChild(element("p", "message-text", text));
  message.appendChild(bubble);
  $("#dialogue").appendChild(message);
  scrollDialogue();
}

function addNpcMessage(name) {
  const message = element("div", "message npc");
  message.appendChild(element("div", "meta", name));
  const bubble = element("div", "bubble");
  const text = element("p", "message-text npc-text");
  bubble.appendChild(text);
  message.appendChild(bubble);
  $("#dialogue").appendChild(message);
  scrollDialogue();
  return text;
}

function addWaiting(name) {
  const message = element("div", "message system waiting");
  message.appendChild(element("span", "waiting-label", `${name}沉吟片刻`));
  message.appendChild(element("span", "waiting-dots", "……"));
  $("#dialogue").appendChild(message);
  scrollDialogue();
  return message;
}

async function typeText(target, text) {
  const characters = Array.from(String(text ?? ""));
  if (reduceMotion) {
    target.textContent = characters.join("");
    scrollDialogue();
    return;
  }
  target.textContent = "";
  target.classList.add("typing");
  for (const char of characters) {
    target.textContent += char;
    scrollDialogue();
    const pause = "。！？…".includes(char)
      ? 180
      : ("，、；：".includes(char) ? 85 : 32);
    await sleep(pause);
  }
  target.classList.remove("typing");
}

function currentRole() {
  return state.roles.find((role) => role.id === state.currentNpcId) || null;
}

function renderRoles() {
  const list = $("#suspect-list");
  list.innerHTML = "";
  state.roles.forEach((role, index) => {
    const card = element("button", "suspect");
    card.type = "button";
    card.dataset.npc = role.id;
    card.setAttribute(
      "aria-pressed",
      role.id === state.currentNpcId ? "true" : "false"
    );
    if (role.id === state.currentNpcId) {
      card.classList.add("selected");
    }
    card.appendChild(
      element("span", "suspect-index", String(index + 1).padStart(2, "0"))
    );
    card.appendChild(element("span", "suspect-name", role.name));
    card.appendChild(element("span", "suspect-public", role.public));
    const row = element("span", "pressure-row");
    row.appendChild(element("span", "pressure-caption", "压 力"));
    row.appendChild(element("span", "pressure-label", "0%"));
    card.appendChild(row);
    const track = element("span", "pressure-track");
    track.appendChild(element("span", "pressure-fill"));
    track.appendChild(element("span", "pressure-ticks"));
    card.appendChild(track);
    card.addEventListener("click", () => selectNpc(role.id));
    list.appendChild(card);
    updatePressureDisplay(role.id);
  });
  $("#suspect-count").textContent = String(state.roles.length).padStart(2, "0");
}

function updatePressureDisplay(npcId) {
  const card = document.querySelector(`.suspect[data-npc="${npcId}"]`);
  if (!card) {
    return;
  }
  const value = state.pressure[npcId] ?? 0;
  const percent = Math.round(value * 100);
  const fill = card.querySelector(".pressure-fill");
  const label = card.querySelector(".pressure-label");
  if (fill) {
    fill.style.width = `${percent}%`;
  }
  if (label) {
    label.textContent = `${percent}%`;
  }
}

function pulsePressure(npcId, delta) {
  const card = document.querySelector(`.suspect[data-npc="${npcId}"]`);
  const role = state.roles.find((item) => item.id === npcId);
  if (!card || !role) {
    return;
  }
  card.classList.remove("pressure-hit");
  void card.offsetWidth;
  card.classList.add("pressure-hit");
  const float = element(
    "span",
    "pressure-float",
    `压力 +${Math.round(delta * 100)}%`
  );
  card.appendChild(float);
  setTimeout(() => {
    card.classList.remove("pressure-hit");
    float.remove();
  }, 1100);
  toast(`${role.name}的压力上升了`, "pressure");
}

function setPressure(npcId, value, animate = false) {
  const old = state.pressure[npcId] ?? 0;
  state.pressure[npcId] = value;
  updatePressureDisplay(npcId);
  if (animate && value > old) {
    pulsePressure(npcId, value - old);
  }
}

function renderClues() {
  const board = $("#clue-board");
  const count = $("#clue-count");
  board.innerHTML = "";
  count.textContent = String(state.clues.length).padStart(2, "0");

  if (state.clues.length === 0) {
    const empty = element("div", "empty-evidence");
    empty.appendChild(element("span", "empty-mark", "∅"));
    empty.appendChild(element("p", "empty-title", "物证板还空着"));
    empty.appendChild(
      element("p", "empty-note", "问出点什么，它自己会记在这里。")
    );
    board.appendChild(empty);
    state.seenClues = new Set();
    refreshControls();
    return;
  }

  const tilts = [-0.8, 0.55, -0.35, 0.9, -0.6, 0.3];
  state.clues.forEach((clue, index) => {
    const card = element("button", "clue-card");
    card.type = "button";
    card.dataset.clue = clue.id;
    card.style.setProperty("--tilt", `${tilts[index % tilts.length]}deg`);

    const isNew = !state.seenClues.has(clue.id);
    if (isNew) {
      card.classList.add("new-evidence");
    }
    if (clue.id === state.selectedClueId) {
      card.classList.add("selected");
    }

    const number = clue.id.replace(/\D/g, "").padStart(2, "0");
    card.appendChild(element("span", "clue-number", `物证 · ${number}`));
    card.appendChild(element("span", "clue-name", clue.name));
    card.appendChild(element("span", "clue-desc", clue.desc));
    card.appendChild(element("span", "clue-code", clue.id.toUpperCase()));
    if (isNew) {
      card.appendChild(element("span", "clue-stamp", "新"));
    }
    card.addEventListener("click", () => selectClue(clue.id));
    board.appendChild(card);
  });

  state.seenClues = new Set(state.clues.map((clue) => clue.id));
  refreshControls();
}

function selectClue(clueId) {
  if (state.busy || state.ended) {
    return;
  }
  state.selectedClueId = state.selectedClueId === clueId ? null : clueId;
  document.querySelectorAll(".clue-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.clue === state.selectedClueId);
  });
  refreshControls();
}

function selectNpc(npcId) {
  if (state.busy || state.ended || state.currentNpcId === npcId) {
    return;
  }
  state.currentNpcId = npcId;
  resetAccuseArm();
  document.querySelectorAll(".suspect").forEach((card) => {
    const selected = card.dataset.npc === npcId;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  const role = currentRole();
  if (role) {
    $("#question-input").placeholder = `问${role.name}……`;
    setDialogueHint(`你把话头转向${role.name}。`);
  }
  refreshControls();
  $("#question-input").focus();
}

function refreshControls() {
  const role = currentRole();
  const question = $("#question-input").value.trim();
  const locked = state.busy || state.ended;
  const clue = state.clues.find((item) => item.id === state.selectedClueId);

  $("#question-input").disabled = locked;
  $("#send-button").disabled = locked || !role || !question;
  $("#accuse-button").disabled = locked || !role;
  $("#restart-button").disabled = state.busy;
  $("#current-suspect-label").textContent = role ? role.name : "未选择";

  if (!role) {
    $("#question-input").placeholder = "先选一个嫌疑人，再开口……";
  }

  const showPresent = Boolean(clue);
  $("#present-panel").classList.toggle("hidden", !showPresent);
  if (showPresent) {
    $("#present-button").disabled = locked || !role;
    $("#present-target").textContent = role
      ? `出示给 ${role.name}`
      : "先选一个嫌疑人";
  }
}

function mergeClue(clue) {
  if (!clue) {
    return;
  }
  if (state.clues.some((item) => item.id === clue.id)) {
    return;
  }
  state.clues.push(clue);
  renderClues();
  toast(`取得物证 ${clue.id.toUpperCase()} · ${clue.name}`, "good");
}

function renderIntro(data) {
  const dialogue = $("#dialogue");
  dialogue.innerHTML = "";
  addSystem(`CASE FILE · ${data.era}`);
  const message = element("div", "message narration");
  const body = element("div", "narration-body");
  body.appendChild(element("span", "narration-kicker", "现场记录"));
  body.appendChild(element("p", "narration-text", data.opening));
  message.appendChild(body);
  dialogue.appendChild(message);
  setDialogueHint("先选一个嫌疑人，开始问话。");
  scrollDialogue();
}

async function handleAsk(event) {
  event.preventDefault();
  if (state.busy || state.ended) {
    return;
  }
  const role = currentRole();
  const input = $("#question-input");
  const question = input.value.trim();
  if (!role) {
    toast("先选一个嫌疑人", "warn");
    return;
  }
  if (!question) {
    toast("先写一句要问的话", "warn");
    return;
  }

  state.busy = true;
  input.value = "";
  refreshControls();
  addPlayerMessage(question);
  const waiting = addWaiting(role.name);

  try {
    const data = await api(`/games/${state.gameId}/ask`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, question }),
    });
    waiting.remove();
    setPressure(role.id, data.pressure, false);
    if (data.unlocked_clue) {
      mergeClue(data.unlocked_clue);
    }
    const text = addNpcMessage(role.name);
    await typeText(text, data.reply);
  } catch (error) {
    waiting.remove();
    toast(error.detail || "这一问没有得到回应", "warn");
  } finally {
    state.busy = false;
    refreshControls();
    scrollDialogue();
  }
}

async function handlePresent() {
  if (state.busy || state.ended) {
    return;
  }
  const role = currentRole();
  const clue = state.clues.find((item) => item.id === state.selectedClueId);
  if (!role) {
    toast("先选一个嫌疑人", "warn");
    return;
  }
  if (!clue) {
    toast("先点一张物证", "warn");
    return;
  }

  state.busy = true;
  refreshControls();
  const waiting = addWaiting(role.name);

  try {
    const data = await api(`/games/${state.gameId}/clues`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, clue_id: clue.id }),
    });
    waiting.remove();
    addSystem(`你把物证「${clue.name}」推到${role.name}面前。`);
    setPressure(role.id, data.pressure, true);
    if (data.unlocked_clue) {
      mergeClue(data.unlocked_clue);
    }
    const text = addNpcMessage(role.name);
    await typeText(text, data.reply);
    state.selectedClueId = null;
    document.querySelectorAll(".clue-card.selected").forEach((card) => {
      card.classList.remove("selected");
    });
  } catch (error) {
    waiting.remove();
    if (error.status === 409) {
      toast(error.detail || "这张线索你已经给他看过了", "warn");
    } else {
      toast(error.detail || "物证没能递出去", "warn");
    }
  } finally {
    state.busy = false;
    refreshControls();
    scrollDialogue();
  }
}

function resetAccuseArm() {
  state.accuseArmed = false;
  if (state.accuseTimer) {
    clearTimeout(state.accuseTimer);
    state.accuseTimer = null;
  }
  const button = $("#accuse-button");
  if (button) {
    button.classList.remove("armed");
    button.textContent = "指认";
  }
}

async function handleAccuse() {
  if (state.busy || state.ended) {
    return;
  }
  const role = currentRole();
  if (!role) {
    toast("先选一个嫌疑人", "warn");
    return;
  }
  if (!state.accuseArmed) {
    state.accuseArmed = true;
    const button = $("#accuse-button");
    button.classList.add("armed");
    button.textContent = "再点一次确认";
    toast(`再点一次，指认 ${role.name}`, "warn");
    state.accuseTimer = setTimeout(resetAccuseArm, 4000);
    return;
  }

  resetAccuseArm();
  state.busy = true;
  refreshControls();

  try {
    const data = await api(`/games/${state.gameId}/accuse`, {
      method: "POST",
      body: JSON.stringify({ suspect_id: role.id }),
    });
    state.ended = true;
    showVerdict(data, role);
  } catch (error) {
    toast(error.detail || "指认失败", "warn");
  } finally {
    state.busy = false;
    refreshControls();
  }
}

function showVerdict(data, role) {
  const overlay = $("#verdict");
  const title = $("#verdict-title");
  title.textContent = data.correct ? "指认成立" : "指认不成立";
  title.className = `verdict-result ${data.correct ? "correct" : "wrong"}`;
  $("#verdict-subtitle").textContent = `你指认了 ${role.name}`;

  const timeline = $("#truth-timeline");
  timeline.innerHTML = "";
  const items = [];
  const facts = Array.isArray(data.timeline) ? data.timeline : [];
  facts.forEach((fact, index) => {
    const item = element("li", "truth-item");
    item.appendChild(
      element(
        "span",
        "truth-id",
        `真相 ${String(index + 1).padStart(2, "0")} · ${fact.fact_id.toUpperCase()}`
      )
    );
    item.appendChild(element("p", "truth-text", fact.text));
    timeline.appendChild(item);
    items.push(item);
  });

  const missed = Array.isArray(data.missed_fact_ids)
    ? data.missed_fact_ids
    : [];
  $("#missed-summary").textContent = missed.length
    ? `漏了 ${missed.length} 条破案链事实`
    : "破案链已全部挖出";
  const missedBox = $("#missed-ids");
  missedBox.innerHTML = "";
  missed.forEach((factId) => {
    missedBox.appendChild(element("span", "missed-chip", factId.toUpperCase()));
  });

  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  $("#restart-verdict").focus();
  revealTimeline(items);
}

async function revealTimeline(items) {
  if (items.length === 0) {
    return;
  }
  if (reduceMotion) {
    items.forEach((item) => item.classList.add("lit"));
    return;
  }
  for (let index = 0; index < items.length; index += 1) {
    items[index].classList.add("lit");
    items[index].scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (index < items.length - 1) {
      await sleep(1000);
    }
  }
}

function resetUI() {
  state.gameId = null;
  state.roles = [];
  state.clues = [];
  state.pressure = {};
  state.currentNpcId = null;
  state.selectedClueId = null;
  state.seenClues = new Set();
  state.busy = false;
  state.ended = false;
  resetAccuseArm();

  $("#dialogue").innerHTML = "";
  $("#suspect-list").innerHTML = "";
  $("#clue-board").innerHTML = "";
  $("#toasts").innerHTML = "";
  $("#present-panel").classList.add("hidden");
  $("#verdict").classList.add("hidden");
  $("#verdict").setAttribute("aria-hidden", "true");
  $("#truth-timeline").innerHTML = "";
  $("#missed-ids").innerHTML = "";
  $("#missed-summary").textContent = "";
  $("#verdict-subtitle").textContent = "";
  $("#question-input").value = "";
  $("#current-suspect-label").textContent = "未选择";
  $("#clue-count").textContent = "00";
  $("#suspect-count").textContent = "00";
  setDialogueHint("先选一个嫌疑人，开始问话。");
  refreshControls();
}

async function startGame() {
  resetUI();
  try {
    const data = await api("/games", { method: "POST" });
    state.gameId = data.game_id;
    state.roles = data.roles || [];
    state.clues = data.clues || [];
    state.pressure = { ...(data.pressure || {}) };
    state.ended = Boolean(data.ended);
    state.seenClues = new Set();

    $("#game-title").textContent = data.title;
    $("#era").textContent = data.era;

    renderRoles();
    renderClues();
    renderIntro(data);
    refreshControls();
  } catch (error) {
    addSystem(`未能开始新的一局：${error.detail || "服务没有回应"}`);
    toast("游戏服务连接失败", "warn");
    setDialogueHint("服务未连接，请重开。");
    refreshControls();
  }
}

function restartGame() {
  const overlay = $("#verdict");
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  startGame();
}

function init() {
  $("#ask-form").addEventListener("submit", handleAsk);
  $("#question-input").addEventListener("input", refreshControls);
  $("#accuse-button").addEventListener("click", handleAccuse);
  $("#restart-button").addEventListener("click", restartGame);
  $("#present-button").addEventListener("click", handlePresent);
  $("#restart-verdict").addEventListener("click", restartGame);
  refreshControls();
  startGame();
}

document.addEventListener("DOMContentLoaded", init);