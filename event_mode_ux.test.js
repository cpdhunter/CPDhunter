'use strict';

/**
 * Event-mode UX / ranking integration tests (33 brief items).
 * Offline / local only.
 */

const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = __dirname;
const M = require('./event_mode');
const recSrc = fs.readFileSync(path.join(ROOT, 'recommendations.js'), 'utf8');
const indexSrc = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const events = JSON.parse(fs.readFileSync(path.join(ROOT, 'events.json'), 'utf8'));

function loadRecommendations() {
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
    require,
    CPDEventMode: M
  };
  sandbox.globalThis = sandbox;
  sandbox.global = sandbox;
  vm.runInNewContext(recSrc, sandbox, { filename: 'recommendations.js' });
  return sandbox.module.exports;
}

const R = loadRecommendations();

function ev(over) {
  return Object.assign(
    {
      id: 'x',
      name: 'Seminar',
      date: '2026-11-20',
      time: '18:00-20:00',
      org: 'Org',
      type: 'H&S',
      disc: ['General'],
      free: true,
      hrs: 2,
      hrs_est: false
    },
    over || {}
  );
}

function ctx(over) {
  return Object.assign(
    {
      discipline: 'Civil',
      related: ['Structural'],
      memberType: 'corp',
      today: '2026-11-10',
      logs: [],
      deficits: R.getDeficits({
        memberType: 'corp',
        logs: [],
        year: '2026'
      })
    },
    over || {}
  );
}

