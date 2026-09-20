// Spieler-Grafik: Maße, Layout und das Zeichnen auf eine Canvas.
//
// Schwester von logic/grafik-zeichnen.js (Ergebnis-Grafik) und nach denselben Regeln gebaut:
// Canvas statt SVG (die Vorschau IST das Exportbild), transparenter Hintergrund (clearRect,
// nie ein flächiges fillRect), Lesbarkeit über Textfarbe + Halo-Kontur + optionale Platten.
// Format, Schriftstapel, Farbwelt und die Textausgabe kommen von dort — beide Bilder sollen
// nebeneinander wie EIN Satz Grafiken aussehen.
//
// Die reine RECHNUNG steht in berechneSpielerLayout() und ist ohne DOM testbar (`messText`
// wird injiziert). Nur zeichneSpielerGrafik() braucht einen Browser.
//
// Das Besondere gegenüber der Ergebnis-Grafik ist das WURFRASTER: je Teilsatz eine Zeile
// mit allen Einzelwürfen. Wie viele Würfe eine Zeile trägt, ergibt sich aus der Zellbreite —
// 30 Würfe Bohle-Volle passen nicht mehr lesbar nebeneinander und werden umgebrochen.

import {
  FORMATE, PALETTE, familieVon, fontStr, rundRect, text, passeEin, kuerze, zeichneLogo,
} from './grafik-zeichnen.js';

// Kegel-Anordnung als Raute, Spalte/Reihe im 5×5-Raster (wie in der Erfassung und im
// Wurfprotokoll). Hier normalisiert auf 0…1, damit das Bild in jede Zellgröße passt.
//        9
//     7     8
//  4     5     6
//     2     3
//        1
const KEGEL_POS = {
  9: [3, 1], 7: [2, 2], 8: [4, 2], 4: [1, 3], 5: [3, 3], 6: [5, 3], 2: [2, 4], 3: [4, 4], 1: [3, 5],
};

// Farben der auffälligen Würfe. Je Textfarbe eigene Werte: ein helles Gold verschwindet auf
// hellem Grund, ein dunkles Rot auf dunklem.
const WURF_FARBEN = {
  hell: { neuner: '#ffc857', fehl: '#ff8f8f' },
  dunkel: { neuner: '#9a6400', fehl: '#b32d2d' },
};

// Alle Layout-Konstanten an einer Stelle. Breiten in Pixeln der 1080er-Bühne.
export const SP_METRIK = {
  rand: 44,
  luft: 14,
  modusBreite: 104,   // linke Spalte: „Volle" / „Kranz" / „Abräum."
  tsBreite: 96,       // rechte Spalte: Teilsatz-Summe
  minZelle: 30,       // darunter wird die Wurfzeile umgebrochen
  maxZelle: 76,       // breiter wird eine Zelle nicht — sonst stehen 4 Würfe verloren herum
  logoBox: 132,       // Kantenlänge des Mannschaftslogos im Kopf
  hoehen: {
    ueberschrift: 50, titel: 68, untertitel: 44, vorSatz: 16,
    satzkopf: 58, zeile: 52, kegel: 40, wurfnummer: 16, zeilenLuft: 2,
    hinweis: 46, vorFuss: 24, fussZeile: 54, gesamt: 86, plattenLuft: 10,
  },
  schrift: {
    ueberschrift: [34, 700], titel: [56, 800], untertitel: [28, 600],
    satz: [34, 800], bahn: [24, 600], satzHolz: [44, 800],
    modus: [23, 700], ts: [32, 800], hinweis: [24, 600],
    wurf: [34, 700], wurfNr: [15, 600],
    fussLabel: [24, 700], fussWert: [34, 800],
    gesamtLabel: [30, 700], gesamt: [58, 800],
  },
  radius: 14,
};

// Geometrie der Spalten einer Wurfzeile (x-Werte auf der 1080er-Bühne).
export function spaltenGeometrie() {
  const m = SP_METRIK;
  const x0 = m.rand;
  const x1 = 1080 - m.rand;
  const wurfX0 = x0 + m.modusBreite + m.luft;
  const wurfX1 = x1 - m.tsBreite - m.luft;
  return { x0, x1, breite: x1 - x0, wurfX0, wurfX1, wurfBreite: wurfX1 - wurfX0 };
}

