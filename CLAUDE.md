<!-- handoff-and-updates:start -->
## Handoff and update files (read this first)

- Read `HANDOFF.md` in full at the start of every session, before doing anything else.
- Check its "Current mark" line so you know which mark the project is on. Marks are Mk I, Mk II, Mk III (roman numerals, never v1 or Mk1).
- After every task that changes anything (code, config, docs, files, even a small fix), update `HANDOFF.md`: add a dated entry at the top of the Change log with Asked / Changed / Verified / Not done, and correct any section the change made untrue. Only a pure question needs no entry.
- Never remove or rewrite the `<!-- handoff-mark: N -->` stamp by hand. `scripts/make-mark.js` owns it.
- Ship changes by making the next mark: `node scripts/make-mark.js --title "..." --notes "..." --entry entry.md`.

Detail lives in [HANDOFF.md](HANDOFF.md).
<!-- handoff-and-updates:end -->
