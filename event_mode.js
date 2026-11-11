/* CPD Hunter attendance-mode helpers. Conservative: online=false is UNKNOWN, not face-to-face. Physical-address FACE_TO_FACE is stamped by the scraper from official event-detail pages only; the frontend honours explicit event.mode, a scraper venueSource=event_detail stamp, plus keyword / hybrid / online=true rules. Registration-channel wording is never attendance evidence. */
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

  const MODE_EVIDENCE = Object.freeze({
    EXPLICIT_MODE_FIELD: "explicit_mode_field",
    EXPLICIT_ATTENDANCE_TEXT: "explicit_attendance_text",
    EXPLICIT_ONLINE_TEXT: "explicit_online_text",
    EXPLICIT_FACE_TEXT: "explicit_face_text",
    PHYSICAL_ADDRESS_NO_ONLINE: "physical_address_no_online",
    LEGACY_ONLINE_TRUE: "legacy_online_true",
    UNKNOWN: "unknown"
  });

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
    /網上(?:活動|講座|課程|研討會|參與|出席|進行)?/,
    /線上(?:活動|講座|課程|研討會|參與|出席|進行)?/,
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

  const STRUCTURED_HYBRID_RE = /^\s*(?:hybrid|blended|混合(?:模式|形式)?)\s*$/i;
  const STRUCTURED_FACE_RE =
    /\bface[- ]?to[- ]?face\b|\bin[- ]?person\b|\bphysical\b|實體|面授|現場/i;
  const STRUCTURED_ONLINE_RE = /^\s*(?:online|virtual|網上|線上)\s*$/i;

  const LABEL_SPECS = [
    [
      "registration",
      [
        "registration",
        "enrolment",
        "enrollment",
        "報名方法",
        "報名方式",
        "報名途徑",
        "報名須知",
        "報名",
        "登記方法",
        "登記方式",
        "登記"
      ]
    ],
    [
      "mode",
      [
        "attendance mode",
        "attendance",
        "format",
        "上課形式",
        "參與形式",
        "上課模式",
        "進行形式",
        "活動形式",
        "形式",
        "模式",
        "mode"
      ]
    ],
    [
      "venue",
      ["講座地點", "舉辦地點", "venue", "location", "場地", "地點"]
    ]
  ];

  const LABEL_TO_CANON = {};
  LABEL_SPECS.forEach(([canon, labels]) => {
    labels.forEach(label => {
      LABEL_TO_CANON[label.toLowerCase()] = canon;
    });
  });

  const LABEL_ALT = Object.keys(LABEL_TO_CANON)
    .sort((a, b) => b.length - a.length)
    .map(label => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");

  const LABELLED_FIELD_RE = new RegExp(
    `(${LABEL_ALT})\\s*[:：]\\s*(.+?)(?=\\s+(?:${LABEL_ALT})\\s*[:：]|$)`,
    "gis"
  );

  const REGISTRATION_CHANNEL_PATTERNS = [
    /\bonline\s+registrations?\b/gi,
    /\bonline\s+enrolments?\b/gi,
    /\bonline\s+enrollments?\b/gi,
    /\bregister(?:ing|ed)?\s+online\b/gi,
    /\benrol(?:s|ling|led|ment)?\s+online\b/gi,
    /\benroll(?:s|ing|ed|ment)?\s+online\b/gi,
    /\bonline\s+enrol(?:s|ment|ments)?\b/gi,
    /\bonline\s+enroll(?:s|ment|ments)?\b/gi,
    /\bonline\s+applications?\b/gi,
    /\bapply(?:ing|ied)?\s+online\b/gi,
    /網上報名(?:須知|表格|系統|連結|鏈接)?/g,
    /網上登記(?:須知|表格|系統)?/g,
    /網上註冊/g,
    /網上申請/g,
    /線上報名(?:須知|表格|系統|連結|鏈接)?/g,
    /線上登記(?:須知|表格|系統)?/g,
    /線上註冊/g,
    /線上申請/g
  ];

  const STREET_NUMBER_RE = /[道街路里巷]\s*\d+\s*號|\d+\s*號/;
  const ENGLISH_STREET_RE = new RegExp(
    "\\d+\\s+[A-Za-z][\\w.'-]*(?:\\s+[A-Za-z][\\w.'-]*)*\\s+" +
      "(?:Street|Road|Avenue|Drive|Lane|Boulevard|Place|Square|Highway|" +
      "Rd\\.?|St\\.?|Ave\\.?|Dr\\.?|Ln\\.?|Blvd\\.?)\\b",
    "i"
  );
  const NAMED_PLACE_RE = new RegExp(
    "演講廳|講座室|職業健康診所|太空館|圖書館|會議展覽中心|會展中心|" +
      "培訓中心|會議室|會議廳|" +
      "\\bconvention\\s+cent(?:re|er)\\b|\\bexhibition\\s+cent(?:re|er)\\b|" +
      "\\bauditorium\\b|\\blecture\\s+(?:room|theatre|theater|hall)\\b|" +
      "\\b(?:training|conference)\\s+cent(?:re|er)\\b|\\bconference\\s+room\\b",
    "i"
  );
  const LECTURE_ROOM_RE =
    /\b(?:lecture\s+(?:room|theatre|theater|hall)|room)\s+[A-Z0-9]/i;
  const FLOOR_OR_BLOCK_RE = /\d+\s*\/\s*F|\d+\s*樓|\b(?:floor|block|campus)\b/i;

  function any(patterns, text) {
    return patterns.some(pattern => {
      pattern.lastIndex = 0;
      const hit = pattern.test(text);
      pattern.lastIndex = 0;
      return hit;
    });
  }

  function stripRegistrationChannel(text) {
    let out = text || "";
    REGISTRATION_CHANNEL_PATTERNS.forEach(pattern => {
      pattern.lastIndex = 0;
      out = out.replace(pattern, " ");
      pattern.lastIndex = 0;
    });
    return clean(out);
  }

  function parseLabelledFields(...texts) {
    const found = {};
    texts.forEach(raw => {
      const text = String(raw || "");
      if (!text.trim()) return;
      LABELLED_FIELD_RE.lastIndex = 0;
      let match;
      while ((match = LABELLED_FIELD_RE.exec(text))) {
        const canon = LABEL_TO_CANON[match[1].toLowerCase()];
        const value = clean(match[2]);
        if (canon && value && !found[canon]) found[canon] = value;
      }
      LABELLED_FIELD_RE.lastIndex = 0;
    });
    return found;
  }

  function eventSourceTexts(event) {
    if (!event) return [];
    return [
      event.modeText,
      event.attendanceMode,
      event.format,
      event.name || event.title,
      event.venue,
      event.location,
      event.description
    ];
  }

  function labelledFieldsFromEvent(event) {
    if (!event || typeof event !== "object") return {};
    const fields = parseLabelledFields(...eventSourceTexts(event));
    ["attendanceMode", "format"].forEach(key => {
      const raw = clean(event[key]);
      if (raw && !fields.mode) {
        const parsed = parseLabelledFields(raw);
        fields.mode = parsed.mode || raw;
      }
    });
    const modeText = clean(event.modeText);
    if (modeText && !fields.mode) {
      const parsed = parseLabelledFields(modeText);
      if (parsed.mode) fields.mode = parsed.mode;
      else if (mapStructuredMode(modeText)) fields.mode = modeText;
    }
    if (!fields.venue) {
      for (const key of ["venue", "location"]) {
        const raw = clean(event[key]);
        if (!raw) continue;
        const parsed = parseLabelledFields(raw);
        if (parsed.venue) {
          fields.venue = parsed.venue;
          break;
        }
      }
    }
    const reg =
      event.registration && typeof event.registration === "object"
        ? event.registration
        : {};
    const regCandidates = [
      fields.registration,
      event.registrationText,
      reg.modeText,
      reg.channel
    ];
    for (const candidate of regCandidates) {
      const raw = clean(candidate);
      if (!raw) continue;
      const parsed = parseLabelledFields(raw);
      fields.registration = parsed.registration || raw;
      break;
    }
    return fields;
  }

  function mapStructuredMode(value) {
    const t = stripRegistrationChannel(clean(value));
    if (!t) return null;
    STRUCTURED_HYBRID_RE.lastIndex = 0;
    if (STRUCTURED_HYBRID_RE.test(t) || any(HYBRID_PATTERNS, t)) {
      return MODE.HYBRID;
    }
    STRUCTURED_FACE_RE.lastIndex = 0;
    STRUCTURED_ONLINE_RE.lastIndex = 0;
    const face = STRUCTURED_FACE_RE.test(t) || any(FACE_PATTERNS, t);
    const online = STRUCTURED_ONLINE_RE.test(t) || any(ONLINE_PATTERNS, t);
    if (face && online) return MODE.HYBRID;
    if (face) return MODE.FACE_TO_FACE;
    if (online) return MODE.ONLINE;
    return null;
  }

  function dropLabelledRegistration(text) {
    LABELLED_FIELD_RE.lastIndex = 0;
    const out = String(text || "").replace(LABELLED_FIELD_RE, (all, label) => {
      const canon = LABEL_TO_CANON[String(label || "").toLowerCase()];
      return canon === "registration" ? " " : all;
    });
    LABELLED_FIELD_RE.lastIndex = 0;
    return out;
  }

  function attendanceEvidenceText(event) {
    if (!event) return "";
    return eventSourceTexts(event)
      .map(raw => {
        let text = clean(raw);
        if (!text) return "";
        text = dropLabelledRegistration(text);
        return stripRegistrationChannel(text);
      })
      .filter(Boolean)
      .join(" | ");
  }

  function fromEventDetail(event) {
    if (!event || typeof event !== "object") return false;
    const src = clean(
      event.venueSource || event.modeSource || event.evidenceSource
    ).toLowerCase();
    return src === "event_detail" || src === "detail" || src === "official_detail";
  }

  function venueEvidenceText(event) {
    if (!event || typeof event !== "object") return "";
    const fields = labelledFieldsFromEvent(event);
    return [event.venue, event.location, fields.venue]
      .map(clean)
      .filter(Boolean)
      .join(" | ");
  }

  function hasPhysicalAddressInternal(event) {
    if (!event || typeof event !== "object") return false;
    const text = venueEvidenceText(event);
    if (!text) return false;
    if (STREET_NUMBER_RE.test(text) || ENGLISH_STREET_RE.test(text)) return true;
    if (NAMED_PLACE_RE.test(text)) return true;
    if (LECTURE_ROOM_RE.test(text) && FLOOR_OR_BLOCK_RE.test(text)) return true;
    return false;
  }

  function result(mode, confidence, reason, modeEvidence) {
    return {
      mode,
      confidence,
      reason,
      mode_evidence: modeEvidence || MODE_EVIDENCE.UNKNOWN
    };
  }

  function inferMode(event) {
    if (!event || typeof event !== "object") {
      return result(MODE.UNKNOWN, "LOW", "no_event", MODE_EVIDENCE.UNKNOWN);
    }

    const explicit = clean(event.mode)
      .toUpperCase()
      .replace(/[ -]+/g, "_");

    if (VALID.has(explicit)) {
      return result(
        explicit,
        explicit === MODE.UNKNOWN ? "LOW" : "HIGH",
        "explicit_mode",
        explicit === MODE.UNKNOWN
          ? MODE_EVIDENCE.UNKNOWN
          : MODE_EVIDENCE.EXPLICIT_MODE_FIELD
      );
    }

    const structured = mapStructuredMode(labelledFieldsFromEvent(event).mode);
    if (structured) {
      return result(
        structured,
        "HIGH",
        "explicit_mode_field",
        MODE_EVIDENCE.EXPLICIT_MODE_FIELD
      );
    }

    const text = attendanceEvidenceText(event);

    if (any(HYBRID_PATTERNS, text)) {
      return result(
        MODE.HYBRID,
        "HIGH",
        "explicit_hybrid_text",
        MODE_EVIDENCE.EXPLICIT_ATTENDANCE_TEXT
      );
    }

    const online = any(ONLINE_PATTERNS, text);
    const face = any(FACE_PATTERNS, text);
    const physical = fromEventDetail(event) && hasPhysicalAddressInternal(event);

    if (online && (face || physical)) {
      return result(
        MODE.HYBRID,
        "HIGH",
        "online_and_face_evidence",
        MODE_EVIDENCE.EXPLICIT_ATTENDANCE_TEXT
      );
    }

    if (online) {
      return result(
        MODE.ONLINE,
        "HIGH",
        "explicit_online_text",
        MODE_EVIDENCE.EXPLICIT_ONLINE_TEXT
      );
    }

    if (face) {
      return result(
        MODE.FACE_TO_FACE,
        "HIGH",
        "explicit_face_text",
        MODE_EVIDENCE.EXPLICIT_FACE_TEXT
      );
    }

    if (event.online === true) {
      return result(
        MODE.ONLINE,
        "MEDIUM",
        "legacy_online_true",
        MODE_EVIDENCE.LEGACY_ONLINE_TRUE
      );
    }

    if (physical) {
      return result(
        MODE.FACE_TO_FACE,
        "HIGH",
        "physical_address_no_online",
        MODE_EVIDENCE.PHYSICAL_ADDRESS_NO_ONLINE
      );
    }

    return result(
      MODE.UNKNOWN,
      "LOW",
      event.online === false
        ? "legacy_false_insufficient"
        : "insufficient_evidence",
      MODE_EVIDENCE.UNKNOWN
    );
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
    MODE_EVIDENCE,
    inferMode,
    modeOf,
    labelFor,
    scoreBonus,
    matches,
    compareOnlineFirst
  };
});
