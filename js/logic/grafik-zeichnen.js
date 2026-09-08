// Ergebnis-Grafik: Maße, Layout und das Zeichnen auf eine Canvas.
//
// Warum Canvas und nicht SVG: der Weg SVG -> PNG führt zwingend über ein isoliertes <img>.
// Dort rastert WebKit kein <foreignObject>, Schriften werden anders aufgelöst als in der
// Vorschau (Vorschau ≠ Export) und Text lässt sich nur über ein zweites Mess-SVG im DOM
// vermessen. Auf der Canvas messen und zeichnen dieselben Aufrufe, die auch das Bitmap
// erzeugen — die Vorschau IST das Exportbild.
//
// Der Hintergrund bleibt TRANSPARENT (bewusste Produktentscheidung): das PNG wird über ein
// eigenes Foto oder den Stream gelegt. Deshalb beginnt jedes Zeichnen mit clearRect und
// NIE mit einem fillRect über die ganze Fläche. Weil das Bild damit auf hellem wie auf
// dunklem Grund landen kann, sichern drei Ebenen die Lesbarkeit: umschaltbare Textfarbe,
// eine Halo-Kontur um jede Schrift (strokeText vor fillText) und optionale halbtransparente
// Platten hinter den Zeilen.
//
// Die reine RECHNUNG (Maße, Umbruch, Kürzung, Skalierung) steht in berechneLayout() und ist
// ohne DOM per Unit-Test prüfbar — `messText` wird injiziert. Nur zeichneGrafik() braucht
// einen Browser; document/window werden nirgends auf Modulebene angefasst.

// Die beiden Ausgabeformate. `korridor` ist der vertikal NUTZBARE Bereich: bei der Story
// bleiben oben die Profilleiste und unten das Antwortfeld der Netzwerke frei.
export const FORMATE = {
  hoch: { id: 'hoch', w: 1080, h: 1440, korridor: [60, 1380], label: 'Hochformat', masse: '1080 × 1440' },
  story: { id: 'story', w: 1080, h: 1920, korridor: [250, 1600], label: 'Story', masse: '1080 × 1920' },
};

// Auswählbare Schriften. Nur Systemschriften — die App bringt keine Fontdateien mit, und
// eine nachzuladende Webfont wäre beim ersten Zeichnen noch nicht vermessbar. Jeder Stapel
// endet deshalb auf einer Gattung, die überall vorhanden ist: fehlt die Wunschschrift auf
// dem Gerät, sieht das Bild schlichter aus, bleibt aber korrekt gesetzt.
export const SCHRIFTEN = {
  system: {
    id: 'system', label: 'System',
    stack: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  },
  schmal: {
    id: 'schmal', label: 'Schmal',
    stack: '"Arial Narrow", "Roboto Condensed", "Liberation Sans Narrow", "Helvetica Neue", sans-serif',
  },
  serif: {
    id: 'serif', label: 'Serif',
    stack: 'Georgia, "Times New Roman", "Noto Serif", serif',
  },
};

const FAMILIE = SCHRIFTEN.system.stack;

// Schriftstapel zu den Optionen (unbekannte Auswahl -> System).
export function familieVon(opts) {
  const s = SCHRIFTEN[opts && opts.schrift];
  return (s || SCHRIFTEN.system).stack;
}

// Alle Layout-Konstanten an einer Stelle. Breiten in Pixeln der 1080er-Bühne.
//
// Die Spalten einer Seite füllen die Hälfte EXAKT aus (name + holz + ewp + 2 × spaltenLuft
// === halb) — geprüft in tests/grafik-zeichnen.test.js. Wer eine Zahlenspalte schmaler
// macht, gibt den Platz also direkt der Namensspalte; Rand und Mittelspalte sind bewusst
// knapp gehalten, damit die Namen möglichst lange ungekürzt bleiben.
export const METRIK = {
  rand: 44,              // Außenrand links/rechts
  mitte: 36,             // Lücke zwischen den beiden Mannschaftsspalten
  spaltenLuft: 12,       // Abstand zwischen den Spalten einer Seite
  spalten: {
    mitEwp: { name: 284, holz: 104, ewp: 66 },
    ohneEwp: { name: 362, holz: 104, ewp: 0 },
  },
  liste: { breite: 860, rang: 72, holz: 150, zeile: 78 },
  hoehen: {
    titel: 68, untertitel: 46, teamkopf: 72, spaltenkopf: 38,
    zeile: 66, zeilenLuft: 6, vorTrenn: 12, trenn: 24, summe: 70, vorLogo: 34, logo: 176,
  },
  schrift: {
    titel: [54, 800], untertitel: [28, 600], teamname: [42, 800], spaltenkopf: [20, 700],
    name: [34, 600], holz: [38, 800], ewp: [32, 700], summe: [40, 800], summeLabel: [30, 700],
    punkte: [96, 800], rang: [34, 700], listeName: [40, 600], listeHolz: [44, 800],
  },
  logoBox: 176,          // Kantenlänge der Logo-Fläche
  punkteBox: [300, 176], // Breite × Höhe der Spielpunkte-Kachel
  radius: 14,
};

