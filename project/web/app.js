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

let speechToken = 0;
let presentToken = 0;
let arriveTimer = null;
let recoilTimer = null;
let lookTimer = null;
let evidenceTimer = null;
let evidenceHideTimer = null;

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

function moodFor(value) {
  if (value < 0.34) {
    return { label: "戒备", className: "mood-guarded" };
  }
  if (value < 0.67) {
    return { label: "动摇", className: "mood-shaken" };
  }
  return { label: "松动", className: "mood-softened" };
}

function updateMood(value) {
  const mood = moodFor(value);
  const actor = $("#actor");
  const actorId = $("#actor-id");
  const word = $("#actor-mood");
  for (const node of [actor, actorId]) {
    node.classList.remove("mood-guarded", "mood-shaken", "mood-softened");
    node.classList.add(mood.className);
  }
  word.textContent = mood.label;
  word.className = `actor-mood ${mood.className}`;
}

async function speak(text, options = {}) {
  const { narration = false, waiting = false } = options;
  speechToken += 1;
  const token = speechToken;
  const speech = $("#speech");
  const target = $("#speech-text");
  speech.classList.toggle("narration", narration);
  speech.classList.toggle("waiting", waiting);
  target.classList.remove("typing");
  target.textContent = "";
  if (reduceMotion) {
    target.textContent = String(text ?? "");
    speech.classList.remove("waiting");
    return;
  }
  target.classList.add("typing");
  for (const char of Array.from(String(text ?? ""))) {
    if (token !== speechToken) {
      return;
    }
    target.textContent += char;
    const pause = "。！？…".includes(char)
      ? 180
      : ("，、；：".includes(char) ? 80 : 30);
    await sleep(pause);
  }
  if (token === speechToken) {
    target.classList.remove("typing");
    speech.classList.remove("waiting");
  }
}

function currentRole() {
  return state.roles.find((role) => role.id === state.currentNpcId) || null;
}

function clueNumber(clue) {
  return clue.id.replace(/\D/g, "").padStart(2, "0");
}

function renderSideRail() {
  const rail = $("#side-rail");
  rail.innerHTML = "";
  state.roles.forEach((role) => {
    const button = element("button", "side-suspect");
    button.type = "button";
    button.dataset.npc = role.id;
    button.setAttribute(
      "aria-pressed",
      role.id === state.currentNpcId ? "true" : "false"
    );
    if (role.id === state.currentNpcId) {
      button.classList.add("selected");
    }
    button.classList.add(`role-${role.id}`);
    const silhouette = element("span", "mini-silhouette");
    silhouette.appendChild(element("span", "mini-head"));
    silhouette.appendChild(element("span", "mini-body"));
    button.appendChild(silhouette);
    button.appendChild(element("span", "side-name", role.name));
    button.addEventListener("click", () => selectNpc(role.id));
    rail.appendChild(button);
  });
}

function renderClues() {
  const hand = $("#clue-hand");
  hand.innerHTML = "";
  if (state.clues.length === 0) {
    hand.appendChild(element("p", "empty-hand", "手边还没有证物。"));
    refreshControls();
    return;
  }

  const tilts = [-4, 2, -1, 3, -2, 1];
  state.clues.forEach((clue, index) => {
    const slip = element("button", "clue-slip");
    slip.type = "button";
    slip.dataset.clue = clue.id;
    slip.style.setProperty("--tilt", `${tilts[index % tilts.length]}deg`);
    slip.style.zIndex = String(index + 1);
    if (!state.seenClues.has(clue.id)) {
      slip.classList.add("new");
    }
    if (clue.id === state.selectedClueId) {
      slip.classList.add("selected");
    }
    slip.appendChild(
      element("span", "clue-stamp", `物证 ${clueNumber(clue)}`)
    );
    slip.appendChild(element("span", "clue-name", clue.name));
    slip.addEventListener("click", () => selectClue(clue.id));
    hand.appendChild(slip);
  });

  state.seenClues = new Set(state.clues.map((clue) => clue.id));
  refreshControls();
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
  toast(`取得物证：${clue.name}`, "good");
}

function applyRoleSilhouette(roleId) {
  const actor = $("#actor");
  for (const role of state.roles) {
    actor.classList.remove(`role-${role.id}`);
  }
  actor.classList.add(`role-${roleId}`);
}

