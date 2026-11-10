'use strict';
/**
 * CPD Hunter — deterministic personalized shortlist (Sprint 2D).
 * Browser-local only. No network. No AI ranking.
 */

const RECO_MAX = 5;

/** Mirror My Progress / tracker requirements — do not invent HKIE numbers. */
const CORP_REQ = { total: 30, DSTM: 5, GPM: 5, 'H&S': 3, OTM: 0, selfCap: 10 };
const TRAINEE_REQ = { total: 45, DSTM: 0, GPM: 18, 'H&S': 18, OTM: 18, selfCap: 0 };

function getEventMode() {
  if (typeof CPDEventMode !== 'undefined' && CPDEventMode) return CPDEventMode;
  if (typeof require === 'function') {
    try {
      return require('./event_mode');
    } catch (err) {
      return null;
    }
  }
  return null;
}

function getRequirements(memberType) {
  return memberType === 'trainee' ? Object.assign({}, TRAINEE_REQ) : Object.assign({}, CORP_REQ);
}

/**
 * @param {{ memberType?: string, logs?: Array, year: string|number }} opts
 * @returns {{ req, logged, deficit, memberType, year }}
 */
function getDeficits(opts) {
  const memberType = opts && opts.memberType === 'trainee' ? 'trainee' : 'corp';
  const year = String((opts && opts.year) || '').slice(0, 4);
  const req = getRequirements(memberType);
  const logs = Array.isArray(opts && opts.logs) ? opts.logs : [];
  const yearLogs = year
    ? logs.filter((l) => l && typeof l.date === 'string' && l.date.startsWith(year))
    : logs.slice();
  // Trainee H&S/OTM/GPM ≥18 are training-period totals; no start date → all-time logs proxy.
  const catLogs = memberType === 'trainee' ? logs.slice() : yearLogs;
  const byCat = (c) =>
    catLogs.filter((l) => l.cat === c).reduce((s, l) => s + (Number(l.hrs) || 0), 0);
  const self = yearLogs.filter((l) => l.mode === 'Self-study').reduce((s, l) => s + (Number(l.hrs) || 0), 0);
  const struct = yearLogs.filter((l) => l.mode !== 'Self-study').reduce((s, l) => s + (Number(l.hrs) || 0), 0);
  const totalLogged =
    memberType === 'trainee' ? struct : struct + Math.min(self, req.selfCap);
  const logged = {
    DSTM: byCat('DSTM'),
    OTM: byCat('OTM'),
    GPM: byCat('GPM'),
    'H&S': byCat('H&S'),
    total: totalLogged
  };
  const deficit = {};
  ['DSTM', 'OTM', 'GPM', 'H&S', 'total'].forEach((k) => {
    deficit[k] = Math.max(0, (req[k] || 0) - (logged[k] || 0));
  });
  return { req, logged, deficit, memberType, year };
}

/** Same DSTM/OTM derivation as index.html catOf — related list must be caller-trusted. */
function classifyEvent(e, discipline, related) {
  const rel = Array.isArray(related) ? related : [];
  if (!e || typeof e !== 'object') return { cat: 'OTM', discMatch: null, why: '' };
  if (e.type === 'H&S') return { cat: 'H&S', discMatch: null, why: '' };
  if (e.type === 'GPM') return { cat: 'GPM', discMatch: null, why: '' };
  const d = (e.disc || ['General']).filter((x) => x !== 'General');
  if (!discipline) return { cat: 'OTM', discMatch: null, why: '未設定學科' };
  if (d.includes(discipline)) return { cat: 'DSTM', discMatch: 'primary', why: '' };
  const hit = d.find((x) => rel.includes(x));
  if (hit) return { cat: 'DSTM', discMatch: 'related', why: hit };
  return { cat: 'OTM', discMatch: null, why: '' };
}

function hasConfirmedDestination(reg) {
  return !!(reg && typeof reg.destination === 'string' && reg.destination.trim());
}

