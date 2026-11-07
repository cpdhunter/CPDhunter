"""Google Forms schema parse + mapping tests. Run: python3 scraper/test_gforms.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gforms import (
    apply_profile_mappings,
    detect_form_status,
    extract_gform_urls,
    map_label_to_profile,
    parse_fb_public_load_data,
    questions_from_fb,
    build_registration_meta,
    _assert_no_pii_in_meta,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "gforms")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_extract_urls():
    html = _load("organiser_with_gform.html")
    urls = extract_gform_urls(html)
    assert urls == ["https://forms.gle/ZYWRkzhxZv86d83C9"], urls
    print("extract_gform_urls OK")


def test_open_simple_parse_and_map():
    html = _load("open_simple.html")
    assert detect_form_status(html, "https://docs.google.com/forms/d/e/x/viewform") == "OPEN"
    data = parse_fb_public_load_data(html)
    assert data is not None
    form_id, questions = questions_from_fb(data)
    assert form_id and form_id.startswith("1FAIpQLS")
    assert any(q["label"] == "Name" for q in questions)
    fields = apply_profile_mappings(questions)
    by_label = {f["label"]: f for f in fields}
    assert by_label["Name"]["profileField"] == "englishName"
    assert by_label["Name"]["safePrefill"] is True
    assert by_label["Email Address"]["profileField"] == "email"
    assert by_label["Mobile Phone Number"]["profileField"] == "phone"
    assert by_label["HKIE Membership Number"]["profileField"] == "hkieNumber"
    # member Y/N must not map
    member = [f for f in fields if "HKIE Member" in f["label"]]
    assert member and member[0]["profileField"] is None
    meta = build_registration_meta(
        destination=f"https://docs.google.com/forms/d/e/{form_id}/viewform",
        form_id=form_id,
        status="OPEN",
        fields=fields,
    )
    _assert_no_pii_in_meta(meta)
    blob = json.dumps(meta)
    assert "value" not in {k for f in meta["fields"] for k in f}
    assert "@" not in blob
    print("open_simple parse/map OK")


def test_split_name_left_manual():
    html = _load("open_split_name.html")
    data = parse_fb_public_load_data(html)
    _, questions = questions_from_fb(data)
    fields = apply_profile_mappings(questions)
    for f in fields:
        lab = f["label"].lower()
        if "surname" in lab or "given name" in lab:
            assert f["profileField"] is None, f
            assert f["safePrefill"] is False
    consent = [f for f in fields if "personal data" in f["label"].lower()]
    assert consent and consent[0]["profileField"] is None
    print("split_name + consent left manual OK")


def test_closed_status():
    html = _load("closed.html")
    st = detect_form_status(
        html,
        "https://docs.google.com/forms/d/e/1FAIpQLScsAr33s4CI_B6Svd-2UNdyBDmOvx_owVT-kKuSXq-6sF8lyQ/closedform",
    )
    assert st == "CLOSED"
    print("closed status OK")


def test_label_mapping_rules():
    assert map_label_to_profile("English Full Name") == "englishName"
    assert map_label_to_profile("Title") is None
    assert map_label_to_profile("Surname") is None
    assert map_label_to_profile("Given Name") is None
    assert map_label_to_profile("Email") == "email"
    assert map_label_to_profile("公司") == "organisation"
    assert map_label_to_profile("職位") == "position"
    assert map_label_to_profile("會員編號") == "hkieNumber"
    assert map_label_to_profile("Emergency Contact Name") is None
    assert map_label_to_profile("Are you HKIE Member?") is None
    assert map_label_to_profile("HKIE Membership No.") == "hkieNumber"
    assert map_label_to_profile("Company Position of the Participant") == "position"
    print("label mapping rules OK")


def test_ambiguous_duplicate_cleared():
    questions = [
        {"entryId": "entry.1", "label": "Email", "type": "SHORT_TEXT", "typeCode": 0, "options": []},
        {"entryId": "entry.2", "label": "Email Address", "type": "SHORT_TEXT", "typeCode": 0, "options": []},
        {"entryId": "entry.3", "label": "Mobile", "type": "SHORT_TEXT", "typeCode": 0, "options": []},
    ]
    fields = apply_profile_mappings(questions)
    emails = [f for f in fields if "email" in f["label"].lower() or f["entryId"] in ("entry.1", "entry.2")]
    assert all(f["profileField"] is None for f in fields if f["entryId"] in ("entry.1", "entry.2"))
    phone = next(f for f in fields if f["entryId"] == "entry.3")
    assert phone["profileField"] == "phone"
    print("ambiguous duplicate cleared OK")


def test_no_profile_values_in_meta():
    fields = [
        {
            "entryId": "entry.1",
            "profileField": "email",
            "label": "Email",
            "type": "SHORT_TEXT",
            "safePrefill": True,
        }
    ]
    meta = build_registration_meta(
        destination="https://docs.google.com/forms/d/e/x/viewform",
        form_id="x",
        status="OPEN",
        fields=fields,
    )
    _assert_no_pii_in_meta(meta)
    try:
        bad = dict(meta)
        bad["fields"] = [dict(fields[0], value="alice@example.com")]
        _assert_no_pii_in_meta(bad)
        raise AssertionError("should have refused")
    except RuntimeError:
        pass
    print("no profile values in meta OK")


if __name__ == "__main__":
    test_extract_urls()
    test_open_simple_parse_and_map()
    test_split_name_left_manual()
    test_closed_status()
    test_label_mapping_rules()
    test_ambiguous_duplicate_cleared()
    test_no_profile_values_in_meta()
    print("ALL gforms tests OK")
