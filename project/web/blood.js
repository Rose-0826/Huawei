(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const API = "/blood";
  const params = new URLSearchParams(window.location.search);

  const PHASE_LABEL = {
    discussion: "白天讨论",
    nomination: "提名投票",
    defense: "自辩质证",
    night: "夜晚",
    ended: "结束",
  };

  const ROLE_LABEL = {
    villager: "村民",
    murderer: "凶手",
  };

  const WINNER_LABEL = {
    villagers: "好人胜",
    village: "好人胜",
    good: "好人胜",
    innocent: "好人胜",
    murderer: "凶手胜",
    murderers: "凶手胜",
    killer: "凶手胜",
    "好人": "好人胜",
    "好人阵营": "好人胜",
    "凶手": "凶手胜",
    "杀手": "凶手胜",
  };

  const state = {
    mock: params.get("mock") === "1",
    mockCase: params.get("case") || "",
    mockVotesCast: 0,
    game: null,
    gameId: null,
    you: null,
    selectedId: null,
    nominationMode: false,
    busy: false,
    lastSeq: 0,
    lastDayShown: 0,
    speakingId: null,
    speakingText: "",
    bubbleTimer: 0,
    lastVotes: null,
    voteResult: null,
    defense: null,
    nominated: null,
    ballotTargetId: null,
    ballotReason: "",
    mockAftermath: [],
    report: "",
    reportKind: "info",
    murdererId: "",
    murdererName: "",
    revealName: "",
    pending: null,
    drawerOpen: false,
  };

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) {
      el.className = className;
    }
    if (text !== undefined && text !== null) {
      el.textContent = String(text);
    }
    return el;
  }

  function showToast(message, kind = "info", duration = 3400) {
    const box = $("toasts");
    while (box.children.length >= 4) {
      box.firstElementChild.remove();
    }
    const item = node("div", `toast ${kind}`, message);
    box.appendChild(item);
    window.setTimeout(() => {
      item.classList.add("leaving");
      window.setTimeout(() => item.remove(), 220);
    }, duration);
  }

  function detailOf(payload) {
    if (!payload) {
      return "";
    }
    const detail = payload.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail.map((item) => item.msg || "").filter(Boolean).join("；");
    }
    if (detail && typeof detail === "object") {
      return detail.message || "";
    }
    return "";
  }

  async function apiRequest(path, options = {}) {
    const request = {
      method: options.method || "GET",
      headers: { "Content-Type": "application/json" },
      ...options,
    };
    if (request.body !== undefined && request.body !== null && typeof request.body !== "string") {
      request.body = JSON.stringify(request.body);
    }
    const response = await fetch(path, request);
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      payload = null;
    }
    if (!response.ok) {
      const message = detailOf(payload) || `请求失败（${response.status}）`;
      const error = new Error(message);
      error.status = response.status;
      error.detail = message;
      throw error;
    }
    return payload === null ? {} : payload;
  }

  function normalizePhase(value) {
    const raw = String(value === undefined || value === null ? "" : value).trim().toLowerCase();
    if (!raw) {
      return "";
    }
    if (["discussion", "discuss", "day", "talk", "白天讨论", "讨论", "白天"].includes(raw)) {
      return "discussion";
    }
    if (["nomination", "nominate", "vote", "voting", "提名投票", "提名", "投票"].includes(raw)) {
      return "nomination";
    }
    if (["defense", "defence", "defending", "自辩", "辩护", "质证", "自辩质证"].includes(raw)) {
      return "defense";
    }
    if (["night", "夜晚", "夜间"].includes(raw)) {
      return "night";
    }
    if (["ended", "end", "over", "finished", "结束", "终局"].includes(raw)) {
      return "ended";
    }
    if (raw.includes("结束") || raw.includes("end") || raw.includes("over")) {
      return "ended";
    }
    if (raw.includes("night") || raw.includes("夜")) {
      return "night";
    }
    if (raw.includes("defen") || raw.includes("自辩") || raw.includes("质证") || raw.includes("辩护")) {
      return "defense";
    }
    if (raw.includes("nom") || raw.includes("vote") || raw.includes("提名")) {
      return "nomination";
    }
    if (raw.includes("disc") || raw.includes("day") || raw.includes("talk") || raw.includes("讨论")) {
      return "discussion";
    }
    return "";
  }

  function normalizeRole(value) {
    const raw = String(value === undefined || value === null ? "" : value).trim().toLowerCase();
    if (["murderer", "killer", "wolf", "凶手", "杀手", "狼"].includes(raw)) {
      return "murderer";
    }
    return "villager";
  }

  const NARRATION_FEMALE_HINTS = ["沈玉兰", "阿蘅", "刘妈", "老板娘", "女佣", "她"];

  function stripDanglingMemory(text) {
    return String(text || "")
      .replace(/[，,、；;\s]*(?:我还记得|我记得)[:：]\s*$/u, "")
      .trim();
  }

  function softenNarration(text) {
    return String(text || "").split(/(?<=[。！？；\n])/u).map((segment) => {
      if (!NARRATION_FEMALE_HINTS.some((hint) => segment.includes(hint))) {
        return segment;
      }
      return segment
        .replace(/他们/gu, "\u0000")
        .replace(/其他/gu, "\u0001")
        .replace(/他/gu, "对方")
        .replace(/\u0000/gu, "他们")
        .replace(/\u0001/gu, "其他");
    }).join("");
  }

  function sanitizeLine(text, narration = false) {
    const clean = stripDanglingMemory(text);
    return narration ? softenNarration(clean) : clean;
  }

  function normalizeEntry(entry, fallbackSeq) {
    if (!entry || typeof entry !== "object") {
      return null;
    }
    const text = entry.text !== undefined ? entry.text : entry.content;
    if (typeof text !== "string" || !text.trim()) {
      return null;
    }
    const speakerId = String(entry.speaker_id || entry.id || entry.player_id || "narrator");
    const speakerName = String(entry.speaker_name || entry.name || "旁白");
    const narration = speakerId === "__narration"
      || speakerId === "narrator"
      || speakerName === "旁白";
    const clean = sanitizeLine(text, narration);
    if (!clean) {
      return null;
    }
    const seq = Number(entry.seq);
    return {
      seq: Number.isFinite(seq) && seq > 0 ? seq : fallbackSeq,
      speaker_id: speakerId,
      speaker_name: speakerName,
      text: clean,
      day: Number.isFinite(Number(entry.day)) ? Number(entry.day) : null,
    };
  }

  function normalizeLog(raw) {
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw
      .map((entry, index) => normalizeEntry(entry, index + 1))
      .filter(Boolean);
  }

  function maxSeq(log) {
    return (log || []).reduce((top, entry) => Math.max(top, Number(entry.seq) || 0), 0);
  }

  function nextSeq(log) {
    return maxSeq(log) + 1;
  }

  function players() {
    return (state.game && Array.isArray(state.game.players)) ? state.game.players : [];
  }

  function findPlayer(id) {
    if (!id) {
      return null;
    }
    return players().find((player) => player.id === id) || null;
  }

  function youPlayer() {
    const found = players().find((player) => player.is_you);
    if (found) {
      return found;
    }
    if (state.you && state.you.id) {
      return findPlayer(state.you.id);
    }
    return null;
  }

  function youId() {
    return (state.you && state.you.id) || (youPlayer() && youPlayer().id) || "p0";
  }

  function youRole() {
    if (state.you && state.you.role) {
      return normalizeRole(state.you.role);
    }
    const player = youPlayer();
    return normalizeRole(player && player.role);
  }

  function youAlive() {
    const player = youPlayer();
    if (!player) {
      return false;
    }
    return player.alive !== false;
  }

  function idOf(value) {
    if (!value) {
      return "";
    }
    if (typeof value === "string") {
      return value;
    }
    if (typeof value === "object") {
      return String(value.id || value.player_id || value.target_id || value.voter_id || "");
    }
    return "";
  }

  function nameOf(value) {
    if (!value) {
      return "";
    }
    const id = idOf(value);
    if (id) {
      const player = findPlayer(id);
      if (player) {
        return player.name || "";
      }
      if (typeof value === "object" && value.name) {
        return value.name;
      }
      return "";
    }
    if (typeof value === "object" && value.name) {
      return value.name;
    }
    return "";
  }

  function playerName(id) {
    if (!id) {
      return "";
    }
    const player = findPlayer(id);
    if (player) {
      return player.name || "客人";
    }
    return String(id);
  }

  function displayName(player) {
    if (!player) {
      return "";
    }
    if (player.is_you) {
      return player.name || "你";
    }
    return player.name || "客人";
  }

  function shortPublic(player) {
    if (!player) {
      return "";
    }
    if (player.is_you) {
      return "你的席位";
    }
    const source = String(player.public || "住客");
    return source.split(/[，,。；;]/)[0] || "住客";
  }

  function currentPhase() {
    if (!state.game) {
      return "discussion";
    }
    if (state.game.winner) {
      return "ended";
    }
    if (state.nominationMode && state.game.phase === "discussion") {
      return "nomination";
    }
    return normalizePhase(state.game.phase) || "discussion";
  }

  function isFinished() {
    return currentPhase() === "ended";
  }

  function winnerRaw() {
    return (state.game && state.game.winner) || "";
  }

  function winnerLabel() {
    const raw = winnerRaw();
    if (!raw) {
      return "";
    }
    return WINNER_LABEL[raw] || String(raw);
  }

  function normalizeYou(you) {
    if (!you || typeof you !== "object") {
      return null;
    }
    const info = you.private_info;
    const privateInfo = Array.isArray(info) ? info.filter(Boolean).map(String) : (typeof info === "string" && info ? [info] : []);
    return {
      id: you.id || "p0",
      name: you.name || "你",
      role: normalizeRole(you.role),
      private_info: privateInfo,
      teammates: Array.isArray(you.teammates) ? you.teammates.slice() : [],
    };
  }

  function applyGame(data, options = {}) {
    if (!data || typeof data !== "object") {
      return;
    }
    const previous = state.game || {};

    if (options.reset) {
      $("discussion-list").textContent = "";
      $("discussion-empty").classList.remove("hidden");
      $("vote-board").classList.add("hidden");
      $("hall-report").classList.add("hidden");
      $("speak-input").value = "";
      state.lastSeq = 0;
      state.lastDayShown = 0;
state.selectedId = null;
    state.nominationMode = false;
    state.ballotTargetId = null;
    state.ballotReason = "";
    state.lastVotes = null;
      state.voteResult = null;
      state.defense = null;
      state.nominated = null;
      state.ballotTargetId = null;
      state.ballotReason = "";
      state.report = "";
      state.reportKind = "info";
      state.speakingId = null;
      state.pending = null;
      clearBubble();
      closeConfirm();
    }

    if (data.you) {
      state.you = normalizeYou(data.you);
    }

    const nextPlayers = Array.isArray(data.players)
      ? data.players.map((player) => ({ ...player }))
      : (previous.players || []).map((player) => ({ ...player }));

    if (!state.you) {
      const found = nextPlayers.find((player) => player.is_you);
      if (found) {
        state.you = normalizeYou(found);
      }
    }

    for (const player of nextPlayers) {
      player.is_you = Boolean(player.is_you || (state.you && player.id === state.you.id));
      player.alive = player.alive !== false;
    }

    state.game = {
      game_id: data.game_id || previous.game_id || state.gameId || "",
      day: data.day !== undefined ? Math.max(1, Number(data.day) || 1) : (previous.day || 1),
      phase: data.phase !== undefined ? normalizePhase(data.phase) : (previous.phase || "discussion"),
      players: nextPlayers,
      public_log: data.public_log !== undefined ? normalizeLog(data.public_log) : (previous.public_log || []),
      dead: Array.isArray(data.dead) ? data.dead.slice() : (previous.dead || []),
      winner: data.winner !== undefined ? data.winner : (previous.winner === undefined ? null : previous.winner),
      message: typeof data.message === "string" ? data.message : (previous.message || ""),
      reveal: data.reveal !== undefined ? data.reveal : (previous.reveal || null),
      aftermath: data.aftermath !== undefined
        ? normalizeAftermath(data.aftermath)
        : (options.reset ? [] : (previous.aftermath || [])),
      you_alive: data.you_alive !== undefined
        ? Boolean(data.you_alive)
        : (previous.you_alive === undefined ? null : previous.you_alive),
    };

    if (!state.game.phase) {
      state.game.phase = "discussion";
    }
    if (state.game.game_id) {
      state.gameId = state.game.game_id;
    }

    ensureYouPlayer();
    applyDeadFlags();
    if (state.game.you_alive === false && state.you && state.you.id) {
      markDead(state.you.id);
    }

    if (state.game.phase !== "discussion") {
      state.nominationMode = false;
    }

    if (resultHasDefense(data)) {
      state.defense = normalizeDefense(data.defense);
      state.nominated = normalizeTarget(data.target) || state.nominated;
      state.game.phase = "defense";
    } else if (state.game.phase !== "defense") {
      state.defense = null;
      state.nominated = null;
    }

    captureReveal(data);

    if (typeof data.message === "string" && data.message) {
      showReport(data.message, data.winner ? "good" : "info");
    }
  }

  function resultHasDefense(data) {
    return Boolean(data && data.defense && typeof data.defense === "object");
  }

  function normalizeTarget(raw) {
    if (!raw) {
      return null;
    }
    if (typeof raw === "string") {
      const player = findPlayer(raw);
      return { id: raw, name: player ? player.name : raw };
    }
    const id = idOf(raw);
    if (!id) {
      return null;
    }
    return {
      id,
      name: (raw && raw.name) || playerName(id),
    };
  }

  function normalizeDefense(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const speakerId = String(raw.speaker_id || raw.speakerId || raw.id || "");
    const speakerName = String(raw.speaker_name || raw.speakerName || raw.name || "")
      || (speakerId ? playerName(speakerId) : "");
    const text = String(raw.text || raw.content || raw.line || "");
    if (!speakerId && !speakerName && !text) {
      return null;
    }
    return {
      speaker_id: speakerId,
      speaker_name: speakerName || "被提名者",
      text: sanitizeLine(text, false),
    };
  }

  function normalizePerson(raw) {
    if (!raw) {
      return null;
    }
    if (typeof raw === "string") {
      const player = players().find((item) => item.name === raw);
      return { id: player ? player.id : raw, name: player ? player.name : raw };
    }
    let id = idOf(raw);
    let name = String((raw && raw.name) || "") || (id ? playerName(id) : "");
    if (!id && name) {
      const byName = players().find((item) => item.name === name);
      if (byName) {
        id = byName.id;
        name = byName.name;
      }
    } else if (id && !findPlayer(id)) {
      const byName = players().find((item) => item.name === name || item.name === id);
      if (byName) {
        id = byName.id;
        name = byName.name;
      }
    }
    if (!id && !name) {
      return null;
    }
    return { id, name };
  }

  function normalizeAftermath(raw) {
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null;
        }
        return {
          day: Math.max(1, Number(item.day) || 1),
          executed: normalizePerson(item.executed),
          killed: normalizePerson(item.killed),
          note: String(item.note || ""),
        };
      })
      .filter(Boolean);
  }

  function ensureYouPlayer() {
    if (!state.you || !state.you.id) {
      return;
    }
    const existing = players().find((player) => player.id === state.you.id);
    if (existing) {
      existing.is_you = true;
      return;
    }
    state.game.players.push({
      id: state.you.id,
      name: state.you.name || "你",
      public: state.you.public || "住客",
      alive: state.you.alive !== false,
      is_you: true,
    });
  }

  function applyDeadFlags() {
    if (!state.game || !Array.isArray(state.game.dead)) {
      return;
    }
    for (const item of state.game.dead) {
      const id = idOf(item);
      const name = typeof item === "object" && item ? item.name : (typeof item === "string" ? item : "");
      const player = findPlayer(id) || players().find((candidate) => candidate.name === name);
      if (player) {
        player.alive = false;
      }
    }
  }

  function revealNameFrom(data) {
    if (!data || typeof data !== "object") {
      return "";
    }
    const candidates = [
      data.murderer,
      data.culprit,
      data.murderer_id,
      data.murderer_name,
      data.reveal && data.reveal.murderer,
      data.reveal && data.reveal.culprit,
      data.reveal && data.reveal.murderer_id,
      data.reveal && data.reveal.murderer_name,
      data.reveal && data.reveal.name,
    ];
    for (const candidate of candidates) {
      const id = idOf(candidate);
      if (id) {
        const player = findPlayer(id);
        if (player) {
          return player.name || "";
        }
      }
      if (typeof candidate === "string") {
        const player = players().find((item) => item.name === candidate);
        return player ? player.name : candidate;
      }
      if (candidate && typeof candidate === "object" && candidate.name) {
        return candidate.name;
      }
    }
    return "";
  }

  function captureReveal(data) {
    const found = revealNameFrom(data);
    if (found) {
      state.revealName = found;
    }
  }

  function startGame(game) {
    state.gameId = game.game_id || "";
    state.you = game.you ? normalizeYou(game.you) : null;
    state.revealName = "";
    applyGame(game, { reset: true });
    hideGate();
    closeDrawer();
    $("end-overlay").classList.add("hidden");
    $("end-overlay").setAttribute("aria-hidden", "true");
    render();

  }

  function showGate(error) {
    const gate = $("gate");
    const status = error && error.status ? `（HTTP ${error.status}）` : "";
    const detail = (error && (error.detail || error.message)) || "服务器没有回应";
    $("gate-text").textContent = `无法连接 /blood 接口${status}：${detail}。可以重试，或先用演示模式验收界面。`;
    gate.classList.remove("hidden");
    gate.setAttribute("aria-hidden", "false");
  }

  function hideGate() {
    $("gate").classList.add("hidden");
    $("gate").setAttribute("aria-hidden", "true");
  }

  function render() {
    renderIdentity();
    renderHeader();
    renderSeats();
    appendLogEntries();
    renderDefense();
    renderVoteBoard();
    renderBallot();
    renderActionBar();
    renderReport();
    renderEnd();
  }

  function renderIdentity() {
    const role = youRole();
    const card = $("identity-card");
    const roleEl = $("identity-role");
    const detailEl = $("identity-detail");
    if (!state.game) {
      card.dataset.role = "villager";
      roleEl.textContent = "身份待定";
      detailEl.textContent = "正在开局……";
      detailEl.title = "";
      return;
    }
    card.dataset.role = role;
    roleEl.textContent = ROLE_LABEL[role] || "身份未知";
    const details = [];
    if (state.you && Array.isArray(state.you.private_info)) {
      details.push(...state.you.private_info);
    }
    if (state.you && Array.isArray(state.you.teammates) && state.you.teammates.length) {
      const names = state.you.teammates
        .map((mate) => (typeof mate === "string" ? (playerName(mate) || mate) : (mate && mate.name) || "？"))
        .filter(Boolean);
      if (names.length) {
        details.push(`同伙：${names.join("、")}`);
      }
    }
    const detail = details.join(" · ");
    detailEl.textContent = detail || (role === "murderer" ? "只有你知道自己做了什么。" : "你手上没有刀。");
    detailEl.title = detail;
  }

  function renderHeader() {
    const day = state.game ? state.game.day : 1;
    const phase = currentPhase();
    $("day-value").textContent = String(day);
    const phaseEl = $("phase-value");
    phaseEl.textContent = PHASE_LABEL[phase] || "白天讨论";
    phaseEl.dataset.phase = phase;
    document.body.dataset.phase = phase;
    $("table-day").textContent = `第 ${day} 夜`;
  }

  function orderedSeatPlayers() {
    const all = players();
    const you = all.find((player) => player.is_you) || null;
    const agents = all.filter((player) => !player.is_you);
    const ordered = [];
    if (you) {
      ordered.push({ player: you, slot: 0, figure: "traveler", tone: 0 });
    }
    agents.slice(0, 5).forEach((player, index) => {
      const figures = ["bun", "glasses", "braids", "hat", "cap"];
      ordered.push({
        player,
        slot: you ? index + 1 : index,
        figure: figures[index % figures.length],
        tone: (index % 5) + 1,
      });
    });
    return ordered;
  }

  function buildSeat(item) {
    const player = item.player;
    const seat = node("button", `seat slot-${item.slot} tone-${item.tone}`);
    seat.type = "button";
    seat.dataset.playerId = String(player.id);

    const portrait = node("span", "seat-portrait");
    const figure = node("span", `figure figure-${item.figure}`);
    figure.setAttribute("aria-hidden", "true");
    figure.append(node("span", "fig-extra"), node("span", "fig-head"), node("span", "fig-body"));
    portrait.append(figure);

    const plate = node("span", "seat-plate");
    const nameRow = node("span", "seat-name-row");
    nameRow.append(node("span", "seat-name", displayName(player)));
    if (player.is_you && displayName(player) !== "你") {
      nameRow.append(node("span", "you-tag", "你"));
    }
    plate.append(nameRow, node("span", "seat-role", shortPublic(player)));
    seat.append(portrait, plate);

    seat.addEventListener("click", () => onSeatClick(String(player.id)));
    return seat;
  }

  function renderSeats() {
    const container = $("seats");
    const ordered = orderedSeatPlayers();
    const signature = ordered
      .map((item) => `${item.player.id}:${item.slot}:${item.player.is_you ? 1 : 0}`)
      .join("|");
    if (container.dataset.sig !== signature) {
      container.textContent = "";
      const fragment = document.createDocumentFragment();
      for (const item of ordered) {
        fragment.append(buildSeat(item));
      }
      container.append(fragment);
      container.dataset.sig = signature;
    }
    updateSeatStates();
  }

  function canSelectPlayer(player) {
    if (!player || state.busy || !state.game) {
      return false;
    }
    if (player.is_you || player.alive === false) {
      return false;
    }
    const phase = currentPhase();
    if (phase === "nomination") {
      return youAlive();
    }
    if (phase === "defense") {
      return youAlive();
    }
    if (phase === "night") {
      return youAlive() && youRole() === "murderer";
    }
    return false;
  }

  function isValidTarget(player) {
    if (!player || !state.game || player.is_you || player.alive === false) {
      return false;
    }
    const phase = currentPhase();
    if (phase === "nomination") {
      return true;
    }
    if (phase === "defense") {
      return true;
    }
    if (phase === "night") {
      return youRole() === "murderer";
    }
    return false;
  }

  function updateSeatStates() {
    const phase = currentPhase();
    const nodes = document.querySelectorAll(".seat");
    for (const seat of nodes) {
      const player = findPlayer(seat.dataset.playerId);
      if (!player) {
        continue;
      }
      const selectable = canSelectPlayer(player);
      const selected = state.selectedId === player.id
        || (phase === "defense" && state.ballotTargetId === player.id);
      seat.classList.toggle("dead", player.alive === false);
      seat.classList.toggle("is-you", Boolean(player.is_you));
      seat.classList.toggle("speaking", state.speakingId === player.id);
      seat.classList.toggle("selectable", selectable);
      seat.classList.toggle("selected", selected);
      seat.disabled = !selectable;
      seat.setAttribute("aria-pressed", selected ? "true" : "false");
      seat.setAttribute(
        "aria-label",
        `${displayName(player)}，${player.alive === false ? "已出局" : "在场"}${player.is_you ? "，你" : ""}${selected ? "，已选中" : ""}`,
      );
      if (selectable && phase === "nomination") {
        seat.dataset.hint = "可提名";
      } else if (selectable && phase === "night") {
        seat.dataset.hint = "可动手";
      } else if (selectable && phase === "defense") {
        seat.dataset.hint = "可投";
      } else {
        delete seat.dataset.hint;
      }
      seat.title = String(player.public || "");
    }
  }

  function onSeatClick(playerId) {
    const player = findPlayer(playerId);
    if (!player || !canSelectPlayer(player)) {
      return;
    }
    const phase = currentPhase();
    if (phase === "defense") {
      state.ballotTargetId = playerId;
      state.selectedId = null;
      const options = $("ballot-options");
      if (options) {
        options.dataset.sig = "";
      }
      renderBallot();
      updateSeatStates();
      renderActionBar();
      return;
    }
    state.selectedId = state.selectedId === playerId ? null : playerId;
    updateSeatStates();
    renderActionBar();
  }

  function renderDayDivider(day) {
    return node("li", "log-day", `第 ${day} 天 · 雪夜`);
  }

  function renderEntry(entry) {
    const isYou = entry.speaker_id === youId();
    const narration = entry.speaker_id === "__narration"
      || entry.speaker_id === "narrator"
      || entry.speaker_name === "旁白";
    const item = node("li", "log-entry");
    if (isYou) {
      item.classList.add("you");
    }
    if (narration) {
      item.classList.add("narration");
    }
    item.append(
      node("p", "log-who", isYou
        ? (entry.speaker_name === "你" ? "你" : `${entry.speaker_name} · 你`)
        : entry.speaker_name),
      node("p", "log-text", entry.text),
    );
    return item;
  }

  function appendLogEntries() {
    const list = $("discussion-list");
    const log = (state.game && state.game.public_log) || [];
    const scroll = $("discussion-scroll");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 120;
    $("discussion-empty").classList.toggle("hidden", log.length > 0);

    const fresh = log.filter((entry) => entry.seq > state.lastSeq);
    if (!fresh.length) {
      updateDiscussionCount();
      return;
    }
    if (state.game.day !== state.lastDayShown) {
      list.append(renderDayDivider(state.game.day));
      state.lastDayShown = state.game.day;
    }
    for (const entry of fresh) {
      list.append(renderEntry(entry));
    }
    state.lastSeq = Math.max(state.lastSeq, maxSeq(fresh));
    updateDiscussionCount();

    if (nearBottom || fresh.length >= log.length) {
      scroll.scrollTop = scroll.scrollHeight;
    }

    const lastSpeakable = [...fresh]
      .reverse()
      .find((entry) => entry.speaker_id !== "__narration" && entry.speaker_name !== "旁白");
    if (lastSpeakable) {
      showBubble(lastSpeakable);
    }
  }

  function updateDiscussionCount() {
    const log = (state.game && state.game.public_log) || [];
    $("discussion-count").textContent = `${log.length} 条`;
  }

  function positionBubble(seatElement) {
    const stage = $("table-stage");
    const bubble = $("speech-bubble");
    const isNarrow = window.matchMedia("(max-width: 820px)").matches;
    bubble.classList.toggle("docked", isNarrow);
    if (isNarrow) {
      bubble.style.left = "";
      bubble.style.top = "";
      bubble.style.transform = "";
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const seatRect = seatElement.getBoundingClientRect();
    const centerX = seatRect.left - stageRect.left + seatRect.width / 2;
    const lowerHalf = seatRect.top - stageRect.top > stageRect.height * 0.42;
    const left = Math.max(150, Math.min(stageRect.width - 150, centerX));
    bubble.style.left = `${left}px`;
    bubble.classList.toggle("below", !lowerHalf);
    if (lowerHalf) {
      bubble.style.top = `${seatRect.top - stageRect.top - 10}px`;
      bubble.style.transform = "translate(-50%, -100%)";
    } else {
      bubble.style.top = `${seatRect.bottom - stageRect.top + 10}px`;
      bubble.style.transform = "translate(-50%, 0)";
    }
  }

  function showBubble(entry) {
    const seatElement = [...document.querySelectorAll(".seat")]
      .find((seat) => seat.dataset.playerId === entry.speaker_id);
    if (!seatElement) {
      return;
    }
    const text = entry.text.length > 96 ? `${entry.text.slice(0, 94)}…` : entry.text;
    const isNarrow = window.matchMedia("(max-width: 820px)").matches;
    const duplicateDefense = isNarrow
      && currentPhase() === "defense"
      && state.defense
      && entry.speaker_id === state.defense.speaker_id
      && entry.text === state.defense.text;
    if (duplicateDefense) {
      $("speech-bubble").classList.add("hidden");
      state.speakingId = null;
      state.speakingText = "";
      updateSeatStates();
      renderActionBar();
      return;
    }
    const bubble = $("speech-bubble");
    bubble.textContent = text;
    bubble.classList.remove("hidden");
    positionBubble(seatElement);
    state.speakingId = entry.speaker_id;
    state.speakingText = entry.text;
    updateSeatStates();
    renderActionBar();
    window.clearTimeout(state.bubbleTimer);
  }

  function clearBubble() {
    window.clearTimeout(state.bubbleTimer);
    $("speech-bubble").classList.add("hidden");
    state.speakingId = null;
    state.speakingText = "";
  }

  function renderDefense() {
    const card = $("defense-card");
    const phase = currentPhase();
    const nominated = state.nominated;
    const defense = state.defense;
    const active = Boolean(state.game) && phase === "defense" && nominated;
    if (!active) {
      card.classList.add("hidden");
      return;
    }
    $("defense-target").textContent = `被提名：${nominated.name || playerName(nominated.id)}`;
    $("defense-speaker").textContent = defense
      ? `${defense.speaker_name} 开口`
      : `${nominated.name || playerName(nominated.id)} 沉默`;
    $("defense-text").textContent = (defense && defense.text)
      || "被提名者没有立刻开口。桌上的目光都压了过来。";
    card.classList.remove("hidden");
  }

  function voteTallyRows() {
    const result = state.voteResult;
    if (!result) {
      return [];
    }
    const tally = [...(result.tally || [])].sort((left, right) => right.count - left.count);
    if (tally.length) {
      return tally;
    }
    const counts = new Map();
    for (const vote of result.votes || []) {
      counts.set(vote.targetId, (counts.get(vote.targetId) || 0) + 1);
    }
    return [...counts.entries()]
      .map(([id, count]) => ({ id, count }))
      .sort((left, right) => right.count - left.count);
  }

  function renderVoteBoard() {
    const board = $("vote-board");
    const result = state.voteResult;
    const discussion = board.closest(".discussion");
    if (discussion) {
      discussion.classList.toggle("voting", Boolean(state.game && result));
    }
    if (!state.game || !result) {
      board.classList.add("hidden");
      board.textContent = "";
      return;
    }
    const rows = voteTallyRows();
    const votes = result.votes || [];
    const threshold = result.threshold;
    const topCount = rows.length ? rows[0].count : 0;
    const short = Boolean(threshold) && topCount < threshold;
    board.textContent = "";
    board.dataset.short = short ? "1" : "0";

    const title = node("p", "vote-title");
    title.append(node("span", "", `第 ${result.day || state.game.day} 天 · 投票`));
    if (threshold) {
      title.append(node(
        "span",
        `vote-threshold${short ? " short" : ""}`,
        `已投 ${votes.length} / 需 ${threshold} 票（最高 ${topCount}）`,
      ));
    }
    board.append(title);

    if (rows.length) {
      const chips = node("div", "vote-tally");
      for (const row of rows) {
        chips.append(node("span", `vote-chip${row.count >= (threshold || 99) ? " reached" : ""}`,
          `${playerName(row.id)} ${row.count} 票`));
      }
      board.append(chips);
    }

    const executedName = result.executedName || "";
    const exec = node("div", `vote-exec ${executedName ? "is-executed" : "is-short"}`);
    exec.append(node("span", "exec-stamp", executedName ? "处决" : "未决"));
    exec.append(node("span", "exec-text", executedName
      ? `处决 · ${executedName} 被投票处决`
      : "未决 · 票数不够，今晚无人被处决"));
    board.append(exec);

    if (votes.length) {
      const groups = node("div", "vote-rows");
      let rowIndex = 0;
      const placed = new Set();
      for (const tallyRow of rows) {
        const group = node("div", "vote-group");
        group.append(node("p", "vote-target",
          `→ ${playerName(tallyRow.id)} · ${tallyRow.count} 票`));
        for (const vote of votes) {
          if (vote.targetId !== tallyRow.id) {
            continue;
          }
          group.append(buildVoteRow(vote, rowIndex));
          rowIndex += 1;
          placed.add(vote);
        }
        groups.append(group);
      }
      for (const vote of votes) {
        if (placed.has(vote)) {
          continue;
        }
        groups.append(buildVoteRow(vote, rowIndex));
        rowIndex += 1;
      }
      board.append(groups);
    }


    board.classList.remove("hidden");
  }

  function buildVoteRow(vote, index) {
    const row = node("div", "vote-row");
    row.style.animationDelay = `${Math.min(index, 8) * 90}ms`;
    const line = node("span", "vote-arrow");
    line.append(
      node("span", "vote-voter", vote.voterName || playerName(vote.voterId)),
      node("span", "vote-dash", "→"),
      node("span", "vote-target-name", vote.targetName || playerName(vote.targetId)),
    );
    const reason = node("span", "vote-reason");
    reason.append(
      node("span", "vote-reason-label", "理由"),
      node("span", `vote-reason-text${vote.reason ? "" : " is-empty"}`,
        vote.reason || "未留理由"),
    );
    row.append(line, reason);
    return row;
  }

  function ballotCandidates() {
    return players().filter((player) => player.alive !== false && !player.is_you);
  }

  function ballotTarget() {
    return findPlayer(state.ballotTargetId)
      || (state.nominated ? findPlayer(state.nominated.id) : null)
      || null;
  }

  function renderBallot() {
    const panel = $("ballot-panel");
    if (!panel) {
      return;
    }
    const phase = currentPhase();
    const visible = Boolean(state.game) && !isFinished() && youAlive() && phase === "defense";
    panel.classList.toggle("hidden", !visible);
    if (!visible) {
      const input = $("ballot-reason");
      if (input && input.value !== state.ballotReason) {
        input.value = state.ballotReason;
      }
      return;
    }

    const candidates = ballotCandidates();
    if (!state.ballotTargetId || !candidates.some((player) => player.id === state.ballotTargetId)) {
      state.ballotTargetId = state.nominated && candidates.some((player) => player.id === state.nominated.id)
        ? state.nominated.id
        : (candidates[0] ? candidates[0].id : null);
    }

    const options = $("ballot-options");
    const signature = candidates
      .map((player) => `${player.id}:${player.name}:${player.id === state.ballotTargetId ? 1 : 0}:${state.nominated && state.nominated.id === player.id ? 1 : 0}`)
      .join("|");
    if (options.dataset.sig !== signature) {
      options.textContent = "";
      for (const player of candidates) {
        const option = node("button", "ballot-option");
        option.type = "button";
        option.dataset.targetId = player.id;
        option.setAttribute("aria-pressed", player.id === state.ballotTargetId ? "true" : "false");
        option.append(node("span", "ballot-option-name", player.name));
        if (state.nominated && state.nominated.id === player.id) {
          option.append(node("span", "ballot-tag", "被提名"));
        }
        option.addEventListener("click", () => {
          state.ballotTargetId = player.id;
          state.selectedId = null;
          options.dataset.sig = "";
          renderBallot();
          updateSeatStates();
          renderActionBar();
        });
        options.append(option);
      }
      options.dataset.sig = signature;
    }

    const input = $("ballot-reason");
    if (input && document.activeElement !== input && input.value !== state.ballotReason) {
      input.value = state.ballotReason;
    }
    const note = $("ballot-note");
    if (note) {
      note.textContent = state.nominated
        ? `可投任意在场的人 · 提名「${state.nominated.name}」`
        : "可投任意在场的人";
    }
  }

  function showReport(text, kind = "info") {
    state.report = text || "";
    state.reportKind = kind;
    renderReport();
  }

  function renderReport() {
    const el = $("hall-report");
    if (!state.report) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    el.className = `hall-report ${state.reportKind}`;
    el.textContent = state.report;
    el.classList.remove("hidden");
  }

  function phaseHintText(phase) {
    if (!state.game) {
      return state.mock ? "演示模式：正在摆好圆桌……" : "正在推开旅馆的门……";
    }
    if (phase === "ended") {
      return "本局已结束。";
    }
    if (!youAlive()) {
      return "你已出局，只能旁观。点「继续观战」，让他们把这一夜走完。";
    }
    if (phase === "defense") {
      const target = state.nominated ? state.nominated.name : "被提名者";
      return `「${target}」正在自辩。听完再落票——可投任意在场的人，也能留一句理由。`;
    }
    if (phase === "nomination") {
      return "点席位选人，再按「提名」进入自辩。";
    }
    if (phase === "night") {
      return youRole() === "murderer"
        ? "熄灯了。选一个人，然后动手。"
        : "你不是凶手。闭上眼睛，等天亮。";
    }
    if (phase === "ended") {
      return "本局已结束。";
    }
    return "轮到你说话。问一句，或者按「结束讨论，提名」。";
  }

  function renderActionBar() {
    const phase = currentPhase();
    const finished = isFinished();
    const alive = youAlive();
    const role = youRole();
    const input = $("speak-input");
    const speakButton = $("speak-button");
    const secondary = $("secondary-button");
    const primary = $("primary-button");

    if (state.selectedId) {
      const selected = findPlayer(state.selectedId);
      if (!selected || !isValidTarget(selected)) {
        state.selectedId = null;
      }
    }

    const speakLocked = finished || state.busy || !alive || !state.game
      || (phase !== "discussion" && phase !== "defense");
    input.disabled = speakLocked;
    if (!state.game) {
      input.placeholder = "正在推开旅馆的门……";
    } else if (finished) {
      input.placeholder = "本局已结束";
    } else if (!alive) {
      input.placeholder = "你已出局，正在观战";
    } else if (phase === "defense") {
      const target = state.nominated ? state.nominated.name : "被提名者";
      input.placeholder = `质证「${target}」，或替自己辩一句`;
    } else if (phase === "nomination") {
      input.placeholder = "提名阶段——先选人，再提名";
    } else if (phase === "night") {
      input.placeholder = "灯已经熄了，等天亮再说";
    } else {
      input.placeholder = "对圆桌上的人说点什么";
    }
    speakButton.textContent = phase === "defense" ? "质证" : "发言";
    speakButton.disabled = speakLocked || !input.value.trim();

    let secondaryText = "";
    let secondaryVisible = false;
    if (state.game && !finished) {
      if (!alive) {
        secondaryText = "继续观战";
        secondaryVisible = true;
      } else if (phase === "discussion") {
        secondaryText = "结束讨论，提名";
        secondaryVisible = true;
      } else if (phase === "nomination") {
        secondaryText = "继续讨论";
        secondaryVisible = true;
      }
    }
    secondary.textContent = secondaryText || "结束讨论，提名";
    secondary.classList.toggle("hidden", !secondaryVisible);
    secondary.disabled = state.busy;

    let primaryText = "";
    let primaryVisible = false;
    let primaryDisabled = state.busy;
    const selection = findPlayer(state.selectedId);
    if (state.game && !finished && alive) {
      if (phase === "nomination") {
        primaryText = "提名";
        primaryVisible = true;
        primaryDisabled = primaryDisabled || !selection;
      } else if (phase === "defense") {
        const target = ballotTarget();
        primaryText = target ? `投票 · ${displayName(target)}` : "投票";
        primaryVisible = true;
        primaryDisabled = primaryDisabled || !target;
      } else if (phase === "night") {
        if (role === "murderer") {
          primaryText = "动手";
          primaryVisible = true;
          primaryDisabled = primaryDisabled || !selection;
        } else {
          primaryText = "等待天亮";
          primaryVisible = true;
        }
      }
    }
    primary.textContent = primaryText || "投票";
    primary.classList.toggle("hidden", !primaryVisible);
    primary.disabled = primaryDisabled;

    $("phase-hint").textContent = phaseHintText(phase);

    const hallHint = $("hall-hint");
    if (!state.game) {
      hallHint.textContent = state.mock ? "演示模式：正在摆好圆桌……" : "正在推开旅馆的门……";
    } else if (phase === "ended") {
      hallHint.textContent = "牌翻过来了。";
    } else if (!alive) {
      hallHint.textContent = "你已出局，观战中。他们还在桌边争论。";
    } else if (state.speakingId) {
      const speech = state.speakingText || "";
      const isNarrow = window.matchMedia("(max-width: 820px)").matches;
      if (isNarrow && speech) {
        const short = speech.length > 44 ? `${speech.slice(0, 42)}…` : speech;
        hallHint.textContent = `「${short}」 — ${playerName(state.speakingId)}`;
      } else {
        hallHint.textContent = `${playerName(state.speakingId)} 正开口。`;
      }
    } else if (phase === "defense") {
      const target = state.nominated ? state.nominated.name : "被提名者";
      hallHint.textContent = `「${target}」被推到了桌前，先自辩，再投票。`;
    } else if (phase === "nomination") {
      hallHint.textContent = "提名摆上了桌。点席位选人，再按「提名」先听自辩。";
    } else if (phase === "night") {
      hallHint.textContent = "灯熄了。雪光从窗缝里漏进来。";
    } else if (phase === "ended") {
      hallHint.textContent = "牌翻过来了。";
    } else {
      hallHint.textContent = "桌上摊着牌，谁都在看别人先开口。";
    }

    updateSeatStates();
  }

  function isVillagerWin() {
    return winnerLabel() === "好人胜";
  }

  function isMurdererWin() {
    return winnerLabel() === "凶手胜";
  }

  function inferredWinnerLabel() {
    const label = winnerLabel();
    if (label) {
      return label;
    }
    const message = (state.game && state.game.message) || "";
    if (message.includes("凶手胜") || message.includes("凶手还站着")) {
      return "凶手胜";
    }
    if (message.includes("好人胜") || message.includes("凶手伏法")) {
      return "好人胜";
    }
    return "";
  }

  function resolveRevealName() {
    if (state.revealName) {
      return state.revealName;
    }
    const fromGame = revealNameFrom(state.game);
    if (fromGame) {
      state.revealName = fromGame;
      return fromGame;
    }
    if (state.murdererName) {
      return state.murdererName;
    }
    if (state.murdererId) {
      const name = playerName(state.murdererId);
      if (name && name !== state.murdererId) {
        return name;
      }
    }
    if (youRole() === "murderer") {
      return displayName(youPlayer()) || "你";
    }
    if (state.voteResult && state.voteResult.executedName && isVillagerWin()) {
      return state.voteResult.executedName;
    }
    if (state.lastVotes && state.lastVotes.executedName && isVillagerWin()) {
      return state.lastVotes.executedName;
    }
    return "终局揭晓";
  }

  function revealRoleLabel() {
    const name = resolveRevealName();
    if (!name || name === "终局揭晓") {
      return "凶手 · 待卷宗封存";
    }
    return "凶手";
  }

  function hashIndex(text, size) {
    let hash = 0;
    const source = String(text || "");
    for (let index = 0; index < source.length; index += 1) {
      hash = (hash * 31 + source.charCodeAt(index)) | 0;
    }
    return Math.abs(hash) % size;
  }

  function renderEndPortrait() {
    const holder = $("end-portrait");
    if (!holder) {
      return;
    }
    holder.textContent = "";
    const name = resolveRevealName();
    const murderer = players().find((player) => player.name === name)
      || (youRole() === "murderer" ? youPlayer() : null);
    let figure = null;
    if (murderer) {
      const seat = [...document.querySelectorAll(".seat")]
        .find((item) => item.dataset.playerId === murderer.id);
      const original = seat ? seat.querySelector(".figure") : null;
      if (original) {
        figure = original.cloneNode(true);
      }
    }
    if (!figure) {
      const figures = ["bun", "glasses", "braids", "hat", "cap", "traveler"];
      const figureName = figures[hashIndex(name || "murderer", figures.length)];
      figure = node("span", `figure figure-${figureName}`);
      figure.setAttribute("aria-hidden", "true");
      figure.append(node("span", "fig-extra"), node("span", "fig-head"), node("span", "fig-body"));
    }
    figure.classList.add("end-figure");
    holder.append(figure);
  }

  function renderAftermath(list) {
    const box = $("end-aftermath");
    const target = $("end-aftermath-list");
    if (!box || !target) {
      return;
    }
    target.textContent = "";
    if (!Array.isArray(list) || !list.length) {
      box.classList.add("hidden");
      return;
    }
    box.classList.remove("hidden");
    for (const item of list) {
      const row = node("li", "end-aftermath-day");
      row.append(node("span", "ea-day", `第 ${item.day} 天`));
      const what = node("span", "ea-what");
      if (item.executed) {
        what.append(node("span", "ea-exec", `处决 · ${item.executed.name}`));
      }
      if (item.executed && item.killed) {
        what.append(document.createTextNode("　"));
      }
      if (item.killed) {
        what.append(node("span", "ea-kill", `夜杀 · ${item.killed.name}`));
      }
      if (!item.executed && !item.killed) {
        what.append(node("span", "ea-empty", "无人出局"));
      }
      row.append(what);
      if (item.note) {
        row.append(node("span", "ea-note", item.note));
      }
      target.append(row);
    }
  }

  function renderFatalVote() {
    const el = $("end-fatal");
    const result = state.voteResult;
    if (!el) {
      return;
    }
    if (!result || !result.executedId) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const execVotes = (Array.isArray(result.votes) ? result.votes : [])
      .filter((vote) => vote.targetId === result.executedId);
    if (!execVotes.length) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const index = Math.min(Math.max((Number(result.threshold) || 1) - 1, 0), execVotes.length - 1);
    const fatal = execVotes[index] || execVotes[execVotes.length - 1];
    const reason = fatal.reason
      ? `　${fatal.reason.startsWith("「") ? fatal.reason : `「${fatal.reason}」`}`
      : "";
    el.textContent = `致命一票 · ${fatal.voterName} → ${fatal.targetName}${reason}`;
    el.classList.remove("hidden");
  }

  function renderEnd() {
    const overlay = $("end-overlay");
    if (!isFinished()) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    const winner = inferredWinnerLabel();
    const result = winner === "好人胜" ? "villagers" : (winner === "凶手胜" ? "murderer" : "unknown");
    $("end-frame").dataset.result = result;
    $("end-kicker").textContent = result === "murderer" ? "NIGHTFALL · 结局" : "DAWN · 结局";
    $("end-title").textContent = winner || "天亮了";
    $("end-subtitle").textContent = (state.game && state.game.message) || "雪停了，真相留在了桌上。";
    $("end-murderer").textContent = resolveRevealName();
    $("end-murderer-role").textContent = revealRoleLabel();
    const role = youRole();
    $("end-you").textContent = `你 · ${ROLE_LABEL[role] || "身份未知"}`;
    $("end-days").textContent = `${state.game ? state.game.day : 1} 天`;
    renderEndPortrait();
    renderAftermath((state.game && state.game.aftermath) || []);
    renderFatalVote();
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function extractDrawerEntries(data) {
    if (Array.isArray(data)) {
      return normalizeLog(data);
    }
    if (!data || typeof data !== "object") {
      return [];
    }
    const raw = data.entries || data.log || data.public_log || data.events || [];
    return normalizeLog(raw);
  }

  function localLogEntries() {
    const day = state.game ? state.game.day : 1;
    return ((state.game && state.game.public_log) || []).map((entry) => ({ ...entry, day: entry.day || day }));
  }

  function renderDrawer(entries) {
    const list = $("log-drawer-list");
    const empty = $("log-drawer-empty");
    list.textContent = "";
    if (!entries.length) {
      empty.classList.remove("hidden");
      empty.textContent = state.game ? "本局还没有记录。" : "还没有开局。";
      $("log-drawer-count").textContent = "0 条";
      return;
    }
    empty.classList.add("hidden");
    for (const entry of entries) {
      const isYou = entry.speaker_id === youId();
      const narration = entry.speaker_id === "__narration"
        || entry.speaker_id === "narrator"
        || entry.speaker_name === "旁白";
      const item = node("li", "drawer-entry");
      if (isYou) {
        item.classList.add("is-you");
      }
      if (narration) {
        item.classList.add("is-narration");
      }
      const day = entry.day || (state.game && state.game.day) || 1;
      item.append(
        node("p", "drawer-meta", `第 ${day} 天 · ${isYou
          ? (entry.speaker_name === "你" ? "你" : `${entry.speaker_name} · 你`)
          : entry.speaker_name}`),
        node("p", "drawer-text", entry.text),
      );
      list.append(item);
    }
    $("log-drawer-count").textContent = `${entries.length} 条`;
  }

  async function openDrawer() {
    const drawer = $("log-drawer");
    drawer.classList.remove("hidden");
    drawer.setAttribute("aria-hidden", "false");
    state.drawerOpen = true;
    $("log-button").setAttribute("aria-expanded", "true");
    $("log-drawer-game").textContent = state.gameId || "";
    renderDrawer([]);
    if (!state.game) {
      return;
    }
    if (state.mock) {
      renderDrawer(localLogEntries());
      return;
    }
    try {
      const data = await apiRequest(`${API}/games/${state.gameId}/log`);
      renderDrawer(extractDrawerEntries(data));
    } catch (error) {
      renderDrawer(localLogEntries());
      showToast("回看接口未就绪，先显示本地记录。", "warn");
    }
  }

  function closeDrawer() {
    $("log-drawer").classList.add("hidden");
    $("log-drawer").setAttribute("aria-hidden", "true");
    state.drawerOpen = false;
    $("log-button").setAttribute("aria-expanded", "false");
  }

  function openConfirm(message, yesLabel, action) {
    state.pending = { action, yesLabel };
    $("confirm-text").textContent = message;
    $("confirm-yes").textContent = yesLabel;
    $("confirm-strip").classList.remove("hidden");
  }

  function closeConfirm() {
    state.pending = null;
    $("confirm-strip").classList.add("hidden");
  }

  function boot() {
    bindEvents();
    if (state.mock) {
      mockCreate();
    } else {
      runAction(createRealGame);
    }
  }

  const MOCK_AGENTS = [
    { id: "p1", name: "沈玉兰", public: "老板娘，四十二岁，掌管内宅与账目" },
    { id: "p2", name: "周砚青", public: "账房先生，三十八岁，寡言" },
    { id: "p3", name: "阿蘅", public: "女佣，十九岁，本地人，在旅馆做工三年" },
    { id: "p4", name: "陆明川", public: "旅客，三十岁，自称跑药材生意" },
    { id: "p5", name: "老韩", public: "马夫，五十五岁，在这家旅馆二十年" },
  ];

  const MOCK_OPENERS = {
    p1: "我十点前就睡下了。雪这么大，谁还有心思在走廊里转？",
    p2: "账我核过了，一分不差。别拿账本说事。",
    p3: "我送完炭就下楼了……真的，什么也没看见。",
    p4: "我不信巧合。昨晚二楼的地板响了两次，第二次比第一次轻。",
    p5: "我在马厩添草，快到半夜才回。楼上谁走动，我听得见。",
  };

  const MOCK_LINES = {
    p1: [
      "我管了这一屋子人二十年，轮不到谁拿话堵我。",
      "死的不是我的人，可这旅馆是我的。都给我把话说清楚。",
      "雪封山之前，谁也没出过这门。凶手就在桌边。",
    ],
    p2: [
      "我话少，不代表我好欺负。",
      "谁欠了钱，谁心里清楚，别往我身上推。",
      "账本上少的那一页，不是我撕的。",
    ],
    p3: [
      "我……我只想保住这份工。别问我了。",
      "我真的没上楼，你们别都看着我。",
      "我送炭的时候，门是虚掩着的。",
    ],
    p4: [
      "三年前那场火，账上写着意外。你们信吗？",
      "雪会停，脚印会没。可话一旦说出口，就收不回去。",
      "我只信证据。没有证据的猜测，都是替凶手省事。",
    ],
    p5: [
      "我在这旅馆二十年，见过的死人比你们吃过的盐多。",
      "马厩的灯亮了一夜。谁从后门过，我看得见。",
      "别把老骨头当傻子。谁夜里出去过，鞋上有雪。",
    ],
  };

  const SUSPECT_LINES = [
    "{name}，你昨晚到底几点回房？别拿雪当借口。",
    "我只问一句：{name} 鞋底的雪，是谁替他擦的？",
    "{name} 说得太顺了，顺得像背过。",
    "别看我，{name} 的袖口上有一道新口子。",
    "要我说，先把 {name} 的房间看一遍，再谈别的。",
  ];

  const REPLY_LINES = [
    "你说的我听见了。可昨晚走廊的脚印，不是你的鞋码。",
    "先别急着问别人，你自己几点回房的？",
    "漂亮话最不值钱。拿点真东西出来。",
    "你这么急着撇清，反倒让我记住你了。",
    "我只信自己看见的。你说得再多，也得有人替你作证。",
  ];

  const MOCK_DEFENSE_LINES = {
    p1: "我管这一屋子的账，夜里查灯油是本分。你们要我认什么？",
    p2: "账核过了，一分不差。拿不出凭据，就别把账房当凶手。",
    p3: "我送完炭就下楼了，没在楼上多留一刻。",
    p4: "我只信证据。没有证据就处决人，正合凶手的意。",
    p5: "我在马厩二十年，谁从后门过我都看得见。说我，得拿出个说法。",
  };

  const MOCK_DEFENSE_REPLIES = [
    "你要证据，可清白的人手里哪来的证据？",
    "这桌上谁都有旧账，为什么偏挑今夜的我？",
    "我问心无愧。你们若非要投我，那就投吧。",
  ];

  const MOCK_VOTE_REASONS = [
    "「{target}」前后两句话对不上，我这一票压过去。",
    "说的时辰和别人对不上，先请下去说清楚。",
    "{target}一直在问别人，自己夜里在哪儿却讲不清。",
    "我信不过{target}的鞋底——雪化了才回来。",
    "众人都在看，我也把话摆明：这一票给{target}。",
  ];

  const MOCK_SAVE_REASONS = [
    "{target}的话更像真的，我不想跟着众人的票走。",
    "比起{target}，另一个人今夜更说不清。",
  ];

  function shuffle(items) {
    const copy = items.slice();
    for (let index = copy.length - 1; index > 0; index -= 1) {
      const other = Math.floor(Math.random() * (index + 1));
      [copy[index], copy[other]] = [copy[other], copy[index]];
    }
    return copy;
  }

  function randomOf(items) {
    if (!items || !items.length) {
      return null;
    }
    return items[Math.floor(Math.random() * items.length)];
  }

  async function runAction(action) {
    if (state.busy) {
      return;
    }
    state.busy = true;
    clearBubble();
    renderActionBar();
    try {
      await action();
    } catch (error) {
      const message = (error && (error.detail || error.message)) || "请求失败";
      showToast(message, "warn", 4200);
      if (!state.game) {
        showGate(error);
      }
    } finally {
      state.busy = false;
      render();
    }
  }

  function bindEvents() {
    $("speak-form").addEventListener("submit", (event) => {
      event.preventDefault();
      handleSpeak();
    });
    $("speak-input").addEventListener("input", () => {
      const phase = currentPhase();
      $("speak-button").disabled = state.busy
        || !state.game
        || !youAlive()
        || (phase !== "discussion" && phase !== "defense")
        || !$("speak-input").value.trim();
    });
    $("ballot-reason").addEventListener("input", () => {
      state.ballotReason = $("ballot-reason").value.slice(0, 80);
    });
    $("primary-button").addEventListener("click", handlePrimary);
    $("secondary-button").addEventListener("click", handleSecondary);
    $("confirm-yes").addEventListener("click", () => {
      const pending = state.pending;
      closeConfirm();
      if (pending && typeof pending.action === "function") {
        runAction(pending.action);
      }
    });
    $("confirm-no").addEventListener("click", closeConfirm);
    $("restart-button").addEventListener("click", restartGame);
    $("end-restart").addEventListener("click", restartGame);
    $("log-button").addEventListener("click", () => {
      if (state.drawerOpen) {
        closeDrawer();
      } else {
        openDrawer();
      }
    });
    $("log-drawer-close").addEventListener("click", closeDrawer);
    $("end-log").addEventListener("click", openDrawer);
    $("gate-retry").addEventListener("click", () => {
      hideGate();
      runAction(createRealGame);
    });
    $("gate-mock").addEventListener("click", () => {
      hideGate();
      state.mock = true;

      mockCreate();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") {
        return;
      }
      if (!$("confirm-strip").classList.contains("hidden")) {
        closeConfirm();
      }
      if (state.drawerOpen) {
        closeDrawer();
      }
    });
    window.addEventListener("resize", () => {
      if (!state.speakingId) {
        return;
      }
      const seat = [...document.querySelectorAll(".seat")]
        .find((item) => item.dataset.playerId === state.speakingId);
      if (seat) {
        positionBubble(seat);
      }
    });
  }

  async function createRealGame() {
    const data = await apiRequest(`${API}/games`, { method: "POST", body: {} });
    if (!data || !data.game_id) {
      const error = new Error("接口没有返回 game_id");
      error.status = 502;
      throw error;
    }
    state.mock = false;
    startGame(data);
    try {
      await doDiscuss();
    } catch (error) {
      showToast(`开场发言失败：${(error && (error.detail || error.message)) || "未知错误"}`, "warn", 4000);
    }
  }

  async function refreshReal() {
    if (state.mock || !state.gameId) {
      return;
    }
    try {
      const data = await apiRequest(`${API}/games/${state.gameId}`);
      const report = state.report;
      const reportKind = state.reportKind;
      const defense = state.defense;
      const nominated = state.nominated;
      const heldDefense = Boolean(defense && nominated);
      applyGame(data);
      if (heldDefense && normalizePhase(state.game && state.game.phase) === "discussion") {
        state.game.phase = "defense";
        state.defense = defense;
        state.nominated = nominated;
      }
      state.report = report;
      state.reportKind = reportKind;
      render();
    } catch (error) {
      return;
    }
  }

  function addEntryIfMissing(entry) {
    const normalized = normalizeEntry(entry, nextSeq(state.game.public_log));
    if (!normalized) {
      return;
    }
    const log = state.game.public_log;
    const exists = log.some((item) => item.speaker_id === normalized.speaker_id && item.text === normalized.text);
    if (exists) {
      return;
    }
    log.push({ ...normalized, seq: nextSeq(log) });
  }

  function addOwnMessage(text) {
    const log = state.game.public_log;
    const id = youId();
    const exists = log.some((item) => item.speaker_id === id && item.text === text);
    if (!exists) {
      log.push({
        seq: nextSeq(log),
        speaker_id: id,
        speaker_name: "你",
        text,
        day: state.game.day,
      });
    }
  }

  function handleReplies(result) {
    applyGame(result);
    const replies = (result && Array.isArray(result.replies)) ? result.replies : [];
    for (const reply of replies) {
      addEntryIfMissing(reply);
    }
    render();
  }

  function handleSpeak() {
    const input = $("speak-input");
    const text = input.value.trim();
    if (!state.game || state.busy) {
      return;
    }
    if (!youAlive()) {
      showToast("你已出局，不能再发言。", "warn");
      return;
    }
    if (currentPhase() !== "discussion" && currentPhase() !== "defense") {
      showToast("现在不是发言的时机。", "warn");
      return;
    }
    if (!text) {
      return;
    }
    input.value = "";
    runAction(async () => {
      let result;
      if (state.mock) {
        result = mockSpeak(text);
      } else {
        result = await apiRequest(`${API}/games/${state.gameId}/speak`, {
          method: "POST",
          body: { text },
        });
      }
      handleReplies(result);
      addOwnMessage(text);
      render();
      if (!state.mock) {
        await refreshReal();
      }
    });
  }

  async function doDiscuss() {
    if (!state.game) {
      return;
    }
    let result;
    if (state.mock) {
      result = mockDiscuss();
    } else {
      result = await apiRequest(`${API}/games/${state.gameId}/discuss`, {
        method: "POST",
        body: {},
      });
    }
    handleReplies(result);
    if (!state.mock) {
      await refreshReal();
    }
  }

  async function doNominate(targetId) {
    let result;
    if (state.mock) {
      result = mockNominate(targetId);
    } else {
      result = await apiRequest(`${API}/games/${state.gameId}/nominate`, {
        method: "POST",
        body: { target_id: targetId },
      });
    }
    handleNominationResult(result, targetId);
    if (!state.mock) {
      await refreshReal();
    }
  }

  async function doVote(targetId, reason) {
    let result;
    const payloadReason = String(reason || "").trim();
    if (state.mock) {
      result = mockVote(targetId, payloadReason);
    } else {
      result = await apiRequest(`${API}/games/${state.gameId}/vote`, {
        method: "POST",
        body: { target_id: targetId, reason: payloadReason },
      });
    }
    handleVoteResult(result);
    if (!state.mock) {
      await refreshReal();
    }
  }

  function handleNominationResult(result, fallbackTargetId) {
    state.nominationMode = false;
    state.selectedId = null;
    closeConfirm();

    if (resultHasDefense(result)) {
      const target = normalizeTarget(result && result.target)
        || normalizeTarget(fallbackTargetId)
        || state.nominated;
      const defense = normalizeDefense(result && result.defense) || {
        speaker_id: target ? target.id : "",
        speaker_name: target ? target.name : "被提名者",
        text: "",
      };
      applyGame({ ...(result || {}), phase: "defense", defense, target });
      if (state.game) {
        state.game.phase = "defense";
      }
      state.defense = defense;
      state.nominated = target;
      state.ballotTargetId = target ? target.id : null;
      state.ballotReason = "";
      const name = target ? target.name : defense.speaker_name;
      showReport(`${name} 被提名上桌。先听自辩，质证完再投票。`, "warn");
      render();
      return;
    }

    handleVoteResult(result);
  }

  function tallyFromVotes(votes) {
    const counts = new Map();
    for (const vote of votes || []) {
      counts.set(vote.targetId, (counts.get(vote.targetId) || 0) + 1);
    }
    return [...counts.entries()]
      .map(([id, count]) => ({ id, count }))
      .sort((left, right) => right.count - left.count);
  }

  function handleVoteResult(result) {
    const votes = normalizeVotes(result && result.votes);
    let tally = normalizeTally(result && result.tally);
    if (!tally.length) {
      tally = tallyFromVotes(votes);
    }
    const aliveCount = players().filter((player) => player.alive !== false).length;
    const threshold = Number(result && result.threshold)
      || Math.floor(aliveCount / 2) + 1;
    const executedId = idOf(result && result.executed);
    const executedName = nameOf(result && result.executed)
      || (executedId ? playerName(executedId) : "");
    const executedPlayer = executedId
      ? (findPlayer(executedId) || players().find((player) => player.name === executedName || player.name === executedId))
      : null;
    const executedActualId = executedPlayer ? executedPlayer.id : executedId;
    state.voteResult = {
      votes,
      tally,
      threshold,
      executedId: executedActualId,
      executedName,
      day: state.game ? state.game.day : 1,
    };
    state.lastVotes = state.voteResult;
    state.nominationMode = false;
    state.selectedId = null;
    state.ballotTargetId = null;
    state.ballotReason = "";

    if (executedActualId) {
      markDead(executedActualId);
    }
    const payload = { ...(result || {}) };
    if (!payload.phase && !payload.winner) {
      payload.phase = "night";
    }
    applyGame(payload);
    if (state.game) {
      state.game.phase = normalizePhase(payload.phase) || "night";
    }
    state.defense = null;
    state.nominated = null;
    if (payload.reveal) {
      captureReveal(payload);
    }

    const message = (result && result.message)
      || (executedName ? `${executedName} 被处决，天黑了。` : "票数不够，今晚无人被处决。");
    showReport(message, executedName ? "warn" : "info");

    const wide = window.matchMedia("(min-width: 821px)").matches;
    if (wide && executedActualId === youId()) {
      showToast("票落在你头上。你已出局。", "warn", 4600);
    } else if (wide && executedName) {
      showToast(`处决：${executedName}。天黑了。`, "warn", 3600);
    }

    render();
    if (executedActualId) {
      flashExecuted(executedActualId);
    }
  }

  function flashExecuted(playerId) {
    const seat = [...document.querySelectorAll(".seat")]
      .find((item) => item.dataset.playerId === playerId);
    if (!seat) {
      return;
    }
    seat.classList.remove("just-executed");
    void seat.offsetWidth;
    seat.classList.add("just-executed");
    window.setTimeout(() => seat.classList.remove("just-executed"), 1900);
  }

  async function doNight(targetId) {
    let result;
    if (state.mock) {
      result = mockNight(targetId);
    } else {
      result = await apiRequest(`${API}/games/${state.gameId}/night`, {
        method: "POST",
        body: { target_id: targetId === undefined ? null : targetId },
      });
    }
    handleNightResult(result);
    if (!state.mock) {
      await refreshReal();
    }
  }

  function handleNightResult(result) {
    const killedId = idOf(result && result.killed);
    let killedName = nameOf(result && result.killed);
    if (!killedName && killedId) {
      killedName = playerName(killedId);
    }
    const killedPlayer = killedId
      ? (findPlayer(killedId) || players().find((player) => player.name === killedName || player.name === killedId))
      : null;
    const killedActualId = killedPlayer ? killedPlayer.id : killedId;
    if (killedActualId) {
      markDead(killedActualId);
    }
    const payload = { ...(result || {}) };
    if (!payload.phase && !payload.winner) {
      payload.phase = "discussion";
    }
    applyGame(payload);
    if (killedActualId) {
      markDead(killedActualId);
    }
    state.selectedId = null;
    state.nominationMode = false;
    state.lastVotes = null;
    state.voteResult = null;
    state.defense = null;
    state.nominated = null;
    if (payload.reveal) {
      captureReveal(payload);
    }


    const message = killedName
      ? (killedName === "你" ? "天亮时，你没有下楼。" : `天亮时，${killedName} 没有下楼。`)
      : ((result && result.message) || "天亮了，没有人死。");
    showReport(message, killedName ? "warn" : "info");
    if (killedActualId === youId()) {
      showToast("你没能熬到天亮。终局揭晓。", "warn", 5200);
    }
    render();
  }

  function normalizeVotes(raw) {
    if (Array.isArray(raw)) {
      return raw
        .map((vote) => {
          if (!vote || typeof vote !== "object") {
            return null;
          }
          const voterId = String(
            vote.voter_id || vote.voterId || vote.from_id || vote.from || vote.voter || "",
          );
          const targetId = idOf(
            vote.target_id || vote.targetId || vote.to_id || vote.to || vote.choice || vote.target,
          );
          if (!voterId || !targetId) {
            return null;
          }
          return {
            voterId,
            voterName: String(vote.voter_name || vote.voterName || "")
              || playerName(voterId),
            targetId,
            targetName: String(vote.target_name || vote.targetName || "")
              || playerName(targetId),
            reason: String(vote.reason || vote.why || vote.rationale || ""),
          };
        })
        .filter(Boolean);
    }
    if (raw && typeof raw === "object") {
      return Object.entries(raw)
        .map(([voterId, value]) => {
          const targetId = typeof value === "string" ? value : idOf(value);
          return targetId
            ? { voterId, voterName: playerName(voterId), targetId, targetName: playerName(targetId), reason: "" }
            : null;
        })
        .filter(Boolean);
    }
    return [];
  }

  function normalizeTally(raw) {
    if (Array.isArray(raw)) {
      return raw
        .map((item) => {
          if (!item || typeof item !== "object") {
            return null;
          }
          const id = idOf(item.target_id || item.targetId || item.id || item.player_id || item.target);
          const count = Number(item.votes ?? item.count ?? item.n ?? item.total ?? 0);
          return id && count ? { id, count } : null;
        })
        .filter(Boolean);
    }
    if (raw && typeof raw === "object") {
      return Object.entries(raw)
        .map(([id, value]) => {
          const count = typeof value === "number"
            ? value
            : Number((value && (value.votes ?? value.count)) || 0);
          return count ? { id, count } : null;
        })
        .filter(Boolean);
    }
    return [];
  }

  function markDead(id) {
    if (!id) {
      return;
    }
    const player = findPlayer(id) || players().find((candidate) => candidate.name === id);
    if (player) {
      player.alive = false;
      if (state.game && Array.isArray(state.game.dead)) {
        const exists = state.game.dead.some((item) => idOf(item) === player.id || item === player.id);
        if (!exists) {
          state.game.dead.push(player.id);
        }
      }
    }
  }

  async function observeNext() {
    const phase = currentPhase();
    if (!state.game) {
      return;
    }
    if (phase === "discussion") {
      await doDiscuss();
      if (!isFinished()) {
        state.nominationMode = true;
        state.selectedId = null;
        clearBubble();
        render();
      }
      return;
    }
    if (phase === "nomination") {
      const target = pickAliveAgent();
      if (!target) {
        throw new Error("桌上没有可提名的目标。");
      }
      await doNominate(target.id);
      return;
    }
    if (phase === "defense") {
      if (!state.nominated) {
        throw new Error("桌上没有正在自辩的人。");
      }
      await doVote(state.nominated.id);
      return;
    }
    if (phase === "night") {
      await doNight(null);
    }
  }

  function pickAliveAgent() {
    const pool = players().filter((player) => player.alive !== false && !player.is_you);
    return randomOf(pool);
  }

  function handleSecondary() {
    if (!state.game || state.busy) {
      return;
    }
    if (isFinished()) {
      renderEnd();
      return;
    }
    if (!youAlive()) {
      runAction(observeNext);
      return;
    }
    const phase = currentPhase();
    if (phase === "discussion") {
      state.nominationMode = true;
      state.selectedId = null;
      clearBubble();
      render();
      return;
    }
    if (phase === "nomination") {
      state.nominationMode = false;
      state.selectedId = null;
      render();
    }
  }

  function handlePrimary() {
    if (!state.game || state.busy || !youAlive()) {
      return;
    }
    const phase = currentPhase();
    if (phase === "nomination") {
      const target = findPlayer(state.selectedId);
      if (!target) {
        showToast("先点一位在场的人。", "warn");
        return;
      }
      openConfirm(
        `提名「${displayName(target)}」，先听自辩再投票？`,
        "确认提名",
        () => doNominate(target.id),
      );
      return;
    }
    if (phase === "defense") {
      const target = ballotTarget();
      if (!target) {
        showToast("先选一个投票目标。", "warn");
        return;
      }
      const reason = ($("ballot-reason").value || state.ballotReason || "").trim();
      state.ballotReason = reason;
      runAction(() => doVote(target.id, reason));
      return;
    }
    if (phase === "night") {
      if (youRole() === "murderer") {
        const target = findPlayer(state.selectedId);
        if (!target) {
          showToast("先选一个目标。", "warn");
          return;
        }
        openConfirm(
          `今晚对「${displayName(target)}」动手？这一步不可撤回。`,
          "确认动手",
          () => doNight(target.id),
        );
        return;
      }
      runAction(() => doNight(null));
    }
  }

  function restartGame() {
    if (state.busy) {
      return;
    }
    closeConfirm();
    closeDrawer();
    $("log-button").setAttribute("aria-expanded", "false");
    $("end-overlay").classList.add("hidden");
    $("end-overlay").setAttribute("aria-hidden", "true");
    state.game = null;
    state.you = null;
    state.gameId = null;
    state.selectedId = null;
    state.nominationMode = false;
    state.lastVotes = null;
    state.voteResult = null;
    state.defense = null;
    state.nominated = null;
    state.ballotTargetId = null;
    state.ballotReason = "";
    state.mockVotesCast = 0;
    state.mockAftermath = [];
    state.report = "";
    state.reportKind = "info";
    state.revealName = "";
    state.murdererId = "";
    state.murdererName = "";
    state.lastSeq = 0;
    state.lastDayShown = 0;
    state.drawerOpen = false;
    $("log-drawer").classList.add("hidden");
    $("log-drawer").setAttribute("aria-hidden", "true");
    $("discussion-list").textContent = "";
    $("discussion-empty").classList.remove("hidden");
    $("vote-board").classList.add("hidden");
    $("hall-report").classList.add("hidden");
    $("speak-input").value = "";
    clearBubble();
    render();
    if (state.mock) {
      mockCreate();
    } else {
      runAction(createRealGame);
    }
  }

  function mockCreate() {
    const forcedVillager = ["you-die", "short", "short2", "execute", "execute3", "vote-you"].includes(state.mockCase);
    const youMurderer = forcedVillager ? false : Math.random() < 0.38;
    const murderer = youMurderer
      ? "p0"
      : (state.mockCase ? "p5" : randomOf(MOCK_AGENTS).id);
    state.murdererId = murderer;
    state.murdererName = murderer === "p0"
      ? "你"
      : ((MOCK_AGENTS.find((agent) => agent.id === murderer) || {}).name || "未知");
    state.revealName = "";
    state.mockVotesCast = 0;
    state.mockAftermath = [];
    state.ballotTargetId = null;
    state.ballotReason = "";

    const players = [
      { id: "p0", name: "你", public: "封山夜最后一位住客", alive: true, is_you: true },
      ...MOCK_AGENTS.map((agent) => ({
        id: agent.id,
        name: agent.name,
        public: agent.public,
        alive: true,
        is_you: false,
      })),
    ];

    const you = {
      id: "p0",
      name: "你",
      role: youMurderer ? "murderer" : "villager",
      private_info: youMurderer
        ? ["你袖中藏着一把裁纸刀。今晚得让一个人再也开不了口。", "先让他们互相怀疑，别让目光落到你身上。"]
        : ["你半夜听见走廊里有人试门把手，却没看清那张脸。", "你不是凶手。可在这张桌上，清白也需要证据。"],
      teammates: [],
    };

    const log = [{
      seq: 1,
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: "暴雪封山，旅馆的门从外面锁死了。六个人围坐在大厅圆桌旁，没有人承认自己去过走廊。",
      day: 1,
    }];
    MOCK_AGENTS.forEach((agent, index) => {
      log.push({
        seq: index + 2,
        speaker_id: agent.id,
        speaker_name: agent.name,
        text: MOCK_OPENERS[agent.id],
        day: 1,
      });
    });

    const game = {
      game_id: `mock-${Math.random().toString(36).slice(2, 8)}`,
      day: 1,
      phase: "discussion",
      players,
      you,
      public_log: log,
      dead: [],
      message: "六个人，六个说法。你只有一夜时间，把谁的话撬开。",
      winner: null,
    };
    startGame(game);
  }

  function mockAlive() {
    return players().filter((player) => player.alive !== false);
  }

  function mockLine(agent) {
    const others = mockAlive().filter((player) => player.id !== agent.id);
    const other = randomOf(others);
    if (other && Math.random() < 0.55) {
      const template = randomOf(SUSPECT_LINES);
      return template.replace("{name}", displayName(other));
    }
    return randomOf(MOCK_LINES[agent.id]) || "桌上的话，我记着。";
  }

  function mockReply(agent) {
    if (Math.random() < 0.5) {
      const others = mockAlive().filter((player) => player.id !== agent.id);
      const other = randomOf(others);
      if (other) {
        return randomOf(SUSPECT_LINES).replace("{name}", displayName(other));
      }
    }
    return randomOf(REPLY_LINES);
  }

  function mockDiscuss() {
    const log = state.game.public_log;
    const speakers = shuffle(mockAlive().filter((player) => !player.is_you)).slice(0, 3);
    const replies = speakers.map((agent) => ({
      seq: nextSeq(log),
      speaker_id: agent.id,
      speaker_name: agent.name,
      text: mockLine(agent),
      day: state.game.day,
    }));
    log.push(...replies);
    return { replies, public_log: log.slice(), phase: "discussion" };
  }

  function mockSpeak(text) {
    const log = state.game.public_log;
    const inDefense = normalizePhase(state.game.phase) === "defense";
    log.push({
      seq: nextSeq(log),
      speaker_id: "p0",
      speaker_name: "你",
      text,
      day: state.game.day,
    });
    let speakers;
    if (inDefense && state.nominated) {
      const nominated = findPlayer(state.nominated.id);
      speakers = nominated && nominated.alive !== false
        ? [nominated]
        : shuffle(mockAlive().filter((player) => !player.is_you)).slice(0, 1);
    } else {
      speakers = shuffle(mockAlive().filter((player) => !player.is_you)).slice(0, 2);
    }
    const replies = speakers.map((agent) => ({
      seq: nextSeq(log),
      speaker_id: agent.id,
      speaker_name: agent.name,
      text: inDefense ? randomOf(MOCK_DEFENSE_REPLIES) : mockReply(agent),
      day: state.game.day,
    }));
    log.push(...replies);
    return { replies, public_log: log.slice(), phase: state.game.phase || "discussion" };
  }

  function mockNominate(targetId) {
    const target = findPlayer(targetId);
    if (!target || target.alive === false) {
      throw new Error("那不在桌上了。");
    }
    const text = MOCK_DEFENSE_LINES[target.id] || "该说的我都说过了。再问，我也只有这句话。";
    const defense = {
      speaker_id: target.id,
      speaker_name: target.name,
      text,
    };
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: target.id,
      speaker_name: target.name,
      text,
      day: state.game.day,
    });
    state.ballotTargetId = target.id;
    state.ballotReason = "";
    return {
      phase: "defense",
      target: { id: target.id, name: target.name },
      defense,
      public_log: log.slice(),
    };
  }

  function mockVote(targetId, reason) {
    const fallback = state.nominated || normalizeTarget(state.selectedId);
    const target = findPlayer(targetId) || (fallback ? findPlayer(fallback.id) : null);
    if (!target) {
      throw new Error("桌上没有正在自辩的人。");
    }
    if (target.alive === false) {
      throw new Error("那不在桌上了。");
    }
    const alive = mockAlive();
    const agents = alive.filter((player) => !player.is_you);
    const mode = state.mockCase;
    const firstRound = state.mockVotesCast === 0;
    const executeAll = mode === "execute" && firstRound;
    const executeThree = mode === "execute3" && firstRound;
    const voteYouOut = mode === "vote-you" && firstRound;
    const shortVote = (mode === "short" || mode === "short2" || mode === "you-die") && firstRound;
    let threshold = Math.floor(alive.length / 2) + 1;
    if (executeThree || voteYouOut) {
      threshold = 3;
    }
    const others = alive.filter((player) => player.id !== target.id && player.id !== youId());
    const votes = [];
    const me = youPlayer();

    agents.forEach((voter, index) => {
      let chosen = target;
      if (voteYouOut) {
        chosen = index < 3 ? (me || target) : (others[index % others.length] || target);
      } else if (executeThree) {
        chosen = index < 2 ? target : (others[index % others.length] || target);
      } else if (executeAll) {
        chosen = target;
      } else if (shortVote) {
        chosen = index === 0 ? target : (others[index % others.length] || target);
      } else if (voter.id === state.murdererId) {
        const safe = alive.filter((player) => player.id !== voter.id && player.id !== target.id);
        chosen = randomOf(safe.length ? safe : alive.filter((player) => player.id !== voter.id)) || target;
      } else if (Math.random() > 0.7) {
        const pool = alive.filter((player) => player.id !== voter.id && player.id !== target.id);
        chosen = randomOf(pool) || target;
      }
      votes.push({
        voter_id: voter.id,
        voter_name: voter.name,
        target_id: chosen.id,
        target_name: chosen.name,
        reason: voteReason(chosen, target, shortVote),
      });
    });

    votes.push({
      voter_id: youId(),
      voter_name: "你",
      target_id: target.id,
      target_name: target.name,
      reason: reason || `「${target.name}」的回应没能说服我，这一票投给${target.name}。`,
    });

    const tally = {};
    for (const vote of votes) {
      tally[vote.target_id] = (tally[vote.target_id] || 0) + 1;
    }
    const ranking = Object.entries(tally).sort((left, right) => right[1] - left[1]);
    const executedId = ranking.length && ranking[0][1] >= threshold ? ranking[0][0] : "";
    const executedName = executedId ? playerName(executedId) : "";
    if (executedId) {
      markMockDead(executedId);
    }
    state.mockVotesCast += 1;

    const murderer = findPlayer(state.murdererId);
    let winner = null;
    if (executedId === state.murdererId) {
      winner = "villagers";
    } else if (executedId === youId() || (murderer && murderer.alive === false)) {
      winner = "murderer";
    } else if (mockAlive().length <= 2 && murderer && murderer.alive !== false) {
      winner = "murderer";
    }

    const day = state.game.day;
    if (executedId) {
      state.mockAftermath.push({
        day,
        executed: { id: executedId, name: executedName },
        killed: null,
        note: `${tally[executedId] || 0} / ${threshold} 票过门槛`,
      });
    } else {
      state.mockAftermath.push({
        day,
        executed: null,
        killed: null,
        note: "票数不够，今晚无人被处决",
      });
    }

    const message = executedId
      ? `${executedName} 被投票处决，天黑了。`
      : "票数不够，今晚无人被处决。";
    const phase = winner ? "ended" : "night";
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: message,
      day: state.game.day,
    });
    return {
      votes,
      tally,
      threshold,
      executed: executedId ? { id: executedId, name: executedName } : null,
      winner,
      reveal: winner ? mockReveal() : null,
      message,
      public_log: log.slice(),
      aftermath: state.mockAftermath.slice(),
      phase,
    };
  }

  function voteReason(chosen, nominated, shortCase) {
    if (chosen.id === nominated.id || chosen.is_you) {
      return randomOf(MOCK_VOTE_REASONS).replace("{target}", chosen.name);
    }
    const template = randomOf(MOCK_SAVE_REASONS);
    return template.replace("{target}", chosen.name) + (shortCase ? "我还没想好要不要跟票。" : "");
  }

  function mockReveal() {
    return {
      murderer_id: state.murdererId,
      murderer_name: state.murdererName,
    };
  }

  function mockNight(targetId) {
    const youMurderer = state.murdererId === "p0";
    const forceYouDie = state.mockCase === "you-die";
    const forceAgentDie = (state.mockCase === "short" || state.mockCase === "short2") && !youMurderer;
    let killedId = "";
    let killedName = "";
    if (youMurderer) {
      const target = findPlayer(targetId);
      if (!target || target.alive === false || target.is_you) {
        throw new Error("请选择一名在场的目标。");
      }
      killedId = target.id;
      killedName = target.name;
    } else if (forceYouDie || forceAgentDie || Math.random() < 0.85) {
      const murderer = findPlayer(state.murdererId);
      if (murderer && murderer.alive !== false) {
        const pool = mockAlive().filter((player) => player.id !== state.murdererId);
        const youTicket = pool.find((player) => player.is_you);
        const agentPool = pool.filter((player) => !player.is_you);
        let victim;
        if (forceYouDie && youTicket) {
          victim = youTicket;
        } else if (forceAgentDie && agentPool.length) {
          victim = randomOf(agentPool);
        } else {
          victim = youTicket && Math.random() < 0.45 ? youTicket : randomOf(pool);
        }
        if (victim) {
          killedId = victim.id;
          killedName = victim.name;
        }
      }
    }
    if (killedId) {
      markMockDead(killedId);
      const night = state.game.day;
      const last = state.mockAftermath[state.mockAftermath.length - 1];
      if (last && last.day === night && !last.executed && !last.killed) {
        last.killed = { id: killedId, name: killedName };
        last.note = "票数不够，无人被处决；夜里又有人没有下楼。";
      } else {
        state.mockAftermath.push({
          day: night,
          executed: null,
          killed: { id: killedId, name: killedName },
          note: `${killedName}夜里没有下楼`,
        });
      }
    }

    const murderer = findPlayer(state.murdererId);
    let winner = null;
    if (murderer && murderer.alive === false) {
      winner = "villagers";
    } else if (killedId === youId() || mockAlive().length <= 2) {
      winner = "murderer";
    }

    const day = winner ? state.game.day : state.game.day + 1;
    const phase = winner ? "ended" : "discussion";
    state.game.day = day;
    const message = killedName
      ? `天亮时，${killedName} 没有下楼。`
      : "天亮时，没有人死。雪把脚印盖住了。";
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: message,
      day,
    });
    return {
      killed: killedId ? { id: killedId, name: killedName } : null,
      aftermath: state.mockAftermath.slice(),
      day,
      phase,
      winner,
      reveal: winner ? mockReveal() : null,
      message,
      public_log: log.slice(),
    };
  }

  function markMockDead(id) {
    const player = findPlayer(id);
    if (!player) {
      return;
    }
    player.alive = false;
    if (state.game && Array.isArray(state.game.dead) && !state.game.dead.some((item) => item === id)) {
      state.game.dead.push(id);
    }
  }

  boot();
})();