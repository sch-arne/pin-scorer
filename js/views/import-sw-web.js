// Import eines GESPIELTEN Spiels aus dem öffentlichen Sportwinner-Ergebnisdienst.
//
// Der zweite Import-Weg neben der Brücke (views/import-sportwinner.js). Dort läuft der Import
// VOR dem Spiel auf dem Vereins-PC und die App erfasst danach jeden Wurf; hier wird ein längst
// gespieltes Spiel nachträglich aus dem Netz geholt — für Auswärtsspiele und überall dort, wo
// die Brücke nicht zur Verfügung steht.
//
// Zwei Dinge sind hier grundsätzlich anders als beim Brücken-Import:
//
//  1. DETAILGRAD. Der Ergebnisdienst kennt keine Einzelwürfe, nur Summen. Sie werden als
//     Teilsatz-Overrides eingetragen (logic/sw-web-import.js), damit Holz und Schnitt exakt
//     stimmen und 9er, Räumer und Wurfbild ehrlich leer bleiben statt erfunden zu werden.
//
//  2. DATENSCHUTZ. Die Namen der Mit- und Gegenspieler stammen aus einer öffentlichen Quelle,
//     aber diese Leute wissen von dieser App nichts. Deshalb bleiben sie ausschließlich LOKAL:
//     in die Datenbank wandert allein die eigene Ergebniszeile, und auch die ohne Namen
//     (sync.linkEigenesErgebnis). Aus demselben Grund lässt sich ein so importierter Wettkampf
//     nicht teilen — der Hub sperrt Beitritts-/Zuschauercode und Overlay.
//
//  3. IDENTITÄT. Der Ergebnisdienst nennt keine LizenzIDen; die amtliche Zuordnung des
//     Brücken-Imports gibt es hier also nicht. An ihre Stelle tritt das Profil
//     (logic/profil-match.js) — allerdings gestuft, denn nicht jeder Import ist einer für die
//     eigene Statistik:
//
//       Konto    — ohne Anmeldung gar kein Import (ohne Profil gibt es keinen Abgleich).
//       Verein   — öffnen lässt sich nur eine Partie, in der der eigene Verein mitspielt.
//       Klarname — in die DATENBANK geht ein Ergebnis nur, wenn der eigene Name in der
//                  Aufstellung steht und die Zeile damit belegbar die eigene ist.
//
//     Die letzte Stufe sperrt deshalb nicht den Import, sondern nur die Übernahme ins Konto:
//     ein Mannschaftsspiel, bei dem man nicht selbst angetreten ist, lässt sich als LOKALE
//     Kopie holen (Vergleich, Auswertung der Mannschaft) — es geht dann nichts in die DB.
//     Umgekehrt kann man auch das eigene Spiel bewusst lokal halten (Schalter „nur auf diesem
//     Gerät"). Was die frühere freie „Das bin ich"-Wahl verhindert: fremde Ergebnisse in die
//     eigene Konto-Statistik zu holen.
//
//  4. ZWISCHENSTAENDE. Importierbar ist nicht nur die beendete Partie, sondern auch die
//     laufende und die abnahmebereite. Der Bericht liefert dann einen Zwischenstand: der
//     Wettkampf entsteht vollstaendig, aber mit leeren Saetzen. Wer dieselbe Partie spaeter
//     noch einmal holt, legt keinen zweiten Wettkampf an — es werden nur die Luecken gefuellt
//     (trageErgebnisseEin mit `nurLeere`). Ueberschrieben wird nie etwas, auch keine von Hand
//     nachgetragene Teilsatz-Aufteilung.

import { esc } from '../util.js';
import {
  parseSpielListe, parseSpielerInfo, buildImportSpec, buildImportWettkampf, trageErgebnisseEin,
} from '../logic/sw-web-import.js';
import { gameBaseStatus, wettkampfBaseStatus } from '../logic/wettkampf.js';
import { sektionToBahnart, parseBahnen } from '../logic/roster-import.js';
import { partiePasst, meineKeys, profilVollstaendig } from '../logic/profil-match.js';
import { PRESETS, ART_LABEL } from '../logic/sportkegeln-presets.js';
import {
  saveGame, saveWettkampf, setActiveWettkampf, getWettkaempfe, getWettkampf, getWettkampfGames,
} from '../store.js';
import { navigate } from '../router.js';
import { bestAnlageMatch } from './import-sportwinner.js';
import * as swWeb from '../backend/sw-web.js';

const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();

// Teilsatz-Modus -> Klartext (nur fuer den Hinweistext; die Erfassung hat ihre eigene Tabelle).
const TEIL_LABEL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };

