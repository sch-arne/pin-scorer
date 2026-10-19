// Wurfdaten aus einer CSV EINLESEN — das Gegenstück zum Export (logic/wurf-csv.js).
//
// Eingelesen wird das Format, das die Bahnanlage je Spieler ausgibt: EINE Datei pro Spieler,
// und darin je bespielter Bahn ein Spalten-TRIPEL (Holz, Wurfbild, Zeit) nebeneinander:
//
//   Wurf;Warmwerfen;Wurfbild Warmwerfen;Zeit Warmwerfen;Bahn 4;Wurfbild Bahn 4;Zeit Bahn 4;…
//   1;9;1 2 3 4 5 6 7 8 9;01:11:58;7;1 2 3 4 6 7 9;01:20:19;…
//   …
//   Summe;141;;;201;;;…
//
// Das ist bewusst NICHT das Format des eigenen Exports (eine Zeile je Wurf, Spalten
// Spieler/Satz/Bahn/Teilsatz/Modus/Wurf/Holz/Kegel). Die Anlage schreibt, was sie weiß —
// Bahn und Wurfnummer — und kennt weder Satz noch Teilsatz noch das Programm. Genau das
// ist hier die Arbeit: die Bahn-Spalten über den BAHNPLAN des Spiels den Sätzen zuordnen
// und die Würfe gegen die Teilsätze dieses Spiels prüfen.
//
// Das WARMWERFEN (Einspielen) gehört nicht zum Spiel und wird nie importiert — es steht in
// derselben Datei, zählt aber in keiner Wertung. Es wird nur gezählt und gemeldet, damit
// sichtbar ist, dass es erkannt und weggelassen wurde.
//
// Reine Logik: kein DOM, kein Store, kein Netz (Browser + Node ladbar, per Unit-Test geprüft).

import { teilsatzRanges } from './teilsaetze.js';
import { isAbraeumMode, abraeumScan } from './abraeumen.js';
import { normalisiere } from './profil-match.js';

// ── CSV zerlegen ─────────────────────────────────────────────────────────────

