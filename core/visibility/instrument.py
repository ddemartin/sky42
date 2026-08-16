"""Il setup, come lo vede il calcolo: quanto arriva in profondità e a che prezzo.

Stessa idea di `Site`: non è la riga di `setup` e non è il file YAML, è il poco
che serve a decidere. Senza `id`, senza nomi, senza date di validità — così una
funzione di limite si prova con quattro numeri scritti a mano, e la domanda
«e se ci mettessi una camera con pixel più piccoli?» non richiede una riga nel
database.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Setup:
    # Il limite dichiarato, alla sua esposizione di riferimento, allo zenit,
    # con cielo scuro e sorgente puntiforme. Tutto il resto sono penalità.
    vlim_ref: float
    vlim_ref_exposure_s: float = 120.0
    # Rivelare un puntino e misurarne la posizione a 0.3″ non sono la stessa
    # soglia: questo è quanto togliere per l'astrometria (numero negativo).
    vlim_astrometric_delta: float = -0.5

    typical_exposure_s: float = 120.0
    max_exposure_s: float = 600.0
    max_airmass: float = 2.2
    min_altitude_deg: float | None = None       # None = eredita dal telescopio
    typical_seeing_arcsec: float = 2.0
    sun_alt_max_deg: float = -15.0              # quanto crepuscolo si accetta

    pixel_scale_arcsec: float = 1.0
    fov_x_arcmin: float = 30.0
    fov_y_arcmin: float = 30.0
    code: str = ""

    @classmethod
    def from_row(cls, row: Mapping) -> "Setup":
        """Da una riga di `setup` (con `min_altitude_eff_deg` se già risolta)."""
        campi = {
            "vlim_ref", "vlim_ref_exposure_s", "vlim_astrometric_delta",
            "typical_exposure_s", "max_exposure_s", "max_airmass",
            "typical_seeing_arcsec", "sun_alt_max_deg", "pixel_scale_arcsec",
            "fov_x_arcmin", "fov_y_arcmin",
        }
        dati = {k: float(row[k]) for k in campi if row.get(k) is not None}
        alt = row.get("min_altitude_eff_deg", row.get("min_altitude_deg"))
        return cls(min_altitude_deg=None if alt is None else float(alt),
                   code=row.get("code") or "", **dati)

    @property
    def fov_min_arcmin(self) -> float:
        """Il lato corto: è quello che decide se un oggetto incerto ci sta dentro."""
        return min(self.fov_x_arcmin, self.fov_y_arcmin)