// Farbwelten je Textfarbe. `kontur` ist der Halo um jede Schrift — auf unruhigen Fotos
// deutlich wirksamer als ein weicher Schatten allein.
const PALETTE = {
  hell: {
    text: '#ffffff',
    dim: 'rgba(255,255,255,0.72)',
    kontur: 'rgba(0,0,0,0.78)',
    linie: 'rgba(255,255,255,0.38)',
    platte: { aus: null, dezent: 'rgba(0,0,0,0.34)', kraeftig: 'rgba(0,0,0,0.58)' },
  },
  dunkel: {
    text: '#12151b',
    dim: 'rgba(18,21,27,0.68)',
    kontur: 'rgba(255,255,255,0.85)',
    linie: 'rgba(18,21,27,0.32)',
    platte: { aus: null, dezent: 'rgba(255,255,255,0.42)', kraeftig: 'rgba(255,255,255,0.70)' },
  },
};

const LOGO_PLATTE = 'rgba(255,255,255,0.92)'; // nur für Logos mit hellem Hintergrund

function fontStr(groesse, gewicht, familie) {
  return `${gewicht} ${groesse}px ${familie || FAMILIE}`;
}

// Text auf eine Breite kürzen: zeichenweise abschneiden und „…" anhängen.
// `mess(s) -> px` kennt die Schrift bereits (Closure), damit die Funktion rein bleibt.
export function kuerze(text, maxPx, mess) {
  const s = String(text == null ? '' : text);
  if (!s || mess(s) <= maxPx) return s;
  let kurz = s;
  while (kurz.length > 1 && mess(kurz + '…') > maxPx) kurz = kurz.slice(0, -1);
  return kurz + '…';
}

// Namen kürzen mit Vorstufe: passt „Vorname Nachname" nicht, wird erst der Vorname zum
// Initial („V. Nachname") — bei Kegelnamen fast immer besser lesbar als ein abgeschnittener
// Nachname. Erst wenn auch das nicht reicht, wird zeichenweise gekürzt.
export function kuerzeName(name, maxPx, mess) {
  const s = String(name == null ? '' : name).trim();
  if (!s || mess(s) <= maxPx) return s;
  const teile = s.split(/\s+/);
  if (teile.length > 1) {
    const kurz = teile[0].slice(0, 1) + '. ' + teile.slice(1).join(' ');
    if (mess(kurz) <= maxPx) return kurz;
    return kuerze(kurz, maxPx, mess);
  }
  return kuerze(s, maxPx, mess);
}

// Text in eine feste Breite bringen: erst die Schrift stufenweise verkleinern (bis `min`),
// erst dann kürzen. Für Titel und Mannschaftsnamen deutlich besser als sofortiges Abschneiden —
// „KV Blau Weiß Sontra 1 – VOK Osnabrück 1" bleibt so vollständig lesbar.
// Rückgabe: { text, schrift } zum direkten Weiterreichen an text().
export function passeEin(roh, maxPx, schrift, min, messText, familie) {
  const [gross, gewicht] = schrift;
  const s = String(roh == null ? '' : roh);
  let groesse = gross;
  while (groesse > min && messText(s, fontStr(groesse, gewicht, familie)) > maxPx) groesse -= 2;
  const mess = (t) => messText(t, fontStr(groesse, gewicht, familie));
  return { text: kuerze(s, maxPx, mess), schrift: [groesse, gewicht] };
}

// EINE Schriftgröße für alle Spielernamen: die größte (bis herunter zu `min`), in der noch
// jeder Name vollständig in die Spalte passt. Erst wenn selbst die kleinste Stufe nicht
// reicht, wird der längste Name abgekürzt — dann aber nur er, nicht die ganze Spalte.
// Uneinheitlich große Namen nebeneinander sähen unruhig aus, deshalb eine gemeinsame Größe.
export function namenSchrift(namen, maxPx, schrift, min, messText, familie) {
  const [gross, gewicht] = schrift;
  let groesse = gross;
  const passtAlles = (g) => namen.every((n) => messText(String(n || ''), fontStr(g, gewicht, familie)) <= maxPx);
  while (groesse > min && !passtAlles(groesse)) groesse -= 2;
  return [groesse, gewicht];
}

