/* CPD Hunter - thin integration adapter between CPDAttendance and production CPD logs.
   Do not change attendance.js / calendar_export.js core rules; adapt at this boundary.
   Production log key: "logs". Production fields: {id, evId, name, date, hrs, cat, mode}.
   Authored attendance fields: {id, eventId, name, date, cat, hours, hrs_est, source}. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CPDLogAdapter = Object.freeze(api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const LOG_KEY = "logs";

  /** Duplicate check against EXISTING production records (evId and/or eventId). */
  function hasEventLog(logs, eventId) {
    const id = String(eventId || "");
    if (!id || !Array.isArray(logs)) return false;
    return logs.some((r) => {
      if (!r || typeof r !== "object") return false;
      return String(r.evId || "") === id || String(r.eventId || "") === id;
    });
  }

  /** Map authored attendance record → production log record (keeps tracker/CSV compatible). */
  function toProdRecord(authored, idHint) {
    const a = authored || {};
    const hrs = Number(a.hours);
    return {
      id: idHint != null ? idHint : Date.now(),
      evId: String(a.eventId || ""),
      name: String(a.name || ""),
      date: String(a.date || ""),
      hrs: hrs,
      cat: String(a.cat || ""),
      mode: "Structured",
      hrs_est: Boolean(a.hrs_est),
      source: a.source || "attendance-confirmation"
    };
  }

  /**
   * Validate via CPDAttendance.buildLogRecord, then append a production-shaped record.
   * Throws if duplicate (checks both evId and eventId on existing logs).
   * Does not write storage — caller persists with SS("logs", …).
   */
  function addAttendanceToProdLog(logs, event, category, hours, Attendance) {
    const A = Attendance || (typeof CPDAttendance !== "undefined" ? CPDAttendance : null);
    if (!A || typeof A.buildLogRecord !== "function") throw new Error("Attendance module unavailable");
    const source = Array.isArray(logs) ? logs.slice() : [];
    if (hasEventLog(source, event && event.id)) throw new Error("This event is already in the CPD log");
    const authored = A.buildLogRecord(event, category, hours);
    source.push(toProdRecord(authored, Date.now()));
    return source;
  }

  return { LOG_KEY, hasEventLog, toProdRecord, addAttendanceToProdLog };
});
