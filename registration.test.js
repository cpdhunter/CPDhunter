'use strict';

/**
 * Offline Node tests for the disconnected registration.js module.
 * Uses node:test + a minimal localStorage / File / DOM mock.
 * Never loads index.html; never contacts the network.
 */

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const MODULE_PATH = path.join(__dirname, 'registration.js');

function createLocalStorage() {
  const store = new Map();
  return {
    getItem(k) {
      return store.has(String(k)) ? store.get(String(k)) : null;
    },
    setItem(k, v) {
      store.set(String(k), String(v));
    },
    removeItem(k) {
      store.delete(String(k));
    },
    clear() {
      store.clear();
    },
    get length() {
      return store.size;
    },
    key(i) {
      return [...store.keys()][i] ?? null;
    },
    _dump() {
      return Object.fromEntries(store);
    }
  };
}

function createFile(content, opts = {}) {
  const text = typeof content === 'string' ? content : JSON.stringify(content);
  const size = opts.size !== undefined ? opts.size : Buffer.byteLength(text, 'utf8');
  return {
    name: opts.name || 'profile.json',
    size,
    type: 'application/json',
    _content: text,
    text: async () => text
  };
}

function eq(a, b) {
  // vm realm objects break assert.deepStrictEqual prototype checks
  assert.equal(JSON.stringify(a), JSON.stringify(b));
}

function loadModule() {

  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  const localStorage = createLocalStorage();
  const networkCalls = [];

  // Ensure network primitives are absent / trapped if someone defines them later.
  const fetchTrap = (...args) => {
    networkCalls.push({ type: 'fetch', args });
    throw new Error('network forbidden');
  };
  const xhrTrap = function () {
    networkCalls.push({ type: 'xhr' });
    throw new Error('network forbidden');
  };
  const beaconTrap = (...args) => {
    networkCalls.push({ type: 'sendBeacon', args });
    return false;
  };

  const document = {
    createElement(tag) {
      return {
        tagName: String(tag).toUpperCase(),
        href: '',
        download: '',
        click() {
          this._clicked = true;
        }
      };
    }
  };

  const blobParts = [];
  class Blob {
    constructor(parts, opts) {
      this.parts = parts;
      this.options = opts;
      blobParts.push(this);
    }
  }

  const objectUrls = [];
  const URL = {
    createObjectURL(blob) {
      const u = 'blob:test-' + objectUrls.length;
      objectUrls.push({ u, blob });
      return u;
    },
    revokeObjectURL() {}
  };

  // FileReader mock used when present
  class FileReader {
    constructor() {
      this.result = null;
      this.onload = null;
      this.onerror = null;
    }
    readAsText(file) {
      try {
        this.result = file._content != null ? file._content : '';
        if (typeof this.onload === 'function') this.onload({ target: this });
      } catch (e) {
        if (typeof this.onerror === 'function') this.onerror(e);
      }
    }
  }

  const window = { document };
  const sandbox = {
    module: { exports: {} },
    exports: {},
    require,
    console,
    localStorage,
    window,
    document,
    Blob,
    URL,
    FileReader,
    TextEncoder,
    TextDecoder,
    alert() {},
    setTimeout,
    clearTimeout,
    Date,
    JSON,
    Error,
    Map,
    Set,
    Promise,
    Object,
    Array,
    String,
    Number,
    Boolean,
    Math,
    Buffer,
    globalThis: null // set below
  };
  sandbox.global = sandbox;
  sandbox.globalThis = sandbox;
  window.localStorage = localStorage;

  // Deliberately do NOT provide fetch / XMLHttpRequest / navigator.sendBeacon
  // on the sandbox so the module cannot call them. Tests also assert absence.
  assert.equal('fetch' in sandbox, false);
  assert.equal('XMLHttpRequest' in sandbox, false);

  vm.runInNewContext(code, sandbox, { filename: 'registration.js' });
  const api = sandbox.module.exports;
  assert.ok(api && typeof api.saveProfile === 'function');

  return {
    api,
    localStorage,
    networkCalls,
    blobParts,
    sandbox,
    window,
    installNetworkTraps() {
      sandbox.fetch = fetchTrap;
      sandbox.XMLHttpRequest = xhrTrap;
      sandbox.navigator = { sendBeacon: beaconTrap };
      return networkCalls;
    }
  };
}

