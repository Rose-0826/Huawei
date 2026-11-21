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
  combineMode: false,
  combinePicks: [],
  combineRemaining: null,
  combineMax: 3,
  combineTarget: null,
  busy: false,
  ended: false,
  accuseArmed: false,
  accuseTimer: null,
  verdictOptions: null,
  verdictOptionsLoaded: false,
  accusePanelOpen: false,
  accuseRole: null,
  accuseChoice: { motive: null, method: null, time: null },
  socialEvent: null,
  socialToken: 0,
  socialResolving: false,
};

let speechToken = 0;
let presentToken = 0;
let arriveTimer = null;
let recoilTimer = null;
let lookTimer = null;
let evidenceTimer = null;
let evidenceHideTimer = null;
let combineTimer = null;
let socialHideTimer = null;
let socialCallTimer = null;

const reduceMotion = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
  : false;

const SOCIAL_KIND_LABELS = {
  approach: "廊下有人走近",
  demand: "他拦住了你",
  whisper: "廊下低声",
};
const SOCIAL_CHOICE_LABELS = {
  press: "追问他",
  dismiss: "让他走",
};
const SOCIAL_MOCK = /(?:^|[?&])event-mock=1(?:&|$)/.test(
  window.location.search
);
const SOCIAL_PREVIEW_KIND = (() => {
  const match = window.location.search.match(
    /[?&]event-preview=(approach|demand|whisper)(?:&|$)/
  );
  return match ? match[1] : null;
})();

const SOCIAL_MOCK_EVENTS = [
  {
    id: "mock-e1",
    kind: "approach",
    speaker: { id: "r5", name: "老韩" },
    target: { id: "r1", name: "沈玉兰" },
    line: "您别再逼沈太太了，23:05 楼梯口的事我瞧见了，手帕是她的，可那不代表什么。",
    choices: [
      { id: "press", label: "追问他" },
      { id: "dismiss", label: "让他走" },
    ],
    press_reply: "您非要这么问，那 23:35 的事我就不瞒了。",
  },
  {
    id: "mock-e2",
    kind: "demand",
    speaker: { id: "r1", name: "沈玉兰" },
    target: null,
    line: "您手里那张 23:05 的记录，是从楼梯口得来的？您先说清楚，我才敢说银元的事。",
    choices: [
      { id: "press", label: "追问他" },
      { id: "dismiss", label: "让他走" },
    ],
    press_reply: "您要这么逼我，那我今晚就更没什么好说的了。",
  },
  {
    id: "mock-e3",
    kind: "whisper",
    speaker: { id: "r2", name: "周砚青" },
    target: { id: "r5", name: "老韩" },
    line: "有件事我一直没说：23:35 老韩收了一包银元，叫我别跟您提二楼的事。",
    choices: [
      { id: "press", label: "追问他" },
      { id: "dismiss", label: "让他走" },
    ],
    press_reply: "话说到这儿，我再多嘴，可就不好收场了。",
  },
];
let socialMockCursor = 0;

const ACCUSE_MOCK = /(?:^|[?&])accuse-mock=1(?:&|$)/.test(
  window.location.search
);
const ACCUSE_MOCK_OPTIONS = {
  motive: [
    { id: "m_old_case", label: "掩盖旧案" },
    { id: "m_money", label: "账目亏空" },
    { id: "m_affair", label: "私情败露" },
  ],
  method: [
    { id: "w_paperweight", label: "镇纸" },
    { id: "w_poker", label: "火钳" },
    { id: "w_bottle", label: "酒瓶" },
  ],
  time: [
    { id: "t_2250", label: "22:50" },
    { id: "t_2305", label: "23:05" },
    { id: "t_2310", label: "23:10" },
  ],
};
const ACCUSE_MOCK_ANSWERS = {
  motive: "m_old_case",
  method: "w_paperweight",
  time: "t_2250",
};
const ACCUSE_MOCK_TIMELINE = [
  { fact_id: "f05", text: "" },
  {
    fact_id: "f06",
    text: "23:05，周砚青在楼梯口碰见沈玉兰，她把手帕攥得死紧。",
  },
  { fact_id: "f08", text: "" },
  { fact_id: "f15", text: "" },
  { fact_id: "f16", text: "" },
];
const ACCUSE_MOCK_MISSED = ["f05", "f08", "f15", "f16"];

const VERDICT_DIMENSIONS = ["motive", "method", "time"];
const VERDICT_DIMENSION_LABELS = {
  motive: "动机",
  method: "手法",
  time: "时间",
};

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

