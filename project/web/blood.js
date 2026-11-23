(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const API = "/blood";
  const params = new URLSearchParams(window.location.search);

  const PHASE_LABEL = {
    discussion: "白天讨论",
    nomination: "提名投票",
    defense: "自辩质证",
    runoff: "平票加赛",
    night: "夜晚",
    spectating: "廊下观战",
    ended: "结束",
  };

  const ROLE_LABEL = {
    villager: "镇民",
    minion: "爪牙",
    murderer: "恶魔",
  };

  const EVIL_ROLES = ["murderer", "minion"];

  const SUCCESSION_HINT = "邪恶没有结束，桌上还得再来一轮。";

  const YOUR_RESULT_LABEL = {
    win: "你赢了",
    lose: "你输了",
    draw: "平局",
    late_good: "你出局后好人赢了",
    late_evil: "你出局后凶手逃脱",
  };

  const LOG_PLAY_INTERVAL = 190;

  const WINNER_LABEL = {
    villagers: "好人胜",
    village: "好人胜",
    good: "好人胜",
    innocent: "好人胜",
    murderer: "凶手胜",
    murderers: "凶手胜",
    killer: "凶手胜",
    evil: "凶手胜",
    escape: "凶手胜",
    escaped: "凶手胜",
    "好人": "好人胜",
    "好人阵营": "好人胜",
    "凶手": "凶手胜",
    "杀手": "凶手胜",
    "凶手逃脱": "凶手胜",
    "逃脱": "凶手胜",
  };

  const CONFIDE_PER_DAY = 1;
  const CONFIDE_PER_GAME = 3;
  const INSPECT_PER_GAME = 1;
  const SPEAK_MAX_CHARS = 200;
  const SPEAK_SOURCE_MAX = 600;

  const STANCE_LABEL = {
    accept: "接受",
    refuse: "拒绝",
    evade: "回避",
    threaten: "威胁",
    promise: "许了个诺",
    betray: "反悔了",
    neutral: "不动声色",
  };

  const state = {
    mock: params.get("mock") === "1",
    mockCase: params.get("case") || "",
    mockVotesCast: 0,
    mockLastVoteTie: false,
    game: null,
    gameId: null,
    you: null,
    selectedId: null,
    nominationMode: false,
    busy: false,
    lastSeq: 0,
    lastDayShown: 0,
    speakingId: null,
    speakingId: null,
    speakingText: "",
    bubbleTimer: 0,
    lastVotes: null,
    voteResult: null,
    lastVoteResult: null,
    voteHeld: false,
    defense: null,
    nominated: null,
    ballotTargetId: null,
    ballotReason: "",
    runoffCandidates: [],
    runoffPickId: null,
    runoffStalemate: 0,
    mockAftermath: [],
    report: "",
    reportKind: "info",
    murdererId: "",
    murdererName: "",
    revealName: "",
    pending: null,
    drawerOpen: false,
    drawerTab: "public",
    localEvents: [],
    privateLog: [],
    confideOpen: false,
    confideTargetId: null,
    confideReply: null,
    confideUsedToday: 0,
    confideUsedTotal: 0,
    confideDay: 1,
    confideSnapshots: {},
    inspectOpen: false,
    inspectTargetId: null,
    inspectUsed: false,
    inspectResult: null,
    inspectAvailable: null,
    lastWordsAvailable: null,
    lastWordsProbed: false,
    lastWordsUsed: false,
    lastWordsText: "",
    speakLimitNotice: "",
    userScrolled: false,
    ignoreScroll: false,
    stickForce: false,

    endPending: false,
    endRevealed: false,
    inspectReveal: false,
    inspectRevealed: false,
    ghostVoteAvailable: null,
    ghostVoteUsed: false,
    ghostTargetId: null,
    ghostVotes: [],
    ghostDismissed: false,
    advancing: false,
    lastKilledName: "",
    thresholdReduced: false,
    mockSpectateStep: 0,
    mockSpectateVotes: [],
    mockGhostVote: null,
    revealInfo: null,

    mockMinionId: "",
    mockOriginalMinionId: "",
    mockOriginalDemonId: "",
    mockSuccession: [],
    mockPoisonedId: "",
    mockWhisperDay: 0,
    successionPending: false,

    logQueue: [],
    logQueueTimer: 0,
    spectateFeed: [],
    spectateFeedDay: 0,
    nightTransitionTimer: 0,
    nightTransitionOpen: false,
    endYourResult: "",
    endKilledInfo: null,
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
    if (["runoff", "re-vote", "revote", "tiebreak", "加赛", "再投", "平票加赛"].includes(raw)) {
      return "runoff";
    }
    if (["night", "夜晚", "夜间"].includes(raw)) {
      return "night";
    }
    if (["spectating", "spectate", "ghost", "observer", "观战", "旁观", "廊下观战"].includes(raw)) {
      return "spectating";
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
    if (raw.includes("spectat") || raw.includes("观战") || raw.includes("旁观")) {
      return "spectating";
    }
    if (raw.includes("defen") || raw.includes("自辩") || raw.includes("质证") || raw.includes("辩护")) {
      return "defense";
    }
    if (raw.includes("runoff") || raw.includes("加赛") || raw.includes("再投")) {
      return "runoff";
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
    if (["murderer", "killer", "wolf", "demon", "凶手", "杀手", "狼", "恶魔"].includes(raw)) {
      return "murderer";
    }
    if (["minion", "accomplice", "claw", "爪牙", "帮凶", "走狗"].includes(raw)) {
      return "minion";
    }
    return "villager";
  }

  function isEvilRole(role) {
    return EVIL_ROLES.includes(role);
  }

  const NARRATION_FEMALE_HINTS = ["沈玉兰", "阿蘅", "刘妈", "老板娘", "女佣", "她"];

  function stripDanglingMemory(text) {
    return String(text || "")
      .split(/我还记得[:：]/u)[0]
      .replace(/[，,、；;\s]*(?:我还记得|我记得)[:：]\s*$/u, "")
      .trim();
  }

  function sanitizeReason(text, targetName = "") {
    const cleaned = stripDanglingMemory(text)
      .replace(/[，,、；;：:\s]+$/u, "")
      .trim();
    if (!cleaned) {
      return "";
    }
    return cleaned
      .replace(/某人|某某|该玩家|某个玩家/gu, targetName || "他")
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

  function publicSafeText(text, narration = false) {
    const raw = String(text || "");
    if (!narration) {
      return raw;
    }
    if (state.game && state.game.winner) {
      return raw;
    }
    if (/邪恶没有结束|游戏继续/u.test(raw)) {
      return raw;
    }
    if (/下药|被下药|毒醉|中毒/u.test(raw)) {
      const victim = raw.match(/(?:天亮时[，,]?\s*)?(你|[^\s，,。；;]{1,6})\s*(?:被下药|被毒|中毒|毒醉)/u);
      return victim ? `天亮时，${victim[1]} 没有下楼。` : "天亮时，有人没有下楼。";
    }
    if (/爪牙|传位|接位|继位|新恶魔/u.test(raw)) {
      if (/没有下楼|死在|天亮|不见/u.test(raw)) {
        return raw.replace(/爪牙|新恶魔|传位|接位|继位/gu, "有人");
      }
      return SUCCESSION_HINT;
    }
    return raw;
  }

  function isWhisperText(text) {
    const raw = String(text || "");
    return /低声[^，。]{0,6}(?:说了|几句|说了几句)/u.test(raw)
      || /廊下低声/u.test(raw);
  }

  function isSelfWhisperText(text) {
    const raw = String(text || "").trim();
    return /^你(?:与|和|跟)/u.test(raw) || raw.includes("你与") || raw.includes("你和");
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
        return displayName(player);
      }
      if (typeof value === "object" && value.name) {
        return value.name;
      }
      return "";
    }
    if (typeof value === "object" && value.name) {
      const byName = players().find((player) => player.name === value.name);
      return byName ? displayName(byName) : value.name;
    }
    return "";
  }

  function playerName(id) {
    if (!id) {
      return "";
    }
    const player = findPlayer(id);
    if (player) {
      return displayName(player);
    }
    return String(id);
  }

  function displayName(player) {
    if (!player) {
      return "";
    }
    if (player.is_you) {
      return "你";
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
    if (state.game.you_alive === false) {
      return "spectating";
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
    mergeNewEntries(data);

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
    state.lastVoteResult = null;
    state.defense = null;
      state.nominated = null;
      state.ballotTargetId = null;
      state.ballotReason = "";
      state.report = "";
      state.reportKind = "info";
      state.speakingId = null;
      state.pending = null;
      state.voteHeld = false;
      state.endPending = false;
      state.endRevealed = false;
      state.confideOpen = false;
      state.confideReply = null;
      state.confideTargetId = null;
      state.confideUsedToday = 0;
      state.confideUsedTotal = 0;
      state.confideDay = 1;
      state.confideSnapshots = {};
      state.privateLog = [];
      state.localEvents = [];
      state.inspectOpen = false;
      state.inspectTargetId = null;
      state.inspectUsed = false;
      state.inspectResult = null;
      state.inspectAvailable = null;
      state.lastWordsAvailable = null;
      state.lastWordsProbed = false;
      state.lastWordsUsed = false;
      state.lastWordsText = "";
      state.runoffCandidates = [];
      state.runoffPickId = null;
      state.runoffStalemate = 0;
      state.userScrolled = false;
      state.ignoreScroll = false;
      state.stickForce = false;
      state.inspectReveal = false;
      state.inspectRevealed = false;
      state.ghostVoteAvailable = null;
      state.ghostVoteUsed = false;
      state.ghostTargetId = null;
      state.ghostVotes = [];
      state.ghostDismissed = false;
      state.advancing = false;
      state.lastKilledName = "";
      state.thresholdReduced = false;
      state.mockSpectateStep = 0;
      state.mockSpectateVotes = [];
state.mockGhostVote = null;
      state.revealInfo = null;
      state.successionPending = false;
      state.logQueue = [];
      state.spectateFeed = [];
      state.spectateFeedDay = 0;
      state.endYourResult = "";
      state.endKilledInfo = null;
      window.clearTimeout(state.logQueueTimer);
      state.logQueueTimer = 0;

      state.drawerTab = "public";
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
        ? normalizeDayHistory(data.aftermath)
        : (options.reset ? [] : (previous.aftermath || [])),
      day_history: data.day_history !== undefined
        ? normalizeDayHistory(data.day_history)
        : (previous.day_history || []),
      you_alive: data.you_alive !== undefined
        ? Boolean(data.you_alive)
        : (previous.you_alive === undefined ? null : previous.you_alive),
      your_result: data.your_result !== undefined
        ? String(data.your_result || "")
        : (data.you_result !== undefined ? String(data.you_result || "") : (previous.your_result || "")),
      you_win: typeof data.you_win === "boolean"
        ? data.you_win
        : (typeof previous.you_win === "boolean" ? previous.you_win : null),
    };

    if (!state.game.phase) {
      state.game.phase = "discussion";
    }
    if (state.game.game_id) {
      state.gameId = state.game.game_id;
    }

    const runoffRaw = data.runoff_candidates || data.runoffCandidates;
    if (Array.isArray(runoffRaw)) {
      state.runoffCandidates = runoffRaw
        .map((item) => idOf(item) || String(item || ""))
        .filter(Boolean);
    } else if (options.reset) {
      state.runoffCandidates = [];
    }
    const stalemateRaw = data.stalemate_count !== undefined
      ? data.stalemate_count
      : data.stalemateCount;
    if (stalemateRaw !== undefined && stalemateRaw !== null) {
      state.runoffStalemate = Math.max(0, Number(stalemateRaw) || 0);
    }
    if (data.threshold_reduced !== undefined || data.thresholdReduced !== undefined) {
      state.thresholdReduced = Boolean(
        data.threshold_reduced !== undefined ? data.threshold_reduced : data.thresholdReduced,
      );
    }
    if (data.ghost_vote_available !== undefined) {
      state.ghostVoteAvailable = Boolean(data.ghost_vote_available);
    } else if (data.ghostVoteAvailable !== undefined) {
      state.ghostVoteAvailable = Boolean(data.ghostVoteAvailable);
    } else if (options.reset) {
      state.ghostVoteAvailable = null;
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

    if (state.game.phase === "runoff" && !state.runoffCandidates.length) {
      state.runoffCandidates = ballotCandidates().map((player) => player.id);
    }
    if (state.game.phase === "defense"
      || state.game.phase === "runoff"
      || state.game.phase === "night") {
      state.stickForce = true;
    }

    captureReveal(data);
    noteSuccessionHint(data);
    if (data.winner && !state.endRevealed) {
      state.endPending = true;
    }

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
      return { id: player ? player.id : raw, name: player ? displayName(player) : raw };
    }
    let id = idOf(raw);
    let name = String((raw && raw.name) || "") || (id ? playerName(id) : "");
    if (id) {
      const player = findPlayer(id);
      if (player) {
        return { id, name: displayName(player) };
      }
    }
    if (!id && name) {
      const byName = players().find((item) => item.name === name);
      if (byName) {
        id = byName.id;
        name = displayName(byName);
      }
    } else if (id && !findPlayer(id)) {
      const byName = players().find((item) => item.name === name || item.name === id);
      if (byName) {
        id = byName.id;
        name = displayName(byName);
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
          tie: Boolean(item.tie || item.tied),
          tally: normalizeTally(item.tally || []),
          threshold: Number(item.threshold) || 0,
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
    const reveal = data.reveal && typeof data.reveal === "object" ? data.reveal : {};
    const candidates = [
      reveal.final_murderer_id,
      reveal.final_murderer_name,
      reveal.final_murderer,
      data.final_murderer_id,
      data.final_murderer_name,
      data.final_murderer,
      data.murderer,
      data.culprit,
      data.murderer_id,
      data.murderer_name,
      reveal.murderer,
      reveal.culprit,
      reveal.murderer_id,
      reveal.murderer_name,
      reveal.demon_id,
      reveal.demon_name,
      reveal.demon,
      reveal.name,
    ];
    for (const candidate of candidates) {
      const id = idOf(candidate);
      if (id) {
        const player = findPlayer(id);
        if (player) {
          return displayName(player);
        }
      }
      if (typeof candidate === "string") {
        const player = players().find((item) => item.name === candidate);
        return player ? displayName(player) : candidate;
      }
      if (candidate && typeof candidate === "object" && candidate.name) {
        const player = players().find((item) => item.name === candidate.name || item.id === candidate.name);
        return player ? displayName(player) : candidate.name;
      }
    }
    if (state.revealInfo && state.revealInfo.final && state.revealInfo.final.name) {
      return state.revealInfo.final.name;
    }
    if (state.revealInfo && state.revealInfo.demon && state.revealInfo.demon.name) {
      return state.revealInfo.demon.name;
    }
    return "";
  }

  function personRef(value) {
    if (!value) {
      return { id: "", name: "" };
    }
    const id = idOf(value);
    if (id) {
      const player = findPlayer(id);
      return { id, name: player ? displayName(player) : String(id) };
    }
    if (typeof value === "string") {
      const player = players().find((item) => item.name === value || item.id === value);
      return { id: player ? player.id : "", name: player ? displayName(player) : value };
    }
    if (typeof value === "object" && value.name) {
      const player = players().find((item) => item.name === value.name || item.id === value.name);
      return {
        id: player ? player.id : String(value.id || ""),
        name: player ? displayName(player) : String(value.name),
      };
    }
    return { id: "", name: "" };
  }

  function firstPersonRef(pairs) {
    for (const pair of pairs) {
      if (!pair || pair[1] === undefined || pair[1] === null || pair[1] === "") {
        continue;
      }
      const ref = personRef(pair[1]);
      if (ref.name || ref.id) {
        return ref;
      }
    }
    return { id: "", name: "" };
  }

  function normalizeSuccession(raw) {
    if (!raw) {
      return [];
    }
    const list = Array.isArray(raw) ? raw : (typeof raw === "object" ? [raw] : []);
    if (typeof raw === "string") {
      return [{ label: raw, day: 0, from: "", to: "" }];
    }
    const steps = [];
    for (const item of list) {
      if (typeof item === "string") {
        const ref = personRef(item);
        steps.push({ label: ref.name ? `原爪牙 ${ref.name} 接位` : item, day: 0, from: "", to: ref.name });
        continue;
      }
      if (!item || typeof item !== "object") {
        continue;
      }
      const from = firstPersonRef([
        ["from_name", item.from_name],
        ["from", item.from],
        ["from_id", item.from_id],
        ["old_name", item.old_name],
        ["old_id", item.old_id],
        ["demon_name", item.demon_name],
        ["demon_id", item.demon_id],
      ]);
      const to = firstPersonRef([
        ["to_name", item.to_name],
        ["to", item.to],
        ["to_id", item.to_id],
        ["new_name", item.new_name],
        ["new_id", item.new_id],
        ["minion_name", item.minion_name],
        ["minion_id", item.minion_id],
      ]);
      const day = Number(item.day || item.round || item.night) || 0;
      const label = String(item.label || item.text || item.note || "").trim();
      if (!from.name && !to.name && !label) {
        continue;
      }
      steps.push({ label, day, from: from.name || "", to: to.name || "" });
    }
    return steps;
  }

  function captureReveal(data) {
    if (!data || typeof data !== "object") {
      return;
    }
    const reveal = data.reveal && typeof data.reveal === "object" ? data.reveal : null;
    const source = reveal || data;
    const info = state.revealInfo || {
      demon: { id: "", name: "" },
      final: { id: "", name: "" },
      minion: { id: "", name: "" },
      poisoned: { id: "", name: "" },
      killed: { id: "", name: "" },
      executed: { id: "", name: "" },
      succession: [],
    };
    if (!info.killed) {
      info.killed = { id: "", name: "" };
    }
    if (!info.executed) {
      info.executed = { id: "", name: "" };
    }
    const demon = firstPersonRef([
      ["murderer_id", source.murderer_id],
      ["murderer", source.murderer],
      ["culprit", source.culprit],
      ["murderer_name", source.murderer_name],
      ["demon_id", source.demon_id],
      ["demon", source.demon],
      ["demon_name", source.demon_name],
      ["killer_id", source.killer_id],
    ]);
    if (demon.name || demon.id) {
      info.demon = demon;
    }
    const final = firstPersonRef([
      ["final_murderer_id", source.final_murderer_id],
      ["final_murderer_name", source.final_murderer_name],
      ["final_murderer", source.final_murderer],
      ["new_murderer_id", source.new_murderer_id],
      ["new_murderer_name", source.new_murderer_name],
      ["new_murderer", source.new_murderer],
      ["current_murderer_id", source.current_murderer_id],
    ]);
    if (final.name || final.id) {
      info.final = final;
    }
    const minion = firstPersonRef([
      ["minion_id", source.minion_id],
      ["minion", source.minion],
      ["minion_name", source.minion_name],
      ["accomplice_id", source.accomplice_id],
      ["accomplice", source.accomplice],
    ]);
    if (minion.name || minion.id) {
      info.minion = minion;
    }
    const poisoned = firstPersonRef([
      ["poisoned_id", source.poisoned_id],
      ["poisoned", source.poisoned],
      ["poisoned_name", source.poisoned_name],
      ["drunk_id", source.drunk_id],
      ["drunk", source.drunk],
      ["drunk_name", source.drunk_name],
    ]);
    if (poisoned.name || poisoned.id) {
      info.poisoned = poisoned;
    }
    const killed = firstPersonRef([
      ["killed_id", source.killed_id],
      ["killed", source.killed],
      ["killed_name", source.killed_name],
      ["night_killed_id", source.night_killed_id],
      ["night_killed", source.night_killed],
      ["night_killed_name", source.night_killed_name],
      ["victim_id", source.victim_id],
      ["victim_name", source.victim_name],
    ]);
    if (killed.name || killed.id) {
      info.killed = killed;
    }
    const executed = firstPersonRef([
      ["executed_id", source.executed_id],
      ["executed", source.executed],
      ["executed_name", source.executed_name],
    ]);
    if (executed.name || executed.id) {
      info.executed = executed;
    }
    const successionRaw = source.succession !== undefined
      ? source.succession
      : (source.succeeded !== undefined ? source.succeeded : source.handoff);
    if (successionRaw !== undefined) {
      const steps = normalizeSuccession(successionRaw);
      if (steps.length) {
        info.succession = steps;
      } else if (successionRaw === true) {
        const holder = minion.name ? minion : info.minion;
        if (holder.name) {
          info.succession = [{ label: `原爪牙 ${holder.name} 接位`, day: 0, from: "", to: holder.name }];
        }
      }
    }
    if (!info.final.name && info.succession.length) {
      const lastStep = [...info.succession].reverse().find((step) => step.to);
      if (lastStep) {
        const ref = personRef(lastStep.to);
        if (ref.name) {
          info.final = ref;
        }
      }
    }
    if (!info.final.name && info.demon.name) {
      info.final = { ...info.demon };
    }
    if (!info.minion.name && info.succession.length) {
      const firstStep = info.succession.find((step) => step.to);
      if (firstStep) {
        const ref = personRef(firstStep.to);
        if (ref.name) {
          info.minion = ref;
        }
      }
    }
    if (!info.demon.name && info.succession.length) {
      const firstFrom = info.succession.find((step) => step.from);
      if (firstFrom) {
        const ref = personRef(firstFrom.from);
        if (ref.name) {
          info.demon = ref;
        }
      }
    }
state.revealInfo = info;
    const explicitFinal = Boolean(final.name || final.id);
    const found = revealNameFrom(data);
    if (!explicitFinal && info.final.name) {
      state.revealName = info.final.name;
    } else if (found) {
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
    syncConfideDay();
    renderIdentity();
    renderHeader();
    renderSeats();
    appendLogEntries();
    renderDefense();
    renderVoteBoard();
    renderSpectate();
    renderGhostVote();
    renderConfide();
    renderInspect();
    renderBallot();
    renderRunoff();
    renderActionBar();
    renderReport();
    renderLastWords();
    renderEnd();
    stickDiscussionToBottom();
  }

  function syncConfideDay() {
    const day = state.game ? state.game.day : 1;
    if (state.confideDay !== day) {
      state.confideDay = day;
      state.confideUsedToday = 0;
    }
  }

  function renderIdentity() {
    const role = youRole();
    const card = $("identity-card");
    const roleEl = $("identity-role");
    const detailEl = $("identity-detail");
    const mateEl = $("identity-mate");
    if (!state.game) {
      card.dataset.role = "villager";
      roleEl.textContent = "身份待定";
      detailEl.textContent = "正在开局……";
      detailEl.title = "";
      if (mateEl) {
        mateEl.textContent = "";
        mateEl.title = "";
        mateEl.classList.add("hidden");
      }
      return;
    }
    card.dataset.role = role;
    roleEl.textContent = ROLE_LABEL[role] || "身份未知";
    const details = [];
    if (state.you && Array.isArray(state.you.private_info)) {
      details.push(...state.you.private_info);
    }
    let mateNames = [];
    if (isEvilRole(role) && state.you && Array.isArray(state.you.teammates) && state.you.teammates.length) {
      mateNames = state.you.teammates
        .map((mate) => {
          if (typeof mate === "string") {
            return playerName(mate) || mate;
          }
          if (mate && typeof mate === "object") {
            return mate.name || (mate.id ? playerName(mate.id) : "");
          }
          return "";
        })
        .filter((name) => name && name !== "你");
    }
    const detail = details.join(" · ");
    const fallback = role === "murderer"
      ? "刀在你手里，别让目光落到自己身上。"
      : (role === "minion" ? "你不是恶魔，可你知道刀在谁手里。" : "你手上没有刀，但你也不能证明。");
    detailEl.textContent = detail || fallback;
    detailEl.title = detail;
    if (mateEl) {
      const mateLine = mateNames.length ? `你的同伴：${mateNames.join("、")}` : "";
      mateEl.textContent = mateLine;
      mateEl.title = mateLine;
      mateEl.classList.toggle("hidden", !mateLine);
    }
  }

  function tableStatusText(phase) {
    const alive = players().filter((player) => player.alive !== false).length;
    const threshold = Math.floor(alive / 2) + 1;
    const nameOf = (item) => {
      if (typeof item === "string") {
        return playerName(item);
      }
      return item ? (item.name || playerName(item.id) || "") : "";
    };
    if (phase === "runoff") {
      const candidates = ((state.game && state.game.runoff_candidates) || [])
        .map(nameOf)
        .filter(Boolean);
      return `加赛 · ${candidates.join(" / ") || "平票"} · 门槛 ${threshold}`;
    }
    if (phase === "defense") {
      const target = state.nominated
        || (state.ballotTargetId ? findPlayer(state.ballotTargetId) : null);
      return `焦点 · ${target ? displayName(target) : "被提名者"} · 存活 ${alive} · 门槛 ${threshold}`;
    }
    if (state.voteResult) {
      const tally = state.voteResult.tally;
      let total = 0;
      if (Array.isArray(tally)) {
        total = tally.reduce((sum, entry) => sum + (Number(entry.count) || 0), 0);
      } else if (tally && typeof tally === "object") {
        total = Object.values(tally).reduce((sum, value) => sum + (Number(value) || 0), 0);
      }
      return `落票 · 共 ${total} 票 · 门槛 ${state.voteResult.threshold || threshold}`;
    }
    if (state.ballotTargetId) {
      return `投票 · ${nameOf(findPlayer(state.ballotTargetId))} · 门槛 ${threshold}`;
    }
    return `存活 ${alive} 人 · 过半需 ${threshold} 票`;
  }

  function renderHeader() {
    const day = state.game ? state.game.day : 1;
    const phase = currentPhase();
    $("day-value").textContent = String(day);
    const phaseEl = $("phase-value");
    phaseEl.textContent = PHASE_LABEL[phase] || "白天讨论";
    phaseEl.dataset.phase = phase;
    document.body.dataset.phase = phase;
    document.body.dataset.spectating = (!isFinished() && !youAlive() && Boolean(state.game)) ? "1" : "0";
    $("table-day").textContent = `第 ${day} 夜`;
    const status = $("table-status");
    if (status) {
      status.textContent = tableStatusText(phase);
    }
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
    if (phase === "discussion") {
      return youAlive();
    }
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
      const nominated = phase === "defense" && (
        (state.nominated && state.nominated.id === player.id)
        || state.ballotTargetId === player.id
      );
      seat.classList.toggle("nominated", Boolean(nominated));
      seat.classList.toggle("selectable", selectable);
      seat.classList.toggle("selected", selected);
      seat.disabled = !selectable;
      seat.setAttribute("aria-pressed", selected ? "true" : "false");
      seat.setAttribute(
        "aria-label",
        `${displayName(player)}，${player.alive === false ? "已出局" : "在场"}${player.is_you ? "，你" : ""}${selected ? "，已选中" : ""}`,
      );
      if (selectable && phase === "discussion") {
        if (window.innerWidth > 430) {
          seat.dataset.hint = "点名";
        } else {
          delete seat.dataset.hint;
        }
      } else if (selectable && phase === "nomination") {
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

  function mentionPlayer(playerId) {
    const player = findPlayer(playerId);
    const input = $("speak-input");
    if (!player || !input || input.disabled) {
      return;
    }
    const name = displayName(player);
    const prefix = `${name}，`;
    const current = input.value.trim();
    if (!current.startsWith(prefix)) {
      input.value = `${prefix}${current}`;
    }
    input.focus();
    const day = Number(state.game && state.game.day) || 1;
    document.querySelectorAll("#discussion-list .log-entry").forEach((node) => {
      const same = node.dataset.speaker === String(player.id)
        && Number(node.dataset.day) === day;
      node.classList.toggle("mention-highlight", same);
    });
    window.clearTimeout(state.mentionTimer);
    state.mentionTimer = window.setTimeout(() => {
      document.querySelectorAll(".log-entry.mention-highlight")
        .forEach((node) => node.classList.remove("mention-highlight"));
    }, 4200);
  }

  function onSeatClick(playerId) {
    const player = findPlayer(playerId);
    if (!player || !canSelectPlayer(player)) {
      return;
    }
    const phase = currentPhase();
    if (phase === "discussion") {
      mentionPlayer(playerId);
      return;
    }
    if (phase === "defense") {
      mentionPlayer(playerId);
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

  function renderEntry(entry, freshIndex = -1) {
    const isYou = entry.speaker_id === youId();
    const narration = entry.speaker_id === "__narration"
      || entry.speaker_id === "narrator"
      || entry.speaker_name === "旁白";
    const text = publicSafeText(entry.text || "", narration);
    const whisper = narration && isWhisperText(text);
    const selfWhisper = whisper && isSelfWhisperText(text);
    const item = node("li", "log-entry");
    item.dataset.day = String(Number(entry.day) || (state.game && state.game.day) || 1);
    if (isYou) {
      item.classList.add("you");
    }
    if (narration) {
      item.classList.add("narration");
    }
    if (narration && /没有下楼|死在|夜杀|天亮时/.test(text)) {
      item.classList.add("death");
    }
    if (whisper) {
      item.classList.add("whisper");
      item.classList.add(selfWhisper ? "whisper-self" : "whisper-pair");
    }
    if (/被提名|先听.{0,4}自辩/u.test(text)) {
      item.classList.add("defense-line");
    }
    if (/被投票处决|平票|门槛|加赛|处决/u.test(text)) {
      item.classList.add("vote-line");
    }
    if (freshIndex >= 0) {
      item.classList.add("log-appear");
      item.style.animationDelay = `${Math.min(freshIndex, 6) * 70}ms`;
    }
    const who = node("p", "log-who", isYou ? "你" : entry.speaker_name);
    if (!narration) {
      item.dataset.speaker = String(entry.speaker_id || "");
      const dot = node("span", "log-dot");
      dot.dataset.speaker = String(entry.speaker_id || "");
      who.prepend(dot);
    }
    if (whisper) {
      who.append(node("span", "log-whisper-tag", selfWhisper ? "你的私谈" : "廊下"));
    }
    item.append(who, node("p", "log-text", text));
    return item;
  }

  function mergeNewEntries(data) {
    if (!data || typeof data !== "object") {
      return;
    }
    const raw = data.new_entries || data.newEntries || data.entries;
    if (!Array.isArray(raw) || !raw.length) {
      return;
    }
    const entries = normalizeLog(raw);
    if (!entries.length) {
      return;
    }
    const log = Array.isArray(data.public_log)
      ? data.public_log
      : ((state.game && Array.isArray(state.game.public_log)) ? state.game.public_log.slice() : []);
    const seen = new Set(log.map((item) => `${String(item.speaker_id || "")}\u0000${String(item.text || item.content || "")}`));
    let cursor = maxSeq(log);
    for (const entry of entries) {
      const key = `${entry.speaker_id}\u0000${entry.text}`;
      if (seen.has(key)) {
        continue;
      }
      cursor += 1;
      seen.add(key);
      log.push({ ...entry, seq: cursor });
    }
    data.public_log = log;
  }

  function enqueueLogEntries(entries, fast = false) {
    if (!entries || !entries.length) {
      return;
    }
    state.logQueue.push(...entries.map((entry) => ({ entry, fast })));
    flushLogQueue();
  }

  function flushLogQueue() {
    if (state.logQueueTimer) {
      return;
    }
    const item = state.logQueue.shift();
    if (!item) {
      return;
    }
    const list = $("discussion-list");
    const entry = item.entry;
    $("discussion-empty").classList.add("hidden");
    const day = Number(entry.day) || state.game && state.game.day || 1;
    if (day !== state.lastDayShown) {
      list.append(renderDayDivider(day));
      state.lastDayShown = day;
    }
    list.append(renderEntry(entry, 0));
    if (!state.userScrolled || state.stickForce) {
      state.stickForce = false;
      scrollDiscussionToBottom();
    }
    const narration = entry.speaker_id === "__narration"
      || entry.speaker_id === "narrator"
      || entry.speaker_name === "旁白";
    if (!narration) {
      showBubble(entry);
    }
    if (state.logQueue.length) {
      state.logQueueTimer = window.setTimeout(() => {
        state.logQueueTimer = 0;
        flushLogQueue();
      }, item.fast ? 30 : LOG_PLAY_INTERVAL);
    }
  }

  function appendLogEntries() {
    const log = (state.game && state.game.public_log) || [];
    $("discussion-empty").classList.toggle("hidden", log.length > 0);

    const fresh = log.filter((entry) => entry.seq > state.lastSeq);
    if (!fresh.length) {
      updateDiscussionCount();
      return;
    }
    const fast = state.lastSeq === 0;
    state.lastSeq = Math.max(state.lastSeq, maxSeq(fresh));
    updateDiscussionCount();
    enqueueLogEntries(fresh, fast);
  }

  function scrollDiscussionToBottom() {
    const scroll = $("discussion-scroll");
    if (!scroll) {
      return;
    }
    state.ignoreScroll = true;
    scroll.scrollTop = scroll.scrollHeight;
    window.requestAnimationFrame(() => {
      scroll.scrollTop = scroll.scrollHeight;
      window.setTimeout(() => {
        state.ignoreScroll = false;
      }, 90);
    });
  }

  function stickDiscussionToBottom() {
    const scroll = $("discussion-scroll");
    if (!scroll) {
      return;
    }
    if (state.stickForce) {
      state.stickForce = false;
      state.userScrolled = false;
      scrollDiscussionToBottom();
      return;
    }
    if (state.userScrolled) {
      return;
    }
    window.requestAnimationFrame(() => {
      if (!state.userScrolled) {
        scrollDiscussionToBottom();
      }
    });
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

  function voteBoardVisible() {
    if (!state.game || !state.voteResult) {
      return false;
    }
    if (isFinished()) {
      return false;
    }
    if (!youAlive()) {
      return true;
    }
    if (currentPhase() === "night" && !state.voteHeld) {
      return false;
    }
    return true;
  }

  function renderVoteBoard() {
    const board = $("vote-board");
    const result = state.voteResult;
    const discussion = board.closest(".discussion");
    const visible = voteBoardVisible();
    const hideLog = visible && youAlive() && currentPhase() === "night" && !state.voteHeld;
    if (discussion) {
      discussion.classList.toggle("voting", hideLog);
    }
    document.body.dataset.voting = hideLog ? "1" : "0";
    if (!state.game || !result || !visible) {
      board.classList.add("hidden");
      board.textContent = "";
      return;
    }
    const rows = voteTallyRows();
    const votes = result.votes || [];
    const threshold = result.threshold;
    const topCount = rows.length ? rows[0].count : 0;
    const executedName = result.executedName || "";
    const short = Boolean(threshold) && topCount < threshold;
    const tieFlag = Boolean(result.tie) || /平票/.test(String(result.message || ""));
    const tied = !executedName && (tieFlag
      || (Boolean(threshold) && rows.length > 1 && rows[1].count === topCount && topCount > 0));
    board.textContent = "";
    board.dataset.short = (short || tied) ? "1" : "0";

    const title = node("p", "vote-title");
    title.append(node("span", "", `第 ${result.day || state.game.day} 天 · 投票`));
    if (threshold) {
      title.append(node(
        "span",
        `vote-threshold${tied ? " tie" : (short ? " short" : "")}`,
        `共 ${votes.length} 票 · 门槛 ${threshold}`,
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

    const outcome = executedName ? "executed" : (tied ? "tie" : "short");
    const inRunoff = currentPhase() === "runoff";
    const exec = node("div", `vote-exec is-${outcome}`);
    exec.append(node("span", "exec-stamp", executedName ? "处决" : (tied ? "平票" : "未决")));
    let execText = "今晚无人被处决";
    if (executedName) {
      execText = `处决 · ${executedName} 被投票处决`;
    } else if (tied && inRunoff) {
      execText = `平票 · 进入第 ${Math.max(1, state.runoffStalemate)} 次加赛`;
    } else if (tied && state.runoffStalemate >= 2) {
      execText = "仍平票 · 僵局夜，今晚无人被处决";
    } else if (tied) {
      execText = "平票，今晚无人被处决";
    } else if (threshold) {
      execText = `最高 ${topCount} 票，未达 ${threshold} 票门槛`;
    }
    exec.append(node("span", "exec-text", execText));
    board.append(exec);

    const reduced = Boolean(state.thresholdReduced)
      || Boolean(result.thresholdReduced)
      || state.runoffStalemate >= 2;
    if (threshold && reduced && !executedName) {
      board.append(node("p", "vote-stalemate-note",
        `僵局持续，门槛降为 ${threshold} 票。`));
    }

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

  function setVoteView(result) {
    if (!result || typeof result !== "object") {
      return null;
    }
    const votes = normalizeVotes(result.votes);
    let tally = normalizeTally(result.tally);
    if (!tally.length) {
      tally = tallyFromVotes(votes);
    }
    const executedId = idOf(result.executed);
    const executedName = nameOf(result.executed)
      || (executedId ? playerName(executedId) : "");
    const executedPlayer = executedId
      ? (findPlayer(executedId) || players().find((player) => player.name === executedName || player.name === executedId))
      : null;
    const executedActualId = executedPlayer ? executedPlayer.id : executedId;
    if (!votes.length && !tally.length && !executedActualId) {
      return null;
    }
    const aliveCount = players().filter((player) => player.alive !== false).length;
    const threshold = Number(result.threshold) || (Math.floor(aliveCount / 2) + 1);
    const message = String(result.message || "");
    state.voteResult = {
      votes,
      tally,
      threshold,
      executedId: executedActualId,
      executedName,
      day: Number(result.day) || (state.game ? state.game.day : 1),
      message,
      tie: Boolean(result.tie || result.tied) || /平票|僵局/u.test(message),
      thresholdReduced: Boolean(result.threshold_reduced || result.thresholdReduced),
    };
    state.lastVotes = state.voteResult;
    state.lastVoteResult = state.voteResult;
    if (Number(result.stalemate_count || result.stalemateCount || 0) >= 2 || state.voteResult.thresholdReduced) {
      state.thresholdReduced = true;
    }
    if (executedActualId) {
      markDead(executedActualId);
    }
    return state.voteResult;
  }

  function spectateVisible() {
    return Boolean(state.game) && !isFinished() && !youAlive();
  }

  function ghostTargets() {
    return players().filter((player) => player.alive !== false && !player.is_you);
  }

  function ghostVoteOpen() {
    if (!spectateVisible() || state.ghostVoteUsed || state.ghostDismissed) {
      return false;
    }
    if (state.ghostVoteAvailable === false) {
      return false;
    }
    const phase = normalizePhase(state.game && state.game.phase);
    const inVotePhase = state.ghostVoteAvailable === true
      || phase === "nomination"
      || phase === "defense"
      || phase === "runoff"
      || Boolean(state.voteResult);
    return inVotePhase && ghostTargets().length > 0;
  }

  function collectFreshEntries(data, sinceSeq) {
    const log = normalizeLog((data && data.public_log) || []);
    const fresh = log.filter((entry) => entry.seq > sinceSeq);
    if (fresh.length) {
      return fresh;
    }
    return normalizeLog((data && (data.new_entries || data.newEntries)) || []);
  }

  function recordSpectateEntries(entries) {
    if (!Array.isArray(entries) || !entries.length) {
      return;
    }
    for (const entry of entries) {
      const exists = state.spectateFeed.some((item) => item.seq === entry.seq
        && item.text === entry.text
        && item.speaker_id === entry.speaker_id);
      if (!exists) {
        state.spectateFeed.push({ ...entry });
      }
    }
    state.spectateFeed.sort((left, right) => (left.seq || 0) - (right.seq || 0));
  }

  function spectateNextHint() {
    if (!state.game || isFinished()) {
      return "";
    }
    const phase = normalizePhase(state.game.phase);
    if (phase === "discussion") {
      return "下一步：点「继续观战」，看这一天的讨论、提名与投票。";
    }
    if (phase === "nomination" || phase === "defense") {
      return "下一步：桌上要落票了，点「继续观战」往下看。";
    }
    if (phase === "runoff") {
      return "下一步：平票加赛，点「继续观战」看谁被推出去。";
    }
    if (phase === "night") {
      return "下一步：天黑了，点「继续观战」等天亮。";
    }
    return "下一步：点「继续观战」推进这一段。";
  }

  function renderSpectateFeed() {
    const host = $("spectate-feed");
    if (!host) {
      return;
    }
    if (!spectateVisible() || !state.spectateFeed.length) {
      host.textContent = "";
      host.dataset.sig = "";
      host.classList.add("hidden");
      return;
    }
    host.classList.remove("hidden");
    const entries = state.spectateFeed;
    const signature = entries.map((entry) => `${entry.seq}:${entry.day}:${entry.text.length}`).join("|");
    if (host.dataset.sig === signature) {
      return;
    }
    host.textContent = "";
    const days = [...new Set(entries.map((entry) => Number(entry.day) || 1))].sort((a, b) => a - b);
    const latest = days[days.length - 1];
    for (const day of days) {
      const rows = entries.filter((entry) => (Number(entry.day) || 1) === day);
      const group = document.createElement("details");
      group.className = "spectate-day-group";
      group.open = day === latest;
      const summary = document.createElement("summary");
      summary.className = "spectate-day-summary";
      summary.append(node("span", "sday", `第 ${day} 天`));
      summary.append(node("span", "scount", `${rows.length} 条`));
      group.append(summary);
      const list = node("ol", "spectate-day-list");
      for (const entry of rows) {
        list.append(renderEntry(entry));
      }
      group.append(list);
      host.append(group);
    }
    host.dataset.sig = signature;
    const pinToBottom = () => {
      host.scrollTop = host.scrollHeight;
    };
    window.requestAnimationFrame(() => {
      pinToBottom();
      window.requestAnimationFrame(pinToBottom);
    });
    window.setTimeout(pinToBottom, 90);
    window.setTimeout(pinToBottom, 240);
  }

  function showNightTransition(title, note, holdMs = 0) {
    const box = $("night-transition");
    if (!box) {
      return;
    }
    const stage = $("table-stage");
    if (stage) {
      const rect = stage.getBoundingClientRect();
      const shift = rect.left + rect.width / 2 - window.innerWidth / 2;
      box.style.setProperty("--dawn-shift", `${Math.round(shift)}px`);
    }
    window.clearTimeout(state.nightTransitionTimer);
    $("night-transition-title").textContent = title;
    $("night-transition-note").textContent = note || "";
    box.classList.remove("hidden");
    box.setAttribute("aria-hidden", "false");
    state.nightTransitionOpen = true;
    if (holdMs > 0) {
      state.nightTransitionTimer = window.setTimeout(() => {
        hideNightTransition();
      }, holdMs);
    }
  }

  function hideNightTransition() {
    const box = $("night-transition");
    if (!box) {
      return;
    }
    window.clearTimeout(state.nightTransitionTimer);
    state.nightTransitionTimer = 0;
    box.classList.add("hidden");
    box.setAttribute("aria-hidden", "true");
    state.nightTransitionOpen = false;
  }

  function renderSpectate() {
    const panel = $("spectate-panel");
    if (!panel) {
      return;
    }
    const visible = spectateVisible();
    const discussion = panel.closest(".discussion");
    if (discussion) {
      discussion.classList.toggle("spectating", visible);
    }
    panel.classList.toggle("hidden", !visible);
    if (!visible) {
      renderSpectateFeed();
      return;
    }
    $("spectate-day").textContent = `第 ${state.game.day} 天`;
    const line = $("spectate-line");
    if (state.ghostVoteUsed) {
      line.textContent = "你已出局。亡者票已经用过，现在只剩看。";
    } else if (ghostVoteOpen()) {
      line.textContent = "你已出局。桌上要落票了——你还能投最后一票。";
    } else {
      line.textContent = "你已出局，观战中。退到廊下，看他们怎么收场。";
    }
    const note = $("spectate-note");
    const pieces = [];
    if (state.lastKilledName) {
      pieces.push(`最近死讯：${state.lastKilledName}`);
    }
    if (state.voteResult && !state.voteResult.executedName && state.voteResult.tie) {
      pieces.push("票数咬死，今晚无人被处决");
    }
    if (state.voteResult && state.voteResult.executedName) {
      pieces.push(`处决：${state.voteResult.executedName}`);
    }
    note.textContent = pieces.join(" · ");
    note.classList.toggle("hidden", !pieces.length);
    renderSpectateFeed();
    const next = $("spectate-next");
    if (next) {
      const hint = spectateNextHint();
      next.textContent = hint;
      next.classList.toggle("hidden", !hint);
    }
    const advance = $("spectate-advance");
    if (advance) {
      advance.disabled = state.busy || state.advancing;
      advance.textContent = state.advancing ? "推着这一夜…" : "继续观战";
    }
    const log = $("spectate-log");
    if (log) {
      log.disabled = state.busy;
    }
  }

  function renderGhostVote() {
    const panel = $("ghost-vote-panel");
    if (!panel) {
      return;
    }
    const open = ghostVoteOpen();
    const visible = spectateVisible() && (open || state.ghostVoteUsed) && !state.ghostDismissed;
    panel.classList.toggle("hidden", !visible);
    if (!visible) {
      return;
    }
    panel.classList.toggle("is-used", state.ghostVoteUsed);
    $("ghost-note").textContent = state.ghostVoteUsed ? "已落，不可再投" : "仅此一次";
    $("ghost-lede").textContent = state.ghostVoteUsed
      ? "这张纸条已经压在票板底下了。"
      : "你已不在桌上，可这一票还压在袖子里。";
    const targets = $("ghost-targets");
    const candidates = ghostTargets();
    if (!candidates.some((player) => player.id === state.ghostTargetId)) {
      state.ghostTargetId = candidates[0] ? candidates[0].id : null;
    }
    const signature = candidates
      .map((player) => `${player.id}:${player.id === state.ghostTargetId ? 1 : 0}`)
      .join("|");
    if (targets.dataset.sig !== signature) {
      targets.textContent = "";
      for (const player of candidates) {
        const chip = node("button", "ghost-target");
        chip.type = "button";
        chip.dataset.targetId = player.id;
        chip.disabled = state.ghostVoteUsed;
        chip.setAttribute("aria-pressed", player.id === state.ghostTargetId ? "true" : "false");
        chip.append(node("span", "ghost-target-name", displayName(player)));
        chip.addEventListener("click", () => {
          if (state.busy || state.ghostVoteUsed) {
            return;
          }
          state.ghostTargetId = player.id;
          targets.dataset.sig = "";
          renderGhostVote();
        });
        targets.append(chip);
      }
      targets.dataset.sig = signature;
    }
    const confirm = $("ghost-confirm");
    const hold = $("ghost-hold");
    if (confirm) {
      confirm.disabled = state.busy || state.ghostVoteUsed || !state.ghostTargetId;
      confirm.textContent = state.ghostVoteUsed ? "亡者票已用" : "投出你的一票";
    }
    if (hold) {
      hold.disabled = state.busy || state.ghostVoteUsed;
    }
    const stamp = $("ghost-stamp");
    if (stamp) {
      stamp.classList.toggle("hidden", !state.ghostVoteUsed);
    }
  }

  function applyAdvance(data, options = {}) {
    if (!data || typeof data !== "object") {
      return;
    }
    const beforeSeq = state.lastSeq;
    const fresh = collectFreshEntries(data, beforeSeq);
    applyGame(data);
    recordSpectateEntries(fresh);
    const view = setVoteView(data);
    const killedId = idOf(data.killed);
    const killedName = nameOf(data.killed) || (killedId ? playerName(killedId) : "");
    if (killedId) {
      markDead(killedId);
      state.lastKilledName = killedName || "一个人";
    }
    if (data.executed) {
      const executedId = idOf(data.executed) || (state.voteResult && state.voteResult.executedId);
      markDead(executedId);
    }
    if (data.ghost_vote_available !== undefined) {
      state.ghostVoteAvailable = Boolean(data.ghost_vote_available);
    }
    if (data.ghost_vote_used !== undefined) {
      state.ghostVoteUsed = Boolean(data.ghost_vote_used);
    }
    if (data.winner) {
      state.endPending = true;
      state.endRevealed = false;
      state.ghostVoteAvailable = false;
    }
    state.ghostDismissed = false;
    state.selectedId = null;
    state.nominationMode = false;
    state.voteHeld = false;
    state.stickForce = true;
    const message = String(data.message || "");
    if (message) {
      showReport(message, data.winner ? "good" : (killedName ? "warn" : "info"));
    } else if (killedName) {
      showReport(killedName === "你" ? "天亮时，你没能再站起来。" : `天亮时，${killedName} 没有下楼。`, "warn");
    } else if (view && view.executedName) {
      showReport(`处决 · ${view.executedName} 被投票处决。`, "warn");
    } else if (view && view.tie) {
      showReport("票数咬死，今晚无人被处决。", "info");
    }
    if (options.ghost) {
      showToast("亡者票落下了。", "warn", 3800);
    }
  }

  async function doAdvance() {
    if (!state.game || state.busy) {
      return;
    }
    if (!spectateVisible()) {
      return;
    }
    state.advancing = true;
    renderSpectate();
    try {
      await runAction(async () => {
        let result;
        if (state.mock) {
          result = mockAdvance();
        } else {
          try {
            result = await apiRequest(`${API}/games/${state.gameId}/advance`, {
              method: "POST",
              body: {},
            });
          } catch (error) {
            if (error && (error.status === 404 || error.status === 405 || error.status === 501)) {
              result = mockAdvance();
              showToast("推进接口还没就绪，先用本地推演接住这一夜。", "warn", 4200);
            } else {
              throw error;
            }
          }
        }
        applyAdvance(result || {});
        if (!state.mock) {
          await refreshReal();
        }
        render();
      });
    } finally {
      state.advancing = false;
      renderSpectate();
    }
  }

  async function doGhostVote() {
    const target = findPlayer(state.ghostTargetId);
    if (!target || target.alive === false || target.is_you) {
      showToast("先选一个还坐在桌边的人。", "warn");
      return;
    }
    if (!ghostVoteOpen()) {
      showToast("现在不是投亡者票的时候。", "warn");
      return;
    }
    runAction(async () => {
      let result;
      if (state.mock) {
        result = mockGhostVote(target.id);
      } else {
        result = await apiRequest(`${API}/games/${state.gameId}/vote`, {
          method: "POST",
          body: { target_id: target.id, ghost: true },
        });
      }
      state.ghostVoteUsed = true;
      state.ghostVoteAvailable = false;
      state.ghostVotes.push({ targetId: target.id, targetName: displayName(target) });
      applyAdvance(result || {}, { ghost: true });
      if (!state.mock) {
        await refreshReal();
      }
      render();
    });
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

  function runoffTarget() {
    const player = findPlayer(state.runoffPickId);
    return player && player.alive !== false ? player : null;
  }

  function renderRunoff() {
    const panel = $("runoff-panel");
    if (!panel) {
      return;
    }
    const phase = currentPhase();
    const visible = Boolean(state.game) && phase === "runoff" && !isFinished() && youAlive();
    panel.classList.toggle("hidden", !visible);
    if (!visible) {
      return;
    }
    const candidates = state.runoffCandidates
      .map((id) => findPlayer(id))
      .filter((player) => player && player.alive !== false);
    if (!candidates.length) {
      panel.classList.add("hidden");
      return;
    }
    if (!candidates.some((player) => player.id === state.runoffPickId)) {
      state.runoffPickId = candidates[0].id;
    }
    const options = $("runoff-options");
    const signature = candidates
      .map((player) => `${player.id}:${player.id === state.runoffPickId ? 1 : 0}`)
      .join("|");
    if (options.dataset.sig !== signature) {
      options.textContent = "";
      for (const player of candidates) {
        const option = node("button", "ballot-option runoff-option");
        option.type = "button";
        option.dataset.targetId = player.id;
        option.setAttribute("aria-pressed", player.id === state.runoffPickId ? "true" : "false");
        option.append(node("span", "ballot-option-name", displayName(player)));
        option.addEventListener("click", () => {
          if (state.busy) {
            return;
          }
          state.runoffPickId = player.id;
          options.dataset.sig = "";
          renderRunoff();
          renderActionBar();
        });
        options.append(option);
      }
      options.dataset.sig = signature;
    }
    const note = $("runoff-note");
    if (note) {
      note.textContent = state.runoffStalemate > 0
        ? `第 ${state.runoffStalemate} 次平票 · 只在候选之间再投一次`
        : "只在平票的人之间再投一次";
    }
  }

  function confideCandidates() {
    return players().filter((player) => player.alive !== false && !player.is_you);
  }

  function confideRemainingToday() {
    return Math.max(0, CONFIDE_PER_DAY - state.confideUsedToday);
  }

  function confideRemainingTotal() {
    return Math.max(0, CONFIDE_PER_GAME - state.confideUsedTotal);
  }

  function canConfide() {
    if (!state.game || state.busy || isFinished() || !youAlive()) {
      return false;
    }
    const phase = currentPhase();
    if (phase !== "discussion" && phase !== "defense") {
      return false;
    }
    return confideRemainingToday() > 0
      && confideRemainingTotal() > 0
      && confideCandidates().length > 0;
  }

  function confideCountText() {
    if (!state.game) {
      return "今日还剩 1 次 · 本局还剩 3 次";
    }
    const today = confideRemainingToday();
    const total = confideRemainingTotal();
    return `今日还剩 ${today} 次 · 本局还剩 ${total} 次`;
  }

  function renderConfide() {
    const panel = $("confide-panel");
    const discussion = panel.closest(".discussion");
    const phase = currentPhase();
    const active = Boolean(state.game) && state.confideOpen
      && (phase === "discussion" || phase === "defense")
      && !isFinished() && youAlive() && confideCandidates().length > 0;
    if (discussion) {
      discussion.classList.toggle("confiding", active);
    }
    if (!active) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const hasReply = Boolean(state.confideReply);
    panel.classList.toggle("has-reply", hasReply);
    $("confide-count").textContent = confideCountText();

    const remaining = confideRemainingToday() > 0 && confideRemainingTotal() > 0;
    $("confide-lede").textContent = hasReply
      ? "廊下只剩你们两个。"
      : (remaining
        ? "把声音压低，只让一个人听见。公开的桌上只会留下一句「低声说了几句」。"
        : "今天的话已经说尽了，明晚再来廊下。");

    const targets = $("confide-targets");
    const candidates = confideCandidates();
    if (!candidates.some((player) => player.id === state.confideTargetId)) {
      state.confideTargetId = candidates[0] ? candidates[0].id : null;
    }
    const signature = candidates
      .map((player) => `${player.id}:${player.name}:${player.id === state.confideTargetId ? 1 : 0}`)
      .join("|");
    if (targets.dataset.sig !== signature) {
      targets.textContent = "";
      for (const player of candidates) {
        const chip = node("button", "confide-target");
        chip.type = "button";
        chip.dataset.targetId = player.id;
        chip.setAttribute("aria-pressed", player.id === state.confideTargetId ? "true" : "false");
        chip.append(node("span", "confide-target-name", player.name));
        chip.addEventListener("click", () => {
          if (state.busy) {
            return;
          }
          state.confideTargetId = player.id;
          targets.dataset.sig = "";
          renderConfide();
          updateConfideSend();
        });
        targets.append(chip);
      }
      targets.dataset.sig = signature;
    }

    const input = $("confide-input");
    if (input && !remaining) {
      input.disabled = true;
    } else if (input) {
      input.disabled = Boolean(state.busy);
    }
    updateConfideSend();
    renderConfideReply();
  }

  function updateConfideSend() {
    const button = $("confide-send");
    const input = $("confide-input");
    if (!button || !input) {
      return;
    }
    const usable = canConfide()
      && Boolean(state.confideTargetId)
      && Boolean(input.value.trim());
    button.disabled = !usable || state.busy;
    button.textContent = state.busy ? "递过去…" : "递过去";
  }

  function updateConfideLimit() {
    const el = $("confide-limit");
    const input = $("confide-input");
    if (!el || !input) {
      return;
    }
    const raw = input.value;
    if (raw.length <= 200) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const trimmed = trimToSentence(raw, 200);
    el.textContent = `密谈超过 200 字，发送时会保留到最后一个句号（${trimmed.text.length} 字）。`;
    el.classList.remove("hidden");
  }

  function renderConfideReply() {
    const box = $("confide-reply");
    const reply = state.confideReply;
    if (!reply) {
      box.classList.add("hidden");
      return;
    }
    $("confide-reply-name").textContent = `${reply.target_name} 压低声音`;
    $("confide-reply-stance").textContent = STANCE_LABEL[reply.stance] || "没有表态";
    $("confide-reply-text").textContent = reply.reply
      || "他没接你的话，只把杯子往桌上一放。";
    $("confide-reply-shift").textContent = formatConfideShift(reply);
    const betray = $("confide-reply-betray");
    if (betray) {
      if (reply.betrayed) {
        betray.textContent = "对方答应了，但可能反悔——也可能已经在公开场合反咬你。";
        betray.classList.remove("hidden");
      } else {
        betray.textContent = "";
        betray.classList.add("hidden");
      }
    }
    box.classList.remove("hidden");
  }

  function formatConfideShift(reply) {
    const read = (key) => {
      const value = Number(reply && reply[key]);
      return Number.isFinite(value) ? value : null;
    };
    const parts = [];
    for (const [key, label] of [["trust_delta", "信任"], ["suspicion_delta", "怀疑"], ["follow_delta", "追随"]]) {
      const value = read(key);
      if (value !== null && value !== 0) {
        parts.push(`${label} ${formatDelta(value)}`);
      }
    }
    if (parts.length) {
      return parts.join(" · ");
    }
    const trust = read("trust");
    const suspicion = read("suspicion");
    const follow = read("follow");
    const absolute = (trust !== null && Math.abs(trust) > 1)
      || (suspicion !== null && Math.abs(suspicion) > 1)
      || (follow !== null && Math.abs(follow) > 1);
    const hold = [];
    if (absolute) {
      if (trust !== null) {
        hold.push(`信任 ${Math.round(trust)}`);
      }
      if (suspicion !== null) {
        hold.push(`怀疑 ${Math.round(suspicion)}`);
      }
      if (follow !== null) {
        hold.push(`追随 ${Math.round(follow)}`);
      }
    } else {
      if (trust !== null && trust !== 0) {
        hold.push(`信任 ${formatDelta(trust)}`);
      }
      if (suspicion !== null && suspicion !== 0) {
        hold.push(`怀疑 ${formatDelta(suspicion)}`);
      }
      if (follow !== null && follow !== 0) {
        hold.push(`追随 ${formatDelta(follow)}`);
      }
    }
    return hold.length ? hold.join(" · ") : "他没让你看出态度变了多少。";
  }

  function formatDelta(value) {
    const sign = value > 0 ? "+" : "−";
    const abs = Math.abs(value);
    const text = abs < 1 ? abs.toFixed(2).replace(/0+$/u, "").replace(/\.$/u, "") : String(Math.round(abs));
    return `${sign}${text}`;
  }

  function inspectCandidates() {
    return players().filter((player) => player.alive !== false && !player.is_you);
  }

  function inspectRemaining() {
    return state.inspectUsed ? 0 : INSPECT_PER_GAME;
  }

  function canInspect() {
    if (!state.game || state.busy || isFinished() || !youAlive()) {
      return false;
    }
    if (isEvilRole(youRole()) || state.inspectUsed) {
      return false;
    }
    const phase = currentPhase();
    if (phase !== "discussion" && phase !== "defense") {
      return false;
    }
    return inspectCandidates().length > 0;
  }

  function inspectCountText() {
    const left = inspectRemaining();
    if (isEvilRole(youRole())) {
      return "你没有查验";
    }
    return left > 0 ? `本局还剩 ${left} 次` : "本局查验已用";
  }

  function renderInspect() {
    const panel = $("inspect-panel");
    if (!panel) {
      return;
    }
    const discussion = panel.closest(".discussion");
    const phase = currentPhase();
    const active = Boolean(state.game) && state.inspectOpen
      && (phase === "discussion" || phase === "defense")
      && !isFinished() && youAlive() && inspectCandidates().length > 0;
    if (discussion) {
      discussion.classList.toggle("inspecting", active);
    }
    if (!active) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const hasResult = Boolean(state.inspectResult);
    panel.classList.toggle("has-result", hasResult);
    $("inspect-count").textContent = inspectCountText();

    const isMurderer = isEvilRole(youRole());
    $("inspect-lede").textContent = isMurderer
      ? "你没有查验。只有镇民手里才有这一项。"
      : (hasResult
        ? (state.inspectResult.revealed
          ? "牌已经翻在桌上，所有人都看见了你查的是谁。"
          : "牌只翻给你一个人看。桌上没人知道你查出了什么。")
        : "只掀一个人的底牌。牌在你手里，公不公开由你决定。");

    const targets = $("inspect-targets");
    const candidates = inspectCandidates();
    if (!candidates.some((player) => player.id === state.inspectTargetId)) {
      state.inspectTargetId = candidates[0] ? candidates[0].id : null;
    }
    const signature = candidates
      .map((player) => `${player.id}:${player.name}:${player.id === state.inspectTargetId ? 1 : 0}`)
      .join("|");
    if (targets.dataset.sig !== signature) {
      targets.textContent = "";
      for (const player of candidates) {
        const chip = node("button", "confide-target");
        chip.type = "button";
        chip.dataset.targetId = player.id;
        chip.setAttribute("aria-pressed", player.id === state.inspectTargetId ? "true" : "false");
        chip.append(node("span", "confide-target-name", player.name));
        chip.addEventListener("click", () => {
          if (state.busy || state.inspectUsed) {
            return;
          }
          state.inspectTargetId = player.id;
          targets.dataset.sig = "";
          renderInspect();
          updateInspectConfirm();
        });
        targets.append(chip);
      }
      targets.dataset.sig = signature;
    }

    const confirm = $("inspect-confirm");
    if (confirm) {
      confirm.classList.toggle("hidden", hasResult || isMurderer || state.inspectUsed);
      confirm.disabled = state.busy || !state.inspectTargetId || state.inspectUsed;
      const picked = findPlayer(state.inspectTargetId);
      const pickedName = picked ? displayName(picked) : "那个人";
      confirm.textContent = state.busy
        ? "查验中…"
        : (state.inspectReveal ? `公开我查过 ${pickedName}` : "悄悄看牌");
    }
    const choice = $("inspect-choice");
    if (choice) {
      const showChoice = !hasResult && !isMurderer && !state.inspectUsed;
      choice.classList.toggle("hidden", !showChoice);
      if (showChoice) {
        const picked = findPlayer(state.inspectTargetId);
        const pickedName = picked ? displayName(picked) : "那个人";
        $("inspect-choice-lede").textContent = state.inspectReveal
          ? `公开就意味着：桌上都会知道你查过 ${pickedName}。`
          : "这张牌，给桌上的人看吗？默认只自己看。";
        const privateBtn = $("inspect-private");
        const publicBtn = $("inspect-public");
        privateBtn.classList.toggle("is-picked", !state.inspectReveal);
        publicBtn.classList.toggle("is-picked", state.inspectReveal);
        privateBtn.setAttribute("aria-pressed", state.inspectReveal ? "false" : "true");
        publicBtn.setAttribute("aria-pressed", state.inspectReveal ? "true" : "false");
        privateBtn.disabled = state.busy;
        publicBtn.disabled = state.busy;
        publicBtn.textContent = `公开我查过 ${pickedName}`;
      }
    }
    const box = $("inspect-result");
    if (hasResult) {
      $("inspect-verdict").textContent = state.inspectResult.verdict;
      $("inspect-verdict").dataset.result = state.inspectResult.murderer ? "murderer" : "clear";
      $("inspect-visibility").textContent = state.inspectResult.revealed
        ? `已公开 · 桌上都知道了${state.inspectResult.publicLine ? "" : ""}`
        : "仅你可见 · 这句话没有上桌";
      $("inspect-visibility").dataset.visible = state.inspectResult.revealed ? "public" : "private";
      $("inspect-public").textContent = state.inspectResult.revealed
        ? state.inspectResult.publicLine
        : "";
      $("inspect-public").classList.toggle("hidden", !state.inspectResult.revealed);
      box.classList.remove("hidden");
    } else {
      box.classList.add("hidden");
    }
  }

  function updateInspectConfirm() {
    const confirm = $("inspect-confirm");
    if (!confirm) {
      return;
    }
    confirm.disabled = state.busy || !state.inspectTargetId || state.inspectUsed;
  }

  function openInspect() {
    if (!state.game || isFinished() || !youAlive()) {
      return;
    }
    if (isEvilRole(youRole())) {
      showToast("你没有查验——只有镇民手里才有这一项。", "warn");
      return;
    }
    if (state.inspectAvailable === false) {
      showToast("查验接口还没就绪，本轮先不开放查验。", "warn");
      return;
    }
    if (state.inspectUsed) {
      showToast("这一局的查验已经用过了。", "warn");
      return;
    }
    const phase = currentPhase();
    if (phase !== "discussion" && phase !== "defense") {
      showToast("现在不是掀牌的时候。", "warn");
      return;
    }
    state.inspectOpen = true;
    state.inspectResult = null;
    state.inspectReveal = false;
    state.inspectRevealed = false;
    state.confideOpen = false;
    state.confideReply = null;
    render();
  }

  function closeInspect() {
    state.inspectOpen = false;
    state.inspectResult = null;
    state.inspectReveal = false;
    render();
  }

  function handleInspect() {
    if (state.busy || !state.game) {
      return;
    }
    const target = findPlayer(state.inspectTargetId);
    if (!target || target.alive === false || target.is_you) {
      showToast("先选一个还坐在桌边的人。", "warn");
      return;
    }
    if (!canInspect()) {
      showToast("这一局的查验已经用过了。", "warn");
      return;
    }
    const reveal = Boolean(state.inspectReveal);
    runAction(async () => {
      let result;
      if (state.mock) {
        result = mockInspect(target.id, reveal);
      } else {
        try {
          result = await apiRequest(`${API}/games/${state.gameId}/inspect`, {
            method: "POST",
            body: { target_id: target.id, reveal },
          });
        } catch (error) {
          if (error && (error.status === 404 || error.status === 405 || error.status === 501)) {
            state.inspectAvailable = false;
            state.inspectOpen = false;
            showToast("查验接口还没就绪，本轮先不开放查验。", "warn", 4400);
            render();
            return;
          }
          throw error;
        }
      }
      applyInspectResult(target, result || {}, reveal);
      state.inspectUsed = true;
      const revealed = Boolean(state.inspectResult && state.inspectResult.revealed);
      if (state.mock && revealed) {
        addInspectLine(target.name, state.inspectResult.publicLine);
      }
      pushLocalEvent({
        type: "inspect",
        day: state.game ? state.game.day : 1,
        text: `查验 · ${target.name} · ${state.inspectResult.murderer ? "凶手" : "不是凶手"}`
          + (revealed ? " · 已公开" : " · 未公开"),
        target: { id: target.id, name: target.name },
        result: state.inspectResult.murderer ? "murderer" : "not_murderer",
        public_line: revealed ? state.inspectResult.publicLine : "",
      });
      if (!state.mock) {
        await refreshReal();
        if (revealed) {
          ensureInspectLine(target.name, state.inspectResult.publicLine);
        }
      }
      render();
    });
  }

  function applyInspectResult(target, result, reveal = false) {
    const raw = String(result.result || result.verdict || "").toLowerCase();
    const murderer = raw === "murderer" || raw === "凶手";
    const verdict = murderer ? "查验结果：凶手" : "查验结果：不是凶手";
    const revealed = Boolean(result.revealed !== undefined ? result.revealed : reveal);
    const publicLine = revealed
      ? String(result.public_line || result.publicLine || `我查过${target.name}。`)
      : "";
    const remaining = Number(result.remaining);
    state.inspectResult = {
      targetId: target.id,
      targetName: target.name,
      murderer,
      verdict,
      publicLine,
      revealed,
      remaining: Number.isFinite(remaining) ? remaining : 0,
    };
    state.inspectRevealed = revealed;
    if (Number.isFinite(remaining)) {
      state.inspectUsed = remaining <= 0;
    }
    return state.inspectResult;
  }

  function addInspectLine(name, publicLine) {
    const log = state.game && state.game.public_log;
    if (!log) {
      return;
    }
    const line = String(publicLine || `我查过${name}。`);
    if (log.some((entry) => entry.text === line)) {
      return;
    }
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: line,
      day: state.game.day,
    });
  }

  function ensureInspectLine(name, publicLine) {
    const log = (state.game && state.game.public_log) || [];
    const line = String(publicLine || `我查过${name}。`);
    if (!log.some((entry) => String(entry.text || "").includes("我查过"))) {
      addInspectLine(name, line);
    }
  }

  function openConfide() {
    if (!state.game || isFinished() || !youAlive()) {
      return;
    }
    const phase = currentPhase();
    if (phase !== "discussion" && phase !== "defense") {
      showToast("现在不是低声说话的时候。", "warn");
      return;
    }
    if (confideRemainingTotal() <= 0) {
      showToast("本局的密谈已经用完了。", "warn");
      return;
    }
    if (confideRemainingToday() <= 0) {
      showToast("今天已经密谈过一次了，明晚再来。", "warn");
      return;
    }
    state.confideOpen = true;
    state.confideReply = null;
    state.inspectOpen = false;
    state.inspectResult = null;
    render();
    const input = $("confide-input");
    if (input) {
      input.value = "";
      window.setTimeout(() => input.focus(), 60);
    }
  }

  function closeConfide() {
    state.confideOpen = false;
    state.confideReply = null;
    render();
  }

  function handleConfideSend() {
    if (state.busy || !state.game) {
      return;
    }
    const input = $("confide-input");
    const raw = input ? input.value.trim() : "";
    const trimmed = trimToSentence(raw, 200);
    const text = trimmed.text;
    const target = findPlayer(state.confideTargetId);
    if (!target || target.alive === false || target.is_you) {
      showToast("先选一个还坐在桌边的人。", "warn");
      return;
    }
    if (!text) {
      showToast("总得说点什么，才算密谈。", "warn");
      return;
    }
    if (!canConfide()) {
      showToast("今天的密谈次数已经用完了。", "warn");
      return;
    }
    if (trimmed.clipped) {
      showToast(`密谈过长，已保留到最后一个句号（${text.length} 字）。`, "warn", 4200);
    }
    if (input) {
      input.value = "";
    }
    $("confide-limit").classList.add("hidden");
    runAction(async () => {
      let result;
      let fallback = false;
      if (state.mock) {
        result = mockConfide(target.id, text);
      } else {
        try {
          result = await apiRequest(`${API}/games/${state.gameId}/confide`, {
            method: "POST",
            body: { target_id: target.id, text },
          });
        } catch (error) {
          if (error && (error.status === 404 || error.status === 405 || error.status === 501)) {
            fallback = true;
            result = mockConfide(target.id, text);
          } else {
            throw error;
          }
        }
      }
      const entry = applyConfideResult(target, text, result || {});
      state.confideReply = entry;
      state.privateLog.push(entry);
      state.confideUsedToday += 1;
      state.confideUsedTotal += 1;
      if (state.mock || fallback) {
        addWhisperLine(target.name);
      }
      if (!state.mock && !fallback) {
        await refreshReal();
        ensureWhisperLine(target.name);
      }
      render();
      if (fallback) {
        showToast("密谈接口还没就绪，先用本地逻辑接住了这句话。", "warn", 4200);
      }
    });
  }

  function applyConfideResult(target, text, result) {
    const stance = String(result.stance || "").toLowerCase();
    const relative = Boolean(result.relative);
    const trust = Number(result.trust !== undefined ? result.trust : result.trust_delta);
    const suspicion = Number(result.suspicion !== undefined ? result.suspicion : result.suspicion_delta);
    const follow = Number(result.follow !== undefined ? result.follow : result.follow_delta);
    const prev = state.confideSnapshots[target.id] || null;
    const baseTrust = prev && Number.isFinite(prev.trust) ? prev.trust : 50;
    const baseSuspicion = prev && Number.isFinite(prev.suspicion) ? prev.suspicion : 0;
    const baseFollow = prev && Number.isFinite(prev.follow) ? prev.follow : 0;
    let trustDelta = null;
    let suspicionDelta = null;
    let followDelta = null;
    if (Number.isFinite(trust)) {
      trustDelta = relative ? trust : trust - baseTrust;
    }
    if (Number.isFinite(suspicion)) {
      suspicionDelta = relative ? suspicion : suspicion - baseSuspicion;
    }
    if (Number.isFinite(follow)) {
      followDelta = relative ? follow : follow - baseFollow;
    }
    if (!relative) {
      state.confideSnapshots[target.id] = {
        trust: Number.isFinite(trust) ? trust : (prev ? prev.trust : undefined),
        suspicion: Number.isFinite(suspicion) ? suspicion : (prev ? prev.suspicion : undefined),
        follow: Number.isFinite(follow) ? follow : (prev ? prev.follow : undefined),
      };
    }
    return {
      day: state.game ? state.game.day : 1,
      target_id: target.id,
      target_name: target.name,
      text,
      stance: STANCE_LABEL[stance] ? stance : "neutral",
      reply: sanitizeLine(String(result.reply || result.text || ""), false),
      betrayed: Boolean(result.betrayed),
      trust: Number.isFinite(trust) ? trust : undefined,
      suspicion: Number.isFinite(suspicion) ? suspicion : undefined,
      follow: Number.isFinite(follow) ? follow : undefined,
      trust_delta: trustDelta,
      suspicion_delta: suspicionDelta,
      follow_delta: followDelta,
    };
  }

  function addWhisperLine(name) {
    const log = state.game && state.game.public_log;
    if (!log) {
      return;
    }
    const line = `你与${name}低声说了几句。`;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: line,
      day: state.game.day,
    });

  }

  function pushLocalEvent(event) {
    if (!event || !state.game) {
      return;
    }
    state.localEvents.push({ ...event, day: Number(event.day) || state.game.day });
  }

  function localEventEntries() {
    return state.localEvents.map(adaptDrawerEntry).filter(Boolean);
  }

  function ensureWhisperLine(name) {
    const log = (state.game && state.game.public_log) || [];
    const recent = log.slice(-6);
    const has = recent.some((entry) => String(entry.text || "").includes("低声"));
    if (!has) {
      addWhisperLine(name);
    }
  }

  function appendNarrationOnce(text) {
    const log = state.game && state.game.public_log;
    if (!log || !text) {
      return;
    }
    const line = String(text);
    if (log.slice(-8).some((entry) => String(entry.text || "").trim() === line)) {
      return;
    }
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: line,
      day: state.game.day,
    });
  }

  function hasSuccessionFlag(data) {
    if (!data || typeof data !== "object") {
      return false;
    }
    for (const key of ["succession", "succession_occurred", "succeeded", "handoff"]) {
      const value = data[key];
      if (Array.isArray(value) ? value.length > 0 : Boolean(value)) {
        return true;
      }
    }
    return false;
  }

  function noteSuccessionHint(data) {
    if (!state.game || data && data.winner) {
      return;
    }
    if (!hasSuccessionFlag(data)) {
      return;
    }
    appendNarrationOnce(SUCCESSION_HINT);
    state.successionPending = true;
    if (!state.game.winner) {
      state.report = SUCCESSION_HINT;
    }
  }

  function showReport(text, kind = "info") {
    const playing = Boolean(state.game) && !state.game.winner;
    let line = text || "";
    if (playing && state.successionPending) {
      line = SUCCESSION_HINT;
      state.successionPending = false;
    }
    state.report = playing ? publicSafeText(line, true) : line;
    state.reportKind = kind;
    renderReport();
  }

  function lastWordsEligible() {
    return Boolean(state.game) && !isFinished() && !youAlive() && !state.lastWordsUsed;
  }

  function renderLastWords() {
    const form = $("last-words-form");
    const speakForm = $("speak-form");
    if (!form || !speakForm) {
      return;
    }
    if (!lastWordsEligible()) {
      form.classList.add("hidden");
      speakForm.classList.remove("hidden");
      return;
    }
    if (!state.lastWordsProbed && !state.mock) {
      state.lastWordsProbed = true;
      probeLastWords();
    }
    const visible = state.lastWordsAvailable !== false;
    form.classList.toggle("hidden", !visible);
    speakForm.classList.toggle("hidden", visible);
    if (!visible) {
      return;
    }
    const input = $("last-words-input");
    const button = $("last-words-button");
    if (!input || !button) {
      return;
    }
    input.disabled = state.busy;
    button.disabled = state.busy || !input.value.trim();
  }

  async function probeLastWords() {
    if (!state.game || state.mock) {
      state.lastWordsAvailable = true;
      render();
      return;
    }
    try {
      await apiRequest(`${API}/games/${state.gameId}/last-words`, { method: "GET" });
      state.lastWordsAvailable = true;
    } catch (error) {
      state.lastWordsAvailable = !(error && error.status === 404);
    }
    render();
  }

  function handleLastWords() {
    if (!state.game || state.busy || youAlive()) {
      return;
    }
    submitLastWords($("last-words-input"));
  }

  function handleEndLastWords() {
    if (!state.game || state.busy) {
      return;
    }
    submitLastWords($("end-last-words-input"));
  }

  function submitLastWords(input) {
    const raw = input ? input.value.trim() : "";
    if (!raw) {
      return;
    }
    const trimmed = trimToSentence(raw, 120);
    const text = trimmed.text;
    runAction(async () => {
      let unsupported = false;
      if (!state.mock) {
        try {
          await apiRequest(`${API}/games/${state.gameId}/last-words`, {
            method: "POST",
            body: { text },
          });
        } catch (error) {
          if (error && (error.status === 404 || error.status === 405 || error.status === 501)) {
            unsupported = true;
            state.lastWordsAvailable = false;
          } else {
            throw error;
          }
        }
      }
      if (unsupported) {
        showToast("遗言通道还没接通，这句话先留在本地。", "warn", 4200);
        render();
        return;
      }
      state.lastWordsUsed = true;
      state.lastWordsText = text;
      if (!state.mock) {
        await refreshReal();
      }
      addLastWordsLine(text);
      pushLocalEvent({
        type: "last_words",
        day: state.game ? state.game.day : 1,
        text: `遗言 · 「${text}」`,
      });
      if (input) {
        input.value = "";
      }
      render();
      showToast("遗言记下了。", "good");
    });
  }

  function addLastWordsLine(text) {
    const log = state.game && state.game.public_log;
    if (!log) {
      return;
    }
    if (log.some((entry) => String(entry.text || "").includes(text))) {
      return;
    }
    log.push({
      seq: nextSeq(log),
      speaker_id: youId(),
      speaker_name: "你",
      text,
      day: state.game.day,
    });
  }

  function lastWordsFromHistory() {
    for (const row of [].concat(state.game && state.game.day_history || [], state.game && state.game.aftermath || [])) {
      const words = String((row && (row.last_words || row.lastWords)) || "").trim();
      if (words) {
        return words;
      }
    }
    return "";
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
      return state.endPending && !state.endRevealed
        ? "下一步：点「查看结局」——先看票板与处决结果，再翻底牌。"
        : "本局已结束。下一步：点「再来一局」。";
    }
    if (!youAlive()) {
      if (ghostVoteOpen()) {
        return "下一步：桌上正在落票。亡者票只有一次，选人后点「投出你的一票」。";
      }
      if (state.ghostVoteUsed) {
        return "下一步：点「继续观战」把这一夜看完。";
      }
      if (lastWordsEligible() && state.lastWordsAvailable !== false) {
        return "下一步：先留一句遗言，再点「继续观战」。";
      }
      return "下一步：点「继续观战」，让他们把这一夜走完。";
    }
    if (phase === "defense") {
      const target = state.nominated ? state.nominated.name : "被提名者";
      return `下一步：听完「${target}」自辩，在票板选人，再按「投票」。`;
    }
    if (phase === "runoff") {
      const round = Math.max(1, state.runoffStalemate);
      return `下一步：第 ${round} 次加赛，只在平票的人里选一个，按「再投一次」。`;
    }
    if (phase === "nomination") {
      return "下一步：点席位选人，再按「提名」；不想提名就按「继续讨论」。";
    }
    if (phase === "night") {
      return youRole() === "murderer"
        ? "下一步：点席位选一个人，再按「动手」。"
        : "下一步：按「等待天亮」，看这一夜发生了什么。";
    }
    return "下一步：可以追问，也可以按「结束讨论，提名」。";
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
    const wait = $("table-wait");
    if (wait) {
      wait.classList.toggle("hidden", !state.busy);
      if (state.busy) {
        let label = "桌上正低声商议……";
        if (state.ballotTargetId) {
          label = "正在落票……";
        } else if (phase === "defense") {
          label = "正在质证……";
        } else if (phase === "night") {
          label = "夜色在动……";
        }
        wait.textContent = label;
      }
    }

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
      input.placeholder = "对桌上的人说点什么";
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
    secondary.disabled = state.busy || state.advancing;

    const confide = $("confide-button");
    const confideVisible = Boolean(state.game) && !finished && alive
      && (phase === "discussion" || phase === "defense");
    confide.classList.toggle("hidden", !confideVisible);
    if (confideVisible) {
      const today = confideRemainingToday();
      const total = confideRemainingTotal();
      if (total <= 0) {
        confide.textContent = "密谈（已用完）";
      } else if (today <= 0) {
        confide.textContent = "密谈（今日已用）";
      } else {
        confide.textContent = "密谈";
      }
      confide.disabled = state.busy || !canConfide();
      confide.title = total <= 0
        ? "本局三次密谈都用完了"
        : (today <= 0 ? "今天已经密谈过一次，明晚再来" : "每天一次，本局三次");
    }

    const inspect = $("inspect-button");
    const inspectVisible = Boolean(state.game) && !finished && alive
      && (phase === "discussion" || phase === "defense");
    inspect.classList.toggle("hidden", !inspectVisible);
    if (inspectVisible) {
      const isMurderer = isEvilRole(role);
      const unavailable = state.inspectAvailable === false;
      inspect.classList.toggle("is-locked", isMurderer || unavailable);
      inspect.textContent = isMurderer
        ? "查验（你没有）"
        : (unavailable ? "查验（暂不可用）" : (state.inspectUsed ? "查验（已用）" : (state.inspectOpen ? "收起查验" : "查验")));
      inspect.disabled = isMurderer || state.busy || state.inspectUsed || unavailable;
      inspect.setAttribute("aria-disabled", isMurderer || state.inspectUsed || unavailable ? "true" : "false");
      inspect.title = isMurderer
        ? "你没有查验——只有镇民手里才有这一项"
        : (unavailable
          ? "查验接口还没就绪，本轮先不开放"
          : (state.inspectUsed ? "本局查验已用" : "只掀一个人的底牌，查完桌上都会知道"));
    }

    let primaryText = "";
    let primaryVisible = false;
    let primaryDisabled = state.busy;
    const selection = findPlayer(state.selectedId);
    if (finished && state.endPending && !state.endRevealed) {
      primaryText = "查看结局";
      primaryVisible = true;
    } else if (state.game && !finished && alive) {
      if (phase === "nomination") {
        primaryText = "提名";
        primaryVisible = true;
        primaryDisabled = primaryDisabled || !selection;
      } else if (phase === "defense") {
        const target = ballotTarget();
        primaryText = target ? `投票 · ${displayName(target)}` : "投票";
        primaryVisible = true;
        primaryDisabled = primaryDisabled || !target;
      } else if (phase === "runoff") {
        const target = runoffTarget();
        primaryText = target ? `再投一次 · ${displayName(target)}` : "再投一次";
        primaryVisible = true;
        primaryDisabled = primaryDisabled || !target;
      } else if (phase === "night") {
        if (state.voteHeld) {
          primaryText = "看过票板，进入夜晚";
          primaryVisible = true;
        } else if (role === "murderer") {
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
      hallHint.textContent = ghostVoteOpen()
        ? "你退到了廊下。桌上正在落票，你的亡者票还攥在手里。"
        : "你已出局，观战中。他们还在桌边争论。";
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
    } else if (phase === "runoff") {
      hallHint.textContent = "票数咬死了。桌上重新摆票，只投平票的那几个人。";
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
    if (message.includes("凶手胜") || message.includes("凶手还站着") || message.includes("逃脱")) {
      return "凶手胜";
    }
    if (message.includes("好人胜") || message.includes("凶手伏法")) {
      return "好人胜";
    }
    return "";
  }

  function murdererStands() {
    const info = resolveRevealInfo();
    const target = info && info.final && (info.final.id || info.final.name)
      ? info.final
      : (info && info.demon && (info.demon.id || info.demon.name) ? info.demon : null);
    if (target) {
      const player = players().find((item) => item.id === target.id || item.name === target.name);
      if (player) {
        return player.alive !== false;
      }
    }
    const name = resolveRevealName();
    if (!name || name === "终局揭晓") {
      return youRole() === "murderer" && youAlive();
    }
    const player = players().find((item) => item.name === name
      || item.id === name
      || displayName(item) === name);
    if (player) {
      return player.alive !== false;
    }
    return youRole() === "murderer" && youAlive();
  }

  function resolveRevealInfo() {
    if (state.revealInfo) {
      return state.revealInfo;
    }
    captureReveal(state.game);
    return state.revealInfo;
  }

  function successionText(info) {
    const steps = info && Array.isArray(info.succession) ? info.succession : [];
    if (!steps.length) {
      return "";
    }
    const parts = steps.map((step) => {
      const day = Number(step.day) || 0;
      const prefix = day ? `第 ${day} 天 · ` : "";
      if (step.from && step.to) {
        return `${prefix}原爪牙 ${step.to} 接位（${step.from} 倒下后）`;
      }
      if (step.to) {
        return `${prefix}原爪牙 ${step.to} 接位`;
      }
      if (step.from) {
        return `${prefix}${step.from} 把印递了出去`;
      }
      return `${prefix}${step.label || "印章换了一只手"}`;
    });
    return parts.join("；");
  }

  function fallbackWinnerLabel() {
    if (!isFinished()) {
      return "";
    }
    const murderer = resolveRevealName();
    if (!murderer || murderer === "终局揭晓") {
      return "";
    }
    return murdererStands() ? "凶手胜" : "好人胜";
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

  function revealRoleLabel(escaped = false) {
    const name = resolveRevealName();
    if (!name || name === "终局揭晓") {
      return "恶魔 · 待卷宗封存";
    }
    return escaped ? "恶魔 · 未被处决" : "恶魔 · 已落网";
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
    const info = resolveRevealInfo();
    const target = info && info.final && info.final.name ? info.final : (info && info.demon);
    const name = (target && target.name) || resolveRevealName();
    const murderer = target && target.id
      ? findPlayer(target.id)
      : (players().find((player) => player.name === name)
        || (youRole() === "murderer" ? youPlayer() : null));
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

  function nameToId(name) {
    const player = players().find((item) => item.name === name || item.id === name);
    return player ? player.id : "";
  }

  function personFromName(name) {
    const id = nameToId(name);
    return { id, name: id ? playerName(id) : name };
  }

  function dayFromText(text) {
    const raw = String(text || "");
    const match = raw.match(/第\s*([0-9]+|[一二三四五六七八九十]+)\s*[天夜]/u);
    if (!match) {
      return 0;
    }
    return parseDayToken(match[1]);
  }

  function parseDayToken(token) {
    const value = String(token || "").trim();
    if (/^\d+$/u.test(value)) {
      return Number(value) || 0;
    }
    const digits = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
    if (value === "十") {
      return 10;
    }
    if (value.length === 2 && value[0] === "十") {
      return 10 + (digits[value[1]] || 0);
    }
    if (value.length === 2 && value[1] === "十") {
      return (digits[value[0]] || 0) * 10;
    }
    if (value.length === 3 && value[1] === "十") {
      return (digits[value[0]] || 0) * 10 + (digits[value[2]] || 0);
    }
    return digits[value] || 0;
  }

  function resolveLogDays(log) {
    let day = 1;
    const out = [];
    for (const entry of log || []) {
      const explicit = Number(entry.day);
      const marker = dayFromText(entry.text);
      if (Number.isFinite(explicit) && explicit > 0) {
        day = explicit;
      } else if (marker) {
        day = marker;
      }
      out.push({ ...entry, day });
      const narration = entry.speaker_id === "__narration"
        || entry.speaker_id === "narrator"
        || entry.speaker_name === "旁白";
      if (narration && !marker && /天亮|次日|转天/u.test(String(entry.text || ""))) {
        day += 1;
      }
    }
    return out;
  }

  function aftermathFromLog() {
    const log = resolveLogDays((state.game && state.game.public_log) || []);
    const byDay = new Map();
    for (const entry of log) {
      const narration = entry.speaker_id === "__narration"
        || entry.speaker_id === "narrator"
        || entry.speaker_name === "旁白";
      if (!narration) {
        continue;
      }
      const text = String(entry.text || "");
      if (!text) {
        continue;
      }
      const day = Math.max(1, Number(entry.day) || 1);
      const row = byDay.get(day) || {
        day,
        executed: null,
        killed: null,
        tie: false,
        tally: [],
        threshold: 0,
        note: "",
      };
      if (/平票/u.test(text)) {
        row.tie = true;
      }
      if (!row.executed) {
        const exec = text.match(/(?:^|[，,。；;\s])([^，,。；;\s]{1,8})\s*被(?:投票)?处决/u);
        if (exec) {
          row.executed = personFromName(exec[1]);
        }
      }
      if (!row.killed) {
        const kill = text.match(/天亮时[，,]?\s*(你|[^，,。；;\s]{1,8})\s*(?:没有下楼|死在|倒在|不见)/u);
        if (kill) {
          row.killed = personFromName(kill[1]);
        }
      }
      if (!row.note) {
        row.note = text.slice(0, 60);
      }
      byDay.set(day, row);
    }
    return [...byDay.values()].sort((left, right) => left.day - right.day);
  }

  function normalizeDayHistory(raw) {
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw
      .map((item) => {
        if (!item || typeof item !== "object") {
          return null;
        }
        const tally = normalizeTally(item.tally || item.votes_tally || []);
        return {
          day: Math.max(1, Number(item.day) || 1),
          executed: normalizePerson(item.executed),
          killed: normalizePerson(item.killed),
          tie: Boolean(item.tie || item.tied),
          stalemate: Boolean(item.stalemate || item.tie || item.tied),
          tally,
          threshold: Number(item.threshold) || 0,
          note: String(item.note || item.message || ""),
          last_words: String(item.last_words || item.lastWords || ""),
        };
      })
      .filter(Boolean);
  }

  function resolveAftermath() {
    const history = normalizeDayHistory(state.game && state.game.day_history);
    const backend = normalizeDayHistory(state.game && state.game.aftermath);
    const rows = [];
    const put = (row) => {
      if (!row) {
        return;
      }
      const existing = rows.find((item) => item.day === row.day);
      if (!existing) {
        rows.push(row);
        return;
      }
      existing.executed = existing.executed || row.executed;
      existing.killed = existing.killed || row.killed;
      existing.tie = existing.tie || row.tie;
      existing.stalemate = existing.stalemate || row.stalemate;
      existing.tally = existing.tally.length ? existing.tally : row.tally;
      existing.threshold = existing.threshold || row.threshold;
      existing.note = existing.note || row.note;
    };
    for (const row of history) {
      put(row);
    }
    for (const row of backend) {
      put(row);
    }
    for (const row of aftermathFromLog()) {
      if (!rows.some((item) => item.day === row.day)) {
        put(row);
      }
    }
    const result = state.voteResult;
    if (result && (result.executedName || result.executedId || result.message)) {
      const day = result.day || (state.game && state.game.day) || 1;
      let row = rows.find((item) => item.day === day);
      if (!row) {
        row = {
          day,
          executed: null,
          killed: null,
          tie: false,
          tally: [],
          threshold: 0,
          note: "",
        };
        rows.push(row);
      }
      if (!row.executed && result.executedName) {
        row.executed = { id: result.executedId, name: result.executedName };
      }
      if (!row.tally.length && Array.isArray(result.tally)) {
        row.tally = result.tally.map((item) => ({ ...item }));
      }
      row.threshold = row.threshold || result.threshold || 0;
      row.tie = row.tie || Boolean(result.tie);
      if (!row.note) {
        row.note = result.message || "";
      }
    }
    if (!rows.length) {
      rows.push({
        day: (state.game && state.game.day) || 1,
        executed: null,
        killed: null,
        note: (state.game && state.game.message) || "牌翻过来了，本局到此为止。",
      });
    }
    return rows.sort((left, right) => left.day - right.day);
  }

  function playerDeathDay() {
    const id = youId();
    const player = youPlayer();
    const names = new Set(["你"]);
    if (player && player.name) {
      names.add(player.name);
    }
    const days = [];
    if (state.voteResult && state.voteResult.executedId === id) {
      days.push(state.voteResult.day || 1);
    }
    for (const item of resolveAftermath()) {
      if (item.executed && (item.executed.id === id || names.has(item.executed.name))) {
        days.push(item.day);
      }
      if (item.killed && (item.killed.id === id || names.has(item.killed.name))) {
        days.push(item.day);
      }
    }
    return days.length ? Math.min(...days) : ((state.game && state.game.day) || 1);
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
      const tally = Array.isArray(item.tally) ? item.tally : [];
      const topCount = tally.length ? Number(tally[0].count) || 0 : 0;
      const tie = Boolean(item.tie)
        || (Boolean(item.stalemate) && tally.length > 1
          && Number(tally[1].count) === topCount && topCount > 0);
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
        let emptyText = "无人出局";
        if (tie) {
          emptyText = "平票 · 无人被处决";
        } else if (item.stalemate) {
          emptyText = item.threshold
            ? `未达 ${item.threshold} 票门槛 · 无人被处决`
            : "未达门槛 · 无人被处决";
        }
        what.append(node("span", `ea-empty${tie ? " is-tie" : ""}`, emptyText));
      }
      row.append(what);
      if (tally.length) {
        const parts = tally
          .slice()
          .sort((left, right) => right.count - left.count)
          .map((entry) => `${playerName(entry.id)} ${entry.count}`);
        row.append(node("span", "ea-tally",
          `共 ${tally.reduce((sum, entry) => sum + (Number(entry.count) || 0), 0)} 票 · ${parts.join(" / ")}`
          + (item.threshold ? ` · 门槛 ${item.threshold}` : "")));
      }
      let note = String(item.note || "").replace(/^第\s*\d+\s*天[，,]\s*/u, "");
      const subjects = [];
      if (item.executed) {
        subjects.push(item.executed.name);
      }
      if (item.killed) {
        subjects.push(item.killed.name);
      }
      const you = youPlayer();
      if (you && you.name) {
        subjects.push(you.name);
      }
      const matched = subjects.find((name) => name && note.startsWith(name));
      if (matched) {
        const deathPrefix = new RegExp(
          `^${matched.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*(?:被(?:投票)?处决|夜里|天亮时|死在|没有下楼|倒下|被杀)`,
          "u",
        );
        if (deathPrefix.test(note)) {
          note = note.slice(matched.length)
            .replace(/^\s*(?:被(?:投票)?处决|夜里|天亮时|死在|没有下楼|倒下|被杀)[，,]?\s*/u, "")
            .replace(/^[；;]\s*/u, "")
            .trim();
        }
      }
      if (tie || /^(?:最高\s*\d+\s*票|平票|票数不够|无人被处决)/u.test(note)
        || /^\d+\s*\/\s*\d+\s*票过门槛/u.test(note)) {
        note = "";
      }
      note = note.replace(/^[。．.、；;，,：:\s]+/u, "").trim();
      if (/^[。．.、；;，,：:\s]*$/u.test(note)) {
        note = "";
      }
      if (note) {
        row.append(node("span", "ea-note", note));
      }
      target.append(row);
    }
  }

  function renderFatalVote() {
    const el = $("end-fatal");
    const result = state.voteResult || state.lastVoteResult;
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

  function dedupeEndMessage(message) {
    const raw = String(message || "");
    if (!raw) {
      return "雪停了，真相留在了桌上。";
    }
    const seen = new Set();
    const kept = raw.split(/(?<=[。！？])/u).filter((sentence) => {
      const trimmed = sentence.trim();
      if (!trimmed) {
        return false;
      }
      if (seen.has(trimmed)) {
        return false;
      }
      seen.add(trimmed);
      return true;
    });
    return kept.join("") || raw;
  }

  function revealDeathText(info) {
    const killed = info && info.killed && info.killed.name ? info.killed.name : "";
    const executed = info && info.executed && info.executed.name ? info.executed.name : "";
    const parts = [];
    if (killed) {
      parts.push(`夜杀 · ${killed}`);
    }
    if (executed) {
      parts.push(`处决 · ${executed}`);
    }
    if (parts.length) {
      return parts.join("；");
    }
    const rows = resolveAftermath();
    const fallback = [];
    for (const row of rows) {
      if (row.killed && row.killed.name) {
        fallback.push(`夜杀 · ${row.killed.name}`);
      }
      if (row.executed && row.executed.name) {
        fallback.push(`处决 · ${row.executed.name}`);
      }
    }
    return fallback.length ? [...new Set(fallback)].join("；") : "无";
  }

  function renderEndReveal() {
    const section = $("end-reveal");
    if (!section) {
      return;
    }
    const info = resolveRevealInfo() || {};
    const minionName = info.minion && info.minion.name ? info.minion.name : "";
    const poisonedName = info.poisoned && info.poisoned.name ? info.poisoned.name : "";
    const deathText = revealDeathText(info);
    const chain = successionText(info);
    $("end-minion").textContent = minionName
      ? `${minionName}${chain ? " · 原爪牙" : ""}`
      : "无";
    $("end-poisoned").textContent = poisonedName
      ? `${poisonedName} · 信息有误（不是夜杀）`
      : "无";
    const killedEl = $("end-killed");
    if (killedEl) {
      killedEl.textContent = deathText;
    }
    const chainEl = $("end-succession");
    if (chainEl) {
      chainEl.textContent = chain || "无";
    }
    const row = $("end-succession-row");
    if (row) {
      row.classList.toggle("hidden", !chain);
    }
    section.classList.toggle("hidden", !(minionName || poisonedName || chain || deathText !== "无"));
  }

  function youIsDead() {
    return Boolean(state.game && state.game.you_alive === false)
      || Boolean(state.voteResult && state.voteResult.executedId === youId())
      || Boolean(youPlayer() && youPlayer().alive === false);
  }

  function resolveYourResult() {
    const raw = String((state.game && (state.game.your_result || state.game.you_result)) || "").toLowerCase();
    if (["win", "lose", "draw", "late_good", "late_evil"].includes(raw)) {
      return raw;
    }
    if (["posthumous_good", "after_death_good", "good_after_death"].includes(raw)) {
      return "late_good";
    }
    if (["posthumous_evil", "after_death_evil", "evil_after_death"].includes(raw)) {
      return "late_evil";
    }
    if (/出局后.*好人/u.test(raw)) {
      return "late_good";
    }
    if (/出局后.*(凶手|逃脱)/u.test(raw)) {
      return "late_evil";
    }
    if (/赢/u.test(raw)) {
      return "win";
    }
    if (/输/u.test(raw)) {
      return "lose";
    }
    const winFlag = state.game && state.game.you_win;
    if (typeof winFlag === "boolean") {
      return winFlag ? "win" : "lose";
    }
    const winner = inferredWinnerLabel() || fallbackWinnerLabel();
    if (!winner) {
      return "";
    }
    const evil = isEvilRole(youRole());
    const sideWin = (winner === "好人胜" && !evil) || (winner === "凶手胜" && evil);
    if (!youIsDead()) {
      return sideWin ? "win" : "lose";
    }
    if (sideWin) {
      return evil ? "late_evil" : "late_good";
    }
    return "lose";
  }

  function renderEnd() {
    const overlay = $("end-overlay");
    if (!isFinished() || !state.endRevealed) {
      overlay.classList.add("hidden");
      overlay.setAttribute("aria-hidden", "true");
      return;
    }
    const winner = inferredWinnerLabel() || fallbackWinnerLabel() || "天亮了";
    const escaped = winner === "凶手胜" && murdererStands();
    const result = winner === "好人胜" ? "villagers" : (winner === "凶手胜" ? "murderer" : "unknown");
    $("end-frame").dataset.result = result;
    $("end-kicker").textContent = result === "murderer" ? "NIGHTFALL · 结局" : "DAWN · 结局";
    $("end-title").textContent = escaped ? "凶手逃脱" : winner;
    const yourResult = resolveYourResult();
    const yourEl = $("end-you-result");
    if (yourEl) {
      const label = YOUR_RESULT_LABEL[yourResult] || "";
      yourEl.textContent = label;
      yourEl.dataset.result = yourResult;
      yourEl.classList.toggle("hidden", !label);
    }
    $("end-frame").dataset.youResult = yourResult || "unknown";
    $("end-subtitle").textContent = dedupeEndMessage((state.game && state.game.message)
      || "雪停了，真相留在了桌上。");
    $("end-murderer").textContent = resolveRevealName();
    $("end-murderer-role").textContent = revealRoleLabel(escaped);
    const role = youRole();
    $("end-you").textContent = `你 · ${ROLE_LABEL[role] || "身份未知"}`;
    renderEndReveal();
    const youDead = youIsDead();
    const survived = youDead ? playerDeathDay() : ((state.game && state.game.day) || 1);
    $("end-days").textContent = `${survived} 天`;
    renderEndPortrait();
    renderAftermath(resolveAftermath());
    renderFatalVote();
    const words = state.lastWordsText || lastWordsFromHistory();
    const wordsEl = $("end-last-words");
    if (wordsEl) {
      if (words) {
        wordsEl.textContent = `遗言 · 「${words}」`;
        wordsEl.classList.remove("hidden");
      } else {
        wordsEl.textContent = "";
        wordsEl.classList.add("hidden");
      }
    }
    renderEndLastWordsForm(youDead);
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function renderEndLastWordsForm(youDead) {
    const form = $("end-last-words-form");
    if (!form) {
      return;
    }
    if (!youDead || state.lastWordsUsed) {
      form.classList.add("hidden");
      return;
    }
    if (!state.lastWordsProbed && !state.mock) {
      state.lastWordsProbed = true;
      probeLastWords();
    }
    const visible = state.lastWordsAvailable !== false;
    form.classList.toggle("hidden", !visible);
    if (!visible) {
      return;
    }
    const input = $("end-last-words-input");
    const button = $("end-last-words-button");
    if (input && button) {
      button.disabled = state.busy || !input.value.trim();
    }
  }

  const DRAWER_ENTRY_TYPES = new Set([
    "ask", "speak", "say", "discuss", "discussion", "reply", "respond",
    "defense", "defend", "crossexam", "cross-exam", "nominate", "nomination",
    "vote", "voting", "night", "kill", "execute", "execution", "executed",
    "narration", "narrate", "public", "message", "report", "system",
    "inspect", "last_words", "lastwords",
  ]);

  const DRAWER_EVENT_TYPES = new Set([
    "nominate", "nomination", "vote", "voting", "night", "kill", "execute", "execution",
    "inspect", "last_words", "lastwords",
  ]);

  const DRAWER_EVENT_META = {
    nominate: "提名",
    nomination: "提名",
    vote: "投票",
    voting: "投票",
    night: "夜晚",
    kill: "夜晚",
    execute: "处决",
    execution: "处决",
    inspect: "查验",
    last_words: "遗言",
    lastwords: "遗言",
  };

  function logPerson(id, provided) {
    if (id) {
      const player = findPlayer(id);
      if (player) {
        return displayName(player);
      }
    }
    return String(provided || id || "某人");
  }

  function summarizeVoteEntry(entry) {
    const rawVotes = entry.votes || entry.ballots || entry.ballot;
    const asArray = Array.isArray(rawVotes)
      ? rawVotes
      : (rawVotes && typeof rawVotes === "object"
        ? Object.entries(rawVotes).map(([voterId, target]) => ({
          voter_id: voterId,
          target_id: typeof target === "string" ? target : idOf(target),
        }))
        : []);
    if (!asArray.length) {
      return "";
    }
    const counts = new Map();
    const lines = [];
    for (const vote of asArray) {
      const voter = logPerson(vote.voter_id || vote.voterId, vote.voter_name || vote.voterName);
      const target = logPerson(
        idOf(vote.target_id || vote.targetId || vote.target),
        vote.target_name || vote.targetName,
      );
      const reason = sanitizeReason(vote.reason || vote.why || "", target);
      counts.set(target, (counts.get(target) || 0) + 1);
      const quote = reason ? (reason.startsWith("「") ? reason : `「${reason}」`) : "";
      lines.push(`${voter} → ${target}${quote ? `：${quote}` : ""}`);
    }
    const tally = [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((left, right) => right.count - left.count);
    const total = asArray.length;
    const threshold = Number(entry.threshold)
      || (state.voteResult && Number(state.voteResult.day) === Number(entry.day)
        ? Number(state.voteResult.threshold) : 0);
    const executedRaw = entry.executed || entry.executed_name || entry.result;
    const executed = executedRaw ? logPerson(idOf(executedRaw), nameOf(executedRaw)) : "";
    const tie = Boolean(entry.tie || entry.tied) || /平票/u.test(String(entry.message || ""));
    const outcome = executed
      ? `处决 ${executed}`
      : (tie ? "平票，无人被处决"
        : (threshold ? `最高 ${tally[0] ? tally[0].count : 0} 票，未达 ${threshold} 票门槛`
          : `最高 ${tally[0] ? tally[0].count : 0} 票`));
    return `投票 · 共 ${total} 票 · ${tally.map((item) => `${item.name} ${item.count}`).join(" / ")} · ${outcome}`
      + `\n${lines.join("\n")}`;
  }

  function summarizeNominateEntry(entry) {
    const targetRaw = entry.target || entry.target_id || entry.nominee;
    if (!targetRaw) {
      return "";
    }
    const target = logPerson(idOf(targetRaw), nameOf(targetRaw));
    const defense = entry.defense && typeof entry.defense === "object"
      ? sanitizeLine(String(entry.defense.text || entry.defense.content || ""), false)
      : "";
    return `提名 · ${target}${defense ? `\n自辩：${defense}` : ""}`;
  }

  function summarizeNightEntry(entry) {
    const killedRaw = entry.killed || entry.killed_id || entry.victim;
    const killed = killedRaw ? logPerson(idOf(killedRaw), nameOf(killedRaw)) : "";
    return killed
      ? `夜晚 · ${killed} 没有下楼`
      : `夜晚 · 无人被杀${/平票|僵局/u.test(String(entry.message || "")) ? "（平票僵局）" : ""}`;
  }

  function adaptDrawerEntry(entry) {
    if (!entry || typeof entry !== "object") {
      return null;
    }
    const type = String(entry.type || entry.kind || entry.event || "").toLowerCase();
    if (type && !DRAWER_ENTRY_TYPES.has(type)) {
      return null;
    }
    const payload = entry.payload && typeof entry.payload === "object" ? entry.payload : null;
    const data = entry.data && typeof entry.data === "object" ? entry.data : null;
    let text = entry.text ?? entry.content
      ?? (payload && (payload.text ?? payload.content))
      ?? (data && (data.text ?? data.content));
    if (typeof text !== "string" || !text.trim()) {
      if (type === "vote" || type === "voting") {
        text = summarizeVoteEntry(entry);
      } else if (type === "nominate" || type === "nomination") {
        text = summarizeNominateEntry(entry);
      } else if (type === "night" || type === "kill" || type === "execute" || type === "execution") {
        text = summarizeNightEntry(entry);
      } else {
        text = "";
      }
    }
    if (!text || !String(text).trim()) {
      return null;
    }
    const isEvent = DRAWER_EVENT_TYPES.has(type);
    return {
      ...entry,
      text: String(text),
      type,
      speaker_id: isEvent ? "__log" : (entry.speaker_id || entry.speakerId
        || (payload && payload.speaker_id) || (data && data.speaker_id)),
      speaker_name: isEvent ? "卷宗" : (entry.speaker_name || entry.speakerName
        || (payload && payload.speaker_name) || (data && data.speaker_name)),
      day: entry.day ?? (payload && payload.day) ?? (data && data.day),
    };
  }

  function extractDrawerEntries(data) {
    if (Array.isArray(data)) {
      return normalizeLog(data.map(adaptDrawerEntry).filter(Boolean));
    }
    if (!data || typeof data !== "object") {
      return [];
    }
    const raw = data.entries || data.log || data.public_log || data.events || [];
    if (!Array.isArray(raw)) {
      return [];
    }
    return normalizeLog(raw.map(adaptDrawerEntry).filter(Boolean));
  }

  function mergeDrawerEntries(primary, extra) {
    const merged = [];
    const seen = new Set();
    for (const entry of [...primary, ...extra]) {
      const key = `${entry.day}|${entry.text}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(entry);
    }
    return merged
      .map((entry, index) => ({ ...entry, seq: index + 1 }))
      .sort((left, right) => (Number(left.day) || 1) - (Number(right.day) || 1));
  }

  function localLogEntries() {
    return resolveLogDays((state.game && state.game.public_log) || []);
  }

  function renderDrawer(entries) {
    const list = $("log-drawer-list");
    const empty = $("log-drawer-empty");
    list.textContent = "";
    const sorted = [...entries].sort((left, right) => {
      const dayDiff = (Number(left.day) || 1) - (Number(right.day) || 1);
      if (dayDiff) {
        return dayDiff;
      }
      const leftEvent = left.speaker_id === "__log" ? 0 : 1;
      const rightEvent = right.speaker_id === "__log" ? 0 : 1;
      return leftEvent - rightEvent;
    });
    if (!sorted.length) {
      empty.classList.remove("hidden");
      empty.textContent = state.game ? "本局还没有记录。" : "还没有开局。";
      return;
    }
    empty.classList.add("hidden");
    let lastDay = 0;
    for (const entry of sorted) {
      const isYou = entry.speaker_id === youId();
      const narration = entry.speaker_id === "__narration"
        || entry.speaker_id === "narrator"
        || entry.speaker_name === "旁白";
      const event = entry.speaker_id === "__log";
      const dayNum = Number(entry.day) || 1;
      if (dayNum !== lastDay) {
        list.append(node("li", "log-day", `第 ${dayNum} 天 · 卷宗`));
        lastDay = dayNum;
      }
      const item = node("li", "drawer-entry");
      if (isYou) {
        item.classList.add("is-you");
      }
      if (narration) {
        item.classList.add("is-narration");
      }
      if (event) {
        item.classList.add("is-event");
        if (entry.type === "vote" || entry.type === "voting") {
          item.classList.add("is-vote");
        }
        if (entry.type === "night" || entry.type === "kill") {
          item.classList.add("is-night");
        }
      }
      const day = Number(entry.day) || 1;
      const who = event
        ? (DRAWER_EVENT_META[entry.type] || "事件")
        : (isYou ? "你" : entry.speaker_name || "旁白");
      const safeText = publicSafeText(entry.text, narration);
      if (narration && isWhisperText(safeText)) {
        item.classList.add("is-whisper");
        if (isSelfWhisperText(safeText)) {
          item.classList.add("is-whisper-self");
        }
      }
      item.append(
        node("p", "drawer-meta", `第 ${day} 天 · ${who}`),
        node("p", "drawer-text", safeText),
      );
      list.append(item);
    }
    if (state.drawerTab === "public") {
      $("log-drawer-count").textContent = `${sorted.length} 条`;
    }
  }

  function normalizePrivateEntries(raw) {
    if (!Array.isArray(raw)) {
      return [];
    }
    return raw
      .map((entry) => {
        if (!entry || typeof entry !== "object") {
          return null;
        }
        const targetId = String(entry.target_id || entry.targetId || "");
        const targetName = String(entry.target_name || entry.targetName || "")
          || (targetId ? playerName(targetId) : "");
        const text = String(entry.text || entry.content || "");
        if (!text.trim()) {
          return null;
        }
        return {
          day: Math.max(1, Number(entry.day) || 1),
          target_id: targetId,
          target_name: targetName || "那个人",
          text,
          stance: String(entry.stance || "neutral"),
          reply: String(entry.reply || ""),
          betrayed: Boolean(entry.betrayed),
          trust: entry.trust !== undefined ? entry.trust : entry.trust_delta,
          suspicion: entry.suspicion !== undefined ? entry.suspicion : entry.suspicion_delta,
          follow: entry.follow !== undefined ? entry.follow : entry.follow_delta,
        };
      })
      .filter(Boolean);
  }

  function mergePrivateEntries(primary, extra) {
    const merged = [];
    const index = new Map();
    for (const entry of [...primary, ...extra]) {
      const key = `${entry.day}|${entry.target_id}|${entry.text}`;
      if (index.has(key)) {
        const kept = merged[index.get(key)];
        for (const field of ["trust", "suspicion", "trust_delta", "suspicion_delta", "reply"]) {
          if (kept[field] === undefined && entry[field] !== undefined) {
            kept[field] = entry[field];
          }
        }
        continue;
      }
      index.set(key, merged.length);
      merged.push(entry);
    }
    return merged.sort((left, right) => (Number(left.day) || 1) - (Number(right.day) || 1));
  }

  function renderPrivateDrawer(entries) {
    const list = $("private-drawer-list");
    const empty = $("private-drawer-empty");
    list.textContent = "";
    if (!entries.length) {
      empty.classList.remove("hidden");
      empty.textContent = state.game ? "本局还没有私下说过话。" : "还没有开局。";
      return;
    }
    empty.classList.add("hidden");
    let lastDay = 0;
    for (const entry of entries) {
      const day = Number(entry.day) || 1;
      if (day !== lastDay) {
        list.append(node("li", "log-day", `第 ${day} 天 · 廊下`));
        lastDay = day;
      }
      const item = node("li", "private-entry");
      item.append(
        node("p", "private-meta", `你对 ${entry.target_name} 低声说`),
        node("p", "private-said", `「${entry.text}」`),
      );
      if (entry.reply) {
        const reply = node("p", "private-reply");
        reply.append(
          node("span", "private-reply-who", `${entry.target_name} · ${STANCE_LABEL[entry.stance] || "没有表态"}`),
          document.createTextNode(entry.reply),
        );
        item.append(reply);
      }
      const shift = formatConfideShift(entry);
      if (!/没让你看出/u.test(shift)) {
        item.append(node("p", "private-shift", shift));
      }
      if (entry.betrayed) {
        item.append(node("p", "private-betray",
          "答应了，但可能反悔——也可能已经在公开场合反咬。"));
      }
      list.append(item);
    }
    if (state.drawerTab === "private") {
      $("log-drawer-count").textContent = `${entries.length} 条`;
    }
  }

  async function loadPrivateDrawer() {
    let entries = state.privateLog.slice();
    if (state.game && !state.mock) {
      try {
        const data = await apiRequest(`${API}/games/${state.gameId}/private-log`);
        const remote = normalizePrivateEntries(data && data.entries);
        if (remote.length) {
          entries = mergePrivateEntries(remote, entries);
          state.privateLog = entries.slice();
        }
      } catch (error) {
        entries = state.privateLog.slice();
      }
    }
    renderPrivateDrawer(entries);
  }

  function setDrawerTab(tab) {
    state.drawerTab = tab === "private" ? "private" : "public";
    const publicScroll = $("log-drawer-scroll");
    const privateScroll = $("private-drawer-scroll");
    const isPrivate = state.drawerTab === "private";
    publicScroll.classList.toggle("hidden", isPrivate);
    privateScroll.classList.toggle("hidden", !isPrivate);
    $("drawer-tab-public").classList.toggle("is-active", !isPrivate);
    $("drawer-tab-private").classList.toggle("is-active", isPrivate);
    $("drawer-tab-public").setAttribute("aria-selected", isPrivate ? "false" : "true");
    $("drawer-tab-private").setAttribute("aria-selected", isPrivate ? "true" : "false");
    if (isPrivate) {
      loadPrivateDrawer();
    } else {
      $("log-drawer-count").textContent = `${$("log-drawer-list").children.length} 条`;
    }
  }

  async function openDrawer() {
    const drawer = $("log-drawer");
    drawer.classList.remove("hidden");
    drawer.setAttribute("aria-hidden", "false");
    state.drawerOpen = true;
    $("log-button").setAttribute("aria-expanded", "true");
    $("log-drawer-game").textContent = state.gameId || "";
    const local = mergeDrawerEntries(localLogEntries(), localEventEntries());
    renderDrawer(local);
    setDrawerTab(state.drawerTab);
    if (!state.game) {
      return;
    }
    if (state.mock) {
      renderDrawer(local);
      return;
    }
    try {
      const data = await apiRequest(`${API}/games/${state.gameId}/log`);
      const merged = mergeDrawerEntries(local, extractDrawerEntries(data));
      renderDrawer(merged);
    } catch (error) {
      renderDrawer(local);
      if (local.length) {
        showToast("回看接口未就绪，先显示本地记录。", "warn");
      }
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

  const MOCK_CONFIDE_LINES = {
    p1: [
      "…你要我保谁？先把话说明白，我不替人白担风险。",
      "廊下风大，你的话我只听一半。剩下半句，等上了桌再说。",
      "这楼里没有白给的人情。你拿什么换我这一句？",
    ],
    p2: [
      "…账我可以替你算，人我不替你保。",
      "低声说话，多半是见不得光的事。你直说吧。",
      "我记性好。你今天说的，我明天会记得。",
    ],
    p3: [
      "…我、我不太敢应你。叫人看见，我这差事就没了。",
      "你别站这么近。有话在桌上说，我听着。",
      "我什么都不知道。真的，你别再问了。",
    ],
    p4: [
      "…生意人听得懂这种话。你先开个价。",
      "我信证据，不信低声。你若拿得出东西，我倒可以听。",
      "你确认过别人的口风，才来找我？那我先听听你的。",
    ],
    p5: [
      "…我在这旅馆二十年，什么低声话没听过。你这也算话？",
      "马厩的灯我盯得清。你今夜从后门过不过，我都记着。",
      "你要我咬死谁？说清楚，别让我到桌上现编。",
    ],
  };

  const MOCK_CONFIDE_FALLBACK = [
    "…我听着，但没答应你什么。",
    "这话我记下了。至于怎么用，得看明天桌上谁先开口。",
    "别靠太近。隔墙有耳。",
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

  function openRules() {
    const overlay = $("rules-overlay");
    if (!overlay) {
      return;
    }
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
    const close = $("rules-close");
    if (close) {
      close.focus();
    }
  }

  function closeRules() {
    const overlay = $("rules-overlay");
    if (!overlay) {
      return;
    }
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    const button = $("rules-button");
    if (button) {
      button.focus();
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
      updateSpeakLimit();
    });
    $("discussion-scroll").addEventListener("scroll", () => {
      if (state.ignoreScroll) {
        return;
      }
      const el = $("discussion-scroll");
      state.userScrolled = el.scrollHeight - el.scrollTop - el.clientHeight > 120;
    });
    for (const gesture of ["wheel", "touchmove"]) {
      $("discussion-scroll").addEventListener(gesture, () => {
        state.ignoreScroll = false;
      }, { passive: true });
    }
    $("inspect-button").addEventListener("click", () => {
      if (state.inspectOpen) {
        closeInspect();
      } else {
        openInspect();
      }
    });
    $("inspect-close").addEventListener("click", closeInspect);
    $("inspect-confirm").addEventListener("click", handleInspect);
    $("inspect-private").addEventListener("click", () => {
      if (state.busy || state.inspectUsed) {
        return;
      }
      state.inspectReveal = false;
      renderInspect();
    });
    $("inspect-public").addEventListener("click", () => {
      if (state.busy || state.inspectUsed) {
        return;
      }
      state.inspectReveal = true;
      renderInspect();
    });
    $("spectate-advance").addEventListener("click", doAdvance);
    $("spectate-log").addEventListener("click", openDrawer);
    $("ghost-confirm").addEventListener("click", doGhostVote);
    $("ghost-hold").addEventListener("click", () => {
      if (state.busy || state.ghostVoteUsed) {
        return;
      }
      state.ghostDismissed = true;
      render();
    });
    $("last-words-input").addEventListener("input", () => {
      const button = $("last-words-button");
      button.disabled = state.busy || !$("last-words-input").value.trim();
    });
    $("last-words-form").addEventListener("submit", (event) => {
      event.preventDefault();
      handleLastWords();
    });
    $("end-last-words-input").addEventListener("input", () => {
      const button = $("end-last-words-button");
      button.disabled = state.busy || !$("end-last-words-input").value.trim();
    });
    $("end-last-words-form").addEventListener("submit", (event) => {
      event.preventDefault();
      handleEndLastWords();
    });
    $("confide-button").addEventListener("click", openConfide);
    $("confide-close").addEventListener("click", closeConfide);
    $("confide-send").addEventListener("click", handleConfideSend);
    $("confide-input").addEventListener("input", () => {
      updateConfideSend();
      updateConfideLimit();
    });
    $("confide-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        handleConfideSend();
      }
    });
    $("drawer-tab-public").addEventListener("click", () => setDrawerTab("public"));
    $("drawer-tab-private").addEventListener("click", () => setDrawerTab("private"));
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
    $("rules-button").addEventListener("click", openRules);
    $("rules-close").addEventListener("click", closeRules);
    $("rules-overlay").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) {
        closeRules();
      }
    });
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
      if (!$("rules-overlay").classList.contains("hidden")) {
        closeRules();
        return;
      }
      if (!$("confirm-strip").classList.contains("hidden")) {
        closeConfirm();
      }
      if (state.confideOpen) {
        closeConfide();
      }
      if (state.drawerOpen) {
        closeDrawer();
      }
    });
    window.addEventListener("resize", () => {
      const feed = $("spectate-feed");
      if (feed && !feed.classList.contains("hidden")) {
        feed.scrollTop = feed.scrollHeight;
      }
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

  function trimToSentence(raw, limit) {
    const text = String(raw || "").trim();
    if (text.length <= limit) {
      return { text, clipped: false };
    }
    const head = text.slice(0, limit);
    let cut = -1;
    for (const mark of ["。", "！", "？", "；", "\n"]) {
      cut = Math.max(cut, head.lastIndexOf(mark));
    }
    if (cut >= Math.floor(limit / 3)) {
      return { text: head.slice(0, cut + 1).trim(), clipped: true };
    }
    return { text: `${head.trim()}…`, clipped: true };
  }

  function updateSpeakLimit() {
    const el = $("speak-limit");
    const raw = $("speak-input").value;
    if (!el) {
      return;
    }
    if (raw.length <= SPEAK_MAX_CHARS) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const trimmed = trimToSentence(raw, SPEAK_MAX_CHARS);
    el.textContent = `发言超过 ${SPEAK_MAX_CHARS} 字，发送时会保留到最后一个句号（${trimmed.text.length} 字）。`;
    el.classList.remove("hidden");
  }

  function handleSpeak() {
    const input = $("speak-input");
    const raw = input.value.trim();
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
    if (!raw) {
      return;
    }
    const trimmed = trimToSentence(raw, SPEAK_MAX_CHARS);
    const text = trimmed.text;
    input.value = "";
    $("speak-limit").classList.add("hidden");
    if (trimmed.clipped) {
      showToast(`发言过长，已保留到最后一个句号（${text.length} 字）。`, "warn", 4200);
    }
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
      pushLocalEvent({
        type: "nominate",
        day: state.game ? state.game.day : 1,
        target: target ? { id: target.id, name: target.name } : null,
        defense: defense && defense.text ? { text: defense.text } : null,
      });
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
    const stalemateCount = Number((result && (result.stalemate_count ?? result.stalemateCount)) || 0);
    state.voteResult = {
      votes,
      tally,
      threshold,
      executedId: executedActualId,
      executedName,
      day: state.game ? state.game.day : 1,
      message: String((result && result.message) || ""),
      tie: Boolean(result && (result.tie || result.tied))
        || /平票|僵局/u.test(String((result && result.message) || "")),
      thresholdReduced: Boolean(result && (result.threshold_reduced || result.thresholdReduced))
        || stalemateCount >= 2,
    };
    if (state.voteResult.thresholdReduced) {
      state.thresholdReduced = true;
    }
    state.lastVotes = state.voteResult;
    state.lastVoteResult = state.voteResult;
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
    state.voteHeld = Boolean(state.game && state.game.phase === "night" && !isFinished());
    if (isFinished()) {
      state.endPending = true;
      state.endRevealed = false;
    }
    if (state.game && normalizePhase(state.game.phase) === "runoff") {
      state.runoffPickId = null;
    }
    state.stickForce = true;

    const message = (hasSuccessionFlag(result) && !(result && result.winner))
      ? SUCCESSION_HINT
      : ((result && result.message)
        || (executedName
          ? `${executedName} 被处决，天黑了。`
          : (state.voteResult.tie
            ? "平票，今晚无人被处决。"
            : `最高 ${Math.max(0, ...tally.map((row) => row.count), 0)} 票，未达 ${threshold} 票门槛。`)));
    showReport(message, executedName ? "warn" : "info");
    pushLocalEvent({
      type: "vote",
      day: state.voteResult.day,
      votes: votes.map((vote) => ({
        voter_id: vote.voterId,
        voter_name: vote.voterName,
        target_id: vote.targetId,
        target_name: vote.targetName,
        reason: vote.reason,
      })),
      threshold,
      executed: executedActualId ? { id: executedActualId, name: executedName } : null,
      tie: state.voteResult.tie,
      message,
    });

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
    const nightDay = state.game ? state.game.day : 1;
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
    const beforeSeq = state.lastSeq;
    const dawnText = killedName
      ? (killedName === "你" ? "天亮时，你没有下楼。" : `天亮时，${killedName} 没有下楼。`)
      : "天亮了，雪地上多了一行脚印。";
    const incoming = collectFreshEntries(payload, beforeSeq);
    if (!incoming.some((entry) => /天亮|天明|次晨/u.test(entry.text))) {
      const log = Array.isArray(payload.public_log)
        ? payload.public_log.slice()
        : ((state.game && Array.isArray(state.game.public_log)) ? state.game.public_log.slice() : []);
      log.push({
        seq: maxSeq(log) + 1,
        speaker_id: "__narration",
        speaker_name: "旁白",
        text: dawnText,
        day: Number(payload.day) || nightDay,
      });
      payload.public_log = log;
    }
    const dawnEntries = collectFreshEntries(payload, beforeSeq);
    showNightTransition(
      "天亮了……",
      killedName
        ? `第 ${Number(payload.day) || nightDay} 天。有人没能下楼。`
        : `第 ${Number(payload.day) || nightDay} 天。雪还在下。`,
      950,
    );
    applyGame(payload);
    recordSpectateEntries(dawnEntries);
    if (killedActualId) {
      markDead(killedActualId);
    }
    state.selectedId = null;
    state.nominationMode = false;
    state.lastVotes = null;
    state.voteResult = null;
    state.defense = null;
    state.nominated = null;
    state.voteHeld = false;
    if (payload.reveal) {
      captureReveal(payload);
    }
    if (isFinished()) {
      state.endPending = true;
      state.endRevealed = false;
    }


    const message = killedName
      ? (killedName === "你" ? "天亮时，你没有下楼。" : `天亮时，${killedName} 没有下楼。`)
      : ((result && result.message) || "天亮了，雪地上多了一行脚印。");
    if (killedName) {
      state.lastKilledName = killedName;
    } else {
      state.lastKilledName = "";
    }
    showReport(message, killedName ? "warn" : "info");
    pushLocalEvent({
      type: "night",
      day: nightDay,
      killed: killedActualId ? { id: killedActualId, name: killedName } : null,
      message,
    });

    render();
  }

  function voteDisplayName(id, provided) {
    if (id && id === youId()) {
      return "你";
    }
    const player = findPlayer(id);
    if (player) {
      return displayName(player);
    }
    if (provided) {
      const byName = players().find((item) => item.name === provided);
      return byName ? displayName(byName) : provided;
    }
    return id || "";
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
          const targetName = voteDisplayName(targetId, String(vote.target_name || vote.targetName || ""));
          return {
            voterId,
            voterName: voteDisplayName(voterId, String(vote.voter_name || vote.voterName || "")),
            targetId,
            targetName,
            reason: sanitizeReason(vote.reason || vote.why || vote.rationale || "", targetName),
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
      if (state.game && player.id === youId()) {
        state.game.you_alive = false;
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
    if (phase === "runoff") {
      const pool = state.runoffCandidates
        .map((id) => findPlayer(id))
        .filter((player) => player && player.alive !== false);
      const target = randomOf(pool);
      if (!target) {
        throw new Error("加赛没有可投的候选。");
      }
      await doVote(target.id, "");
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
      if (state.endPending && !state.endRevealed) {
        state.endPending = false;
        state.endRevealed = true;
        render();
      } else {
        renderEnd();
      }
      return;
    }
    if (!youAlive()) {
      doAdvance();
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
    if (!state.game || state.busy) {
      return;
    }
    if (isFinished()) {
      if (state.endPending && !state.endRevealed) {
        state.endPending = false;
        state.endRevealed = true;
        render();
      }
      return;
    }
    if (!youAlive()) {
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
    if (phase === "runoff") {
      const target = runoffTarget();
      if (!target) {
        showToast("先选一个平票候选。", "warn");
        return;
      }
      runAction(() => doVote(target.id, ""));
      return;
    }
    if (phase === "night") {
      if (state.voteHeld) {
        state.voteHeld = false;
        render();
        return;
      }
      if (youRole() === "murderer") {
        const target = findPlayer(state.selectedId);
        if (!target) {
          showToast("先选一个目标。", "warn");
          return;
        }
        openConfirm(
          `今晚对「${displayName(target)}」动手？这一步不可撤回。`,
          "确认动手",
          () => {
            showNightTransition("熄灯了……", "雪光从窗缝里漏进来，楼板响了一下。", 6000);
            return doNight(target.id);
          },
        );
        return;
      }
      showNightTransition("熄灯了……", "你回到房里，听着走廊里的动静。", 6000);
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
    state.drawerTab = "public";
    state.confideOpen = false;
    state.confideReply = null;
    state.confideTargetId = null;
    state.confideUsedToday = 0;
    state.confideUsedTotal = 0;
    state.confideDay = 1;
    state.confideSnapshots = {};
    state.privateLog = [];
    state.localEvents = [];
    state.inspectOpen = false;
    state.inspectTargetId = null;
    state.inspectUsed = false;
    state.inspectResult = null;
    state.inspectAvailable = null;
    state.inspectReveal = false;
    state.inspectRevealed = false;
    state.ghostVoteAvailable = null;
    state.ghostVoteUsed = false;
    state.ghostTargetId = null;
    state.ghostVotes = [];
    state.ghostDismissed = false;
    state.advancing = false;
    state.lastKilledName = "";
    state.thresholdReduced = false;
    state.mockSpectateStep = 0;
    state.mockSpectateVotes = [];
    state.mockGhostVote = null;
    state.logQueue = [];
    state.spectateFeed = [];
    state.spectateFeedDay = 0;
    state.endYourResult = "";
    state.endKilledInfo = null;
    window.clearTimeout(state.logQueueTimer);
    state.logQueueTimer = 0;
    state.lastWordsAvailable = null;
    state.lastWordsProbed = false;
    state.lastWordsUsed = false;
    state.lastWordsText = "";
    state.runoffCandidates = [];
    state.runoffPickId = null;
    state.runoffStalemate = 0;
    state.speakLimitNotice = "";
    state.userScrolled = false;
    state.ignoreScroll = false;
    state.stickForce = false;

    state.voteHeld = false;
    state.endPending = false;
    state.endRevealed = false;
    state.mockLastVoteTie = false;
    state.mockSpectateStep = 0;
    state.mockSpectateVotes = [];
    state.mockGhostVote = null;
    $("confide-panel").classList.add("hidden");
    $("inspect-panel").classList.add("hidden");
    $("spectate-panel").classList.add("hidden");
    $("ghost-vote-panel").classList.add("hidden");
    $("runoff-panel").classList.add("hidden");
    $("last-words-form").classList.add("hidden");
    $("end-last-words-form").classList.add("hidden");
    $("speak-form").classList.remove("hidden");
    $("confide-input").value = "";
    $("last-words-input").value = "";
    $("end-last-words-input").value = "";
    $("speak-limit").classList.add("hidden");
    setDrawerTab("public");
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

  function mockEndingGame(kind) {
    const nameOfAgent = (id) => {
      if (id === "p0") {
        return "你";
      }
      const agent = MOCK_AGENTS.find((item) => item.id === id);
      return agent ? agent.name : id;
    };
    const config = {
      "end-lose": {
        youRole: "villager",
        youAlive: true,
        winner: "murderer",
        day: 4,
        dead: ["p1", "p3"],
        executed: "p1",
        killed: "p3",
        poisoned: "p4",
        murderer: "p5",
        finalMurderer: "p5",
        minion: "p2",
        message: "旅馆的门没有再开。凶手还站在桌边，剩下的人谁也不敢先动。",
      },
      "end-late-good": {
        youRole: "villager",
        youAlive: false,
        winner: "good",
        day: 4,
        dead: ["p0", "p2"],
        executed: "p5",
        killed: "p0",
        poisoned: "p2",
        murderer: "p5",
        finalMurderer: "p5",
        minion: "p3",
        message: "凶手被票了出去。雪停时，好人赢了——只是你已经看不到了。",
      },
      "end-win": {
        youRole: "villager",
        youAlive: true,
        winner: "good",
        day: 4,
        dead: ["p5", "p3"],
        executed: "p5",
        killed: "p3",
        poisoned: "p4",
        murderer: "p5",
        finalMurderer: "p5",
        minion: "p2",
        message: "老韩 被票了出去。牌翻开——正是他。天亮时，你还在桌边。",
      },
      "end-late-evil": {
        youRole: "murderer",
        youAlive: false,
        winner: "murderer",
        day: 4,
        dead: ["p0", "p1"],
        executed: "p0",
        killed: "p1",
        poisoned: "p2",
        murderer: "p0",
        finalMurderer: "p4",
        minion: "p4",
        message: "你被票了出去，可印章落在了陆明川手里。凶手还是赢了。",
        succession: [{ from_id: "p0", from_name: "你", to_id: "p4", to_name: "陆明川", day: 3 }],
      },
    }[kind];
    if (!config) {
      return false;
    }
    state.murdererId = config.finalMurderer;
    state.mockOriginalDemonId = config.murderer;
    state.murdererName = nameOfAgent(config.murderer);
    state.mockMinionId = config.minion;
    state.mockOriginalMinionId = config.minion;
    state.mockSuccession = (config.succession || []).slice();
    state.mockPoisonedId = config.poisoned;
    state.mockAftermath = [];
    state.revealInfo = null;
    state.revealName = "";
    state.endYourResult = "";
    state.endKilledInfo = null;
    const players = [
      { id: "p0", name: "你", public: "封山夜最后一位住客", alive: config.youAlive, is_you: true },
      ...MOCK_AGENTS.map((agent) => ({
        id: agent.id,
        name: agent.name,
        public: agent.public,
        alive: !config.dead.includes(agent.id),
        is_you: false,
      })),
    ];
    const you = {
      id: "p0",
      name: "你",
      role: config.youRole,
      private_info: config.youRole === "villager"
        ? ["你手上有几段对不上的时间。"]
        : ["刀在你手里，你知道这局该怎么收。"],
      teammates: config.youRole === "murderer" ? [nameOfAgent(config.minion)] : [],
    };
    const log = [
      { seq: 1, speaker_id: "__narration", speaker_name: "旁白", text: "暴雪封山，旅馆的门从外面锁死了。", day: 1 },
      { seq: 2, speaker_id: "p1", speaker_name: "沈玉兰", text: MOCK_OPENERS.p1, day: 1 },
      { seq: 3, speaker_id: "p2", speaker_name: "周砚青", text: MOCK_OPENERS.p2, day: 1 },
      { seq: 4, speaker_id: "p3", speaker_name: "阿蘅", text: MOCK_OPENERS.p3, day: 1 },
      { seq: 5, speaker_id: "p4", speaker_name: "陆明川", text: MOCK_OPENERS.p4, day: 1 },
      { seq: 6, speaker_id: "p5", speaker_name: "老韩", text: MOCK_OPENERS.p5, day: 1 },
      { seq: 7, speaker_id: "__narration", speaker_name: "旁白", text: `第 2 天，${nameOfAgent(config.executed)} 被投票处决。`, day: 2 },
      { seq: 8, speaker_id: "__narration", speaker_name: "旁白", text: `第 3 天，${nameOfAgent(config.killed)} 没有下楼。`, day: 3 },
      { seq: 9, speaker_id: "__narration", speaker_name: "旁白", text: config.message, day: config.day },
    ];
    const reveal = {
      murderer_id: config.murderer,
      murderer_name: nameOfAgent(config.murderer),
      final_murderer_id: config.finalMurderer,
      final_murderer_name: nameOfAgent(config.finalMurderer),
      minion_id: config.minion,
      minion_name: nameOfAgent(config.minion),
      poisoned_id: config.poisoned,
      poisoned_name: nameOfAgent(config.poisoned),
      killed_id: config.killed,
      killed_name: nameOfAgent(config.killed),
      executed_id: config.executed,
      executed_name: nameOfAgent(config.executed),
      succession: (config.succession || []).map((step) => ({ ...step })),
    };
    const game = {
      game_id: `mock-${Math.random().toString(36).slice(2, 8)}`,
      day: config.day,
      phase: "ended",
      players,
      you,
      public_log: log,
      dead: config.dead.slice(),
      message: config.message,
      winner: config.winner,
      reveal,
      you_alive: config.youAlive,
      day_history: [
        { day: 2, executed: { id: config.executed, name: nameOfAgent(config.executed) }, killed: null, note: "" },
        { day: 3, executed: null, killed: { id: config.killed, name: nameOfAgent(config.killed) }, note: "" },
      ],
      aftermath: [
        { day: 2, executed: { id: config.executed, name: nameOfAgent(config.executed) }, killed: null, note: "" },
        { day: 3, executed: null, killed: { id: config.killed, name: nameOfAgent(config.killed) }, note: "" },
      ],
    };
    startGame(game);
    state.endPending = true;
    state.endRevealed = false;
    render();
    return true;
  }

  function mockCreate() {
    if (mockEndingGame(state.mockCase)) {
      return;
    }
    const forcedVillager = [
      "you-die", "short", "short2", "execute", "execute3", "vote-you", "tie",
      "runoff", "runoff2", "inspect", "betray", "lastwords", "spectate",
      "succession", "minion", "poison",
    ].includes(state.mockCase);
    const youMurderer = state.mockCase === "murderer"
      ? true
      : (forcedVillager ? false : Math.random() < 0.38);
    const youMinion = state.mockCase === "minion";
    const isSpectate = state.mockCase === "spectate";
    const allowMinion = state.mockCase === ""
      || state.mockCase === "succession"
      || state.mockCase === "minion"
      || state.mockCase === "murderer";
    const murderer = youMurderer
      ? "p0"
      : (isSpectate ? "p5" : (state.mockCase ? "p5" : randomOf(MOCK_AGENTS).id));
    state.murdererId = murderer;
    state.mockOriginalDemonId = murderer;
    state.murdererName = murderer === "p0"
      ? "你"
      : ((MOCK_AGENTS.find((agent) => agent.id === murderer) || {}).name || "未知");
    let minionId = "";
    if (allowMinion) {
      if (youMinion) {
        minionId = "p0";
      } else if (state.mockCase === "succession") {
        minionId = "p4";
      } else {
        const pool = MOCK_AGENTS.filter((agent) => agent.id !== murderer);
        minionId = (randomOf(pool) || {}).id || "";
      }
    }
    state.mockMinionId = minionId;
    state.mockOriginalMinionId = minionId;
    state.mockSuccession = [];
    const goodPool = MOCK_AGENTS.filter((agent) => agent.id !== murderer && agent.id !== minionId);
    state.mockPoisonedId = (state.mockCase === "succession" || state.mockCase === "poison")
      ? "p2"
      : (state.mockCase === "" && goodPool.length ? randomOf(goodPool).id : "");
    state.mockWhisperDay = 1;
    state.revealInfo = null;
    state.revealName = "";
    state.mockVotesCast = 0;
    state.mockLastVoteTie = false;

    state.mockAftermath = [];
    state.runoffCandidates = [];
    state.runoffPickId = null;
    state.runoffStalemate = 0;
    state.ballotTargetId = null;
    state.ballotReason = "";
    state.mockSpectateStep = 0;
    state.mockSpectateVotes = [];
    state.mockGhostVote = null;
    state.logQueue = [];
    state.spectateFeed = [];
    state.spectateFeedDay = 0;
    state.endYourResult = "";
    state.endKilledInfo = null;
    window.clearTimeout(state.logQueueTimer);
    state.logQueueTimer = 0;
    state.ghostVoteUsed = false;
    state.ghostTargetId = null;
    state.ghostVotes = [];
    state.ghostDismissed = false;
    state.ghostVoteAvailable = null;
    state.thresholdReduced = false;
    state.lastKilledName = "";
    state.inspectReveal = false;
    state.inspectRevealed = false;

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

    const teammateName = (id) => (id === "p0"
      ? "你"
      : ((MOCK_AGENTS.find((agent) => agent.id === id) || {}).name || ""));
    const role = youMurderer ? "murderer" : (youMinion ? "minion" : "villager");
    const teammates = youMurderer && minionId
      ? [teammateName(minionId)]
      : (youMinion ? [teammateName(murderer)] : []);
    const you = {
      id: "p0",
      name: "你",
      role,
      private_info: youMurderer
        ? ["你袖中藏着一把裁纸刀。今晚得让一个人再也开不了口。", "先让他们互相怀疑，别让目光落到你身上。"]
        : (youMinion
          ? ["你不是恶魔，可你知道刀在谁手里。", "替那个人把话圆过去，别让人顺着线摸到你。"]
          : ["你半夜听见走廊里有人试门把手，却没看清那张脸。", "你不是凶手。可在这张桌上，清白也需要证据。"]),
      teammates,
    };

    const whisperPair = MOCK_AGENTS.slice(0, 2);
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
    log.push({
      seq: log.length + 1,
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: `${whisperPair[0].name} 和 ${whisperPair[1].name} 在廊下低声说了几句。`,
      day: 1,
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

  function mockEvilIds() {
    const ids = [state.murdererId];
    if (state.mockMinionId) {
      ids.push(state.mockMinionId);
    }
    return ids.filter(Boolean);
  }

  function mockPromoteMinion(day) {
    const minion = findPlayer(state.mockMinionId);
    if (!minion || minion.alive === false) {
      return false;
    }
    const demon = findPlayer(state.murdererId);
    const step = {
      from_id: state.murdererId,
      from_name: demon ? demon.name : state.murdererName,
      to_id: minion.id,
      to_name: minion.name,
      day: Number(day) || (state.game ? state.game.day : 1),
    };
    state.mockSuccession.push(step);
    state.murdererId = minion.id;
    state.murdererName = minion.name;
    state.mockMinionId = "";
    return true;
  }

  function mockMaybeWhisper() {
    if (!state.game || state.mockWhisperDay === state.game.day) {
      return;
    }
    const agents = mockAlive().filter((player) => !player.is_you);
    if (agents.length < 2) {
      return;
    }
    const pair = shuffle(agents).slice(0, 2);
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: `${pair[0].name} 和 ${pair[1].name} 在廊下低声说了几句。`,
      day: state.game.day,
    });
    state.mockWhisperDay = state.game.day;
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
    mockMaybeWhisper();
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

  function mockConfide(targetId, text) {
    const target = findPlayer(targetId);
    if (!target || target.is_you || target.alive === false) {
      throw new Error("那不在桌上了。");
    }
    const stanceRoll = Math.random();
    let stance = "evade";
    if (stanceRoll < 0.3) {
      stance = "accept";
    } else if (stanceRoll < 0.55) {
      stance = "refuse";
    } else if (stanceRoll < 0.82) {
      stance = "evade";
    } else {
      stance = "threaten";
    }
    if (state.mockCase === "betray") {
      stance = "accept";
    }
    let reply = randomOf(MOCK_CONFIDE_LINES[target.id] || MOCK_CONFIDE_FALLBACK);
    if (target.id === state.murdererId && Math.random() < 0.6) {
      reply = "…你问得有点多了。你自己那夜又在哪儿？";
      stance = "threaten";
    }
    const trust = Number(((Math.random() * 0.5) - 0.1).toFixed(2));
    const suspicion = Number(((Math.random() * 0.4) - 0.2).toFixed(2));
    const follow = Number(((Math.random() * 0.4) - 0.1).toFixed(2));
    const betrayed = state.mockCase === "betray"
      ? true
      : (stance === "accept" && Math.random() < 0.35);
    return {
      stance,
      reply,
      trust,
      suspicion,
      follow,
      betrayed,
      relative: true,
      public_line: `你与${target.name}低声说了几句。`,
    };
  }

  function mockInspect(targetId, reveal = false) {
    const target = findPlayer(targetId);
    if (!target || target.is_you || target.alive === false) {
      throw new Error("那不在桌上了。");
    }
    const murderer = target.id === state.murdererId;
    return {
      result: murderer ? "murderer" : "not_murderer",
      public_line: reveal ? `我查过${target.name}。` : "",
      remaining: 0,
      revealed: Boolean(reveal),
    };
  }

  function mockNominate(targetId) {
    mockMaybeWhisper();
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
    const executeAll = (mode === "execute" && firstRound)
      || (mode === "succession" && (firstRound || state.mockVotesCast === 1));
    const executeThree = mode === "execute3" && firstRound;
    const voteYouOut = mode === "vote-you" && firstRound;
    const shortVote = (mode === "short" || mode === "short2" || mode === "you-die") && firstRound;
    const tieCase = mode === "tie" && firstRound;
    const spectateTie = mode === "spectate" && firstRound;
    const runoffCase = mode === "runoff" || mode === "runoff2";
    const runoffTie = runoffCase && firstRound;
    const runoffAgain = mode === "runoff2" && state.mockVotesCast === 1;
    let threshold = Math.floor(alive.length / 2) + 1;
    if (state.runoffStalemate >= 2) {
      threshold = Math.max(1, threshold - 1);
      state.thresholdReduced = true;
    }
    const others = alive.filter((player) => player.id !== target.id && player.id !== youId());
    const votes = [];
    const me = youPlayer();

    agents.forEach((voter, index) => {
      let chosen = target;
      if (voteYouOut) {
        chosen = index < 4 ? (me || target) : (others[index % others.length] || target);
      } else if (executeThree) {
        chosen = index < 3 ? target : (others[index % others.length] || target);
      } else if (executeAll) {
        chosen = target;
      } else if (shortVote) {
        if (voter.id === target.id) {
          chosen = others.find((player) => player.id !== voter.id) || target;
        } else if (index <= 1) {
          chosen = target;
        } else {
          const pool = others.filter((player) => player.id !== voter.id);
          chosen = pool[(index + 1) % Math.max(1, pool.length)] || target;
        }
      } else if (runoffTie || runoffAgain) {
        const rival = others[0] || target;
        if (voter.id === target.id) {
          chosen = rival;
        } else {
          chosen = (index % 2 === 0) ? target : rival;
        }
      } else if (tieCase || spectateTie) {
        const rival = others[0] || target;
        if (voter.id === target.id) {
          chosen = rival;
        } else {
          chosen = index >= 2 ? rival : target;
        }
      } else if (voter.id === state.murdererId) {
        const safe = alive.filter((player) => player.id !== voter.id && player.id !== target.id);
        chosen = randomOf(safe.length ? safe : alive.filter((player) => player.id !== voter.id)) || target;
      } else if (Math.random() > 0.7) {
        const pool = alive.filter((player) => player.id !== voter.id && player.id !== target.id);
        chosen = randomOf(pool) || target;
      }
      if (chosen.id === voter.id) {
        chosen = randomOf(alive.filter((player) => player.id !== voter.id)) || chosen;
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
    const topCount = ranking.length ? ranking[0][1] : 0;
    const rawTied = ranking.length > 1 && ranking[1][1] === topCount;
    const tied = runoffTie || runoffAgain ? true : rawTied;
    const executedId = !tied && ranking.length && topCount >= threshold ? ranking[0][0] : "";
    const executedName = executedId ? playerName(executedId) : "";
    if (executedId) {
      markMockDead(executedId);
    }
    state.mockVotesCast += 1;

    const demonBefore = state.murdererId;
    let winner = null;
    let succeeded = false;
    if (executedId && executedId === demonBefore) {
      const minion = findPlayer(state.mockMinionId);
      if (minion && minion.alive !== false && minion.id !== executedId) {
        succeeded = mockPromoteMinion(state.game.day);
      } else {
        winner = "villagers";
      }
    } else if (executedId && executedId === state.mockMinionId) {
      state.mockMinionId = "";
    }
    const murderer = findPlayer(state.murdererId);
    if (!winner && murderer && murderer.alive === false) {
      if (state.mockMinionId && mockPromoteMinion(state.game.day)) {
        succeeded = true;
      } else {
        winner = "villagers";
      }
    }
    if (!winner && murderer && murderer.alive !== false && mockAlive().length <= 2) {
      winner = "murderer";
    }
    if (!winner && state.game.day > 8) {
      winner = "murderer";
    }

    const day = state.game.day;
    const tallyRows = Object.entries(tally)
      .map(([id, count]) => ({ id, count }))
      .sort((left, right) => right.count - left.count);
    state.mockLastVoteTie = !executedId && tied;
    if (runoffTie || runoffAgain) {
      state.mockLastVoteTie = true;
    }
    if (executedId) {
      state.mockAftermath.push({
        day,
        executed: { id: executedId, name: executedName },
        killed: null,
        tie: false,
        tally: tallyRows,
        threshold,
        note: `${tally[executedId] || 0} / ${threshold} 票过门槛`,
      });
    } else {
      state.mockAftermath.push({
        day,
        executed: null,
        killed: null,
        tie: tied,
        tally: tallyRows,
        threshold,
        note: tied
          ? `平票，最高 ${topCount} 票，门槛 ${threshold} 票`
          : `最高 ${topCount} 票，未达 ${threshold} 票门槛`,
      });
    }

    const message = (succeeded && !winner)
      ? SUCCESSION_HINT
      : (executedId
        ? `${executedName} 被投票处决，天黑了。`
        : (tied
          ? "平票，今晚无人被处决，僵局一直拖到天亮。"
          : `最高 ${topCount} 票，未达 ${threshold} 票门槛。`));
    const runoffRival = others[0] || target;
    if (spectateTie) {
      const nightLog = state.game.public_log;
      const nightMessage = "平票，今晚无人被处决，天黑了。";
      nightLog.push({
        seq: nextSeq(nightLog),
        speaker_id: "__narration",
        speaker_name: "旁白",
        text: nightMessage,
        day: state.game.day,
      });
      state.mockLastVoteTie = true;
      return {
        votes,
        tally,
        threshold,
        executed: null,
        tie: true,
        phase: "night",
        message: nightMessage,
        public_log: nightLog.slice(),
        aftermath: state.mockAftermath.slice(),
      };
    }
    if (runoffTie || runoffAgain) {
      const runoffMessage = runoffTie
        ? "平票，进入加赛。只投平票的那几个人。"
        : "仍平票，僵局夜，今晚无人被处决。";
      const runoffLog = state.game.public_log;
      runoffLog.push({
        seq: nextSeq(runoffLog),
        speaker_id: "__narration",
        speaker_name: "旁白",
        text: runoffMessage,
        day: state.game.day,
      });
      return {
        votes,
        tally,
        threshold,
        executed: null,
        tie: true,
        runoff_candidates: [target.id, runoffRival.id],
        stalemate_count: runoffTie ? 1 : 2,
        phase: runoffTie ? "runoff" : "night",
        message: runoffMessage,
        public_log: runoffLog.slice(),
        aftermath: state.mockAftermath.slice(),
      };
    }
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
      tie: !executedId && tied,
      winner,
      succession: succeeded ? state.mockSuccession.slice() : null,
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
    const originalId = state.mockOriginalDemonId || state.murdererId;
    const original = findPlayer(originalId);
    const current = findPlayer(state.murdererId);
    const minion = findPlayer(state.mockOriginalMinionId);
    const poisoned = findPlayer(state.mockPoisonedId);
    const killedRow = [...state.mockAftermath].reverse().find((row) => row && row.killed);
    const executedRows = [...state.mockAftermath].reverse().filter((row) => row && row.executed);
    const killed = killedRow ? killedRow.killed : null;
    const executed = executedRows.length ? executedRows[0].executed : null;
    return {
      murderer_id: originalId,
      murderer_name: original ? original.name : state.murdererName,
      final_murderer_id: state.murdererId,
      final_murderer_name: current ? current.name : state.murdererName,
      minion_id: state.mockOriginalMinionId,
      minion_name: minion ? minion.name : "",
      succession: state.mockSuccession.slice(),
      poisoned_id: state.mockPoisonedId,
      poisoned_name: poisoned ? poisoned.name : "",
      killed_id: killed && killed.id ? killed.id : "",
      killed_name: killed && killed.name ? killed.name : "",
      executed_id: executed && executed.id ? executed.id : "",
      executed_name: executed && executed.name ? executed.name : "",
    };
  }

  function mockNarration(text, day) {
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text,
      day: Number(day) || state.game.day,
    });
    return log;
  }

  function buildMockSpectateVotes(agents, scripted) {
    return agents.map((agent, index) => {
      const fallback = agents[(index + 1) % agents.length];
      const targetId = scripted[agent.id] || (fallback ? fallback.id : agent.id);
      const target = findPlayer(targetId) || fallback || agent;
      return {
        voter_id: agent.id,
        voter_name: agent.name,
        target_id: target.id,
        target_name: target.name,
        reason: randomOf(MOCK_VOTE_REASONS).replace("{target}", target.name),
      };
    });
  }

  function mockGhostVote(targetId) {
    const target = findPlayer(targetId);
    if (!target || target.alive === false || target.is_you) {
      throw new Error("那不在桌上了。");
    }
    if (state.ghostVoteUsed) {
      throw new Error("亡者票已经用过了。");
    }
    const vote = {
      voter_id: youId(),
      voter_name: "你（亡者）",
      target_id: target.id,
      target_name: target.name,
      reason: "最后一票。",
    };
    state.mockGhostVote = vote;
    const votes = state.mockSpectateVotes.concat(vote);
    const tally = tallyFromVotes(normalizeVotes(votes));
    const threshold = Math.floor(mockAlive().length / 2) + 1;
    const log = mockNarration(`一只苍白的手把最后一票压在 ${target.name} 面前。`);
    return {
      day: state.game.day,
      phase: "defense",
      votes,
      tally,
      threshold,
      executed: null,
      tie: false,
      winner: null,
      ghost_vote_available: false,
      message: "亡者票压进了票板。",
      public_log: log.slice(),
    };
  }

  function mockAdvance() {
    if (!state.game) {
      throw new Error("还没有开局。");
    }
    const phase = normalizePhase(state.game.phase);
    const votePhase = phase === "defense" || phase === "runoff";
    const day = phase === "night" ? (state.game.day || 1) + 1 : (state.game.day || 1);
    state.game.day = day;
    mockMaybeWhisper();
    state.mockSpectateStep += 1;
    const step = state.mockSpectateStep;

    if (!votePhase) {
      const alive = mockAlive();
      const agents = alive.filter((player) => !player.is_you);
      const log = state.game.public_log;
      const fresh = [];
      const speakerCount = Math.min(4, agents.length);
      for (let index = 0; index < speakerCount; index += 1) {
        const speaker = agents[index];
        const entry = {
          seq: nextSeq(log),
          speaker_id: speaker.id,
          speaker_name: speaker.name,
          text: mockLine(speaker),
          day,
        };
        log.push(entry);
        fresh.push(entry);
      }
      const target = randomOf(agents.filter((player) => player.id !== state.murdererId))
        || randomOf(agents);
      let defense = null;
      if (target) {
        const text = MOCK_DEFENSE_LINES[target.id] || "该说的我都说过了。再问，我也只有这句话。";
        defense = { speaker_id: target.id, speaker_name: target.name, text };
        const nomination = {
          seq: nextSeq(log),
          speaker_id: "__narration",
          speaker_name: "旁白",
          text: `第 ${day} 天，${target.name} 被提上桌。先听自辩。`,
          day,
        };
        const defenseEntry = {
          seq: nextSeq(log),
          speaker_id: target.id,
          speaker_name: target.name,
          text,
          day,
        };
        log.push(nomination, defenseEntry);
        fresh.push(nomination, defenseEntry);
        state.nominated = { id: target.id, name: target.name };
        state.ballotTargetId = target.id;
      }
      state.mockSpectateVotes = buildMockSpectateVotes(agents, {
        p1: "p5", p2: "p5", p3: "p1", p4: "p2", p5: "p1",
      });
      const threshold = Math.floor(mockAlive().length / 2) + 1;
      return {
        day,
        phase: "defense",
        target: target ? { id: target.id, name: target.name } : null,
        defense,
        votes: [],
        tally: {},
        threshold,
        executed: null,
        tie: false,
        winner: null,
        ghost_vote_available: !state.ghostVoteUsed,
        message: target ? `${target.name} 被提名。先听自辩。` : "桌上重新落票。",
        public_log: log.slice(),
        new_entries: fresh,
      };
    }

    let votes = state.mockSpectateVotes.slice();
    if (!votes.length) {
      const agentsNow = mockAlive().filter((player) => !player.is_you);
      state.mockSpectateVotes = buildMockSpectateVotes(agentsNow, {
        p1: "p5", p2: "p5", p3: "p1", p4: "p2", p5: "p1",
      });
      votes = state.mockSpectateVotes.slice();
    }
    if (state.mockGhostVote && !votes.some((vote) => vote.voter_id === state.mockGhostVote.voter_id)) {
      votes.push(state.mockGhostVote);
    }
    const tally = tallyFromVotes(normalizeVotes(votes));
    const threshold = Math.floor(mockAlive().length / 2) + 1;
    const top = tally[0] || { id: "", count: 0 };
    const tieTop = tally.length > 1 && tally[1].count === top.count;
    let executedId = (!tieTop && top.id && top.count >= threshold) ? top.id : "";
    if (!executedId && state.mockGhostVote) {
      const murdererAlive = findPlayer(state.murdererId);
      if (murdererAlive && murdererAlive.alive !== false) {
        executedId = murdererAlive.id;
      }
    }
    if (!executedId && step >= 3) {
      const murdererAlive = findPlayer(state.murdererId);
      if (murdererAlive && murdererAlive.alive !== false) {
        executedId = murdererAlive.id;
      }
    }

    if (!executedId) {
      const pool = mockAlive().filter((player) => player.id !== state.murdererId && !player.is_you);
      const victim = randomOf(pool);
      if (victim) {
        markMockDead(victim.id);
      }
      state.thresholdReduced = true;
      const message = `最高 ${top.count} 票，未达 ${threshold} 票门槛；天亮时，${victim ? victim.name : "又一个人"} 没有下楼。`;
      const log = mockNarration(message, day);
      return {
        day,
        phase: "spectating",
        votes,
        tally,
        threshold,
        executed: null,
        tie: true,
        killed: victim ? { id: victim.id, name: victim.name } : null,
        winner: null,
        ghost_vote_available: !state.ghostVoteUsed,
        threshold_reduced: true,
        message,
        public_log: log.slice(),
      };
    }

    const executed = findPlayer(executedId);
    markMockDead(executedId);
    const executedName = executed ? executed.name : playerName(executedId);
    const winner = executedId === state.murdererId ? "villagers" : null;
    const message = winner
      ? `${executedName} 被处决。牌翻开——正是他。天亮了，旅馆的门开了。`
      : `${executedName} 被处决，可牌翻过来不对。`;
    const log = mockNarration(message, day);
    return {
      day,
      phase: winner ? "ended" : "spectating",
      votes,
      tally,
      threshold,
      executed: { id: executedId, name: executedName },
      tie: false,
      winner,
      reveal: winner ? mockReveal() : null,
      ghost_vote_available: false,
      message,
      public_log: log.slice(),
    };
  }

  function mockNight(targetId) {
    const youMurderer = state.murdererId === "p0";
    const forceYouDie = state.mockCase === "you-die" || state.mockCase === "spectate";
    const forceAgentDie = (state.mockCase === "short" || state.mockCase === "short2"
      || state.mockCase === "succession") && !youMurderer;
    let killedId = "";
    let killedName = "";
    const murderer = findPlayer(state.murdererId);

    if (murderer && murderer.alive !== false) {
      if (youMurderer) {
        const target = findPlayer(targetId);
        if (!target || target.alive === false || target.is_you) {
          throw new Error("请选择一名在场的目标。");
        }
        if (target.id === state.mockMinionId) {
          throw new Error("那是替你守秘密的人。");
        }
        killedId = target.id;
        killedName = target.name;
      } else {
        const evil = mockEvilIds();
        const pool = mockAlive().filter((player) => !evil.includes(player.id));
        const youTicket = pool.find((player) => player.is_you);
        const agentPool = pool.filter((player) => !player.is_you);
        let victim = null;
        if (forceYouDie && youTicket) {
          victim = youTicket;
        } else if (forceAgentDie && agentPool.length) {
          victim = randomOf(agentPool);
        } else {
          victim = youTicket && Math.random() < 0.4 ? youTicket : randomOf(pool);
        }
        if (victim) {
          killedId = victim.id;
          killedName = victim.name;
        }
      }
    }
    if (!killedId && murderer && murderer.alive !== false) {
      const evil = mockEvilIds();
      const victim = randomOf(mockAlive().filter((player) => !evil.includes(player.id)));
      if (victim) {
        killedId = victim.id;
        killedName = victim.name;
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
          tie: false,
          tally: [],
          threshold: 0,
          note: `${killedName}夜里没有下楼`,
        });
      }
    }

    let murdererAfter = findPlayer(state.murdererId);
    const aliveAfter = mockAlive().length;
    let winner = null;
    let succeededNight = false;
    if (murdererAfter && murdererAfter.alive === false) {
      if (state.mockMinionId && mockPromoteMinion(state.game.day)) {
        succeededNight = true;
        murdererAfter = findPlayer(state.murdererId);
      } else {
        winner = "villagers";
      }
    }
    if (!winner && murdererAfter && murdererAfter.alive !== false && aliveAfter <= 2) {
      winner = "murderer";
    }
    if (!winner && state.game.day > 8) {
      winner = "murderer";
    }
    const spectating = !winner && killedId === youId();

    const night = state.game.day;
    const day = winner ? night : night + 1;
    const phase = winner ? "ended" : (spectating ? "spectating" : "discussion");
    const message = killedId
      ? `天亮时，${killedName} 没有下楼。`
      : "天亮时，雪地上多了一行脚印。";
    const log = state.game.public_log;
    log.push({
      seq: nextSeq(log),
      speaker_id: "__narration",
      speaker_name: "旁白",
      text: message,
      day: night,
    });
    state.game.day = day;
    if (!winner) {
      mockMaybeWhisper();
    }
    state.mockLastVoteTie = false;
    if (spectating) {
      state.ghostVoteAvailable = state.ghostVoteUsed ? false : true;
    }
    return {
      killed: killedId ? { id: killedId, name: killedName } : null,
      aftermath: state.mockAftermath.slice(),
      day,
      phase,
      winner,
      succession: succeededNight ? state.mockSuccession.slice() : null,
      reveal: winner ? mockReveal() : null,
      message,
      public_log: log.slice(),
      ghost_vote_available: spectating ? true : (winner ? false : undefined),
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
    if (state.game && id === youId()) {
      state.game.you_alive = false;
    }
  }

  boot();
})();