function validProfile(overrides = {}) {
  return {
    version: 1,
    title: 'Ir',
    englishName: 'Alice Chan',
    chineseName: '陳小明',
    email: 'alice@example.com',
    phone: '+852 1234 5678',
    position: 'Engineer',
    organisation: 'Example Ltd',
    hkieNumber: 'M123456',
    primaryDiscipline: 'DSTM',
    secondaryDiscipline: 'OTM',
    preferredLanguage: 'en',
    ...overrides
  };
}

describe('registration.js hardened local module', () => {
  let ctx;
  let api;

  beforeEach(() => {
    ctx = loadModule();
    api = ctx.api;
  });

  afterEach(() => {
    ctx = null;
    api = null;
  });

  it('valid save/load round-trip', () => {
    const saved = api.saveProfile(validProfile());
    assert.ok(saved);
    assert.equal(saved.version, 1);
    assert.equal(saved.englishName, 'Alice Chan');
    const loaded = api.loadProfile();
    eq(loaded, saved);
    assert.equal(ctx.localStorage.getItem(api.PROFILE_KEY), JSON.stringify(saved));
  });

  it('profileComplete true for full required set', () => {
    const p = api.saveProfile(validProfile());
    assert.equal(api.profileComplete(p), true);
  });

  for (const field of ['englishName', 'email', 'organisation', 'position', 'primaryDiscipline']) {
    it(`profileComplete false when required ${field} missing`, () => {
      const raw = validProfile();
      delete raw[field];
      const p = api.saveProfile(raw);
      assert.ok(p);
      assert.equal(api.profileComplete(p), false);
    });
  }

  it('title is optional (not required)', () => {
    const raw = validProfile();
    delete raw.title;
    const p = api.saveProfile(raw);
    assert.equal(api.profileComplete(p), true);
    assert.equal('title' in p, false);
  });

  it('valid export schema: profile only, version 1, allowlisted fields', () => {
    api.saveProfile(validProfile({ secretToken: 'nope', events: [{ id: 1 }] }));
    // Also plant regState and fake CPD data in storage
    ctx.localStorage.setItem(api.REGSTATE_KEY, JSON.stringify({ e1: { state: 'opened', ts: 't', note: '' } }));
    ctx.localStorage.setItem('events', JSON.stringify([{ id: 'x' }]));
    const exported = api.getExportProfile();
    assert.ok(exported);
    assert.equal(exported.version, 1);
    assert.equal('secretToken' in exported, false);
    assert.equal('events' in exported, false);
    assert.equal('regState' in exported, false);
    for (const k of Object.keys(exported)) {
      if (k === 'version') continue;
      assert.ok(api.ALLOWED_FIELDS.includes(k), `unexpected export key ${k}`);
    }
    const viaExport = api.exportProfile();
    eq(viaExport, exported);
    // Verify the actual Blob JSON downloaded by the browser, not only its source.
    const exportBlob = ctx.blobParts.at(-1);
    assert.equal(exportBlob.options.type, 'application/json');
    eq(JSON.parse(exportBlob.parts[0]), exported);
    assert.equal(exportBlob.parts[0].includes('nope'), false);
    // Ensure export JSON text would not include regState history
    const text = JSON.stringify(exported);
    assert.equal(text.includes('regState'), false);
    assert.equal(text.includes('opened'), false);
  });

  it('valid import succeeds for complete profile', async () => {
    const file = createFile(validProfile());
    const imported = await api.importProfile(file);
    assert.equal(imported.englishName, 'Alice Chan');
    assert.equal(api.profileComplete(imported), true);
    eq(api.loadProfile(), imported);
  });

  it('malformed JSON rejection', async () => {
    await assert.rejects(() => api.importProfile(createFile('{not json')), /invalid/);
  });

  it('array rejection', async () => {
    await assert.rejects(() => api.importProfile(createFile([validProfile()])), /invalid/);
  });

  it('unsupported version rejection', async () => {
    await assert.rejects(
      () => api.importProfile(createFile(validProfile({ version: 99 }))),
      /version/
    );
  });

  it('unexpected keys removed safely on import', async () => {
    const raw = validProfile({ evil: '<script>alert(1)</script>', __proto__: { x: 1 }, nested: { a: 1 } });
    // JSON round-trip drops proto weirdness; keep evil + nested
    const payload = JSON.parse(JSON.stringify(raw));
    payload.evil = '<script>alert(1)</script>';
    payload.nested = { a: 1 };
    const imported = await api.importProfile(createFile(payload));
    assert.equal('evil' in imported, false);
    assert.equal('nested' in imported, false);
    assert.equal(api.profileComplete(imported), true);
  });

  it('invalid field types rejected on import (required)', async () => {
    const raw = validProfile({ englishName: 12345 });
    await assert.rejects(() => api.importProfile(createFile(raw)), /type/);
  });

  it('null, boolean and object fields rejected', async () => {
    for (const value of [null, true, { nested: 'string' }]) {
      await assert.rejects(() => api.importProfile(createFile(validProfile({ title: value }))), /type/);
    }
    assert.equal(api.saveProfile(validProfile({ organisation: true })), null);
  });

  it('invalid optional field types rejected on import (not omitted)', async () => {
    const raw = validProfile({ phone: 999, chineseName: { x: 1 } });
    await assert.rejects(() => api.importProfile(createFile(raw)), /type/);
    assert.equal(api.loadProfile(), null);
  });

  it('invalid field types rejected on save (null failure semantics)', () => {
    assert.equal(api.saveProfile(validProfile({ phone: 999 })), null);
    assert.equal(api.loadProfile(), null);
  });

  it('oversized fields rejected (not truncated) on save and import', async () => {
    const longName = 'A'.repeat(api.FIELD_LIMITS.englishName + 1);
    assert.equal(api.saveProfile(validProfile({ englishName: longName })), null);
    assert.equal(api.loadProfile(), null);
    await assert.rejects(
      () => api.importProfile(createFile(validProfile({ englishName: longName }))),
      /too_long/
    );
    await assert.rejects(
      () => api.importProfile(createFile(validProfile({ title: 'T'.repeat(api.FIELD_LIMITS.title + 1) }))),
      /too_long/
    );
  });

  it('all allowed fields accepted at exact character limits', async () => {
    const filled = { version: 1 };
    for (const [field, limit] of Object.entries(api.FIELD_LIMITS)) filled[field] = 'x'.repeat(limit);
    filled.email = `${'e'.repeat(242)}@example.com`;
    const imported = await api.importProfile(createFile(filled));
    for (const [field, limit] of Object.entries(api.FIELD_LIMITS)) {
      assert.equal(imported[field].length, limit, field);
    }
  });

  it('oversized import file rejected by declared size (100 KB)', async () => {
    const big = createFile(validProfile(), { size: 100 * 1024 + 1 });
    await assert.rejects(() => api.importProfile(big), /too_large/);
  });

  it('UTF-8 byte guard rejects content over 100 KB even when file.size=0', async () => {
    // Multi-byte chars make UTF-8 byte length exceed 100 KB while lying file.size=0.
    const text =
      '{"version":1,"englishName":"Alice Chan","email":"alice@example.com",' +
      '"organisation":"Example Ltd","position":"Engineer","primaryDiscipline":"DSTM",' +
      '"pad":"' + '字'.repeat(40 * 1024) + '"}';
    assert.ok(Buffer.byteLength(text, 'utf8') > 100 * 1024);
    const file = createFile(text, { size: 0 });
    await assert.rejects(() => api.importProfile(file), /too_large/);
  });

  it('invalid email rejected on import and save', async () => {
    const bad = validProfile({ email: 'not-an-email' });
    assert.equal(api.saveProfile(bad), null);
    assert.equal(api.loadProfile(), null);
    await assert.rejects(() => api.importProfile(createFile(bad)), /email/);
  });

  it('HTML/script strings remain inert data (never executed/rendered)', async () => {
    const xss = '<script>window.__pwned=1</script><img onerror="alert(1)" src=x>';
    const saved = api.saveProfile(validProfile({ organisation: xss, chineseName: xss }));
    assert.ok(saved);
    assert.equal(saved.organisation, xss);
    // Sandbox must not gain __pwned or execute markup
    assert.equal(ctx.sandbox.__pwned, undefined);
    assert.equal(ctx.window.__pwned, undefined);
    const imported = await api.importProfile(createFile(validProfile({ organisation: xss })));
    assert.equal(imported.organisation.includes('<script>'), true);
    assert.equal(ctx.sandbox.__pwned, undefined);
    // No HTML sink used
    assert.equal(ctx.sandbox.document.body, undefined);
  });

  it('only valid registration states accepted', () => {
    for (const state of api.VALID_REG_STATES) {
      assert.equal(api.setRegState('evt-1', state, 'ok'), true);
      assert.equal(api.getRegState('evt-1').state, state);
    }
  });

  it('invalid registration state rejected', () => {
    assert.equal(api.setRegState('evt-2', 'submitted_auto', 'nope'), false);
    assert.equal(api.setRegState('evt-2', 'registered', ''), false);
    assert.equal(api.setRegState('evt-2', '', ''), false);
    assert.equal(api.setRegState('evt-2', null, ''), false);
    assert.equal(api.getRegState('evt-2'), null);
    eq(api.loadRegState(), {});
  });

  it('note length capped at 500', () => {
    const note = 'N'.repeat(800);
    assert.equal(api.setRegState('evt-n', 'opened', note), true);
    assert.equal(api.getRegState('evt-n').note.length, api.NOTE_LIMIT);
  });

  it('deleteProfile preserves regState', () => {
    api.saveProfile(validProfile());
    api.setRegState('e1', 'opened', 'keep');
    api.deleteProfile();
    assert.equal(api.loadProfile(), null);
    assert.equal(api.getRegState('e1').state, 'opened');
    assert.equal(api.getRegState('e1').note, 'keep');
  });

  it('clearRegState preserves regProfile', () => {
    api.saveProfile(validProfile());
    api.setRegState('e1', 'cancelled', 'x');
    api.clearRegState();
    assert.ok(api.loadProfile());
    assert.equal(api.loadProfile().englishName, 'Alice Chan');
    eq(api.loadRegState(), {});
    assert.equal(api.getRegState('e1'), null);
  });


  it('regState rejects arrays and non-plain objects', () => {
    assert.equal(api.saveRegState([]), false);
    assert.equal(api.saveRegState(null), false);
    assert.equal(api.saveRegState('x'), false);
    eq(api.loadRegState(), {});
    // Plant array in storage — load must reject
    ctx.localStorage.setItem(api.REGSTATE_KEY, '[]');
    eq(api.loadRegState(), {});
    ctx.localStorage.setItem(api.REGSTATE_KEY, '"nope"');
    eq(api.loadRegState(), {});
  });

  it('regState rejects unsafe keys (__proto__/constructor/prototype)', () => {
    assert.equal(api.setRegState('__proto__', 'opened', 'x'), false);
    assert.equal(api.setRegState('constructor', 'opened', 'x'), false);
    assert.equal(api.setRegState('prototype', 'opened', 'x'), false);
    assert.equal(api.getRegState('__proto__'), null);
    assert.equal(api.getRegState('constructor'), null);
    // Normal event ids still work
    assert.equal(api.setRegState('evt-safe-1', 'opened', 'ok'), true);
    assert.equal(api.getRegState('evt-safe-1').state, 'opened');
    // Plant unsafe keys via raw JSON (object-literal __proto__ is special-cased by JS).
    ctx.localStorage.setItem(
      api.REGSTATE_KEY,
      '{"__proto__":{"state":"opened","ts":"t","note":""},' +
        '"constructor":{"state":"opened","ts":"t","note":""},' +
        '"prototype":{"state":"opened","ts":"t","note":""},' +
        '"evt-ok":{"state":"cancelled","ts":"t","note":"n"}}'
    );
    const loaded = api.loadRegState();
    assert.equal(Object.prototype.hasOwnProperty.call(loaded, '__proto__'), false);
    assert.equal(Object.prototype.hasOwnProperty.call(loaded, 'constructor'), false);
    assert.equal(loaded['evt-ok'].state, 'cancelled');
  });

  it('adapter cannot autofill or submit; URL-only canHandle is false', () => {
    const a = api.RegistrationAdapter;
    assert.equal(a.canHandle('https://example.com/register'), false);
    assert.equal(a.canHandle('https://docs.google.com/forms/d/e/x/viewform'), false);
    assert.equal(a.inspect(), null);
    eq(a.matchFields(), []);
    assert.equal(a.fill(), undefined);
    eq(a.validate(), { ok: false, reason: 'no auto-submit' });
    eq(a.getUnsupportedFields(), []);
    assert.equal('submit' in a, false);
    assert.equal(typeof a.submit, 'undefined');
  });

  it('no profile values sent over network (fetch/XHR/sendBeacon absent or trapped)', () => {
    assert.equal('fetch' in ctx.sandbox, false);
    assert.equal('XMLHttpRequest' in ctx.sandbox, false);
    assert.equal('navigator' in ctx.sandbox, false);

    api.saveProfile(validProfile());
    api.exportProfile();
    api.setRegState('e1', 'opened', 'alice@example.com');

    // Install traps and ensure module paths still do not call them
    const calls = ctx.installNetworkTraps();
    api.saveProfile(validProfile({ email: 'bob@example.com' }));
    api.getExportProfile();
    api.exportProfile();
    return api.importProfile(createFile(validProfile())).then(() => {
      assert.equal(calls.length, 0);
      // Even if traps exist, adapter fill/validate must not use them
      api.RegistrationAdapter.fill();
      api.RegistrationAdapter.validate();
      assert.equal(calls.length, 0);
    });
  });

  it('control characters sanitized from profile fields', () => {
    const dirty = validProfile({
      englishName: 'Alice\u0000Chan\u0007',
      organisation: 'Org\u001FLtd'
    });
    const saved = api.saveProfile(dirty);
    assert.equal(saved.englishName.includes('\u0000'), false);
    assert.equal(saved.organisation.includes('\u001F'), false);
    assert.equal(saved.englishName, 'AliceChan');
  });

  it('window.RegistrationAdapter is exposed', () => {
    assert.equal(ctx.window.RegistrationAdapter, api.RegistrationAdapter);
    assert.equal(ctx.window.RegistrationAdapter.canHandle('x'), false);
  });
});