// Spaltengeometrie einer Duell-Seite. Rückgabe je Seite die x-Werte, die das Zeichnen
// braucht: `name` ist der Ausrichtungspunkt (links außen linksbündig, rechts außen
// rechtsbündig — die Namen stehen also immer außen und die Zahlen zur Mitte hin).
function spaltenGeometrie(mitEwp) {
  const m = METRIK;
  const b = mitEwp ? m.spalten.mitEwp : m.spalten.ohneEwp;
  const halb = (1080 - 2 * m.rand - m.mitte) / 2;
  // Links: NAME | HOLZ | EWP (EWP innen an der Mitte)
  const lName = [m.rand, m.rand + b.name];
  const lHolz = [lName[1] + m.spaltenLuft, lName[1] + m.spaltenLuft + b.holz];
  const lEwp = [lHolz[1] + m.spaltenLuft, lHolz[1] + m.spaltenLuft + b.ewp];
  // Rechts gespiegelt: EWP | HOLZ | NAME
  const r0 = m.rand + halb + m.mitte;
  const rEwp = [r0, r0 + b.ewp];
  const rHolz = [rEwp[1] + (b.ewp ? m.spaltenLuft : 0), rEwp[1] + (b.ewp ? m.spaltenLuft : 0) + b.holz];
  const rName = [rHolz[1] + m.spaltenLuft, rHolz[1] + m.spaltenLuft + b.name];
  return {
    halb,
    breiten: b,
    links: {
      x0: m.rand, x1: m.rand + halb,
      name: lName[1], nameAlign: 'right', nameBreite: b.name,
      holz: (lHolz[0] + lHolz[1]) / 2,
      ewp: (lEwp[0] + lEwp[1]) / 2,
    },
    rechts: {
      x0: r0, x1: r0 + halb,
      name: rName[0], nameAlign: 'left', nameBreite: b.name,
      holz: (rHolz[0] + rHolz[1]) / 2,
      ewp: (rEwp[0] + rEwp[1]) / 2,
    },
  };
}

