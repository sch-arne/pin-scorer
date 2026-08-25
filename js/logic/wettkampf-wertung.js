// Wettkampf-Wertung: aus der Einzel-Auswertung (computeWettkampfStats) die Spielpunkte je
// Mannschaft ableiten. Reine Logik — Browser + Node ladbar, per Unit-Test abgesichert.
//
// Gesteuert durch die im Setup („Wertung"-Tab) gespeicherte Konfiguration wettkampf.wertung:
//   { modus, gesamtholzPunkte, kriterium2, kriterium2Punkte, ewp:{minHolz}, ewpSchwelle }
// Fehlt sie (Altbestand), wird ein Standard aus der Bahnart abgeleitet.
//
// Umgesetzt: DUELL (2 Mannschaften) mit EWP als Kriterium 2. Regeln:
//   • Kriterium 1 — Gesamtholz: gesamtholzPunkte an die Mannschaft mit dem höheren Gesamtholz
//     (Summe aller Spieler); bei Gleichstand geteilt.
//   • Kriterium 2 — EWP: alle Spieler des Wettkampfs (min. 1 Holz gespielt) in eine gemeinsame
//     Rangliste; der Beste bekommt N EWP (bei 2×6 = 12), der Schlechteste 1. Team-EWP = Summe
//     der eigenen Spieler. Der Gast bekommt kriterium2Punkte, sobald seine Team-EWP-Summe die
//     Schwelle (ewpSchwelle) erreicht; sonst das Heim-Team.
//   Gleichstand-Feinregeln bei GLEICHEM Spielerergebnis (Gesamtholz) für die EWP-Vergabe:
//     – zwischen den Mannschaften: der GAST bekommt die höhere EWP;
//     – innerhalb einer Mannschaft: der Spieler mit dem höheren ABRÄUM-Ergebnis.
//
// Satzpunkte (Classic) und Rangliste (>2 Mannschaften) folgen später — dort liefert
// computeWertung vorerst null (der Hub zeigt dann die Gesamtholz-Rangliste).

// Bahnart eines Wettkampfs bestimmen: bevorzugt aus dem Programm-Preset, sonst aus den
// Teilsätzen eines Durchgang-Spiels abgeleitet (kranz-abräumen → Schere, abräumen → Classic,
// nur Volle → Bohle).
export function bahnartOf(wettkampf, games) {
  const preset = wettkampf && wettkampf.programm && wettkampf.programm.preset;
  if (preset === 'schere' || preset === 'bohle' || preset === 'classic') return preset;
  const cfg = (games || []).map((g) => g && g.config).find((c) => c && Array.isArray(c.teilsaetze));
  const modi = (cfg && cfg.teilsaetze || []).map((t) => t && t.modus);
  if (modi.includes('kranz-abraeumen')) return 'schere';
  if (modi.includes('abraeumen')) return 'classic';
  if (modi.length && modi.every((m) => m === 'volle')) return 'bohle';
  return null;
}

// EWP an die Spieler vergeben (mutiert die Einzel-Objekte: setzt `p.ewp`).
// Nur Spieler mit mindestens `minHolz` gespielten Holz kommen in die Rangliste; wer weniger
// hat (z. B. noch nicht gespielt), bekommt 0 EWP. Reihenfolge (bester zuerst): Gesamtholz
// absteigend; bei Gleichstand steht der Gast VOR dem Heim-Spieler (Gast = höhere EWP),
// innerhalb derselben Mannschaft das höhere Abräum-Ergebnis zuerst.
// Der Beste erhält die volle Feldgröße als EWP: `fieldSize` (Anzahl aller Spieler im Wettkampf,
// z. B. 2×6 = 12), sonst — ohne Vorgabe — die Zahl der bereits gewerteten Spieler. So bleibt die
// Skala über den Wettkampf stabil (bester = Maximum), statt nur die aktuell Spielenden zu zählen.
// Der jeweils Schlechteste liegt entsprechend höher; die Vergabe bleibt lückenlos und distinkt.
export function assignEwp(einzel, homeId, minHolz = 1, fieldSize = 0) {
  const all = (einzel || []).filter((p) => p && p.mannschaftId);
  const gewertet = all.filter((p) => (p.gesamt || 0) >= minHolz);
  const top = Math.max(gewertet.length, fieldSize || 0); // Skala: bester bekommt die volle Feldgröße
  const sorted = gewertet.slice().sort((a, b) =>
    (b.gesamt || 0) - (a.gesamt || 0)                                   // 1. mehr Holz
    || (a.mannschaftId === homeId ? 1 : 0) - (b.mannschaftId === homeId ? 1 : 0) // 2. Gast vor Heim
    || (b.abraeum || 0) - (a.abraeum || 0));                            // 3. mehr Abräumen
  sorted.forEach((p, i) => { p.ewp = top - i; }); // bester → top (Feldgröße), dann absteigend
  all.filter((p) => (p.gesamt || 0) < minHolz).forEach((p) => { p.ewp = 0; });
  return sorted;
}

