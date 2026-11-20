"use strict";

const state = {
  gameId: null,
  roles: [],
  clues: [],
  pressure: {},
  currentNpcId: null,
  selectedClueId: null,
  seenClues: new Set(),
  askedNpcIds: new Set(),
  confrontMode: false,
  confrontIds: [],
  confrontHistory: [],
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

function updateSideRailMoods() {
  document.querySelectorAll(".side-suspect").forEach((button) => {
    const npcId = button.dataset.npc;
    button.classList.remove("mood-guarded", "mood-shaken", "mood-softened");
    button.classList.add(moodFor(state.pressure[npcId] ?? 0).className);
  });
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
    button.classList.add(moodFor(state.pressure[role.id] ?? 0).className);
    const pickIndex = state.confrontIds.indexOf(role.id);
    if (state.confrontMode && pickIndex >= 0) {
      button.classList.add("confront-picked");
      button.dataset.pick = String(pickIndex + 1);
    }
    const silhouette = element("span", "mini-silhouette");
    silhouette.appendChild(element("span", "mini-head"));
    silhouette.appendChild(element("span", "mini-body"));
    button.appendChild(silhouette);
    button.appendChild(element("span", "side-name", role.name));
    button.addEventListener("click", () => handleSuspectClick(role.id));
    rail.appendChild(button);
  });
}

