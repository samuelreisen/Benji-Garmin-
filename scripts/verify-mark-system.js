#!/usr/bin/env node
'use strict';
// verify-mark-system.js: proves the mark system works on THIS project, in a scratch folder.
//   node scripts/verify-mark-system.js [--keep]
// Needs a real Mk I already built (marks/history.json). Never touches the project's own marks or HANDOFF.md:
// the temporary Mk II is made in a scratch copy, so there is nothing to clean up afterwards.

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const mp = require('./markpack');
const { installMark } = require('./install-mark');

const root = path.resolve(__dirname, '..');
let pass = 0, total = 0;
function check(name, cond, detail) {
  total++;
  if (cond) pass++;
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (detail ? '  (' + detail + ')' : ''));
}
function throwsCode(fn) { try { fn(); return null; } catch (e) { return e.code || e.message; } }

// 1. markName
const table = [[1, 'Mk I'], [2, 'Mk II'], [4, 'Mk IV'], [9, 'Mk IX'], [14, 'Mk XIV'], [40, 'Mk XL']];
check('markName 1,2,4,9,14,40', table.every(([n, s]) => mp.markName(n) === s), table.map(([n]) => mp.markName(n)).join(', '));
check('markTag drops the space', mp.markTag(3) === 'MkIII');

// 2. the real Mk I parses back
const cfg = mp.loadConfig();
const histPath = path.join(root, 'marks', 'history.json');
if (!fs.existsSync(histPath)) { console.error('No marks/history.json. Build Mk I first.'); process.exit(1); }
const historyBefore = fs.readFileSync(histPath, 'utf8');
const history = JSON.parse(historyBefore);
const first = history.find((h) => h.mark === 1) || history[0];
const mk1 = fs.readFileSync(path.join(root, first.file));
const parsed = mp.parseMark(mk1, cfg.shellVersion);
check('Mk I parses with the app parser', parsed.header.mark === first.mark, 'bytes ' + mk1.length);
check('Mk I sha256 matches history.json', mp.sha256(mk1) === first.sha256);
check('HANDOFF.md is inside Mk I', !!parsed.handoff);
check('stamp inside Mk I equals its mark number', mp.readStamp(parsed.handoff.toString('utf8')) === first.mark);
check('first mark in history is 1', history[0].mark === 1);
check('file name uses roman numeral and chosen extension', path.basename(first.file) === cfg.project.replace(/[^A-Za-z0-9_-]/g, '') + '-' + mp.markTag(first.mark) + cfg.ext, path.basename(first.file));

// 3. scratch copy of the project, with a temporary Mk II made inside it
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'mark-verify-'));
const copyProj = path.join(scratch, 'proj');
const skip = new Set(['node_modules', '.git', 'handoff-history']);
(function copy(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const n of fs.readdirSync(src)) {
    if (skip.has(n)) continue;
    const s = path.join(src, n), d = path.join(dst, n);
    if (fs.statSync(s).isDirectory()) copy(s, d); else fs.copyFileSync(s, d);
  }
})(root, copyProj);
execFileSync(process.execPath, [path.join(copyProj, 'scripts', 'make-mark.js'), '--title', 'verify temp', '--notes', 'temporary Mk II for verification'], { cwd: copyProj, stdio: 'pipe' });
const hist2 = JSON.parse(fs.readFileSync(path.join(copyProj, 'marks', 'history.json'), 'utf8'));
const mk2rec = hist2[hist2.length - 1];
check('scratch copy produced Mk II', mk2rec.mark === hist2[hist2.length - 2].mark + 1 && mk2rec.name === mp.markName(mk2rec.mark), mk2rec.file);
const mk2 = fs.readFileSync(path.join(copyProj, mk2rec.file));

// 4. install into a scratch target that already has an old HANDOFF.md (stamp 0)
const target = path.join(scratch, 'installed');
fs.mkdirSync(target, { recursive: true });
const oldDoc = '<!-- handoff-mark: 0 -->\n# old handoff\n';
fs.writeFileSync(path.join(target, 'HANDOFF.md'), oldDoc);
const hh = () => (fs.existsSync(path.join(target, 'handoff-history')) ? fs.readdirSync(path.join(target, 'handoff-history')) : []);
const stampOf = () => mp.readStamp(fs.readFileSync(path.join(target, 'HANDOFF.md'), 'utf8'));

let r = installMark(mk1, target, { config: cfg });
check('HANDOFF.md replaced when incoming Mk I is newer than installed', r.handoff.replaced && stampOf() === 1, r.handoff.reason);
check('old copy landed in handoff-history/', hh().length === 1 && /^HANDOFF-MkI-\d{8}T\d{6}Z-was-none\.md$/.test(hh()[0]), hh().join(', '));
check('backup holds the old text', fs.readFileSync(path.join(target, 'handoff-history', hh()[0]), 'utf8') === oldDoc);

r = installMark(mk2, target, { config: cfg });
check('HANDOFF.md replaced when incoming Mk II is newer than Mk I', r.handoff.replaced && stampOf() === 2, r.handoff.reason);
check('second backup is named was-MkI', hh().length === 2 && hh().some((f) => /-was-MkI\.md$/.test(f)), hh().join(', '));

const before = fs.readFileSync(path.join(target, 'HANDOFF.md'), 'utf8');
const nBackups = hh().length;
r = installMark(mk1, target, { config: cfg });
check('HANDOFF.md NOT replaced when incoming Mk I is older than installed Mk II', !r.handoff.replaced && stampOf() === 2 && fs.readFileSync(path.join(target, 'HANDOFF.md'), 'utf8') === before, r.handoff.reason);
check('no extra backup made for the refused replacement', hh().length === nBackups);

// 5. refusals
const snapshot = JSON.stringify(fs.readdirSync(target).sort());
const tampered = Buffer.from(mk1);
tampered[tampered.length - 20] ^= 0xff;
const c1 = throwsCode(() => installMark(tampered, target, { config: cfg }));
check('tampered file refused', c1 === 'DAMAGED', String(c1));
const wrongMagic = Buffer.from(mk1);
wrongMagic[0] ^= 0x01;
const c2 = throwsCode(() => installMark(wrongMagic, target, { config: cfg }));
check('file with wrong magic bytes refused', c2 === 'NOT_A_MARK', String(c2));
const tooNew = mp.packMark({ mark: 99, name: mp.markName(99), title: 't', notes: '', created: new Date().toISOString(), minShell: '999.0.0' }, { 'HANDOFF.md': '<!-- handoff-mark: 99 -->\n' }, { config: cfg });
const c3 = throwsCode(() => installMark(tooNew, target, { config: cfg }));
check('file needing a newer shell refused', c3 === 'TOO_NEW', String(c3));
check('refusals changed nothing in the target', JSON.stringify(fs.readdirSync(target).sort()) === snapshot && stampOf() === 2);

// 6. the real project was not touched
check('real marks/history.json unchanged', fs.readFileSync(histPath, 'utf8') === historyBefore);

if (process.argv.includes('--keep')) console.log('scratch kept at ' + scratch); else fs.rmSync(scratch, { recursive: true, force: true });
console.log('\n' + pass + '/' + total + ' checks passed');
process.exit(pass === total ? 0 : 1);
