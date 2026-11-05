'use strict';
// markpack.js: shared helpers for the update-file ("mark") system.
// Used by make-mark.js (build) and install-mark.js (install). Node built-ins only.
// Reads scripts/mark.config.json for the extension, project name and shipped files.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const zlib = require('zlib');

const CONFIG_PATH = path.join(__dirname, 'mark.config.json');
function loadConfig() { return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); }

const sha256 = (b) => crypto.createHash('sha256').update(b).digest('hex');

function fail(code, msg) { const e = new Error(msg); e.code = code; return e; }

// ---------- roman numerals ----------
const ROMAN = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
  [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
function toRoman(n) {
  if (!Number.isInteger(n) || n < 1 || n > 3999) throw new Error('mark number out of range: ' + n);
  let out = '';
  for (const [v, s] of ROMAN) while (n >= v) { out += s; n -= v; }
  return out;
}
// Display name: "Mk IV". Tag for file names: "MkIV".
function markName(n) { return 'Mk ' + toRoman(n); }
function markTag(n) { return 'Mk' + toRoman(n); }
// Tag for a HANDOFF stamp that may be missing or zero (used in backup file names).
function stampTag(n) { return n == null ? 'unstamped' : n < 1 ? 'none' : markTag(n); }

// ---------- extension and magic bytes ----------
function normaliseExt(raw) {
  const s = String(raw || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!s) throw new Error('the extension needs at least one letter or digit');
  return '.' + s;
}
function magicFor(ext) {
  const s = String(ext).replace(/^\./, '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  return Buffer.from((s + '________').slice(0, 8), 'latin1');
}

// ---------- versions ----------
function cmpVersion(a, b) {
  const pa = String(a).split('.').map((x) => parseInt(x, 10) || 0);
  const pb = String(b).split('.').map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d < 0 ? -1 : 1;
  }
  return 0;
}

// ---------- paths ----------
function safeRel(p) {
  const s = String(p).replace(/\\/g, '/');
  if (!s || s.startsWith('/') || /^[a-zA-Z]:/.test(s) || s.split('/').some((seg) => seg === '..' || seg === '')) {
    throw fail('DAMAGED', 'unsafe path in update file: ' + p);
  }
  return s;
}

// ---------- container ----------
// bytes 0-7: magic | u32 BE header length L | L bytes UTF-8 JSON header | gzip(all files concatenated)
function packMark(meta, fileMap, opts = {}) {
  const cfg = opts.config || loadConfig();
  const magic = magicFor(opts.ext || cfg.ext);
  const names = Object.keys(fileMap).sort();
  const parts = [];
  const files = [];
  let offset = 0;
  for (const n of names) {
    const b = Buffer.isBuffer(fileMap[n]) ? fileMap[n] : Buffer.from(fileMap[n]);
    parts.push(b);
    files.push({ path: safeRel(n), size: b.length, offset, sha256: sha256(b) });
    offset += b.length;
  }
  const payload = Buffer.concat(parts);
  const gz = zlib.gzipSync(payload, { level: 9 });
  const header = Object.assign({ format: 1 }, meta, {
    payloadSize: payload.length,
    payloadSha256: sha256(payload),
    gzipBytes: gz.length,
    files,
  });
  const hb = Buffer.from(JSON.stringify(header), 'utf8');
  const len = Buffer.alloc(4);
  len.writeUInt32BE(hb.length, 0);
  return Buffer.concat([magic, len, hb, gz]);
}

// Throws an Error with .code of NOT_A_MARK, DAMAGED or TOO_NEW. Checksums catch damage, they are not signatures.
function parseMark(buf, shellVersion, opts = {}) {
  const cfg = opts.config || loadConfig();
  const exts = [cfg.ext].concat(cfg.previousExts || []);
  if (!Buffer.isBuffer(buf) || buf.length < 12) throw fail('NOT_A_MARK', 'not an update file (too short)');
  const magic = buf.subarray(0, 8).toString('latin1');
  if (!exts.some((e) => magicFor(e).toString('latin1') === magic)) {
    throw fail('NOT_A_MARK', 'not an update file (wrong magic bytes)');
  }
  const L = buf.readUInt32BE(8);
  if (L < 2 || 12 + L > buf.length) throw fail('DAMAGED', 'update file is damaged (bad header length)');
  let header;
  try { header = JSON.parse(buf.subarray(12, 12 + L).toString('utf8')); }
  catch (e) { throw fail('DAMAGED', 'update file is damaged (header is not valid JSON)'); }
  let payload;
  try { payload = zlib.gunzipSync(buf.subarray(12 + L)); }
  catch (e) { throw fail('DAMAGED', 'update file is damaged (payload will not decompress)'); }
  if (payload.length !== header.payloadSize || sha256(payload) !== header.payloadSha256) {
    throw fail('DAMAGED', 'update file is damaged (payload checksum mismatch)');
  }
  const files = {};
  for (const f of header.files || []) {
    const rel = safeRel(f.path);
    const b = payload.subarray(f.offset, f.offset + f.size);
    if (b.length !== f.size || sha256(b) !== f.sha256) throw fail('DAMAGED', 'update file is damaged (checksum mismatch in ' + rel + ')');
    files[rel] = Buffer.from(b);
  }
  if (shellVersion != null && header.minShell && cmpVersion(header.minShell, shellVersion) > 0) {
    throw fail('TOO_NEW', 'this update file needs shell ' + header.minShell + ' or newer (running ' + shellVersion + ')');
  }
  return { header, files, handoff: files['HANDOFF.md'] || null };
}

// ---------- HANDOFF.md text helpers ----------
const STAMP_RE = /^<!--\s*handoff-mark:\s*(\d+)\s*-->\s*$/;
const CURRENT_RE = /^\*\*Current mark:.*$/m;
const CHANGELOG_RE = /^#{1,3}\s+(?:\d+\.\s+)?Change log\s*$/i;
const eolOf = (t) => (t.includes('\r\n') ? '\r\n' : '\n');

function readStamp(text) {
  const m = STAMP_RE.exec(text.split(/\r?\n/, 1)[0]);
  return m ? parseInt(m[1], 10) : null;
}
// Puts exactly one stamp on line 1 and removes any other stamp lines.
function setStamp(text, n) {
  const lines = text.split(/\r?\n/).filter((l) => !STAMP_RE.test(l));
  lines.unshift('<!-- handoff-mark: ' + n + ' -->');
  return lines.join(eolOf(text));
}
function setCurrentMark(text, n) {
  const line = '**Current mark: ' + markName(n) + '**';
  if (CURRENT_RE.test(text)) return text.replace(CURRENT_RE, line);
  const eol = eolOf(text);
  const lines = text.split(/\r?\n/);
  lines.splice(1, 0, '', line);
  return lines.join(eol);
}
function hasEntryFor(text, n) {
  return new RegExp('^###\\s+.*\\bMk ' + toRoman(n) + '\\s+"', 'm').test(text);
}
// Inserts the entry at the top of the change log (directly under the Format: line when there is one).
function addChangeLogEntry(text, entry) {
  const eol = eolOf(text);
  const lines = text.split(/\r?\n/);
  const h = lines.findIndex((l) => CHANGELOG_RE.test(l));
  if (h < 0) throw new Error('HANDOFF.md has no "Change log" heading');
  let i = h + 1;
  while (i < lines.length && lines[i].trim() === '') i++;
  const insertAt = i < lines.length && /^(\*\*)?Format:/i.test(lines[i]) ? i + 1 : h + 1;
  const block = [''].concat(entry.replace(/\s+$/, '').split(/\r?\n/));
  if (insertAt < lines.length && lines[insertAt].trim() !== '') block.push('');
  lines.splice(insertAt, 0, ...block);
  return lines.join(eol);
}

// ---------- syncHandoff ----------
// Replaces <targetDir>/HANDOFF.md only when the incoming stamp is strictly NEWER.
// The replaced copy goes to handoff-history/HANDOFF-<label>-<timestamp>-was-Mk<Roman>.md.
function syncHandoff(incoming, targetDir, opts = {}) {
  const inStamp = readStamp(incoming.toString('utf8'));
  const dest = path.join(targetDir, 'HANDOFF.md');
  if (inStamp == null) return { replaced: false, backup: null, reason: 'incoming HANDOFF.md has no handoff-mark stamp, kept the installed one' };
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(targetDir, { recursive: true });
    fs.writeFileSync(dest, incoming);
    return { replaced: true, backup: null, reason: 'no HANDOFF.md was installed yet' };
  }
  const cur = fs.readFileSync(dest);
  const curStamp = readStamp(cur.toString('utf8'));
  if (curStamp != null && inStamp <= curStamp) {
    return { replaced: false, backup: null, reason: 'incoming ' + stampTag(inStamp) + ' is not newer than installed ' + stampTag(curStamp) };
  }
  const dir = path.join(targetDir, 'handoff-history');
  fs.mkdirSync(dir, { recursive: true });
  const ts = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const label = opts.label || stampTag(inStamp);
  let backup = path.join(dir, 'HANDOFF-' + label + '-' + ts + '-was-' + stampTag(curStamp) + '.md');
  for (let k = 2; fs.existsSync(backup); k++) {
    backup = path.join(dir, 'HANDOFF-' + label + '-' + ts + '-' + k + '-was-' + stampTag(curStamp) + '.md');
  }
  fs.writeFileSync(backup, cur);
  fs.writeFileSync(dest, incoming);
  return { replaced: true, backup, reason: stampTag(inStamp) + ' is newer than ' + stampTag(curStamp) };
}

module.exports = {
  loadConfig, sha256, toRoman, markName, markTag, stampTag, normaliseExt, magicFor, cmpVersion, safeRel,
  packMark, parseMark, readStamp, setStamp, setCurrentMark, hasEntryFor, addChangeLogEntry, syncHandoff,
};
