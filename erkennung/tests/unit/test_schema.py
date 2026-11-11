"""Die projekteigene Feldpruefung -- Ersatz fuer pydantic.

WARUM DIESE TESTS BESONDERS WICHTIG SIND: Hier wurde eine erprobte
Fremdbibliothek durch eigenen Code ersetzt, und dieser Code traegt JEDEN
Schwellwert des Projekts. Ein Fehler darin verstellt keine einzelne Zahl,
sondern verschiebt still alle.

Der Anlass war Android: pydantic v2 hat einen Kern in Rust, und Chaquopy
liefert nur reine Python-Pakete. Ohne diesen Ersatz haette der Erkennungskern
auf dem Telefon nicht einmal importiert werden koennen.

Geprueft wird gegen das Verhalten, das die Schemata voraussetzen -- nicht
gegen alles, was pydantic kann.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from kegel_cv.schema import (BaseModel, Field, field_validator,
                             model_validator)


class Innen(BaseModel):
    zahl: int = 3
    text: str = "hallo"


class Aussen(BaseModel):
    innen: Innen = Field(default_factory=Innen)
    liste: list[int] = Field(default_factory=list)
    quote: float = Field(default=0.5, ge=0.0, le=1.0)
    modus: Literal["a", "b"] = "a"
    wahl: int | None = None
    pfad: Path | None = None


class TestVorgabewerte:
    def test_ohne_angaben_gelten_die_vorgaben(self):
        a = Aussen()
        assert a.quote == 0.5
        assert a.innen.zahl == 3
        assert a.liste == []

    def test_jedes_objekt_bekommt_seine_eigene_liste(self):
        """Ein gemeinsam benutzter veraenderlicher Vorgabewert ist ein Fehler,
        der erst auffaellt, wenn zwei Objekte sich gegenseitig aendern."""
        a, b = Aussen(), Aussen()
        a.liste.append(1)
        assert b.liste == []

    def test_auch_verschachtelte_vorgaben_sind_eigenstaendig(self):
        a, b = Aussen(), Aussen()
        a.innen.zahl = 99
        assert b.innen.zahl == 3

    def test_ein_feld_ohne_vorgabe_muss_angegeben_werden(self):
        class Pflicht(BaseModel):
            wert: int

        with pytest.raises(ValueError, match="wert"):
            Pflicht()
        assert Pflicht(wert=7).wert == 7


class TestTypwandlung:
    def test_ganze_zahl_wird_zu_gleitkomma(self):
        """YAML schreibt `2` auch dort, wo eine Kommazahl gemeint ist."""
        assert isinstance(Aussen(quote=1).quote, float)

    def test_gleitkomma_ohne_rest_wird_zu_ganzer_zahl(self):
        assert Innen(zahl=4.0).zahl == 4

    def test_gleitkomma_mit_rest_wird_abgelehnt(self):
        with pytest.raises(ValueError, match="ganze Zahl"):
            Innen(zahl=4.5)

    def test_wahrheitswert_ist_keine_zahl(self):
        """`True` ist in Python ein `int`. Als Zahl durchzulassen waere in
        einer Konfiguration fast immer ein Tippfehler."""
        with pytest.raises(ValueError):
            Innen(zahl=True)

    def test_verschachteltes_mapping_wird_zum_objekt(self):
        a = Aussen(innen={"zahl": 9})
        assert isinstance(a.innen, Innen)
        assert a.innen.zahl == 9 and a.innen.text == "hallo"

    def test_liste_wird_elementweise_gewandelt(self):
        assert Aussen(liste=[1, 2.0, 3]).liste == [1, 2, 3]

    def test_tupel_fester_laenge(self):
        class MitTupel(BaseModel):
            rect: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

        m = MitTupel(rect=[1, 2, 3, 4])
        assert m.rect == (1.0, 2.0, 3.0, 4.0)
        with pytest.raises(ValueError, match="genau 4"):
            MitTupel(rect=[1, 2, 3])

    def test_optional_nimmt_none(self):
        assert Aussen(wahl=None).wahl is None
        assert Aussen(wahl=5).wahl == 5

    def test_pfad_aus_text(self):
        a = Aussen(pfad="a/b")
        assert isinstance(a.pfad, Path)

    def test_literal_laesst_nur_erlaubtes_zu(self):
        assert Aussen(modus="b").modus == "b"
        with pytest.raises(ValueError, match="erlaubten Werte"):
            Aussen(modus="c")

    def test_text_wo_zahl_erwartet_wird(self):
        with pytest.raises(ValueError, match="Zahl"):
            Aussen(quote="viel")


class TestWertebereiche:
    def test_untergrenze(self):
        with pytest.raises(ValueError, match=">="):
            Aussen(quote=-0.1)

    def test_obergrenze(self):
        with pytest.raises(ValueError, match="<="):
            Aussen(quote=1.1)

    def test_die_grenzen_selbst_sind_erlaubt(self):
        assert Aussen(quote=0.0).quote == 0.0
        assert Aussen(quote=1.0).quote == 1.0

    def test_echt_groesser(self):
        class Streng(BaseModel):
            wert: float = Field(default=1.0, gt=0.0)

        with pytest.raises(ValueError, match=">"):
            Streng(wert=0.0)

    def test_laenge(self):
        class MitLaenge(BaseModel):
            ecken: list[list[float]] = Field(default_factory=list,
                                             min_length=4, max_length=4)

        assert len(MitLaenge(ecken=[[0, 0]] * 4).ecken) == 4
        with pytest.raises(ValueError, match="mindestens 4"):
            MitLaenge(ecken=[[0, 0]] * 3)
        with pytest.raises(ValueError, match="hoechstens 4"):
            MitLaenge(ecken=[[0, 0]] * 5)


class TestOptionaleFelderMitGrenzen:
    """GEFUNDEN 2026-09-15 am ersten solchen Feld (`AnlagenProfil.hue_min`):
    Der Wertebereich wurde auch auf `None` angewandt und warf einen
    TypeError. `int | None = Field(default=None, ge=0)` heisst: WENN eine Zahl
    dasteht, dann keine negative -- nicht, dass eine dastehen muss."""

    class MitGrenze(BaseModel):
        zahl: int | None = Field(default=None, ge=0, le=179)

    def test_none_verletzt_keine_grenze(self):
        assert self.MitGrenze().zahl is None
        assert self.MitGrenze(zahl=None).zahl is None

    def test_die_grenze_gilt_weiterhin_fuer_werte(self):
        assert self.MitGrenze(zahl=5).zahl == 5
        with pytest.raises(ValueError, match=">="):
            self.MitGrenze(zahl=-1)
        with pytest.raises(ValueError, match="<="):
            self.MitGrenze(zahl=200)


class TestPruefmethoden:
    def test_feldpruefer_laeuft_und_darf_ersetzen(self):
        class MitFeldpruefer(BaseModel):
            name: str = "x"

            @field_validator("name")
            @classmethod
            def _gross(cls, v):
                if not v:
                    raise ValueError("name darf nicht leer sein")
                return v.upper()

        assert MitFeldpruefer(name="ab").name == "AB"
        with pytest.raises(ValueError, match="leer"):
            MitFeldpruefer(name="")

    def test_modellpruefer_sieht_alle_felder(self):
        class MitModellpruefer(BaseModel):
            unten: float = 1.0
            oben: float = 2.0

            @model_validator(mode="after")
            def _reihenfolge(self):
                if self.unten >= self.oben:
                    raise ValueError("unten muss kleiner als oben sein")
                return self

        MitModellpruefer(unten=1.0, oben=2.0)
        with pytest.raises(ValueError, match="kleiner"):
            MitModellpruefer(unten=3.0, oben=2.0)

    def test_nur_nach_dem_erzeugen(self):
        with pytest.raises(ValueError, match="mode='after'"):
            model_validator(mode="before")


class TestUmgangMitDatenSaetzen:
    def test_abschrift_ist_rein_und_verschachtelt(self):
        daten = Aussen(innen={"zahl": 5}, liste=[1, 2]).model_dump()
        assert daten["innen"] == {"zahl": 5, "text": "hallo"}
        assert daten["liste"] == [1, 2]
        import json
        json.dumps(daten)          # darf nicht werfen

    def test_ausgenommene_felder_fehlen_in_der_abschrift(self):
        class MitGeheimnis(BaseModel):
            sichtbar: int = 1
            woher: Path = Field(default_factory=Path.cwd, exclude=True)

        assert "woher" not in MitGeheimnis().model_dump()

    def test_hin_und_zurueck(self):
        a = Aussen(innen={"zahl": 5}, quote=0.25, modus="b")
        assert Aussen.model_validate(a.model_dump()) == a

    def test_unbekannte_schluessel_werden_uebergangen(self):
        """Eine Konfigurationsdatei aus einem aelteren Stand traegt womoeglich
        Schluessel, die es nicht mehr gibt -- sie darf davon nicht unlesbar
        werden. `occlusion_off_fraction` ist genau so ein Fall."""
        a = Aussen.model_validate({"quote": 0.2, "gibt_es_nicht_mehr": 7})
        assert a.quote == 0.2

    def test_kopie_ist_eigenstaendig(self):
        a = Aussen(liste=[1])
        b = a.model_copy(deep=True)
        b.liste.append(2)
        assert a.liste == [1]

    def test_flache_kopie_teilt_die_verschachtelten_teile(self):
        a = Aussen()
        b = a.model_copy()
        assert b.innen is a.innen

    def test_kopie_mit_aenderung_prueft_nicht(self):
        """Absicht, und von den Aufrufstellen vorausgesetzt: In
        `roi_feinschliff` darf ein Bereich voruebergehend ueber den Tafelrand
        hinausragen und wird erst beim Speichern beanstandet."""
        a = Aussen().model_copy(update={"quote": 99.0})
        assert a.quote == 99.0


class TestGleichheit:
    def test_gleiche_werte_sind_gleich(self):
        assert Aussen(quote=0.3) == Aussen(quote=0.3)

    def test_verschiedene_werte_sind_verschieden(self):
        assert Aussen(quote=0.3) != Aussen(quote=0.4)

    def test_fremde_typen_sind_nicht_gleich(self):
        assert Aussen() != Innen()


class TestAmEchtenSchema:
    """Die eigentliche Probe: das Schema des Projekts selbst."""

    def test_die_konfiguration_laedt(self):
        from kegel_cv.config import load_config
        cfg = load_config()
        assert 0.0 <= cfg.detection.green.occlusion_edge_fraction <= 1.0
        assert cfg.detection.person_model.input_size > 0

    def test_eine_unmoegliche_hysterese_wird_abgelehnt(self):
        from kegel_cv.config.schema import GreenDetectionConfig
        with pytest.raises(ValueError, match="off_threshold"):
            GreenDetectionConfig(on_threshold=10.0, off_threshold=20.0)

    def test_ein_bereich_ohne_flaeche_wird_abgelehnt(self):
        from kegel_cv.calibration.model import Roi
        with pytest.raises(ValueError):
            Roi(name="x", rect=(0.1, 0.1, 0.0, 0.2))

    def test_kalibrierung_hin_und_zurueck(self, tmp_path):
        from kegel_cv.calibration.model import Calibration
        original = Calibration.load("data/calibrations/Fastlane.json")
        ziel = tmp_path / "k.json"
        original.save(ziel)
        wieder = Calibration.load(ziel)
        assert len(wieder.lanes) == len(original.lanes)
        assert wieder.lanes[0].rois[0].rect == original.lanes[0].rois[0].rect
