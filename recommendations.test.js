'use strict';

/**
 * Offline Node tests for recommendations.js (Sprint 2D).
 * Pure / local — asserts no personalization network transmission.
 */

const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const MODULE_PATH = path.join(__dirname, 'recommendations.js');

function loadModule() {
  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  const networkCalls = [];
  const fetchTrap = (...args) => {
    networkCalls.push({ type: 'fetch', args });
    throw new Error('network forbidden');
  };
  const xhrTrap = function () {
    networkCalls.push({ type: 'xhr' });
    throw new Error('network forbidden');
  };
  const sandbox = {
    module: { exports: {} },
    exports: {},
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    Error,
    parseInt,
    parseFloat,
    isNaN,
    Infinity,
    NaN,
    globalThis: null
  };
  sandbox.globalThis = sandbox;
  sandbox.global = sandbox;
  Object.defineProperty(sandbox, 'fetch', {
    get() {
      return fetchTrap;
    },
    set() {
      /* ignore */
    },
    configurable: true
  });
  Object.defineProperty(sandbox, 'XMLHttpRequest', {
    get() {
      return xhrTrap;
    },
    set() {
      /* ignore */
    },
    configurable: true
  });
  vm.runInNewContext(code, sandbox, { filename: 'recommendations.js' });
  const api = sandbox.module.exports;
  assert.ok(api && typeof api.scoreEvent === 'function');
  assert.equal('fetch' in sandbox, true);
  return { api, networkCalls, sandbox };
}

function baseEvent(over) {
  return Object.assign(
    {
      id: 'e1',
      name: 'Sample Event',
      org: 'Org',
      date: '2026-11-20',
      time: '18:00-20:00',
      hrs: 2,
      hrs_est: false,
      type: 'H&S',
      disc: ['General'],
      url: 'https://example.com/e',
      region: 'HK',
      online: false,
      free: true,
      source: 'Test',
      group: 'Test',
      registration: {
        mechanism: 'OTHER_PUBLIC_FORM',
        destination: 'https://example.com/reg',
        status: 'OPEN'
      }
    },
    over || {}
  );
}

function ctx(over) {
  const today = '2026-11-08';
  const base = {
    discipline: 'Civil',
    related: ['Structural', 'Geotechnical', 'Logistics & Transportation', 'Environmental'],
    memberType: 'corp',
    today,
    logs: [],
    regState: {}
  };
  const c = Object.assign(base, over || {});
  c.deficits = c.deficits || c.apiGetDeficits || null;
  return c;
}

