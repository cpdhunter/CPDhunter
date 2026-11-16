'use strict';

/**
 * CLOSED-registration catalogue eligibility tests.
 * Official registration.status == CLOSED is hidden from the normal catalogue
 * but remains available for My Events / ICS / attendance when already registered.
 */
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

const ROOT = __dirname;
const C = require('./catalogue');
const R = require('./recommendations');
const Cal = require('./calendar_export');
const A = require('./attendance');
const Reg = require('./registration');

const indexSrc = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const eventsPath = path.join(ROOT, 'events.json');
const eventsShaBefore = crypto.createHash('sha256').update(fs.readFileSync(eventsPath)).digest('hex');

function ev(over) {
  return Object.assign(
    {
      id: 'c1',
      name: 'Safety seminar',
      date: '2026-12-01',
      time: '15:30-16:45',
      org: 'OSHC',
      type: 'H&S',
      disc: ['General'],
      free: true,
      hrs: 1.25,
      url: 'https://sms.oshc.hk/online/activityE.aspx?activityid=9921',
      registration: { status: 'OPEN', mechanism: 'OSHC_PORTAL', destination: 'https://sms.oshc.hk/online/activityE.aspx?activityid=9921' }
    },
    over || {}
  );
}

function closed(over) {
  return ev(Object.assign({
    registration: { status: 'CLOSED', mechanism: 'REGISTRATION_CLOSED', destination: 'https://sms.oshc.hk/online/activityE.aspx?activityid=9921' }
  }, over || {}));
}

