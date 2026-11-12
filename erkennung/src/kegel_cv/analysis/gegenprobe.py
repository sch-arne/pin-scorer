"""Vier Messungen, die einander befragen -- vorerst nur beobachtend.

DIE IDEE (Nutzer, 2026-09-15): *"ich moechte erreichen, dass wir 2 Messsysteme
parallel laufen haben, die sich am Ende gegenseitig korrigieren."*

Das Werkzeug misst die gefallenen Kegel aus den LAMPEN. Die Tafel weiss es
ebenfalls, auf mehreren voneinander unabhaengigen Wegen.

DER TRICK MIT DER SUMME. Die Anzeige traegt das Ergebnis erst nach dem Wurf
nach; zum Meldezeitpunkt steht dort der Stand VOR diesem Wurf (gemessen ueber
einen ganzen Lauf: 294 von 305 Faellen, siehe `throw_analyzer`). Genau daraus
wird ein unabhaengiges Mass:

    Summe(N+1) - Summe(N) = gefallene Kegel bei Wurf N

Die Differenz zweier aufeinanderfolgender Summen ist eine Kegelzahl, die weder
aus den Lampen noch aus der Kegelziffer stammt. Sie kommt einen Wurf zu
spaet -- fuer eine Gegenprobe ist das gleichgueltig.

DIE WURFNUMMER sagt, OB ueberhaupt geworfen wurde. Sie steigt um genau eins
oder faellt beim Spielwechsel auf null zurueck; Zwischenwerte gibt es nicht,
weil jede Ziffer anders leuchtet als die naechste. Steht sie still, hat die
Anlage keinen Wurf gezaehlt -- wir aber einen gebucht.

DER FEHLWURFZAEHLER schliesst die letzte Luecke. Bei einem Wurf ohne
gefallenen Kegel steigt er um eins, die Summe bleibt stehen. Damit laesst sich
unterscheiden, was sonst gleich aussieht: ein echter Nullwurf und ein Wurf,
den es nie gab. Der Nutzer dazu: *"bei einem Fehlwurf steht da ja auch eine 0
und Wurfnummer geht um 1 hoch, und die Summe steigt halt eben nicht."*

WAS DIESES MODUL NICHT TUT

Es korrigiert nichts. Kein Wurf wird durch die Gegenprobe veraendert,
verworfen oder erzeugt; die Lampen behalten ihr Hoheitsrecht. Das Modul
schreibt auf, wer wem widerspricht, und zaehlt es zusammen.

Der Grund ist derselbe wie ueberall in diesem Projekt: erst messen, dann
bauen. Ob die Kegelziffer haeufiger recht hat als die Lampen, ist eine
BEHAUPTUNG, solange es niemand ausgezaehlt hat -- und eine Korrektur auf
Verdacht kann mehr kaputtmachen, als sie heilt. Zeigen die Zahlen, dass ein
Zeuge dem anderen ueberlegen ist, ist der Umbau eine Kleinigkeit.

DIE URTEILE

    einig                Lampen, Ziffer und Summendifferenz stimmen ueberein
    einig_ohne_summe     Lampen und Ziffer stimmen, die Summe schweigt
    ziffer_falsch        Summe stuetzt die LAMPEN, die Ziffer weicht ab
    lampen_verdaechtig   Summe stuetzt die ZIFFER, die Lampen weichen ab
    strittig             Lampen und Ziffer widersprechen sich, und die Summe
                         haette entscheiden koennen -- war aber nicht lesbar
    unklar               die Summe stuetzt keinen von beiden
    wurf_fehlt           die Wurfnummer springt um mehr als eins
    wurf_unbestaetigt    die Wurfnummer steht still -- die Anlage hat keinen
                         Wurf gezaehlt, wir aber schon
    nur_lampen           weder Ziffer noch Summe gelesen: nichts zu vergleichen

GEFUEHRTES LESEN DER SUMME (Nutzer, 2026-09-15): *"gerade standen wir bei
0172 -> jetzt melden Ziffer und Lampen eine 3 -> sicher dass du hier eine 8176
melden willst und nicht eher eine 0175?"* Die Summe wird deshalb nicht mehr als
blosse Zahl uebernommen, sondern durch `gefuehrtes_lesen.Summenspur` gereicht.
Die Spur kennt die Systematik -- die Summe beginnt bei null, faellt nie, steigt
je Wurf um hoechstens `pin_count` -- und loest damit unlesbare Stellen auf,
ohne die Lampen zu fragen.

Fuer die Gegenprobe zaehlt dabei nur eines: ob die Lampen GEBRAUCHT wurden.
War die Lesung aus sich heraus eindeutig, bleibt die Summe ein eigener Zeuge.
Musste die Erwartung waehlen, ist sie eine Buchung und kein Zeuge mehr -- ihre
Differenz stimmt dann zwangslaeufig mit den Lampen ueberein und beweist nichts.
`_Offen.summe_unabhaengig` haelt das auseinander.

DIE SUMME IST DER SCHIEDSRICHTER, NICHT DIE GRUNDLAGE. GEMESSEN ueber 57
Wuerfe des Hallenmitschnitts, wie oft jede Quelle ueberhaupt vorlag:

    Lampen         57 von 57
    Kegelziffer    56 von 57
    Wurfnummer     40 von 57
    Summe           2 von 57

Ein Urteil, das ohne Summe schweigt, schwiege dort in 95 % der Faelle. Die
haeufigste Gegenprobe ist deshalb Lampen gegen Kegelziffer; die Summe tritt
hinzu, wenn die beiden sich uneinig sind -- oder wenn sie beide bestaetigt
werden sollen.

`lampen_verdaechtig` beziffert, wie oft ein gebuchtes Ergebnis von zwei
unabhaengigen Quellen gemeinsam bestritten wird. `wurf_unbestaetigt` zaehlt
Wuerfe, die es womoeglich gar nicht gab -- die Signatur eines Phantomwurfs.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from kegel_cv.analysis.gefuehrtes_lesen import (EINDEUTIG, GEFUEHRT, STUMM,
                                                UNMOEGLICH, VERANKERT,
                                                WIDERSPRUCH, Summenspur)

log = logging.getLogger(__name__)

EINIG = "einig"
ZIFFER_FALSCH = "ziffer_falsch"
LAMPEN_VERDAECHTIG = "lampen_verdaechtig"
UNKLAR = "unklar"
WURF_FEHLT = "wurf_fehlt"
WURF_UNBESTAETIGT = "wurf_unbestaetigt"
EINIG_OHNE_SUMME = "einig_ohne_summe"
STRITTIG = "strittig"
NUR_LAMPEN = "nur_lampen"

# Urteile, die etwas ueber das ERGEBNIS sagen und deshalb ins Protokoll
# gehoeren. "Ziffer falsch" ist haeufig und folgenlos -- dort waere es Rauschen.
MELDENSWERT = (LAMPEN_VERDAECHTIG, WURF_UNBESTAETIGT, WURF_FEHLT,
               STRITTIG)


@dataclass
class Befund:
    """Was die Gegenprobe ueber EINEN Wurf sagt.

    Sie faellt erst, wenn der NAECHSTE Wurf derselben Bahn vorliegt -- vorher
    fehlt die zweite Summe.
    """

    bahn: int
    wurf: int
    frame: int | None
    lampen: int
    ziffer: int | None
    summe_vorher: int | None
    summe_danach: int | None
    nummer_vorher: int | None
    nummer_danach: int | None
    urteil: str
    # UNKLARE LAMPEN. Die in der AUSGANGSLAGE ist die gefaehrlichere: Beim
    # Abraeumen wird sie abgezogen, obwohl niemand weiss, ob der Kegel lag
    # (BUG-027, Bahn 2 Wurf 21 -- 5 gebucht, Ziffer und Summe sagten 4).
    lampen_unklar: int = 0
    grundlage_unklar: int | None = None
    bemerkung: str = ""
    # Hat der Fehlwurfzaehler getan, was er bei diesem Ergebnis tun muesste?
    # "ja", "nein" oder "" (nicht auf beiden Seiten gelesen).
    fehlwurf_stimmt: str = ""

    @property
    def differenz(self) -> int | None:
        if self.summe_vorher is None or self.summe_danach is None:
            return None
        return self.summe_danach - self.summe_vorher

    def als_zeile(self) -> dict[str, object]:
        leer = lambda w: "" if w is None else w      # noqa: E731
        return {
            "Bahn": self.bahn,
            "Wurf": self.wurf,
            "Frame": leer(self.frame),
            "Lampen": self.lampen,
            "Ziffer": leer(self.ziffer),
            "SummeVorher": leer(self.summe_vorher),
            "SummeDanach": leer(self.summe_danach),
            "Differenz": leer(self.differenz),
            "NummerVorher": leer(self.nummer_vorher),
            "NummerDanach": leer(self.nummer_danach),
            "LampenUnklar": self.lampen_unklar,
            "GrundlageUnklar": leer(self.grundlage_unklar),
            "Fehlwurfzaehler": self.fehlwurf_stimmt,
            "Urteil": self.urteil,
            "Bemerkung": self.bemerkung,
        }


@dataclass
class _Offen:
    """Ein Wurf, dessen Gegenprobe noch auf den naechsten wartet."""

    wurf: int
    frame: int | None
    lampen: int
    ziffer: int | None
    summe: int | None
    nummer: int | None
    fehlwurf: int | None
    # Wie die Summe zustande kam (`gefuehrtes_lesen`) und ob sie als eigener
    # Zeuge auftreten darf. Eine aus den Lampen gefuehrte Summe darf die
    # Lampen nicht bestaetigen -- sonst zaehlte eine Messung doppelt.
    summe_art: str = "roh"
    summe_unabhaengig: bool = True
    # Unklare Kegellampen -- im Ergebnis und in der Ausgangslage (BUG-027).
    lampen_unklar: int = 0
    grundlage_unklar: int | None = None


@dataclass
class Gegenprobe:
    """Sammelt Befunde ueber alle Bahnen. Zustandsbehaftet je Bahn."""

    pin_count: int = 9
    _offen: dict[int, _Offen] = field(default_factory=dict)
    _spuren: dict[int, Summenspur] = field(default_factory=dict)
    befunde: list[Befund] = field(default_factory=list)

    def spur(self, bahn: int) -> Summenspur:
        """Die Summenspur einer Bahn -- je Bahn eine eigene (Regel 3)."""
        if bahn not in self._spuren:
            self._spuren[bahn] = Summenspur(pin_count=self.pin_count)
        return self._spuren[bahn]

    def nimm(self, wurf, summen_lesung=None) -> Befund | None:
        """Nimmt einen Wurf entgegen und schliesst den vorherigen ab.

        Args:
            wurf: das gebuchte Ergebnis.
            summen_lesung: die Summe als `DigitReading` MIT Kandidaten je
                Stelle. Liegt sie vor, wird gefuehrt gelesen
                (`gefuehrtes_lesen`) statt den rohen Wert zu nehmen: Die
                Systematik -- beginnt bei null, faellt nie, steigt je Wurf um
                hoechstens `pin_count` -- loest unlesbare Stellen auf und
                verwirft Lesungen, die es nicht gegeben haben kann.

        Rueckgabe ist der Befund ueber den VORHERIGEN Wurf derselben Bahn --
        oder None, wenn es keinen gab.
        """
        vorher = self._offen.get(wurf.lane)
        summe, art, unabhaengig = self._summe(wurf, vorher, summen_lesung)
        jetzt = _Offen(
            wurf=wurf.throw_number,
            frame=wurf.source_frame,
            lampen=wurf.pins_count,
            ziffer=wurf.displayed_pin_count,
            summe=summe,
            nummer=wurf.displayed_throw_number,
            fehlwurf=wurf.displayed_foul_count,
            summe_art=art,
            summe_unabhaengig=unabhaengig,
            lampen_unklar=getattr(wurf, "lamps_unknown", 0) or 0,
            grundlage_unklar=getattr(wurf, "baseline_unknown", None),
        )
        self._offen[wurf.lane] = jetzt
        if vorher is None:
            return None
        urteil, bemerkung = self._urteil(vorher, jetzt)
        befund = Befund(
            bahn=wurf.lane, wurf=vorher.wurf, frame=vorher.frame,
            lampen=vorher.lampen, ziffer=vorher.ziffer,
            summe_vorher=vorher.summe, summe_danach=jetzt.summe,
            nummer_vorher=vorher.nummer, nummer_danach=jetzt.nummer,
            urteil=urteil, bemerkung=bemerkung,
            lampen_unklar=vorher.lampen_unklar,
            grundlage_unklar=vorher.grundlage_unklar,
            fehlwurf_stimmt=self._fehlwurf(vorher, jetzt))
        self.befunde.append(befund)
        return befund

    def _summe(self, wurf, vorher, lesung) -> tuple[int | None, str, bool]:
        """Was gilt als Summe dieses Wurfs -- und was ist sie wert?

        Ohne Lesung mit Kandidaten bleibt es beim rohen Wert; das ist der
        bisherige Zustand und aendert nichts.

        Mit Lesung entscheidet die Spur. Sie bekommt zwei Hinweise:

        * die WURFNUMMER der Tafel -- nur so kann die Spur mitten in ein
          laufendes Spiel einsteigen, statt jeden Stand oberhalb der selbst
          gezaehlten Wuerfe fuer unmoeglich zu halten.
        * die Kegel des VORHERIGEN Wurfs als Erwartung. Die Tafel traegt das
          Ergebnis verspaetet nach; zum Meldezeitpunkt steht dort der Stand
          nach dem Wurf davor.
        """
        if lesung is None or not getattr(lesung, "digits", ()):
            return wurf.displayed_total, "roh", True

        spur = self.spur(wurf.lane)
        spur.kennt_wurfnummer(wurf.displayed_throw_number)
        gefallen = None if vorher is None else vorher.lampen
        deutung = spur.deute(lesung, gefallen=gefallen)
        if not deutung.brauchbar:
            return None, deutung.art, False
        return deutung.wert, deutung.art, deutung.unabhaengig

    def _fehlwurf(self, a: _Offen, b: _Offen) -> str:
        """Hat der Fehlwurfzaehler getan, was er tun muesste?

        Er steigt bei einem Wurf ohne gefallenen Kegel um eins und bleibt
        sonst stehen. Damit ist er der einzige Zeuge, der einen echten
        Nullwurf von einem Wurf unterscheidet, den es nie gab: Bei beiden
        bleibt die Summe stehen.
        """
        if a.fehlwurf is None or b.fehlwurf is None:
            return ""
        erwartet = 1 if a.lampen == 0 else 0
        return "ja" if (b.fehlwurf - a.fehlwurf) == erwartet else "nein"

    def _urteil(self, a: _Offen, b: _Offen) -> tuple[str, str]:
        # DIE WURFNUMMER ZUERST -- sie sagt, OB geworfen wurde. Ohne diese
        # Frage sind alle weiteren sinnlos: Liegt ein ungesehener Wurf
        # dazwischen, gehoert die Summendifferenz nicht zu EINEM Ergebnis.
        if a.nummer is not None and b.nummer is not None:
            sprung = b.nummer - a.nummer
            # Ein Rueckfall auf 0 oder 1 ist der Spielwechsel, kein Fehler.
            if b.nummer > 1 and sprung > 1:
                return (WURF_FEHLT,
                        f"Wurfnummer springt {a.nummer} -> {b.nummer}, "
                        f"{sprung - 1} Wurf/Wuerfe fehlen")
            if sprung == 0:
                zusatz = ""
                if a.fehlwurf is not None and b.fehlwurf is not None:
                    zusatz = (", Fehlwurfzaehler ebenfalls unveraendert"
                              if b.fehlwurf == a.fehlwurf
                              else ", aber der Fehlwurfzaehler stieg")
                return (WURF_UNBESTAETIGT,
                        f"Wurfnummer bleibt bei {a.nummer}{zusatz}")

        d = None if (a.summe is None or b.summe is None) else b.summe - a.summe
        # DIE SPRUNGGRENZE. Mehr als `pin_count` Kegel faellt kein Wurf,
        # weniger als null auch nicht. Ein Wert ausserhalb heisst, dass eine
        # der beiden Summen falsch gelesen wurde -- und eine unbrauchbare
        # Summe ist so gut wie keine. Sie darf dann nicht als Schiedsrichter
        # auftreten.
        #
        # EBENSO WENIG eine GEFUEHRTE Summe. Wurde sie aus der Erwartung
        # gewonnen -- also aus den Lampen --, stimmt ihre Differenz mit den
        # Lampen zwangslaeufig ueberein. Sie als Bestaetigung zu zaehlen
        # hiesse, eine Messung zweimal zu befragen und die Antwort fuer zwei
        # Zeugen zu halten (siehe `gefuehrtes_lesen`, "Die Richtung
        # entscheidet ueber die Ehrlichkeit").
        eigenstaendig = a.summe_unabhaengig and b.summe_unabhaengig
        brauchbar = (d is not None and 0 <= d <= self.pin_count
                     and eigenstaendig)

        if not brauchbar:
            if d is None:
                grund = "Summe nicht auf beiden Seiten gelesen"
            elif not eigenstaendig:
                gefuehrt = [k for k, o in (("vorher", a), ("danach", b))
                            if not o.summe_unabhaengig]
                grund = (f"Summe {'/'.join(gefuehrt)} gefuehrt gelesen, "
                         "kein eigener Zeuge")
            else:
                grund = (f"Summensprung {d} liegt ausserhalb "
                         f"0..{self.pin_count}, unbrauchbar")
            if a.ziffer is None:
                return (NUR_LAMPEN, grund + ", auch keine Kegelziffer")
            if a.ziffer == a.lampen:
                return (EINIG_OHNE_SUMME,
                        f"Lampen und Ziffer sagen beide {a.lampen}; " + grund)
            return (STRITTIG,
                    f"Lampen sagen {a.lampen}, Ziffer {a.ziffer}; " + grund)

        passt_lampen = d == a.lampen
        passt_ziffer = a.ziffer is not None and d == a.ziffer

        if passt_lampen and a.ziffer is None:
            return (EINIG, "Kegelziffer nicht gelesen, Summe stuetzt die Lampen")
        if passt_lampen and passt_ziffer:
            return (EINIG, "")
        if passt_lampen:
            return (ZIFFER_FALSCH,
                    f"Summe sagt {d} wie die Lampen, die Ziffer sagt {a.ziffer}")
        if passt_ziffer:
            return (LAMPEN_VERDAECHTIG,
                    f"Summe sagt {d} wie die Ziffer, die Lampen sagen {a.lampen}")
        if a.ziffer is None:
            return (UNKLAR,
                    f"Summe sagt {d}, die Lampen sagen {a.lampen}, "
                    "keine Kegelziffer zum Vergleich")
        return (UNKLAR,
                f"Summe sagt {d}, Lampen {a.lampen}, Ziffer {a.ziffer} "
                "-- keiner bestaetigt")

    # -------------------------------------------------------------- Bericht

    def _unklare_lampen(self) -> list[str]:
        """Wie oft war eine Kegellampe unklar -- und wo.

        Die Zahl gehoert in den Bericht, weil sie einen Fehler sichtbar macht,
        der sonst wie ein richtiges Ergebnis aussieht: Eine unklare Lampe
        faellt aus der Kegelliste und wirkt wie "steht". Beim ABRAEUMEN ist
        das Ergebnis die Differenz zweier Messungen -- eine unklare Lampe in
        der AUSGANGSLAGE wird dann abgezogen, obwohl niemand weiss, ob der
        Kegel lag. Genau so entstand BUG-027 (Bahn 2 Wurf 21: 5 gebucht,
        Ziffer und Summe sagten 4).
        """
        mit_ergebnis = [b for b in self.befunde if b.lampen_unklar]
        mit_grundlage = [b for b in self.befunde if b.grundlage_unklar]
        if not mit_ergebnis and not mit_grundlage:
            return []
        zeilen = ["  Unklare Kegellampen:"]
        zeilen.append(f"    im Ergebnis      {len(mit_ergebnis):4d} von "
                      f"{len(self.befunde)} Wuerfen")
        zeilen.append(f"    in der Grundlage {len(mit_grundlage):4d} von "
                      f"{len(self.befunde)} Wuerfen  <- schlaegt beim "
                      f"Abraeumen auf den Punktestand durch")
        for b in mit_grundlage[:6]:
            zeilen.append(f"      Bahn {b.bahn} Wurf {b.wurf} (Frame "
                          f"{b.frame}): {b.grundlage_unklar} unklar, "
                          f"Lampen {b.lampen}, Ziffer {b.ziffer}")
        if len(mit_grundlage) > 6:
            zeilen.append(f"      ... und {len(mit_grundlage) - 6} weitere")
        return zeilen

    def _summenzeilen(self) -> list[str]:
        """Was das gefuehrte Lesen mit den Summen gemacht hat -- je Bahn.

        Die Zeile gehoert in den Bericht, weil sie zwei Dinge auseinanderhaelt,
        die im Urteil beide als "keine Summe" erscheinen: eine Summe, die nicht
        lesbar war, und eine, die gelesen aber verworfen wurde, weil es sie
        nicht gegeben haben kann. Das Zweite zeigt auf ein Feld, das nicht
        stimmt -- GEMESSEN auf Bahn 2 des Hallenmitschnitts.
        """
        aktive = {b: s for b, s in sorted(self._spuren.items()) if s.zaehler}
        if not aktive:
            return []
        zeilen = ["  Summenlesung je Bahn "
                  "(eigenstaendig / gefuehrt / verworfen):"]
        for bahn, spur in aktive.items():
            z = spur.zaehler
            eigen = z.get(EINDEUTIG, 0) + z.get(VERANKERT, 0)
            verworfen = z.get(UNMOEGLICH, 0) + z.get(WIDERSPRUCH, 0)
            stumm = z.get(STUMM, 0)
            zeilen.append(
                f"    Bahn {bahn}: {eigen} eigenstaendig, "
                f"{z.get(GEFUEHRT, 0)} gefuehrt, {verworfen} verworfen, "
                f"{stumm} nicht gelesen; Stand zuletzt {spur.stand}")
        return zeilen

    def zusammenfassung(self) -> dict[str, int]:
        return dict(Counter(b.urteil for b in self.befunde))

    def bericht(self) -> str:
        """Menschenlesbare Bilanz -- das, was am Ende zaehlt."""
        if not self.befunde:
            return "Gegenprobe: keine abgeschlossenen Wuerfe."
        zahlen = self.zusammenfassung()
        gesamt = len(self.befunde)
        zeilen = [f"Gegenprobe ueber {gesamt} Wuerfe "
                  f"(jeder bestaetigt durch den naechsten):"]
        for name, klartext in (
            (EINIG, "Lampen, Ziffer und Summe einig"),
            (EINIG_OHNE_SUMME, "Lampen und Ziffer einig, Summe schweigt"),
            (ZIFFER_FALSCH, "Summe stuetzt die LAMPEN, Ziffer weicht ab"),
            (LAMPEN_VERDAECHTIG, "Summe stuetzt die ZIFFER, Lampen weichen ab"),
            (STRITTIG, "Lampen gegen Ziffer, kein Schiedsrichter"),
            (UNKLAR, "kein Zeuge bestaetigt"),
            (WURF_FEHLT, "Wurfnummer springt -- Wurf fehlt"),
            (WURF_UNBESTAETIGT, "Wurfnummer steht still -- Wurf fraglich"),
            (NUR_LAMPEN, "nur die Lampen -- nichts zu vergleichen"),
        ):
            n = zahlen.get(name, 0)
            zeilen.append(f"  {klartext:46s} {n:5d}  ({100 * n / gesamt:4.1f} %)")

        geprueft = [b for b in self.befunde if b.fehlwurf_stimmt]
        if geprueft:
            passend = sum(1 for b in geprueft if b.fehlwurf_stimmt == "ja")
            zeilen.append(
                f"  {'Fehlwurfzaehler passt zum Ergebnis':46s} {passend:5d}  "
                f"({100 * passend / len(geprueft):4.1f} % von "
                f"{len(geprueft)} lesbaren)")

        zeilen.extend(self._unklare_lampen())
        zeilen.extend(self._summenzeilen())

        strittig = [b for b in self.befunde
                    if b.urteil in (LAMPEN_VERDAECHTIG, WURF_UNBESTAETIGT,
                                    STRITTIG)]
        if strittig:
            zeilen.append("  Wuerfe, denen andere Quellen widersprechen:")
            for b in strittig[:10]:
                zeilen.append(f"    Bahn {b.bahn} Wurf {b.wurf} "
                              f"(Frame {b.frame}): {b.bemerkung}")
            if len(strittig) > 10:
                zeilen.append(f"    ... und {len(strittig) - 10} weitere")
        return "\n".join(zeilen)
