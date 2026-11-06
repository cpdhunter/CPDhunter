// CPD Hunter Sprint 1 - local registration profile & state
// Profile and registration state are stored only in this browser (localStorage).
// Nothing is sent to any server.
// Hardened: schema v1 validation, state allowlist, import/export guards.
// Still DISCONNECTED from index.html — experimental module only.

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

// Adapter remains disabled: no autofill, no submit(), no CAPTCHA,
// no organiser API calls, no network transmission of profile.
const RegistrationAdapter = {
  canHandle(url) {
    return false;
  },
  inspect() {
    return null;
  },
  matchFields() {
    return [];
  },
  fill() {
    /* disabled in Sprint 1 */
  },
  validate() {
    return { ok: false, reason: "Sprint 1: no auto-fill" };
  },
  getUnsupportedFields() {
    return [];
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
    RegistrationAdapter
  };
}
