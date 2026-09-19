import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  assignEwp, computeWertung, fmtPunkte, bahnartOf,
  defaultWertung, defaultEwpSchwelle, teamEwpBereich,
} from '../js/logic/wettkampf-wertung.js';

// Hilfs-Spieler: p(team, gesamt, abraeum).
function p(team, gesamt, abraeum = 0, name = team + gesamt) {
  return { mannschaftId: team, gesamt, abraeum, name };
}

const wkSchere = { mannschaften: [{ id: 'A', name: 'Heim' }, { id: 'B', name: 'Gast' }], programm: { preset: 'schere' } };

test('assignEwp: bester bekommt N, schlechtester 1, lückenlos', () => {
  const einzel = [p('A', 550), p('B', 500), p('A', 600), p('B', 480)];
  assignEwp(einzel, 'A');
  const byName = Object.fromEntries(einzel.map((x) => [x.name, x.ewp]));
  assert.equal(byName.A600, 4); // bester
  assert.equal(byName.A550, 3);
  assert.equal(byName.B500, 2);
  assert.equal(byName.B480, 1); // schlechtester
});

test('assignEwp: Gleichstand → Gast (Nicht-Heim) bekommt die höhere EWP', () => {
  const einzel = [p('A', 500, 100, 'Heim1'), p('B', 500, 90, 'Gast1')];
  assignEwp(einzel, 'A'); // A = Heim
  const g = einzel.find((x) => x.name === 'Gast1');
  const h = einzel.find((x) => x.name === 'Heim1');
  assert.ok(g.ewp > h.ewp, 'Gast höher trotz niedrigerem Abräumen');
  assert.equal(g.ewp, 2);
  assert.equal(h.ewp, 1);
});

test('assignEwp: Gleichstand innerhalb einer Mannschaft → höheres Abräumen zuerst', () => {
  const einzel = [p('A', 500, 80, 'Heim_lo'), p('A', 500, 120, 'Heim_hi')];
  assignEwp(einzel, 'A');
  const hi = einzel.find((x) => x.name === 'Heim_hi');
  const lo = einzel.find((x) => x.name === 'Heim_lo');
  assert.ok(hi.ewp > lo.ewp);
});

test('computeWertung Schere: 2 Punkte fürs mehr Holz, 3. Punkt über EWP, Summe 3', () => {
  // Heim hat mehr Holz UND mehr EWP → 3:0.
  const einzel = [p('A', 600), p('A', 590), p('B', 500), p('B', 490)];
  const w = computeWertung(wkSchere, { einzel }, []);
  assert.equal(w.home.mannschaftspunkte, 2);
  assert.equal(w.home.ewpPunkt, 1);
  assert.equal(w.home.spielpunkte, 3);
  assert.equal(w.away.spielpunkte, 0);
  assert.equal(w.home.spielpunkte + w.away.spielpunkte, 3);
});

test('computeWertung Schere: Holz-Gleichstand 1:1, EWP-Schwelle (neutral) → Gast bei Gleichheit', () => {
  // Gleiche Team-Summe (1090:1090) → Mannschaftspunkte 1:1.
  // EWP: A600(4)+A490(1)=5 ; B550(3)+B540(2)=5. Topf 10, Schwelle neutral = 5.
  // Gast (B) erreicht die Schwelle (5 ≥ 5) → EWP-Punkt an den Gast.
  const einzel = [p('A', 600), p('A', 490), p('B', 550), p('B', 540)];
  const w = computeWertung(wkSchere, { einzel }, []);
  assert.equal(w.home.gesamtholz, 1090);
  assert.equal(w.away.gesamtholz, 1090);
  assert.equal(w.home.mannschaftspunkte, 1);
  assert.equal(w.away.mannschaftspunkte, 1);
  assert.equal(w.home.ewpPunkt, 0);
  assert.equal(w.away.ewpPunkt, 1);
  assert.equal(w.away.spielpunkte, 2);
});

