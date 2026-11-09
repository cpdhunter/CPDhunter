const assert = require('assert');
const fs = require('fs');
const C = require('./calendar_export');
const A = require('./attendance');
const Bridge = require('./cpd_bridge');

const html = fs.readFileSync('index.html', 'utf8');
assert(!html.includes('<!-- PLACEHOLDER') && !/skeleton demo|simplified rewrite/i.test(html));
assert(html.includes('src="calendar_export.js"'));
assert(html.includes('src="attendance.js"'));
assert(html.includes('src="cpd_bridge.js"'));
assert(html.includes('src="recommendations.js"'));
assert(html.includes('src="registration.js"'));
assert(html.includes('data-t="home"'));
assert(html.includes('data-t="events"'));
assert(html.includes('data-t="tracker"'));
assert(html.includes('myEventsRoot'));
assert(html.includes('加入行事曆'));
assert(html.includes('你有參加嗎'));
assert(html.includes('為我推薦'));
assert(html.includes('7日內'));
assert(html.includes('CPDLogAdapter'));
assert(html.includes('CPDCalendarExport'));
assert(html.includes('CPDAttendance'));
// modules must remain optional — guarded loads
assert(html.includes('typeof CPDCalendarExport'));
assert(html.includes('typeof CPDAttendance'));

// ICS: no invented end, HKT, CRLF, alarm, official URL, no PII
const e = {
  id: 'ics1',
  name: 'Safety, Risk; and \\ Practice',
  date: '2026-11-12',
  time: '19:00-21:00',
  org: 'OSHC',
  venue: 'Online',
  hrs: 2,
  hrs_est: true,
  url: 'https://example.com/official'
};
const ics = C.createICS(e, { category: 'H&S', now: new Date('2026-11-01T00:00:00Z') });
assert(ics.includes('BEGIN:VCALENDAR\r\n'));
assert(ics.includes('DTSTART;TZID=Asia/Hong_Kong:20261112T190000'));
assert(ics.includes('DTEND;TZID=Asia/Hong_Kong:20261112T210000'));
assert(ics.includes('TRIGGER:-PT30M'));
assert(ics.includes('UID:ics1@cpdhunter'));
assert(ics.includes('URL:https://example.com/official'));
assert(ics.includes('estimated') && ics.includes('verify with organiser'));
assert(!/email|phone|hkie|organisation|@gmail/i.test(ics));
assert(!ics.includes('docs.google.com/forms'));
const one = C.createICS({ ...e, time: '19:00' });
assert(one.includes('DTSTART;TZID=Asia/Hong_Kong:20261112T190000'));
assert(!one.includes('DTEND;TZID=Asia/Hong_Kong'));
const day = C.createICS({ ...e, time: '' });
assert(day.includes('DTSTART;VALUE=DATE:20261112'));

// Attendance boundaries
class Mem {
  constructor() { this.m = new Map(); }
  getItem(k) { return this.m.get(k) || null; }
  setItem(k, v) { this.m.set(k, v); }
  removeItem(k) { this.m.delete(k); }
}
const past = { id: 'p1', name: 'Past', date: '2026-11-01', time: '10:00-11:00', hrs: 2, hrs_est: false };
const future = { id: 'f1', name: 'Future', date: '2026-12-01', time: '10:00-11:00', hrs: 2 };
assert.equal(A.shouldPrompt(past, 'registered_manual', new Date('2026-11-02T00:00:00+08:00'), new Mem()), true);
assert.equal(A.shouldPrompt(past, 'opened', new Date('2026-11-02T00:00:00+08:00'), new Mem()), false);
assert.equal(A.shouldPrompt(future, 'registered_manual', new Date('2026-11-02T00:00:00+08:00'), new Mem()), false);

// Adapter duplicate prevention on production logs
const logs = Bridge.addAttendanceToProdLog([], past, 'H&S', 2, A);
assert.throws(() => Bridge.addAttendanceToProdLog(logs, past, 'H&S', 2, A));
assert.equal(Bridge.hasEventLog(logs, 'p1'), true);

console.log('sprint2e_integration tests PASS');