function renderClues() {
  const hand = $("#clue-hand");
  const hint = $("#hand-hint");
  hand.innerHTML = "";
  hand.classList.remove("density-2", "density-3", "density-4");
  if (state.clues.length === 0) {
    if (hint) {
      hint.classList.add("hidden");
    }
    hand.appendChild(
      element("p", "empty-hand", "手边还没有证物。追问细节，可能换来一张纸。")
    );
    refreshControls();
    return;
  }
  if (hint) {
    hint.classList.remove("hidden");
  }
  if (state.clues.length >= 4) {
    hand.classList.add("density-4");
  } else if (state.clues.length >= 2) {
    hand.classList.add(`density-${state.clues.length}`);
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

function handleSuspectClick(npcId) {
  if (state.confrontMode) {
    toggleConfrontPick(npcId);
    return;
  }
  selectNpc(npcId);
}

function toggleConfrontPick(npcId) {
  if (state.busy || state.ended) {
    return;
  }
  const index = state.confrontIds.indexOf(npcId);
  if (index >= 0) {
    state.confrontIds.splice(index, 1);
  } else {
    state.confrontIds.push(npcId);
    if (state.confrontIds.length > 2) {
      state.confrontIds.shift();
    }
  }
  renderSideRail();
  updateConfrontPlaceholder();
  refreshControls();
  if (state.confrontIds.length === 2) {
    $("#question-input").focus();
  }
}

function confrontNames() {
  return state.confrontIds
    .map((id) => {
      const role = state.roles.find((item) => item.id === id);
      return role ? role.name : id;
    })
    .join(" 与 ");
}

function updateConfrontPlaceholder() {
  if (!state.confrontMode) {
    return;
  }
  const input = $("#question-input");
  input.placeholder = state.confrontIds.length === 2
    ? `问${confrontNames()}……`
    : "先在左边选两个人";
}

function toggleConfrontMode() {
  if (state.busy || state.ended) {
    return;
  }
  state.confrontMode = !state.confrontMode;
  state.confrontIds = [];
  const toggle = $("#confront-toggle");
  toggle.classList.toggle("active", state.confrontMode);
  toggle.setAttribute("aria-pressed", String(state.confrontMode));
  toggle.textContent = state.confrontMode ? "退出对质" : "对质";
  $("#send-button").textContent = state.confrontMode ? "对" : "问";
  resetConfrontSession();
  $("#speech").classList.remove("hidden");
  if (state.confrontMode) {
    revealConfrontLog();
    updateConfrontPlaceholder();
  } else {
    const role = currentRole();
    $("#question-input").placeholder = role
      ? `问${role.name}……`
      : "先点左边一个人，再问";
    if (state.confrontHistory.length > 0) {
      revealConfrontLog();
    } else {
      $("#confront-log").classList.add("hidden");
    }
  }
  renderSideRail();
  refreshControls();
  $("#question-input").focus();
}

function resetConfrontSession() {
  const echo = $("#confront-question-echo");
  echo.textContent = "";
  echo.removeAttribute("title");
  $("#confront-who-a").textContent = "";
  $("#confront-say-a").textContent = "";
  $("#confront-who-b").textContent = "";
  $("#confront-say-b").textContent = "";
  $("#confront-verdict").textContent = "";
}

function revealConfrontLog() {
  const log = $("#confront-log");
  if (!log) {
    return;
  }
  renderConfrontHistory();
  log.classList.remove("hidden");
}

function clearConfrontLog() {
  const log = $("#confront-log");
  if (!log) {
    return;
  }
  resetConfrontSession();
  log.classList.add("hidden");
}

function clearConfrontHistory() {
  state.confrontHistory = [];
  renderConfrontHistory();
}

function renderConfrontHistory() {
  const list = $(".confront-history-list");
  if (!list) {
    return;
  }
  list.innerHTML = "";
  for (const entry of state.confrontHistory) {
    const item = element("li", "confront-history-item");
    item.appendChild(element("p", "history-question", `「${entry.question}」`));
    for (const reply of entry.replies) {
      const line = element("p", "history-reply");
      line.appendChild(element("span", "history-who", `${reply.name}：`));
      line.appendChild(element("span", "history-say", reply.reply));
      item.appendChild(line);
    }
    const verdict = element(
      "p",
      "history-verdict",
      `— ${CONFRONT_VERDICTS[entry.alignment] || "说不清"}`
    );
    verdict.dataset.alignment = entry.alignment || "unclear";
    item.appendChild(verdict);
    list.appendChild(item);
  }
}

function refreshControls() {
  const role = currentRole();
  const question = $("#question-input").value.trim();
  const locked = state.busy || state.ended;
  const hasClue = Boolean(state.selectedClueId);
  const confronting = state.confrontMode;
  const twoPicked = state.confrontIds.length === 2;
  const asked = Boolean(role) && state.askedNpcIds.has(role.id);

  $("#question-input").disabled = locked;
  if (confronting) {
    $("#send-button").disabled = locked || !twoPicked || !question;
  } else {
    $("#send-button").disabled = locked || !role || !question;
  }
  $("#accuse-button").disabled = locked || !role || confronting;
  $("#restart-button").disabled = state.busy;
  $("#confront-toggle").disabled = locked;
  $("#present-button").classList.toggle(
    "hidden",
    confronting || state.clues.length === 0
  );
  $("#present-button").disabled = locked || !role || confronting || !hasClue || !asked;

  let presentHint = "";
  if (!confronting && state.clues.length !== 0) {
    if (!role) {
      presentHint = "先点左边一个人，再问";
    } else if (!asked) {
      presentHint = "先问一句，再出示";
    } else if (!hasClue) {
      presentHint = "先点一张物证";
    } else {
      presentHint = `递给 ${role.name}`;
    }
  }
  $("#present-target").textContent = presentHint;
  $("#present-button").title = presentHint;

  if (!role && !confronting) {
    $("#question-input").placeholder = "先点左边一个人，再问";
  }
}

function selectClue(clueId) {
  if (state.busy || state.ended) {
    return;
  }
  state.seenClues.add(clueId);
  const slip = document.querySelector(`.clue-slip[data-clue="${clueId}"]`);
  if (slip) {
    slip.classList.remove("new");
  }
  if (state.selectedClueId === clueId) {
    state.selectedClueId = null;
    hideTableEvidence();
  } else {
    state.selectedClueId = clueId;
    const clue = state.clues.find((item) => item.id === clueId);
    if (clue) {
      showTableEvidence(clue, { pinned: true });
    }
  }
  document.querySelectorAll(".clue-slip").forEach((slip) => {
    slip.classList.toggle("selected", slip.dataset.clue === state.selectedClueId);
  });
  refreshControls();
}

function setPressure(npcId, value, animate = false) {
  const old = state.pressure[npcId] ?? 0;
  state.pressure[npcId] = value;
  if (npcId !== state.currentNpcId) {
    updateSideRailMoods();
    return;
  }
  updateMood(value);
  updateSideRailMoods();
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

function applyConfrontPressure(payload) {
  const pressure = payload || {};
  if (typeof pressure === "number") {
    for (const npcId of state.confrontIds) {
      setPressure(npcId, pressure, true);
    }
    return;
  }
  if (typeof pressure !== "object") {
    return;
  }
  for (const [npcId, value] of Object.entries(pressure)) {
    if (typeof value === "number") {
      setPressure(npcId, value, true);
    }
  }
  updateSideRailMoods();
}

function showTableEvidence(clue, options = {}) {
  const { pinned = false, delta = 0 } = options;
  const box = $("#table-evidence");
  box.innerHTML = "";
  box.appendChild(
    element("span", "evidence-stamp", `物证 ${clueNumber(clue)}`)
  );
  if (delta > 0) {
    box.appendChild(
      element("span", "evidence-delta", `压力 +${delta.toFixed(2)}`)
    );
  }
  box.appendChild(element("span", "evidence-name", clue.name));
  box.appendChild(element("p", "evidence-desc", clue.desc));
  box.classList.toggle("pinned", pinned);
  box.classList.remove("hidden");
  document.body.classList.add("evidence-open");
  requestAnimationFrame(() => box.classList.add("visible"));
  clearTimeout(evidenceTimer);
  clearTimeout(evidenceHideTimer);
  if (!pinned) {
    evidenceTimer = setTimeout(hideTableEvidence, 2800);
  }
}

function hideTableEvidence() {
  const box = $("#table-evidence");
  if (!box) {
    return;
  }
  clearTimeout(evidenceTimer);
  box.classList.remove("visible", "pinned");
  document.body.classList.remove("evidence-open");
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

const CONFRONT_VERDICTS = {
  aligned: "两人口径一致",
  conflicting: "两人口径对不上",
  unclear: "两人都没把话说实",
};

function renderConfront(data, question) {
  const replies = Array.isArray(data.replies) ? data.replies : [];
  const first = replies[0];
  const second = replies[1];
  if (!first || !second) {
    toast("两人的回答没有对上", "warn");
    return;
  }
  $("#confront-question-echo").textContent = question;
  $("#confront-question-echo").title = question;
  $("#confront-who-a").textContent = first.name;
  $("#confront-say-a").textContent = first.reply;
  $("#confront-who-b").textContent = second.name;
  $("#confront-say-b").textContent = second.reply;
  const verdict = $("#confront-verdict");
  verdict.textContent = CONFRONT_VERDICTS[data.alignment] || "说不清";
  verdict.dataset.alignment = data.alignment || "unclear";
  $("#confront-log").classList.remove("hidden");
  state.confrontHistory.push({
    question,
    replies: [first, second],
    alignment: data.alignment || "unclear",
  });
  state.confrontHistory = state.confrontHistory.slice(-3);
  renderConfrontHistory();
}

async function handleConfront(event) {
  event.preventDefault();
  if (state.busy || state.ended) {
    return;
  }
  if (!state.gameId) {
    toast("等开局再对质", "warn");
    return;
  }
  if (state.confrontIds.length !== 2) {
    toast("先在左边选两个人", "warn");
    return;
  }
  const question = $("#question-input").value.trim();
  if (!question) {
    toast("先写一句要问两个人的话", "warn");
    return;
  }

  state.busy = true;
  $("#question-input").value = "";
  refreshControls();
  $("#speech").classList.add("hidden");
  resetConfrontSession();
  if (state.confrontHistory.length > 0) {
    revealConfrontLog();
  }

  try {
    const data = await api(`/games/${state.gameId}/confront`, {
      method: "POST",
      body: JSON.stringify({
        npc_ids: state.confrontIds,
        question,
      }),
    });
    for (const clue of data.unlocked_clues || []) {
      mergeClue(clue);
    }
    applyConfrontPressure(data.pressure || {});
    renderConfront(data, question);
  } catch (error) {
    toast(error.detail || "两人没有对上话", "warn");
    $("#speech").classList.remove("hidden");
  } finally {
    state.busy = false;
    refreshControls();
  }
}

async function handleAsk(event) {
  event.preventDefault();
  if (state.confrontMode) {
    await handleConfront(event);
    return;
  }
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
  clearConfrontLog();
  $("#speech").classList.remove("hidden");
  $("#last-question").textContent = `你问：${question}`;
  $("#actor").classList.add("asking");
  speak("……", { waiting: true });

  try {
    const data = await api(`/games/${state.gameId}/ask`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, question }),
    });
    setPressure(role.id, data.pressure, false);
    state.askedNpcIds.add(role.id);
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
  if (!state.askedNpcIds.has(role.id)) {
    toast("先问一句，再出示", "warn");
    return;
  }
  if (!clue) {
    toast("先点一张物证", "warn");
    return;
  }

  presentToken += 1;
  const token = presentToken;
  const pressureBefore = state.pressure[role.id] ?? 0;
  state.busy = true;
  refreshControls();
  $("#actor").classList.add("looking");
  clearTimeout(lookTimer);
  lookTimer = setTimeout(() => $("#actor").classList.remove("looking"), 2600);

  try {
    const data = await api(`/games/${state.gameId}/clues`, {
      method: "POST",
      body: JSON.stringify({ npc_id: role.id, clue_id: clue.id }),
    });
    setPressure(role.id, data.pressure, true);
    if (data.unlocked_clue) {
      mergeClue(data.unlocked_clue);
    }
    if (token === presentToken) {
      flyClue(clue, () => {
        if (token === presentToken) {
          const delta = (data.pressure ?? pressureBefore) - pressureBefore;
          showTableEvidence(clue, { pinned: true, delta });
        }
      });
    }
    await speak(data.reply);
    state.selectedClueId = null;
    renderClues();
  } catch (error) {
    presentToken += 1;
    clearTimeout(lookTimer);
    $("#actor").classList.remove("looking");
    state.selectedClueId = null;
    renderClues();
    hideTableEvidence();
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

function factKey(value) {
  return String(value ?? "").trim().toLowerCase();
}

function showVerdict(data, role) {
  const overlay = $("#verdict");
  const title = $("#verdict-title");
  title.textContent = data.correct ? "指认成立" : "指认不成立";
  title.className = `verdict-result ${data.correct ? "correct" : "wrong"}`;
  $("#verdict-subtitle").textContent = `你指认了 ${role.name}`;

  const facts = Array.isArray(data.timeline) ? data.timeline : [];
  const missed = Array.isArray(data.missed_fact_ids)
    ? data.missed_fact_ids
    : [];
  const missedSet = new Set(missed.map(factKey));

  const timeline = $("#truth-timeline");
  timeline.innerHTML = "";
  const items = [];
  facts.forEach((fact, index) => {
    const key = factKey(fact.fact_id);
    const unfound = missedSet.has(key);
    const item = element("li", `truth-item${unfound ? " unfound" : ""}`);
    item.appendChild(
      element(
        "span",
        "truth-id",
        `真相 ${String(index + 1).padStart(2, "0")} · ${String(fact.fact_id || "").toUpperCase()}`
      )
    );
    if (unfound) {
      item.appendChild(
        element("p", "truth-text truth-locked", "未挖出")
      );
    } else {
      item.appendChild(element("p", "truth-text", fact.text));
    }
    timeline.appendChild(item);
    items.push(item);
  });

  if (missed.length && missed.length === facts.length) {
    $("#missed-summary").textContent = "破案链一条都没挖出来";
  } else if (missed.length) {
    $("#missed-summary").textContent = `漏了 ${missed.length} 条破案链事实`;
  } else {
    $("#missed-summary").textContent = "破案链已全部挖出";
  }
  const missedBox = $("#missed-ids");
  missedBox.innerHTML = "";
  missed.forEach((factId) => {
    missedBox.appendChild(
      element("span", "missed-chip", String(factId).toUpperCase())
    );
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
  state.askedNpcIds = new Set();
  state.confrontHistory = [];
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
  $("#question-input").placeholder = "先点左边一个人，再问";
  state.confrontMode = false;
  state.confrontIds = [];
  $("#confront-toggle").classList.remove("active");
  $("#confront-toggle").setAttribute("aria-pressed", "false");
  $("#confront-toggle").textContent = "对质";
  $("#send-button").textContent = "问";
  clearConfrontLog();
  clearConfrontHistory();
  $("#speech").classList.remove("hidden");
  $("#present-button").classList.add("hidden");
  $("#present-target").textContent = "";
  $("#table-evidence").classList.add("hidden");
  $("#table-evidence").classList.remove("visible", "pinned");
  document.body.classList.remove("evidence-open");
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
  $("#confront-toggle").addEventListener("click", toggleConfrontMode);
  $("#restart-verdict").addEventListener("click", restartGame);
  refreshControls();
  startGame();
}

document.addEventListener("DOMContentLoaded", init);