// Layout berechnen — reine Rechnung, kein DOM. `messText(text, font) -> px`.
// Rückgabe enthält alle y-Positionen RELATIV zum Blockanfang plus `yTop`/`skala` für die
// Transformation, und die bereits gekürzten Texte: das Zeichnen muss nichts mehr entscheiden.
export function berechneLayout(modell, opts, messText) {
  const fmt = FORMATE[opts.format] || FORMATE.hoch;
  const H = METRIK.hoehen;
  const S = METRIK.schrift;
  const familie = familieVon(opts);
  const mess = (groesse, gewicht) => (s) => messText(s, fontStr(groesse, gewicht, familie));
  const duell = modell.modus === 'duell' && modell.teams.length === 2;
  const mitEwp = duell && !!opts.ewp;
  const geo = duell ? spaltenGeometrie(mitEwp) : null;

  const y = {};
  let h = 0;
  // Titel und Untertitel dürfen die volle Inhaltsbreite nutzen und schrumpfen dafür.
  const inhaltsbreite = 1080 - 2 * METRIK.rand;
  const titel = passeEin(String(modell.titel || '').trim(), inhaltsbreite, S.titel, 30, messText, familie);
  const untertitel = passeEin(String(modell.untertitel || '').trim(), inhaltsbreite, S.untertitel, 20, messText, familie);
  if (titel.text) { y.titel = h + H.titel / 2; h += H.titel; }
  if (untertitel.text) { y.untertitel = h + H.untertitel / 2; h += H.untertitel; }

  let teams = [];
  let liste = [];
  let namenGroesse = S.name;      // gemeinsame Schriftgröße aller Spielernamen (Duell)
  let listeGroesse = S.listeName; // dasselbe für die Rangliste
  if (duell) {
    y.teamkopf = h + H.teamkopf / 2;
    y.akzent = h + H.teamkopf - 10;
    h += H.teamkopf;
    if (opts.spaltenkoepfe) { y.spaltenkopf = h + H.spaltenkopf / 2; h += H.spaltenkopf; }
    const n = Math.max(...modell.teams.map((t) => t.zeilen.length), 0);
    y.zeilen = [];
    for (let i = 0; i < n; i += 1) {
      y.zeilen.push({ mitte: h + H.zeile / 2, oben: h, hoehe: H.zeile });
      h += H.zeile + (i < n - 1 ? H.zeilenLuft : 0);
    }
    h += H.vorTrenn;
    y.trenn = h + H.trenn / 2;
    h += H.trenn;
    y.summe = h + H.summe / 2;
    y.summeOben = h;
    y.summeHoehe = H.summe;
    h += H.summe;
    if (opts.logos || opts.spielpunkte) {
      h += H.vorLogo;
      y.logo = h;
      h += H.logo;
    }
    const alleNamen = modell.teams.flatMap((t) => t.zeilen.map((z) => z.name));
    namenGroesse = namenSchrift(alleNamen, geo.breiten.name, S.name, 26, messText, familie);
    const messName = mess(...namenGroesse);
    teams = modell.teams.map((t) => ({
      ...t,
      // Mannschaftsnamen sind lang („KV Blau Weiß Sontra 1") — lieber kleiner als abgeschnitten.
      kopf: passeEin(t.name, geo.halb - 16, S.teamname, 26, messText, familie),
      zeilen: t.zeilen.map((z) => ({
        ...z,
        nameKurz: kuerzeName(z.name, geo.breiten.name, messName),
        holzText: z.gespielt ? String(z.gesamt) : '–',
        ewpText: z.gespielt ? String(z.ewp) : '–',
      })),
    }));
  } else {
    const L = METRIK.liste;
    const nameBreite = L.breite - L.rang - L.holz - 2 * METRIK.spaltenLuft;
    listeGroesse = namenSchrift(modell.zeilen.map((z) => z.name), nameBreite, S.listeName, 26, messText, familie);
    const messName = mess(...listeGroesse);
    y.zeilen = [];
    modell.zeilen.forEach((_, i) => {
      y.zeilen.push({ mitte: h + L.zeile / 2, oben: h, hoehe: L.zeile });
      h += L.zeile + (i < modell.zeilen.length - 1 ? H.zeilenLuft : 0);
    });
    liste = modell.zeilen.map((z) => ({
      ...z,
      nameKurz: kuerzeName(z.name, nameBreite, messName),
      holzText: z.gespielt ? String(z.gesamt) : '–',
    }));
  }

  const [oben, unten] = fmt.korridor;
  const verfuegbar = unten - oben;
  const skala = h > 0 ? Math.min(1, verfuegbar / h) : 1;
  const echt = h * skala;
  let yTop = oben;
  if (opts.position === 'mitte') yTop = oben + (verfuegbar - echt) / 2;
  else if (opts.position === 'unten') yTop = unten - echt;

  return {
    fmt, familie, mitEwp, duell, geo, y, hoehe: h, skala, yTop,
    titel, untertitel, teams, liste, namenGroesse, listeGroesse,
  };
}

// ── Zeichen-Helfer (Browser) ─────────────────────────────────────────────────

// Abgerundetes Rechteck ohne ctx.roundRect — das gibt es erst ab Safari 16.
function rundRect(ctx, x, y, w, h, r) {
  const rad = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rad, y);
  ctx.arcTo(x + w, y, x + w, y + h, rad);
  ctx.arcTo(x + w, y + h, x, y + h, rad);
  ctx.arcTo(x, y + h, x, y, rad);
  ctx.arcTo(x, y, x + w, y, rad);
  ctx.closePath();
}

// Eine Textzeile mit Halo: erst die Kontur (ohne Schatten, sonst doppelt), dann die Füllung
// mit einem dezenten Schatten, der die Kante ans Hintergrundbild bindet.
// Ohne `o.kontur` (Umrandung aus) bleibt die reine Füllung — sauberer über ruhigen Flächen,
// auf einem unruhigen Foto aber schlechter lesbar. Der Schatten hängt an derselben Farbe und
// fällt deshalb mit weg: sonst bliebe ein grauer Rand ohne die Kante, die ihn trägt.
function text(ctx, s, x, y, o) {
  if (s == null || s === '') return;
  const [groesse, gewicht] = o.schrift;
  ctx.font = fontStr(groesse, gewicht, o.familie);
  ctx.textAlign = o.align || 'left';
  ctx.textBaseline = 'middle';
  if (o.kontur) {
    ctx.save();
    ctx.shadowColor = 'transparent';
    ctx.lineJoin = 'round';
    ctx.miterLimit = 2;
    ctx.lineWidth = Math.max(3, groesse * 0.16);
    ctx.strokeStyle = o.kontur;
    ctx.strokeText(String(s), x, y);
    ctx.restore();
  }
  ctx.save();
  if (o.kontur) {
    ctx.shadowColor = o.kontur;
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = 3;
  }
  ctx.fillStyle = o.farbe;
  ctx.fillText(String(s), x, y);
  ctx.restore();
}

