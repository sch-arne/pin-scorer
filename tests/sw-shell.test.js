// Der Service-Worker muss ALLE App-Module vorab cachen — sonst fehlen sie beim ersten
// Offline-Start (und ein Nachladen scheitert genau dann, wenn man es braucht).
//
// Der Auslöser für diesen Test: in `sw.js` fehlten elf Dateien, darunter aus app.js
// STATISCH importierte Views (setup-wettkampf, wettkampf-hub, anlagen). Beim Hinzufügen
// eines Moduls vergisst man den Eintrag leicht — dieser Test erinnert daran.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// Nicht auslieferbare Dateien: die lokale Entwicklungs-Config wird bewusst nie deployed.
const AUSGENOMMEN = new Set(['js/backend/config.local.js']);

function alleModule(dir) {
  const out = [];
  for (const eintrag of readdirSync(dir)) {
    const voll = join(dir, eintrag);
    if (statSync(voll).isDirectory()) out.push(...alleModule(voll));
    else if (eintrag.endsWith('.js')) out.push(relative(ROOT, voll).split(sep).join('/'));
  }
  return out;
}

const sw = readFileSync(join(ROOT, 'sw.js'), 'utf8');
const shell = new Set([...sw.matchAll(/'\.\/([^']+)'/g)].map((m) => m[1]));

test('sw.js cacht jedes App-Modul aus js/ vorab', () => {
  const fehlt = alleModule(join(ROOT, 'js'))
    .filter((f) => !AUSGENOMMEN.has(f))
    .filter((f) => !shell.has(f))
    .sort();
  assert.deepEqual(fehlt, [], `Diese Module fehlen in der SHELL-Liste von sw.js:\n- ${fehlt.join('\n- ')}`);
});

test('sw.js listet keine Datei, die es nicht gibt', () => {
  const vorhanden = new Set(alleModule(join(ROOT, 'js')));
  const tot = [...shell].filter((f) => f.startsWith('js/') && !vorhanden.has(f)).sort();
  assert.deepEqual(tot, [], `Diese Einträge in sw.js zeigen ins Leere:\n- ${tot.join('\n- ')}`);
});

test('sw.js cacht die Einstiegsdateien der App', () => {
  ['./', './index.html', './manifest.webmanifest', './css/app.css', './js/app.js']
    .forEach((p) => assert.ok(sw.includes(`'${p}'`), `${p} fehlt in der SHELL-Liste`));
});
