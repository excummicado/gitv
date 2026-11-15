"""The check of a live tournament site against what the import reads (services/site_check.py), and the links to
drafts following the site's address (services/darte.py)."""

from app.services import darte, site_check


def test_a_path_is_found_when_any_item_has_it():
    data = {"items": [{"prize": None, "links": []}, {"prize": 100, "links": [{"url": "https://t.me/x"}]}]}
    assert site_check.found(data, "items[].prize")
    assert site_check.found(data, "items[].links[].url")
    assert not site_check.found(data, "items[].currency")
    assert not site_check.found({"items": [{"prize": None}]}, "items[].prize")
    assert site_check.found([{"_id": "a"}], "[]._id")
    assert site_check.found({"users": ["a", "b"]}, "users[]")


def test_a_needed_field_gone_fails_and_an_optional_one_warns():
    result = site_check.CheckResult()
    site_check.check(
        result, "system", {"main": {}, "costs": {"agents": [{"agent": "a", "costs": [1]}]}}, site_check.SYSTEM
    )
    assert (result.failed, result.warned) == (2, 1)  # the weapons' ids and costs; the title
    assert result.lines[0].startswith("FAIL")
    assert "       missing, needed: costs.engines[].engine" in result.lines
    assert "       missing, optional: main.title" in result.lines


def test_a_draft_link_is_built_from_its_key_on_the_site_s_address(monkeypatch):
    monkeypatch.setattr(darte, "SITE", "https://new.example")
    assert (
        darte.draft_url("d1", "k1")
        == "https://new.example/draft?draft_id=d1&session_key=k1&show_costs=true&show_controls"
    )
