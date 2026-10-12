"""Session -> a few readable lines. The same text goes to the model and to the terminal."""

def _visible_s(s):
    v = [float(e["props"].get("seconds") or 0) for e in s["events"] if e["event"] == "time_on_page"]
    return sum(v) if v else None

def _max_depth(s):
    d = [float(e["props"].get("max_depth") or 0) for e in s["events"] if e["event"] == "time_on_page"]
    d += [float(e["props"].get("depth") or 0) for e in s["events"] if e["event"] == "scroll_depth"]
    return max(d) if d else None

def device_key(s):
    return f"{s.get('browser')} {s['viewport'][0]:.0f}x{round(s['viewport'][1], -1):.0f}" if s["viewport"][0] else str(s.get("browser"))

def session_lines(i, s, sc):
    head = (f"S{i} {s['id'][:8]} · {s['start'][:16].replace('T',' ')}Z · {device_key(s)} · "
            f"ref {s.get('referrer') or '-'} · {'recorded' if s.get('timeline') else 'events only'} · visitor …{s['distinct_id'][-6:]}")
    out = [head]
    vis, dep = _visible_s(s), _max_depth(s)
    out.append(f"  visible {vis:.0f}s" if vis is not None else "  visible ? (no time_on_page)")
    out[-1] += f" · deepest scroll mark {dep:.0f}%" if dep is not None else " · scroll mark ?"
    custom = [e for e in s["events"] if not e["event"].startswith("$") and e["event"] not in ("time_on_page",)]
    if custom:
        out.append("  did: " + "; ".join(f"{e['event']} {', '.join(f'{k}={v}' for k, v in e['props'].items() if k not in ('site','path','distinct_id'))}" for e in custom[:12]))
    tl = s.get("timeline")
    if tl:
        pg = tl["pages"][0] if tl["pages"] else {}
        out.append(f"  replay: {tl['duration_s']:.0f}s long, {tl['active_s']}s active, max scrollY {pg.get('max_scroll_px',0)}px, viewport {tl['viewport'][0]}x{tl['viewport'][1]}")
        first = tl["scrolls"][0] if tl["scrolls"] else None
        if first and first[0] < 1 and first[2] > 0:
            out.append(f"  opened already scrolled to {first[2]}px (browser restored the tab)")
        vis_marks = [c["tag"] for c in tl["custom"] if c["tag"] in ("window hidden", "window visible")]
        hid = [f"{c['tag'].split()[1]} +{c['t']}s" for c in tl["custom"] if c["tag"] in ("window hidden", "window visible")]
        if hid: out.append("  tab: " + ", ".join(dict.fromkeys(hid)))
        if tl["clicks"]: out.append("  taps: " + "; ".join(f"+{c['t']}s {c['el']}{' RAGE' if c['rage'] else ''}" for c in tl["clicks"][:15]))
        else: out.append("  taps: none")
        if tl["inputs"]: out.append("  typed: " + "; ".join(f"+{x['t']}s {x['el']} ({x['len']} chars)" for x in tl["inputs"]))
        if tl["errors"]: out.append("  errors: " + "; ".join(f"+{x['t']}s {x['msg']}" for x in tl["errors"][:5]))
    path = " → ".join(f"{x['step']} {'✓' if x['state']=='reached' else '✗' if x['state']=='missed' else '?'}" for x in sc["steps"])
    out.append(f"  path: {path}")
    return out
