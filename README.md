# Benji Garmin Coach

A personal fitness coach. Garmin data goes in, Gemini (prompted as a blunt, mate-style coach) turns it into advice.

```
Garmin -> normalise -> trend snapshot -> Gemini (coach prompt) -> chat + daily briefing
```

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python -m app.cli gen-secrets        # paste SESSION_SECRET and TOKEN_ENC_KEY into .env
python -m app.cli hash-password      # paste APP_PASSWORD_HASH into .env
```

Then fill in `GEMINI_API_KEY` (from Google AI Studio) and `GARMIN_EMAIL` / `GARMIN_PASSWORD`.
For local http testing only, set `COOKIE_SECURE=0`.

```bash
python -m app.cli serve              # http://127.0.0.1:8000
python -m app.cli sync               # pull Garmin data from the terminal
python -m app.cli briefing           # print today's briefing
python -m pytest                     # tests (no network, no real keys)
```

The first sync pulls 28 days and logs in with his Garmin email and password once. After that the session
tokens are cached encrypted in `data/`, and you can remove the password from `.env`.

## Garmin access

- **Now:** the unofficial `garminconnect` library. It works without approval but Garmin doesn't support it and can break it.
  If his account has MFA on, log in once from the terminal.
- **Later:** `GarminOfficialClient` in `app/garmin/client.py` is a placeholder for Garmin's official API, which needs
  approved developer keys. Everything else only talks to the `GarminClient` interface, so swapping is one class.

## Security notes

- Every key stays on the server. Nothing secret is sent to the browser or committed (`.env`, `data/` are gitignored).
- One password login (bcrypt), 5 wrong tries locks that address for 5 minutes, signed HttpOnly SameSite=Strict cookie.
- Garmin tokens are Fernet encrypted at rest. They are never written in plaintext.
- Serve it over HTTPS only. Behind a reverse proxy, run uvicorn with `--proxy-headers` and `--forwarded-allow-ips` set to
  the proxy so lockout and rate limits see real client addresses.
- His health data is sent to Google's Gemini to generate advice. Make sure he's fine with that.
