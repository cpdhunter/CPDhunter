const assert = require('assert');
const A = require('./attendance');
const Bridge = require('./cpd_bridge');

const e = { id: 'ev99', name: 'Bridge Test Talk', date: '2026-10-01', time: '10:00-11:00', hrs: 2, hrs_est: true };
const authored = A.buildLogRecord(e, 'H&S', 2);
assert.equal(authored.eventId, 'ev99');
assert.equal(authored.hours, 2);

const mapped = Bridge.toProdRecord(authored, 12345);
assert.equal(mapped.id, 12345);
assert.equal(mapped.evId, 'ev99');
assert.equal(mapped.hrs, 2);
assert.equal(mapped.cat, 'H&S');
assert.equal(mapped.mode, 'Structured');
assert.equal(mapped.hrs_est, true);
assert.equal(mapped.source, 'attendance-confirmation');
assert.strictEqual(mapped.eventId, undefined);
assert.strictEqual(mapped.hours, undefined);

// Existing production-shaped log (evId only) blocks duplicate via adapter
const existing = [{ id: 1, evId: 'ev99', name: 'Old', date: '2026-09-01', hrs: 1, cat: 'DSTM', mode: 'Structured' }];
assert.equal(Bridge.hasEventLog(existing, 'ev99'), true);
assert.equal(Bridge.hasEventLog(existing, 'other'), false);
assert.throws(() => Bridge.addAttendanceToProdLog(existing, e, 'H&S', 2, A));

// Authored-shaped eventId also detected
const authoredShaped = [{ id: 'event:ev99', eventId: 'ev99', name: 'X', date: '2026-09-01', cat: 'H&S', hours: 1 }];
assert.equal(Bridge.hasEventLog(authoredShaped, 'ev99'), true);

// Fresh add works and preserves old records
const next = Bridge.addAttendanceToProdLog([], e, 'H&S', 2, A);
assert.equal(next.length, 1);
assert.equal(next[0].evId, 'ev99');
assert.equal(next[0].hrs, 2);
assert.equal(next[0].mode, 'Structured');

// Old logs without evId remain readable / not deleted
const oldManual = [{ id: 9, name: 'Manual CPD', date: '2026-01-02', hrs: 3, cat: 'GPM', mode: 'Self-study' }];
const mixed = Bridge.addAttendanceToProdLog(oldManual, e, 'OTM', 1.5, A);
assert.equal(mixed.length, 2);
assert.equal(mixed[0].name, 'Manual CPD');
assert.equal(mixed[0].mode, 'Self-study');
assert.equal(mixed[1].evId, 'ev99');

console.log('cpd_bridge tests PASS');