test('computeWertung: Config-Schwelle entscheidet den EWP-Punkt', () => {
  const einzel = [p('A', 600), p('A', 590), p('B', 500), p('B', 490)]; // EWP: A=4+3=7, B=2+1=3
  const wk = { mannschaften: [{ id: 'A', name: 'Heim' }, { id: 'B', name: 'Gast' }],
    wertung: { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 1, ewp: { minHolz: 1 }, ewpSchwelle: 3 } };
  // Gast-EWP 3 ≥ Schwelle 3 → EWP-Punkt an den Gast (obwohl Heim mehr EWP hat).
  const w = computeWertung(wk, { einzel }, []);
  assert.equal(w.away.ewpPunkt, 1);
  assert.equal(w.home.ewpPunkt, 0);
  // Schwelle 4 → Gast (3) verfehlt sie → Punkt ans Heim.
  const einzel2 = [p('A', 600), p('A', 590), p('B', 500), p('B', 490)];
  const w2 = computeWertung({ ...wk, wertung: { ...wk.wertung, ewpSchwelle: 4 } }, { einzel: einzel2 }, []);
  assert.equal(w2.home.ewpPunkt, 1);
  assert.equal(w2.away.ewpPunkt, 0);
});

test('computeWertung: konfigurierte EWP-Wertung rechnet, Satzpunkte-Config → null', () => {
  const teams = [{ id: 'A', name: 'H' }, { id: 'B', name: 'G' }];
  const wkEwp = { mannschaften: teams, wertung: { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 1, ewp: { minHolz: 1 }, ewpSchwelle: 2 } };
  const wB = computeWertung(wkEwp, { einzel: [p('A', 500), p('B', 400)] }, []);
  assert.ok(wB && wB.home.spielpunkte + wB.away.spielpunkte > 0);
  // Kriterium 2 = Satzpunkte → noch nicht umgesetzt → null.
  const wkSatz = { mannschaften: teams, wertung: { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'satzpunkte', kriterium2Punkte: 1 } };
  assert.equal(computeWertung(wkSatz, { einzel: [p('A', 500), p('B', 400)] }, []), null);
});

test('computeWertung: ohne Konfiguration greift der Bahnart-Standard (Classic → null)', () => {
  const teams = [{ id: 'A' }, { id: 'B' }];
  const wk = (preset) => ({ mannschaften: teams, spielerJeMannschaft: 6, programm: { preset } });
  const neu = () => [p('A', 500), p('B', 400)];
  // Schere UND Bohle werten über EWP — Bohle blieb früher ungewertet (Rückgabe null).
  assert.ok(computeWertung(wk('schere'), { einzel: neu() }, []));
  assert.ok(computeWertung(wk('bohle'), { einzel: neu() }, []));
  // Classic nutzt Satzpunkte — die folgen noch, deshalb weiterhin null.
  assert.equal(computeWertung(wk('classic'), { einzel: neu() }, []), null);
  // Bahnart nicht erkennbar → nichts ableitbar, es bleibt beim Kegel-Zwischenstand.
  assert.equal(computeWertung({ mannschaften: teams, spielerJeMannschaft: 6 }, { einzel: neu() }, []), null);
});

test('defaultEwpSchwelle: Vereinsvorgaben, sonst neutrale Mitte, ohne Größe null', () => {
  assert.equal(defaultEwpSchwelle('schere', 6), 31);
  assert.equal(defaultEwpSchwelle('schere', 4), 15);
  assert.equal(defaultEwpSchwelle('bohle', 6), 32);
  // Unbekannte Mannschaftsgröße → neutrale Mitte des möglichen Team-EWP-Bereichs (5er: 15–40).
  const { min, max } = teamEwpBereich(5);
  assert.equal(defaultEwpSchwelle('schere', 5), Math.round((min + max) / 2));
  // Ohne brauchbare Größe kein Ratewert — computeWertung nimmt dann den halben Topf.
  assert.equal(defaultEwpSchwelle('schere', 0), null);
  assert.equal(defaultEwpSchwelle('schere', undefined), null);
});

