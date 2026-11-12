"""Ein kleiner Ersatz fuer pydantic -- gerade so viel, wie dieses Projekt nutzt.

WARUM ES IHN GIBT

pydantic v2 laeuft nicht auf Android. Sein Kern (`pydantic-core`) ist in Rust
geschrieben, und Chaquopy liefert nur reine Python-Pakete plus eigene native
Uebersetzungen. Damit haette der Erkennungskern auf dem Telefon nicht einmal
importiert werden koennen.

Die Alternativen waren schlechter:

* **pydantic v1** ist reines Python, hat aber eine andere Schnittstelle
  (`validator`, `.dict()`, `parse_obj`). Man entwickelte gegen v2 und lieferte
  v1 aus -- zwei Verhalten, und genau das soll dieses Projekt nicht haben.
* **Konfiguration als fertiges JSON ausliefern** loest die Kalibrierungen nicht,
  die auf dem Geraet gelesen und geschrieben werden muessen.

Deshalb steht die Pruefung jetzt hier. Sie ist klein, weil die genutzte
Oberflaeche klein ist -- gemessen am 2026-09-14 ueber beide betroffenen
Dateien: 24 Klassen, `Field` mit Wertebereichen, acht Pruefer, dazu
`model_dump`, `model_validate` und `model_copy`.

WAS SIE TUT UND WAS NICHT

Sie wandelt Werte in den angegebenen Typ, prueft Wertebereiche und ruft die
Pruefmethoden. Sie erzeugt KEINE Schemata, KEINE JSON-Schemas, KEINE
Serialisierungsregeln -- all das wurde hier nie gebraucht.

Unbekannte Schluessel werden **stillschweigend uebergangen**, wie pydantic es
voreingestellt auch tut. Das ist Absicht: Eine Konfigurationsdatei aus einem
aelteren Stand traegt womoeglich Schluessel, die es nicht mehr gibt, und darf
deshalb nicht unlesbar werden.

Zuweisungen nach dem Erzeugen werden NICHT geprueft -- auch das wie pydantic.
Tests und Werkzeuge setzen Werte direkt, und eine Pruefung dort wuerde nur
Reibung erzeugen, ohne einen bekannten Fehler zu verhindern.
"""

from __future__ import annotations

import copy
import typing
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

FEHLT = object()
"""Kein Vorgabewert -- das Feld muss angegeben werden."""


