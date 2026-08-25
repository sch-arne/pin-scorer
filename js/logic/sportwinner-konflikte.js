// Konflikt-Erkennung Sportwinner ⇄ App und Übernahme von Sportwinner-Werten in die App.
//
// Die Brücke liefert über GET /sportwinner den Live-Stand (Aufstellung + Wurfwerte je Slot/Bahn).
// Hier wird er gegen den App-Stand verglichen — Ergebnisse UND Aufstellung — und der Nutzer
// entscheidet je Abweichung in der App. Reine Logik (kein DOM/Netz), per Unit-Test abgesichert.
//
// „Konflikt" heisst bewusst: Sportwinner hat etwas, das der App WIDERSPRICHT. Ein leerer
// Sportwinner-Wert (0/0/0 bzw. kein Spieler) ist KEIN Konflikt — dort führt die App und die
// Brücke schreibt ohnehin nach Sportwinner. So bleibt das Panel im Normalbetrieb ruhig.

import {
  swSatzWerte, bahnplanOf, bahnSlot, swSeitenMap, ergKey, ABRAEUM_MODI, SW_BAHNEN,
} from './sportwinner-ergebnis.js';
import { teilsatzRanges } from './teilsaetze.js';

export { ergKey };

// Stabiler Schlüssel eines Aufstellungs-Konflikts (Seite/Slot).
export function aufKey(side, slot) {
  return `auf|${side}|${slot}`;
}

const leerErg = (v) => !v || (v.volle === 0 && v.abr === 0 && v.fehler === 0);
const gleichErg = (a, b) => a.volle === b.volle && a.abr === b.abr && a.fehler === b.fehler;

// Sportwinner-Live-Snapshot -> Lookup side -> slot -> { name, pass, extId, bahnen[{volle,abr,fehler}] }.
function swIndex(swLive) {
  const idx = { GG: {}, G: {} };
  if (!swLive || !swLive.seiten) return idx;
  ['GG', 'G'].forEach((side) => {
    const seite = swLive.seiten[side];
    if (!seite || !Array.isArray(seite.aufstellung)) return;
    seite.aufstellung.forEach((p, i) => {
      const slot = Number.isFinite(p.pos) ? p.pos : i;
      idx[side][slot] = {
        name: [p.vorname, p.nachname].filter(Boolean).join(' ').trim(),
        pass: String(p.pass || '').trim(),
        extId: p.id ?? null,
        bahnen: (Array.isArray(p.bahnen) ? p.bahnen : []).map((b) => ({
          volle: +b.volle || 0, abr: +b.abr || 0, fehler: +b.fehler || 0,
        })),
      };
    });
  });
  return idx;
}

// App-Stand (Wettkampf + Durchgang-Spiele) gegen den Sportwinner-Live-Stand vergleichen.
// Rückgabe: { ergebnis:[…], aufstellung:[…] } mit je einem stabilen `key`.
export function buildKonflikte(wettkampf, games, swLive) {
  const out = { ergebnis: [], aufstellung: [] };
  const sw = wettkampf && wettkampf.sportwinner;
  if (!sw || !sw.seiten || !swLive || !swLive.seiten) return out;

  const map = swSeitenMap(sw);
  const swIdx = swIndex(swLive);
  const passByKey = {};
  (sw.spieler || []).forEach((p) => {
    passByKey[`${p.mannschaftId}|${p.teamPos}`] = String(p.pass || '').trim();
  });

  (games || []).forEach((g) => {
    const c = g.config || {};
    if (!Array.isArray(c.teilsaetze) || !c.teilsaetze.length) return;
    const ranges = teilsatzRanges(c);
    const bloecke = (g.erfassung && g.erfassung.bloecke) || [];
    const bahnListe = Array.isArray(c.bahnListe) ? c.bahnListe : [];
    const bahnplan = bahnplanOf(c);
    (c.spielerListe || []).forEach((spCfg, idx) => {
      const m = map[`${spCfg.mannschaftId}|${spCfg.teamPos}`];
      if (!m || m.side == null || m.slot == null) return;
      const swSlot = swIdx[m.side] && swIdx[m.side][m.slot];

      // ── Aufstellung: erwartete Passnummer vs. der aktuell in Sportwinner gelegte Spieler.
      const erwPass = passByKey[`${spCfg.mannschaftId}|${spCfg.teamPos}`] || '';
      const swPass = swSlot ? swSlot.pass : '';
      if (swPass && swPass !== erwPass) {
        out.aufstellung.push({
          key: aufKey(m.side, m.slot), side: m.side, slot: m.slot,
          gameId: g.id, spielerIdx: idx, mannschaftId: spCfg.mannschaftId, teamPos: spCfg.teamPos,
          app: { name: spCfg.name || '', pass: erwPass },
          sw: { name: swSlot.name, pass: swPass, extId: swSlot.extId },
        });
      }

      // ── Ergebnis je Satz: App-Summen (Volle/Abräumen/Fehler) vs. Sportwinner-Bahn.
      const satzArr = Array.isArray(bloecke[idx]) ? bloecke[idx] : [];
      const plan = bahnplan && Array.isArray(bahnplan[idx]) ? bahnplan[idx] : null;
      const nSaetze = Math.min(c.saetze || satzArr.length, SW_BAHNEN);
      for (let s = 0; s < nSaetze; s += 1) {
        const bahn = bahnSlot(bahnListe, plan, s);
        if (bahn >= SW_BAHNEN) continue;
        const appErg = swSatzWerte(satzArr[s], ranges);
        const swErg = (swSlot && swSlot.bahnen[bahn]) || { volle: 0, abr: 0, fehler: 0 };
        if (!leerErg(swErg) && !gleichErg(appErg, swErg)) {
          out.ergebnis.push({
            key: ergKey(m.side, m.slot, bahn), side: m.side, slot: m.slot, bahn,
            gameId: g.id, spielerIdx: idx, satz: s,
            durchgangNr: g.durchgangNr ?? null,
            spielerName: spCfg.name || '',
            bahnNummer: bahnListe[bahn] != null ? bahnListe[bahn] : null,
            app: appErg, sw: swErg,
          });
        }
      }
    });
  });
  return out;
}

