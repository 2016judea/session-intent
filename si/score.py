"""Session x Intent -> Score. Deterministic. A step is reached / missed / unknown.

unknown = the step's evidence needs data this session doesn't have (no recording, no
instrumented event). Never counted as missed."""

def _num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def _event_hits(s, m):
    for e in s["events"]:
        if e["event"] != m["event"]: continue
        if "min" in m:
            v = _num(e["props"].get(m["prop"]))
            if v is None or v < m["min"]: continue
        if "contains" in m and not any(x in str(e["props"].get(m["prop"], "")) for x in m["contains"]): continue
        if "equals" in m and str(e["props"].get(m["prop"])) != str(m["equals"]): continue
        return e["ts"]
    return None

def _available(s, kind, m):
    if m.get("decides_miss") is False:  # a hit proves the step; a non-hit proves nothing
        return False
    tl = s.get("timeline")
    if kind in ("click", "scroll_px", "input"): return tl is not None
    if kind == "event":
        # an instrumented event is decidable if the page's tracker ran (it sends time_on_page on hide)
        return any(e["event"] in m.get("evidence_of_tracker", ["time_on_page"]) for e in s["events"]) or tl is not None
    if kind == "pageview": return True
    return False

def _match(s, kind, m):
    tl = s.get("timeline")
    if kind == "pageview":
        return next((e["ts"] for e in s["events"] if e["event"] == "$pageview" and (e["path"] or "").startswith(m["path"])), None) \
            or (s["events"][0]["ts"] if s["events"] else None)
    if kind == "event":
        return _event_hits(s, m)
    if not tl: return None
    if kind == "scroll_px":
        for t, _id, y in tl["scrolls"]:
            if y >= m["min"]: return f"+{t}s"
        return None
    if kind == "click":
        for c in tl["clicks"]:
            if any(sel.lower() in c["el"].lower() for sel in m["any"]): return f"+{c['t']}s"
        return None
    if kind == "input":
        return next((f"+{i['t']}s" for i in tl["inputs"] if any(sel in i["el"] for sel in m["any"])), None)
    return None

def score(session, intent):
    reached, states = [], []
    for st in intent["steps"]:
        hit, decidable = None, False
        for alt in st["match"]:
            kind = alt["kind"]
            if _available(session, kind, alt): decidable = True
            hit = hit or _match(session, kind, alt)
        state = "reached" if hit else ("missed" if decidable else "unknown")
        states.append({"step": st["id"], "state": state, "at": hit})
        if hit: reached.append(st["id"])
    furthest, left_at = None, None
    for s in states:
        if s["state"] == "reached": furthest = s["step"]
        elif left_at is None: left_at = s["step"] if s["state"] == "missed" else f"{s['step']}?"
    return {"session": session["id"], "steps": states, "furthest_step": furthest, "left_at": left_at,
            "success": any(s["step"] == intent["success"] and s["state"] == "reached" for s in states)}

def flag_bursts(sessions, window_s=120, min_n=3):
    """>= min_n sessions, distinct visitor ids, same device profile, starting within window_s: automation.
    Deterministic and stated in the report; flagged sessions are listed but left out of the counts."""
    from datetime import datetime
    from .render import device_key
    ts = lambda s: datetime.fromisoformat(s["start"].replace("Z", "+00:00")).timestamp()
    by = {}
    for s in sessions: by.setdefault(device_key(s), []).append(s)
    for key, group in by.items():
        group.sort(key=ts)
        for i, s in enumerate(group):
            near = [g for g in group if abs(ts(g) - ts(s)) <= window_s]
            if len({g["distinct_id"] for g in near}) >= min_n:
                s["excluded"] = f"burst: {len(near)} sessions from {key} within {window_s}s, distinct ids (likely QA automation)"
    return sessions

def summary(scores, intent):
    out = []
    for st in intent["steps"]:
        c = {"reached": 0, "missed": 0, "unknown": 0}
        for sc in scores:
            c[next(x["state"] for x in sc["steps"] if x["step"] == st["id"])] += 1
        out.append({"step": st["id"], "label": st["label"], **c})
    lefts = {}
    for sc in scores: lefts[sc["left_at"]] = lefts.get(sc["left_at"], 0) + 1
    return {"n": len(scores), "per_step": out, "left_at": lefts, "success": sum(sc["success"] for sc in scores)}
