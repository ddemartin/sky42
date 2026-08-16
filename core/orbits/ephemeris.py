"""Dove stanno la Terra e il Sole. L'unico modulo che apre DE440s.

Il resto del codice non sa che esiste Skyfield: chiede un array di JD e riceve
un array di posizioni in AU, equatoriali ICRF, eliocentriche. Il giorno in cui
DE440s diventasse DE441 o Skyfield venisse sostituito, il confine è questo file.

Il kernel (32 MB) si scarica **una volta** e sta in `data/ephem/`. Passa da
`core/ingest/http.py` come qualunque altra cosa che entra dall'esterno, così
lascia la sua riga in `external_call` e la sua versione in `catalog_version`:
un'effemeride planetaria è un dato scaricato come gli altri, e fra due anni
«quale kernel stavamo usando» deve avere una risposta.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

from core import config

log = logging.getLogger("sky42.ephem")

# Obliquità media dell'eclittica a J2000 (IAU 2006), in gradi. È l'unico posto
# in cui compare: eclittica ed equatoriale si scambiano solo qui e nel
# positioner, che la importa da qui.
OBLIQUITY_J2000_DEG = 23.439291111111

_lock = threading.Lock()
_kernel = None          # oggetto Skyfield, caricato una volta sola
_timescale = None


def ensure_kernel(force: bool = False):
    """Scarica DE440s se manca. Restituisce il percorso locale.

    Non si chiama a ogni uso: `_load()` la invoca solo quando il file non c'è.
    Un servizio che parte senza rete deve poter funzionare su tutto ciò che non
    richiede effemeridi planetarie.
    """
    from core.db import init_db
    from core.ingest.http import fetch

    if config.DE440S_FILE.exists() and not force:
        return config.DE440S_FILE
    log.info("DE440s assente: lo scarico (32 MB, una volta sola)")
    # `fetch` scrive la versione nel database: se qualcuno arriva qui prima che
    # lo schema esista (un test, uno script), lo si crea invece di fallire.
    init_db()
    d = fetch("de440s", config.DE440S_URL, config.DE440S_FILE.name,
              force=force, dest_dir=config.EPHEM_DIR)
    return d.path


def _load():
    """Carica kernel e scala dei tempi una volta per processo.

    Il lock serve perché il primo accesso può arrivare da due richieste
    dell'interfaccia insieme, e aprire due volte 32 MB di kernel è uno spreco
    che si nota su un Mac mini.
    """
    global _kernel, _timescale
    if _kernel is not None:
        return _kernel, _timescale
    with _lock:
        if _kernel is None:
            from skyfield.api import load, load_file

            path = ensure_kernel()
            # `builtin=True`: la scala dei tempi di Skyfield è inclusa nel
            # pacchetto e non fa nessuna richiesta di rete. Un modulo di
            # calcolo che scarica file da solo, all'improvviso, no.
            _timescale = load.timescale(builtin=True)
            _kernel = load_file(str(path))
            log.info("DE440s caricato da %s", path)
    return _kernel, _timescale


def _positions(target: str, jd) -> np.ndarray:
    kernel, ts = _load()
    t = ts.tdb_jd(np.asarray(jd, dtype=float))
    # Eliocentrico e non baricentrico: i nostri elementi orbitali hanno il Sole
    # nell'origine, e mescolare le due origini sposta tutto di ~0.005 AU.
    vec = (kernel[target] - kernel["sun"]).at(t).position.au
    return np.moveaxis(np.asarray(vec, dtype=float), 0, -1)     # (..., 3)


def earth_equatorial(jd) -> np.ndarray:
    """Posizione della Terra rispetto al Sole, AU, equatoriale ICRF, forma (..., 3).

    È il centro della Terra: le correzioni topocentriche stanno nel visibility
    engine, che è l'unico a sapere che esistono i siti.
    """
    return _positions("earth", jd)


def ecliptic_to_equatorial(vec: np.ndarray) -> np.ndarray:
    """Rotazione di ε attorno a x. I nostri elementi sono eclittici, DE440s no."""
    eps = np.radians(OBLIQUITY_J2000_DEG)
    x, y, z = vec[..., 0], vec[..., 1], vec[..., 2]
    return np.stack([x, y * np.cos(eps) - z * np.sin(eps),
                     y * np.sin(eps) + z * np.cos(eps)], axis=-1)


def is_available() -> bool:
    """Il kernel c'è già su disco? Serve all'interfaccia per non bloccarsi 32 MB."""
    return config.DE440S_FILE.exists()
