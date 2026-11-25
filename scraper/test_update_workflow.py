"""Structural tests for .github/workflows/update.yml Pages reliability.

Run: python scraper/test_update_workflow.py

Does not trigger GitHub Actions, does not scrape, and does not write
events.json or source_health.json. Parses the workflow with the standard
library only (no PyYAML dependency).
"""
import hashlib
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "update.yml")
EVENTS_JSON = os.path.join(ROOT, "events.json")
HEALTH_JSON = os.path.join(ROOT, "source_health.json")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _job_block(text, job):
    """Return the YAML body of a top-level job (dedented inner text)."""
    m = re.search(
        rf"^  {re.escape(job)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        text,
        re.M | re.S,
    )
    assert m, f"job {job} not found"
    return m.group(1)


def test_workflow_architecture():
    events_before = _sha(EVENTS_JSON)
    health_before = _sha(HEALTH_JSON)
    with open(WORKFLOW, encoding="utf-8") as f:
        text = f.read()

    # 1. Normal Daily CPD path still works (schedule scrapes, then build, then deploy).
    assert 'cron: "0 22 * * *"' in text
    for job in ("update", "pages-build", "pages-deploy"):
        assert re.search(rf"^  {job}:", text, re.M), job
    update = _job_block(text, "update")
    build = _job_block(text, "pages-build")
    deploy = _job_block(text, "pages-deploy")
    assert "Scrape CPD events" in update
    assert "python scraper/fetch.py" in update
    assert "needs: update" in build
    assert "needs: pages-build" in deploy

    # 2. deploy-only skips scraper
    assert "workflow_dispatch:" in text
    assert "deploy_only:" in text
    assert "type: boolean" in text
    assert "default: false" in text
    assert "github.event.inputs.deploy_only != 'true'" in update
    assert "github.event_name == 'schedule'" in update
    # The update/scrape job is not used on push
    assert "github.event_name == 'push'" not in update

    # 3/4. deploy-only / pages jobs do not modify events.json or source_health
    for name, block in (("pages-build", build), ("pages-deploy", deploy)):
        assert "fetch.py" not in block, name
        assert "events.json" not in block, name
        assert "source_health" not in block, name
        assert "git commit" not in block, name
        assert "git push" not in block, name
        assert "newsletter" not in block, name
        assert "scrapling" not in block.lower(), name
        assert "playwright" not in block.lower(), name

    # 5/7. build creates a single github-pages artifact
    assert "actions/upload-pages-artifact@v3" in build
    assert re.search(r"name:\s*github-pages", build)
    assert re.search(r"path:\s*\.", build)
    assert "upload-pages-artifact" not in update
    assert "upload-pages-artifact" not in deploy
    assert len(re.findall(r"actions/upload-pages-artifact@", text)) == 1

    # 6. deploy happens after artifact upload (explicit job dependency)
    assert "needs: pages-build" in deploy
    assert "actions/deploy-pages@v4" in deploy
    assert "deploy-pages" not in build
    assert "deploy-pages" not in update
    assert "artifact_name: github-pages" in deploy

    # 8. deployment permissions are the GitHub Pages minimum
    perm = re.search(r"permissions:\n((?:      .+\n)+)", deploy)
    assert perm, deploy
    perm_text = perm.group(1)
    assert "pages: write" in perm_text
    assert "id-token: write" in perm_text
    assert "contents: write" not in perm_text
    # no extra permission keys
    keys = re.findall(r"^      ([A-Za-z0-9_-]+):", perm_text, re.M)
    assert set(keys) <= {"pages", "id-token", "contents"}
    if "contents" in keys:
        assert "contents: read" in perm_text

    # 9. overlapping deploys serialize safely; scrape is not cancelled by deploy
    assert re.search(
        r"^concurrency:\n  group: cpd-update\n  cancel-in-progress: false",
        text,
        re.M,
    )
    assert "group: cpd-pages-deploy" in deploy
    assert "cancel-in-progress: false" in deploy
    assert "environment:" not in update
    assert "name: github-pages" in deploy

    # 10. failure cannot trigger infinite retries (no automatic retry loop)
    assert "retry-count" not in text.lower()
    assert "max-attempts" not in text.lower()
    assert "continue-on-error" not in text
    assert "pages-deploy-retry" not in text
    assert len(re.findall(r"actions/deploy-pages@", text)) == 1

    # pages-build still runs for deploy-only (update skipped) and push
    assert "needs.update.result == 'skipped'" in build
    assert "needs.update.result == 'success'" in build

    # checkout of the committed snapshot after scrape, not the stale starting SHA
    assert "actions/checkout@v4" in build
    assert "commit_sha" in build
    assert "needs.update.outputs.commit_sha" in build

    assert _sha(EVENTS_JSON) == events_before
    assert _sha(HEALTH_JSON) == health_before
    print("update.yml Pages workflow tests OK")


if __name__ == "__main__":
    test_workflow_architecture()
    print("ALL update workflow tests passed")
