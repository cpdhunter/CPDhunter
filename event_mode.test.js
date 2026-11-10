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
  [{}, "UNKNOWN"]
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

console.log("event_mode tests PASS");
