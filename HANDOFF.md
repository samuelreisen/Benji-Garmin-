<!-- handoff-mark: 1 -->

**Current mark: Mk I**

# Benji Garmin Coach – handoff

> **MAINTENANCE RULE.** EVERYTHING done to this project is saved in this file. Every session reads this file first, in full.
> After each change (code, config, docs, files, a fix, an experiment, a refactor, even a small one), add a dated entry at the top of the
> Change log (section 12), newest first, with exactly these four fields:
> - **Asked** – the owner's request, quoted or closely paraphrased.
> - **Changed** – what was changed, with root causes and file names.
> - **Verified** – how it was checked, with real numbers, tests run and counts. Never just "works".
> - **Not done** – honest limits, and what was skipped, such as untested parts or no commit/push.
>
> The same step must also correct any other section the change makes untrue. This document is kept correct, not just appended to.
> A prompt that changes nothing (a pure question) needs no entry. Never remove or edit the `handoff-mark` stamp on line 1 by hand:
> `scripts/make-mark.js` owns it.

## 1. What it is and who it is for
A personal fitness coach web app for the owner's mate (Benji), who has a Garmin watch. Flow: Garmin data -> normalised per-day metrics ->
computed trend snapshot (7-day vs 28-day) -> Gemini prompted as a blunt, mate-style coach -> chat and a daily morning briefing.
Python 3.13, FastAPI, SQLite, `google-genai`, `garminconnect`. Plain HTML/CSS/JS front end built to Apple HIG tokens.

**Owner:** Samuel Reisen (samuelreisen@icloud.com)

**What the owner cares about / their standards:** Casual direct tone (swearing fine, never em dashes). Secure by default (no secrets in the
client or repo). Apple HIG look and feel. Every change logged here. Update files use the `.benji` extension.

## 2. How to run it
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env     # then: python -m app.cli gen-secrets ; python -m app.cli hash-password
python -m app.cli serve  # http://127.0.0.1:8000 (set COOKIE_SECURE=0 for local http)
python -m pytest         # 33 tests, no network
node scripts/verify-mark-system.js
```

> **DANGER: test data.** Tests and experiments must run against a scratch data folder, never the real data.
> Real data lives at: `$BENJI_DATA_DIR` (default `./data`): `benji.sqlite3` (Garmin cache, briefings, chat), `garmin_tokens.enc` (encrypted Garmin session), `profile.json`.
> Point `BENJI_DATA_DIR` at a temp folder before running anything that writes. The pytest suite already uses `tmp_path`.
> If you run the server for a demo, use a scratch dir and fake clients (see Change log 2026-11-05 for how).

## 3. Repository map
- `app/config.py` env settings. `app/store.py` SQLite (days, activities, briefings, chat, meta).
- `app/garmin/client.py` `GarminClient` interface, `GarminConnectClient` (unofficial), `GarminOfficialClient` (placeholder), `TokenVault` (Fernet).
- `app/garmin/normalise.py` Garmin JSON -> flat metrics. `app/garmin/summarise.py` metrics -> trend snapshot.
- `app/coach/prompt.py` the coach system prompt. `app/coach/gemini.py` `Coach` + injectable transport.
- `app/service.py` sync/snapshot/briefing/chat/profile glue. `app/scheduler.py` daily briefing loop.
- `app/auth.py` bcrypt, lockout, rate limiter. `app/main.py` FastAPI routes, security headers, static UI. `app/cli.py` helpers.
- `web/` `index.html`, `styles.css`, `app.js`, `hig-tokens.css`. `tests/` pytest suite. `scripts/` update-file tooling. `marks/` release history.

## 4. Data model
SQLite: `days(day, data json)`, `activities(id, day, data json)`, `briefings(day, text)`, `chat(role user|model, content)`, `meta(key, value)`.
Day metrics: steps, resting_hr, stress_avg, body_battery_high/low, sleep_hours, deep/rem_sleep_hours, sleep_score, hrv_ms, hrv_status,
training_readiness(+level). Missing values stay `null`, never 0.

## 5. Core logic
`build_snapshot` computes per metric: latest (within 7 days), 7-day avg, 28-day avg, latest vs 28-day avg in percent; plus training load
(last 7 days vs weekly average of the prior 21 days, hard sessions = aerobic training effect >= 3.5). Gemini only ever sees this snapshot, not raw Garmin JSON.

Regression targets (numbers this logic was verified against, re-check after changing it):
- 28 days with HRV 50 and today 40 gives avg_28d 49.6 and a negative delta (`tests/test_garmin_data.py`).
- 1 run 10 km in last 7 days plus 1 x 6 km run 16 days ago gives prior weekly average 2.0 km.

## 6. Subsystem notes
- **Sync:** first sync pulls 28 days, later syncs the last 4 days. 0.4 s pause between Garmin calls. One failed metric never aborts a sync.
- **Briefing:** cached per day in SQLite. Scheduler (only when `run_scheduler=True`) syncs and regenerates at `BRIEFING_HOUR` in `TZ_NAME`.
- **Coach refuses** (safe message) when there is no data or no key, rather than guessing.
- **Security:** see section 7.

## 7. Traps and facts only real data revealed
- Real Garmin endpoint shapes are mapped from the `garminconnect` 0.3.20 API and NOT yet verified against a real account. First real sync may show fields coming back `null`. Check `normalise.py` against a real response.
- `create_app()` defaults to `run_scheduler=False` (tests); `serve_app()` in `app/main.py` turns the daily briefing loop on and is what `python -m app.cli serve` uses. For production run `uvicorn app.main:serve_app --factory`.
- Behind a reverse proxy the client IP is the proxy's, so lockout and rate limits act on everyone at once unless uvicorn is run with `--proxy-headers`.
- Security invariants (do not break): no secrets in client/repo; app fails closed with no `SESSION_SECRET` or no password hash; Garmin tokens never written in plaintext; all non-GET requests need `X-Requested-With: benji`; model text rendered with `textContent` only; strict CSP so no inline script/style.

## 8. Persistence
SQLite file plus encrypted token file plus `profile.json` in `BENJI_DATA_DIR`.

**Must never be lost:** `TOKEN_ENC_KEY` (losing it just means logging in to Garmin again) and `data/benji.sqlite3` (chat history and cached Garmin history).

## 9. UI notes and traps
HIG web medium: tab bar (Today / Coach / Trends / Profile), glass top and tab bars only, 44 px targets, light and dark via tokens, reduced motion respected.
No inline styles or scripts allowed by CSP. Colour is never the only signal (deltas also say Up/Down in words). Checked in Playwright at 390 px in light and dark.

## 10. Platform and build notes
Web app, not an installable app, so no in-app updater. Deploy over HTTPS only (Fly.io, Render or a Pi at home). Update files (`.benji`) carry the source plus the latest HANDOFF.md.

## 11. Working method
- Read this file first. Log every change (see the Maintenance rule).
- Ship changes with `node scripts/make-mark.js --title "..." --notes "..." --entry entry.md`. Call `node` directly for multi-line notes: on Windows, `npm run` cuts a multi-line argument at the first line break.
- Marks are named Mk I, Mk II, Mk III (roman numerals). The `handoff-mark` stamp and `marks/history.json` hold the plain number.
- Install a mark with `node scripts/install-mark.js <file>` (newer HANDOFF.md wins, the replaced one is kept in `handoff-history/`). `node scripts/verify-mark-system.js` re-checks the whole system.

## 12. Open items and known quirks (prioritised)
1. Run a real sync with the mate's Garmin and check the numbers against Garmin Connect (normaliser is unverified on real data).
2. Confirm a real `GEMINI_API_KEY` works and the default model name `gemini-2.5-flash` is still current.
3. Decide whether official Garmin API keys exist; then implement `GarminOfficialClient`.
4. Deploy over HTTPS and set `--proxy-headers`.
5. Weekly training plans and goal tracking (v2 scope).

## 13. Rough chronology (why the code looks the way it does)
Built in one session from an approved plan: Garmin behind an interface so the unofficial library can be swapped for the official API; a summariser sits between Garmin and Gemini so the model quotes computed numbers instead of raw JSON; single-user login because it exposes health data.

## 14. Change log
Format: `### <date> – <title>` then the four fields **Asked**, **Changed**, **Verified**, **Not done**. Newest first. Mark entries read `### <date> – Mk <Roman> "<title>" – update file` and end with a **Mark file** line.

