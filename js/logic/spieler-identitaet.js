// Spieler-Identität: welcher Slot eines Spiels ist WELCHE Person?
//
// Ein Spieler ist in diesem Datenmodell kein eigener Datensatz, sondern eine Position in
// einem Spiel (config.spielerListe[i] bzw. spiel_spieler.position). Die Brücke zu einem
// Account läuft über die LizenzID/Passnummer:
//
//   profil.passnummer  ←→  wettkampf.sportwinner.spieler[].pass  →  Position im Durchgang
//
// Zusätzlich gibt es die manuelle „Das bin ich"-Markierung für Spiele ohne Sportwinner-
// Roster (Training, Freizeit). Beides mündet hier in einer einzigen Frage: welcher Index
// bin ich in DIESEM Spiel? Genau dieser Index bekommt beim Spielende `profil_id` gesetzt —
// alle anderen bleiben NULL, damit mit erfasste Mitspieler und Gegner nicht in der eigenen
// Account-Statistik landen.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

// Schlüssel einer Spieler-Position im Wettkampf: "<mannschaftId>|<teamPos>". Stabil über
// alle Durchgänge hinweg (im Paarkreuz tritt derselbe Spieler mehrfach an, jedes Mal auf
// einem anderen Spieler-Index). null, wenn der Eintrag keine Team-Zuordnung trägt
// (Einzelspiel/Training) — dort adressiert die Position selbst.
export function slotKey(sp) {
  if (!sp || sp.mannschaftId == null || sp.teamPos == null) return null;
  return `${sp.mannschaftId}|${sp.teamPos}`;
}

// Passnummern je Spieler-Position eines Durchgangs: { [position]: '095578', … }.
// Auflösung über die Sportwinner-Zuordnung (mannschaftId|teamPos), nicht über den Namen —
// eine Umbenennung im Kontrollzentrum darf die LizenzID nicht verschieben.
// Leeres Objekt, wenn kein Roster vorliegt (manuell angelegte Spiele).
export function passByPosition(config, sportwinner) {
  const out = {};
  const liste = (config && config.spielerListe) || [];
  const swSpieler = (sportwinner && sportwinner.spieler) || [];
  if (!swSpieler.length) return out;

  const byKey = {};
  swSpieler.forEach((s) => {
    const pass = String(s.pass == null ? '' : s.pass).trim();
    if (pass) byKey[`${s.mannschaftId}|${s.teamPos}`] = pass;
  });
  liste.forEach((sp, i) => {
    const k = slotKey(sp);
    if (k && byKey[k]) out[i] = byKey[k];
  });
  return out;
}

// Ist die Zuordnung in diesem Wettkampf AUSSCHLIESSLICH Sache der LizenzID?
//
// Ein aus Sportwinner importierter Wettkampf bringt die amtliche Aufstellung samt LizenzID
// jedes Spielers mit. Wer wer ist, steht damit fest — eine manuelle „Das bin ich"-Markierung
// wäre dort nicht nur überflüssig, sondern gefährlich: sie könnte die amtliche Zuordnung
// überstimmen und jemandem fremde Ergebnisse in die Statistik schreiben. Deshalb zählt in
// solchen Wettkämpfen NUR der LizenzID-Treffer. Manuell angelegte Wettkämpfe (und Training)
// haben keine LizenzIDen — dort ist die Selbstmarkierung der einzige Weg und bleibt erlaubt.
export function istLizenzWettkampf(wettkampf) {
  if (!wettkampf) return false;
  return wettkampf.quelle === 'sportwinner' || !!wettkampf.sportwinner;
}

// Welcher Spieler-Index bin ICH in diesem Spiel? null = keiner (z.B. ein Durchgang, in dem
// ich nicht antrete, oder ein Spiel, das ich nur für andere erfasst habe).
//
// Reihenfolge — die ausdrückliche Entscheidung des Nutzers schlägt die Automatik:
//   1) ichSlot  — Wettkampf-Markierung ("<mannschaftId>|<teamPos>"), gilt für alle Durchgänge
//   2) ichIndex — Einzelspiel-Markierung (Position in genau diesem Spiel)
//   3) LizenzID — eigene profil.passnummer gegen die Aufstellungs-Pässe (passByPos)
//
// `nurLizenz` (Sportwinner-Wettkämpfe, siehe istLizenzWettkampf) überspringt 1) und 2)
// vollständig: dort entscheidet allein die LizenzID.
export function resolveIchIndex(config, opts = {}) {
  const liste = (config && config.spielerListe) || [];
  const {
    ichSlot = null, ichIndex = null, passByPos = null, meinePass = null, nurLizenz = false,
  } = opts;

  if (!nurLizenz) {
    if (ichSlot) {
      const i = liste.findIndex((sp) => slotKey(sp) === ichSlot);
      if (i >= 0) return i;
    }
    if (Number.isInteger(ichIndex) && ichIndex >= 0 && ichIndex < liste.length) return ichIndex;
  }

  const pass = String(meinePass == null ? '' : meinePass).trim();
  if (pass && passByPos) {
    const treffer = Object.keys(passByPos)
      .find((pos) => String(passByPos[pos]).trim() === pass);
    if (treffer != null) return Number(treffer);
  }
  return null;
}

// Der Wettkampf-Slot ("<mannschaftId>|<teamPos>"), unter dem die eigene LizenzID in der
// Aufstellung steht — für die automatische Vorbelegung der „Das bin ich"-Markierung beim
// Sportwinner-Import. null, wenn die eigene LizenzID nicht in der Aufstellung vorkommt.
export function ichSlotAusRoster(sportwinner, meinePass) {
  const pass = String(meinePass == null ? '' : meinePass).trim();
  if (!pass) return null;
  const treffer = ((sportwinner && sportwinner.spieler) || [])
    .find((s) => String(s.pass == null ? '' : s.pass).trim() === pass);
  return treffer ? `${treffer.mannschaftId}|${treffer.teamPos}` : null;
}

// Lokal vorhandene KLARNAMEN gegen eine serverseitig anonymisierte Aufstellung behaupten.
//
// Sobald ein Spiel auf `beendet` steht, ersetzt der DB-Trigger die Namen (Anzeigename des
// Profils bzw. neutraler Platzhalter). Geräte, die während des Spiels verbunden waren, haben
// die echten Namen aber bereits lokal — die sollen dort stehen bleiben. Diese Funktion wird
// deshalb NUR für anonymisierte Spiele aufgerufen (spiel.anonymisiert_am gesetzt); bei allen
// übrigen gewinnt weiterhin der Server, damit Umbenennungen im Kontrollzentrum ankommen.
//
// Rückgabe: eine NEUE Liste (Eingaben werden nicht verändert).
export function mergeSpielerNamen(remoteListe, lokalListe) {
  const rem = Array.isArray(remoteListe) ? remoteListe : [];
  const lok = Array.isArray(lokalListe) ? lokalListe : [];
  if (!lok.length) return rem;
  return rem.map((sp, i) => {
    const name = lok[i] && typeof lok[i].name === 'string' ? lok[i].name.trim() : '';
    return name ? { ...sp, name } : sp;
  });
}
