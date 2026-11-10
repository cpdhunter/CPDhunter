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

console.log("event_mode tests PASS");
