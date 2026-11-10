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
  [
    {
      venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號 (維多利亞公園對面/港鐵天后站B出口)"
    },
    "FACE_TO_FACE"
  ],
  [
    {
      venue:
        "Hong Kong Metropolitan University, Lecture Room E0311, 3/F, Block E"
    },
    "FACE_TO_FACE"
  ],
  [{ venue: "Hong Kong Convention Centre" }, "FACE_TO_FACE"],
  [
    {
      venue: "香港中央圖書館演講廳 香港銅鑼灣高士威道66號",
      description: "Also available on Zoom webinar"
    },
    "HYBRID"
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
  "physical_address_no_online"
);

assert(!M.hasPhysicalAddress({ venue: "Kowloon Bay" }));
assert(!M.hasPhysicalAddress({ venue: "HKIE HQ" }));
assert(!M.hasPhysicalAddress({ online: false }));
assert(
  M.hasPhysicalAddress({
    venue: "香港太空館演講廳 九龍尖沙咀梳士巴利道10號"
  })
);

console.log("event_mode tests PASS");