/** Mirror registration.js gformCanPrefill without importing it. */
function hasGFormSafePrefill(reg) {
  if (!reg || reg.mechanism !== 'GOOGLE_FORMS' || reg.status !== 'OPEN') return false;
  const fields = Array.isArray(reg.fields) ? reg.fields : [];
  return fields.some((f) => f && f.safePrefill && f.profileField && f.entryId);
}

function addDays(isoDate, n) {
  const t = Date.parse(isoDate + 'T00:00:00Z');
  if (!Number.isFinite(t)) return isoDate;
  const d = new Date(t + n * 86400000);
  return d.toISOString().slice(0, 10);
}

/**
 * Score one future event. Returns null if excluded.
 * Does not mutate `e`.
 *
 * @param {object} e raw or enriched event
 * @param {object} ctx
 *   discipline, related, deficits (from getDeficits), today (YYYY-MM-DD HKT),
 *   regState: { [eventId]: { state } } or getter function
 */
function scoreEvent(e, ctx) {
  if (!e || typeof e !== 'object') return null;
  const today = (ctx && ctx.today) || '1970-01-01';
  const discipline = (ctx && ctx.discipline) || null;
  const related = (ctx && ctx.related) || [];
  const deficits = (ctx && ctx.deficits) || getDeficits({ memberType: 'corp', logs: [], year: today.slice(0, 4) });
  const deficit = deficits.deficit || {};

  // DATE — past / already started
  if (!e.date || e.date < today) return null;

  // Explicit paid — do not recommend
  if (e.free === false) return null;

  const reg = e.registration && typeof e.registration === 'object' ? e.registration : null;
  if (reg && reg.status === 'CLOSED') return null;

  let regState = null;
  if (typeof ctx.getRegState === 'function') {
    regState = ctx.getRegState(e.id);
  } else if (ctx.regState && e.id != null) {
    regState = ctx.regState[e.id] || null;
  }
  const st = regState && regState.state ? regState.state : regState;
  if (st === 'registered_manual') return null;
  if (st === 'cancelled') return null;

  const modeApi = getEventMode();
  if (ctx && Array.isArray(ctx.allowedModes)) {
    if (!ctx.allowedModes.length) return null;
    if (modeApi && !modeApi.matches(e, ctx.allowedModes)) return null;
  }

  const cls = classifyEvent(e, discipline, related);
  const cat = cls.cat;
  let score = 0;
  const reasons = [];
  const flags = {
    cat,
    discMatch: cls.discMatch,
    categoryDeficit: 0,
    closesDeficit: false,
    free: e.free === true,
    online: e.online === true,
    hoursKind: !e.hrs ? 'unknown' : e.hrs_est ? 'estimated' : 'official',
    hrs: e.hrs || null,
    hasDestination: hasConfirmedDestination(reg),
    hasGFormPrefill: hasGFormSafePrefill(reg),
    opened: st === 'opened',
    soon: false
  };

  // CATEGORY DEFICIT
  const catDef = Number(deficit[cat]) || 0;
  flags.categoryDeficit = catDef;
  if (catDef > 0) {
    score += 40;
    reasons.push({
      code: 'cat_deficit',
      text: '你今年仲差 ' + catDef + ' 小時 ' + cat,
      detail: cat + ' 類別仲差 ' + catDef + ' 小時（最低要求）'
    });
    const hrs = Number(e.hrs) || 0;
    if (hrs > 0 && hrs >= catDef) {
      score += 10;
      flags.closesDeficit = true;
      reasons.push({
        code: 'closes_deficit',
        text: '完成呢個活動後可以補足 ' + cat + ' 最低要求',
        detail: '活動時數 ' + hrs + 'h ≥ ' + cat + ' deficit ' + catDef + 'h'
      });
    }
  }

  // DISCIPLINE (Technical only — H&S/GPM have discMatch null)
  if (cls.discMatch === 'primary') {
    score += 30;
    reasons.push({
      code: 'disc_primary',
      text: '符合你嘅 ' + discipline + ' discipline',
      detail: '技術活動匹配主要學科 ' + discipline
    });
  } else if (cls.discMatch === 'related') {
    score += 15;
    const relName = cls.why || '相關界別';
    reasons.push({
      code: 'disc_related',
      text: '符合相關界別（' + relName + '）',
      detail: '技術活動匹配已認可相關界別 ' + relName
    });
  }

  // FREE
  if (e.free === true) {
    score += 15;
    reasons.push({
      code: 'free',
      text: e.online === true ? '免費網上活動' : '免費',
      detail: 'free === true'
    });
  }

  // ATTENDANCE MODE — weights from CPDEventMode.scoreBonus only (25 / 18 / 0 / -3)
  const mode = modeApi ? modeApi.modeOf(e) : null;
  const modeBonus = modeApi ? modeApi.scoreBonus(e) : 0;
  flags.mode = mode;
  if (modeApi) {
    score += modeBonus;
    if (mode === 'ONLINE') {
      reasons.push({ code: 'mode_online', text: '網上活動', detail: 'mode ONLINE' });
    } else if (mode === 'HYBRID') {
      reasons.push({ code: 'mode_hybrid', text: '混合模式，可網上參與', detail: 'mode HYBRID' });
    } else if (mode === 'FACE_TO_FACE') {
      reasons.push({ code: 'mode_face', text: '面授活動', detail: 'mode FACE_TO_FACE' });
    } else {
      reasons.push({ code: 'mode_unknown', text: '活動形式未確認', detail: 'mode UNKNOWN' });
    }
  }

  // CPD HOURS
  if (e.hrs && !e.hrs_est) {
    score += 10;
    reasons.push({
      code: 'hrs_official',
      text: '有官方 ' + e.hrs + ' CPD hours',
      detail: '主辦方註明時數（非估算）'
    });
  } else if (e.hrs && e.hrs_est) {
    score += 5;
    reasons.push({
      code: 'hrs_estimated',
      text: '估算 ' + e.hrs + ' 小時',
      detail: '按活動時長估算，未經主辦方確認'
    });
  }

  // REGISTRATION bonuses (CLOSED already excluded)
  if (hasConfirmedDestination(reg)) {
    score += 5;
    reasons.push({
      code: 'reg_dest',
      text: '可以直接準備報名',
      detail: '已確認報名連結（registration.destination）'
    });
  }
  if (hasGFormSafePrefill(reg)) {
    score += 5;
    reasons.push({
      code: 'gform_prefill',
      text: 'Google Forms 可預填基本資料',
      detail: 'Google Forms OPEN 且有 safePrefill 欄位'
    });
  }

  // opened penalty
  if (st === 'opened') {
    score -= 5;
    reasons.push({
      code: 'opened',
      text: '你已開啟過報名頁',
      detail: '本機狀態 opened（−5）',
      quiet: true
    });
  }

  // DATE within 7 days
  const limit = addDays(today, 7);
  if (e.date <= limit) {
    score += 5;
    flags.soon = true;
    reasons.push({
      code: 'soon',
      text: '未來 7 日內',
      detail: '活動日期 ' + e.date
    });
  }

  // Visible reasons for card (skip quiet duplicates)
  const displayReasons = reasons.filter((r) => !r.quiet).map((r) => r.text);

  return {
    id: e.id,
    score,
    cat,
    discMatch: cls.discMatch,
    reasons: displayReasons,
    reasonItems: reasons,
    flags,
    event: e
  };
}