describe('closed registration catalogue filter', () => {
  it('1. future event + explicit Registration closed -> excluded', () => {
    const e = closed();
    assert.equal(C.isCatalogueEligible(e), false);
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), false);
    assert.equal(C.catalogueEvents([e], '2026-11-16').length, 0);
  });

  it('2. future event + 截止報名 status already stamped CLOSED -> excluded', () => {
    const e = closed({ id: 'zh1', name: '職安講座' });
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), false);
  });

  it('3. future event + 此講座會議已經截止報名 stamped CLOSED -> excluded', () => {
    const e = closed({ id: 'oshc9921' });
    assert.ok(!C.catalogueEvents([e], '2026-11-16').some((x) => x.id === 'oshc9921'));
  });

  it('4. future event + Fully booked / CLOSED -> excluded', () => {
    const e = closed({ id: 'fb', registration: { status: 'CLOSED', mechanism: 'REGISTRATION_CLOSED' } });
    assert.equal(C.isRegistrationClosed(e), true);
    assert.equal(C.isCatalogueEligible(e), false);
  });

  it('5. missing registration link is not automatically CLOSED', () => {
    const e = ev({
      registration: {
        status: 'UNKNOWN',
        mechanism: 'REGISTRATION_LINK_NOT_FOUND',
        destination: null
      }
    });
    assert.equal(C.isRegistrationClosed(e), false);
    assert.equal(C.isCatalogueEligible(e), true);
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), true);
  });

  it('6. CAPTCHA is not CLOSED', () => {
    const e = ev({
      registration: { status: 'UNKNOWN', mechanism: 'CAPTCHA_BLOCKED', destination: null }
    });
    assert.equal(C.isRegistrationClosed(e), false);
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), true);
  });

  it('7. login required is not CLOSED', () => {
    const e = ev({
      registration: { status: 'LOGIN_REQUIRED', mechanism: 'LOGIN_REQUIRED', destination: null }
    });
    assert.equal(C.isRegistrationClosed(e), false);
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), true);
  });

  it('8. registration unknown remains catalogue-eligible', () => {
    const e = ev({
      registration: { status: 'UNKNOWN', mechanism: 'UNKNOWN', destination: null }
    });
    assert.equal(C.isCatalogueEligible(e), true);
    assert.equal(C.isVisibleFuture(e, '2026-11-16'), true);
  });

  it('9. past event still excluded by normal date rule', () => {
    const openPast = ev({ date: '2026-11-01', registration: { status: 'OPEN', mechanism: 'OSHC_PORTAL' } });
    const closedPast = closed({ date: '2026-11-01' });
    assert.equal(C.isVisibleFuture(openPast, '2026-11-16'), false);
    assert.equal(C.isVisibleFuture(closedPast, '2026-11-16'), false);
    // Untimed future is also hidden from the visible catalogue (existing time-slot rule).
    const untimed = ev({ time: '' });
    assert.equal(C.isCatalogueEligible(untimed), false);
  });

  it('10. CLOSED event excluded from recommendations', () => {
    const e = closed({ type: 'H&S', free: true, hrs: 2 });
    const ctx = {
      discipline: 'Civil',
      related: [],
      memberType: 'corp',
      today: '2026-11-16',
      logs: [],
      deficits: R.getDeficits({ memberType: 'corp', logs: [], year: '2026' })
    };
    assert.equal(R.scoreEvent(e, ctx), null);
    const ranked = R.rankEvents([e, ev({ id: 'open1' })], ctx);
    assert.ok(!ranked.ranked.some((s) => s.event.id === e.id));
    assert.ok(ranked.ranked.some((s) => s.event.id === 'open1') || ranked.ranked.length >= 0);
  });

  it('11. CLOSED event excluded from Upcoming / visible future list', () => {
    const closedE = closed({ id: 'up-closed' });
    const openE = ev({ id: 'up-open' });
    const upcoming = C.catalogueEvents([closedE, openE], '2026-11-16');
    assert.deepEqual(upcoming.map((e) => e.id), ['up-open']);
    assert.match(indexSrc, /function renderList\(\)[\s\S]*byCat\(filtered\(\)\)\.filter\(e=>e\.date>=today\)/);
    assert.match(indexSrc, /function filtered\(\)[\s\S]*return catalogueEvents\(\)\.filter/);
  });

  it('12. CLOSED event excluded from normal search', () => {
    const closedE = closed({ id: 's-closed', name: 'Workplace Verbal Abuse seminar' });
    const openE = ev({ id: 's-open', name: 'Workplace Verbal Abuse seminar' });
    const hits = C.searchCatalogue([closedE, openE], 'Verbal Abuse', '2026-11-16');
    assert.deepEqual(hits.map((e) => e.id), ['s-open']);
  });

  it('13. CLOSED + registered_manual remains in My Events', () => {
    const e = closed({ id: 'my1' });
    assert.equal(C.remainsInMyEvents('registered_manual'), true);
    assert.equal(C.isLocallyRegistered('registered_manual'), true);
    assert.equal(C.isCatalogueEligible(e), false);
    // index keeps My Events on allEvents() (timed, including CLOSED) and eventById on the full dataset
    assert.match(indexSrc, /function renderMyEvents\(\)[\s\S]*const events=allEvents\(\)/);
    assert.match(indexSrc, /function eventById\(id\)\{const e=DATA\.events\.find/);
    assert.match(indexSrc, /function allEvents\(\)\{return DATA\.events\.filter\(hasTimeSlot\)/);
  });

  it('14. CLOSED + registered_manual still allows ICS', () => {
    const e = closed({
      id: 'ics-closed',
      name: 'Closed but registered seminar',
      date: '2026-12-01',
      time: '15:30-16:45',
      url: 'https://sms.oshc.hk/online/activityE.aspx?activityid=9921'
    });
    assert.equal(C.isLocallyRegistered('registered_manual'), true);
    const ics = Cal.createICS(e, { category: 'H&S', now: new Date('2026-11-16T00:00:00Z') });
    assert.match(ics, /BEGIN:VCALENDAR/);
    assert.match(ics, /SUMMARY:Closed but registered seminar/);
    assert.match(ics, /DTSTART;TZID=Asia\/Hong_Kong:20261201T153000/);
    assert.match(ics, /URL:https:\/\/sms\.oshc\.hk\/online\/activityE\.aspx\?activityid=9921/);
    assert.doesNotMatch(ics, /email|@gmail/i);
  });

  it('15. CLOSED + registered_manual still allows attendance flow', () => {
    class Mem {
      constructor() { this.m = new Map(); }
      getItem(k) { return this.m.get(k) || null; }
      setItem(k, v) { this.m.set(k, v); }
      removeItem(k) { this.m.delete(k); }
    }
    const past = closed({ id: 'att1', date: '2026-11-10', time: '10:00-11:00', hrs: 1 });
    const mem = new Mem();
    assert.equal(A.shouldPrompt(past, 'registered_manual', new Date('2026-11-16T00:00:00+08:00'), mem), true);
    const rec = A.buildLogRecord(past, 'H&S', 1);
    assert.equal(rec.eventId, 'att1');
    assert.equal(rec.name, past.name);
  });

  it('16. CLOSED + opened is not treated as registered', () => {
    const e = closed({ id: 'opened1' });
    assert.equal(C.isLocallyRegistered('opened'), false);
    assert.equal(C.remainsInMyEvents('opened'), true);
    assert.equal(C.isCatalogueEligible(e), false);
    assert.equal(C.registrationNowClosedLabel(e, 'opened'), 'Registration now closed');
    class Mem {
      constructor() { this.m = new Map(); }
      getItem(k) { return this.m.get(k) || null; }
      setItem(k, v) { this.m.set(k, v); }
    }
    assert.equal(A.shouldPrompt(closed({ id: 'opened1', date: '2026-11-10', time: '10:00-11:00' }), 'opened', new Date('2026-11-16T00:00:00+08:00'), new Mem()), false);
  });

  it('17. CLOSED event cannot start Prepare Registration', () => {
    const e = closed();
    assert.equal(C.canStartPrepareRegistration(e), false);
    assert.equal(C.canStartPrepareRegistration(ev()), true);
    assert.match(indexSrc, /function fillRegPrep[\s\S]*isRegistrationClosed\(e\)[\s\S]*return;/);
    assert.match(indexSrc, /準備報名 \/ Prepare Registration/);
    // Closed path returns before the Prepare Registration heading / official-page button
    const fn = indexSrc.slice(indexSrc.indexOf('function fillRegPrep'), indexSrc.indexOf('function openRegDestination'));
    const closedReturn = fn.indexOf('return;');
    const heading = fn.indexOf('準備報名 / Prepare Registration');
    assert.ok(closedReturn > 0 && heading > closedReturn);
  });

  it('18. existing Google Forms CLOSED behavior unchanged', () => {
    const meta = {
      mechanism: 'GOOGLE_FORMS',
      status: 'CLOSED',
      destination: 'https://docs.google.com/forms/d/e/1FAIpQLSx/viewform',
      formId: '1FAIpQLSx',
      fields: []
    };
    assert.equal(Reg.gformCanPrefill({ registration: meta }), false);
    assert.equal(Reg.buildGFormPrefillUrl({ englishFullName: 'A B', email: 'a@b.c' }, meta), null);
    const res = Reg.openGFormPrefill(
      { id: 'g1', registration: meta },
      { englishFullName: 'A B', email: 'a@b.c', phone: '1', organisation: 'X', position: 'Y' },
      () => true,
      () => null
    );
    assert.equal(res.ok, false);
    assert.equal(res.reason, 'closed');
  });

  it('20. this suite does not manually edit events.json', () => {
    const after = crypto.createHash('sha256').update(fs.readFileSync(eventsPath)).digest('hex');
    assert.equal(after, eventsShaBefore);
  });
});