function showActor(role) {
  const actor = $("#actor");
  const actorId = $("#actor-id");
  applyRoleSilhouette(role.id);
  $("#actor-name").textContent = role.name;
  $("#actor-public").textContent = role.public;
  updateMood(state.pressure[role.id] ?? 0);
  actor.classList.remove("hidden");
  actorId.classList.remove("hidden");
  actor.classList.remove("arriving");
  void actor.offsetWidth;
  actor.classList.add("arriving");
  clearTimeout(arriveTimer);
  arriveTimer = setTimeout(() => actor.classList.remove("arriving"), 750);
}

function hideActor() {
  const actor = $("#actor");
  const actorId = $("#actor-id");
  actor.classList.add("hidden");
  actorId.classList.add("hidden");
  actor.classList.remove("arriving", "asking", "recoiling", "looking");

}

function selectNpc(npcId) {
  if (state.busy || state.ended || state.currentNpcId === npcId) {
    return;
  }
  state.currentNpcId = npcId;
  state.selectedClueId = null;
  resetAccuseArm();
  renderSideRail();
  renderClues();
  const role = currentRole();
  if (!role) {
    return;
  }
  showActor(role);
  updateMood(state.pressure[role.id] ?? 0);
  $("#actor").classList.remove("asking", "recoiling", "looking");
  clearTimeout(recoilTimer);
  clearTimeout(lookTimer);
  hideTableEvidence();
  $("#last-question").textContent = "";
  $("#question-input").placeholder = `问${role.name}……`;
  speak("他走过来，在对面坐下。", { narration: true });
  refreshControls();
  $("#question-input").focus();
}

function refreshControls() {
  const role = currentRole();
  const question = $("#question-input").value.trim();
  const locked = state.busy || state.ended;
  const hasClue = Boolean(state.selectedClueId);

  $("#question-input").disabled = locked;
  $("#send-button").disabled = locked || !role || !question;
  $("#accuse-button").disabled = locked || !role;
  $("#restart-button").disabled = state.busy;
  $("#present-button").classList.toggle("hidden", !hasClue);
  $("#present-button").disabled = locked || !role;
  $("#present-target").textContent = hasClue
    ? (role ? `递给 ${role.name}` : "先选一个人")
    : "";

  if (!role) {
    $("#question-input").placeholder = "你要问什么？";
  }
}

function selectClue(clueId) {
  if (state.busy || state.ended) {
    return;
  }
  state.selectedClueId = state.selectedClueId === clueId ? null : clueId;
  document.querySelectorAll(".clue-slip").forEach((slip) => {
    slip.classList.toggle("selected", slip.dataset.clue === state.selectedClueId);
  });
  refreshControls();
}

function setPressure(npcId, value, animate = false) {
  const old = state.pressure[npcId] ?? 0;
  state.pressure[npcId] = value;
  if (npcId !== state.currentNpcId) {
    return;
  }
  updateMood(value);
  if (!animate || value <= old) {
    return;
  }
  const actor = $("#actor");
  actor.classList.remove("recoiling");
  void actor.offsetWidth;
  actor.classList.add("recoiling");
  clearTimeout(recoilTimer);
  recoilTimer = setTimeout(() => actor.classList.remove("recoiling"), 1800);
}

function showTableEvidence(clue) {
  const box = $("#table-evidence");
  box.innerHTML = "";
  box.appendChild(
    element("span", "evidence-stamp", `物证 ${clueNumber(clue)}`)
  );
  box.appendChild(element("span", "evidence-name", clue.name));
  box.appendChild(element("p", "evidence-desc", clue.desc));
  box.classList.remove("hidden");
  requestAnimationFrame(() => box.classList.add("visible"));
  clearTimeout(evidenceTimer);
  clearTimeout(evidenceHideTimer);
  evidenceTimer = setTimeout(hideTableEvidence, 2800);
}

function hideTableEvidence() {
  const box = $("#table-evidence");
  if (!box) {
    return;
  }
  box.classList.remove("visible");
  clearTimeout(evidenceHideTimer);
  evidenceHideTimer = setTimeout(() => box.classList.add("hidden"), 260);
}

