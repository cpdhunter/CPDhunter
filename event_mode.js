/* CPD Hunter attendance-mode helpers. Conservative: online=false is UNKNOWN, not face-to-face. Physical-address FACE_TO_FACE is stamped by the scraper from official event-detail pages only; the frontend honours explicit event.mode plus keyword / hybrid / online=true rules. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.CPDEventMode = Object.freeze(api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MODE = Object.freeze({
    ONLINE: "ONLINE",
    FACE_TO_FACE: "FACE_TO_FACE",
    HYBRID: "HYBRID",
    UNKNOWN: "UNKNOWN"
  });

  const VALID = new Set(Object.values(MODE));

  const LABEL = Object.freeze({
    ONLINE: {
      en: "Online",
      zh: "網上",
      icon: "🟢"
    },
    FACE_TO_FACE: {
      en: "Face to Face",
      zh: "面授",
      icon: "🔵"
    },
    HYBRID: {
      en: "Hybrid",
      zh: "混合模式",
      icon: "🟣"
    },
    UNKNOWN: {
      en: "Mode not confirmed",
      zh: "形式未確認",
      icon: "⚪"
    }
  });

  const BONUS = Object.freeze({
    ONLINE: 25,
    HYBRID: 18,
    FACE_TO_FACE: 0,
    UNKNOWN: -3
  });

  const clean = value =>
    String(value ?? "").replace(/\s+/g, " ").trim();

  const HYBRID_PATTERNS = [
    /\bhybrid\b/i,
    /\bblended\b/i,
    /混合(?:模式|形式)?/,
    /線上[及和與/]實體/,
    /網上[及和與/]實體/,
    /online\s*(?:and|&)\s*(?:in[- ]?person|physical|face[- ]?to[- ]?face)/i,
    /(?:in[- ]?person|physical|face[- ]?to[- ]?face)\s*(?:and|&)\s*online/i
  ];

  const ONLINE_PATTERNS = [
    /\bonline(?:\s+event|\s+seminar|\s+course|\s+session)?\b/i,
    /\bwebinar\b/i,
    /\bvirtual\b/i,
    /\bzoom\b/i,
    /\bmicrosoft teams\b/i,
    /\bwebex\b/i,
    /網上(?:活動|講座|課程|研討會)?/,
    /線上(?:活動|講座|課程|研討會)?/,
    /視像(?:會議|講座)?/
  ];

  const FACE_PATTERNS = [
    /\bface[- ]?to[- ]?face\b/i,
    /\bin[- ]?person\b/i,
    /\bphysical attendance\b/i,
    /實體(?:活動|講座|課程|研討會|考察|參觀)?/,
    /面授(?:課程|講座)?/,
    /現場(?:參與|出席|講座)?/
  ];

  function evidenceText(event) {
    return [
      event?.modeText,
      event?.attendanceMode,
      event?.name,
      event?.venue,
      event?.location,
      event?.description,
      event?.registration?.modeText
    ]
      .map(clean)
      .filter(Boolean)
      .join(" | ");
  }

  function any(patterns, text) {
    return patterns.some(pattern => pattern.test(text));
  }

  function inferMode(event) {
    if (!event || typeof event !== "object") {
      return {
        mode: MODE.UNKNOWN,
        confidence: "LOW",
        reason: "no_event"
      };
    }

    const explicit = clean(event.mode)
      .toUpperCase()
      .replace(/[ -]+/g, "_");

    if (VALID.has(explicit)) {
      return {
        mode: explicit,
        confidence: "HIGH",
        reason: "explicit_mode"
      };
    }

    const text = evidenceText(event);

    if (any(HYBRID_PATTERNS, text)) {
      return {
        mode: MODE.HYBRID,
        confidence: "HIGH",
        reason: "explicit_hybrid_text"
      };
    }

    const online = any(ONLINE_PATTERNS, text);
    const face = any(FACE_PATTERNS, text);

    if (online && face) {
      return {
        mode: MODE.HYBRID,
        confidence: "HIGH",
        reason: "online_and_face_evidence"
      };
    }

    if (online) {
      return {
        mode: MODE.ONLINE,
        confidence: "HIGH",
        reason: "explicit_online_text"
      };
    }

    if (face) {
      return {
        mode: MODE.FACE_TO_FACE,
        confidence: "HIGH",
        reason: "explicit_face_text"
      };
    }

    if (event.online === true) {
      return {
        mode: MODE.ONLINE,
        confidence: "MEDIUM",
        reason: "legacy_online_true"
      };
    }

    return {
      mode: MODE.UNKNOWN,
      confidence: "LOW",
      reason:
        event.online === false
          ? "legacy_false_insufficient"
          : "insufficient_evidence"
    };
  }

  function modeOf(event) {
    return inferMode(event).mode;
  }

  function labelFor(mode, language = "zh") {
    const selected = VALID.has(mode) ? mode : MODE.UNKNOWN;
    const label = LABEL[selected];

    return `${label.icon} ${
      language === "en" ? label.en : label.zh
    }`;
  }

  function scoreBonus(event) {
    return BONUS[modeOf(event)];
  }

  function matches(event, selectedModes) {
    if (!selectedModes || selectedModes.length === 0) {
      return true;
    }

    return new Set(selectedModes).has(modeOf(event));
  }

  function sortPriority(event) {
    return {
      ONLINE: 0,
      HYBRID: 1,
      FACE_TO_FACE: 2,
      UNKNOWN: 3
    }[modeOf(event)];
  }

  function compareOnlineFirst(a, b) {
    return (
      sortPriority(a) - sortPriority(b) ||
      String(a.date || "").localeCompare(String(b.date || "")) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    );
  }

  return {
    MODE,
    VALID: [...VALID],
    LABEL,
    BONUS,
    inferMode,
    modeOf,
    labelFor,
    scoreBonus,
    matches,
    compareOnlineFirst
  };
});