// Ein Logo in seine Box einpassen (contain), bei hellem Logo-Hintergrund mit weißer Platte.
function zeichneLogo(ctx, bild, cx, y, box, logoBg) {
  if (!bild || !bild.width || !bild.height) return;
  if (logoBg === 'light') {
    ctx.fillStyle = LOGO_PLATTE;
    rundRect(ctx, cx - box / 2, y, box, box, METRIK.radius + 4);
    ctx.fill();
  }
  const pad = logoBg === 'light' ? 14 : 0;
  const frei = box - 2 * pad;
  const s = Math.min(frei / bild.width, frei / bild.height);
  const w = bild.width * s;
  const h = bild.height * s;
  ctx.drawImage(bild, cx - w / 2, y + (box - h) / 2, w, h);
}

// Die Grafik auf die Canvas zeichnen. `bilder` ist eine Map mannschaftId -> geladenes
// Image (das Laden macht das Panel, damit dieses Modul ohne DOM auskommt).
// Die Canvas-Maße werden hier gesetzt — das setzt den Kontext ohnehin zurück.
export function zeichneGrafik(canvas, modell, opts, bilder = {}) {
  const ctx = canvas.getContext('2d');
  const messText = (s, font) => { ctx.font = font; return ctx.measureText(s).width; };
  const L = berechneLayout(modell, opts, messText);
  const P = PALETTE[opts.textfarbe] || PALETTE.hell;
  const platte = P.platte[opts.flaechen] || null;

  if (canvas.width !== L.fmt.w) canvas.width = L.fmt.w;
  if (canvas.height !== L.fmt.h) canvas.height = L.fmt.h;
  // Transparenz ist der Sinn der Sache: leeren, nicht füllen.
  ctx.clearRect(0, 0, L.fmt.w, L.fmt.h);

  // Eine Stil-Fabrik für alles: sie trägt Schriftfamilie und Kontur, die überall gleich sind.
  const kontur = opts.kontur === false ? null : P.kontur;
  const stil = (schrift, farbe = P.text, align = 'center') =>
    ({ schrift, farbe, align, kontur, familie: L.familie });

  ctx.save();
  // Block als Ganzes an seinen Platz und (bei sehr vielen Zeilen) verkleinern —
  // horizontal um die Bühnenmitte, damit die Spiegelung erhalten bleibt.
  ctx.translate(L.fmt.w / 2, L.yTop);
  ctx.scale(L.skala, L.skala);
  ctx.translate(-L.fmt.w / 2, 0);

  if (L.titel.text) text(ctx, L.titel.text, L.fmt.w / 2, L.y.titel, stil(L.titel.schrift));
  if (L.untertitel.text) text(ctx, L.untertitel.text, L.fmt.w / 2, L.y.untertitel, stil(L.untertitel.schrift, P.dim));

  if (L.duell) zeichneDuell(ctx, L, opts, P, platte, bilder, stil);
  else zeichneListe(ctx, L, P, platte, stil);

  ctx.restore();
  return L;
}

