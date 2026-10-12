"""Decode PostHog rrweb blobs and compress them into a timeline.

rrweb enums mirrored from rrweb-io/rrweb (MIT), packages/types/src/index.ts.
PostHog 'cv: 2024-10' compression: some string fields are gzip bytes carried as latin-1.
"""
import gzip, json

FULL, INCR, META, CUSTOM, PLUGIN = 2, 3, 4, 5, 6
MUTATION, MOUSEMOVE, MOUSE, SCROLL, VIEWPORT, INPUT, TOUCHMOVE = 0, 1, 2, 3, 4, 5, 6
CLICK_TYPES = {2: "click", 4: "dblclick", 7: "touchend", 9: "touchstart"}  # MouseInteractions

def _unz(v):
    if isinstance(v, str) and v[:2] == "\x1f\x8b":
        return json.loads(gzip.decompress(v.encode("latin-1")))
    return v

def decode(blob: bytes):
    out = []
    for line in blob.decode("utf-8").split("\n"):
        if not line.strip():
            continue
        o = json.loads(line)
        ev = o[1] if isinstance(o, list) else o
        if ev.get("cv"):
            d = _unz(ev.get("data"))
            if isinstance(d, dict):
                d = {k: _unz(x) for k, x in d.items()}
            ev["data"] = d
        out.append(ev)
    out.sort(key=lambda e: e["timestamp"])
    return out

class Nodes:
    """id -> serialized node, so a click on id 412 reads as 'button#copy "Copy list"'."""
    def __init__(self):
        self.n, self.parent = {}, {}
    def add(self, node, parent=None):
        self.n[node["id"]] = node
        if parent is not None:
            self.parent[node["id"]] = parent
        for c in node.get("childNodes", []) or []:
            self.add(c, node["id"])
    def text(self, nid, limit=80):
        node, parts = self.n.get(nid), []
        def walk(x):
            if len(" ".join(parts)) > limit: return
            if x.get("type") == 3: parts.append((x.get("textContent") or "").strip())
            for c in x.get("childNodes", []) or []: walk(c)
        if node: walk(node)
        return " ".join(p for p in parts if p)[:limit]
    def label(self, nid):
        node = self.n.get(nid)
        if not node: return f"#node{nid}"
        if node.get("type") == 3:  # text node: report its parent element
            return self.label(self.parent.get(nid, -1))
        a = node.get("attributes", {}) or {}
        s = node.get("tagName", "?")
        if a.get("id"): s += "#" + a["id"]
        if a.get("class"): s += "." + ".".join(str(a["class"]).split()[:2])
        t = self.text(nid) or a.get("aria-label") or a.get("href") or ""
        return f'{s} "{t}"' if t else s
    def ancestors(self, nid):
        out = []
        while nid in self.n:
            out.append(nid); nid = self.parent.get(nid)
            if nid is None: break
        return out
    def matches(self, nid, sel):
        """Tiny selector: 'tag', '#id', '.class', 'tag#id', 'tag.class', or 'text:Copy list'. Checks ancestors."""
        if sel.startswith("text:"):
            want = sel[5:].lower()
            return any(want in self.text(a, 200).lower() for a in self.ancestors(nid))
        tag, _, rest = sel.partition("#") if "#" in sel else (sel.split(".")[0], "", "")
        for a in self.ancestors(nid):
            node = self.n[a]; at = node.get("attributes", {}) or {}
            t = node.get("tagName", "")
            if "#" in sel:
                if (not tag or t == tag) and at.get("id") == rest: return True
            elif "." in sel:
                tg, cls = sel.split(".", 1)
                if (not tg or t == tg) and cls in str(at.get("class", "")).split(): return True
            elif t == sel: return True
        return False

def timeline(events):
    """Return dict: viewport, pages[], clicks[], inputs[], scroll samples, errors, custom, active_s."""
    nodes = Nodes()
    t0 = events[0]["timestamp"] if events else 0
    vw = vh = None; href = None
    pages, clicks, inputs, errors, custom, scrolls = [], [], [], [], [], []
    last_click = {}
    active = set()
    for e in events:
        t = (e["timestamp"] - t0) / 1000
        d = e.get("data") or {}
        if e["type"] == META:
            vw, vh, href = d.get("width"), d.get("height"), d.get("href")
            if not pages or pages[-1]["href"] != href:
                pages.append({"href": href, "t": t, "max_scroll_px": 0})
        elif e["type"] == FULL:
            nodes = Nodes(); nodes.add(d["node"])
        elif e["type"] == INCR and isinstance(d, dict):
            src = d.get("source")
            if src != MUTATION: active.add(int(t))
            if src == MUTATION:
                for a in d.get("adds", []) or []:
                    nodes.add(a["node"], a.get("parentId"))
            elif src == MOUSE and d.get("type") in CLICK_TYPES:
                if d.get("type") not in (2, 7): continue  # count clicks + touchend only
                if d["type"] == 7 and any(abs(c["t"] - t) < 0.5 and c["id"] == d.get("id") for c in clicks[-2:]):
                    continue  # touchend that becomes a click: one tap
                nid = d.get("id")
                prev = last_click.get(nid, [])
                prev = [p for p in prev if t - p < 1.0] + [t]; last_click[nid] = prev
                clicks.append({"t": round(t, 1), "id": nid, "el": nodes.label(nid), "rage": len(prev) >= 3, "page": href})
            elif src == SCROLL:
                y = d.get("y", 0)
                scrolls.append((round(t, 1), d.get("id"), y))
                if pages and y > pages[-1]["max_scroll_px"]:
                    pages[-1]["max_scroll_px"] = y
            elif src == VIEWPORT:
                vw, vh = d.get("width", vw), d.get("height", vh)
            elif src == INPUT:
                txt = d.get("text") or ""
                inputs.append({"t": round(t, 1), "id": d.get("id"), "el": nodes.label(d.get("id")), "len": len(txt), "checked": d.get("isChecked")})
        elif e["type"] == PLUGIN and isinstance(d, dict) and d.get("plugin") == "rrweb/console@1":
            p = d.get("payload", {})
            if p.get("level") == "error":
                errors.append({"t": round(t, 1), "msg": " ".join(map(str, p.get("payload", [])))[:200]})
        elif e["type"] == CUSTOM and isinstance(d, dict):
            custom.append({"t": round(t, 1), "tag": d.get("tag")})
    dur = (events[-1]["timestamp"] - t0) / 1000 if events else 0
    # collapse duplicate input events per element (keep last length)
    seen = {}
    for i in inputs: seen[i["id"]] = i
    return {"viewport": [vw, vh], "duration_s": round(dur, 1), "active_s": len(active),
            "pages": pages, "clicks": clicks, "inputs": list(seen.values()), "errors": errors,
            "custom": custom, "nodes": nodes, "scrolls": scrolls}
