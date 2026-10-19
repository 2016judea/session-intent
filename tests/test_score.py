"""Scorer + rrweb decode on synthetic data (no network). Run: python3 -m pytest -q tests"""
import gzip, json
from si import score, rrweb

INTENT = {"steps": [
    {"id": "land", "match": [{"kind": "pageview", "path": "/"}]},
    {"id": "rows", "match": [{"kind": "event", "event": "time_on_page", "prop": "max_depth", "min": 25},
                             {"kind": "scroll_px", "min": 900}]},
    {"id": "take", "match": [{"kind": "event", "event": "download"}, {"kind": "click", "any": ["button#copy"]}]},
    {"id": "proof", "match": [{"kind": "event", "event": "copy", "decides_miss": False}]}],
    "success": "take"}

def sess(events, tl=None, did="a", start="2026-10-12T00:00:00Z", vp=(393, 659)):
    return {"id": did + start, "distinct_id": did, "start": start, "browser": "Mobile Safari", "viewport": list(vp),
            "events": [{"ts": "t", "event": e, "path": "/", "props": p} for e, p in events], "timeline": tl}

def states(sc): return [x["state"] for x in sc["steps"]]

def test_events_only_bounce_is_missed_not_unknown():
    sc = score.score(sess([("$pageview", {}), ("time_on_page", {"seconds": 2, "max_depth": 0})]), INTENT)
    assert states(sc) == ["reached", "missed", "missed", "unknown"] and sc["left_at"] == "rows"

def test_no_tracker_no_recording_is_unknown():
    sc = score.score(sess([("$pageview", {})]), INTENT)
    assert states(sc)[1:3] == ["unknown", "unknown"]

def test_recorded_scroll_and_click_reach_success():
    tl = {"scrolls": [(1.0, 1, 1200)], "clicks": [{"t": 3.0, "el": 'button#copy "Copy list"'}], "inputs": []}
    sc = score.score(sess([("$pageview", {})], tl), INTENT)
    assert states(sc)[:3] == ["reached"] * 3 and sc["success"]

def test_burst_of_distinct_ids_is_excluded_but_one_person_reopening_is_not():
    burst = [sess([], did=f"q{i}", start=f"2026-10-10T18:40:{i:02d}Z", vp=(390, 844)) for i in range(5)]
    reopen = [sess([], did="me", start=f"2026-10-11T{h:02d}:00:00Z") for h in range(5)]
    score.flag_bursts(burst + reopen)
    assert all(s.get("excluded") for s in burst) and not any(s.get("excluded") for s in reopen)

def test_decode_posthog_compressed_full_snapshot():
    node = {"type": 0, "id": 1, "childNodes": [{"type": 2, "id": 2, "tagName": "button", "attributes": {"id": "copy"},
            "childNodes": [{"type": 3, "id": 3, "textContent": "Copy list"}]}]}
    z = gzip.compress(json.dumps({"node": node, "initialOffset": {"top": 0, "left": 0}}).encode()).decode("latin-1")
    lines = [["w", {"type": 4, "timestamp": 0, "data": {"href": "https://x/", "width": 393, "height": 659}}],
             ["w", {"type": 2, "timestamp": 1, "cv": "2024-10", "data": z}],
             ["w", {"type": 3, "timestamp": 2000, "data": {"source": 2, "type": 2, "id": 3}}]]
    blob = "\n".join(json.dumps(l) for l in lines).encode()
    tl = rrweb.timeline(rrweb.decode(blob))
    assert tl["clicks"][0]["el"] == 'button#copy "Copy list"' and tl["viewport"] == [393, 659]

def test_left_at_is_where_the_session_ended_not_a_step_it_skipped():
    # events-only: lands, scrolls (max_depth 30), skips the optional narrow, downloads
    intent = {"steps": INTENT["steps"][:2] + [{"id": "narrow", "optional": True,
              "match": [{"kind": "event", "event": "filter"}]}] + INTENT["steps"][2:], "success": "take"}
    sc = score.score(sess([("$pageview", {}), ("time_on_page", {"seconds": 40, "max_depth": 30}), ("download", {})]), intent)
    assert states(sc) == ["reached", "reached", "missed", "reached", "unknown"]
    assert sc["success"] and sc["furthest_step"] == "take" and sc["left_at"] is None
    # a required step skipped on the way to a later one is not where they left either
    sc = score.score(sess([("$pageview", {}), ("time_on_page", {"seconds": 3, "max_depth": 0}), ("download", {})]), intent)
    assert states(sc)[:4] == ["reached", "missed", "missed", "reached"] and sc["left_at"] is None
    # but a session that stops at the required step still reports it
    sc = score.score(sess([("$pageview", {}), ("time_on_page", {"seconds": 3, "max_depth": 0})]), intent)
    assert sc["left_at"] == "rows"
    # an optional step is never the answer to "where did they leave"
    sc = score.score(sess([("$pageview", {}), ("time_on_page", {"seconds": 40, "max_depth": 30})]), intent)
    assert sc["left_at"] == "take"