function flyClue(clue, onLanded) {
  const source = document.querySelector(`.clue-slip[data-clue="${clue.id}"]`);
  const target = $("#table-focus");
  if (!source || !target) {
    onLanded();
    return;
  }
  const from = source.getBoundingClientRect();
  const to = target.getBoundingClientRect();
  const fly = element("div", "clue-fly");
  fly.appendChild(element("span", "fly-stamp", `物证 ${clueNumber(clue)}`));
  fly.appendChild(element("span", "fly-name", clue.name));
  fly.style.left = `${from.left}px`;
  fly.style.top = `${from.top}px`;
  fly.style.width = `${from.width}px`;
  fly.style.height = `${from.height}px`;
  document.body.appendChild(fly);

  requestAnimationFrame(() => {
    const dx = to.left + to.width / 2 - (from.left + from.width / 2);
    const dy = to.top + to.height / 2 - (from.top + from.height / 2);
    requestAnimationFrame(() => {
      fly.style.transform = `translate(${dx}px, ${dy}px) rotate(0deg) scale(1.08)`;
    });
  });

  setTimeout(() => {
    fly.classList.add("gone");
    setTimeout(() => fly.remove(), 240);
    onLanded();
  }, 560);
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
    toast("先选一个人", "warn");
    return;
  }
  if (!question) {
    toast("先写一句要问的话", "warn");
    return;
  }

  state.busy = true;
  input.value = "";
  refreshControls();
  $("#last-question").textContent = `你问：${question}`;
  $("#actor").classList.add("asking");
  speak("……", { waiting: true });

  try {
    const data = await api(`/games/${state.gameId}/ask`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, question }),
    });
    setPressure(role.id, data.pressure, false);
    if (data.unlocked_clue) {
      mergeClue(data.unlocked_clue);
    }
    await speak(data.reply);
  } catch (error) {
    await speak("他没有接话。", { narration: true });
    toast(error.detail || "这一问没有得到回应", "warn");
  } finally {
    $("#actor").classList.remove("asking");
    state.busy = false;
    refreshControls();
  }
}

async function handlePresent() {
  if (state.busy || state.ended) {
    return;
  }
  const role = currentRole();
  const clue = state.clues.find((item) => item.id === state.selectedClueId);
  if (!role) {
    toast("先选一个人", "warn");
    return;
  }
  if (!clue) {
    toast("先点一张物证", "warn");
    return;
  }

  presentToken += 1;
  const token = presentToken;
  state.busy = true;
  refreshControls();
  $("#actor").classList.add("looking");
  clearTimeout(lookTimer);
  lookTimer = setTimeout(() => $("#actor").classList.remove("looking"), 2600);
  flyClue(clue, () => {
    if (token === presentToken) {
      showTableEvidence(clue);
    }
  });

  try {
    const data = await api(`/games/${state.gameId}/clues`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, clue_id: clue.id }),
    });
    setPressure(role.id, data.pressure, true);
    if (data.unlocked_clue) {
      mergeClue(data.unlocked_clue);
    }
    await speak(data.reply);
    state.selectedClueId = null;
    renderClues();
  } catch (error) {
    presentToken += 1;
    hideTableEvidence();
    $("#actor").classList.remove("looking");
    if (error.status === 409) {
      toast(error.detail || "这张线索你已经给他看过了", "warn");
    } else {
      toast(error.detail || "物证没能递出去", "warn");
    }
  } finally {
    state.busy = false;
    refreshControls();
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
    toast("先选一个人", "warn");
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
  speechToken += 1;
  presentToken += 1;
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
  clearTimeout(arriveTimer);
  clearTimeout(recoilTimer);
  clearTimeout(lookTimer);
  clearTimeout(evidenceTimer);
  clearTimeout(evidenceHideTimer);
  document.querySelectorAll(".clue-fly").forEach((fly) => fly.remove());

  $("#side-rail").innerHTML = "";
  $("#clue-hand").innerHTML = "";
  $("#last-question").textContent = "";
  $("#question-input").value = "";
  $("#question-input").placeholder = "你要问什么？";
  $("#present-button").classList.add("hidden");
  $("#present-target").textContent = "";
  $("#table-evidence").classList.add("hidden");
  $("#table-evidence").classList.remove("visible");
  $("#table-evidence").innerHTML = "";
  $("#actor-name").textContent = "";
  $("#actor-public").textContent = "";
  $("#actor-mood").textContent = "戒备";
  $("#actor-mood").className = "actor-mood mood-guarded";
  hideActor();
  const speech = $("#speech");
  const speechText = $("#speech-text");
  speech.className = "speech narration";
  speechText.textContent = "";
  speechText.classList.remove("typing");
  $("#verdict").classList.add("hidden");
  $("#verdict").setAttribute("aria-hidden", "true");
  $("#truth-timeline").innerHTML = "";
  $("#missed-ids").innerHTML = "";
  $("#missed-summary").textContent = "";
  $("#verdict-subtitle").textContent = "";
  $("#toasts").innerHTML = "";
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

    renderSideRail();
    renderClues();
    refreshControls();
    speak(data.opening, { narration: true });
  } catch (error) {
    await speak("今晚没有接通。", { narration: true });
    toast("游戏服务连接失败", "warn");
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