"""Conservative event-mode classification — scraper rules, detail-page physical venue."""
import unittest

from event_mode import (
    infer_mode,
    mode_of,
    attach_mode,
    has_physical_address,
    from_event_detail,
    MODE_UNKNOWN,
)

LABOUR_DETAIL_VENUE = "香港中央圖書館演講廳"
LABOUR_LISTING_VENUE = (
    "香港中央圖書館演講廳 香港銅鑼灣高士威道66號 (維多利亞公園對面/港鐵天后站B出口)"
)
DETAIL = {"venueSource": "event_detail"}


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

    def test_01_detail_physical_venue_no_online_is_face_to_face(self):
        ev = {"venue": LABOUR_DETAIL_VENUE, **DETAIL}
        self.assertEqual(mode_of(ev), "FACE_TO_FACE")
        self.assertEqual(infer_mode(ev)["reason"], "physical_address_no_online")
        stamped = {"venue": LABOUR_DETAIL_VENUE, **DETAIL}
        attach_mode(stamped)
        self.assertEqual(stamped["mode"], "FACE_TO_FACE")

    def test_02_detail_physical_venue_plus_zoom_is_hybrid(self):
        self.assertEqual(
            mode_of({
                "venue": LABOUR_DETAIL_VENUE,
                "description": "Also available on Zoom",
                **DETAIL,
            }),
            "HYBRID",
        )

    def test_03_detail_physical_venue_plus_teams_is_hybrid(self):
        self.assertEqual(
            mode_of({
                "venue": LABOUR_DETAIL_VENUE,
                "description": "Join on Microsoft Teams",
                **DETAIL,
            }),
            "HYBRID",
        )

    def test_04_detail_address_plus_word_online_is_hybrid(self):
        self.assertEqual(
            mode_of({
                "venue": "香港中央圖書館演講廳 香港銅鑼灣高士威道66號",
                "description": "Online attendance is also offered",
                **DETAIL,
            }),
            "HYBRID",
        )

    def test_05_organisation_name_only_is_unknown(self):
        self.assertEqual(mode_of({"venue": "HKIE"}), "UNKNOWN")
        self.assertEqual(mode_of({"venue": "HKIE HQ", **DETAIL}), "UNKNOWN")
        self.assertEqual(mode_of({"org": "OSHC", "source": "OSHC Seminars & Conferences"}), "UNKNOWN")
        self.assertFalse(has_physical_address({"venue": "CIC"}))

    def test_06_district_only_is_unknown(self):
        self.assertEqual(mode_of({"venue": "Kowloon Bay"}), "UNKNOWN")
        self.assertEqual(mode_of({"venue": "銅鑼灣", **DETAIL}), "UNKNOWN")
        self.assertEqual(mode_of({"venue": "Hong Kong", **DETAIL}), "UNKNOWN")

    def test_07_online_false_only_is_unknown(self):
        self.assertEqual(mode_of({"online": False}), "UNKNOWN")
        self.assertEqual(mode_of({"online": False, "name": "Annual Seminar"}), "UNKNOWN")
        self.assertEqual(infer_mode({"online": False})["reason"], "legacy_false_insufficient")

    def test_08_explicit_webinar_no_address_is_online(self):
        self.assertEqual(mode_of({"name": "Safety webinar"}), "ONLINE")

    def test_09_explicit_face_to_face_is_face_to_face(self):
        self.assertEqual(mode_of({"description": "Face-to-face workshop"}), "FACE_TO_FACE")

    def test_10_listing_page_address_must_not_classify(self):
        listing = {"venue": LABOUR_LISTING_VENUE}
        self.assertEqual(mode_of(listing), "UNKNOWN")
        self.assertFalse(from_event_detail(listing))
        attached = dict(listing)
        attach_mode(attached)
        self.assertNotIn("mode", attached)
        # CIPHE-style calendar listing venue must not stamp FACE_TO_FACE
        ciphe = {
            "venue": "Hong Kong Metropolitan University, Lecture Room E0311, 3/F, Block E, Jockey Club Campus, 81 Chung Hau Street, Ho Man Tin, Kowloon"
        }
        self.assertEqual(mode_of(ciphe), "UNKNOWN")
        self.assertEqual(mode_of({"venue": "Hong Kong Convention Centre"}), "UNKNOWN")

    def test_11_event_detail_labelled_venue_and_address_is_face_to_face(self):
        ev = {
            "venue": "香港中央圖書館演講廳 香港銅鑼灣高士威道66號",
            "modeText": "講座地點 香港中央圖書館演講廳",
            **DETAIL,
        }
        self.assertEqual(mode_of(ev), "FACE_TO_FACE")
        self.assertTrue(from_event_detail(ev))

    def test_12_event_detail_venue_plus_online_option_is_hybrid(self):
        ev = {
            "venue": LABOUR_DETAIL_VENUE,
            "description": "This talk is also a webinar",
            **DETAIL,
        }
        self.assertEqual(mode_of(ev), "HYBRID")