function toast(message, kind = "info", duration = 3200) {
  const box = $("#toasts");
  while (box.children.length >= 4) {
    box.firstElementChild.remove();
  }
  const item = element("div", `toast ${kind}`, message);
  box.appendChild(item);
  setTimeout(() => {
    item.classList.add("leaving");
    setTimeout(() => item.remove(), 220);
  }, duration);
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
    if (!state.combineMode && clue.id === state.selectedClueId) {
      slip.classList.add("selected");
    }
    const pickIndex = state.combinePicks.indexOf(clue.id);
    if (state.combineMode && pickIndex >= 0) {
      slip.classList.add("combine-picked");
      slip.dataset.pick = String(pickIndex + 1);
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
  if (state.combineMode) {
    exitCombineMode();
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
  const combining = state.combineMode;
  const twoPicked = state.confrontIds.length === 2;
  const asked = Boolean(role) && state.askedNpcIds.has(role.id);
  const twoClues = state.clues.length >= 2;
  const exhausted = state.combineRemaining === 0;

  $("#question-input").disabled = locked;
  if (confronting) {
    $("#send-button").disabled = locked || !twoPicked || !question;
  } else {
    $("#send-button").disabled = locked || !role || !question;
  }
  $("#accuse-button").disabled = locked || !role || confronting || combining;
  $("#restart-button").disabled = state.busy;
  $("#confront-toggle").disabled = locked;
  $("#present-button").classList.toggle(
    "hidden",
    confronting || combining || state.clues.length === 0
  );
  $("#present-button").disabled =
    locked || !role || confronting || combining || !hasClue || !asked;

  const combineButton = $("#combine-button");
  combineButton.classList.toggle("hidden", confronting);
  combineButton.classList.toggle("active", combining);
  combineButton.setAttribute("aria-pressed", String(combining));
  $("#combine-exit").classList.toggle("hidden", !combining);
  combineButton.disabled = combining
    ? locked || state.combinePicks.length !== 2
    : locked || !twoClues || exhausted;

  let presentHint = "";
  if (!confronting && !combining && state.clues.length !== 0 && role) {
    if (!asked) {
      presentHint = "先问一句，再出示";
    } else if (!hasClue) {
      presentHint = "先点一张物证";
    } else {
      presentHint = `递给 ${role.name}`;
    }
  }
  $("#present-target").textContent = presentHint;
  $("#present-button").title = presentHint;

  updateHandHint(twoClues);
  updateCombineCount();

  if (!role && !confronting) {
    $("#question-input").placeholder = "先点左边一个人，再问";
  }
}

function combineRemainingNow() {
  return typeof state.combineRemaining === "number"
    ? state.combineRemaining
    : state.combineMax;
}

function updateCombineCount() {
  const node = $("#combine-count");
  if (!node) {
    return;
  }
  const max = state.combineMax > 0 ? state.combineMax : 3;
  const remaining = Math.max(0, Math.min(combineRemainingNow(), max));
  node.classList.toggle("exhausted", remaining === 0);
  if (remaining === 0) {
    node.textContent = "对撞次数用完";
    node.title = "本局的对撞次数已经用完，重开一局才能再拼";
    return;
  }
  node.textContent = remaining >= max
    ? `对撞 ${remaining}/${max}`
    : `剩 ${remaining} 次`;
  node.title = `本局共 ${max} 次对撞，还剩 ${remaining} 次`;
}

function applyCombineMeta(data) {
  if (!data) {
    return;
  }
  if (typeof data.combine_max === "number" && data.combine_max > 0) {
    state.combineMax = data.combine_max;
  }
  if (typeof data.combine_remaining === "number") {
    state.combineRemaining = Math.max(0, data.combine_remaining);
  }
  updateCombineCount();
}

async function syncCombineState() {
  if (!state.gameId) {
    return;
  }
  try {
    const data = await api(`/games/${state.gameId}`);
    applyCombineMeta(data);
  } catch (error) {
    // 接口未就绪时保留本地默认值
  }
}

function updateHandHint(twoClues) {
  const hint = $("#hand-hint");
  if (!hint || state.clues.length === 0) {
    return;
  }
  if (state.combineMode) {
    const picked = state.combinePicks.length;
    if (!twoClues) {
      hint.textContent = "至少两张物证";
    } else if (picked === 2) {
      hint.textContent = "对撞这两张";
    } else if (picked === 1) {
      hint.textContent = "选两张物证（还差一张）";
    } else {
      hint.textContent = "选两张物证";
    }
    return;
  }

  hint.textContent = "点纸片查看详情";
}

function selectClue(clueId) {
  if (state.busy || state.ended) {
    return;
  }
  if (state.combineMode) {
    toggleCombinePick(clueId);
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

function socialSpeakerOf(event) {
  const raw = event && event.speaker ? event.speaker : {};
  const role = state.roles.find((item) => item.id === raw.id);
  return {
    id: raw.id || (role ? role.id : ""),
    name: raw.name || (role ? role.name : ""),
  };
}

function clearSocialEventUI() {
  clearTimeout(socialHideTimer);
  socialHideTimer = null;
  const card = $("#social-event");
  if (!card) {
    return;
  }
  card.classList.remove("visible", "leaving", "resolved");
  card.classList.add("hidden");
  document.body.classList.remove("social-event-open");
  const log = $("#confront-log");
  if (log) {
    log.classList.remove("social-tucked");
  }
  clearTimeout(socialCallTimer);
  document.querySelectorAll(".side-suspect.social-call").forEach((node) => {
    node.classList.remove("social-call");
  });
  state.socialEvent = null;
  state.socialResolving = false;
}

function hideSocialEvent() {
  state.socialToken += 1;
  clearSocialEventUI();
}

function markSocialCall(npcId) {
  clearTimeout(socialCallTimer);
  document.querySelectorAll(".side-suspect.social-call").forEach((node) => {
    node.classList.remove("social-call");
  });
  if (!npcId) {
    return;
  }
  const button = document.querySelector(`.side-suspect[data-npc="${npcId}"]`);
  if (!button) {
    return;
  }
  button.classList.add("social-call");
  socialCallTimer = setTimeout(
    () => button.classList.remove("social-call"),
    3200
  );
}

function renderSocialChoices(event) {
  const box = $("#social-event-choices");
  box.innerHTML = "";
  const raw = Array.isArray(event.choices) && event.choices.length > 0
    ? event.choices
    : [
      { id: "press", label: SOCIAL_CHOICE_LABELS.press },
      { id: "dismiss", label: SOCIAL_CHOICE_LABELS.dismiss },
    ];
  for (const choice of raw) {
    const id = choice && choice.id;
    if (id !== "press" && id !== "dismiss") {
      continue;
    }
    const button = element(
      "button",
      "social-choice",
      choice.label || SOCIAL_CHOICE_LABELS[id]
    );
    button.type = "button";
    button.dataset.choice = id;
    button.addEventListener("click", () => respondSocialEvent(id));
    box.appendChild(button);
  }
}

function showSocialEvent(event) {
  if (!event || typeof event !== "object" || !event.line) {
    return;
  }
  clearSocialEventUI();
  const card = $("#social-event");
  const speaker = socialSpeakerOf(event);
  const kind = SOCIAL_KIND_LABELS[event.kind] ? event.kind : "approach";
  card.dataset.kind = kind;
  $("#social-event-kind").textContent = SOCIAL_KIND_LABELS[kind];
  $("#social-event-speaker").textContent = speaker.name || "有人";

  const targetNode = $("#social-event-target");
  const target = event.target && (event.target.name || event.target.id)
    ? event.target
    : null;
  if (target) {
    targetNode.textContent = `提到 ${target.name || target.id}`;
    targetNode.classList.remove("hidden");
  } else {
    targetNode.textContent = "";
    targetNode.classList.add("hidden");
  }

  $("#social-event-line").textContent = String(event.line);
  renderSocialChoices(event);
  const reply = $("#social-event-reply");
  reply.textContent = "";
  reply.classList.add("hidden");
  const effects = $("#social-event-effects");
  effects.textContent = "";
  effects.classList.add("hidden");

  const figure = $("#social-figure");
  for (const role of state.roles) {
    figure.classList.remove(`role-${role.id}`);
  }
  if (speaker.id) {
    figure.classList.add(`role-${speaker.id}`);
  }

  state.socialEvent = event;
  const log = $("#confront-log");
  if (log && !log.classList.contains("hidden")) {
    log.classList.add("social-tucked");
  }
  document.body.classList.add("social-event-open");
  card.classList.remove("hidden", "leaving", "resolved");
  void card.offsetWidth;
  card.classList.add("visible");
  markSocialCall(speaker.id);
}

function applySocialPressure(pressure) {
  const lines = [];
  if (!pressure || typeof pressure !== "object" || Array.isArray(pressure)) {
    return lines;
  }
  for (const [npcId, value] of Object.entries(pressure)) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      continue;
    }
    const role = state.roles.find((item) => item.id === npcId);
    const name = role ? role.name : npcId;
    const before = state.pressure[npcId] ?? 0;
    const next = Math.max(0, Math.min(1, value));
    setPressure(npcId, next, next > before + 0.0001);
    const delta = next - before;
    if (delta > 0.0001) {
      lines.push(`${name} · 压力 +${delta.toFixed(2)}`);
    } else if (delta < -0.0001) {
      lines.push(`${name} · 压力 ${delta.toFixed(2)}`);
    } else {
      lines.push(`${name} · 压力 ${next.toFixed(2)}`);
    }
  }
  updateSideRailMoods();
  return lines;
}

function showSocialResolution(reply, lines, unlockedClue) {
  const card = $("#social-event");
  if (!card) {
    return;
  }
  card.classList.add("resolved");
  const replyNode = $("#social-event-reply");
  replyNode.textContent = reply || "他没再开口。";
  replyNode.classList.remove("hidden");
  const effects = $("#social-event-effects");
  const parts = lines.slice();
  if (unlockedClue && unlockedClue.name) {
    parts.push(`取得物证：${unlockedClue.name}`);
  }
  if (parts.length > 0) {
    effects.textContent = parts.join(" · ");
    effects.classList.remove("hidden");
  } else {
    effects.textContent = "";
    effects.classList.add("hidden");
  }
  clearTimeout(socialHideTimer);
  socialHideTimer = setTimeout(() => {
    const node = $("#social-event");
    if (!node) {
      return;
    }
    node.classList.add("leaving");
    socialHideTimer = setTimeout(clearSocialEventUI, 320);
  }, 2500);
}

function mockSocialResult(event, choice) {
  const speaker = socialSpeakerOf(event);
  const before = state.pressure[speaker.id] ?? 0;
  if (choice === "dismiss") {
    return {
      reply: "他退了半步，像是还想说什么，终究还是转身回了廊下。",
      pressure: speaker.id
        ? { [speaker.id]: Math.min(1, before + 0.05) }
        : {},
      event: null,
    };
  }
  return {
    reply: event.press_reply || "他压低声音，补了一句没头没尾的话。",
    pressure: speaker.id
      ? { [speaker.id]: Math.min(1, before + 0.1) }
      : {},
    event: null,
  };
}

async function respondSocialEvent(choice) {
  const event = state.socialEvent;
  if (!event || state.socialResolving || state.ended) {
    return;
  }
  if (choice !== "press" && choice !== "dismiss") {
    return;
  }
  state.socialResolving = true;
  const card = $("#social-event");
  card.querySelectorAll(".social-choice").forEach((button) => {
    button.disabled = true;
  });

  let data = null;
  try {
    if (SOCIAL_MOCK) {
      await sleep(180);
      data = mockSocialResult(event, choice);
    } else {
      data = await api(`/games/${state.gameId}/event`, {
        method: "POST",
        body: JSON.stringify({ choice }),
      });
    }
  } catch (error) {
    const silent = error.status === 404 || error.status === 405 ||
      error.status === 409;
    const stillCurrent = state.socialEvent === event;
    state.socialResolving = false;
    if (!stillCurrent) {
      return;
    }
    clearSocialEventUI();
    if (!silent) {
      toast(error.detail || "他没再说下去", "warn");
    }
    return;
  }

  state.socialResolving = false;
  if (state.socialEvent !== event) {
    return;
  }
  const lines = applySocialPressure(data && data.pressure);
  if (data && data.unlocked_clue) {
    mergeClue(data.unlocked_clue);
  }
  showSocialResolution(
    data && data.reply,
    lines,
    data && data.unlocked_clue ? data.unlocked_clue : null
  );
}

async function checkSocialEvent() {
  if (!state.gameId || state.ended) {
    return;
  }
  const gameId = state.gameId;
  const token = ++state.socialToken;
  let payload = null;
  if (SOCIAL_MOCK) {
    await sleep(240);
    payload = {
      event: SOCIAL_MOCK_EVENTS[socialMockCursor % SOCIAL_MOCK_EVENTS.length],
    };
    socialMockCursor += 1;
  } else {
    try {
      payload = await api(`/games/${gameId}/event`);
    } catch (error) {
      return;
    }
  }
  if (token !== state.socialToken || gameId !== state.gameId || state.ended) {
    return;
  }
  const event = payload && payload.event ? payload.event : null;
  if (event) {
    showSocialEvent(event);
  }
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
  suppressCombineCard();
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
  restoreCombineCard();
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

function toggleCombinePick(clueId) {
  if (state.busy || state.ended) {
    return;
  }
  state.seenClues.add(clueId);
  const index = state.combinePicks.indexOf(clueId);
  if (index >= 0) {
    state.combinePicks.splice(index, 1);
  } else {
    state.combinePicks.push(clueId);
    if (state.combinePicks.length > 2) {
      state.combinePicks.shift();
    }
  }
  renderClues();
  refreshControls();
}

function enterCombineMode() {
  if (state.busy || state.ended || state.combineRemaining === 0) {
    return;
  }
  if (state.clues.length < 2) {
    toast("至少要有两张物证", "warn");
    return;
  }
  if (state.confrontMode) {
    toggleConfrontMode();
  }
  hideCombineCard();
  state.combineMode = true;
  state.combinePicks = [];
  state.selectedClueId = null;
  hideTableEvidence();
  renderClues();
  refreshControls();
}

function exitCombineMode() {
  if (!state.combineMode) {
    return;
  }
  state.combineMode = false;
  state.combinePicks = [];
  renderClues();
  refreshControls();
}

function handleCombineClick() {
  if (state.busy || state.ended) {
    return;
  }
  if (!state.combineMode) {
    enterCombineMode();
    return;
  }
  if (state.combinePicks.length === 2) {
    handleCombine();
  }
}

function applyCombinePressure(pressure) {
  const lines = [];
  if (!pressure || typeof pressure !== "object" || Array.isArray(pressure)) {
    return lines;
  }
  for (const [npcId, value] of Object.entries(pressure)) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      continue;
    }
    const role = state.roles.find((item) => item.id === npcId);
    const name = role ? role.name : npcId;
    const before = state.pressure[npcId] ?? 0;
    const next = Math.max(0, Math.min(1, value));
    setPressure(npcId, next, next > before);
    const delta = next - before;
    lines.push(
      delta > 0
        ? `${name} · 压力 +${delta.toFixed(2)}`
        : `${name} · 压力 ${next.toFixed(2)}`
    );
  }
  updateSideRailMoods();
  return lines;
}

function spawnCombineFly(clue, rect, targetX, targetY, rotation) {
  const fly = element("div", "clue-fly combine-fly");
  fly.appendChild(element("span", "fly-stamp", `物证 ${clueNumber(clue)}`));
  fly.appendChild(element("span", "fly-name", clue.name));
  fly.style.left = `${rect.left}px`;
  fly.style.top = `${rect.top}px`;
  fly.style.width = `${rect.width}px`;
  fly.style.height = `${rect.height}px`;
  document.body.appendChild(fly);
  const dx = targetX - (rect.left + rect.width / 2);
  const dy = targetY - (rect.top + rect.height / 2);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      fly.style.transform =
        `translate(${dx}px, ${dy}px) rotate(${rotation}deg) scale(0.94)`;
    });
  });
  return fly;
}

