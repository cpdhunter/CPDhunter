// CPD Hunter Sprint 1 - local registration profile & state
// Profile and registration state are stored only in this browser (localStorage).
// Nothing is sent to any server.
// Hardened: schema v1 validation, state allowlist, import/export guards.
// Connected to index.html Prepare Registration (Google Forms partial prefill).

const PROFILE_KEY = "regProfile";
const REGSTATE_KEY = "regState";
const PROFILE_VERSION = 1;
const MAX_IMPORT_BYTES = 100 * 1024; // 100 KB (UTF-8)
const NOTE_LIMIT = 500;

const ALLOWED_FIELDS = [
  "title",
  "englishName",
  "chineseName",
  "email",
  "phone",
  "position",
  "organisation",
  "hkieNumber",
  "primaryDiscipline",
  "secondaryDiscipline",
  "preferredLanguage"
];

const FIELD_LIMITS = {
  title: 20,
  englishName: 150,
  chineseName: 150,
  email: 254,
  phone: 50,
  position: 150,
  organisation: 200,
  hkieNumber: 100,
  primaryDiscipline: 100,
  secondaryDiscipline: 100,
  preferredLanguage: 50
};

// Required for a complete profile. title is optional.
const REQUIRED = [
  "englishName",
  "email",
  "organisation",
  "position",
  "primaryDiscipline"
];

const VALID_REG_STATES = Object.freeze([
  "not_started",
  "opened",
  "registered_manual",
  "cancelled"
]);
const VALID_REG_STATE_SET = new Set(VALID_REG_STATES);

const UNSAFE_KEYS = new Set(["__proto__", "constructor", "prototype"]);

// Conservative email check: non-empty local, @, domain with a dot; no spaces.
const EMAIL_RE = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

function _stripControlChars(s) {
  // Remove C0 controls and DEL; ordinary spaces retained.
  return s.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "");
}

function _utf8ByteLength(str) {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(str).length;
  }
  // Minimal UTF-8 length fallback (BMP + surrogate pairs).
  let bytes = 0;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    if (c <= 0x7f) bytes += 1;
    else if (c <= 0x7ff) bytes += 2;
    else if (c >= 0xd800 && c <= 0xdbff) {
      bytes += 4;
      i++; // skip low surrogate
    } else bytes += 3;
  }
  return bytes;
}

function _isPlainObject(value) {
  // Realm-safe: avoid Object.prototype identity (breaks under Node vm contextification).
  // Accept JSON-like objects; reject arrays and other built-in tags.
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.prototype.toString.call(value) === "[object Object]";
}

function _isSafeKey(key) {
  const k = String(key);
  return k !== "" && !UNSAFE_KEYS.has(k);
}

/**
 * Sanitize one allowlisted field.
 * Returns { ok:true, value } or { ok:false, error:"type"|"too_long" }.
 * Oversized fields are REJECTED (not truncated). Invalid types REJECTED (not omitted).
 */
function _sanitizeField(name, value) {
  if (typeof value !== "string") return { ok: false, error: "type" };
  const limit = FIELD_LIMITS[name] || 200;
  if (value.length > limit) return { ok: false, error: "too_long" };
  return { ok: true, value: _stripControlChars(value) };
}

function isValidEmail(email) {
  if (typeof email !== "string") return false;
  const e = email.trim();
  if (!e || e.length > 254) return false;
  return EMAIL_RE.test(e);
}

/**
 * Build a clean schema-v1 profile object from an arbitrary input.
 * Policy: allowlist only; invalid field types REJECTED; oversized fields REJECTED;
 * unexpected keys dropped; control chars stripped; does not execute or render content.
 * Returns { ok:true, profile } or { ok:false, error }.
 */
function normalizeProfile(input, opts) {
  const requireComplete = !!(opts && opts.requireComplete);
  if (!_isPlainObject(input)) {
    return { ok: false, error: "invalid" };
  }
  if (input.version !== undefined && input.version !== PROFILE_VERSION) {
    return { ok: false, error: "version" };
  }

  const clean = { version: PROFILE_VERSION };
  for (const k of ALLOWED_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(input, k)) continue;
    const field = _sanitizeField(k, input[k]);
    if (!field.ok) return { ok: false, error: field.error };
    clean[k] = field.value;
  }

  if (clean.email !== undefined && clean.email.trim() !== "" && !isValidEmail(clean.email)) {
    return { ok: false, error: "email" };
  }

  if (requireComplete && !profileComplete(clean)) {
    return { ok: false, error: "incomplete" };
  }
  return { ok: true, profile: clean };
}

function loadProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!_isPlainObject(data)) return null;
    return data;
  } catch {
    return null;
  }
}

/**
 * Save a profile after sanitization.
 * Rejects invalid types, oversized fields, invalid email, and unsupported shape.
 * Incomplete drafts are allowed for local editing; import uses requireComplete.
 * Returns the saved profile, or null on rejection (storage unchanged on reject).
 * Failure semantics: falsy/null (does not throw).
 */
function saveProfile(p) {
  const result = normalizeProfile(p || {}, { requireComplete: false });
  if (!result.ok) return null;
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(result.profile));
  } catch {
    return null;
  }
  return result.profile;
}

/** Delete ONLY regProfile. Does not touch regState. */
function deleteProfile() {
  try {
    localStorage.removeItem(PROFILE_KEY);
  } catch {}
}

function profileComplete(p) {
  if (!p) return false;
  return REQUIRED.every(k => (p[k] || "").toString().trim());
}

/** Return export payload: registration profile only (no regState, events, secrets). */
function getExportProfile() {
  const p = loadProfile();
  if (!p) return null;
  const result = normalizeProfile(p, { requireComplete: false });
  if (!result.ok) return null;
  return result.profile;
}

function exportProfile() {
  const payload = getExportProfile();
  if (!payload) {
    if (typeof alert === "function") alert("\u5514\u8a3b\u518a\u6a94\u6848\u53ef\u532f\u51fa");
    return null;
  }
  const text = JSON.stringify(payload, null, 2);
  if (typeof Blob !== "undefined" && typeof document !== "undefined") {
    try {
      const blob = new Blob([text], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "cpd-hunter-registration-profile.json";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {}
  }
  return payload;
}

/**
 * Import a local JSON profile file.
 * - max 100 KB UTF-8 (declared size AND actual text bytes; defeats size=0 lies)
 * - valid JSON object only (arrays rejected)
 * - supported version required
 * - allowlist fields only; invalid types REJECTED
 * - oversized fields REJECTED (exact per-field char limits; no truncate)
 * - control chars sanitized
 * - incomplete required profile rejected
 * - never executes or renders imported content as HTML
 */
function importProfile(file) {
  return new Promise((resolve, reject) => {
    if (!file || typeof file !== "object") {
      reject(new Error("invalid"));
      return;
    }
    if (typeof file.size === "number" && file.size > MAX_IMPORT_BYTES) {
      reject(new Error("too_large"));
      return;
    }

    const finishWithText = text => {
      try {
        if (typeof text !== "string") throw new Error("invalid");
        // UTF-8 byte guard — enforces 100 KB even when file.size is 0 / missing / lying.
        if (_utf8ByteLength(text) > MAX_IMPORT_BYTES) throw new Error("too_large");
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          throw new Error("invalid");
        }
        if (!_isPlainObject(data)) {
          throw new Error("invalid");
        }
        if (data.version !== PROFILE_VERSION) {
          throw new Error("version");
        }
        const result = normalizeProfile(data, { requireComplete: true });
        if (!result.ok) throw new Error(result.error);
        if (!isValidEmail(result.profile.email || "")) {
          throw new Error("email");
        }
        try {
          localStorage.setItem(PROFILE_KEY, JSON.stringify(result.profile));
        } catch {
          throw new Error("storage");
        }
        resolve(result.profile);
      } catch (e) {
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    };

    // Prefer FileReader when available (browser); fall back to text()/sync content for tests.
    if (typeof FileReader !== "undefined") {
      const r = new FileReader();
      r.onload = () => finishWithText(r.result);
      r.onerror = () => reject(new Error("read"));
      try {
        r.readAsText(file);
      } catch (e) {
        reject(new Error("read"));
      }
      return;
    }
    if (typeof file.text === "function") {
      Promise.resolve(file.text())
        .then(finishWithText)
        .catch(() => reject(new Error("read")));
      return;
    }
    if (typeof file._content === "string") {
      finishWithText(file._content);
      return;
    }
    reject(new Error("read"));
  });
}

/**
 * Load regState map. Rejects arrays / non-plain roots; drops unsafe keys and bad entries.
 */
function loadRegState() {
  try {
    const raw = localStorage.getItem(REGSTATE_KEY);
    if (!raw) return {};
    const data = JSON.parse(raw);
    if (!_isPlainObject(data)) return {};
    const clean = {};
    for (const key of Object.keys(data)) {
      if (!_isSafeKey(key)) continue;
      const entry = data[key];
      if (!_isPlainObject(entry)) continue;
      const state = entry.state;
      if (!VALID_REG_STATE_SET.has(state)) continue;
      let note = "";
      if (typeof entry.note === "string") {
        note = _stripControlChars(entry.note).slice(0, NOTE_LIMIT);
      }
      const ts = typeof entry.ts === "string" ? entry.ts : "";
      clean[key] = { state, ts, note };
    }
    return clean;
  } catch {
    return {};
  }
}

/**
 * Persist regState map. Rejects arrays / non-plain objects; strips unsafe keys.
 * Returns true on success, false on rejection (storage unchanged).
 */
function saveRegState(s) {
  if (!_isPlainObject(s)) return false;
  const clean = {};
  for (const key of Object.keys(s)) {
    if (!_isSafeKey(key)) continue;
    const entry = s[key];
    if (!_isPlainObject(entry)) continue;
    if (!VALID_REG_STATE_SET.has(entry.state)) continue;
    let note = "";
    if (typeof entry.note === "string") {
      note = _stripControlChars(entry.note).slice(0, NOTE_LIMIT);
    }
    const ts = typeof entry.ts === "string" ? entry.ts : "";
    clean[key] = { state: entry.state, ts, note };
  }
  try {
    localStorage.setItem(REGSTATE_KEY, JSON.stringify(clean));
    return true;
  } catch {
    return false;
  }
}

/**
 * Set registration state for an event.
 * Only: not_started | opened | registered_manual | cancelled.
 * Rejects unsafe event ids (__proto__/constructor/prototype), invalid states,
 * and non-string notes (when provided). Note capped at 500 chars.
 */
function setRegState(eventId, state, note) {
  if (eventId === undefined || eventId === null) return false;
  const id = String(eventId);
  if (!_isSafeKey(id)) return false;
  if (!VALID_REG_STATE_SET.has(state)) return false;
  let n = "";
  if (note !== undefined && note !== null && note !== "") {
    if (typeof note !== "string") return false;
    if (note.length > NOTE_LIMIT) {
      n = _stripControlChars(note).slice(0, NOTE_LIMIT);
    } else {
      n = _stripControlChars(note);
    }
  }
  const all = loadRegState();
  all[id] = {
    state,
    ts: new Date().toISOString(),
    note: n
  };
  return saveRegState(all);
}

function getRegState(eventId) {
  if (eventId === undefined || eventId === null) return null;
  const id = String(eventId);
  if (!_isSafeKey(id)) return null;
  const all = loadRegState();
  return Object.prototype.hasOwnProperty.call(all, id) ? all[id] : null;
}

/** Clear ONLY registration-state history. Does not touch regProfile. */
function clearRegState() {
  try {
    localStorage.removeItem(REGSTATE_KEY);
  } catch {}
}

// ---- Google Forms partial-prefill (Sprint 2B2) ----
// Schema comes from scraped event.registration (non-personal).
// Profile values stay local; prefilled URL is built in memory only.
// No submit(), no formResponse POST, no CAPTCHA, no sign-in.

const GFORM_CONFIRM_MSG =
  "CPD Hunter will place selected profile values into a temporary Google Forms URL. The URL is opened directly on Google and may appear in your browser history. Consent and questionnaire answers will not be filled. Continue?";

const GFORM_SAFE_PROFILE_FIELDS = Object.freeze([
  "englishName",
  "chineseName",
  "email",
  "phone",
  "organisation",
  "position",
  "hkieNumber",
  "primaryDiscipline",
  "secondaryDiscipline"
]);

function _normGFormLabel(label) {
  if (!label) return "";
  return String(label)
    .toLowerCase()
    .replace(/[\u3000\s]+/g, " ")
    .replace(/[^\w\u4e00-\u9fff\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function _gformLabelHas(norm, phrases) {
  for (let i = 0; i < phrases.length; i++) {
    if (norm.indexOf(phrases[i]) !== -1) return true;
  }
  return false;
}

const _GFORM_BLOCK = [
  "consent", "privacy", "personal data provided", "declaration", "acknowledge",
  "i noted", "i agree", "marketing", "newsletter", "promotional",
  "are you a hkie member", "are you hkie member", "are you a member", "are you member", "member?",
  "attendance", "mode of", "passport number", "passport no", "travel document number", "room",
  "accommodation", "hotel", "dietary", "allergy", "running", "legal",
  "disclaimer", "assumption of risk", "emergency", "mainland mobile",
  "other name", "media consent", "photography", "first come",
  "priority will be given", "wish to apply", "course enrollment", "session ",
  "surname", "given name", "first name", "last name", "family name", "forename",
  "mr ms", "mr/ms", "ir/prof"
];

/**
 * Deterministic label → profile field (mirrors scraper/gforms.py).
 * Split name fields (surname/given) intentionally unmapped.
 */
function mapGFormLabel(label, typeCode) {
  const norm = _normGFormLabel(label);
  if (!norm) return null;
  if (norm === "title" || norm.indexOf("title ") === 0) return null;
  for (let i = 0; i < _GFORM_BLOCK.length; i++) {
    if (norm.indexOf(_GFORM_BLOCK[i]) !== -1) return null;
  }
  if (norm.indexOf("聲明") !== -1) return null;

  if (
    _gformLabelHas(norm, [
      "chinese name", "name in chinese", "name chinese", "中文姓名", "姓名 中文", "中文名"
    ]) || /name\s*\(.*chinese/.test(norm)
  ) {
    return "chineseName";
  }
  if (_gformLabelHas(norm, ["email address", "e mail", "email", "電郵", "電子郵件"])) {
    if (norm.indexOf("personal data") !== -1) return null;
    return "email";
  }
  if (
    _gformLabelHas(norm, [
      "mobile phone", "mobile number", "mobile no", "contact number",
      "contact phone", "telephone", "phone number", "mobile", "phone",
      "手提電話", "聯絡電話", "電話"
    ])
  ) {
    return "phone";
  }
  if (
    _gformLabelHas(norm, [
      "hkie membership", "hkie or iom3 membership", "membership no",
      "membership number", "member no", "會員編號"
    ]) ||
    norm.indexOf("please fill in your membership number") !== -1 ||
    /^membership no\b/.test(norm)
  ) {
    return "hkieNumber";
  }
  if (
    _gformLabelHas(norm, [
      "job title", "job position", "company position", "designation", "position", "職位"
    ])
  ) {
    return "position";
  }
  if (
    _gformLabelHas(norm, [
      "organisation", "organization", "company name", "company", "employer",
      "institution", "present employment", "公司", "機構", "僱主"
    ])
  ) {
    if (norm.indexOf("division") !== -1 && norm.indexOf("committee") !== -1) return null;
    if ((typeCode === 2 || typeCode === 4) && (norm === "organization" || norm === "organisation")) {
      return null;
    }
    return "organisation";
  }
  if (_gformLabelHas(norm, ["secondary discipline", "second discipline", "次要界別"])) {
    return "secondaryDiscipline";
  }
  if (
    _gformLabelHas(norm, ["engineering discipline", "discipline", "專業界別", "學科"]) ||
    /^division\b/.test(norm) ||
    norm.indexOf("division e g") !== -1 ||
    norm.indexOf("division eg") !== -1
  ) {
    if (norm.indexOf("committee") !== -1 || norm.indexOf("wish to apply") !== -1) return null;
    return "primaryDiscipline";
  }
  if (
    _gformLabelHas(norm, [
      "english full name", "english name", "name in english", "full name",
      "applicant name", "name english"
    ]) || /name\s*\(.*english/.test(norm)
  ) {
    if (norm.indexOf("institute") !== -1 || norm.indexOf("emergency") !== -1) return null;
    return "englishName";
  }
  if (norm === "name") return "englishName";
  return null;
}

/**
 * Resolve ambiguous duplicate profileField mappings: if two fields claim the
 * same profile field, neither is safe to prefill.
 */
function resolveGFormFieldMappings(fields) {
  const list = Array.isArray(fields) ? fields.map((f) => ({ ...f })) : [];
  const counts = Object.create(null);
  for (const f of list) {
    const pf = f && f.profileField;
    if (pf) counts[pf] = (counts[pf] || 0) + 1;
  }
  for (const f of list) {
    if (f && f.profileField && counts[f.profileField] > 1) {
      f.profileField = null;
      f.safePrefill = false;
    }
  }
  return list;
}

function getGFormRegistration(eventOrReg) {
  if (!eventOrReg || typeof eventOrReg !== "object") return null;
  const reg =
    eventOrReg.registration && typeof eventOrReg.registration === "object"
      ? eventOrReg.registration
      : eventOrReg.mechanism
        ? eventOrReg
        : null;
  if (!reg || reg.mechanism !== "GOOGLE_FORMS") return null;
  return reg;
}

function gformCanPrefill(reg) {
  const r = getGFormRegistration(reg);
  if (!r) return false;
  if (r.status !== "OPEN") return false;
  const fields = Array.isArray(r.fields) ? r.fields : [];
  return fields.some((f) => f && f.safePrefill && f.profileField && f.entryId);
}

function listGFormPrefillPlan(reg, profile) {
  const r = getGFormRegistration(reg);
  const prefill = [];
  const manual = [];
  if (!r) {
    return { prefill, manual, status: null };
  }
  const fields = Array.isArray(r.fields) ? r.fields : [];
  const p = profile && typeof profile === "object" ? profile : {};
  for (const f of fields) {
    if (!f || !f.entryId) continue;
    const label = typeof f.label === "string" ? f.label : f.entryId;
    const pf = f.profileField;
    const raw = pf && typeof p[pf] === "string" ? p[pf].trim() : "";
    let can = !!(f.safePrefill && pf && raw);
    if (can && (f.type === "RADIO" || f.type === "DROPDOWN")) {
      const opts = Array.isArray(f.options) ? f.options : [];
      can = opts.some((o) => String(o) === raw);
    }
    if (can && (f.type === "CHECKBOX" || f.type === "SECTION" || f.type === "PAGE")) {
      can = false;
    }
    if (can) prefill.push({ entryId: f.entryId, profileField: pf, label });
    else manual.push({ entryId: f.entryId, profileField: pf || null, label });
  }
  return { prefill, manual, status: r.status || null, requiresManualCompletion: true };
}

/**
 * Build a temporary prefilled viewform URL. Caller must not store/log/clipboard it.
 * Returns null if nothing to prefill.
 */
function buildGFormPrefillUrl(profile, registrationMeta) {
  const r = getGFormRegistration(registrationMeta);
  if (!r || r.status !== "OPEN") return null;
  const dest = typeof r.destination === "string" ? r.destination.trim() : "";
  if (!dest || dest.indexOf("https://docs.google.com/forms/") !== 0) return null;
  const plan = listGFormPrefillPlan(r, profile);
  if (!plan.prefill.length) return null;
  const params = ["usp=pp_url"];
  for (const item of plan.prefill) {
    const val = String(profile[item.profileField]).trim();
    if (!val) continue;
    const key = item.entryId.indexOf("entry.") === 0 ? item.entryId : "entry." + item.entryId;
    params.push(encodeURIComponent(key) + "=" + encodeURIComponent(val));
  }
  if (params.length <= 1) return null;
  const base = dest.split("?")[0].split("#")[0];
  return base + "?" + params.join("&");
}

/**
 * Confirm once, open prefilled Google Form, set local state to opened.
 * Never logs or persists the URL. Returns { ok, reason }.
 */
function openGFormPrefill(event, profile, confirmFn, openFn) {
  const r = getGFormRegistration(event);
  if (!r) return { ok: false, reason: "not_google_forms" };
  if (r.status === "CLOSED") return { ok: false, reason: "closed" };
  if (r.status !== "OPEN") return { ok: false, reason: "unavailable" };
  if (!profileComplete(profile)) return { ok: false, reason: "incomplete_profile" };
  const ask = typeof confirmFn === "function" ? confirmFn : confirm;
  if (!ask(GFORM_CONFIRM_MSG)) return { ok: false, reason: "cancelled" };
  let url = null;
  try {
    url = buildGFormPrefillUrl(profile, r);
  } catch {
    return { ok: false, reason: "build_failed" };
  }
  if (!url) return { ok: false, reason: "nothing_to_prefill" };
  const opener = typeof openFn === "function" ? openFn : window.open.bind(window);
  try {
    opener(url, "_blank", "noopener,noreferrer");
  } finally {
    url = null; // drop reference
  }
  const id = event && event.id != null ? String(event.id) : "";
  if (id && _isSafeKey(id)) setRegState(id, "opened", "");
  return { ok: true, reason: "opened" };
}

// Adapter: Google Forms only. No other mechanisms. Intentionally no submit().
const RegistrationAdapter = {
  canHandle(eventOrUrl) {
    if (typeof eventOrUrl === "string") {
      // URL-only: never claim handle without scraped schema.
      return false;
    }
    return gformCanPrefill(eventOrUrl);
  },
  inspect(event) {
    const r = getGFormRegistration(event);
    if (!r) return null;
    return {
      mechanism: "GOOGLE_FORMS",
      status: r.status,
      destination: r.destination,
      formId: r.formId,
      requiresManualCompletion: true,
      fieldCount: Array.isArray(r.fields) ? r.fields.length : 0
    };
  },
  matchFields(event, profile) {
    return listGFormPrefillPlan(event, profile).prefill;
  },
  getUnsupportedFields(event, profile) {
    return listGFormPrefillPlan(event, profile).manual;
  },
  buildPrefillUrl(profile, registrationMeta) {
    return buildGFormPrefillUrl(profile, registrationMeta);
  },
  openPrefill(event, profile, confirmFn, openFn) {
    return openGFormPrefill(event, profile, confirmFn, openFn);
  },
  fill() {
    /* never DOM-fill; URL prefill only */
  },
  validate() {
    return { ok: false, reason: "no auto-submit" };
  }
  // intentionally no submit()
};

// Browser globals (script-tag style) + adapter on window.
const _root =
  typeof globalThis !== "undefined"
    ? globalThis
    : typeof window !== "undefined"
      ? window
      : typeof global !== "undefined"
        ? global
        : {};

if (typeof window !== "undefined") {
  window.RegistrationAdapter = RegistrationAdapter;
}

// Expose helpers as globals for browser script usage (original pattern).
_root.loadProfile = loadProfile;
_root.saveProfile = saveProfile;
_root.deleteProfile = deleteProfile;
_root.profileComplete = profileComplete;
_root.exportProfile = exportProfile;
_root.getExportProfile = getExportProfile;
_root.importProfile = importProfile;
_root.loadRegState = loadRegState;
_root.saveRegState = saveRegState;
_root.setRegState = setRegState;
_root.getRegState = getRegState;
_root.clearRegState = clearRegState;
_root.RegistrationAdapter = RegistrationAdapter;
_root.mapGFormLabel = mapGFormLabel;
_root.buildGFormPrefillUrl = buildGFormPrefillUrl;
_root.openGFormPrefill = openGFormPrefill;
_root.gformCanPrefill = gformCanPrefill;
_root.listGFormPrefillPlan = listGFormPrefillPlan;
_root.GFORM_CONFIRM_MSG = GFORM_CONFIRM_MSG;

// CommonJS exports for offline Node tests (no bundler required).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    PROFILE_KEY,
    REGSTATE_KEY,
    PROFILE_VERSION,
    MAX_IMPORT_BYTES,
    NOTE_LIMIT,
    ALLOWED_FIELDS,
    FIELD_LIMITS,
    REQUIRED,
    VALID_REG_STATES,
    UNSAFE_KEYS,
    isValidEmail,
    normalizeProfile,
    loadProfile,
    saveProfile,
    deleteProfile,
    profileComplete,
    getExportProfile,
    exportProfile,
    importProfile,
    loadRegState,
    saveRegState,
    setRegState,
    getRegState,
    clearRegState,
    RegistrationAdapter,
    GFORM_CONFIRM_MSG,
    GFORM_SAFE_PROFILE_FIELDS,
    mapGFormLabel,
    resolveGFormFieldMappings,
    getGFormRegistration,
    gformCanPrefill,
    listGFormPrefillPlan,
    buildGFormPrefillUrl,
    openGFormPrefill
  };
}
