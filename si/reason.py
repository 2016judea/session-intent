"""Scored timelines + intent + source lines -> Finding. Counts come from score.summary, never the model."""
import json, os, pathlib, re
import anthropic
from . import ph

MODEL = "claude-opus-5-5"

SYSTEM = """You are the session analyst for a small set of websites whose source code you can see.
For one page you get: what the page is FOR (the intent spec, with the source line behind each step),
those source lines, the deterministic counts of how far sessions got along the intended path, and a
short timeline of every session.

Your job: name the single step where people actually fail, show it with 1-2 sessions, and give the one
specific code change, at file:line, most likely to move people past that step.

Rules:
- Never state a count, percentage or duration that is not printed in the input. The counts are shown to
  the reader next to your text by code; refer to them, don't restate new ones.
- Be honest about what the data can't tell. If every session comes from one device, say so: that is one
  person's behaviour, not a crowd's. If sessions are events-only, say what is unknown.
- A fix must be concrete: which element moves where, which line changes, what the new line says.
  Point at a line number that appears in the source excerpt.
- The fix must hold on BOTH a 390px phone and a 1440px desktop. Read the layout CSS in the excerpt before
  moving DOM nodes; prefer a viewport-scoped CSS change when a DOM move would break the other layout.
- Never guess who a visitor is (owner, customer, bot). Describe the device and the pattern only.
- The reader is on a phone and has a minute. Decision first. Plain words. No hedging paragraphs."""

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "description": "The one change, in one sentence, imperative."},
        "fail_step": {"type": "string"},
        "why": {"type": "string", "description": "<= 2 sentences: what people do instead, grounded in the timelines."},
        "examples": {"type": "array", "items": {"type": "object", "properties": {
            "session": {"type": "string", "description": "S-number from the input, e.g. S3"},
            "what_happened": {"type": "string"}}, "required": ["session", "what_happened"], "additionalProperties": False}},
        "fix_file": {"type": "string"},
        "fix_line": {"type": "integer"},
        "fix_change": {"type": "string", "description": "The concrete edit."},
        "caveat": {"type": "string", "description": "What this data cannot tell, in one sentence. Empty if nothing."},
    },
    "required": ["decision", "fail_step", "why", "examples", "fix_file", "fix_line", "fix_change", "caveat"],
    "additionalProperties": False,
}

def source_excerpts(intent, ctx=4):
    repo = pathlib.Path(os.path.expanduser(intent["repo"]))
    lines_wanted = {}
    for st in intent["steps"]:
        for f, ln in re.findall(r"([\w./-]+\.\w+):(\d+)", st.get("source", "")):
            lines_wanted.setdefault(f, set()).add(int(ln))
        for ln in re.findall(r"(?<![\w.]):(\d+)", st.get("source", "").split(" ", 1)[-1]):
            lines_wanted.setdefault(intent["source_file"], set()).add(int(ln))
    out = []
    for f, lns in lines_wanted.items():
        p = repo / f
        if not p.exists(): continue
        text = p.read_text().split("\n")
        keep = sorted({i for ln in lns for i in range(max(1, ln - ctx), min(len(text), ln + ctx) + 1)})
        out.append(f"--- {f}")
        prev = None
        for i in keep:
            if prev and i != prev + 1: out.append("   ...")
            out.append(f"{i:5d}| {text[i-1][:260]}")
            prev = i
    return "\n".join(out)

def find(intent, summary, timelines_text):
    user = (f"INTENT\n{json.dumps(intent, indent=1)}\n\nSOURCE\n{source_excerpts(intent)}\n\n"
            f"COUNTS (computed)\n{json.dumps(summary, indent=1)}\n\nSESSIONS\n{timelines_text}")
    client = anthropic.Anthropic(api_key=ph._E["ANTHROPIC_API_KEY"])
    resp = client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"},
        messages=[{"role": "user", "content": user}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"model refused: {resp.stop_details}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), {"model": resp.model, "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}
