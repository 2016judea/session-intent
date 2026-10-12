"""Site -> Session[]: events from HogQL (always), timeline from rrweb (when a recording exists)."""
import json, pathlib
from . import ph, rrweb

CACHE = pathlib.Path(__file__).resolve().parent.parent / "out" / "cache"

def _q(s):  # HogQL string literal
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

def sessions(site, days=14, limit=200):
    """One row per $session_id on host+path_prefix. filterTestAccounts applied via {filters}."""
    q = f"""select `$session_id` as sid, any(distinct_id) as did, min(timestamp) as t0, max(timestamp) as t1,
      any(properties.`$device_type`) as device, any(properties.`$browser`) as browser,
      any(properties.`$viewport_width`) as vw, any(properties.`$viewport_height`) as vh,
      any(properties.`$referring_domain`) as ref, any(properties.utm_source) as utm,
      groupArray(tuple(toString(timestamp), event, properties.`$pathname`, properties)) as evs
      from events
      where properties.`$host` = {_q(site['host'])} and properties.`$pathname` like {_q(site.get('path_prefix','/') + '%')}
        and timestamp > now() - interval {int(days)} day and `$session_id` != '' and {{filters}}
      group by sid order by t0 desc limit {int(limit)}"""
    d = ph._req("/query/", {"query": {"kind": "HogQLQuery", "query": q, "filters": {"filterTestAccounts": True}},
                           "refresh": "force_blocking"})
    rows = [dict(zip(d["columns"], r)) for r in d["results"]]
    out = []
    for r in rows:
        evs = []
        for ts, name, path, props in sorted(r["evs"]):
            p = json.loads(props) if props else {}
            if isinstance(p, str): p = json.loads(p)
            keep = {k: v for k, v in p.items() if not k.startswith("$") or k in ("$el_text", "$event_type", "$exception_message")}
            keep.pop("token", None)
            evs.append({"ts": ts, "event": name, "path": path, "props": keep})
        out.append({"id": r["sid"], "distinct_id": r["did"], "start": r["t0"], "end": r["t1"], "device": r["device"],
                    "browser": r["browser"], "viewport": [r["vw"], r["vh"]], "referrer": r["ref"], "utm": r["utm"],
                    "events": evs, "replay_url": ph.replay_url(r["sid"])})
    return out

def recordings_index(days=30):
    """ids of every recording in the window (one list call, paginated)."""
    ids, url = set(), f"/session_recordings?limit=200&date_from=-{int(days)}d"
    while url:
        d = ph._req(url)
        ids |= {r["id"] for r in d["results"]}
        url = d.get("next") if d.get("has_next") else None
        if url and not url.startswith("http"): url = None
    return ids

def timeline(sid):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sid}.json"
    if f.exists():
        return json.loads(f.read_text())
    evs = []
    for s in ph.snapshot_sources(sid):
        evs += rrweb.decode(ph.snapshot_blob(sid, s))
    tl = rrweb.timeline(evs)
    tl.pop("nodes", None)
    tl["scrolls"] = tl["scrolls"][-200:]
    f.write_text(json.dumps(tl))
    return tl

def collect(site, days=14):
    rec = recordings_index(max(days, 30))
    out = []
    for s in sessions(site, days):
        s["has_recording"] = s["id"] in rec
        s["timeline"] = None
        if s["has_recording"]:
            try: s["timeline"] = timeline(s["id"])
            except Exception as e: s["timeline_error"] = str(e)[:200]
        out.append(s)
    return out
