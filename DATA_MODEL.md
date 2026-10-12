# Data model: session-intent

Written from the need, before the data was looked at (BUSINESS.md rule 5). The
need: for one of Aidan's sites, say **which step of the intended path people fail
at, the evidence, and the line of our source to change**.

## Entities

### Site
| field | question it answers |
|---|---|
| `host` | Which sessions belong to this site? (`$host` on every event) |
| `path_prefix` | Which page on a shared host? (`/for/d9143508/` on brickandmortar.dev) |
| `repo` | Where is the source we point the fix at? |

### Intent (one per site, `sites/<slug>/intent.json`, versioned with the source)
| field | question it answers |
|---|---|
| `job` | What did a visitor come here to do, in their words? |
| `steps[]` | What is the intended path, in order? |
| `success` | Which step, once reached, means the job got done? |
| `known_exits[]` | Which ways out are fine (a mailto, an outbound link) versus abandonment? |
| `source_commit` | Which version of the source were the file:line refs read from? |

### Step
| field | question it answers |
|---|---|
| `id`, `label` | What do we call this step in a finding? |
| `match` | How does a deterministic join know a session reached it? One of: `pageview` (path), `scroll` (min % of page), `event` (custom event name + optional property), `click` (CSS selector or element text), `input` (selector), `dwell` (seconds on page). |
| `source` | `file:line` that renders this step. Where the fix goes. |

### Session (built from PostHog, one per `$session_id` on the site)
| field | question it answers |
|---|---|
| `id`, `replay_url` | Which recording do I watch to check the claim? |
| `start`, `duration_s`, `active_s` | Did they stay, and were they doing anything? |
| `device`, `viewport_w/h`, `referrer`, `utm` | Who, on what screen, from where? |
| `pages[]` (path, entered_at, dwell_s, max_scroll_pct) | How far down each page did they get? |
| `clicks[]` (t, selector, text, rage, dead) | What did they press, and did it do anything? |
| `inputs[]` (t, selector, masked length) | Did they try to type? |
| `custom_events[]` (t, name, props) | Which instrumented actions fired? |
| `errors[]` (t, message) | Did the page break on them? |
| `exit` (t, last_path, last_action, outbound_url) | How did it end? |
| `has_recording` | Is the timeline from rrweb (rich) or events only (thin)? |

### Score (Session × Intent, deterministic, no model)
| field | question it answers |
|---|---|
| `reached[]` | Which steps did the session hit, and when? |
| `furthest_step` | How far along the path did they get? |
| `left_at` | First intended step they did NOT reach. |
| `instead` | What did they do after their last reached step (their next clicks/scrolls/exit)? |
| `success` | Did they reach the success step? |

### Finding (Site, many sessions, model-written prose over deterministic counts)
| field | question it answers |
|---|---|
| `decision` | The one change to make, first. |
| `fail_step` | Which step loses the most people (from Score counts, not the model). |
| `counts` | reached per step, n sessions, n with recording. Computed, never typed by the model. |
| `examples[]` | 1–2 sessions with replay links that show it. |
| `fix` | file:line plus the specific edit. |

## Joins
- Site → Session: `events.properties.$host = host AND $pathname LIKE path_prefix%`, `filterTestAccounts`.
- Session → recording: `$session_id` = recording id.
- Session × Intent → Score: each Step's `match` evaluated against the Session timeline.
- Score[] → Finding: counts by `left_at`; the model reads Score[] + Intent + the source lines.

## Reality check (2026-10-12, PostHog US cloud, our plan)

| field | source | result |
|---|---|---|
| sessions per site | HogQL on `events` by `$host`/`$pathname` | **fills.** 18 prod sessions on /for/d9143508/ in 14 days |
| `has_recording` | `/session_recordings` list | **fails for most sessions.** 3 of 18 target sessions have a recording; the rest show `$recording_status: lazy_loading` (never started). |
| `pages`, `max_scroll_pct`, `clicks`, `inputs`, `viewport` | rrweb blobs: `/session_recordings/<id>/snapshots?source=blob_v2&start_blob_key=k&end_blob_key=k` | **fills when a recording exists.** JSONL of `[window_id, event]`; `cv: "2024-10"` payloads are gzip carried as latin-1 strings. Readable on our plan. |
| `clicks` from events | `$autocapture` | **fails on brickandmortar.dev**: autocapture never fires there in the window (only `$pageview`, `time_on_page`, `$web_vitals`). |
| `custom_events` | site's own `posthog.capture` | **fills where instrumented.** /for/ pages fire `row_click`, `filter`, `sort`, `download`, `scroll_depth`. |
| `errors` | recording `console_error_count` + `$exception` | fills when recorded. |
| rage/dead clicks | `$rageclick`/`$dead_click` events | needs autocapture; derived from rrweb clicks instead (3 clicks <1s on one node = rage). |

**Consequence, stated plainly:** where no recording exists, the Session is events
only: pageview, `time_on_page` dwell, and custom events. Scroll and clicks are
unknown, not zero. The Score marks a step `unknown` rather than `missed` when its
`match` needs data the session doesn't have, and the Finding reports how many
sessions were rich versus thin.

### Added after the first two runs (2026-10-12)

- **Scroll-percentage events lie on long pages.** presale-detail is ~100k px tall (180 cards):
  a visitor scrolled 3,785px and `time_on_page.max_depth` still said 0. Only rrweb scrollY, or an
  interaction inside the list, proves a scroll step there. Matches can carry `decides_miss: false`
  (a hit proves the step; a non-hit proves nothing, so the step stays `unknown`).
- **QA automation passes `filterTestAccounts`.** Five sessions, five distinct ids, one 390x844
  Chrome-iOS profile, inside one minute (presale-detail, 2026-10-10 18:40Z). The scorer leaves out
  any burst of 3+ distinct ids from one device profile within 120s and prints that it did.
- **One device can be all of a page's traffic.** /for/d9143508/: 18 sessions, 2 visitor ids, one
  393x659 iPhone, every recording opening at a restored scrollY of 109px. Device count is printed
  next to every finding.