describe('event-mode UX integration', () => {
  it('1. explicit ONLINE', () => {
    assert.equal(M.modeOf({ mode: 'ONLINE' }), 'ONLINE');
  });
  it('2. explicit FACE_TO_FACE', () => {
    assert.equal(M.modeOf({ mode: 'FACE_TO_FACE' }), 'FACE_TO_FACE');
  });
  it('3. explicit HYBRID', () => {
    assert.equal(M.modeOf({ mode: 'HYBRID' }), 'HYBRID');
  });
  it('4. explicit UNKNOWN', () => {
    assert.equal(M.modeOf({ mode: 'UNKNOWN' }), 'UNKNOWN');
  });
  it('5. online=true fallback', () => {
    assert.equal(M.modeOf({ online: true }), 'ONLINE');
    assert.equal(M.inferMode({ online: true }).reason, 'legacy_online_true');
  });
  it('6. online=false remains UNKNOWN', () => {
    assert.equal(M.modeOf({ online: false, venue: 'HKIE' }), 'UNKNOWN');
    assert.equal(M.inferMode({ online: false }).reason, 'legacy_false_insufficient');
  });
  it('7. district or org-only venue remains UNKNOWN', () => {
    assert.equal(M.modeOf({ venue: 'Kowloon Bay' }), 'UNKNOWN');
    assert.equal(M.modeOf({ venue: '銅鑼灣' }), 'UNKNOWN');
    assert.equal(M.modeOf({ venue: 'HKIE HQ' }), 'UNKNOWN');
    assert.equal(M.modeOf({ venue: 'Hong Kong' }), 'UNKNOWN');
  });
  it('7b. listing or raw physical venue is not classified by the frontend', () => {
    assert.equal(M.modeOf({ venue: 'Hong Kong Convention Centre' }), 'UNKNOWN');
    assert.equal(
      M.modeOf({
        venue: '香港中央圖書館演講廳 香港銅鑼灣高士威道66號'
      }),
      'UNKNOWN'
    );
    assert.equal(
      M.modeOf({
        venue: '香港中央圖書館演講廳 香港銅鑼灣高士威道66號',
        description: 'Also available on Zoom webinar'
      }),
      'ONLINE'
    );
    assert.equal(
      M.modeOf({
        mode: 'FACE_TO_FACE',
        venue: '香港中央圖書館演講廳 香港銅鑼灣高士威道66號'
      }),
      'FACE_TO_FACE'
    );
  });
  it('8. Zoom becomes ONLINE', () => {
    assert.equal(M.modeOf({ venue: 'Zoom' }), 'ONLINE');
  });
  it('9. face-to-face wording becomes FACE_TO_FACE', () => {
    assert.equal(M.modeOf({ description: 'Face-to-face workshop' }), 'FACE_TO_FACE');
  });
  it('10. online plus physical evidence becomes HYBRID', () => {
    assert.equal(
      M.modeOf({ name: 'Hybrid seminar', venue: 'CIC-ZCP and Zoom' }),
      'HYBRID'
    );
    assert.equal(
      M.modeOf({ description: 'In-person and online attendance' }),
      'HYBRID'
    );
  });
  it('11-16. mode filters including multi and none', () => {
    const online = ev({ mode: 'ONLINE' });
    const face = ev({ mode: 'FACE_TO_FACE' });
    const hybrid = ev({ mode: 'HYBRID' });
    const unk = ev({ mode: 'UNKNOWN' });
    const all = [online, face, hybrid, unk];
    const pick = (modes) => all.filter((e) => M.matches(e, modes));
    assert.deepEqual(pick(['ONLINE']).map(M.modeOf), ['ONLINE']);
    assert.deepEqual(pick(['FACE_TO_FACE']).map(M.modeOf), ['FACE_TO_FACE']);
    assert.deepEqual(pick(['HYBRID']).map(M.modeOf), ['HYBRID']);
    assert.deepEqual(pick(['UNKNOWN']).map(M.modeOf), ['UNKNOWN']);
    assert.deepEqual(pick(['ONLINE', 'HYBRID']).map(M.modeOf), ['ONLINE', 'HYBRID']);
    assert.equal(pick([]).length, 4);
    assert.equal(M.matches(face, []), true);
  });
  it('17-21. online-first sort and date tie-break', () => {
    const list = [
      ev({ mode: 'UNKNOWN', name: 'u', date: '2026-11-12' }),
      ev({ mode: 'FACE_TO_FACE', name: 'f', date: '2026-11-11' }),
      ev({ mode: 'HYBRID', name: 'h', date: '2026-11-13' }),
      ev({ mode: 'ONLINE', name: 'o-late', date: '2026-11-20' }),
      ev({ mode: 'ONLINE', name: 'o-early', date: '2026-11-15' }),
      ev({ mode: 'ONLINE', name: 'a-same', date: '2026-11-15' })
    ].sort(M.compareOnlineFirst);
    assert.deepEqual(
      list.map((e) => e.name),
      ['a-same', 'o-early', 'o-late', 'h', 'f', 'u']
    );
    assert.deepEqual(list.map(M.modeOf), [
      'ONLINE',
      'ONLINE',
      'ONLINE',
      'HYBRID',
      'FACE_TO_FACE',
      'UNKNOWN'
    ]);
  });
  it('22-25. recommendation bonuses 25 / 18 / 0 / -3', () => {
    const c = ctx();
    const base = { type: 'H&S', free: null, hrs: null, registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' } };
    const sOn = R.scoreEvent(ev(Object.assign({ id: 'on', mode: 'ONLINE' }, base)), c);
    const sHy = R.scoreEvent(ev(Object.assign({ id: 'hy', mode: 'HYBRID' }, base)), c);
    const sFa = R.scoreEvent(ev(Object.assign({ id: 'fa', mode: 'FACE_TO_FACE' }, base)), c);
    const sUn = R.scoreEvent(ev(Object.assign({ id: 'un', mode: 'UNKNOWN' }, base)), c);
    assert.equal(sOn.score - sFa.score, 25);
    assert.equal(sHy.score - sFa.score, 18);
    assert.equal(sUn.score - sFa.score, -3);
    assert.ok(sOn.reasons.includes('網上活動'));
    assert.ok(sHy.reasons.includes('混合模式，可網上參與'));
    assert.ok(sFa.reasons.includes('面授活動'));
    assert.ok(sUn.reasons.includes('活動形式未確認'));
  });
  it('26. outstanding deficit still affects ranking', () => {
    const c = ctx();
    const hsFace = ev({
      id: 'hsf',
      type: 'H&S',
      mode: 'FACE_TO_FACE',
      free: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const otmOnline = ev({
      id: 'otmo',
      type: 'Technical',
      disc: ['Mechanical'],
      mode: 'ONLINE',
      free: null,
      hrs: null,
      registration: { status: 'UNKNOWN', destination: null, mechanism: 'UNKNOWN' }
    });
    const r = R.rankEvents([otmOnline, hsFace], c);
    assert.equal(r.ranked[0].id, 'hsf');
  });
  it('27. disabled user mode excluded from shortlist', () => {
    const on = ev({ id: 'on', mode: 'ONLINE', type: 'H&S' });
    const hy = ev({ id: 'hy', mode: 'HYBRID', type: 'H&S', name: 'Hybrid seminar' });
    const r = R.rankEvents([on, hy], ctx({ allowedModes: ['HYBRID'] }));
    assert.ok(r.ranked.every((s) => s.id !== 'on'));
    assert.ok(r.ranked.some((s) => s.id === 'hy'));
  });
  it('28. mode preference remains browser-local', () => {
    assert.match(indexSrc, /MODE_PREF_KEY="modePref"/);
    assert.match(indexSrc, /SS\(MODE_PREF_KEY/);
    assert.match(indexSrc, /localStorage/);
    const prefBlock = indexSrc.slice(
      indexSrc.indexOf('MODE_PREF_KEY'),
      indexSrc.indexOf('function filtered')
    );
    assert.doesNotMatch(prefBlock, /fetch\s*\(/);
    assert.doesNotMatch(prefBlock, /XMLHttpRequest/);
    assert.doesNotMatch(prefBlock, /sendBeacon/);
    assert.match(indexSrc, /偏好只存於呢部裝置嘅瀏覽器/);
  });
  it('29. event cards include text label', () => {
    assert.match(indexSrc, /function item\(e\)[\s\S]*eventModeLabel\(e\)/);
    assert.match(indexSrc, /function evChip\(e\)[\s\S]*eventModeLabel\(e\)/);
    assert.match(indexSrc, /function myEventCard[\s\S]*eventModeLabel\(e\)/);
    assert.match(indexSrc, /t\.textContent=eventModeLabel\(e\)/);
    assert.match(indexSrc, /labelFor/);
    assert.doesNotMatch(indexSrc, /textContent="實體"/);
  });
  it('30. event modal includes full mode', () => {
    assert.match(indexSrc, /function showEv[\s\S]*eventModeDetail\(e\)/);
    assert.match(indexSrc, /id="evModeDetail"/);
    assert.match(indexSrc, /活動形式：/);
    assert.match(indexSrc, /md\.zh/);
    assert.match(indexSrc, /md\.en/);
    assert.match(indexSrc, /官方來源未明確說明/);
  });
  it('31. long title remains unchanged', () => {
    const long = ev({
      name: 'A'.repeat(180) + ' Online Seminar on Structural Engineering Safety'
    });
    assert.equal(M.modeOf(long), 'ONLINE');
    const freeze = long.name;
    M.inferMode(long);
    R.scoreEvent(long, ctx());
    assert.equal(long.name, freeze);
    assert.match(indexSrc, /title="\$\{esc\(e\.name\)\}"/);
    assert.doesNotMatch(indexSrc, /e\.name\s*=/);
  });
  it('32. no source data mutation', () => {
    const raw = ev({ id: 'mut', venue: 'Kowloon Bay', online: false });
    const freeze = JSON.stringify(raw);
    M.inferMode(raw);
    M.modeOf(raw);
    R.scoreEvent(raw, ctx());
    R.rankEvents([raw], ctx());
    assert.equal(JSON.stringify(raw), freeze);
    const snapshot = JSON.stringify(events);
    events.events.slice(0, 20).forEach((e) => M.modeOf(e));
    assert.equal(JSON.stringify(events), snapshot);
  });
  it('33. no network transmission of preferences', () => {
    assert.doesNotMatch(recSrc, /fetch\s*\(/);
    assert.doesNotMatch(recSrc, /XMLHttpRequest/);
    assert.doesNotMatch(recSrc, /sendBeacon/);
    assert.match(indexSrc, /allowedModes:myModePref\(\)/);
    assert.doesNotMatch(indexSrc, /fetch\([^)]*modePref/);
    assert.ok(!/navigator\.sendBeacon/.test(indexSrc));
  });

  it('frontend loads event_mode.js before consumers', () => {
    const em = indexSrc.indexOf('src="event_mode.js"');
    const rec = indexSrc.indexOf('src="recommendations.js"');
    assert.ok(em >= 0 && rec > em);
  });

  it('filter chips include four modes with Online first after reco', () => {
    const start = indexSrc.indexOf('const items=[');
    const block = indexSrc.slice(start, indexSrc.indexOf('root.innerHTML=items', start));
    const keys = [...block.matchAll(/\["([A-Z_]+|reco|days|free)"/g)].map((m) => m[1]);
    assert.deepEqual(
      keys.slice(0, 5),
      ['reco', 'ONLINE', 'HYBRID', 'FACE_TO_FACE', 'UNKNOWN']
    );
    assert.ok(keys.indexOf('days') > keys.indexOf('UNKNOWN'));
  });

  it('current production catalog can be classified without fabrication', () => {
    const today = '2026-11-10';
    const future = events.events.filter((e) => e.date >= today);
    const counts = { ONLINE: 0, FACE_TO_FACE: 0, HYBRID: 0, UNKNOWN: 0 };
    future.forEach((e) => {
      counts[M.modeOf(e)]++;
    });
    assert.ok(future.length > 0);
    assert.equal(Object.values(counts).reduce((a, b) => a + b, 0), future.length);
    future.forEach((e) => {
      if (e.online === false && !e.mode) {
        const sample = { online: false, venue: e.venue, name: 'x' };
        // Frontend does not infer FACE_TO_FACE from online=false or a listing venue.
        assert.notEqual(M.modeOf(sample), 'FACE_TO_FACE');
      }
    });
  });
});

console.log('event_mode_ux tests defined');