export function importSwWebView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const state = {
    phase: 'laden',        // laden | gesperrt | auswahl | anlegen | fertig | fehler
    fehler: '',
    msg: '',
    // Konto + Profil: ohne beides laeuft hier gar nichts (siehe Kopf, Punkt 3)
    profil: null, angemeldet: false, sperrGrund: '', fehlend: [],
    // Auswahlkette
    saisons: [], saison: '',
    sektion: 2,
    ligen: [], liga: '', ligenLaden: false,
    spieltage: [], spieltag: '',
    partien: [], partie: null, partienLaden: false,
    // Spielbericht + daraus abgeleitetes Spec
    spec: null, berichtLaden: false,
    anlagen: [], anlageId: '', anlageBahnen: [], playedLanes: [], bahnenText: '',
    gemeldeteBahnen: [],   // Bahnen laut Ergebnisdienst (GetBahnanlage) — Vorschlag, nicht Gesetz
    ichKey: '',            // "<mannschaftId>|<teamPos>" — meine Zeile in der Aufstellung
    meineKeys: [],         // die Slots, die laut Profil ueberhaupt meine sein koennen
    inDb: false,           // eigenes Ergebnis ins Konto uebernehmen? (sonst rein lokal)
    nachimport: null,      // { id, name, offen, ichSlot, remote } — Partie ist schon importiert
    warnungen: [],
  };

  // --- Laden ----------------------------------------------------------------

  // Konto + Profil pruefen, BEVOR die Auswahlkette startet.
  //
  // Frueher lief man den ganzen Baum durch und scheiterte erst am Ende an der RLS; und wer
  // kein Profil gepflegt hat, kann hier ohnehin nichts zuordnen — der Ergebnisdienst kennt
  // nur Klarnamen. Beides sagen wir deshalb sofort, samt dem Feld, das fehlt.
  async function pruefeKonto() {
    try {
      const auth = await import('../backend/auth.js');
      const user = await auth.currentUser();
      state.angemeldet = auth.isPermanent(user);
      state.profil = state.angemeldet ? await auth.getProfil() : null;
    } catch (e) {
      state.angemeldet = false;
      state.profil = null;
    }
    if (!state.angemeldet) {
      state.sperrGrund = 'konto';
      state.phase = 'gesperrt';
      render();
      return;
    }
    const { ok, fehlend } = profilVollstaendig(state.profil);
    if (!ok) {
      state.sperrGrund = 'profil';
      state.fehlend = fehlend;
      state.phase = 'gesperrt';
      render();
      return;
    }
    state.sperrGrund = '';
    ladeSaisons();
  }

  async function ladeSaisons() {
    try {
      state.saisons = await swWeb.saisons();
      state.saison = state.saisons.length ? String(state.saisons[0].id) : '';
      state.phase = 'auswahl';
      render();
      if (state.saison) ladeLigen();
    } catch (e) {
      state.phase = 'fehler';
      state.fehler = e.message || 'Ergebnisdienst nicht erreichbar.';
      render();
    }
  }

  async function ladeLigen() {
    state.ligenLaden = true; state.ligen = []; state.liga = '';
    state.spieltage = []; state.spieltag = ''; state.partien = []; state.partie = null;
    state.spec = null;
    render();
    try {
      state.ligen = await swWeb.alleLigen(state.saison, state.sektion);
    } catch (e) {
      state.fehler = e.message || 'Ligen konnten nicht geladen werden.';
    }
    state.ligenLaden = false;
    render();
  }

  async function ladeSpieltageUndPartien() {
    state.partienLaden = true; state.partien = []; state.partie = null; state.spec = null;
    render();
    try {
      // Spieltage sind nur die Filterliste — die Partien kommen unabhängig davon.
      state.spieltage = await swWeb.spieltage(state.saison, state.sektion, state.liga);
    } catch (e) { state.spieltage = []; }
    try {
      const rows = await swWeb.spiele(state.saison, state.sektion, state.liga, state.spieltag);
      // Auch die laufende und die abnahmebereite Partie: sie liefert einen Zwischenstand,
      // und der laesst sich spaeter durch einen zweiten Import vervollstaendigen.
      state.partien = parseSpielListe(rows).filter((p) => p.importierbar);
      if (!state.partien.length) {
        state.fehler = 'Keine Partie in dieser Auswahl, die schon läuft oder gespielt ist.';
      }
      else state.fehler = '';
    } catch (e) {
      state.fehler = e.message || 'Partien konnten nicht geladen werden.';
    }
    state.partienLaden = false;
    render();
  }

  // Spielbericht der gewählten Partie holen und daraus das Import-Spec bauen.
  async function ladeBericht(partie) {
    state.partie = partie; state.spec = null; state.berichtLaden = true; state.fehler = '';
    state.ichKey = ''; state.meineKeys = []; state.inDb = false; state.nachimport = null;
    render();
    try {
      const preset = sektionToBahnart(state.sektion) || 'schere';
      const rows = await swWeb.spielbericht(
        state.saison, state.sektion, partie.idSpiel, partie.wertung,
      );
      const bericht = parseSpielerInfo(rows, { saetze: PRESETS[preset].saetze });
      const spec = buildImportSpec(partie, bericht);
      spec.preset = preset;
      state.spec = spec;
      state.warnungen = spec.warnungen;
      // Wer ich in dieser Aufstellung bin, steht damit fest — die Handauswahl von frueher ist
      // nur noch Bestaetigung (im Paarkreuz koennen es mehrere Positionen sein).
      state.meineKeys = meineKeys(spec, state.profil);
      if (state.meineKeys.length === 1) [state.ichKey] = state.meineKeys;
      // Uebernahme ins Konto ist der Normalfall — aber nur, wenn ueberhaupt eine eigene
      // Zeile da ist. Ohne sie bleibt der Import zwangslaeufig lokal.
      state.inDb = state.meineKeys.length > 0;
      const dup = getWettkaempfe().find((w) => w.swWeb && w.swWeb.idSpiel === spec.idSpiel);
      state.nachimport = dup ? probeNachimport(dup, spec) : null;
      if (!state.nachimport) await ladeAnlage();
    } catch (e) {
      state.fehler = e.message || 'Spielbericht konnte nicht gelesen werden.';
    }
    state.berichtLaden = false;
    render();
  }

  // Was wuerde ein zweiter Import dieser Partie ueberhaupt noch beitragen?
  //
  // Gerechnet auf den Durchgaengen des VORHANDENEN Wettkampfs — deren Bahnplan kann im Hub
  // korrigiert worden sein, und dann sitzt Spalte 1 woanders als beim ersten Import. Geschrieben
  // wird dabei nichts (`probe`); das entscheidet erst der Knopf.
  function probeNachimport(w, spec) {
    const games = getWettkampfGames(w.id);
    const { gefuellt } = trageErgebnisseEin(games, spec, {
      nurLeere: true, probe: true, mannschaften: w.mannschaften,
    });
    return {
      id: w.id,
      name: w.name || '—',
      offen: gefuellt,
      ichSlot: !!w.ichSlot,
      remote: games.some((g) => g.remoteId),
    };
  }

  // Anlage + bespielte Bahnen: die Bahnen kennt nur GetBahnanlage (je Heimmannschaft).
  //
  // Die BAHNNUMMERN sind hier nicht Beiwerk, sondern die Zuordnung selbst: der Ergebnisdienst
  // nummeriert seine vier Ergebnisspalten von 1 bis 4, gemeint ist damit aber die erste bis
  // vierte BESPIELTE Bahn der Anlage. Wer auf den Bahnen 5-8 spielt, bekommt die Spalten also
  // nur dann richtig auf seine Sätze verteilt, wenn hier 5-8 steht (buildImportWettkampf).
  async function ladeAnlage() {
    const spec = state.spec;
    const heim = spec.mannschaften[0].name;
    let ort = null;
    try {
      const anlagen = await swWeb.bahnanlagen(state.saison, state.sektion, state.liga);
      ort = anlagen.find((a) => norm(a.mannschaft) === norm(heim)) || null;
    } catch (e) { /* ohne Spielort weiter — Bahnen lassen sich von Hand setzen */ }

    state.gemeldeteBahnen = parseBahnen(ort && ort.bahnen);
    setBahnen(state.gemeldeteBahnen.length ? state.gemeldeteBahnen : [1, 2, 3, 4]);

    try {
      const mod = await import('../backend/anlagen.js');
      state.anlagen = (await mod.listAnlagen()) || [];
      const treffer = ort ? bestAnlageMatch(state.anlagen, {
        name: ort.anlage, plz: ort.plz, ort: ort.ort,
      }) : null;
      state.anlageId = treffer ? treffer.id : '';
      if (state.anlageId) await ladeAnlageBahnen();
    } catch (e) { /* offline / kein Konto: Anlage bleibt leer, Import geht trotzdem */ }
  }

  // Bespielte Bahnen setzen (eine Quelle für Liste UND Eingabefeld).
  function setBahnen(lanes) {
    state.playedLanes = (lanes || []).slice().sort((a, b) => a - b);
    state.bahnenText = state.playedLanes.join(', ');
  }

  // Bahnen der gewählten Anlage laden und die bespielten daran ausrichten: die echte
  // Nummerierung der Anlage gewinnt gegenüber der Angabe des Ergebnisdienstes. Passt keine
  // gemeldete Bahn zur Anlage, werden die ersten Bahnen der Anlage genommen (so viele, wie
  // gemeldet waren) — sonst stünde die Zuordnung auf Bahnen, die es dort gar nicht gibt.
  async function ladeAnlageBahnen() {
    const mod = await import('../backend/anlagen.js');
    state.anlageBahnen = ((await mod.listBahnen(state.anlageId)) || [])
      .slice().sort((a, b) => a.nummer - b.nummer);
    const nummern = state.anlageBahnen.map((b) => b.nummer);
    if (!nummern.length) return;
    const gemeldet = state.gemeldeteBahnen || [];
    const inter = gemeldet.filter((n) => nummern.includes(n));
    setBahnen(inter.length ? inter : nummern.slice(0, gemeldet.length || 4));
  }

  // --- Anlegen --------------------------------------------------------------

  function ichPosition(game) {
    const liste = (game.config && game.config.spielerListe) || [];
    return liste.findIndex((sp) => `${sp.mannschaftId}|${sp.teamPos}` === state.ichKey);
  }

  async function anlegen() {
    const spec = state.spec;
    if (!spec) return;
    // Der deaktivierte Knopf ist nicht die einzige Verteidigungslinie: in die Datenbank geht
    // eine Zeile nur, wenn sie laut Profil auch wirklich meine ist. Ohne diesen Nachweis wird
    // trotzdem importiert — nur eben rein lokal.
    const insKonto = !!(state.inDb && state.ichKey && state.meineKeys.includes(state.ichKey));
    state.phase = 'anlegen'; state.msg = 'Baue Wettkampf …'; render();
    try {
      const anlage = state.anlagen.find((a) => a.id === state.anlageId) || null;
      const { wettkampf, games } = buildImportWettkampf(spec, {
        playedLanes: state.playedLanes,
        anlageId: state.anlageId || null,
        anlageName: anlage ? anlage.name : '',
        anlageBahnen: state.anlageBahnen,
      });
      // Herkunft vervollständigen: Duplikat-Erkennung und Teilen-Sperre hängen daran.
      Object.assign(wettkampf.swWeb, {
        saison: state.saison, sektion: state.sektion, liga: state.liga,
      });
      // Die eigene Zeile auch beim rein lokalen Import markieren: davon lebt die Statistik
      // auf diesem Geraet. In die DB gespiegelt wird ichSlot ohnehin nie.
      if (state.ichKey && state.meineKeys.includes(state.ichKey)) {
        wettkampf.ichSlot = state.ichKey;
      }

      games.forEach((g) => saveGame(g));
      saveWettkampf(wettkampf);
      setActiveWettkampf(wettkampf.id);

      if (!insKonto) {
        state.msg = state.meineKeys.length
          ? 'Importiert — nur auf diesem Gerät, nichts in die Datenbank übertragen.'
          : 'Importiert — du stehst nicht in der Aufstellung, der Wettkampf bleibt lokal.';
        state.phase = 'fertig';
        render();
        return;
      }

      // Nur die EIGENE Ergebniszeile in die Datenbank — Namen bleiben auf diesem Gerät.
      state.msg = 'Übertrage dein Ergebnis …'; render();
      const meineMannschaft = spec.mannschaften
        .find((m) => state.ichKey.startsWith(`${m.id}|`));
      const sync = await import('../backend/sync.js');
      let uebertragen = 0;
      for (const g of games) {
        const pos = ichPosition(g);
        if (pos < 0) continue;
        const { remoteId } = await sync.linkEigenesErgebnis(g, {
          position: pos,
          mannschaftName: meineMannschaft ? meineMannschaft.name : '',
        });
        g.linked = true;
        g.remoteId = remoteId;
        saveGame(g);
        uebertragen += 1;
      }
      state.msg = uebertragen
        ? `Importiert — ${uebertragen} Durchgang${uebertragen > 1 ? 'e' : ''} in deiner Statistik.`
        : 'Importiert — lokal gespeichert (keine eigene Position gefunden).';
      state.phase = 'fertig';
      render();
    } catch (e) {
      const m = (e && e.message) || '';
      state.phase = 'auswahl';
      state.fehler = /angemeldet|login|auth|jwt|permission|row-level/i.test(m)
        ? 'Konto nötig — bitte unter „Spieler" anmelden und erneut versuchen.'
        : (m || 'Import fehlgeschlagen.');
      render();
    }
  }

  // Zweiter Import derselben Partie: NUR die Luecken fuellen.
  //
  // Kein zweiter Wettkampf — bei einer laufenden Partie liefert der Ergebnisdienst
  // zwangslaeufig Zwischenstaende, und wer noch einmal importiert, will den Stand nachziehen und
  // nicht dasselbe Spiel doppelt in seiner Statistik haben. Ueberschrieben wird nichts: was
  // schon dasteht — importiert ODER von Hand nachgetragen —, bleibt unangetastet.
  async function ergaenzen() {
    const spec = state.spec;
    const nach = state.nachimport;
    if (!spec || !nach) return;
    state.phase = 'anlegen'; state.msg = 'Ergänze Ergebnisse …'; render();
    try {
      const w = getWettkampf(nach.id);
      if (!w) throw new Error('Der Wettkampf ist nicht mehr da — bitte neu importieren.');
      const games = getWettkampfGames(w.id);
      const { gefuellt, geaendert } = trageErgebnisseEin(games, spec, {
        nurLeere: true, mannschaften: w.mannschaften,
      });
      geaendert.forEach((g) => { g.status = gameBaseStatus(g); saveGame(g); });
      w.status = wettkampfBaseStatus(w, games);
      saveWettkampf(w);
      setActiveWettkampf(w.id);

      // Die eigene Zeile in der Datenbank nachziehen — samt Ergebnis-Snapshot: mit neuen Saetzen
      // aendern sich Gesamtholz und Schnitt, und der Snapshot ist die einzige Quelle der
      // Konto-Statistik. Lag der Wettkampf rein lokal, bleibt er es auch jetzt.
      let uebertragen = 0;
      const remote = w.ichSlot ? geaendert.filter((g) => g.remoteId) : [];
      if (remote.length) {
        state.msg = 'Übertrage dein Ergebnis …'; render();
        const sync = await import('../backend/sync.js');
        for (const g of remote) {
          const pos = ((g.config && g.config.spielerListe) || [])
            .findIndex((sp) => `${sp.mannschaftId}|${sp.teamPos}` === w.ichSlot);
          if (pos < 0) continue;
          await sync.pushEigenesErgebnis(g, pos, { ergebnis: true });
          uebertragen += 1;
        }
      }
      state.msg = `${gefuellt} Satzergebnis${gefuellt === 1 ? '' : 'se'} ergänzt`
        + (uebertragen
          ? ` — dein Ergebnis ist in ${uebertragen} Durchgang${uebertragen > 1 ? 'en' : ''} auch `
            + 'in der Datenbank nachgezogen.'
          : ' — nur auf diesem Gerät.');
      state.phase = 'fertig';
      render();
    } catch (e) {
      state.phase = 'auswahl';
      state.fehler = (e && e.message) || 'Ergänzen fehlgeschlagen.';
      render();
    }
  }

  // --- Darstellung ----------------------------------------------------------

  const opt = (v, label, sel) =>
    `<option value="${esc(String(v))}"${String(v) === String(sel) ? ' selected' : ''}>${esc(label)}</option>`;

  function auswahlSection() {
    const s = state;
    return `
      <section class="field">
        <label class="field-label" for="swb-saison">Saison</label>
        <select class="join-input select-full" id="swb-saison" data-field="saison">
          ${s.saisons.map((x) => opt(x.id, `${x.jahr}${x.aktiv ? ' (aktuell)' : ''}`, s.saison)).join('')}
        </select>
      </section>
      <section class="field">
        <label class="field-label" for="swb-sektion">Disziplin</label>
        <select class="join-input select-full" id="swb-sektion" data-field="sektion">
          ${swWeb.SEKTIONEN.map((x) => opt(x.id, x.label, s.sektion)).join('')}
        </select>
      </section>
      <section class="field">
        <label class="field-label" for="swb-liga">Liga</label>
        <select class="join-input select-full" id="swb-liga" data-field="liga" ${s.ligenLaden ? 'disabled' : ''}>
          <option value="">${s.ligenLaden ? 'Lade Ligen …' : 'Bitte wählen'}</option>
          ${s.ligen.map((x) => opt(x.id, x.name, s.liga)).join('')}
        </select>
      </section>
      ${s.liga ? `
      <section class="field">
        <label class="field-label" for="swb-spieltag">Spieltag</label>
        <select class="join-input select-full" id="swb-spieltag" data-field="spieltag">
          <option value="">Alle Spieltage</option>
          ${s.spieltage.map((x) => opt(x.id, x.name, s.spieltag)).join('')}
        </select>
      </section>` : ''}
      ${partienSection()}`;
  }

  // Fremde Partien werden GEZEIGT, aber gesperrt — nicht ausgeblendet. Wer seinen Verein im
  // Profil anders schreibt als der Ergebnisdienst, saehe sonst eine leere Liste und wuesste
  // nicht, warum sein Spiel fehlt. So steht der Grund an der Partie.
  function partienSection() {
    const s = state;
    if (!s.liga) return '';
    if (s.partienLaden) return '<p class="stats-sub">Lade Partien …</p>';
    if (!s.partien.length) return '';
    const verein = (s.profil && s.profil.verein) || '';
    const eigene = s.partien.filter((p) => partiePasst(p, verein)).length;
    // Schon importierte Partien gleich in der Liste kenntlich machen — sonst klickt man sich
    // durch den halben Baum, um dann zu erfahren, dass der Wettkampf laengst da ist.
    const schonDa = new Set(getWettkaempfe()
      .filter((w) => w.swWeb && w.swWeb.idSpiel).map((w) => w.swWeb.idSpiel));
    return `
      <section class="field">
        <label class="field-label">Partie</label>
        <div class="stat-list">
          ${s.partien.map((p) => {
            const meine = partiePasst(p, verein);
            return `<button type="button" class="resume-main" data-partie="${esc(p.idSpiel)}"
              ${meine ? '' : 'disabled'}
              ${s.partie && s.partie.idSpiel === p.idSpiel ? 'aria-current="true"' : ''}>
              <span class="tile-label">${esc(p.heim)} – ${esc(p.gast)}</span>
              <span class="tile-desc">${esc(p.termin)} · ${esc(String(p.heimWert))}:${esc(String(p.gastWert))}${
                p.gespielt ? '' : ` · ${esc(p.status || 'läuft')}`}${
                schonDa.has(p.idSpiel) ? ' · importiert' : ''}${
                meine ? '' : ' · nicht dein Verein'}</span>
            </button>`;
          }).join('')}
        </div>
        <p class="field-hint">${eigene
          ? `Importieren lässt sich nur eine Partie mit deinem Verein („${esc(verein)}").`
          : `Keine Partie mit deinem Verein („${esc(verein)}") in dieser Auswahl. Passt die
             Schreibweise? Der Ergebnisdienst nennt die Mannschaft, dein Profil den Verein —
             im <a class="anl-inline-link" href="#/spieler">Profil</a> anpassen.`}</p>
      </section>`;
  }

  function berichtSection() {
    const s = state;
    if (s.berichtLaden) return '<p class="stats-sub">Lade Spielbericht …</p>';
    const spec = s.spec;
    if (!spec) return '';

    const ohneSaetze = Object.values(spec.ergebnisse).some((e) => !e.saetze);
    if (ohneSaetze) {
      return `<section class="field">
        <p class="field-hint">⚠ Der Ergebnisdienst liefert für diese Partie nur Gesamtsummen je
          Spieler, keine Satzergebnisse. Ein Import würde die Sätze erfinden — deshalb ist er
          hier gesperrt.</p>
      </section>`;
    }

    // Schon importiert: dann wird nicht noch einmal angelegt, sondern ERGAENZT. Anlage, Bahnen
    // und die eigene Zeile stehen im vorhandenen Wettkampf laengst fest — sie hier noch einmal
    // zu fragen, koennte den Stand nur verschlechtern.
    if (s.nachimport) return nachimportSection();

    const anlage = s.anlagen.find((a) => a.id === s.anlageId);
    const teams = spec.mannschaften.map((m) => `
      <div class="field">
        <span class="field-label">${esc(m.name)}</span>
        <div class="stat-list">
          ${m.spieler.map((p) => {
            const key = `${m.id}|${p.teamPos}`;
            const erg = spec.ergebnisse[key];
            const holz = erg && erg.saetze
              ? erg.saetze.reduce((n, x) => n + (x.holz || 0), 0) : 0;
            const meiner = s.meineKeys.includes(key);
            return `<button type="button" class="resume-main" data-ich="${esc(key)}"
                ${meiner ? '' : 'disabled'}
                ${s.ichKey === key ? 'aria-current="true"' : ''}>
                <span class="tile-label">${s.ichKey === key ? '★ ' : ''}${esc(p.name)}</span>
                <span class="tile-desc">${holz} Holz</span>
              </button>`;
          }).join('')}
        </div>
      </div>`).join('');

    return `
      <section class="field">
        <span class="field-label">Programm</span>
        <span class="readout">${esc(ART_LABEL[spec.preset] || spec.preset)}
          <small>· ${PRESETS[spec.preset].saetze}×${PRESETS[spec.preset].wuerfeProSatz}
          · ${PRESETS[spec.preset].teilsaetze.length} Teilsätze</small></span>
      </section>
      <section class="field">
        <label class="field-label" for="swb-anlage">Anlage</label>
        <select class="join-input select-full" id="swb-anlage" data-field="anlageId">
          <option value="">Ohne Anlage (nur lokal)</option>
          ${s.anlagen.map((a) => opt(a.id, a.name, s.anlageId)).join('')}
        </select>
        ${anlage ? '' : '<p class="field-hint">Ohne Anlage bleibt der Wettkampf rein lokal.</p>'}
      </section>
      <section class="field">
        <label class="field-label" for="swb-bahnen">Bespielte Bahnen</label>
        <input class="join-input select-full" id="swb-bahnen" data-field="bahnenText" type="text"
          placeholder="z. B. 5-8" value="${esc(s.bahnenText)}" />
        <p class="field-hint">🎳 Der Ergebnisdienst zählt seine Ergebnisspalten von 1 bis 4 — gemeint
          ist die erste bis vierte Bahn DIESER Anlage. Spalte 1 wird deshalb Bahn
          ${esc(String(s.playedLanes[0] != null ? s.playedLanes[0] : '?'))} zugeordnet und von dort
          über den Bahnwechsel auf den Satz gelegt, den der Spieler dort gespielt hat.
          ${s.gemeldeteBahnen.length && s.gemeldeteBahnen.join(',') !== s.playedLanes.join(',')
            ? `Der Ergebnisdienst meldet ${esc(s.gemeldeteBahnen.join(', '))}.` : ''}</p>
        <p class="field-hint">Wer auf welcher Bahn beginnt, sagt Sportwinner nicht — vorbelegt
          wird der Standard der Bahnart (${esc(ART_LABEL[spec.preset] || spec.preset)}). Stimmt er
          nicht, lässt sich die Startbahn nach dem Import in der Mannschafts-Übersicht ändern;
          die Ergebnisse wandern dann mit ihrer Bahn.</p>
      </section>
      <section class="field">
        <label class="field-label">Deine Zeile${s.meineKeys.length > 1
          ? ' <small class="field-note">· Pflicht</small>' : ''}</label>
        ${teams}
        <p class="field-hint">${meineZeileHinweis()}</p>
        ${s.meineKeys.length ? `
        <label class="field-check">
          <input type="checkbox" data-field="inDb" ${s.inDb ? 'checked' : ''} />
          <span>Ergebnis in meine Konto-Statistik übernehmen</span>
        </label>
        <p class="field-hint">${s.inDb
          ? 'Deine Ergebniszeile geht (ohne Namen) in die Datenbank und zählt damit auf allen '
            + 'deinen Geräten.'
          : 'Aus: Der Wettkampf bleibt vollständig auf diesem Gerät — nichts wird übertragen. '
            + 'Nachträglich übernehmen geht nicht: ein zweiter Import derselben Partie ergänzt '
            + 'nur fehlende Ergebnisse. Dafür müsstest du ihn löschen und neu importieren.'}</p>`
        : ''}
      </section>
      <section class="field">
        <p class="field-hint">📉 Der Ergebnisdienst kennt keine Einzelwürfe. Holz, Schnitt und
          bester Satz stimmen exakt; 9er, Räumer-Tempo, Fehlwürfe und Wurfbild bleiben bei
          importierten Spielen leer — sie lassen sich aus Summen nicht rekonstruieren.</p>
        ${spec.nurHolz ? `<p class="field-hint">➗ Für diese Partie nennt der Bericht nur das
          Satz-Holz, nicht die Trennung in Volle und Abräumen. Der Wettkampf bekommt trotzdem die
          Teilsätze der Bahnart (${esc(PRESETS[spec.preset].teilsaetze.map((m) => TEIL_LABEL[m] || m).join(' + '))});
          sie bleiben leer, und das Satzergebnis steht am Satz — es stimmt exakt. Wer die
          Aufteilung kennt, kann sie in der Übersicht nachtragen: der zweite Teilsatz ergibt sich
          dann von selbst.</p>` : ''}
        <p class="field-hint">🔒 Datenschutz: Die Namen aller Spieler bleiben auf DIESEM Gerät.
          ${s.inDb
            ? 'In die Datenbank geht ausschließlich deine eigene Ergebniszeile, und auch die '
              + 'ohne Namen.'
            : 'In die Datenbank geht bei diesem Import gar nichts.'}
          Ein so importierter Wettkampf lässt sich deshalb nicht teilen und nicht im
          Overlay zeigen.</p>
      </section>
      ${warnungenSection()}`;
  }

  function warnungenSection() {
    return state.warnungen.length
      ? `<section class="field">${state.warnungen
        .map((w) => `<p class="field-hint">⚠ ${esc(w)}</p>`).join('')}</section>`
      : '';
  }

  // Die Partie liegt schon als Wettkampf vor — hier steht nur noch, was ein zweiter Import
  // beitragen wuerde.
  function nachimportSection() {
    const n = state.nachimport;
    return `
      <section class="field">
        <p class="field-hint">${n.offen
          ? `↻ Diese Partie ist schon importiert („${esc(n.name)}"). Der Ergebnisdienst hat
             inzwischen ${n.offen} Satzergebnis${n.offen === 1 ? '' : 'se'} mehr — genau die
             kommen dazu. Alles, was schon dasteht, bleibt unangetastet.`
          : `✓ Diese Partie ist schon importiert („${esc(n.name)}") und dort vollständig —
             es gibt nichts zu ergänzen. Du kannst sie direkt öffnen.`}</p>
        ${n.offen && n.ichSlot && !n.remote
          ? `<p class="field-hint">🔒 Der Wettkampf liegt nur auf diesem Gerät; das bleibt auch
             so. Wer ihn doch in der Konto-Statistik haben will, muss ihn löschen und neu
             importieren.</p>` : ''}
        ${n.offen && n.ichSlot && n.remote
          ? '<p class="field-hint">Deine Ergebniszeile wird dabei auch in der Datenbank '
            + 'nachgezogen — weiterhin ohne Namen.</p>' : ''}
      </section>
      ${warnungenSection()}`;
  }

  // Drei Faelle: gar kein Treffer (Import bleibt lokal), genau einer (vorbelegt), mehrere
  // (Paarkreuz — der Nutzer sagt, welche Position dieser Durchgang ist).
  function meineZeileHinweis() {
    const s = state;
    const name = [s.profil && s.profil.vorname, s.profil && s.profil.nachname]
      .filter(Boolean).join(' ');
    if (!s.meineKeys.length) {
      return `„${esc(name)}" steht nicht in dieser Aufstellung — der Wettkampf lässt sich
        trotzdem importieren, bleibt dann aber ganz auf diesem Gerät und geht in keine
        Konto-Statistik. Bist du doch dabei und schreibt der Ergebnisdienst deinen Namen
        anders, passe ihn im <a class="anl-inline-link" href="#/spieler">Profil</a> an.`;
    }
    if (s.meineKeys.length > 1 && !s.ichKey) {
      return 'Du stehst mehrfach in der Aufstellung — wähle die Position dieses Durchgangs.';
    }
    return '★ Aus deinem Profil erkannt. Nur die Ergebnisse dieser Zeile können in deine '
      + 'Statistik gehen; alle anderen Spieler bleiben in jedem Fall rein lokal.';
  }

  function render() {
    const s = state;
    if (s.phase === 'laden') {
      root.innerHTML = '<header class="app-header"><h1 class="brand">Aus dem Ergebnisdienst</h1>'
        + '</header><p class="stats-sub">Lade Saisons …</p>';
      return;
    }
    if (s.phase === 'gesperrt') {
      // Der Marker „Ergebnisdienst" bleibt auch hier stehen (Router-Test 00-router.js).
      const konto = s.sperrGrund === 'konto';
      root.innerHTML = `
        <header class="app-header"><h1 class="brand">Aus dem Ergebnisdienst</h1></header>
        <p class="field-hint">${konto
          ? '🔒 Zum Importieren brauchst du ein Konto — das Ergebnis wird deinem Profil '
            + 'zugeordnet, und ohne Anmeldung gibt es kein Profil.'
          : `🔒 Dein Profil braucht dafür noch ${esc(s.fehlend.join(' und '))}. Der
             Ergebnisdienst nennt keine LizenzIDen — deine Zeile wird über Verein und
             Klarnamen erkannt.`}</p>
        <div class="field-row">
          <a class="btn-primary" href="#/spieler">${konto ? 'Jetzt anmelden' : 'Zum Profil'}</a>
          <button type="button" class="erf-btn" data-action="erneut">Erneut prüfen</button>
          <a class="erf-btn" href="#/menu">Zurück</a>
        </div>`;
      return;
    }
    if (s.phase === 'fehler') {
      // Eine Sackgasse mit nur „Zurück" ist keine Auskunft: hier steht, WORAN es liegt, und
      // beide Wege weiter — noch einmal versuchen und (der haeufigste Grund) anmelden.
      root.innerHTML = `
        <header class="app-header"><h1 class="brand">Aus dem Ergebnisdienst</h1></header>
        <p class="field-hint">⚠ ${esc(s.fehler)}</p>
        <div class="field-row">
          <button type="button" class="btn-primary" data-action="erneut">Erneut versuchen</button>
          <a class="erf-btn" href="#/spieler">Zum Konto</a>
          <a class="erf-btn" href="#/menu">Zurück</a>
        </div>`;
      return;
    }
    if (s.phase === 'fertig') {
      root.innerHTML = `
        <header class="app-header"><h1 class="brand">Import fertig</h1></header>
        <p class="stats-sub">${esc(s.msg)}</p>
        <div class="field-row">
          <a class="btn-primary" href="#/wettkampf">Zum Wettkampf</a>
          <a class="erf-btn" href="#/statistiken">Zur Statistik</a>
        </div>`;
      return;
    }

    // Ohne Uebernahme ins Konto braucht es keine eigene Zeile — nur mit ihr muss belegt
    // sein, WELCHE Zeile meine ist (im Paarkreuz waehlt der Nutzer sie).
    const nach = s.nachimport;
    const zeileOk = !s.inDb || (s.ichKey && s.meineKeys.includes(s.ichKey));
    const kannAnlegen = !!(s.spec && !nach && zeileOk && s.phase === 'auswahl'
      && !Object.values(s.spec.ergebnisse).some((e) => !e.saetze));
    const kannErgaenzen = !!(nach && nach.offen && s.phase === 'auswahl');
    root.innerHTML = `
      <header class="app-header">
        <h1 class="brand">Aus dem Ergebnisdienst</h1>
        <p class="tagline">Ein gespieltes Spiel per Webabfrage übernehmen</p>
      </header>
      ${s.fehler ? `<p class="field-hint">⚠ ${esc(s.fehler)}</p>` : ''}
      ${auswahlSection()}
      ${berichtSection()}
      <div class="field-row">
        <button type="button" class="btn-primary" data-action="${nach ? 'ergaenzen' : 'anlegen'}"
          ${(nach ? kannErgaenzen : kannAnlegen) ? '' : 'disabled'}>
          ${s.phase === 'anlegen' ? esc(s.msg || 'Importiere …')
            : nach ? 'Fehlende Ergebnisse ergänzen'
              : (s.spec && !s.inDb ? 'Nur lokal importieren' : 'Importieren')}
        </button>
        ${nach ? `<button type="button" data-action="oeffnen"
          class="${nach.offen ? 'erf-btn' : 'btn-primary'}">Wettkampf öffnen</button>` : ''}
        <a class="erf-btn" href="#/menu">Abbrechen</a>
      </div>`;
  }

  root.addEventListener('change', (ev) => {
    const feld = ev.target.dataset && ev.target.dataset.field;
    if (!feld) return;
    if (feld === 'inDb') { state.inDb = ev.target.checked; render(); return; }
    state[feld] = feld === 'sektion' ? Number(ev.target.value) : ev.target.value;
    if (feld === 'saison' || feld === 'sektion') ladeLigen();
    else if (feld === 'liga') { state.spieltag = ''; ladeSpieltageUndPartien(); }
    else if (feld === 'spieltag') ladeSpieltageUndPartien();
    else if (feld === 'bahnenText') {
      // Von Hand gesetzte Bahnen: leere/unlesbare Eingabe faellt auf die Meldung des
      // Ergebnisdienstes zurueck, damit die Spalten-Zuordnung nie ohne Bahnen dasteht.
      const lanes = parseBahnen(ev.target.value);
      setBahnen(lanes.length ? lanes : (state.gemeldeteBahnen.length ? state.gemeldeteBahnen : [1, 2, 3, 4]));
      render();
    } else if (feld === 'anlageId') {
      state.anlageBahnen = [];
      if (state.anlageId) ladeAnlageBahnen().catch(() => {}).then(render);
      else { setBahnen(state.gemeldeteBahnen.length ? state.gemeldeteBahnen : state.playedLanes); render(); }
    } else render();
  });

  root.addEventListener('click', (ev) => {
    const partie = ev.target.closest('[data-partie]');
    if (partie) {
      const p = state.partien.find((x) => x.idSpiel === partie.dataset.partie);
      if (p && partiePasst(p, (state.profil && state.profil.verein) || '')) ladeBericht(p);
      return;
    }
    const ich = ev.target.closest('[data-ich]');
    if (ich) { state.ichKey = ich.dataset.ich; render(); return; }
    if (ev.target.closest('[data-action="erneut"]')) {
      state.phase = 'laden'; state.fehler = '';
      render();
      pruefeKonto();
      return;
    }
    // Schon importiert: direkt hin. Der Umweg ueber das Menue waere hier reine Schikane —
    // an dieser Stelle weiss die Ansicht ja genau, welcher Wettkampf gemeint ist.
    if (ev.target.closest('[data-action="oeffnen"]')) {
      if (!state.nachimport) return;
      setActiveWettkampf(state.nachimport.id);
      navigate('/wettkampf');
      return;
    }
    if (ev.target.closest('[data-action="ergaenzen"]')) { ergaenzen(); return; }
    const btn = ev.target.closest('[data-action="anlegen"]');
    if (btn) anlegen();
  });

  render();
  pruefeKonto();
  return root;
}
