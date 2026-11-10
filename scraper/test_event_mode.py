"""Conservative event-mode classification — mirrors event_mode.js rules."""
import unittest

from event_mode import infer_mode, mode_of, attach_mode, MODE_UNKNOWN


class EventModeTests(unittest.TestCase):
    def test_explicit_modes(self):
        self.assertEqual(mode_of({"mode": "ONLINE"}), "ONLINE")
        self.assertEqual(mode_of({"mode": "FACE_TO_FACE"}), "FACE_TO_FACE")
        self.assertEqual(mode_of({"mode": "HYBRID"}), "HYBRID")
        self.assertEqual(mode_of({"mode": "UNKNOWN"}), "UNKNOWN")

    def test_text_evidence(self):
        self.assertEqual(mode_of({"name": "Free structural engineering webinar"}), "ONLINE")
        self.assertEqual(mode_of({"venue": "Microsoft Teams"}), "ONLINE")
        self.assertEqual(mode_of({"name": "Hybrid seminar", "venue": "CIC-ZCP and Zoom"}), "HYBRID")
        self.assertEqual(mode_of({"description": "Face-to-face workshop"}), "FACE_TO_FACE")
        self.assertEqual(mode_of({"venue": "Zoom"}), "ONLINE")

    def test_online_false_is_unknown(self):
        self.assertEqual(mode_of({"venue": "Kowloon Bay"}), "UNKNOWN")
        self.assertEqual(mode_of({"online": False, "venue": "HKIE"}), "UNKNOWN")
        self.assertEqual(mode_of({"is_online": False, "venue": "HKIE HQ"}), "UNKNOWN")
        self.assertEqual(mode_of({}), "UNKNOWN")
        r = infer_mode({"online": False, "org": "HKIE"})
        self.assertEqual(r["mode"], "UNKNOWN")
        self.assertEqual(r["reason"], "legacy_false_insufficient")

    def test_legacy_online_true(self):
        self.assertEqual(mode_of({"online": True}), "ONLINE")
        self.assertEqual(mode_of({"is_online": True}), "ONLINE")
        self.assertEqual(infer_mode({"online": True})["confidence"], "MEDIUM")

    def test_attach_mode_omits_unknown(self):
        ev = {"name": "Seminar at Kowloon Bay", "online": False}
        attach_mode(ev)
        self.assertNotIn("mode", ev)
        ev2 = {"name": "Online Seminar on Safety"}
        attach_mode(ev2)
        self.assertEqual(ev2["mode"], "ONLINE")

    def test_does_not_infer_face_from_address_or_org(self):
        self.assertEqual(mode_of({"venue": "Hong Kong Convention Centre"}), "UNKNOWN")
        self.assertEqual(mode_of({"org": "HKIE", "source": "HKIE Events"}), "UNKNOWN")
        self.assertEqual(mode_of({"online": False, "name": "Annual Seminar"}), "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