test('computeWertung: importierter Schere-Wettkampf ohne Wertung nutzt die Schwelle 31', () => {
  // Echter Fall aus der Produktion (VOK Osnabrück 1 – SK Mülheim 1, per Sportwinner-Brücke
  // importiert, deshalb OHNE wettkampf.wertung): Heim 5081 Holz / 41 EWP, Gast 5028 / 37.
  // Der alte Standard ohne Schwelle nahm den halben Topf (39) und schob den EWP-Punkt dem
  // Heim-Team zu → 3:0. Mit der Vereinsvorgabe 31 erreicht der Gast die Schwelle → 2:1.
  const teams = [{ id: 'A', name: 'VOK Osnabrück 1' }, { id: 'B', name: 'SK Mülheim 1' }];
  const wk = { mannschaften: teams, spielerJeMannschaft: 6, programm: { preset: 'schere' } };
  const holz = { A: [915, 864, 852, 832, 824, 794], B: [897, 867, 859, 815, 800, 790] };
  const einzel = [...holz.A.map((h) => p('A', h)), ...holz.B.map((h) => p('B', h))];
  const w = computeWertung(wk, { einzel }, []);
  assert.equal(w.ewpSchwelle, 31);
  assert.equal(w.home.gesamtholz, 5081);
  assert.equal(w.away.gesamtholz, 5028);
  assert.equal(w.home.ewpSumme, 41);
  assert.equal(w.away.ewpSumme, 37);
  assert.equal(w.home.mannschaftspunkte, 2); // mehr Holz
  assert.equal(w.away.ewpPunkt, 1);          // 37 >= 31
  assert.equal(w.home.spielpunkte, 2);
  assert.equal(w.away.spielpunkte, 1);
});

test('defaultWertung: Bahnart bestimmt Kriterium 2, Mannschaftszahl den Modus', () => {
  assert.equal(defaultWertung('schere', 6).kriterium2, 'ewp');
  assert.equal(defaultWertung('bohle', 6).kriterium2, 'ewp');
  assert.equal(defaultWertung('classic', 6).kriterium2, 'satzpunkte');
  assert.equal(defaultWertung('schere', 6).ewpSchwelle, 31);
  assert.equal(defaultWertung('schere', 6, 2).modus, 'duell');
  assert.equal(defaultWertung('schere', 6, 4).modus, 'rangliste');
});

test('assignEwp: Spieler ohne Holz (0) bekommen 0 EWP, Rest lückenlos', () => {
  const einzel = [p('A', 500), p('B', 0, 0, 'B_leer'), p('A', 400), p('B', 450)];
  assignEwp(einzel, 'A');
  const byName = Object.fromEntries(einzel.map((x) => [x.name, x.ewp]));
  assert.equal(byName.B_leer, 0);           // nicht gewertet
  assert.equal(einzel.find((x) => x.gesamt === 500).ewp, 3); // 3 gewertete: 3,2,1
});

test('assignEwp: fieldSize skaliert den Besten auf die volle Feldgröße', () => {
  // Nur 2 von 12 haben gespielt → bester bekommt 12 (nicht 2), lückenlos absteigend.
  const einzel = [p('A', 600), p('B', 500)];
  assignEwp(einzel, 'A', 1, 12);
  const byName = Object.fromEntries(einzel.map((x) => [x.name, x.ewp]));
  assert.equal(byName.A600, 12); // bester → Feldgröße
  assert.equal(byName.B500, 11);
});

test('assignEwp: fieldSize kleiner als Gewertete → mind. Anzahl Gewerteter', () => {
  const einzel = [p('A', 600), p('B', 500), p('A', 400)];
  assignEwp(einzel, 'A', 1, 2); // fieldSize 2 < 3 gewertet → top = 3
  assert.equal(einzel.find((x) => x.gesamt === 600).ewp, 3);
});

