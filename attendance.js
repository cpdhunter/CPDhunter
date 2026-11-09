/* CPD Hunter - browser-local attendance and CPD-log bridge. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CPDAttendance = Object.freeze(api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const KEY = "cpdAttendance";
  const VALID = new Set(["unknown", "attended", "not_attended"]);
  const parse = (raw, fallback) => { try { const v=JSON.parse(raw); return v && typeof v === "object" && !Array.isArray(v) ? v : fallback; } catch { return fallback; } };
  const clean = (value, max=500) => String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, "").trim().slice(0,max);
  function load(storage = localStorage) { return parse(storage.getItem(KEY), {}); }
  function get(eventId, storage = localStorage) { return load(storage)[String(eventId)] || {state:"unknown"}; }
  function set(eventId, state, storage = localStorage) {
    if (!VALID.has(state)) throw new Error("Invalid attendance state");
    const all=load(storage); all[String(eventId)]={state,ts:new Date().toISOString()}; storage.setItem(KEY,JSON.stringify(all)); return all[String(eventId)];
  }
  function clear(eventId, storage = localStorage) { const all=load(storage); delete all[String(eventId)]; storage.setItem(KEY,JSON.stringify(all)); }
  function endMoment(event) {
    if (!event || !/^\d{4}-\d{2}-\d{2}$/.test(String(event.date||""))) return null;
    const range=String(event.time||"").match(/\b([01]\d|2[0-3]):[0-5]\d\s*[-–—]\s*(([01]\d|2[0-3]):[0-5]\d)\b/);
    const one=String(event.time||"").match(/\b([01]\d|2[0-3]):[0-5]\d\b/);
    const t=range ? range[2] : one ? one[0] : "23:59";
    return new Date(`${event.date}T${t}:00+08:00`);
  }
  function shouldPrompt(event, registrationState, now = new Date(), storage = localStorage) {
    if (registrationState !== "registered_manual") return false;
    const end=endMoment(event); if (!end || end >= now) return false;
    return get(event.id,storage).state === "unknown";
  }
  function buildLogRecord(event, category, hours) {
    const h=Number(hours);
    if (!Number.isFinite(h) || h <= 0 || h > 24) throw new Error("Enter valid CPD hours");
    return {
      id:`event:${clean(event.id,120)}`,
      eventId:clean(event.id,120),
      name:clean(event.name,500),
      date:clean(event.date,10),
      cat:clean(category,20),
      hours:h,
      hrs_est:Boolean(event.hrs_est),
      source:"attendance-confirmation"
    };
  }
  function hasEventLog(logs,eventId) { return Array.isArray(logs) && logs.some(r=>String(r.eventId||"")===String(eventId)); }
  function addToLog(logs,event,category,hours,{allowDuplicate=false}={}) {
    const source=Array.isArray(logs)?logs.slice():[];
    if (!allowDuplicate && hasEventLog(source,event.id)) throw new Error("This event is already in the CPD log");
    source.push(buildLogRecord(event,category,hours)); return source;
  }
  return {KEY,VALID:[...VALID],load,get,set,clear,endMoment,shouldPrompt,buildLogRecord,hasEventLog,addToLog};
});