// Wie viele Würfe passen in EINE Zeile, und wie breit wird eine Zelle?
// Erst die größtmögliche Zahl Zellen über `minZelle` bestimmen, dann auf die nötigen Zeilen
// gleichmäßig verteilen: 30 Würfe werden zu 2 × 15 und nicht zu 25 + 5.
export function zellenAufteilung(anzahl, breite) {
  const m = SP_METRIK;
  if (anzahl <= 0) return { proZeile: 0, zeilen: 0, zelleBreite: 0 };
  const passend = Math.max(1, Math.floor(breite / m.minZelle));
  const zeilen = Math.max(1, Math.ceil(anzahl / passend));
  const proZeile = Math.ceil(anzahl / zeilen);
  return { proZeile, zeilen, zelleBreite: Math.min(m.maxZelle, breite / proZeile) };
}

// Die Sätze in der gewünschten Reihenfolge. 'bahnen' sortiert nach der Bahnnummer (bei
// gleicher Bahn nach Satz) — sonst bleibt die Spielreihenfolge. Es wird nur SORTIERT, nie
// etwas weggelassen: jeder Satz steht genau einmal im Bild.
export function sortiereSaetze(saetze, reihenfolge) {
  const liste = (saetze || []).slice();
  if (reihenfolge !== 'bahnen') return liste;
  // Eine unbekannte Bahn (null, '') wandert ans Ende — Number(null) waere 0 und stellte sie
  // faelschlich an den Anfang.
  const nr = (b) => {
    if (b == null || b === '') return Number.POSITIVE_INFINITY;
    const n = Number(b);
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  };
  return liste.sort((a, b) => nr(a.bahn) - nr(b.bahn) || (a.nr || 0) - (b.nr || 0));
}

// Höhe einer Wurfzeile aus den gewählten Extras.
function zeilenHoehe(opts) {
  const H = SP_METRIK.hoehen;
  return H.zeile + (opts.kegelbilder ? H.kegel : 0) + (opts.wurfnummern ? H.wurfnummer : 0);
}

// Ein Posten der Fußzeile („Volle 220"): Label dim, Wert fett — beide gemessen, damit die
// Gruppen links und rechts sauber aneinanderstoßen.
function postenMessen(posten, messText, familie) {
  const S = SP_METRIK.schrift;
  return posten.map((p) => {
    const labelW = messText(p.label, fontStr(S.fussLabel[0], S.fussLabel[1], familie));
    const wertW = messText(String(p.val), fontStr(S.fussWert[0], S.fussWert[1], familie));
    return { ...p, labelW, wertW, breite: labelW + 10 + wertW };
  });
}

function gruppenBreite(posten) {
  return posten.reduce((s, p, i) => s + p.breite + (i ? 28 : 0), 0);
}

