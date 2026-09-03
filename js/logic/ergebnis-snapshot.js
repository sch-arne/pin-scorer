// Der Ergebnis-Snapshot eines fertigen Spiels — die Zeilen für `spiel_ergebnis`.
//
// Dieser Snapshot ist die EINZIGE Quelle der Konto-Statistik: sie fragt nicht die Würfe ab,
// sondern genau diese Zeilen (sync.pullMeineErgebnisse). Fehlt er, liegen Aufstellung und
// Würfe in der Datenbank, und die Statistik bleibt trotzdem leer.
//
// Zwei Spalten tragen die Zuordnung, und sie bedeuten Verschiedenes:
//   • profil_id  — „das bin ICH". Nur an der eigenen Zeile, sonst landeten auf einem
//                  Vereins-PC alle mit erfassten Mitspieler und Gegner in der eigenen
//                  Statistik.
//   • passnummer — die LizenzID, an JEDER Zeile, die eine hat. Darüber findet jeder
//                  Mitspieler sein eigenes Ergebnis auch in fremd erfassten Spielen wieder.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert). Hier,
// damit die beiden Wege, auf denen ein Spiel fertig wird, dieselben Zeilen schreiben:
// das Spielende in der Erfassung und das nachträgliche Teilen eines bereits fertigen Spiels.

// `players` = computeGameStats(...).players, in Positions-Reihenfolge.
// `spielerIdFuer(pos)` liefert die spiel_spieler-id oder etwas Falsy (Position überspringen —
// z.B. ein Spieler, den ein anderes Gerät steuert).
export function ergebnisZeilen(players, {
  spielId, spielerIdFuer, konto = null, passByPos = null, ichIndex = null,
} = {}) {
  const rows = [];
  (players || []).forEach((p, pos) => {
    const spielerId = spielerIdFuer && spielerIdFuer(pos);
    if (!spielerId) return;
    const row = {
      spiel_id: spielId,
      spieler_id: spielerId,
      profil_id: ichIndex != null && pos === ichIndex ? konto : null,
      erfasst_von: konto,
      gesamt: p.gesamt,
      schnitt_satz: p.schnittSatz,
      schnitt_wurf: p.schnittWurf,
      bester_satz: p.bester,
      neuner: p.neuner,
      fehl: p.fehl,
      wurf_count: p.wurfCount,
      rang: p.rang,
    };
    // passnummer nur setzen, wenn vorhanden — so bleibt das Schreiben auch auf einer DB ohne
    // die (neuere) Spalte lauffähig (PostgREST meldet sonst eine unbekannte Spalte).
    const pass = passByPos && passByPos[pos];
    if (pass) row.passnummer = pass;
    rows.push(row);
  });
  return rows;
}
