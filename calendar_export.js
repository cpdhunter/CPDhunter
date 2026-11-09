/* CPD Hunter - client-side iCalendar export. No profile data, OAuth, or network use. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CPDCalendarExport = Object.freeze(api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const pad = n => String(n).padStart(2, "0");
  const nowStamp = d => `${d.getUTCFullYear()}${pad(d.getUTCMonth()+1)}${pad(d.getUTCDate())}T${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}Z`;
  const dateOnly = s => /^\d{4}-\d{2}-\d{2}$/.test(String(s || ""));
  const timeOnly = s => /^([01]\d|2[0-3]):[0-5]\d$/.test(String(s || ""));
  function escapeText(value) {
    return String(value ?? "")
      .replace(/\\/g, "\\\\")
      .replace(/\r?\n/g, "\\n")
      .replace(/,/g, "\\,")
      .replace(/;/g, "\\;");
  }
  function foldLine(line) {
    // RFC 5545 limit is 75 octets. UTF-8 safe folding is intentionally conservative.
    const out = [];
    let buf = "", bytes = 0;
    for (const ch of String(line)) {
      const size = new TextEncoder().encode(ch).length;
      if (bytes + size > 73 && buf) { out.push(buf); buf = " " + ch; bytes = 1 + size; }
      else { buf += ch; bytes += size; }
    }
    if (buf) out.push(buf);
    return out.join("\r\n");
  }
  function compactDate(date) { return String(date).replaceAll("-", ""); }
  function compactLocal(date, time) { return `${compactDate(date)}T${String(time).replace(":", "")}00`; }
  function parseTimeRange(event) {
    const directStart = event.startTime || event.start_time || "";
    const directEnd = event.endTime || event.end_time || "";
    if (timeOnly(directStart)) return {start: directStart, end: timeOnly(directEnd) ? directEnd : ""};
    const text = String(event.time || "").trim();
    const m = text.match(/\b([01]\d|2[0-3]):([0-5]\d)\s*[-–—]\s*([01]\d|2[0-3]):([0-5]\d)\b/);
    if (m) return {start: `${m[1]}:${m[2]}`, end: `${m[3]}:${m[4]}`};
    const one = text.match(/\b([01]\d|2[0-3]):([0-5]\d)\b/);
    return one ? {start: `${one[1]}:${one[2]}`, end: ""} : {start:"", end:""};
  }
  function safeUrl(value) {
    try { const u = new URL(String(value || "")); return /^https?:$/.test(u.protocol) ? u.href : ""; }
    catch { return ""; }
  }
  function safeFilename(name) {
    const base = String(name || "event").normalize("NFKD")
      .replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 70) || "event";
    return `cpd-hunter-${base.toLowerCase()}.ics`;
  }
  function eventDescription(event, effectiveCategory) {
    const lines = [
      event.org ? `Organiser: ${event.org}` : "",
      effectiveCategory ? `CPD category: ${effectiveCategory}` : "",
      event.hrs != null ? `CPD hours: ${event.hrs}${event.hrs_est ? " (estimated; verify with organiser)" : " (stated by organiser)"}` : "CPD hours: not stated",
      safeUrl(event.url) ? `Official event: ${safeUrl(event.url)}` : "",
      "Please verify final event details with the organiser."
    ].filter(Boolean);
    return lines.join("\n");
  }
  function createICS(event, options = {}) {
    if (!event || !dateOnly(event.date)) throw new Error("Event requires a valid YYYY-MM-DD date");
    const title = String(event.name || "").trim();
    if (!title) throw new Error("Event title is required");
    const id = String(event.id || `${title}-${event.date}`).replace(/[^A-Za-z0-9._-]/g, "-");
    const times = parseTimeRange(event);
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CPD Hunter//CPD Event//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "BEGIN:VEVENT"];
    lines.push(`UID:${escapeText(id)}@cpdhunter`);
    lines.push(`DTSTAMP:${nowStamp(options.now instanceof Date ? options.now : new Date())}`);
    if (times.start) {
      lines.push(`DTSTART;TZID=Asia/Hong_Kong:${compactLocal(event.date, times.start)}`);
      if (times.end) lines.push(`DTEND;TZID=Asia/Hong_Kong:${compactLocal(event.date, times.end)}`);
    } else {
      const start = new Date(`${event.date}T00:00:00Z`);
      const next = new Date(start.getTime() + 86400000).toISOString().slice(0,10);
      lines.push(`DTSTART;VALUE=DATE:${compactDate(event.date)}`);
      lines.push(`DTEND;VALUE=DATE:${compactDate(next)}`);
    }
    lines.push(`SUMMARY:${escapeText(title)}`);
    if (event.venue || event.location) lines.push(`LOCATION:${escapeText(event.venue || event.location)}`);
    lines.push(`DESCRIPTION:${escapeText(eventDescription(event, options.category || event.cat || event.type))}`);
    const url = safeUrl(event.url); if (url) lines.push(`URL:${url}`);
    lines.push("BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", `DESCRIPTION:${escapeText(`Reminder: ${title}`)}`, "END:VALARM", "END:VEVENT", "END:VCALENDAR");
    return lines.map(foldLine).join("\r\n") + "\r\n";
  }
  function downloadICS(event, options = {}) {
    const text = createICS(event, options);
    const blob = new Blob([text], {type:"text/calendar;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = safeFilename(event.name); a.rel = "noopener"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return {escapeText, parseTimeRange, safeFilename, createICS, downloadICS};
});