// Summe gleichmässig über Positionen verteilen (Nullen erlaubt; für Volle-Teilsätze).
function verteileSumme(wuerfe, positionen, summe) {
  const n = positionen.length;
  if (n === 0) return;
  const base = Math.floor(summe / n);
  const rest = summe % n;
  positionen.forEach((p, k) => { wuerfe[p] = base + (k < rest ? 1 : 0); });
}

// Abräum-Summe + GENAU `fehler` Nullwürfe rekonstruieren, sodass swSatzWerte beides exakt
// zurückgibt (Fehler = Nullwürfe im Abräumen). Für reale Werte (Summe ≫ Wurfzahl) exakt;
// nur bei pathologisch kleiner Summe weicht die Fehleranzahl ab (Summe hat Vorrang).
function verteileAbraeumen(wuerfe, positionen, summe, fehler) {
  const len = positionen.length;
  if (len === 0) return;
  let z = Math.max(0, Math.min(fehler | 0, len)); // Anzahl Nullen (= Fehler)
  let nz = len - z;                                // Nicht-Null-Würfe (jeder ≥ 1)
  if (nz === 0 && summe > 0) { nz = Math.min(summe, len); z = len - nz; }
  if (nz > 0 && summe < nz) { nz = summe; z = len - nz; } // zu wenig für lauter ≥1
  if (nz > 0) {
    const base = Math.floor(summe / nz);
    const rest = summe % nz;
    for (let k = 0; k < nz; k += 1) wuerfe[positionen[k]] = base + (k < rest ? 1 : 0);
    // positionen[nz..] bleiben 0 (die z Fehler).
  }
}

// Aus den Sportwinner-Summen eines Satzes (volle/abr/fehler) einen vollständigen App-Block bauen.
// Über synthetische Einzelwürfe (keine Overrides), damit swSatzWerte volle/abr UND fehler exakt
// reproduziert und der Konflikt nach der Übernahme wirklich verschwindet. Einzelwurf-Details sind
// synthetisch (die echten liefert Sportwinner nicht) — die Summen/Wertung stimmen.
export function adoptErgebnisBlock(config, swErg) {
  const ranges = teilsatzRanges(config);
  const total = ranges.reduce((n, r) => n + r.soll, 0);
  const wuerfe = new Array(total).fill(0);
  const vollePos = [];
  const abrPos = [];
  ranges.forEach((r) => {
    for (let p = r.start; p < r.end; p += 1) (ABRAEUM_MODI.has(r.modus) ? abrPos : vollePos).push(p);
  });
  verteileSumme(wuerfe, vollePos, +swErg.volle || 0);
  verteileAbraeumen(wuerfe, abrPos, +swErg.abr || 0, +swErg.fehler || 0);
  return {
    wuerfe,
    kegel: wuerfe.map(() => null),   // Einzel-Kegel unbekannt (synthetisch) -> „unbestimmt"
    koenig: wuerfe.map(() => false),
    overrides: ranges.map(() => null),
    done: true,
  };
}

// Aufstellungs-Konflikt übernehmen: Namen im Spiel und Pass/Id in der Sportwinner-Zuordnung des
// Wettkampfs auf den Sportwinner-Stand setzen. Gibt gepatchte KOPIEN { wettkampf, game } zurück;
// der Aufrufer persistiert (saveWettkampf/saveGame). Ohne Treffer werden die Eingaben durchgereicht.
export function adoptAufstellung(wettkampf, game, konflikt) {
  const w = JSON.parse(JSON.stringify(wettkampf));
  const g = JSON.parse(JSON.stringify(game));
  const sl = g.config && g.config.spielerListe && g.config.spielerListe[konflikt.spielerIdx];
  if (sl) sl.name = konflikt.sw.name || sl.name;
  const eintrag = (w.sportwinner && w.sportwinner.spieler || []).find(
    (p) => p.mannschaftId === konflikt.mannschaftId && p.teamPos === konflikt.teamPos,
  );
  if (eintrag) { eintrag.pass = konflikt.sw.pass; eintrag.extId = konflikt.sw.extId; }
  return { wettkampf: w, game: g };
}