function getRecommendationReasons(scored) {
  if (!scored) return [];
  if (Array.isArray(scored.reasonItems)) return scored.reasonItems.slice();
  return (scored.reasons || []).map((t) => ({ code: '', text: t, detail: t }));
}

/**
 * Rank future events. Stable tie-break: score desc, date asc, id asc.
 * Never mutates input event objects.
 * @returns {{ ranked, emptyKind, deficits, max }}
 */
function rankEvents(events, ctx, max) {
  const limit = max == null ? RECO_MAX : Math.max(0, max | 0);
  const list = Array.isArray(events) ? events : [];
  const discipline = ctx && ctx.discipline;
  const today = (ctx && ctx.today) || '1970-01-01';
  const year = today.slice(0, 4);
  const deficits =
    (ctx && ctx.deficits) ||
    getDeficits({
      memberType: (ctx && ctx.memberType) || 'corp',
      logs: (ctx && ctx.logs) || [],
      year
    });

  const futureExist = list.some((e) => e && e.date && e.date >= today);
  if (!futureExist) {
    return { ranked: [], emptyKind: 'no_events', deficits, max: limit };
  }
  if (!discipline) {
    return { ranked: [], emptyKind: 'no_discipline', deficits, max: limit };
  }

  const scoreCtx = Object.assign({}, ctx, { deficits, today, discipline });
  const scored = [];
  for (let i = 0; i < list.length; i++) {
    const e = list[i];
    // freeze identity check later — work on shallow copy of refs only
    const s = scoreEvent(e, scoreCtx);
    if (s) scored.push(s);
  }

  scored.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const da = (a.event && a.event.date) || '';
    const db = (b.event && b.event.date) || '';
    if (da !== db) return da < db ? -1 : 1;
    const ia = String((a.event && a.event.id) || a.id || '');
    const ib = String((b.event && b.event.id) || b.id || '');
    if (ia !== ib) return ia < ib ? -1 : 1;
    return 0;
  });

  const catOutstanding =
    (deficits.deficit['H&S'] || 0) > 0 ||
    (deficits.deficit.GPM || 0) > 0 ||
    (deficits.deficit.DSTM || 0) > 0 ||
    (deficits.deficit.OTM || 0) > 0;

  // Prefer events that actually help; drop pure zeros when nothing distinguishes them
  let usable = scored.filter((s) => s.score > 0);
  if (!usable.length) {
    return {
      ranked: [],
      emptyKind: catOutstanding ? 'none' : 'deficits_complete_none',
      deficits,
      max: limit
    };
  }

  const ranked = usable.slice(0, limit);
  const emptyKind = catOutstanding ? 'ok' : 'deficits_complete';
  return { ranked, emptyKind, deficits, max: limit };
}