class Feld:
    """Vorgabewert und Wertebereich eines Feldes."""

    __slots__ = ("default", "default_factory", "ge", "gt", "le", "lt",
                 "min_length", "max_length", "exclude")

    def __init__(self, default: Any = FEHLT, *, default_factory=None,
                 ge=None, gt=None, le=None, lt=None,
                 min_length=None, max_length=None, exclude: bool = False) -> None:
        self.default = default
        self.default_factory = default_factory
        self.ge, self.gt, self.le, self.lt = ge, gt, le, lt
        self.min_length, self.max_length = min_length, max_length
        # Nicht mitschreiben: `project_root` und `config_path` beschreiben,
        # WOHER die Konfiguration kam -- sie gehoeren nicht in ihre Abschrift.
        self.exclude = exclude

    def vorgabe(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is FEHLT:
            return FEHLT
        # Tief kopieren: Ein gemeinsam benutzter Vorgabewert waere ein Fehler,
        # der erst auffaellt, wenn zwei Objekte sich gegenseitig aendern.
        return copy.deepcopy(self.default)

    def pruefe(self, name: str, wert: Any) -> None:
        if wert is None:
            # Ein nicht gesetztes Feld hat keinen Wertebereich zu verletzen.
            # `int | None = Field(default=None, ge=0)` heisst: WENN eine Zahl
            # dasteht, dann keine negative -- nicht, dass eine dastehen muss.
            # (pydantic haelt es genauso; gefunden am 2026-09-15 durch das
            # erste optionale Feld mit Grenzen, `AnlagenProfil.hue_min`.)
            return
        for grenze, zeichen, erfuellt in (
            (self.ge, ">=", lambda w, g: w >= g),
            (self.gt, ">", lambda w, g: w > g),
            (self.le, "<=", lambda w, g: w <= g),
            (self.lt, "<", lambda w, g: w < g),
        ):
            if grenze is not None and not erfuellt(wert, grenze):
                raise ValueError(f"{name}: {wert} muss {zeichen} {grenze} sein")
        if self.min_length is not None and len(wert) < self.min_length:
            raise ValueError(f"{name}: braucht mindestens {self.min_length} "
                             f"Eintraege, hat {len(wert)}")
        if self.max_length is not None and len(wert) > self.max_length:
            raise ValueError(f"{name}: hoechstens {self.max_length} Eintraege "
                             f"erlaubt, hat {len(wert)}")


def Field(default: Any = FEHLT, **grenzen) -> Feld:      # noqa: N802
    """Gleiche Schreibweise wie bei pydantic, damit die Schemata unveraendert
    bleiben konnten."""
    return Feld(default, **grenzen)


def field_validator(*namen: str):
    """Prueft EIN Feld, nachdem es gewandelt wurde.

    Die vorhandenen Schemata schreiben `@field_validator(...)` ueber
    `@classmethod`; der Dekorator bekommt dann bereits ein classmethod-Objekt.
    Weil sich daran keine Merkmale setzen lassen, wird es ausgepackt,
    markiert und neu verpackt.
    """
    def deko(fn):
        roh = fn.__func__ if isinstance(fn, (classmethod, staticmethod)) else fn
        roh._prueft_felder = namen
        return classmethod(roh)
    return deko


def model_validator(*, mode: str = "after"):
    """Prueft das ganze Objekt, nachdem alle Felder stehen.

    Nur `mode="after"` -- mehr wurde nie gebraucht. Die Methode bekommt `self`
    und gibt `self` zurueck.
    """
    if mode != "after":
        raise ValueError("nur mode='after' wird unterstuetzt")

    def deko(fn):
        fn._prueft_modell = True
        return fn
    return deko


def _ist_modell(typ: Any) -> bool:
    return isinstance(typ, type) and issubclass(typ, BaseModel)


def _wandle(wert: Any, typ: Any, pfad: str) -> Any:
    """Bringt einen Wert auf den angegebenen Typ -- oder sagt, warum nicht."""
    if typ is Any or typ is None:
        return wert

    herkunft = get_origin(typ)

    if herkunft is Literal:
        erlaubt = get_args(typ)
        if wert not in erlaubt:
            raise ValueError(f"{pfad}: {wert!r} ist keiner der erlaubten Werte "
                             f"{list(erlaubt)}")
        return wert

    if herkunft is typing.Union or str(herkunft) == "<class 'types.UnionType'>":
        moeglich = get_args(typ)
        if wert is None and type(None) in moeglich:
            return None
        letzter: Exception | None = None
        for kandidat in moeglich:
            if kandidat is type(None):
                continue
            try:
                return _wandle(wert, kandidat, pfad)
            except (ValueError, TypeError) as exc:
                letzter = exc
        raise ValueError(f"{pfad}: {wert!r} passt zu keinem der Typen "
                         f"{moeglich}" + (f" ({letzter})" if letzter else ""))

    if herkunft in (list, set, frozenset):
        (innen,) = get_args(typ) or (Any,)
        if not isinstance(wert, (list, tuple, set, frozenset)):
            raise ValueError(f"{pfad}: erwartet eine Liste, bekommen "
                             f"{type(wert).__name__}")
        gewandelt = [_wandle(e, innen, f"{pfad}[{i}]")
                     for i, e in enumerate(wert)]
        return herkunft(gewandelt)

    if herkunft is tuple:
        teile = get_args(typ)
        if not isinstance(wert, (list, tuple)):
            raise ValueError(f"{pfad}: erwartet eine Folge, bekommen "
                             f"{type(wert).__name__}")
        if len(teile) == 2 and teile[1] is Ellipsis:
            return tuple(_wandle(e, teile[0], f"{pfad}[{i}]")
                         for i, e in enumerate(wert))
        if len(teile) != len(wert):
            raise ValueError(f"{pfad}: braucht genau {len(teile)} Werte, "
                             f"hat {len(wert)}")
        return tuple(_wandle(e, t, f"{pfad}[{i}]")
                     for i, (e, t) in enumerate(zip(wert, teile)))

    if herkunft is dict:
        schluesseltyp, werttyp = get_args(typ) or (Any, Any)
        if not isinstance(wert, dict):
            raise ValueError(f"{pfad}: erwartet ein Mapping, bekommen "
                             f"{type(wert).__name__}")
        return {_wandle(k, schluesseltyp, f"{pfad}.{k}"):
                _wandle(v, werttyp, f"{pfad}.{k}") for k, v in wert.items()}

    if _ist_modell(typ):
        if isinstance(wert, typ):
            return wert
        if isinstance(wert, dict):
            return typ(**wert)
        raise ValueError(f"{pfad}: erwartet {typ.__name__} oder ein Mapping")

    if typ is Path:
        if isinstance(wert, Path):
            return wert
        if isinstance(wert, str):
            return Path(wert)
        raise ValueError(f"{pfad}: erwartet einen Pfad")

    if typ is bool:
        if isinstance(wert, bool):
            return wert
        raise ValueError(f"{pfad}: erwartet true oder false, bekommen {wert!r}")

    if typ is int:
        # `bool` ist in Python ein `int`; als Zahl durchzulassen waere fast
        # immer ein Tippfehler in der Konfiguration.
        if isinstance(wert, bool):
            raise ValueError(f"{pfad}: erwartet eine ganze Zahl, bekommen "
                             f"{wert!r}")
        if isinstance(wert, int):
            return wert
        if isinstance(wert, float) and wert.is_integer():
            return int(wert)
        raise ValueError(f"{pfad}: erwartet eine ganze Zahl, bekommen {wert!r}")

    if typ is float:
        if isinstance(wert, bool):
            raise ValueError(f"{pfad}: erwartet eine Zahl, bekommen {wert!r}")
        if isinstance(wert, (int, float)):
            return float(wert)
        raise ValueError(f"{pfad}: erwartet eine Zahl, bekommen {wert!r}")

    if typ is str:
        if isinstance(wert, str):
            return wert
        raise ValueError(f"{pfad}: erwartet Text, bekommen {type(wert).__name__}")

    if isinstance(typ, type) and isinstance(wert, typ):
        return wert
    raise ValueError(f"{pfad}: {wert!r} passt nicht zu {typ}")


class BaseModel:
    """Basisklasse mit Typwandlung, Wertebereichen und Pruefmethoden."""

    __slots__ = ("__dict__",)

    _felder: dict[str, Feld]
    _typen: dict[str, Any] | None = None

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)
        felder: dict[str, Feld] = {}
        for basis in reversed(cls.__mro__[1:]):
            felder.update(getattr(basis, "_felder", {}) or {})
        for name in cls.__dict__.get("__annotations__", {}):
            if name.startswith("_"):
                continue
            vorgabe = cls.__dict__.get(name, FEHLT)
            felder[name] = (vorgabe if isinstance(vorgabe, Feld)
                            else Feld(vorgabe))
        cls._felder = felder
        cls._typen = None            # erst bei Bedarf aufloesen

    @classmethod
    def _hole_typen(cls) -> dict[str, Any]:
        """Annotationen aufloesen -- erst jetzt, nicht beim Erzeugen der Klasse.

        Die Schemata stehen unter `from __future__ import annotations`, ihre
        Annotationen sind also Zeichenketten. Frueh aufgeloest wuerden
        Verweise auf spaeter definierte Klassen scheitern.
        """
        if cls._typen is None:
            cls._typen = typing.get_type_hints(cls)
        return cls._typen

    def __init__(self, **werte: Any) -> None:
        typen = self._hole_typen()
        for name, feld in self._felder.items():
            if name in werte:
                roh = werte[name]
            else:
                roh = feld.vorgabe()
                if roh is FEHLT:
                    raise ValueError(
                        f"{type(self).__name__}: Feld '{name}' fehlt")
                object.__setattr__(self, name, roh)
                continue
            wert = _wandle(roh, typen.get(name, Any),
                           f"{type(self).__name__}.{name}")
            feld.pruefe(f"{type(self).__name__}.{name}", wert)
            object.__setattr__(self, name, wert)

        for name in self._felder:
            for pruefer in self._feldpruefer(name):
                gepruefr = pruefer(type(self), getattr(self, name))
                if gepruefr is not None:
                    object.__setattr__(self, name, gepruefr)

        for pruefer in self._modellpruefer():
            pruefer(self)

    @classmethod
    def _feldpruefer(cls, name: str):
        for klasse in cls.__mro__:
            for eintrag in vars(klasse).values():
                fn = getattr(eintrag, "__func__", None)
                if fn is not None and name in getattr(fn, "_prueft_felder", ()):
                    yield fn

    @classmethod
    def _modellpruefer(cls):
        gesehen = set()
        for klasse in cls.__mro__:
            for schluessel, eintrag in vars(klasse).items():
                if (getattr(eintrag, "_prueft_modell", False)
                        and schluessel not in gesehen):
                    gesehen.add(schluessel)
                    yield eintrag

    # ------------------------------------------------------------- Umgang

    @classmethod
    def model_validate(cls, daten: Any):
        if isinstance(daten, cls):
            return daten
        if not isinstance(daten, dict):
            raise ValueError(f"{cls.__name__}: erwartet ein Mapping")
        return cls(**daten)

    def model_dump(self) -> dict[str, Any]:
        return {name: _als_daten(getattr(self, name))
                for name, feld in self._felder.items() if not feld.exclude}

    def model_copy(self, *, update: dict[str, Any] | None = None,
                   deep: bool = False):
        """Kopie mit geaenderten Feldern.

        Wie bei pydantic wird dabei NICHT geprueft -- die vorhandenen
        Aufrufstellen verlassen sich darauf (siehe `roi_feinschliff`: Ein
        Bereich darf voruebergehend ueber den Tafelrand hinausragen und wird
        erst beim Speichern beanstandet).
        """
        neu = object.__new__(type(self))
        for name in self._felder:
            wert = getattr(self, name)
            object.__setattr__(neu, name,
                               copy.deepcopy(wert) if deep else wert)
        for name, wert in (update or {}).items():
            object.__setattr__(neu, name, wert)
        return neu

    def __eq__(self, andere: object) -> bool:
        if type(andere) is not type(self):
            return NotImplemented
        return all(getattr(self, n) == getattr(andere, n)
                   for n in self._felder)

    def __repr__(self) -> str:
        teile = ", ".join(f"{n}={getattr(self, n)!r}" for n in self._felder)
        return f"{type(self).__name__}({teile})"


def _als_daten(wert: Any) -> Any:
    if isinstance(wert, BaseModel):
        return wert.model_dump()
    if isinstance(wert, (list, tuple, set, frozenset)):
        return [_als_daten(e) for e in wert]
    if isinstance(wert, dict):
        return {k: _als_daten(v) for k, v in wert.items()}
    if isinstance(wert, Path):
        return str(wert)
    return wert
