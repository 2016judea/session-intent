"""si <slug> [--days N] [--no-model]: how are people using <site>?"""
import argparse, json, pathlib, sys
from . import collect, score, render, reason

ROOT = pathlib.Path(__file__).resolve().parent.parent

def load_intent(slug):
    p = ROOT / "sites" / slug / "intent.json"
    if not p.exists():
        sys.exit(f"no intent at {p}. sites: {', '.join(x.name for x in (ROOT/'sites').iterdir())}")
    return json.loads(p.read_text())

def main(argv=None):
    ap = argparse.ArgumentParser(prog="si")
    ap.add_argument("slug")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--no-model", action="store_true", help="scored timelines only; reason in-session")
    a = ap.parse_args(argv)
    if a.slug == "hosts":
        return hosts(a.days)
    intent = load_intent(a.slug)
    allss = score.flag_bursts(collect.collect(intent, a.days))
    excluded = [s for s in allss if s.get("excluded")]
    ss = [s for s in allss if not s.get("excluded")]
    scs = [score.score(s, intent) for s in ss]
    summ = score.summary(scs, intent)
    devices = {render.device_key(s) for s in ss}
    summ.update(recorded=sum(1 for s in ss if s.get("timeline")), visitors=len({s["distinct_id"] for s in ss}),
                devices=len(devices), device_list=sorted(devices), days=a.days,
                excluded=[{"id": s["id"], "why": s["excluded"]} for s in excluded])
    tl_text = "\n".join("\n".join(render.session_lines(i + 1, s, sc)) for i, (s, sc) in enumerate(zip(ss, scs)))
    out = ROOT / "out" / a.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "sessions.json").write_text(json.dumps({"intent": intent, "summary": summ, "sessions": ss, "scores": scs}, default=str))
    (out / "timelines.txt").write_text(tl_text)
    counts = render_counts(intent, summ)
    if a.no_model or not ss:
        print(counts); print(); print(tl_text); return
    f, usage = reason.find(intent, summ, tl_text)
    md = render_finding(intent, summ, f, ss, counts, usage)
    (out / "finding.md").write_text(md)
    print(md)

def hosts(days):
    """Which host+path had sessions, so you know where an intent spec is worth writing."""
    from . import ph
    d = ph._req("/query/", {"query": {"kind": "HogQLQuery", "filters": {"filterTestAccounts": True}, "query":
        f"select properties.`$host` h, properties.`$pathname` p, count(distinct `$session_id`) s, count(distinct distinct_id) v "
        f"from events where timestamp > now() - interval {int(days)} day and {{filters}} and properties.`$host` not like 'localhost%' "
        f"group by h, p order by s desc limit 30"}, "refresh": "force_blocking"})
    have = {json.loads(p.read_text())["host"] + json.loads(p.read_text())["path_prefix"]: p.parent.name for p in (ROOT / "sites").glob("*/intent.json")}
    for h, p, s, v in d["results"]:
        tag = next((slug for k, slug in have.items() if f"{h}{p}".startswith(k)), "")
        print(f"{s:>4} sessions {v:>4} visitors  {h}{p}  {('-> ' + tag) if tag else ''}")

def render_counts(intent, s):
    rows = [f"{intent['name']} · last {s['days']}d · {s['n']} sessions, {s['visitors']} visitor ids, {s['devices']} device(s), {s['recorded']} recorded"]
    for p in s["per_step"]:
        rows.append(f"  {p['label']:<52} {p['reached']:>3} reached  {p['missed']:>3} missed  {p['unknown']:>3} unknown")
    if s.get("excluded"):
        rows.append(f"  left out: {len(s['excluded'])} sessions, {s['excluded'][0]['why']}")
    return "\n".join(rows)

def render_finding(intent, s, f, ss, counts, usage):
    lines = [f"# {f['decision']}", "", f"{f['why']}", "", "```", counts, "```", ""]
    for ex in f["examples"]:
        try: sess = ss[int(ex["session"].lstrip("Ss")) - 1]; link = sess["replay_url"] if sess.get("has_recording") else "(no recording)"
        except (ValueError, IndexError): link = ""
        lines.append(f"- **{ex['session']}** {ex['what_happened']} {link}")
    lines += ["", f"**Fix:** `{f['fix_file']}:{f['fix_line']}` — {f['fix_change']}"]
    if f.get("caveat"): lines += ["", f"_{f['caveat']}_"]
    lines += ["", f"<sub>{usage['model']} · {usage['in']} in / {usage['out']} out tokens · source @ {intent.get('source_commit')}</sub>"]
    return "\n".join(lines)

if __name__ == "__main__":
    main()