test('bahnartOf: aus Preset und ersatzweise aus Teilsätzen', () => {
  assert.equal(bahnartOf({ programm: { preset: 'schere' } }, []), 'schere');
  assert.equal(bahnartOf({}, [{ config: { teilsaetze: [{ modus: 'volle' }, { modus: 'kranz-abraeumen' }] } }]), 'schere');
  assert.equal(bahnartOf({}, [{ config: { teilsaetze: [{ modus: 'volle' }, { modus: 'abraeumen' }] } }]), 'classic');
  assert.equal(bahnartOf({}, [{ config: { teilsaetze: [{ modus: 'volle' }, { modus: 'volle' }] } }]), 'bohle');
});

test('fmtPunkte: ganze Zahl schlicht, halbe mit Komma', () => {
  assert.equal(fmtPunkte(2), '2');
  assert.equal(fmtPunkte(1.5), '1,5');
  assert.equal(fmtPunkte(0), '0');
});

test('computeWertung: EWP-Punkt rechnet auf der vollen Feldgröße (Zwischenstand)', () => {
  // 2x6 Schere, Schwelle 31 (Vereinsvorgabe) — erst je 4 Spieler gewertet, der Gast dominiert.
  // Die EWP-Skala muss die des ganzen Feldes sein (bester = 12), sonst bleibt die Schwelle
  // unerreichbar und der Zusatzpunkt ginge fälschlich ans Heim-Team.
  const teams = [{ id: 'A', name: 'Heim' }, { id: 'B', name: 'Gast' }];
  const wk = { mannschaften: teams, spielerJeMannschaft: 6, programm: { preset: 'schere' },
    wertung: { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 1, ewp: { minHolz: 1 }, ewpSchwelle: 31 } };
  const einzel = [
    p('B', 560), p('B', 555), p('B', 550), p('B', 545),
    p('A', 500), p('A', 495), p('A', 490), p('A', 485),
    p('B', 0), p('B', 0), p('A', 0), p('A', 0), // noch nicht gespielt
  ];
  const w = computeWertung(wk, { einzel }, []);
  assert.equal(w.away.ewpSumme, 42); // 12+11+10+9
  assert.equal(w.home.ewpSumme, 26); // 8+7+6+5
  assert.equal(w.away.ewpPunkt, 1);  // 42 >= 31 → Zusatzpunkt an den Gast
  assert.equal(w.home.ewpPunkt, 0);
  assert.equal(w.away.spielpunkte, 3);
  assert.equal(w.home.spielpunkte, 0);
});

test('computeWertung: Team-EWP-Summen decken sich mit der angezeigten Skala', () => {
  // Der Hub/das Overlay ruft assignEwp nach computeWertung mit derselben Feldgröße erneut auf —
  // beide Wege müssen dieselben Summen liefern (sonst weicht die Anzeige von der Punktvergabe ab).
  const teams = [{ id: 'A', name: 'Heim' }, { id: 'B', name: 'Gast' }];
  const wk = { mannschaften: teams, spielerJeMannschaft: 6, programm: { preset: 'schere' },
    wertung: { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 1, ewp: { minHolz: 1 }, ewpSchwelle: 31 } };
  const einzel = [p('A', 540), p('A', 520), p('B', 530), p('B', 510), p('B', 505)];
  const w = computeWertung(wk, { einzel }, []);
  assignEwp(einzel, 'A', 1, 12); // wie in wettkampf-hub.js / overlay.js
  const sum = (id) => einzel.filter((x) => x.mannschaftId === id).reduce((s, x) => s + (x.ewp || 0), 0);
  assert.equal(sum('A'), w.home.ewpSumme);
  assert.equal(sum('B'), w.away.ewpSumme);
});
