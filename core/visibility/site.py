"""Il sito, come lo vede il calcolo: una posizione sulla Terra e un cielo sopra.

Non è la riga di `observatory` e non è il file YAML: è il poco che serve a
calcolare, senza `id`, senza nomi e senza date di validità. Così una funzione di
visibilità si può provare con tre numeri scritti a mano, e il giorno in cui si
vorrà valutare un sito che non esiste ancora — «e se lo mettessi in Namibia?» —
non serve inventarsi una riga nel database.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Site:
    latitude: float                 # gradi, nord positivo
    longitude: float                # gradi, est positivo
    altitude_m: float = 0.0
    timezone: str = "UTC"           # IANA: decide *quale* notte, non il calcolo
    sky_zenith_mag: float = 21.6    # V mag/arcsec² in notte scura senza Luna
    extinction_k: float = 0.16      # mag/airmass in V
    horizon: tuple | None = None    # ((az, alt), ...) crescente in azimut
    code: str = ""

    @classmethod
    def from_row(cls, row: Mapping) -> "Site":
        """Da una riga di `observatory`. L'orizzonte arriva come JSON."""
        horizon = row.get("horizon_json")
        if isinstance(horizon, str) and horizon.strip():
            horizon = tuple(tuple(map(float, p)) for p in json.loads(horizon))
        else:
            horizon = None
        return cls(
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            altitude_m=float(row.get("altitude_m") or 0.0),
            timezone=row.get("timezone") or "UTC",
            sky_zenith_mag=float(row.get("sky_zenith_mag") or 21.6),
            extinction_k=float(row.get("extinction_k") or 0.16),
            horizon=horizon,
            code=row.get("code") or "",
        )

    def horizon_altitude(self, az_deg):
        """Altezza minima del terreno all'azimut dato, interpolata.

        Senza profilo restituisce 0: il limite dello strumento è un'altra cosa e
        lo applica chi conosce il setup. Qui c'è solo ciò che c'è davvero
        intorno — alberi, muri, la cupola del vicino.
        """
        az = np.asarray(az_deg, dtype=float) % 360.0
        if not self.horizon:
            return np.zeros_like(az)
        punti = sorted(self.horizon)
        azs = np.array([p[0] for p in punti], dtype=float)
        alts = np.array([p[1] for p in punti], dtype=float)
        # `period=360` chiude il cerchio: fra l'ultimo punto e il primo si
        # interpola passando per nord, che è la cosa che il profilo descrive.
        return np.interp(az, azs, alts, period=360.0)