function flyCombineToTable(first, second) {
  if (reduceMotion) {
    return Promise.resolve();
  }
  const sourceA = document.querySelector(
    `.clue-slip[data-clue="${first.id}"]`
  );
  const sourceB = document.querySelector(
    `.clue-slip[data-clue="${second.id}"]`
  );
  const target = $("#table-focus");
  if (!sourceA || !sourceB || !target) {
    return Promise.resolve();
  }
  const rectA = sourceA.getBoundingClientRect();
  const rectB = sourceB.getBoundingClientRect();
  const box = target.getBoundingClientRect();
  const centerX = box.left + box.width / 2;
  const centerY = box.top + 42;
  const flyA = spawnCombineFly(first, rectA, centerX - 42, centerY, -5);
  const flyB = spawnCombineFly(second, rectB, centerX + 42, centerY, 5);

  return new Promise((resolve) => {
    setTimeout(() => {
      flyA.classList.add("closing");
      flyB.classList.add("closing");
      flyA.style.transform =
        `translate(${centerX - 24 - (rectA.left + rectA.width / 2)}px, ` +
        `${centerY - (rectA.top + rectA.height / 2)}px) rotate(-1.5deg) scale(0.94)`;
      flyB.style.transform =
        `translate(${centerX + 24 - (rectB.left + rectB.width / 2)}px, ` +
        `${centerY - (rectB.top + rectB.height / 2)}px) rotate(1.5deg) scale(0.94)`;
      setTimeout(() => {
        flyA.classList.add("gone");
        flyB.classList.add("gone");
        setTimeout(() => {
          flyA.remove();
          flyB.remove();
          resolve();
        }, 240);
      }, 220);
    }, 520);
  });
}