// Layout berechnen — reine Rechnung, kein DOM. `messText(text, font) -> px`.
// Rückgabe: alle y-Positionen RELATIV zum Blockanfang plus `yTop`/`skala`, und alle Texte
// bereits gekürzt — das Zeichnen muss nichts mehr entscheiden.
export function berechneSpielerLayout(modell, opts, messText) {
  const fmt = FORMATE[opts.format] || FORMATE.hoch;
  const H = SP_METRIK.hoehen;
  const S = SP_METRIK.schrift;
  const familie = familieVon(opts);
  const geo = spaltenGeometrie();

  let h = 0;
  const y = {};
  // Das Mannschaftslogo steht LINKS im Kopf und kostet keine eigene Höhe — der Text rückt
  // dafür nach rechts und wird in der verbleibenden Breite zentriert. Ein Logo über dem
  // Namen hätte den ohnehin knappen senkrechten Platz gekostet.
  const mitLogo = !!(opts.logo && modell.hatLogo);
  const kopfBreite = mitLogo ? geo.breite - SP_METRIK.logoBox - SP_METRIK.luft : geo.breite;
  const kopfMitte = mitLogo
    ? geo.x0 + SP_METRIK.logoBox + SP_METRIK.luft + kopfBreite / 2
    : 1080 / 2;

  // Drei Kopfzeilen, jede für sich weglassbar: freie Überschrift, Name, Kontextzeile.
  const ueberschrift = passeEin(String(modell.ueberschrift || '').trim(), kopfBreite, S.ueberschrift, 20, messText, familie);
  const titel = passeEin(String(modell.titel || '').trim(), kopfBreite, S.titel, 30, messText, familie);
  const untertitel = passeEin(String(modell.untertitel || '').trim(), kopfBreite, S.untertitel, 18, messText, familie);
  if (ueberschrift.text) { y.ueberschrift = h + H.ueberschrift / 2; h += H.ueberschrift; }
  if (titel.text) { y.titel = h + H.titel / 2; h += H.titel; }
  if (untertitel.text) { y.untertitel = h + H.untertitel / 2; h += H.untertitel; }
  y.kopfMitte = kopfMitte;
  if (mitLogo) {
    // Das Logo senkrecht auf die Mitte der Textzeilen ausrichten; ist der Kopf niedriger als
    // das Logo (nur ein Name), wächst er auf dessen Höhe mit.
    const box = SP_METRIK.logoBox;
    if (h < box) h = box;
    y.logo = { x: geo.x0 + box / 2, oben: (h - box) / 2, box };
  }

  const messModus = (s) => messText(s, fontStr(S.modus[0], S.modus[1], familie));
  const messHinweis = (s) => messText(s, fontStr(S.hinweis[0], S.hinweis[1], familie));
  const zh = zeilenHoehe(opts);

  const nachBahnen = opts.reihenfolge === 'bahnen';
  const saetze = sortiereSaetze(modell.saetze, opts.reihenfolge).map((s) => {
    h += H.vorSatz;
    const oben = h;
    const kopfMitte = h + H.satzkopf / 2;
    h += H.satzkopf;

    // Ein Satz, dessen Holz ohne Teilsatz-Aufteilung übermittelt wurde (Web-Import), bekommt
    // EINE Hinweiszeile statt leerer Teilsatz-Zeilen: die Aufteilung existiert nicht, sie ist
    // nicht bloß null.
    let zeilen = [];
    if (s.nurSatz) {
      zeilen = [{
        hinweis: kuerze('nur das Satz-Ergebnis übermittelt', geo.wurfBreite, messHinweis),
        oben: h, hoehe: H.hinweis, mitte: h + H.hinweis / 2,
        kurz: '', tsText: '', zellen: [],
      }];
      h += H.hinweis;
    } else {
      s.teilsaetze.forEach((ts) => {
        const tsText = (ts.holz || ts.manual || ts.wuerfe.length) ? String(ts.holz) : '';
        if (!ts.wuerfe.length) {
          // Kein einziger Wurf erfasst: bei gesetztem Ergebnis der Hinweis, sonst eine
          // stille Leerzeile — der Teilsatz ist schlicht noch nicht gespielt.
          const hinweis = ts.manual ? 'nur Ergebnis eingetragen' : '';
          zeilen.push({
            kurz: kuerze(ts.kurz, SP_METRIK.modusBreite, messModus),
            tsText,
            hinweis: hinweis ? kuerze(hinweis, geo.wurfBreite, messHinweis) : '',
            oben: h, hoehe: H.hinweis, mitte: h + H.hinweis / 2,
            zellen: [],
          });
          h += H.hinweis + H.zeilenLuft;
          return;
        }
        const auf = zellenAufteilung(ts.wuerfe.length, geo.wurfBreite);
        for (let li = 0; li < auf.zeilen; li += 1) {
          const teil = ts.wuerfe.slice(li * auf.proZeile, (li + 1) * auf.proZeile);
          zeilen.push({
            // Modus-Spalte und Teilsatz-Summe stehen nur an der ersten bzw. letzten Zeile
            // eines umgebrochenen Teilsatzes — sonst läse es sich wie zwei Teilsätze.
            kurz: li === 0 ? kuerze(ts.kurz, SP_METRIK.modusBreite, messModus) : '',
            tsText: li === auf.zeilen - 1 ? tsText : '',
            hinweis: '',
            oben: h, hoehe: zh, mitte: h + zh / 2,
            zelleBreite: auf.zelleBreite,
            // Zentriert, wenn die letzte Zeile nicht voll wird — eine linksbündige
            // Restzeile sähe wie ein Fehler aus.
            xStart: geo.wurfX0 + (geo.wurfBreite - teil.length * auf.zelleBreite) / 2,
            zellen: teil,
          });
          h += zh + H.zeilenLuft;
        }
      });
      if (zeilen.length) h -= H.zeilenLuft;
    }

    // Wonach sortiert wird, steht auch vorn: nach Bahnen sortiert ist „Bahn 3" die
    // Überschrift des Blocks und die Satz-Nummer der Zusatz — sonst umgekehrt.
    const satzText = s.nr + '. Satz';
    const bahnText = s.bahn == null || s.bahn === '' ? '' : 'Bahn ' + s.bahn;
    const block = {
      nr: s.nr,
      bahn: s.bahn,
      label: (nachBahnen && bahnText) ? bahnText : satzText,
      bahnLabel: (nachBahnen && bahnText) ? satzText : bahnText,
      holzText: s.gespielt ? String(s.holz) : '–',
      gespielt: s.gespielt,
      oben, kopfMitte, zeilen,
      hoehe: 0,
    };
    block.hoehe = h - oben;
    return block;
  });

  // ── Fußzeile ───────────────────────────────────────────────────────────────
  const fuss = { zeilen: [], oben: 0, hoehe: 0 };
  h += H.vorFuss;
  fuss.oben = h;
  if (opts.kennzahlen) {
    const links = postenMessen(modell.summen || [], messText, familie);
    const rechts = postenMessen([
      { label: '9er', val: modell.neuner || 0 },
      { label: 'Kränze', val: modell.kranz || 0 },
      { label: 'Fehler', val: modell.fehl || 0 },
    ], messText, familie);
    const lb = gruppenBreite(links);
    const rb = gruppenBreite(rechts);
    // Passt beides nebeneinander? Sonst untereinander — lieber eine Zeile mehr als ein
    // Überlappen der Zahlen.
    if (links.length && lb + rb + 40 > geo.breite) {
      fuss.zeilen.push({ links, rechts: [], mitte: h + H.fussZeile / 2 });
      h += H.fussZeile;
      fuss.zeilen.push({ links: [], rechts, mitte: h + H.fussZeile / 2 });
      h += H.fussZeile;
    } else {
      fuss.zeilen.push({ links, rechts, mitte: h + H.fussZeile / 2 });
      h += H.fussZeile;
    }
  }
  fuss.gesamtMitte = h + H.gesamt / 2;
  fuss.gesamtOben = h;
  h += H.gesamt;
  fuss.hoehe = h - fuss.oben;
  fuss.gesamtText = String(modell.gesamt || 0);
  fuss.schnittText = modell.wurfCount
    ? 'Ø ' + (Math.round((modell.schnitt || 0) * 100) / 100).toLocaleString('de-DE') + ' / Wurf'
    : '';

  const [obenK, untenK] = fmt.korridor;
  const verfuegbar = untenK - obenK;
  const skala = h > 0 ? Math.min(1, verfuegbar / h) : 1;
  const echt = h * skala;
  let yTop = obenK;
  if (opts.position === 'mitte') yTop = obenK + (verfuegbar - echt) / 2;
  else if (opts.position === 'unten') yTop = untenK - echt;

  return {
    fmt, familie, geo, y, mitLogo, ueberschrift, titel, untertitel, saetze, fuss,
    hoehe: h, skala, yTop,
  };
}

