# session-intent

A session analyst for sites whose source you own. PostHog's AI summaries watch a
recording blind and say *what happened*. This knows what each page is **for**, so it
says *where people fail against that intent*, and *which line of the source to change*.

```
$ python3 -m si presale-detail
# Make a tap on the message text itself copy it, because people tap the message, not the Copy button.
  Scrolls into the job cards      4 reached  0 missed  2 unknown
  Copies a ready message          1 reached  5 missed  0 unknown
  left out: 5 sessions, burst from Chrome iOS 390x840 within 120s (likely QA automation)
- S3 ... tapped div.msg four times, never hit Copy message  <replay link>
Fix: scripts/page.html:161 — ...
```

## How it works

1. **Intent spec** per page, `sites/<slug>/intent.json`: the visitor's job, the intended
   path as steps, and for each step the evidence that proves it (a custom event, an rrweb
   scroll depth in px, a tap on a selector) and the `file:line` that renders it.
2. **Collect** (`si/collect.py`): every PostHog session on the page's `$host` + path
   (`filterTestAccounts` on), plus the rrweb recording when one exists, decoded by
   `si/rrweb.py` into pages, scrollY, taps with element text, inputs (length only), errors,
   tab hidden/visible.
3. **Score** (`si/score.py`): a deterministic join. Each step is `reached`, `missed`, or
   `unknown` (no data could decide it; never counted as a miss). Bursts of distinct ids from
   one device profile inside 120s are left out as automation, and the report says so.
4. **Reason** (`si/reason.py`): `claude-opus-5-5` reads the intent, the source lines, the
   computed counts and every session's timeline, and returns the decision, two example
   sessions, and the fix at `file:line`. Counts are printed by code, never by the model.

`DATA_MODEL.md` is the model it was built against, and what PostHog actually fills.

## Use

```
python3 -m si hosts                 # which pages have sessions, and which have an intent
python3 -m si <slug> [--days 14]    # finding -> out/<slug>/finding.md
python3 -m si <slug> --no-model     # counts + timelines only (reason in a Claude session)
python3 -m pytest -q tests
```

Keys come from `~/Desktop/bricks/.env` (`POSTHOG_PERSONAL_API_KEY`, `POSTHOG_PROJECT_ID`,
`POSTHOG_HOST`, `ANTHROPIC_API_KEY`); override the path with `SI_ENV`. Needs `anthropic`.
A run costs about 6–10k input tokens.

Intent specs live here, not in each site's repo, because a file under a static site's
`website/` or `site/` folder gets deployed publicly. Each spec pins `source_commit`.

MIT.