function zeichneDuell(ctx, L, opts, P, platte, bilder, stil) {
  const S = METRIK.schrift;
  const seiten = [L.geo.links, L.geo.rechts];

  // Mannschaftsnamen mittig über der jeweiligen Hälfte, darunter die Akzentlinie.
  L.teams.forEach((t, i) => {
    const s = seiten[i];
    const cx = (s.x0 + s.x1) / 2;
    text(ctx, t.kopf.text, cx, L.y.teamkopf, stil(t.kopf.schrift));
    ctx.fillStyle = t.accent;
    rundRect(ctx, cx - L.geo.halb * 0.34, L.y.akzent, L.geo.halb * 0.68, 5, 3);
    ctx.fill();
  });

  if (L.y.spaltenkopf != null) {
    seiten.forEach((s) => {
      text(ctx, 'SPIELER', s.name, L.y.spaltenkopf, stil(S.spaltenkopf, P.dim, s.nameAlign));
      text(ctx, 'HOLZ', s.holz, L.y.spaltenkopf, stil(S.spaltenkopf, P.dim));
      if (L.mitEwp) text(ctx, 'EWP', s.ewp, L.y.spaltenkopf, stil(S.spaltenkopf, P.dim));
    });
  }

  // Spielerzeilen: je Seite eine Platte (falls gewählt) und Name · Holz · EWP.
  L.y.zeilen.forEach((zy, i) => {
    L.teams.forEach((t, ti) => {
      const z = t.zeilen[i];
      if (!z) return;
      const s = seiten[ti];
      if (platte) {
        ctx.fillStyle = platte;
        rundRect(ctx, s.x0, zy.oben, L.geo.halb, zy.hoehe, METRIK.radius);
        ctx.fill();
      }
      const dim = z.gespielt ? P.text : P.dim;
      text(ctx, z.nameKurz, s.name, zy.mitte, stil(L.namenGroesse, dim, s.nameAlign));
      text(ctx, z.holzText, s.holz, zy.mitte, stil(S.holz, dim));
      if (L.mitEwp) text(ctx, z.ewpText, s.ewp, zy.mitte, stil(S.ewp, dim));
    });
  });

  // Trennlinie über der Summenzeile, je Hälfte.
  ctx.fillStyle = P.linie;
  seiten.forEach((s) => { ctx.fillRect(s.x0, L.y.trenn, L.geo.halb, 2); });

  // Summenzeile: Gesamtholz und (mit Wertung) die EWP-Summe.
  L.teams.forEach((t, ti) => {
    const s = seiten[ti];
    if (platte) {
      ctx.fillStyle = platte;
      rundRect(ctx, s.x0, L.y.summeOben, L.geo.halb, L.y.summeHoehe, METRIK.radius);
      ctx.fill();
    }
    text(ctx, 'Gesamt', s.name, L.y.summe, stil(S.summeLabel, P.dim, s.nameAlign));
    // Summen in der normalen Textfarbe: die Akzentfarbe eines Vereins kann auf einem
    // beliebigen Foto untergehen — sie traegt oben die Linie unter dem Mannschaftsnamen.
    text(ctx, String(t.summeHolz), s.holz, L.y.summe, stil(S.summe));
    if (L.mitEwp) text(ctx, String(t.summeEwp), s.ewp, L.y.summe, stil(S.summe));
  });

  if (L.y.logo == null) return;
  // Logos außen, Spielpunkte in der Mitte.
  const box = METRIK.logoBox;
  // Mittig über der jeweiligen Hälfte — aus der Geometrie gerechnet, nicht fest verdrahtet,
  // sonst wandern die Logos bei jeder Änderung an Rand oder Mittelspalte aus der Flucht.
  const mitten = seiten.map((s) => (s.x0 + s.x1) / 2);
  if (opts.logos) {
    L.teams.forEach((t, i) => zeichneLogo(ctx, bilder[t.id], mitten[i], L.y.logo, box, t.logoBg));
  }
  if (opts.spielpunkte && L.teams[0].spielpunkte != null) {
    const [pw, ph] = METRIK.punkteBox;
    const x = L.fmt.w / 2 - pw / 2;
    ctx.save();
    ctx.strokeStyle = P.linie;
    ctx.lineWidth = 3;
    rundRect(ctx, x, L.y.logo, pw, ph, 24);
    ctx.stroke();
    ctx.restore();
    const punkte = `${L.teams[0].spielpunkte} : ${L.teams[1].spielpunkte}`;
    text(ctx, punkte, L.fmt.w / 2, L.y.logo + ph / 2, stil(S.punkte));
  }
}

function zeichneListe(ctx, L, P, platte, stil) {
  const S = METRIK.schrift;
  const M = METRIK.liste;
  const x0 = (1080 - M.breite) / 2;
  const rangX = x0 + M.rang / 2;
  const nameX = x0 + M.rang + METRIK.spaltenLuft;
  const holzX = x0 + M.breite - M.holz / 2;

  L.y.zeilen.forEach((zy, i) => {
    const z = L.liste[i];
    if (!z) return;
    if (platte) {
      ctx.fillStyle = platte;
      rundRect(ctx, x0, zy.oben, M.breite, zy.hoehe, METRIK.radius);
      ctx.fill();
    }
    text(ctx, z.rang + '.', rangX, zy.mitte, stil(S.rang, P.dim));
    text(ctx, z.nameKurz, nameX, zy.mitte, stil(L.listeGroesse, P.text, 'left'));
    text(ctx, z.holzText, holzX, zy.mitte, stil(S.listeHolz));
  });
}