### 2026-11-05 – Mk I "First working coach" – update file
- **Asked** – Build a personal fitness coach for a mate with a Garmin: Garmin API into Gemini, prompted as a fitness coach that tells him everything. Plan mode first, then secure, Apple HIG UI, and handoff with a `.benji` update extension.
- **Changed** – Whole app built from scratch: Garmin client behind an interface (unofficial `garminconnect` now, official API placeholder), normaliser and trend summariser, coach prompt, Gemini wrapper, SQLite store, FastAPI API with login, lockout, rate limits, CSRF header, CSP and security headers, encrypted Garmin tokens, daily briefing scheduler, HIG web UI (Today, Coach, Trends, Profile), CLI helpers, README, 33 tests, HANDOFF.md and the mark tooling.
- **Verified** – `python -m pytest`: 33 passed (normalise, summarise, prompt, coach errors, auth, lockout, rate limit, vault encryption, injection safety, API flow, headers and cookie flags). UI screenshotted with Playwright at 390 px in light and dark against a fake Garmin and fake Gemini, no console errors apart from the expected 502 before first sync. Security audit greps: no hardcoded secrets, no innerHTML/eval/inline handlers, no http:// or disabled TLS checks, .env and data ignored.
- **Not done** – NOT tested against a real Garmin account or a real Gemini key (all Garmin and Gemini calls were faked). Official Garmin API not implemented. Not deployed. Nothing committed or pushed to git.
- **Mark file:** `marks/out/BenjiGarminCoach-MkI.benji` (32 files, minimum shell 1.0.0)

### 2026-11-05 – Set up HANDOFF.md and the update-file system
- **Asked** – Run the handoff-and-updates skill: living HANDOFF.md plus numbered update files with extension `.benji`.
- **Changed** – Added HANDOFF.md, CLAUDE.md block, `scripts/` (markpack, make-mark, install-mark, verify-mark-system, mark.config.json) and `marks/history.json`. Extension `.benji`. Shipped paths: app, web, tests, profile.example.json, requirements.txt, .env.example, README.md, CLAUDE.md.
- **Verified** – See the Mk I entry below once built.
- **Not done** – Mk I is built by the next step of setup.
