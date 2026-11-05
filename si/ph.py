"""PostHog API client: HogQL, recordings list, snapshot blobs. Reads keys from bricks/.env."""
import json, os, pathlib, urllib.request, urllib.parse

ENV = pathlib.Path(os.environ.get("SI_ENV", "~/Desktop/workspace/bricks/.env")).expanduser()

def _env():
    out = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out

_E = _env()
HOST = _E.get("POSTHOG_HOST", "https://us.posthog.com").rstrip("/")
PID = _E["POSTHOG_PROJECT_ID"]
KEY = _E["POSTHOG_PERSONAL_API_KEY"]
BASE = f"{HOST}/api/projects/{PID}"

def _req(path, body=None, raw=False):
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as resp:
        b = resp.read()
    return b if raw else json.loads(b)

def hogql(q):
    d = _req("/query/", {"query": {"kind": "HogQLQuery", "query": q}, "refresh": "force_blocking"})
    return [dict(zip(d["columns"], row)) for row in d["results"]]

def recording(sid):
    return _req(f"/session_recordings/{sid}")

def snapshot_sources(sid):
    return _req(f"/session_recordings/{sid}/snapshots?blob_v2=true").get("sources", [])

def snapshot_blob(sid, src):
    q = {"source": src["source"]}
    if src["source"] == "blob_v2":
        k = src.get("blob_key", "0")
        q.update(start_blob_key=k, end_blob_key=k)
    elif "blob_key" in src:
        q["blob_key"] = src["blob_key"]
    return _req(f"/session_recordings/{sid}/snapshots?" + urllib.parse.urlencode(q), raw=True)

def replay_url(sid):
    return f"{HOST}/project/{PID}/replay/{sid}"
