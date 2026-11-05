#!/usr/bin/env node
'use strict';
// make-mark.js: ship the next numbered update file (Mk I, Mk II, ...) with the latest HANDOFF.md inside.
//
//   node scripts/make-mark.js --title "Short title" --notes "What changed" [--entry entry.md] [--dry-run]
//
// Windows: `npm run` cuts multi-line arguments at the first line break. For multi-line notes call node directly.

const fs = require('fs');
const path = require('path');
const mp = require('./markpack');

const root = path.resolve(__dirname, '..');
const die = (msg) => { console.error('make-mark: ' + msg); process.exit(1); };

function parseArgs(argv) {
  const a = { dry: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--dry-run') a.dry = true;
    else if (k === '--help' || k === '-h') a.help = true;
    else if (['--title', '--notes', '--entry', '--min-shell'].includes(k)) a[k.slice(2)] = argv[++i];
    else die('unknown argument ' + k);
  }
  return a;
}

function collect(cfg) {
  const out = new Set();
  const excl = (cfg.exclude || []).concat(['node_modules', '.git', 'marks', 'handoff-history']);
  const skip = (name) => excl.some((p) => (p.startsWith('*') ? name.endsWith(p.slice(1)) : name === p));
  const walk = (rel) => {
    const abs = path.join(root, rel);
    if (!fs.existsSync(abs)) return;
    const st = fs.statSync(abs);
    if (st.isDirectory()) {
      for (const n of fs.readdirSync(abs).sort()) if (!skip(n)) walk(rel + '/' + n);
    } else if (st.isFile()) out.add(rel.replace(/^\.\//, ''));
  };
  for (const inc of cfg.include || []) walk(inc.replace(/\\/g, '/').replace(/\/$/, ''));
  out.delete('HANDOFF.md');
  out.delete('mark.json');
  return [...out].sort();
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  console.log('node scripts/make-mark.js --title "..." --notes "..." [--entry entry.md] [--min-shell x.y.z] [--dry-run]');
  process.exit(0);
}
if (!args.title) die('--title is required');

const cfg = mp.loadConfig();
const handoffPath = path.join(root, 'HANDOFF.md');
if (!fs.existsSync(handoffPath)) die('HANDOFF.md is missing. Run the handoff-and-updates skill first. A mark cannot be made without it.');
const histPath = path.join(root, 'marks', 'history.json');
const history = fs.existsSync(histPath) ? JSON.parse(fs.readFileSync(histPath, 'utf8')) : [];

const next = (history.length ? Math.max(...history.map((h) => h.mark)) : 0) + 1;
const name = mp.markName(next);
const tag = mp.markTag(next);
let text = fs.readFileSync(handoffPath, 'utf8');
if (mp.hasEntryFor(text, next)) die('HANDOFF.md already has an entry for ' + name + '. Fix the change log or marks/history.json before making another mark.');
const stamp = mp.readStamp(text);
if (stamp != null && stamp !== next - 1) console.warn('make-mark: warning, HANDOFF.md stamp is ' + stamp + ' but history says the last mark is ' + (next - 1));

const minShell = args['min-shell'] || cfg.minShell || cfg.shellVersion || '1.0.0';
const project = String(cfg.project || 'project').replace(/[^A-Za-z0-9_-]/g, '');
const fileName = project + '-' + tag + cfg.ext;
const relOut = 'marks/out/' + fileName;
const created = new Date().toISOString();
const d = new Date();
const date = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const notes = args.notes || '';

const shipped = collect(cfg);
const fileCount = shipped.length + 2; // plus HANDOFF.md and mark.json

let body;
if (args.entry) {
  if (!fs.existsSync(args.entry)) die('entry file not found: ' + args.entry);
  body = fs.readFileSync(args.entry, 'utf8').split(/\r?\n/).filter((l, i, arr) => !(/^###\s/.test(l) && i === arr.findIndex((x) => x.trim() !== ''))).join('\n').trim();
} else {
  body = [
    '- **Asked** – Ship the next update file.',
    '- **Changed** – ' + (notes || 'not recorded'),
    '- **Verified** – not recorded',
    '- **Not done** – not recorded',
  ].join('\n');
}
const entry = '### ' + date + ' – ' + name + ' "' + args.title + '" – update file\n' + body + '\n' +
  '- **Mark file:** `' + relOut + '` (' + fileCount + ' files, minimum shell ' + minShell + ')';

text = mp.addChangeLogEntry(text, entry);
text = mp.setStamp(text, next);
text = mp.setCurrentMark(text, next);
const markJson = JSON.stringify({ mark: next, name, title: args.title, notes, created }, null, 2) + '\n';

const fileMap = {};
for (const rel of shipped) fileMap[rel] = fs.readFileSync(path.join(root, rel));
fileMap['HANDOFF.md'] = Buffer.from(text, 'utf8');
fileMap['mark.json'] = Buffer.from(markJson, 'utf8');
const meta = { mark: next, name, title: args.title, notes, created, minShell };
const buf = mp.packMark(meta, fileMap);

// Re-read with the same parser the installer uses. Nothing is written unless this passes.
let parsed;
try { parsed = mp.parseMark(buf, minShell); } catch (e) { die('self-check failed: ' + e.message); }
if (!parsed.handoff) die('self-check failed: HANDOFF.md is not inside the update file');
if (parsed.handoff.toString('utf8') !== text) die('self-check failed: HANDOFF.md inside the file differs from the one just written');
if (mp.readStamp(parsed.handoff.toString('utf8')) !== next) die('self-check failed: stamp inside the file is not ' + next);
if (Object.keys(parsed.files).length !== fileCount) die('self-check failed: file count mismatch');

console.log((args.dry ? '[dry run] ' : '') + name + ' "' + args.title + '"');
console.log('  file:   ' + relOut);
console.log('  files:  ' + fileCount + ' (' + shipped.length + ' shipped + HANDOFF.md + mark.json)');
console.log('  size:   ' + buf.length + ' bytes, min shell ' + minShell);
console.log('  sha256: ' + mp.sha256(buf));
if (args.dry) {
  console.log('  self-check passed. Nothing written. Entry that would be added:\n');
  console.log(entry.split('\n').map((l) => '    ' + l).join('\n'));
  process.exit(0);
}

const outPath = path.join(root, relOut);
const original = fs.readFileSync(handoffPath);
try {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, buf);
  fs.writeFileSync(handoffPath, text);
  fs.writeFileSync(path.join(root, 'mark.json'), markJson);
  const record = { mark: next, name, title: args.title, notes, created, file: relOut, sha256: mp.sha256(buf), bytes: buf.length, minShell, handoff: true };
  fs.mkdirSync(path.dirname(histPath), { recursive: true });
  fs.writeFileSync(histPath + '.tmp', JSON.stringify(history.concat([record]), null, 2) + '\n');
  fs.renameSync(histPath + '.tmp', histPath);
} catch (e) {
  try { fs.writeFileSync(handoffPath, original); fs.rmSync(outPath, { force: true }); } catch (_) { /* best effort */ }
  die('write failed, HANDOFF.md restored: ' + e.message);
}
console.log('  done. HANDOFF.md now reads "Current mark: ' + name + '".');