function resolveCombineTarget(data) {
  const reaction = data && data.reaction ? data.reaction : null;
  const pressureIds = data && data.pressure && typeof data.pressure === "object"
    ? Object.keys(data.pressure)
    : [];
  const candidate = data && data.target_npc_id
    ? data.target_npc_id
    : (reaction && reaction.npc_id
      ? reaction.npc_id
      : pressureIds.find((id) => state.roles.some((role) => role.id === id)));
  if (!candidate) {
    return null;
  }
  return state.roles.some((role) => role.id === candidate) ? candidate : null;
}

function showCombineCard(data, pressureLines) {
  const card = $("#combine-card");
  $("#combine-title").textContent = data.title || "对撞";
  $("#combine-text").textContent = data.text || "";
  const pressure = $("#combine-pressure");
  if (pressureLines.length > 0) {
    pressure.textContent = pressureLines.join("，");
    pressure.classList.remove("hidden");
  } else {
    pressure.textContent = "";
    pressure.classList.add("hidden");
  }

  const reaction = data.reaction && data.reaction.line ? data.reaction : null;
  const reactionNode = $("#combine-reaction");
  if (reaction) {
    reactionNode.textContent = reaction.line;
    reactionNode.classList.remove("hidden");
  } else {
    reactionNode.textContent = "";
    reactionNode.classList.add("hidden");
  }

  state.combineTarget = resolveCombineTarget(data);
  const followup = $("#combine-followup");
  if (state.combineTarget) {
    const targetRole = state.roles.find((role) => role.id === state.combineTarget);
    followup.classList.remove("hidden");
    followup.disabled = false;
    followup.title = targetRole
      ? `带这条推断去问${targetRole.name}`
      : "带这条推断去问相关的人";
  } else {
    followup.classList.add("hidden");
    followup.disabled = true;
    followup.removeAttribute("title");
  }

  card.classList.remove("hidden", "visible", "stamping");
  void card.offsetWidth;
  card.classList.add("visible", "stamping");
  clearTimeout(combineTimer);
  combineTimer = setTimeout(() => card.classList.remove("stamping"), 900);
}

