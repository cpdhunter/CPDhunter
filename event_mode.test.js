const assert = require("assert");
const M = require("./event_mode");

const cases = [
  [{ mode: "ONLINE" }, "ONLINE"],
  [{ mode: "FACE_TO_FACE" }, "FACE_TO_FACE"],
  [{ mode: "HYBRID" }, "HYBRID"],
  [{ name: "Free structural engineering webinar" }, "ONLINE"],
  [{ venue: "Microsoft Teams" }, "ONLINE"],
  [
    {
      name: "Hybrid seminar",
      venue: "CIC-ZCP and Zoom"
    },
    "HYBRID"
  ],
  [
    {
      description: "Face-to-face workshop"
    },
    "FACE_TO_FACE"
  ],
  [{ venue: "Kowloon Bay" }, "UNKNOWN"],
  [
    {
      online: false,
      venue: "HKIE"
    },
    "UNKNOWN"
  ],
  [{ online: true }, "ONLINE"],
  [{}, "UNKNOWN"],
  [{ venue: "Hong Kong" }, "UNKNOWN"],
  [{ venue: "銅鑼灣" }, "UNKNOWN"],
  // Frontend must not infer FACE_TO_FACE from a listing/raw venue.
  [
    {
      venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號 (維多利亞公園對面/港鐵天后站B出口)"
    },
    "UNKNOWN"
  ],
  [
    {
      venue:
        "Hong Kong Metropolitan University, Lecture Room E0311, 3/F, Block E"
    },
    "UNKNOWN"
  ],
  [{ venue: "Hong Kong Convention Centre" }, "UNKNOWN"],
  // Zoom keyword still applies; listing address does not create HYBRID in the frontend.
  [
    {
      venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號",
      description: "Also available on Zoom webinar"
    },
    "ONLINE"
  ],
  // Scraper-stamped mode is honoured.
  [
    {
      mode: "FACE_TO_FACE",
      venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號"
    },
    "FACE_TO_FACE"
  ]
];

for (const [event, expected] of cases) {
  assert.equal(
    M.modeOf(event),
    expected,
    JSON.stringify(event)
  );
}

assert.equal(M.scoreBonus({ mode: "ONLINE" }), 25);
assert.equal(M.scoreBonus({ mode: "HYBRID" }), 18);
assert.equal(M.scoreBonus({ mode: "FACE_TO_FACE" }), 0);
assert.equal(M.scoreBonus({}), -3);

assert(M.matches({ mode: "ONLINE" }, ["ONLINE"]));

assert(
  !M.matches(
    { mode: "FACE_TO_FACE" },
    ["ONLINE", "HYBRID"]
  )
);

assert(M.matches({}, []));

const sorted = [
  { mode: "UNKNOWN", name: "u" },
  { mode: "FACE_TO_FACE", name: "f" },
  { mode: "HYBRID", name: "h" },
  { mode: "ONLINE", name: "o" }
].sort(M.compareOnlineFirst);

assert.deepEqual(
  sorted.map(M.modeOf),
  [
    "ONLINE",
    "HYBRID",
    "FACE_TO_FACE",
    "UNKNOWN"
  ]
);

assert(M.labelFor("ONLINE").includes("網上"));

assert(
  M.labelFor("FACE_TO_FACE", "en")
    .includes("Face to Face")
);

assert.equal(
  M.inferMode({
    venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號"
  }).reason,
  "insufficient_evidence"
);

assert.equal(typeof M.hasPhysicalAddress, "undefined");

const TQM_DETAIL_VENUE =
  "TQM Training Centre, 11/F Lockhart Centre, 301-307 Lockhart Road, Hong Kong";

const registrationCases = [
  // 1. Mode: Face to Face + Registration: Online Registration
  [
    { description: "Mode: Face to Face\nRegistration: Online Registration" },
    "FACE_TO_FACE"
  ],
  // 2. Event-detail physical venue + Online Registration, no attendance wording
  [
    {
      description:
        "Venue: " +
        TQM_DETAIL_VENUE +
        "\nRegistration: Online Registration",
      venueSource: "event_detail"
    },
    "FACE_TO_FACE"
  ],
  // 3. Mode: Online + Registration: Online Registration
  [
    { description: "Mode: Online\nRegistration: Online Registration" },
    "ONLINE"
  ],
  // 4. Mode: Hybrid + Registration: Online Registration
  [
    { description: "Mode: Hybrid\nRegistration: Online Registration" },
    "HYBRID"
  ],
  // 5. Registration: Online Registration only
  [
    { description: "Registration: Online Registration" },
    "UNKNOWN"
  ],
  [
    { registration: { modeText: "Online Registration" } },
    "UNKNOWN"
  ],
  [{ description: "Online Enrolment" }, "UNKNOWN"],
  [{ description: "Online Enrollment" }, "UNKNOWN"],
  [{ description: "Online Application" }, "UNKNOWN"],
  [{ description: "網上報名" }, "UNKNOWN"],
  [{ description: "網上登記" }, "UNKNOWN"],
  [{ description: "線上報名" }, "UNKNOWN"],
  // 6. Register Online only
  [{ name: "Register Online" }, "UNKNOWN"],
  [{ description: "Register Online" }, "UNKNOWN"],
  // 7. Online Webinar - Register Online
  [{ name: "Online Webinar - Register Online" }, "ONLINE"],
  // 8. Detail-sourced physical venue + Zoom joining option
  [
    {
      venue: TQM_DETAIL_VENUE,
      description: "Join via Zoom",
      venueSource: "event_detail"
    },
    "HYBRID"
  ],
  // 9. Physical address only from event-specific detail page
  [
    { venue: TQM_DETAIL_VENUE, venueSource: "event_detail" },
    "FACE_TO_FACE"
  ],
  // 10. Generic listing-page organisation address
  [{ venue: "HKIE HQ" }, "UNKNOWN"],
  [{ venue: "TQM Consultants" }, "UNKNOWN"],
  [
    {
      venue:
        "Hong Kong Metropolitan University, Lecture Room E0311, 3/F, Block E, Jockey Club Campus, 81 Chung Hau Street, Ho Man Tin, Kowloon"
    },
    "UNKNOWN"
  ]
];

for (const [event, expected] of registrationCases) {
  assert.equal(
    M.modeOf(event),
    expected,
    JSON.stringify(event)
  );
}

assert.equal(
  M.inferMode({
    description: "Mode: Face to Face\nRegistration: Online Registration"
  }).mode_evidence,
  "explicit_mode_field"
);
assert.equal(
  M.inferMode({ name: "Register Online" }).mode_evidence,
  "unknown"
);
assert.equal(
  M.inferMode({ name: "Online Webinar - Register Online" }).mode_evidence,
  "explicit_online_text"
);

console.log("event_mode tests PASS");