describe('recommendations.js Sprint 2D', () => {
  let api;
  let networkCalls;

  beforeEach(() => {
    const loaded = loadModule();
    api = loaded.api;
    networkCalls = loaded.networkCalls;
  });

  function withDeficits(logs, memberType) {
    return api.getDeficits({ memberType: memberType || 'corp', logs: logs || [], year: '2026' });
  }

  it('1. outstanding H&S ranks H&S event higher', () => {
    const deficits = withDeficits([{ date: '2026-01-01', cat: 'H&S', hrs: 1, mode: 'Structured' }]);
    assert.equal(deficits.deficit['H&S'], 2);
    const hs = baseEvent({ id: 'hs', type: 'H&S', name: 'H&S Webinar' });
    const gpm = baseEvent({ id: 'gpm', type: 'GPM', name: 'GPM Talk', registration: { status: 'OPEN', destination: 'https://x.com', mechanism: 'OTHER_PUBLIC_FORM' } });
    // complete GPM so only H&S has deficit among these
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'H&S', hrs: 1, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'DSTM', hrs: 5, mode: 'Structured' }
    ]);
    const c = ctx({ deficits: defs });
    const sh = api.scoreEvent(hs, c);
    const sg = api.scoreEvent(gpm, c);
    assert.ok(sh.score > sg.score);
    assert.ok(sh.reasons.some((r) => /H&S/.test(r)));
  });

  it('2. outstanding DSTM ranks matching technical event higher', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'H&S', hrs: 3, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' }
    ]);
    assert.ok(defs.deficit.DSTM > 0);
    const match = baseEvent({
      id: 'civ',
      type: 'Technical',
      disc: ['Civil'],
      name: 'Civil seminar'
    });
    const other = baseEvent({
      id: 'mech',
      type: 'Technical',
      disc: ['Mechanical'],
      name: 'Mech seminar'
    });
    const c = ctx({ deficits: defs });
    const sm = api.scoreEvent(match, c);
    const so = api.scoreEvent(other, c);
    assert.equal(sm.cat, 'DSTM');
    assert.equal(so.cat, 'OTM');
    assert.ok(sm.score > so.score);
  });

  it('3. completed H&S receives no deficit bonus', () => {
    const defs = withDeficits([{ date: '2026-01-01', cat: 'H&S', hrs: 3, mode: 'Structured' }]);
    assert.equal(defs.deficit['H&S'], 0);
    const hs = baseEvent({ id: 'hs', type: 'H&S' });
    const s = api.scoreEvent(hs, ctx({ deficits: defs }));
    assert.ok(s);
    assert.equal(s.flags.categoryDeficit, 0);
    assert.ok(!s.reasonItems.some((r) => r.code === 'cat_deficit'));
    // score should not include +40
    const defsOut = withDeficits([]);
    const s2 = api.scoreEvent(hs, ctx({ deficits: defsOut }));
    assert.ok(s2.score >= s.score + 40);
  });

  it('4. correct discipline match bonus', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const primary = baseEvent({ id: 'p', type: 'Technical', disc: ['Civil'], free: null, online: null, hrs: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const related = baseEvent({ id: 'r', type: 'Technical', disc: ['Structural'], free: null, online: null, hrs: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const other = baseEvent({ id: 'o', type: 'Technical', disc: ['Mechanical'], free: null, online: null, hrs: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const c = ctx({ deficits: defs });
    const sp = api.scoreEvent(primary, c);
    const sr = api.scoreEvent(related, c);
    const so = api.scoreEvent(other, c);
    assert.equal(sp.discMatch, 'primary');
    assert.equal(sr.discMatch, 'related');
    assert.equal(so.discMatch, null);
    assert.equal(sp.score - so.score, 30);
    assert.equal(sr.score - so.score, 15);
  });

  it('5. free beats fee-unknown when otherwise equal', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const freeEv = baseEvent({
      id: 'f',
      type: 'H&S',
      free: true,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const unk = baseEvent({
      id: 'u',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const c = ctx({ deficits: defs });
    assert.ok(api.scoreEvent(freeEv, c).score > api.scoreEvent(unk, c).score);
  });

  it('6. online bonus', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const on = baseEvent({
      id: 'on',
      type: 'H&S',
      free: null,
      online: true,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const off = baseEvent({
      id: 'off',
      type: 'H&S',
      free: null,
      online: false,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const c = ctx({ deficits: defs });
    assert.equal(api.scoreEvent(on, c).score - api.scoreEvent(off, c).score, 10);
  });

  it('7. official hours rank above estimated', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const off = baseEvent({
      id: 'off',
      type: 'H&S',
      free: null,
      online: null,
      hrs: 2,
      hrs_est: false,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const est = baseEvent({
      id: 'est',
      type: 'H&S',
      free: null,
      online: null,
      hrs: 2,
      hrs_est: true,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const c = ctx({ deficits: defs });
    assert.ok(api.scoreEvent(off, c).score > api.scoreEvent(est, c).score);
  });

  it('8. estimated ranks above unknown', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const est = baseEvent({
      id: 'est',
      type: 'H&S',
      free: null,
      online: null,
      hrs: 2,
      hrs_est: true,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const unk = baseEvent({
      id: 'unk',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const c = ctx({ deficits: defs });
    assert.ok(api.scoreEvent(est, c).score > api.scoreEvent(unk, c).score);
  });

  it('9. event that closes deficit gets bonus', () => {
    const defs = withDeficits([{ date: '2026-01-01', cat: 'H&S', hrs: 1, mode: 'Structured' }]);
    assert.equal(defs.deficit['H&S'], 2);
    const closer = baseEvent({ id: 'c', type: 'H&S', hrs: 2, hrs_est: false, free: null, online: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const partial = baseEvent({ id: 'p', type: 'H&S', hrs: 1, hrs_est: false, free: null, online: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const c = ctx({ deficits: defs });
    const sc = api.scoreEvent(closer, c);
    const sp = api.scoreEvent(partial, c);
    assert.equal(sc.flags.closesDeficit, true);
    assert.equal(sp.flags.closesDeficit, false);
    assert.equal(sc.score - sp.score, 10);
  });

  it('10. registration destination bonus', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const withD = baseEvent({
      id: 'd',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'OPEN', destination: 'https://example.com/r', mechanism: 'OTHER_PUBLIC_FORM' }
    });
    const noD = baseEvent({
      id: 'n',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'REGISTRATION_LINK_NOT_FOUND' }
    });
    const c = ctx({ deficits: defs });
    assert.equal(api.scoreEvent(withD, c).score - api.scoreEvent(noD, c).score, 5);
  });

  it('11. Google Forms prefill bonus', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const gform = baseEvent({
      id: 'g',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: {
        mechanism: 'GOOGLE_FORMS',
        status: 'OPEN',
        destination: 'https://docs.google.com/forms/d/e/x/viewform',
        fields: [{ entryId: 'entry.1', safePrefill: true, profileField: 'englishName', label: 'Name' }]
      }
    });
    const plain = baseEvent({
      id: 'p',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: {
        mechanism: 'OTHER_PUBLIC_FORM',
        status: 'OPEN',
        destination: 'https://example.com/r'
      }
    });
    const c = ctx({ deficits: defs });
    // both have destination (+5); gform also +5 prefill
    assert.equal(api.scoreEvent(gform, c).score - api.scoreEvent(plain, c).score, 5);
    assert.ok(api.hasGFormSafePrefill(gform.registration));
  });

  it('12. closed registration excluded', () => {
    const e = baseEvent({
      registration: { status: 'CLOSED', destination: 'https://x.com', mechanism: 'OTHER_PUBLIC_FORM' }
    });
    assert.equal(api.scoreEvent(e, ctx({ deficits: withDeficits([]) })), null);
  });

  it('13. past event excluded', () => {
    const e = baseEvent({ date: '2026-11-07' });
    assert.equal(api.scoreEvent(e, ctx({ deficits: withDeficits([]), today: '2026-11-08' })), null);
  });

  it('14. registered_manual excluded', () => {
    const e = baseEvent({ id: 'rm' });
    const c = ctx({
      deficits: withDeficits([]),
      regState: { rm: { state: 'registered_manual' } }
    });
    assert.equal(api.scoreEvent(e, c), null);
  });

  it('15. cancelled excluded', () => {
    const e = baseEvent({ id: 'ca' });
    const c = ctx({
      deficits: withDeficits([]),
      regState: { ca: { state: 'cancelled' } }
    });
    assert.equal(api.scoreEvent(e, c), null);
  });

  it('16. opened state penalty', () => {
    const e = baseEvent({ id: 'op', free: null, online: null, hrs: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } });
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' }
    ]);
    const base = api.scoreEvent(e, ctx({ deficits: defs, regState: {} }));
    const opened = api.scoreEvent(e, ctx({ deficits: defs, regState: { op: { state: 'opened' } } }));
    assert.equal(opened.score, base.score - 5);
  });

  it('17. maximum 5 events', () => {
    const defs = withDeficits([]);
    const events = [];
    for (let i = 0; i < 12; i++) {
      events.push(
        baseEvent({
          id: 'x' + i,
          name: 'E' + i,
          date: '2026-12-' + String(10 + (i % 20)).padStart(2, '0'),
          type: 'H&S'
        })
      );
    }
    const r = api.rankEvents(events, ctx({ deficits: defs }), 5);
    assert.equal(r.ranked.length, 5);
    assert.equal(api.RECO_MAX, 5);
  });

  it('18. deterministic stable ranking on equal scores', () => {
    // Leave H&S deficit so equal non-tiebreak scores stay > 0 (not dropped as weak).
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' }
    ]);
    const a = baseEvent({
      id: 'b-id',
      name: 'B',
      date: '2026-12-01',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const b = baseEvent({
      id: 'a-id',
      name: 'A',
      date: '2026-12-01',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const c = baseEvent({
      id: 'c-id',
      name: 'C',
      date: '2026-11-15',
      type: 'H&S',
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const ctx1 = ctx({ deficits: defs });
    const r1 = api.rankEvents([a, b, c], ctx1);
    const r2 = api.rankEvents([c, a, b], ctx1);
    assert.deepEqual(
      r1.ranked.map((x) => x.id),
      r2.ranked.map((x) => x.id)
    );
    // earlier date first among equal scores; then id asc
    assert.equal(r1.ranked[0].id, 'c-id');
    assert.equal(r1.ranked[1].id, 'a-id');
    assert.equal(r1.ranked[2].id, 'b-id');
  });

  it('19. no mutation of events.json objects', () => {
    const e = baseEvent({ id: 'mut' });
    const freeze = JSON.stringify(e);
    const defs = withDeficits([]);
    api.scoreEvent(e, ctx({ deficits: defs }));
    api.rankEvents([e], ctx({ deficits: defs }));
    assert.equal(JSON.stringify(e), freeze);
  });

  it('20. no profile/CPD data network transmission', () => {
    const defs = withDeficits([{ date: '2026-01-01', cat: 'H&S', hrs: 1, mode: 'Structured' }]);
    const e = baseEvent();
    api.scoreEvent(e, ctx({ deficits: defs }));
    api.rankEvents([e], ctx({ deficits: defs, logs: [{ date: '2026-01-01', cat: 'H&S', hrs: 1 }] }));
    assert.equal(networkCalls.length, 0);
    // module source must not call fetch/XHR/beacon for personalization
    const src = fs.readFileSync(MODULE_PATH, 'utf8');
    assert.equal(/fetch\s*\(/.test(src), false);
    assert.equal(/XMLHttpRequest/.test(src), false);
    assert.equal(/sendBeacon/.test(src), false);
    assert.equal(/navigator\./.test(src), false);
  });

  it('21. missing discipline empty-state behavior', () => {
    const r = api.rankEvents([baseEvent()], ctx({ discipline: null, deficits: withDeficits([]) }));
    assert.equal(r.emptyKind, 'no_discipline');
    assert.equal(r.ranked.length, 0);
    const msg = api.emptyStateMessage('no_discipline');
    assert.ok(msg.title.includes('HKIE discipline'));
    assert.equal(msg.actionKind, 'disc');
  });

  it('22. all-deficits-complete fallback ranking', () => {
    const defs = withDeficits([
      { date: '2026-01-01', cat: 'DSTM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-02', cat: 'GPM', hrs: 5, mode: 'Structured' },
      { date: '2026-01-03', cat: 'H&S', hrs: 3, mode: 'Structured' },
      { date: '2026-01-04', cat: 'OTM', hrs: 20, mode: 'Structured' }
    ]);
    assert.equal(defs.deficit.DSTM, 0);
    assert.equal(defs.deficit.GPM, 0);
    assert.equal(defs.deficit['H&S'], 0);
    const civil = baseEvent({
      id: 'civ',
      type: 'Technical',
      disc: ['Civil'],
      free: true,
      online: true,
      hrs: 2,
      hrs_est: false
    });
    const other = baseEvent({
      id: 'oth',
      type: 'Technical',
      disc: ['Mechanical'],
      free: null,
      online: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const r = api.rankEvents([other, civil], ctx({ deficits: defs }));
    assert.equal(r.emptyKind, 'deficits_complete');
    assert.ok(r.ranked.length >= 1);
    assert.equal(r.ranked[0].id, 'civ');
    const msg = api.emptyStateMessage(r.emptyKind);
    assert.ok(msg.title.includes('已達標'));
  });

  it('Scheme A uses TN-G period H&S/OTM/GPM targets', () => {
    const d = api.getDeficits({ memberType: 'trainee', logs: [], year: '2026' });
    assert.equal(d.req['H&S'], 18);
    assert.equal(d.req.OTM, 18);
    assert.equal(d.req.GPM, 18);
    assert.equal(d.req.total, 45);
    assert.equal(d.req.DSTM, 0);
    assert.equal(d.deficit['H&S'], 18);
    assert.equal(d.deficit.OTM, 18);
    assert.equal(d.deficit.GPM, 18);
    // Period categories use all-time logs; year still gates total
    const d2 = api.getDeficits({
      memberType: 'trainee',
      logs: [
        { date: '2025-06-01', cat: 'H&S', hrs: 10, mode: 'Structured' },
        { date: '2026-03-01', cat: 'H&S', hrs: 5, mode: 'Structured' },
        { date: '2025-01-01', cat: 'OTM', hrs: 18, mode: 'Structured' },
        { date: '2026-02-01', cat: 'GPM', hrs: 3, mode: 'Structured' }
      ],
      year: '2026'
    });
    assert.equal(d2.logged['H&S'], 15);
    assert.equal(d2.deficit['H&S'], 3);
    assert.equal(d2.logged.OTM, 18);
    assert.equal(d2.deficit.OTM, 0);
    assert.equal(d2.logged.GPM, 3);
    assert.equal(d2.deficit.GPM, 15);
    assert.equal(d2.logged.total, 8);
    assert.equal(d2.deficit.total, 37);
  });

  it('getRecommendationReasons returns deterministic items', () => {
    const s = api.scoreEvent(baseEvent(), ctx({ deficits: withDeficits([]) }));
    const reasons = api.getRecommendationReasons(s);
    assert.ok(reasons.length > 0);
    assert.ok(reasons.every((r) => r.text));
  });
});