TQM_DETAIL_VENUE = (
    "TQM Training Centre, 11/F Lockhart Centre, 301-307 Lockhart Road, Hong Kong"
)


class RegistrationChannelTests(unittest.TestCase):
    """Registration wording is a channel, not attendance mode."""

    def test_01_mode_face_to_face_online_registration(self):
        ev = {"description": "Mode: Face to Face\nRegistration: Online Registration"}
        self.assertEqual(mode_of(ev), "FACE_TO_FACE")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "explicit_mode_field")

    def test_02_detail_venue_online_registration_no_attendance_is_face(self):
        ev = {
            "description": (
                "Venue: " + TQM_DETAIL_VENUE + "\n"
                "Registration: Online Registration"
            ),
            **DETAIL,
        }
        self.assertEqual(mode_of(ev), "FACE_TO_FACE")
        self.assertEqual(infer_mode(ev)["reason"], "physical_address_no_online")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "physical_address_no_online")

    def test_03_mode_online_plus_online_registration(self):
        ev = {"description": "Mode: Online\nRegistration: Online Registration"}
        self.assertEqual(mode_of(ev), "ONLINE")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "explicit_mode_field")

    def test_04_mode_hybrid_plus_online_registration(self):
        ev = {"description": "Mode: Hybrid\nRegistration: Online Registration"}
        self.assertEqual(mode_of(ev), "HYBRID")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "explicit_mode_field")

    def test_05_online_registration_only_is_unknown(self):
        ev = {"description": "Registration: Online Registration"}
        self.assertEqual(mode_of(ev), "UNKNOWN")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "unknown")
        self.assertEqual(
            mode_of({"registration": {"modeText": "Online Registration"}}),
            "UNKNOWN",
        )
        self.assertEqual(mode_of({"description": "Online Enrolment"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "Online Enrollment"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "Online Application"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "網上報名"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "網上登記"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "線上報名"}), "UNKNOWN")

    def test_06_register_online_only_is_unknown(self):
        self.assertEqual(mode_of({"name": "Register Online"}), "UNKNOWN")
        self.assertEqual(mode_of({"description": "Register Online"}), "UNKNOWN")

    def test_07_online_webinar_register_online_is_online(self):
        ev = {"name": "Online Webinar - Register Online"}
        self.assertEqual(mode_of(ev), "ONLINE")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "explicit_online_text")

    def test_08_detail_physical_venue_plus_zoom_is_hybrid(self):
        ev = {
            "venue": TQM_DETAIL_VENUE,
            "description": "Join via Zoom",
            **DETAIL,
        }
        self.assertEqual(mode_of(ev), "HYBRID")
        self.assertEqual(infer_mode(ev)["mode_evidence"], "explicit_attendance_text")

    def test_09_detail_physical_address_only_is_face_to_face(self):
        ev = {"venue": TQM_DETAIL_VENUE, **DETAIL}
        self.assertEqual(mode_of(ev), "FACE_TO_FACE")
        self.assertEqual(infer_mode(ev)["reason"], "physical_address_no_online")

    def test_10_listing_organisation_address_is_unknown(self):
        self.assertEqual(mode_of({"venue": "HKIE HQ"}), "UNKNOWN")
        self.assertEqual(mode_of({"venue": "TQM Consultants"}), "UNKNOWN")
        listing = {
            "venue": (
                "Hong Kong Metropolitan University, Lecture Room E0311, 3/F, "
                "Block E, Jockey Club Campus, 81 Chung Hau Street, Ho Man Tin, Kowloon"
            )
        }
        self.assertEqual(mode_of(listing), "UNKNOWN")
        self.assertFalse(from_event_detail(listing))




if __name__ == "__main__":
    unittest.main()
