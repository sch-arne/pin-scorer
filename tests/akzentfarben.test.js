// Standard-Akzentfarben des Livestream-Overlays (AKZENT_PRESETS in
// views/livestream-einstellungen.js).
//
// Die Akzentfarbe trägt im Overlay Mannschaftsnamen, Punktestand und Bahn-Ränder — auf dem
// dunklen Grund der Tafeln (#1a1e27). Eine zu dunkle Vorschlagsfarbe wäre im Stream nicht
// lesbar, und genau das kann man niemandem im laufenden Punktspiel erklären. Dieser Test
// hält die Zusage aus dem Modul-Kommentar fest: JEDER Vorschlag bringt mindestens 6:1
// Kontrast mit (WCAG AA für großen Text wäre 3:1, für normalen 4.5:1).
//
// Der frei wählbare Farbwähler daneben bleibt davon unberührt — wer bewusst Dunkelblau will,
// bekommt es.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AKZENT_PRESETS } from '../js/views/livestream-einstellungen.js';

// Hintergrund der Overlay-Tafeln (css/app.css, .ov-wait/.ov-table).
const OVERLAY_BG = '#1a1e27';

// Relative Leuchtdichte nach WCAG 2.1.
function leuchtdichte(hex) {
  const kanal = (v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return 0.2126 * kanal(r) + 0.7152 * kanal(g) + 0.0722 * kanal(b);
}

function kontrast(a, b) {
  const la = leuchtdichte(a);
  const lb = leuchtdichte(b);
  const [hell, dunkel] = la > lb ? [la, lb] : [lb, la];
  return (hell + 0.05) / (dunkel + 0.05);
}

test('Jede Standard-Akzentfarbe ist auf dem Overlay-Grund lesbar', () => {
  assert.ok(AKZENT_PRESETS.length >= 4, 'zu wenige Vorschläge');
  AKZENT_PRESETS.forEach(({ hex, name }) => {
    assert.match(hex, /^#[0-9A-Fa-f]{6}$/, `${name}: kein #rrggbb`);
    assert.ok(name && name.trim(), `${hex}: ohne Namen (Titel/Vorlesehilfe)`);
    const k = kontrast(hex, OVERLAY_BG);
    assert.ok(k >= 6, `${name} (${hex}) ist mit ${k.toFixed(1)}:1 zu dunkel für das Overlay`);
  });
});

test('Kegel-Gold ist der Standard und steht vorn', () => {
  // Gold ist die Farbe, die eine Mannschaft ohne eigene Akzentfarbe ohnehin trägt
  // (ACCENT_DEFAULT). Es gehört deshalb an die erste Stelle der Palette.
  assert.equal(AKZENT_PRESETS[0].hex.toLowerCase(), '#f5a623', 'Gold steht nicht an erster Stelle');
  assert.match(AKZENT_PRESETS[0].name, /Standard/, 'Gold ist nicht als Standard benannt');
});

test('Das vorgegebene Grün (R111 G214 B97) ist in der Palette', () => {
  const gruen = AKZENT_PRESETS.find((p) => p.hex.toLowerCase() === '#6fd661');
  assert.ok(gruen, 'der vorgegebene Grünton fehlt');
  assert.equal(gruen.name, 'Grün');
});

test('Keine Farbe doppelt — sonst raten zwei Tupfer dasselbe', () => {
  const hexe = AKZENT_PRESETS.map((p) => p.hex.toLowerCase());
  assert.equal(new Set(hexe).size, hexe.length);
});
