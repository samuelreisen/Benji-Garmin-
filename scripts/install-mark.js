#!/usr/bin/env node
'use strict';
// install-mark.js: apply an update file ("mark") to a project folder. Node built-ins only.
// For projects with no updater of their own. App projects can require() installMark() from their updater instead.
//
//   node scripts/install-mark.js <file> [--target dir] [--shell x.y.z] [--dry-run]
//   node scripts/install-mark.js --list [--target dir]
//   node scripts/install-mark.js --switch <III|3|"Mk III"> [--target dir]
//
// HANDOFF.md is split out and goes through syncHandoff: it only replaces the installed copy when the
// incoming handoff-mark is strictly newer, and the replaced copy is kept in handoff-history/.

const fs = require('fs');
const path = require('path');
const mp = require('./markpack');

const KEEP = 5; // installed marks kept for switching back

function storeDir(target) { return path.join(target, 'marks', 'installed'); }

function listInstalled(target, cfg) {
  const dir = storeDir(target);
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const f of fs.readdirSync(dir)) {
    try {
      const { header } = mp.parseMark(fs.readFileSync(path.join(dir, f)), null, { config: cfg });
      out.push({ file: path.join(dir, f), mark: header.mark, name: mp.markName(header.mark), title: header.title, created: header.created });
    } catch (e) { /* not a readable mark, ignore */ }
  }
  return out.sort((a, b) => b.mark - a.mark);
}

function currentMark(target) {
  try { return JSON.parse(fs.readFileSync(path.join(target, 'mark.json'), 'utf8')).mark; } catch (e) { return null; }
}

// Returns { mark, name, written, handoff }. Throws (with .code) on a bad, damaged or too-new file, before touching anything.
function installMark(buf, target, opts = {}) {
  const cfg = opts.config || mp.loadConfig();
  const shell = opts.shellVersion || cfg.shellVersion || '1.0.0';
  const { header, files, handoff } = mp.parseMark(buf, shell, { config: cfg });
  if (opts.dryRun) {
    return { mark: header.mark, name: mp.markName(header.mark), written: Object.keys(files).filter((f) => f !== 'HANDOFF.md'), handoff: { replaced: false, reason: 'dry run' }, dryRun: true };
  }
  const written = [];
  for (const rel of Object.keys(files)) {
    if (rel === 'HANDOFF.md') continue;
    const dest = path.join(target, ...mp.safeRel(rel).split('/'));
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, files[rel]);
    written.push(rel);
  }
  const sync = handoff ? mp.syncHandoff(handoff, target, { label: mp.markTag(header.mark) }) : { replaced: false, reason: 'update file carried no HANDOFF.md' };
  if (opts.store !== false) {
    const dir = storeDir(target);
    fs.mkdirSync(dir, { recursive: true });
    const project = String(cfg.project || 'project').replace(/[^A-Za-z0-9_-]/g, '');
    fs.writeFileSync(path.join(dir, project + '-' + mp.markTag(header.mark) + cfg.ext), buf);
    for (const old of listInstalled(target, cfg).slice(KEEP)) fs.rmSync(old.file, { force: true });
  }
  return { mark: header.mark, name: mp.markName(header.mark), written, handoff: sync };
}

function main() {
  const argv = process.argv.slice(2);
  const o = { target: process.cwd() };
  let file;
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--target') o.target = path.resolve(argv[++i]);
    else if (k === '--shell') o.shell = argv[++i];
    else if (k === '--dry-run') o.dry = true;
    else if (k === '--list') o.list = true;
    else if (k === '--switch') o.switchTo = argv[++i];
    else if (!k.startsWith('--')) file = k;
    else { console.error('unknown argument ' + k); process.exit(1); }
  }
  const cfg = mp.loadConfig();
  try {
    if (o.list) {
      const cur = currentMark(o.target);
      const items = listInstalled(o.target, cfg);
      if (!items.length) return console.log('No installed marks stored in ' + storeDir(o.target));
      for (const it of items) console.log((it.mark === cur ? '* ' : '  ') + it.name + '  ' + (it.title || '') + '  (' + path.basename(it.file) + ')');
      return console.log('(* = installed now, newest ' + KEEP + ' kept)');
    }
    if (o.switchTo) {
      const want = o.switchTo.replace(/\s+/g, '').replace(/^mk/i, '').toUpperCase();
      const hit = listInstalled(o.target, cfg).find((it) => String(it.mark) === want || mp.toRoman(it.mark) === want);
      if (!hit) { console.error('No stored mark matches "' + o.switchTo + '". Try --list.'); process.exit(1); }
      file = hit.file;
    }
    if (!file) { console.error('usage: node scripts/install-mark.js <file> [--target dir] [--shell x.y.z] [--dry-run]'); process.exit(1); }
    const r = installMark(fs.readFileSync(file), o.target, { shellVersion: o.shell, dryRun: o.dry, store: !o.switchTo });
    console.log((o.dry ? '[dry run] would install ' : 'Installed ') + r.name + ' (' + r.written.length + ' files)');
    console.log('HANDOFF.md: ' + (r.handoff.replaced ? 'replaced (' + r.handoff.reason + ')' : 'kept (' + r.handoff.reason + ')'));
    if (r.handoff.backup) console.log('Old copy saved to ' + r.handoff.backup);
  } catch (e) {
    console.error('Refused: ' + e.message + (e.code ? ' [' + e.code + ']' : ''));
    process.exit(1);
  }
}

module.exports = { installMark, listInstalled };
if (require.main === module) main();