// Zwei-Nachkommastellen-freie Punktdarstellung: ganze Zahl schlicht, halbe mit Komma.
export function fmtPunkte(n) {
  if (n == null) return '';
  return Number.isInteger(n) ? String(n) : String(n).replace('.', ',');
}

// Wertungskonfiguration ermitteln: bevorzugt die im Setup gespeicherte wettkampf.wertung.
// Fehlt sie (Altbestand ohne „Wertung"-Tab), wird nur für SCHERE ein Standard abgeleitet —
// so bleiben bestehende Schere-Wettkämpfe gewertet, während andere ohne Konfiguration den
// Kegel-Zwischenstand behalten (Rückgabe null). Neue Wettkämpfe bringen ihre Wertung mit.
function wertungConfig(wettkampf, art, teamsCount) {
  if (wettkampf && wettkampf.wertung) return wettkampf.wertung;
  if (art === 'schere') {
    return {
      modus: teamsCount === 2 ? 'duell' : 'rangliste',
      gesamtholzPunkte: 2,
      kriterium2: 'ewp',
      kriterium2Punkte: 1,
      ewp: { minHolz: 1 },
      ewpSchwelle: null, // ohne Vorgabe: neutrale Mitte des möglichen Team-EWP-Bereichs
    };
  }
  return null;
}

// Vollständige Wertung für ein Duell (2 Mannschaften) mit EWP als Kriterium 2. Rückgabe null,
// wenn es keine zwei Mannschaften gibt, der Modus Rangliste ist oder Kriterium 2 Satzpunkte
// nutzt (folgt später) — der Aufrufer zeigt dann die Gesamtholz-Rangliste.
//   wettkampf: { mannschaften:[{id,name}], wertung?, programm? }
//   stats:     Ergebnis von computeWettkampfStats (stats.einzel wird um `ewp` ergänzt)
//   games:     Durchgang-Spiele (nur zur Bahnart-Erkennung als Fallback)
export function computeWertung(wettkampf, stats, games) {
  const teams = (wettkampf && wettkampf.mannschaften) || [];
  if (teams.length < 2) return null;
  const art = bahnartOf(wettkampf, games);
  const cfg = wertungConfig(wettkampf, art, teams.length);
  if (!cfg) return null;                            // keine Wertung hinterlegt/ableitbar
  if (cfg.modus === 'rangliste') return null;      // >2 Mannschaften: folgt später
  if (cfg.kriterium2 === 'satzpunkte') return null; // Satzpunkte: folgt später

  const homeId = teams[0].id;
  const awayId = teams[1].id;
  const einzel = (stats && stats.einzel) || [];
  const minHolz = (cfg.ewp && cfg.ewp.minHolz != null) ? cfg.ewp.minHolz : 1;
  assignEwp(einzel, homeId, minHolz);

  const acc = (id) => einzel.filter((p) => p.mannschaftId === id)
    .reduce((s, p) => ({ holz: s.holz + (p.gesamt || 0), ewp: s.ewp + (p.ewp || 0) }), { holz: 0, ewp: 0 });
  const h = acc(homeId);
  const a = acc(awayId);

  // Kriterium 1 — Gesamtholz: gesamtholzPunkte an das mehr Holz, Gleichstand geteilt.
  const gp = cfg.gesamtholzPunkte != null ? cfg.gesamtholzPunkte : 2;
  let mpH; let mpA;
  if (h.holz > a.holz) { mpH = gp; mpA = 0; } else if (h.holz < a.holz) { mpH = 0; mpA = gp; } else { mpH = gp / 2; mpA = gp / 2; }

  // Kriterium 2 — EWP-Punkt: der Gast bekommt kriterium2Punkte, sobald seine Team-EWP-Summe die
  // Schwelle erreicht; sonst das Heim-Team. Ohne Schwelle die neutrale Mitte (halber EWP-Topf).
  const kp = cfg.kriterium2Punkte != null ? cfg.kriterium2Punkte : 1;
  const topf = (h.ewp + a.ewp);
  const schwelle = cfg.ewpSchwelle != null ? cfg.ewpSchwelle : (topf / 2);
  let epH; let epA;
  if (a.ewp >= schwelle) { epA = kp; epH = 0; } else { epH = kp; epA = 0; }

  const mk = (t, gh, mp, ep) => ({
    mannschaftId: t.id, name: t.name,
    gesamtholz: gh.holz, ewpSumme: gh.ewp,
    mannschaftspunkte: mp, ewpPunkt: ep, spielpunkte: mp + ep,
  });
  const home = mk(teams[0], h, mpH, epH);
  const away = mk(teams[1], a, mpA, epA);
  return {
    bahnart: art, homeId, awayId, home, away,
    ewpSchwelle: schwelle,
    teams: { [homeId]: home, [awayId]: away },
  };
}