// Eine CSV-Zeile in Zellen. Semikolon wie im Export; "…"-Quoting wird geduldet (die Anlage
// nutzt es nicht, Excel setzt es aber, sobald jemand die Datei dort einmal gespeichert hat).
function zellen(zeile) {
  const out = [];
  let cur = '';
  let quoted = false;
  for (let i = 0; i < zeile.length; i += 1) {
    const ch = zeile[i];
    if (quoted) {
      if (ch === '"') {
        if (zeile[i + 1] === '"') { cur += '"'; i += 1; } else quoted = false;
      } else cur += ch;
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ';') {
      out.push(cur); cur = '';
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

// Zeilen einer CSV: BOM weg, CRLF wie LF, Leerzeilen raus.
function zeilen(text) {
  return String(text || '')
    .replace(/^﻿/, '')
    .split(/\r?\n/)
    .map((z) => zellen(z))
    .filter((z) => z.some((c) => c.trim() !== ''));
}

// Spaltengruppen aus der Kopfzeile. Eine Gruppe beginnt bei jeder Spalte, die NICHT
// „Wurf", „Wurfbild …" oder „Zeit …" heißt; die folgenden Wurfbild-/Zeit-Spalten gehören
// zu ihr. So bleibt die Datei lesbar, auch wenn Wurfbild oder Zeit gar nicht mitkommen.
function gruppen(kopf) {
  const out = [];
  kopf.forEach((raw, i) => {
    const h = String(raw || '').trim();
    if (/^wurf$/i.test(h)) return;                       // die Wurfnummer-Spalte selbst
    if (/^(wurfbild|kegel|zeit|uhrzeit)\b/i.test(h)) {   // Beigabe zur laufenden Gruppe
      const g = out[out.length - 1];
      if (!g) return;
      if (/^zeit|^uhrzeit/i.test(h)) g.iZeit = i; else g.iBild = i;
      return;
    }
    if (!h) return;
    const m = /^bahn\s*(\d+)$/i.exec(h);
    out.push({
      label: h,
      bahn: m ? parseInt(m[1], 10) : null,
      warm: /warm|einspiel/i.test(h),
      iHolz: i,
      iBild: -1,
      iZeit: -1,
    });
  });
  return out;
}

const ZAHL = /^-?\d+$/;

// Kegelbild „1 3 5" -> [1,3,5]. Auch Komma/Semikolon-getrennt, falls jemand nachbessert.
function pinListe(s) {
  const t = String(s || '').trim();
  if (!t) return [];
  return t.split(/[\s,]+/).filter(Boolean).map((x) => parseInt(x, 10));
}

// „01:20:19" -> Sekunden. Ohne/mit kaputter Angabe: null (Zeiten sind Beigabe, kein Muss).
export function zeitSekunden(s) {
  const m = /^(\d{1,3}):([0-5]\d):([0-5]\d)$/.exec(String(s || '').trim());
  if (!m) return null;
  return parseInt(m[1], 10) * 3600 + parseInt(m[2], 10) * 60 + parseInt(m[3], 10);
}

// Eine Spieler-Datei zerlegen. Rückgabe:
//   { spalten: [{ label, bahn, warm, wuerfe:[{nr,holz,pins,zeit}], summe }], fehler: [text] }
// `summe` ist die Zahl aus der Summenzeile der Datei (oder null) — sie ist die Gegenprobe
// zur Summe der Einzelwürfe und deckt ein abgeschnittenes Kopieren auf.
export function parseWurfdatei(text) {
  const rows = zeilen(text);
  if (!rows.length) return { spalten: [], fehler: ['Die Datei ist leer.'] };

  const kopf = rows[0];
  const fehler = [];
  if (!kopf.some((h) => /^wurf$/i.test(String(h || '').trim()))) {
    fehler.push('Keine Spalte „Wurf" in der Kopfzeile — ist das eine Wurfdaten-Datei der Anlage?');
  }
  const gs = gruppen(kopf);
  if (!gs.length) return { spalten: [], fehler: fehler.concat(['Keine Bahn-Spalten gefunden.']) };

  const spalten = gs.map((g) => ({
    label: g.label, bahn: g.bahn, warm: g.warm, wuerfe: [], summe: null,
  }));

  rows.slice(1).forEach((r) => {
    const erste = String(r[0] || '').trim();
    const istSumme = /^summe$/i.test(erste);
    gs.forEach((g, gi) => {
      const holzRaw = String(r[g.iHolz] == null ? '' : r[g.iHolz]).trim();
      if (holzRaw === '') return;
      if (!ZAHL.test(holzRaw)) {
        fehler.push(`${g.label}, Zeile „${erste || '?'}": „${holzRaw}" ist keine Holzzahl.`);
        return;
      }
      if (istSumme) { spalten[gi].summe = parseInt(holzRaw, 10); return; }
      spalten[gi].wuerfe.push({
        nr: ZAHL.test(erste) ? parseInt(erste, 10) : spalten[gi].wuerfe.length + 1,
        holz: parseInt(holzRaw, 10),
        pins: g.iBild >= 0 ? pinListe(r[g.iBild]) : [],
        zeit: g.iZeit >= 0 ? String(r[g.iZeit] || '').trim() : '',
      });
    });
  });

  return { spalten, fehler };
}

// ── Spielername aus dem Dateinamen ───────────────────────────────────────────

// Die Anlage legt je Spieler eine Datei „Vorname_Nachname.csv" an; der Name steht NICHT
// in der Datei. Unterstriche sind also Leerzeichen, eine Zählendung („ (1)") Beiwerk des
// Browsers beim zweiten Download.
export function spielerAusDateiname(dateiname) {
  return String(dateiname || '')
    .replace(/^.*[\\/]/, '')
    .replace(/\.csv$/i, '')
    .replace(/\s*\(\d+\)$/, '')
    .replace(/[_]+/g, ' ')
    .trim();
}

// ── Zuordnung zur Aufstellung ────────────────────────────────────────────────

// Vergleichsform eines Namens für die DATEI-Zuordnung: wie normalisiere(), zusätzlich aber
// mit aufgelöster Umlaut-Umschrift. Die Anlage schreibt Dateinamen ohne Umlaute („Rene_Puetz",
// „Christoph_Hoesel"), die Aufstellung trägt sie („Pütz", „Hösel") — normalisiere() faltet nur
// „ü" zu „u" und ließe beide Schreibweisen auseinanderlaufen. Weil der Vergleich danach immer
// noch BEIDE Namensteile verlangt und ein mehrdeutiger Treffer zur Hand-Zuordnung führt, ist
// die zusätzliche Toleranz hier gefahrlos. Bewusst NICHT in profil-match.js: dort entscheidet
// derselbe Vergleich darüber, wessen Ergebnisse in ein Konto wandern.
export function vergleichsname(s) {
  return normalisiere(s)
    .replace(/ae/g, 'a')
    .replace(/oe/g, 'o')
    .replace(/ue/g, 'u')
    .replace(/ss/g, 's');
}

const teile = (s) => vergleichsname(s).split(' ').filter(Boolean);

// Welcher Slot der Aufstellung ist das? Erst die exakte Vergleichsform, dann der
// Bestandteil-Vergleich — „Schierbaum, Arne" und „Arne Schierbaum" sind dieselbe Person,
// die Reihenfolge sagt nichts. Verlangt wird der VOLLE Bestand (jeder Namensteil des einen
// kommt im anderen vor), damit in einer Mannschaft mit Brüdern nicht der Falsche getroffen
// wird. Mehrdeutig (mehr als ein Treffer) -> -1, dann entscheidet der Mensch in der View.
export function findeSpieler(name, spielerListe, belegt = []) {
  const liste = spielerListe || [];
  const frei = (i) => !belegt.includes(i);
  const ziel = vergleichsname(name);
  if (!ziel) return -1;

  const exakt = liste.map((p, i) => i).filter((i) => frei(i) && vergleichsname(liste[i].name) === ziel);
  if (exakt.length === 1) return exakt[0];
  if (exakt.length > 1) return -1;

  const a = teile(name);
  const treffer = liste.map((p, i) => i).filter((i) => {
    if (!frei(i)) return false;
    const b = teile(liste[i].name);
    if (!a.length || !b.length) return false;
    return a.every((t) => b.includes(t)) || b.every((t) => a.includes(t));
  });
  return treffer.length === 1 ? treffer[0] : -1;
}

// Bahn eines Spielers im Satz — wie in logic/statistik.js und logic/wurf-csv.js.
export const bahnOf = (c, sp, st) => (c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st));

// Bahn-Spalten der Datei den SÄTZEN des Spielers zuordnen.
//
// Der Bahnplan sagt, auf welcher Bahn dieser Spieler welchen Satz spielt. Die Spalten der
// Datei stehen in Spielreihenfolge, also in Satzreihenfolge. Eine Bahn kann im Plan MEHRFACH
// vorkommen (Classic-/Bohle-Duo pendelt zwischen zwei Bahnen) — dann wird die jeweils
// früheste noch freie Satz-Nummer mit dieser Bahn genommen, weshalb die Spaltenreihenfolge
// zählt und nicht die Bahnnummer allein.
// Rückgabe: Liste parallel zu `spalten` mit dem Satz-Index (oder null = keine Bahn im Plan).
export function ordneSaetze(spalten, config, sp) {
  const saetze = config.saetze || 0;
  const vergeben = new Set();
  return spalten.map((s) => {
    if (s.warm || s.bahn == null) return null;
    for (let st = 0; st < saetze; st += 1) {
      if (!vergeben.has(st) && bahnOf(config, sp, st) === s.bahn) { vergeben.add(st); return st; }
    }
    return null;
  });
}

// ── Prüfung ──────────────────────────────────────────────────────────────────

// Ein Satz-Block aus den Würfen einer Bahn-Spalte. Das Kegelbild wird IMMER mitgeschrieben
// (auch die leere Liste beim Fehlwurf) — die Anlage kennt es, und ohne Bild fehlten später
// Räumer-Auswertung, Wurfprotokoll und Wurfbild-Grafik. `koenig` bleibt durchweg false:
// das Flag ist nur die Abkürzung für den Kranz-Langdruck in der Erfassung; hier stehen die
// gefallenen Kegel ohnehin konkret da.
export function baueBlock(wuerfe, config) {
  const anzahl = (config.teilsaetze || []).length;
  return {
    wuerfe: wuerfe.map((w) => w.holz),
    kegel: wuerfe.map((w) => w.pins.slice().sort((a, b) => a - b)),
    koenig: wuerfe.map(() => false),
    overrides: Array.from({ length: anzahl }, () => null),
    done: wuerfe.length >= (config.wuerfeProSatz || 0),
  };
}

const befund = (art, text) => ({ art, text });

// Eine Bahn-Spalte prüfen. `art`:
//   'fehler'  — so nicht importierbar (Zahlen unbrauchbar)
//   'warnung' — importierbar, aber jemand sollte hinsehen (Holz stimmt, das Bild nicht)
//   'hinweis' — nur zur Kenntnis (unfertiger Satz, Überschreiben)
export function pruefeSpalte(spalte, config, satzIndex) {
  const out = [];
  const w = spalte.wuerfe;
  const soll = config.wuerfeProSatz || 0;

  // 1) Holzzahlen und Kegelbilder in sich stimmig.
  w.forEach((x) => {
    if (x.holz < 0 || x.holz > 9) {
      out.push(befund('fehler', `Wurf ${x.nr}: Holz ${x.holz} liegt nicht zwischen 0 und 9.`));
    }
    if (!x.pins.length) {
      if (x.holz !== 0) out.push(befund('warnung', `Wurf ${x.nr}: ${x.holz} Holz, aber kein Kegelbild.`));
      return;
    }
    if (x.pins.some((p) => !(p >= 1 && p <= 9))) {
      out.push(befund('fehler', `Wurf ${x.nr}: Kegelnummer außerhalb 1–9 (${x.pins.join(' ')}).`));
      return;
    }
    if (new Set(x.pins).size !== x.pins.length) {
      out.push(befund('fehler', `Wurf ${x.nr}: derselbe Kegel mehrfach im Bild (${x.pins.join(' ')}).`));
      return;
    }
    if (x.pins.length !== x.holz) {
      out.push(befund('fehler', `Wurf ${x.nr}: Holz ${x.holz}, aber ${x.pins.length} Kegel im Bild (${x.pins.join(' ')}).`));
    }
  });

  // 2) Gegenprobe gegen die Summenzeile der Datei.
  const summe = w.reduce((s, x) => s + x.holz, 0);
  if (spalte.summe != null && spalte.summe !== summe) {
    out.push(befund('warnung', `Summenzeile sagt ${spalte.summe}, die Einzelwürfe ergeben ${summe}.`));
  }

  // 3) Zeiten aufsteigend — eine Rückwärts-Zeit heißt vertauschte oder doppelte Zeilen.
  for (let i = 1; i < w.length; i += 1) {
    const a = zeitSekunden(w[i - 1].zeit);
    const b = zeitSekunden(w[i].zeit);
    if (a != null && b != null && b < a) {
      out.push(befund('warnung', `Wurf ${w[i].nr} (${w[i].zeit}) liegt zeitlich vor Wurf ${w[i - 1].nr} (${w[i - 1].zeit}).`));
    }
  }

  // 4) Wurfzahl gegen das Programm des Spiels.
  if (soll && w.length > soll) {
    out.push(befund('fehler', `${w.length} Würfe, das Spiel sieht je Satz ${soll} vor.`));
  } else if (soll && w.length < soll) {
    out.push(befund('hinweis', `Nur ${w.length} von ${soll} Würfen — der Satz bleibt offen und kann in der App weitergeführt werden.`));
  }

  // 5) Abräumen/Kranz mit der Logik der App durchrechnen (logic/abraeumen.js). So meldet der
  //    Import genau das, was die Erfassung später am Wurf anzeigen würde — keine zweite,
  //    womöglich abweichende Regelauslegung.
  if (satzIndex != null) {
    const blk = baueBlock(w, config);
    teilsatzRanges(config).forEach((r, ti) => {
      if (!isAbraeumMode(r.modus)) return;
      if (blk.wuerfe.length <= r.start) return;
      const scan = abraeumScan(blk, r);
      const end = Math.min(r.end, blk.wuerfe.length);
      for (let j = r.start; j < end; j += 1) {
        if (scan.error[j]) {
          out.push(befund('warnung',
            `Wurf ${j + 1} (Teilsatz ${ti + 1}, ${r.modus === 'kranz-abraeumen' ? 'Kranz-Abräumen' : 'Abräumen'}): ${scan.error[j]}.`));
        }
      }
    });
  }

  return out;
}

// ── Gesamtplan ───────────────────────────────────────────────────────────────

// Eine Datei gegen ein Spiel auswerten. `dateien` sind { dateiname, text }.
// `zuordnung` erlaubt der View, die Spieler-Zuordnung zu überschreiben:
// { [dateiname]: spielerIndex | -1 }.
//
// Rückgabe je Datei:
//   { dateiname, spielerName, spielerIndex, mehrdeutig, fehler[], warm, saetze[], befunde[] }
// und je Satz:
//   { satz, bahn, label, wuerfe, holz, block, befunde[], ueberschreibt }
export function baueImportPlan(dateien, game, zuordnung = {}) {
  const config = (game && game.config) || {};
  const bloecke = (game && game.erfassung && game.erfassung.bloecke) || [];
  const liste = config.spielerListe || [];

  // Erst alle Dateien lesen und die eindeutig erkannten Spieler belegen, danach die
  // offenen — sonst könnte eine unsichere Zuordnung einen Slot wegnehmen, den eine
  // eindeutige noch braucht.
  const gelesen = dateien.map((d) => {
    const { spalten, fehler } = parseWurfdatei(d.text);
    return { dateiname: d.dateiname, spielerName: spielerAusDateiname(d.dateiname), spalten, fehler };
  });

  const belegt = [];
  Object.keys(zuordnung).forEach((k) => { if (zuordnung[k] >= 0) belegt.push(zuordnung[k]); });
  gelesen.forEach((g) => {
    if (Object.prototype.hasOwnProperty.call(zuordnung, g.dateiname)) {
      g.spielerIndex = zuordnung[g.dateiname];
      return;
    }
    const i = findeSpieler(g.spielerName, liste, belegt);
    g.spielerIndex = i;
    if (i >= 0) belegt.push(i);
  });

  return gelesen.map((g) => {
    const sp = g.spielerIndex;
    const warm = g.spalten
      .filter((s) => s.warm)
      .reduce((n, s) => n + s.wuerfe.length, 0);
    const spielBahnen = g.spalten.filter((s) => !s.warm);

    if (sp == null || sp < 0) {
      return {
        dateiname: g.dateiname,
        spielerName: g.spielerName,
        spielerIndex: -1,
        fehler: g.fehler,
        warm,
        saetze: [],
        befunde: [befund('fehler', liste.length
          ? 'Kein Spieler der Aufstellung passt eindeutig zu diesem Namen — bitte unten zuordnen.'
          : 'Das Spiel hat keine Aufstellung.')],
      };
    }

    const zuSatz = ordneSaetze(g.spalten, config, sp);
    const saetze = [];
    const befunde = [];
    g.spalten.forEach((s, i) => {
      if (s.warm) return;
      const satz = zuSatz[i];
      if (satz == null) {
        befunde.push(befund('fehler',
          `Spalte „${s.label}": ${s.bahn == null ? 'keine Bahn erkennbar' : `Bahn ${s.bahn} kommt im Bahnplan von ${liste[sp].name} nicht (mehr) vor`}.`));
        return;
      }
      const vorhanden = bloecke[sp] && bloecke[sp][satz];
      const hatWuerfe = !!(vorhanden && Array.isArray(vorhanden.wuerfe) && vorhanden.wuerfe.length);
      const eigene = pruefeSpalte(s, config, satz);
      if (hatWuerfe) {
        eigene.push(befund('hinweis',
          `Satz ${satz + 1} enthält bereits ${vorhanden.wuerfe.length} Würfe — die werden ersetzt.`));
      }
      saetze.push({
        satz,
        bahn: s.bahn,
        label: s.label,
        wuerfe: s.wuerfe.length,
        holz: s.wuerfe.reduce((a, x) => a + x.holz, 0),
        block: baueBlock(s.wuerfe, config),
        befunde: eigene,
        ueberschreibt: hatWuerfe,
      });
    });

    if (!spielBahnen.length) befunde.push(befund('fehler', 'Die Datei enthält nur Warmwerfen — nichts zu importieren.'));

    return {
      dateiname: g.dateiname,
      spielerName: g.spielerName,
      spielerIndex: sp,
      fehler: g.fehler,
      warm,
      saetze: saetze.sort((a, b) => a.satz - b.satz),
      befunde,
    };
  });
}

// Höchste Schwere einer Befundliste (für Ampel/Sortierung in der View).
export function schwere(befunde) {
  const list = befunde || [];
  if (list.some((b) => b.art === 'fehler')) return 'fehler';
  if (list.some((b) => b.art === 'warnung')) return 'warnung';
  return list.length ? 'hinweis' : 'ok';
}

// Ist diese Datei importierbar? Fehler am Spieler/an der Datei blockieren alles, ein Fehler
// an EINEM Satz nur diesen Satz — die übrigen Sätze derselben Datei gehen trotzdem rein.
export function istImportierbar(eintrag) {
  if (!eintrag || eintrag.spielerIndex < 0) return false;
  if (schwere(eintrag.befunde) === 'fehler') return false;
  return eintrag.saetze.some((s) => schwere(s.befunde) !== 'fehler');
}

// Die Sätze einer Datei, die tatsächlich geschrieben werden.
export function importierbareSaetze(eintrag) {
  if (!istImportierbar(eintrag)) return [];
  return eintrag.saetze.filter((s) => schwere(s.befunde) !== 'fehler');
}
