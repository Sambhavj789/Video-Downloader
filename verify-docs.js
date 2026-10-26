'use strict';

// Zero-dependency docs gate. Copy with the docs kit; wire it into the project's verify
// command. Configure required docs and source roots in doc-check.json.

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const CONFIG = path.join(ROOT, 'doc-check.json');
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const SOURCE_EXT = new Set([
  '.js', '.jsx', '.ts', '.tsx', '.py', '.go', '.rs', '.java', '.kt', '.swift',
  '.sql', '.css', '.html', '.sh', '.ps1', '.c', '.cpp', '.h', '.cs', '.rb',
  '.php', '.ex', '.exs', '.dart', '.lua', '.gd'
]);
const SKIP_DIR = new Set([
  '.git', 'node_modules', 'dist', 'build', 'coverage', '.next', '.nuxt', '.expo',
  'vendor', 'out', '.cache', '__pycache__', '.venv', 'venv', 'target', 'bin', 'obj'
]);

let passed = 0;
let failed = 0;

function ok(cond, label, detail) {
  if (cond) {
    passed++;
    console.log('PASS  ' + label);
  } else {
    failed++;
    console.error('FAIL  ' + label + (detail ? '\n      ' + detail : ''));
  }
}

function read(rel) {
  return fs.readFileSync(path.join(ROOT, rel), 'utf8');
}

function exists(rel) {
  return fs.existsSync(path.join(ROOT, rel));
}

if (!fs.existsSync(CONFIG)) {
  console.error('Missing doc-check.json');
  process.exit(1);
}

let config;
try {
  config = JSON.parse(fs.readFileSync(CONFIG, 'utf8'));
} catch (err) {
  console.error('Invalid doc-check.json: ' + err.message);
  process.exit(1);
}

const required = Array.isArray(config.required) ? config.required : [];
const sources = Array.isArray(config.sources) ? config.sources : [];

console.log('docs check — ' + path.basename(ROOT) + '\n');

const index = exists('docs/00-index.md') ? read('docs/00-index.md') : '';

required.forEach((rel) => {
  const present = exists(rel);
  ok(present, 'exists: ' + rel);
  if (!present) return;

  const text = read(rel);
  const min = rel.startsWith('docs/') ? 200 : 120;
  ok(text.length > min, 'non-trivial: ' + rel, text.length + ' bytes');

  if (rel.startsWith('docs/')) {
    const fm = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
    ok(!!fm, 'front matter: ' + rel);
    if (!fm) return;
    ok(/^title\s*:\s*\S+/m.test(fm[1]), 'front matter title: ' + rel);
    ok(/^status\s*:\s*(draft|active|superseded)\b/m.test(fm[1]), 'front matter status: ' + rel);
    const updated = (fm[1].match(/^updated\s*:\s*(\S+)/m) || [])[1];
    ok(DATE.test(updated || ''), 'front matter updated: ' + rel);
  }
});

required
  .filter((rel) => rel.startsWith('docs/') && rel !== 'docs/00-index.md')
  .forEach((rel) => {
    ok(index.includes(path.basename(rel)), 'index links: ' + path.basename(rel));
  });

const linkSources = ['README.md', 'AGENTS.md']
  .concat(required.filter((rel) => rel.startsWith('docs/')))
  .filter((rel) => exists(rel));

let linkCount = 0;
const broken = [];

linkSources.forEach((rel) => {
  const base = path.dirname(path.join(ROOT, rel));
  const text = read(rel);
  const re = /\[[^\]]*\]\(([^)\s]+)\)/g;
  let m;
  while ((m = re.exec(text))) {
    const href = m[1];
    if (/^(https?:|mailto:|#)/.test(href)) continue;
    const clean = href.split('#')[0].split('?')[0];
    if (!clean) continue;
    linkCount++;
    if (!fs.existsSync(path.resolve(base, clean))) broken.push(rel + ' -> ' + href);
  }
});

ok(broken.length === 0, 'relative links resolve (' + linkCount + ' checked)', broken.join('\n      '));

const codemap = exists('docs/CODEMAP.md') ? read('docs/CODEMAP.md') : '';
const files = [];

function walk(dir) {
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true });
  } catch (_) {
    return;
  }
  entries.forEach((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!SKIP_DIR.has(entry.name)) walk(full);
      return;
    }
    if (!SOURCE_EXT.has(path.extname(entry.name).toLowerCase())) return;
    files.push(full);
  });
}

sources.forEach((rel) => {
  const full = path.join(ROOT, rel);
  if (fs.existsSync(full) && fs.statSync(full).isDirectory()) walk(full);
});

const unmapped = files
  .map((full) => path.relative(ROOT, full).replace(/\\/g, '/'))
  .filter((rel) => !codemap.includes(rel) && !codemap.includes(path.basename(rel)));

ok(unmapped.length === 0, 'sources are in CODEMAP (' + files.length + ' checked)',
  'unmapped:\n      ' + unmapped.slice(0, 20).join('\n      '));

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed === 0 ? 0 : 1);
