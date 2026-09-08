// Abgleich zwischen dem eigenen PROFIL und einer Aufstellung aus dem Ergebnisdienst.
//
// Der Brücken-Import kennt die LizenzID jedes Spielers und weiß damit amtlich, wer wer ist
// (logic/spieler-identitaet.js). Der Web-Import kann das nicht: der öffentliche Ergebnisdienst
// nennt keine LizenzIDen, nur Klarnamen. Ohne eine Prüfung wäre die „Das bin ich"-Markierung
// dort völlig frei — jeder könnte sich als beliebigen Spieler markieren und dessen Ergebnisse
// in die eigene Konto-Statistik holen. Deshalb treten hier VEREIN und KLARNAME aus dem Profil
// an die Stelle der LizenzID:
//
//   profil.verein            ←→  Mannschaftsname der Partie   (welche Partien darf ich öffnen?)
//   profil.vorname/nachname  ←→  Name in der Aufstellung       (welche Zeile ist meine?)
//
// Beide Quellen sind Menschenwerk: das Profil ist ein Freitextfeld, der Ergebnisdienst schreibt
// „VOK Osnabrück 1" statt „VOK Osnabrück" und „Schierbaum, Arne" statt „Arne Schierbaum".
// Der Abgleich ist deshalb bewusst tolerant — aber nur in Schreibweise, nie in der Person.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

// Vergleichsform eines Namens: Kleinschreibung, Umlaute/Akzente gefaltet (NFD + Marken weg),
// alles außer Buchstaben/Ziffern zu Leerzeichen. „Osnabrück" und „Osnabruck" werden damit
// gleich, „Greste-Lage" und „Greste Lage" auch.
export function normalisiere(s) {
  return String(s == null ? '' : s)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

// Mannschaftsnummer am Ende abschneiden: „vok osnabruck 1" -> „vok osnabruck".
// Der Ergebnisdienst hängt sie an JEDEN Mannschaftsnamen, im Profil steht der Verein.
// Arabisch wie römisch, weil beide Schreibweisen im Spielbetrieb vorkommen.
const ohneMannschaftsNr = (s) => s.replace(/\s+(\d{1,2}|i{1,3}|iv|v|vi{1,3}|ix|x)$/, '').trim();

// Ein Vereinsname ist erst ab dieser Länge aussagekräftig. Kürzere („sv", „tv") würden als
// Teilzeichenkette in halb Deutschland stecken und die Prüfung wertlos machen.
const MIN_VEREIN = 3;

// Gehört diese Mannschaft zu meinem Verein?
//
// Stufen: gleich > der eine Name steckt im anderen. Die zweite Stufe fängt genau die Fälle ab,
// die im Alltag entstehen — „VOK Osnabrück" im Profil gegen „VOK Osnabrück 1" beim Ergebnis-
// dienst, oder umgekehrt ein ausgeschriebener Vereinsname gegen ein Kürzel im Spielbetrieb.
export function vereinMatcht(mannschaftName, verein) {
  const a = ohneMannschaftsNr(normalisiere(mannschaftName));
  const b = ohneMannschaftsNr(normalisiere(verein));
  if (a.length < MIN_VEREIN || b.length < MIN_VEREIN) return false;
  return a === b || a.includes(b) || b.includes(a);
}

// Spielt mein Verein in dieser Partie überhaupt mit? (partie aus parseSpielListe)
export function partiePasst(partie, verein) {
  if (!partie) return false;
  return vereinMatcht(partie.heim, verein) || vereinMatcht(partie.gast, verein);
}

// Namens-Bestandteile in Vergleichsform. „Schierbaum, Arne" und „Arne Schierbaum" ergeben
// dieselbe Menge — die Reihenfolge sagt beim Ergebnisdienst nichts Verlässliches, der
// Bestand schon. Doppelnamen zerfallen dabei in ihre Teile („Meyer-Schmidt" -> meyer, schmidt),
// damit eine unterschiedliche Bindestrich-Schreibweise nicht zum Nichttreffer führt.
function teile(s) {
  return normalisiere(s).split(' ').filter(Boolean);
}

// Steht dieser Vorname in der Aufstellung? Ein einzelner Buchstabe ist die Abkürzung, wie sie
// manche Vereine melden („Schierbaum, A."); sie zählt nur, wenn der Anfangsbuchstabe passt.
// Ein abgekürzter Vorname im PROFIL zählt dagegen nie — das Profil gehört dem Nutzer, dort
// steht der echte Name.
function vornameTrifft(tokens, vorname) {
  const v = teile(vorname);
  if (!v.length) return false;
  return v.every((teil) => tokens.some((t) => t === teil
    || (t.length === 1 && t === teil[0])));
}

// Ist das MEIN Name in der Aufstellung?
//
// Verlangt werden Vor- UND Nachname aus dem Profil; ein Treffer allein auf dem Nachnamen wäre
// in einer Mannschaft mit Brüdern oder Vater und Sohn genau der Fehlgriff, den diese Prüfung
// verhindern soll. Fehlt eines der beiden Profilfelder, gibt es keinen Treffer — dann ist die
// Frage „bin ich das?" schlicht nicht beantwortbar.
export function nameMatcht(aufstellungsName, profil) {
  const tokens = teile(aufstellungsName);
  if (!tokens.length || !profil) return false;
  const nach = teile(profil.nachname);
  if (!nach.length || !nach.every((teil) => tokens.includes(teil))) return false;
  return vornameTrifft(tokens, profil.vorname);
}

// Welche Slots dieses Import-Specs (buildImportSpec) bin ICH?
//
// Rückgabe: Liste von "<mannschaftId>|<teamPos>". Ein Slot zählt nur, wenn BEIDES stimmt —
// die Mannschaft gehört zu meinem Verein UND der Name ist meiner. Die Vereinsbedingung ist
// dabei kein Beiwerk: ohne sie könnte ein zufällig gleichnamiger Gegner gewählt werden.
// Im Paarkreuz tritt derselbe Spieler mehrfach an, deshalb sind mehrere Treffer möglich.
export function meineKeys(spec, profil) {
  if (!spec || !profil) return [];
  const out = [];
  (spec.mannschaften || []).forEach((m) => {
    if (!vereinMatcht(m.name, profil.verein)) return;
    (m.spieler || []).forEach((p) => {
      if (nameMatcht(p.name, profil)) out.push(`${m.id}|${p.teamPos}`);
    });
  });
  return out;
}

// Trägt das Profil alles, was der Abgleich braucht? Die fehlenden Felder werden benannt,
// damit die View nicht „Profil unvollständig" sagen muss, sondern WAS fehlt.
export function profilVollstaendig(profil) {
  const fehlend = [];
  if (!teile(profil && profil.vorname).length) fehlend.push('Vorname');
  if (!teile(profil && profil.nachname).length) fehlend.push('Nachname');
  if (ohneMannschaftsNr(normalisiere(profil && profil.verein)).length < MIN_VEREIN) {
    fehlend.push('Verein');
  }
  return { ok: !fehlend.length, fehlend };
}