function emptyStateMessage(kind) {
  if (kind === 'no_discipline') {
    return {
      title: '設定你嘅 HKIE discipline，就可以收到個人化 CPD 推薦。',
      action: '設定 discipline',
      actionKind: 'disc'
    };
  }
  if (kind === 'deficits_complete' || kind === 'deficits_complete_none') {
    return {
      title: '主要 CPD 類別要求暫時已達標。以下按 discipline、免費、online 同時數推薦。',
      action: null,
      actionKind: null
    };
  }
  if (kind === 'none') {
    return { title: '暫時冇合適推薦。', action: null, actionKind: null };
  }
  return null;
}

const _root =
  typeof globalThis !== 'undefined'
    ? globalThis
    : typeof window !== 'undefined'
      ? window
      : typeof global !== 'undefined'
        ? global
        : {};

_root.CPDRecommendations = {
  RECO_MAX,
  CORP_REQ,
  TRAINEE_REQ,
  getRequirements,
  getDeficits,
  classifyEvent,
  scoreEvent,
  rankEvents,
  getRecommendationReasons,
  emptyStateMessage,
  hasConfirmedDestination,
  hasGFormSafePrefill
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    RECO_MAX,
    CORP_REQ,
    TRAINEE_REQ,
    getRequirements,
    getDeficits,
    classifyEvent,
    scoreEvent,
    rankEvents,
    getRecommendationReasons,
    emptyStateMessage,
    hasConfirmedDestination,
    hasGFormSafePrefill
  };
}