// ── Zeichnen (Browser) ───────────────────────────────────────────────────────

// Kegelbild eines Wurfs: gefallene Kegel gefüllt, stehende nur umrissen.
// `fallen` = null -> kein Bild (unbekannter Reststand); dann bleibt die Fläche leer.
function zeichneKegel(ctx, fallen, cx, cy, groesse, farben) {
  if (!Array.isArray(fallen)) return;
  const gefallen = new Set(fallen);
  const r = groesse / 22;
  for (let n = 1; n <= 9; n += 1) {
    const [col, row] = KEGEL_POS[n];
    const x = cx - groesse / 2 + ((col - 1) * 4 + 3) * r;
    const y = cy - groesse / 2 + ((row - 1) * 4 + 3) * r;
    ctx.beginPath();
    ctx.arc(x, y, r * (gefallen.has(n) ? 1.8 : 1.5), 0, Math.PI * 2);
    if (gefallen.has(n)) {
      ctx.fillStyle = farben.voll;
      ctx.fill();
    } else {
      ctx.lineWidth = Math.max(1, r * 0.7);
      ctx.strokeStyle = farben.leer;
      ctx.stroke();
    }
  }
}

// Die Spieler-Grafik auf die Canvas zeichnen. Die Canvas-Maße werden hier gesetzt — das
// setzt den Kontext ohnehin zurück.
// `bilder` ist eine Map mannschaftId -> geladenes Image (das Laden macht das Panel, damit
// dieses Modul ohne DOM auskommt) — dieselbe Map wie bei der Ergebnis-Grafik.
export function zeichneSpielerGrafik(canvas, modell, opts, bilder = {}) {
  const ctx = canvas.getContext('2d');
  const messText = (s, font) => { ctx.font = font; return ctx.measureText(s).width; };
  const L = berechneSpielerLayout(modell, opts, messText);
  const P = PALETTE[opts.textfarbe] || PALETTE.hell;
  const W = WURF_FARBEN[opts.textfarbe] || WURF_FARBEN.hell;
  const platte = P.platte[opts.flaechen] || null;
  const S = SP_METRIK.schrift;
  const H = SP_METRIK.hoehen;

  if (canvas.width !== L.fmt.w) canvas.width = L.fmt.w;
  if (canvas.height !== L.fmt.h) canvas.height = L.fmt.h;
  ctx.clearRect(0, 0, L.fmt.w, L.fmt.h);

  const kontur = opts.kontur === false ? null : P.kontur;
  const stil = (schrift, farbe = P.text, align = 'center') =>
    ({ schrift, farbe, align, kontur, familie: L.familie });

  ctx.save();
  // Block als Ganzes an seinen Platz und (bei vielen Sätzen) verkleinern.
  ctx.translate(L.fmt.w / 2, L.yTop);
  ctx.scale(L.skala, L.skala);
  ctx.translate(-L.fmt.w / 2, 0);

  const kx = L.y.kopfMitte;
  if (L.ueberschrift.text) text(ctx, L.ueberschrift.text, kx, L.y.ueberschrift, stil(L.ueberschrift.schrift));
  if (L.titel.text) text(ctx, L.titel.text, kx, L.y.titel, stil(L.titel.schrift));
  if (L.untertitel.text) text(ctx, L.untertitel.text, kx, L.y.untertitel, stil(L.untertitel.schrift, P.dim));
  if (L.mitLogo && L.y.logo) {
    zeichneLogo(ctx, bilder[modell.mannschaftId], L.y.logo.x, L.y.logo.oben, L.y.logo.box, modell.logoBg);
  }

  const g = L.geo;
  L.saetze.forEach((s) => {
    // EINE Platte je Satz (Kopf + seine Wurfzeilen) — sie fasst zusammen, was zusammengehört.
    if (platte) {
      ctx.fillStyle = platte;
      rundRect(ctx, g.x0 - 8, s.oben - H.plattenLuft / 2, g.breite + 16, s.hoehe + H.plattenLuft, SP_METRIK.radius);
      ctx.fill();
    }
    text(ctx, s.label, g.x0, s.kopfMitte, stil(S.satz, P.text, 'left'));
    if (s.bahnLabel) {
      const breite = messText(s.label, fontStr(S.satz[0], S.satz[1], L.familie));
      text(ctx, s.bahnLabel, g.x0 + breite + 14, s.kopfMitte, stil(S.bahn, P.dim, 'left'));
    }
    text(ctx, s.holzText, g.x1, s.kopfMitte, stil(S.satzHolz, s.gespielt ? P.text : P.dim, 'right'));
    // Feine Linie unter dem Satzkopf — trennt Überschrift und Wurfraster.
    ctx.fillStyle = P.linie;
    ctx.fillRect(g.x0, s.oben + H.satzkopf - 6, g.breite, 2);

    s.zeilen.forEach((z) => {
      if (z.kurz) text(ctx, z.kurz, g.x0, z.mitte, stil(S.modus, P.dim, 'left'));
      if (z.tsText) text(ctx, z.tsText, g.x1, z.mitte, stil(S.ts, P.text, 'right'));
      if (z.hinweis) {
        text(ctx, z.hinweis, g.wurfX0 + g.wurfBreite / 2, z.mitte, stil(S.hinweis, P.dim));
        return;
      }
      const zb = z.zelleBreite;
      const wurfGroesse = Math.max(14, Math.min(S.wurf[0], zb * 0.66));
      const kegelGroesse = Math.min(zb * 0.72, H.kegel * 0.86);
      // Senkrechter Aufbau einer Zelle: Kegelbild · Wurfzahl · Wurfnummer.
      const zahlY = z.oben + (opts.kegelbilder ? H.kegel : 0) + H.zeile / 2;
      const kegelY = z.oben + H.kegel / 2;
      const nrY = z.oben + z.hoehe - H.wurfnummer / 2;
      z.zellen.forEach((w, i) => {
        const cx = z.xStart + (i + 0.5) * zb;
        if (opts.kegelbilder) {
          zeichneKegel(ctx, w.kegel, cx, kegelY, kegelGroesse, { voll: P.text, leer: P.dim });
        }
        const farbe = w.neuner ? W.neuner : (w.fehl ? W.fehl : P.text);
        text(ctx, String(w.wert), cx, zahlY, stil([wurfGroesse, S.wurf[1]], farbe));
        // Kranz: das ♔ sitzt hochgestellt neben der Zahl, wie im Wurfprotokoll.
        if (w.kranz) {
          text(ctx, '♔', cx + zb * 0.3, zahlY - wurfGroesse * 0.38,
            stil([Math.max(11, wurfGroesse * 0.5), 700], W.neuner));
        }
        if (opts.wurfnummern) text(ctx, String(w.nr), cx, nrY, stil(S.wurfNr, P.dim));
      });
    });
  });

  // ── Fußzeile ───────────────────────────────────────────────────────────────
  const f = L.fuss;
  if (platte) {
    ctx.fillStyle = platte;
    rundRect(ctx, g.x0 - 8, f.oben - H.plattenLuft / 2, g.breite + 16, f.hoehe + H.plattenLuft, SP_METRIK.radius);
    ctx.fill();
  }
  const zeichnePosten = (posten, x, mitte) => {
    let cur = x;
    posten.forEach((p) => {
      text(ctx, p.label, cur, mitte, stil(S.fussLabel, P.dim, 'left'));
      text(ctx, String(p.val), cur + p.labelW + 10, mitte, stil(S.fussWert, P.text, 'left'));
      cur += p.breite + 28;
    });
  };
  f.zeilen.forEach((z) => {
    if (z.links.length) zeichnePosten(z.links, g.x0, z.mitte);
    if (z.rechts.length) zeichnePosten(z.rechts, g.x1 - gruppenBreite(z.rechts), z.mitte);
  });
  ctx.fillStyle = P.linie;
  ctx.fillRect(g.x0, f.gesamtOben, g.breite, 2);
  text(ctx, 'GESAMT', g.x0, f.gesamtMitte, stil(S.gesamtLabel, P.dim, 'left'));
  if (f.schnittText) {
    text(ctx, f.schnittText, g.x0 + 160, f.gesamtMitte, stil(S.bahn, P.dim, 'left'));
  }
  text(ctx, f.gesamtText, g.x1, f.gesamtMitte, stil(S.gesamt, P.text, 'right'));

  ctx.restore();
  return L;
}