describe('Google Forms partial prefill (Sprint 2B2)', () => {
  let ctx;
  let api;

  beforeEach(() => {
    ctx = loadModule();
    api = ctx.api;
  });

  afterEach(() => {
    ctx = null;
    api = null;
  });

  function openMeta(overrides = {}) {
    return {
      mechanism: 'GOOGLE_FORMS',
      destination: 'https://docs.google.com/forms/d/e/1FAIpQLSfixture/viewform',
      formId: '1FAIpQLSfixture',
      status: 'OPEN',
      requiresManualCompletion: true,
      fields: [
        {
          entryId: 'entry.111',
          profileField: 'englishName',
          label: 'English Name',
          type: 'SHORT_TEXT',
          safePrefill: true
        },
        {
          entryId: 'entry.222',
          profileField: 'email',
          label: 'Email',
          type: 'SHORT_TEXT',
          safePrefill: true
        },
        {
          entryId: 'entry.333',
          profileField: null,
          label: 'Are you a HKIE Member?',
          type: 'RADIO',
          safePrefill: false
        },
        {
          entryId: 'entry.444',
          profileField: 'primaryDiscipline',
          label: 'Discipline',
          type: 'DROPDOWN',
          safePrefill: true,
          options: ['Civil', 'Structural']
        }
      ],
      ...overrides
    };
  }

  it('maps safe labels and refuses consent/title/judgment/split-name', () => {
    assert.equal(api.mapGFormLabel('English Full Name'), 'englishName');
    assert.equal(api.mapGFormLabel('Full name (Same as HKID / Travel Passport)'), 'englishName');
    assert.equal(api.mapGFormLabel('Chinese Name (e.g. 陳大文)'), 'chineseName');
    assert.equal(api.mapGFormLabel('Email Address'), 'email');
    assert.equal(api.mapGFormLabel('Mobile Phone Number'), 'phone');
    assert.equal(api.mapGFormLabel('Company Name'), 'organisation');
    assert.equal(api.mapGFormLabel('Job Title'), 'position');
    assert.equal(api.mapGFormLabel('HKIE Membership Number'), 'hkieNumber');
    assert.equal(api.mapGFormLabel('Discipline'), 'primaryDiscipline');
    assert.equal(api.mapGFormLabel('Title'), null);
    assert.equal(api.mapGFormLabel('Title', 2), null);
    assert.equal(api.mapGFormLabel('Surname (e.g. CHAN)'), null);
    assert.equal(api.mapGFormLabel('Given Name (e.g. Tai Man)'), null);
    assert.equal(api.mapGFormLabel('First Name / Given Name'), null);
    assert.equal(api.mapGFormLabel('Last Name / Family Name'), null);
    assert.equal(api.mapGFormLabel('Emergency Contact Name'), null);
    assert.equal(
      api.mapGFormLabel(
        'Any personal data provided in this registration form will be used for the purposes directly related'
      ),
      null
    );
    assert.equal(api.mapGFormLabel('Are you a HKIE Member?'), null);
    assert.equal(api.mapGFormLabel('I noted the above information.'), null);
  });

  it('clears ambiguous duplicate profileField mappings', () => {
    const fields = api.resolveGFormFieldMappings([
      { entryId: 'entry.1', profileField: 'email', label: 'Email', type: 'SHORT_TEXT', safePrefill: true },
      { entryId: 'entry.2', profileField: 'email', label: 'E-mail', type: 'SHORT_TEXT', safePrefill: true },
      { entryId: 'entry.3', profileField: 'phone', label: 'Mobile', type: 'SHORT_TEXT', safePrefill: true }
    ]);
    assert.equal(fields[0].profileField, null);
    assert.equal(fields[0].safePrefill, false);
    assert.equal(fields[1].profileField, null);
    assert.equal(fields[2].profileField, 'phone');
    assert.equal(fields[2].safePrefill, true);
  });

  it('buildGFormPrefillUrl encodes values and uses usp=pp_url', () => {
    const profile = validProfile({
      englishName: 'Alice Chan',
      email: 'alice@example.com',
      primaryDiscipline: 'Civil'
    });
    const url = api.buildGFormPrefillUrl(profile, openMeta());
    assert.ok(url);
    assert.equal(url.includes('usp=pp_url'), true);
    assert.equal(url.includes('entry.111=' + encodeURIComponent('Alice Chan')), true);
    assert.equal(url.includes('entry.222=' + encodeURIComponent('alice@example.com')), true);
    assert.equal(url.includes('entry.444=' + encodeURIComponent('Civil')), true);
    assert.equal(url.includes('entry.333='), false);
    assert.equal(url.startsWith('https://docs.google.com/forms/d/e/1FAIpQLSfixture/viewform?'), true);
  });

  it('omits empty profile values and unmapped fields', () => {
    const profile = validProfile({ englishName: 'Alice', email: 'alice@example.com', phone: '' });
    const meta = openMeta({
      fields: [
        { entryId: 'entry.1', profileField: 'englishName', label: 'Name', type: 'SHORT_TEXT', safePrefill: true },
        { entryId: 'entry.2', profileField: 'phone', label: 'Phone', type: 'SHORT_TEXT', safePrefill: true },
        { entryId: 'entry.3', profileField: null, label: 'Consent', type: 'RADIO', safePrefill: false }
      ]
    });
    const url = api.buildGFormPrefillUrl(profile, meta);
    assert.ok(url);
    assert.equal(url.includes('entry.1='), true);
    assert.equal(url.includes('entry.2='), false);
    assert.equal(url.includes('entry.3='), false);
  });

  it('dropdown/radio only prefills exact option match', () => {
    const profile = validProfile({ primaryDiscipline: 'Mechanical' });
    const url = api.buildGFormPrefillUrl(profile, openMeta());
    assert.ok(url);
    assert.equal(url.includes('entry.444='), false);
  });

  it('canHandle requires OPEN schema with safePrefill fields', () => {
    const event = { id: 'e1', registration: openMeta() };
    assert.equal(api.RegistrationAdapter.canHandle(event), true);
    assert.equal(api.gformCanPrefill(openMeta({ status: 'CLOSED' })), false);
    assert.equal(
      api.RegistrationAdapter.canHandle({
        id: 'e2',
        registration: openMeta({ status: 'CLOSED' })
      }),
      false
    );
    assert.equal(
      api.RegistrationAdapter.canHandle({
        id: 'e3',
        registration: openMeta({
          fields: [{ entryId: 'entry.1', profileField: null, label: 'X', type: 'RADIO', safePrefill: false }]
        })
      }),
      false
    );
  });

  it('openGFormPrefill confirms, opens with noopener, sets opened, does not store URL', () => {
    const profile = validProfile();
    api.saveProfile(profile);
    const opened = [];
    const event = { id: 'evtG1', registration: openMeta() };
    const res = api.openGFormPrefill(
      event,
      profile,
      () => true,
      (url, target, feat) => {
        opened.push({ url, target, feat });
      }
    );
    assert.equal(res.ok, true);
    assert.equal(opened.length, 1);
    assert.equal(opened[0].target, '_blank');
    assert.equal(opened[0].feat, 'noopener,noreferrer');
    assert.equal(opened[0].url.includes('usp=pp_url'), true);
    assert.equal(api.getRegState('evtG1').state, 'opened');
    // Prefill URL must not appear in localStorage (profile email may legitimately exist)
    const dump = JSON.stringify(ctx.localStorage._dump());
    assert.equal(dump.includes('usp=pp_url'), false);
    assert.equal(dump.includes('entry.111'), false);
    assert.equal(dump.includes('1FAIpQLSfixture'), false);
  });

  it('openGFormPrefill cancels without opening when confirm is false', () => {
    const profile = validProfile();
    const opened = [];
    const res = api.openGFormPrefill(
      { id: 'evtG2', registration: openMeta() },
      profile,
      () => false,
      (url) => opened.push(url)
    );
    assert.equal(res.ok, false);
    assert.equal(res.reason, 'cancelled');
    assert.equal(opened.length, 0);
    assert.equal(api.getRegState('evtG2'), null);
  });

  it('CLOSED forms do not build prefill URLs', () => {
    const url = api.buildGFormPrefillUrl(validProfile(), openMeta({ status: 'CLOSED' }));
    assert.equal(url, null);
  });
});