function hideCombineCard() {
  const card = $("#combine-card");
  if (!card) {
    return;
  }
  clearTimeout(combineTimer);
  state.combineTarget = null;
  card.classList.remove("visible", "stamping", "suppressed");
  card.classList.add("hidden");
  const followup = $("#combine-followup");
  if (followup) {
    followup.classList.add("hidden");
    followup.disabled = true;
  }
}

function suppressCombineCard() {
  const card = $("#combine-card");
  if (!card || !card.classList.contains("visible")) {
    return;
  }
  card.classList.add("suppressed");
}

function restoreCombineCard() {
  const card = $("#combine-card");
  if (!card) {
    return;
  }
  card.classList.remove("suppressed");
}

function followupCombine() {
  if (state.busy || state.ended || !state.combineTarget) {
    return;
  }
  const targetId = state.combineTarget;
  if (state.combineMode) {
    exitCombineMode();
  }
  selectNpc(targetId);
  const input = $("#question-input");
  input.placeholder = "用这条推断问他……";
  input.focus();
  refreshControls();
}

async function handleCombine() {
  if (state.busy || state.ended) {
    return;
  }
  if (!state.gameId) {
    toast("等开局再对撞", "warn");
    return;
  }
  if (state.combinePicks.length !== 2) {
    toast("选两张物证", "warn");
    return;
  }
  const first = state.clues.find((item) => item.id === state.combinePicks[0]);
  const second = state.clues.find((item) => item.id === state.combinePicks[1]);
  if (!first || !second) {
    toast("这两张纸不在手边", "warn");
    return;
  }

  state.busy = true;
  refreshControls();
  hideSocialEvent();

  try {
    const data = await api(`/games/${state.gameId}/combine`, {
      method: "POST",
      body: JSON.stringify({ clue_ids: [first.id, second.id] }),
    });
    if (typeof data.remaining === "number") {
      state.combineRemaining = Math.max(0, data.remaining);
    }
    if (typeof data.combine_max === "number" && data.combine_max > 0) {
      state.combineMax = data.combine_max;
    }
    const pressureLines = applyCombinePressure(data.pressure || {});
    state.combineMode = false;
    state.combinePicks = [];
    hideTableEvidence();
    hideCombineCard();
    renderClues();
    await flyCombineToTable(first, second);
    showCombineCard(data, pressureLines);
    refreshControls();
    void checkSocialEvent();
  } catch (error) {
    const notReady = error.status === 404 || error.status === 405;
    let message = error.detail || "";
    if (!message) {
      message = notReady
        ? "对撞接口暂时没有接通"
        : "这两张物证对不上，试试有共同人物/时间的物证";
    } else if (message === "这两张物证对不上") {
      message = "这两张物证对不上，试试有共同人物/时间的物证";
    }
    toast(message, "warn", 5200);
    await syncCombineState();
  } finally {
    state.busy = false;
    refreshControls();
  }
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
  hideSocialEvent();
  $("#speech").classList.add("hidden");
  hideCombineCard();
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
    void checkSocialEvent();
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
  hideSocialEvent();
  clearConfrontLog();
  $("#speech").classList.remove("hidden");
  hideCombineCard();
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
    void checkSocialEvent();
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
  hideSocialEvent();
  hideCombineCard();
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
    void checkSocialEvent();
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

function hasVerdictOptions(options) {
  if (!options || typeof options !== "object") {
    return false;
  }
  return VERDICT_DIMENSIONS.every(
    (dim) => Array.isArray(options[dim]) && options[dim].length > 0
  );
}

async function handleAccuse() {
  if (state.busy || state.ended || state.accusePanelOpen) {
    return;
  }
  const role = currentRole();
  if (!role) {
    toast("先选一个人", "warn");
    return;
  }
  if (ACCUSE_MOCK) {
    state.verdictOptions = ACCUSE_MOCK_OPTIONS;
    state.verdictOptionsLoaded = true;
    openAccusePanel(role);
    return;
  }
  if (!state.verdictOptionsLoaded) {
    state.busy = true;
    refreshControls();
    try {
      const data = await api(`/games/${state.gameId}`);
      state.verdictOptions = data.verdict_options || null;
    } catch (error) {
      state.verdictOptions = null;
    } finally {
      state.verdictOptionsLoaded = true;
      state.busy = false;
      refreshControls();
    }
  }
  if (hasVerdictOptions(state.verdictOptions)) {
    openAccusePanel(role);
    return;
  }
  legacyArmAccuse(role);
}

function legacyArmAccuse(role) {
  if (!state.accuseArmed) {
    state.accuseArmed = true;
    const button = $("#accuse-button");
    button.classList.add("armed");
    button.textContent = "再点一次确认";
    toast(`再点一次，指认 ${role.name}`, "warn");
    state.accuseTimer = setTimeout(resetAccuseArm, 4000);
    return;
  }
  void legacyAccuse(role);
}

async function legacyAccuse(role) {
  resetAccuseArm();
  state.busy = true;
  refreshControls();
  hideSocialEvent();

  try {
    const data = await api(`/games/${state.gameId}/accuse`, {
      method: "POST",
      body: JSON.stringify({ suspect_id: role.id }),
    });
    state.ended = true;
    hideCombineCard();
    showVerdict(data, role, null);
  } catch (error) {
    toast(error.detail || "指认失败", "warn");
  } finally {
    state.busy = false;
    refreshControls();
  }
}

function openAccusePanel(role) {
  const options = state.verdictOptions || {};
  state.accuseRole = role;
  state.accusePanelOpen = true;
  state.accuseChoice = { motive: null, method: null, time: null };

  const suspect = $("#accuse-suspect");
  suspect.textContent = role.public
    ? `${role.name} · ${role.public}`
    : role.name;

  const panel = $("#accuse-panel");
  VERDICT_DIMENSIONS.forEach((dim) => {
    const items = Array.isArray(options[dim]) ? options[dim] : [];
    renderAccuseOptions(dim, items);
    const card = panel.querySelector(`.accuse-card[data-dim="${dim}"]`);
    if (card) {
      card.classList.remove("pressed");
      const tag = card.querySelector(".accuse-card-state");
      if (tag) {
        tag.textContent = "未定";
      }
    }
  });

  panel.classList.remove("hidden");
  panel.setAttribute("aria-hidden", "false");
  hideSocialEvent();
  updateAccuseControls();
  const first = panel.querySelector(".accuse-option");
  if (first) {
    first.focus();
  }
}

function closeAccusePanel(restoreFocus = true) {
  if (!state.accusePanelOpen) {
    return;
  }
  state.accusePanelOpen = false;
  const panel = $("#accuse-panel");
  panel.classList.add("hidden");
  panel.setAttribute("aria-hidden", "true");
  if (restoreFocus) {
    $("#accuse-button").focus();
  }
}

function resetAccusePanel() {
  state.accusePanelOpen = false;
  state.accuseRole = null;
  state.accuseChoice = { motive: null, method: null, time: null };
  const panel = $("#accuse-panel");
  if (!panel) {
    return;
  }
  panel.classList.add("hidden");
  panel.setAttribute("aria-hidden", "true");
  VERDICT_DIMENSIONS.forEach((dim) => {
    const box = $(`#accuse-options-${dim}`);
    if (box) {
      box.innerHTML = "";
    }
    const card = panel.querySelector(`.accuse-card[data-dim="${dim}"]`);
    if (card) {
      card.classList.remove("pressed");
      const tag = card.querySelector(".accuse-card-state");
      if (tag) {
        tag.textContent = "未定";
      }
    }
  });
  const hint = $("#accuse-hint");
  if (hint) {
    hint.textContent = "还差三格：动机、手法、时间。";
    hint.classList.remove("ready");
  }
  const submit = $("#accuse-submit");
  if (submit) {
    submit.disabled = true;
  }
  const suspect = $("#accuse-suspect");
  if (suspect) {
    suspect.textContent = "";
  }
}

function renderAccuseOptions(dim, items) {
  const box = $(`#accuse-options-${dim}`);
  box.innerHTML = "";
  items.forEach((item) => {
    const value = String(item.id);
    const label = item.label !== undefined && item.label !== null
      ? String(item.label)
      : value;
    const option = element("button", "accuse-option");
    option.type = "button";
    option.dataset.value = value;
    option.setAttribute("role", "radio");
    option.setAttribute("aria-checked", "false");
    option.appendChild(element("span", "accuse-option-label", label));
    option.addEventListener("click", () => chooseAccuseOption(dim, value));
    box.appendChild(option);
  });
}

function chooseAccuseOption(dim, value) {
  if (!state.accusePanelOpen || state.busy || state.ended) {
    return;
  }
  state.accuseChoice[dim] = value;
  const box = $(`#accuse-options-${dim}`);
  const options = box.querySelectorAll(".accuse-option");
  options.forEach((option) => {
    const picked = option.dataset.value === value;
    option.classList.toggle("selected", picked);
    option.setAttribute("aria-checked", picked ? "true" : "false");
  });
  const card = box.closest(".accuse-card");
  if (card) {
    card.classList.add("pressed");
    const tag = card.querySelector(".accuse-card-state");
    if (tag) {
      tag.textContent = "按定";
    }
  }
  updateAccuseControls();
}

function updateAccuseControls() {
  const missing = VERDICT_DIMENSIONS.filter(
    (dim) => !state.accuseChoice[dim]
  );
  const ready = missing.length === 0;
  const submit = $("#accuse-submit");
  if (submit) {
    submit.disabled = !ready || state.busy || state.ended;
  }
  const hint = $("#accuse-hint");
  if (hint) {
    hint.textContent = ready
      ? "三张卡都按住了，落章提交。"
      : `还差 ${missing.length} 格：${missing
          .map((dim) => VERDICT_DIMENSION_LABELS[dim])
          .join("、")}`;
    hint.classList.toggle("ready", ready);
  }
}

function mockAccuseResult(choice) {
  const dimensions = VERDICT_DIMENSIONS.map((dim) => ({
    id: dim,
    label: VERDICT_DIMENSION_LABELS[dim],
    choice: choice[dim],
    correct: choice[dim] === ACCUSE_MOCK_ANSWERS[dim],
  }));
  const correct = dimensions.every((item) => item.correct);
  return {
    correct,
    partial: !correct && dimensions.some((item) => item.correct),
    dimensions,
    timeline: ACCUSE_MOCK_TIMELINE,
    missed_fact_ids: ACCUSE_MOCK_MISSED,
  };
}

async function submitAccuse() {
  if (state.busy || state.ended || !state.accusePanelOpen) {
    return;
  }
  const role = state.accuseRole;
  if (!role) {
    return;
  }
  const choice = { ...state.accuseChoice };
  if (VERDICT_DIMENSIONS.some((dim) => !choice[dim])) {
    toast("三格还没选满", "warn");
    updateAccuseControls();
    return;
  }

  state.busy = true;
  updateAccuseControls();
  refreshControls();
  try {
    const data = ACCUSE_MOCK
      ? mockAccuseResult(choice)
      : await api(`/games/${state.gameId}/accuse`, {
          method: "POST",
          body: JSON.stringify({
            suspect_id: role.id,
            motive: choice.motive,
            method: choice.method,
            time: choice.time,
          }),
        });
    state.ended = true;
    hideCombineCard();
    closeAccusePanel(false);
    showVerdict(data, role, choice);
  } catch (error) {
    toast(error.detail || "指认失败", "warn");
  } finally {
    state.busy = false;
    updateAccuseControls();
    refreshControls();
  }
}

function factKey(value) {
  return String(value ?? "").trim().toLowerCase();
}

function dimensionChoiceLabel(dim, value) {
  if (value === undefined || value === null || value === "") {
    return "未选";
  }
  const items =
    state.verdictOptions && Array.isArray(state.verdictOptions[dim])
      ? state.verdictOptions[dim]
      : [];
  const hit = items.find((item) => String(item.id) === String(value));
  return hit && hit.label !== undefined && hit.label !== null
    ? String(hit.label)
    : String(value);
}

function renderVerdictDimensions(dimensions, choice) {
  const box = $("#verdict-dimensions");
  box.innerHTML = "";
  if (!Array.isArray(dimensions) || dimensions.length === 0) {
    box.classList.add("hidden");
    return;
  }
  dimensions.forEach((dim) => {
    const id = String(dim.id || "");
    const label = dim.label || VERDICT_DIMENSION_LABELS[id] || id;
    const raw =
      dim.choice !== undefined && dim.choice !== null
        ? dim.choice
        : choice
          ? choice[id]
          : "";
    const text = dimensionChoiceLabel(id, raw);
    const ok = Boolean(dim.correct);
    const row = element("p", `verdict-dimension ${ok ? "ok" : "bad"}`);
    row.appendChild(element("span", "dimension-label", `${label}：`));
    row.appendChild(element("span", "dimension-choice", text));
    row.appendChild(element("span", "dimension-mark", ok ? "✓" : "✗"));
    row.setAttribute(
      "aria-label",
      `${label}：${text}，${ok ? "正确" : "错误"}`
    );
    box.appendChild(row);
  });
  box.classList.remove("hidden");
}

function showVerdict(data, role, choice) {
  const overlay = $("#verdict");
  const title = $("#verdict-title");
  const partial = Boolean(data.partial) && !data.correct;
  let resultText = "指认不成立";
  let resultClass = "wrong";
  if (data.correct) {
    resultText = "指认成立";
    resultClass = "correct";
  } else if (partial) {
    resultText = "证据不足（部分吻合）";
    resultClass = "partial";
  }
  title.textContent = resultText;
  title.className = `verdict-result ${resultClass}`;
  $("#verdict-subtitle").textContent = `你指认了 ${role.name}`;

  renderVerdictDimensions(data.dimensions, choice);

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
    const text = String(fact.text ?? "").trim();
    const unfound = missedSet.has(key) || text === "";
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
        element("p", "truth-text truth-locked", "你没能证明这一条")
      );
    } else {
      item.appendChild(element("p", "truth-text", text));
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
  state.combineMode = false;
  state.combinePicks = [];
  state.combineRemaining = null;
  state.combineMax = 3;
  state.combineTarget = null;
  state.busy = false;
  state.ended = false;
  state.socialEvent = null;
  state.socialResolving = false;
  state.socialToken += 1;
  socialMockCursor = 0;
  resetAccuseArm();
  resetAccusePanel();
  state.verdictOptions = null;
  state.verdictOptionsLoaded = false;
  clearTimeout(arriveTimer);
  clearTimeout(recoilTimer);
  clearTimeout(lookTimer);
  clearTimeout(evidenceTimer);
  clearTimeout(evidenceHideTimer);
  clearTimeout(combineTimer);
  clearTimeout(socialHideTimer);
  clearTimeout(socialCallTimer);
  clearSocialEventUI();
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
  $("#combine-button").classList.remove("active");
  $("#combine-button").setAttribute("aria-pressed", "false");
  $("#combine-exit").classList.add("hidden");
  $("#hand-hint").textContent = "点纸片查看详情";
  $("#combine-count").textContent = "对撞 3/3";
  $("#combine-count").classList.remove("exhausted");
  $("#combine-reaction").textContent = "";
  $("#combine-reaction").classList.add("hidden");
  $("#combine-followup").classList.add("hidden");
  $("#combine-followup").disabled = true;
  hideCombineCard();
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
  $("#verdict-dimensions").innerHTML = "";
  $("#verdict-dimensions").classList.add("hidden");
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
    applyCombineMeta(data);

    $("#game-title").textContent = data.title;
    $("#era").textContent = data.era;

    renderSideRail();
    renderClues();
    refreshControls();
    if (typeof data.combine_remaining !== "number") {
      syncCombineState();
    }
    speak(data.opening, { narration: true });
    if (SOCIAL_PREVIEW_KIND) {
      const preview = SOCIAL_MOCK_EVENTS.find(
        (item) => item.kind === SOCIAL_PREVIEW_KIND
      );
      if (preview) {
        setTimeout(() => showSocialEvent(preview), 700);
      }
    }
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
  $("#combine-button").addEventListener("click", handleCombineClick);
  $("#combine-exit").addEventListener("click", exitCombineMode);
  $("#combine-followup").addEventListener("click", followupCombine);
  $("#confront-toggle").addEventListener("click", toggleConfrontMode);
  $("#restart-verdict").addEventListener("click", restartGame);
  $("#accuse-cancel").addEventListener("click", () => closeAccusePanel());
  $("#accuse-submit").addEventListener("click", submitAccuse);
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      state.accusePanelOpen &&
      !state.busy &&
      !state.ended
    ) {
      closeAccusePanel();
    }
  });
  refreshControls();
  startGame();
}

document.addEventListener("DOMContentLoaded", init);