"""La magnitudine limite efficace, con la sua scomposizione.

`eff_vlim` è la profondità che *quel* setup raggiunge in *quel* momento: il
limite dichiarato meno tutto ciò che lo peggiora. Non esce mai da solo — regola
5 — ma insieme a `pen_airmass`, `pen_moon`, `pen_twilight`, `pen_trailing`.
Senza la scomposizione un ranking non si sa spiegare, e quel che non si sa
spiegare non si tara.

**Il fattore 1.25.** In regime sky-limited il rapporto segnale/rumore va come
`√t` e come `1/√B`: una magnitudine di cielo in più ne costa **mezza** di
limite, e ogni fattore sul fondo o sul tempo entra come `1.25 log₁₀`. Chi
scrive 2.5 raddoppia tutte le penalità del sistema, e i numeri restano
plausibili — è l'errore da tenere d'occhio in questo file
(docs/modelli.md §7).
"""
from __future__ import annotations

import numpy as np

from core.visibility.geometry import airmass
from core.visibility.instrument import Setup
from core.visibility.site import Site
from core.visibility.sky import dark_sky_nl, moon_brightness_nl, nanolambert, twilight_excess_nl

# S/N ∝ 1/√B e ∝ √t: mezza magnitudine di limite per ogni magnitudine di fondo.
SKY_LIMITED = 1.25

# La somma delle quattro penalità deve fare *esattamente* la differenza fra il
# limite dichiarato e quello efficace. `residual` esiste per verificarlo a ogni
# chiamata invece che per fiducia: se un domani qualcuno aggiunge un quinto
# contributo e si dimentica di scomporlo, salta fuori qui e non in una
# discussione su perché un sito perde.
RESIDUAL_TOL = 1e-9


def trailing_penalty(motion_arcsec_min, exposure_s, seeing_arcsec):
    """Quanto costa che l'oggetto si muova: 1.25 log₁₀(1 + L/θ).

        L = μ · t / 60          lunghezza della traccia, arcsec

    La luce si spalma su una traccia invece che su un disco di seeing: il
    rumore raccolto cresce con la lunghezza, il segnale no.
    """
    mu = np.asarray(motion_arcsec_min, dtype=float)
    t = np.asarray(exposure_s, dtype=float)
    theta = np.maximum(np.asarray(seeing_arcsec, dtype=float), 0.1)
    traccia = np.maximum(mu, 0.0) * t / 60.0
    return SKY_LIMITED * np.log10(1.0 + traccia / theta)


def max_exposure_for_trailing(motion_arcsec_min, seeing_arcsec, pixel_scale_arcsec):
    """Posa massima perché la traccia resti dentro una FWHM.

        t_max = 60 · max(θ, 1.5 · scala) / μ

    Il `max` con una volta e mezza il pixel serve ai setup sottocampionati: con
    un seeing di 1.6″ e pixel da 2″ la tolleranza vera non è il seeing, è il
    pixel. Con oggetto fermo non c'è limite, e si restituisce infinito.
    """
    mu = np.asarray(motion_arcsec_min, dtype=float)
    tolleranza = np.maximum(np.asarray(seeing_arcsec, dtype=float),
                            1.5 * np.asarray(pixel_scale_arcsec, dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(mu > 0, 60.0 * tolleranza / mu, np.inf)
    return t


def effective_limit(*, site: Site, setup: Setup, target_alt_deg,
                    motion_arcsec_min=0.0, exposure_s=None,
                    moon_alt_deg=None, moon_phase_deg=None, moon_sep_deg=None,
                    sun_alt_deg=None):
    """`eff_vlim` e le quattro penalità che lo spiegano.

        eff_vlim = vlim_ref
                 + 1.25 log₁₀(t / t_ref)              esposizione
                 − k (X − 1)                          estinzione sul bersaglio
                 − 1.25 log₁₀(B_tot / B_zenit)        fondo di cielo
                 − pen_trailing

    Restituisce un dizionario di array: `eff_vlim`, `eff_vlim_astrometric`, le
    quattro penalità, l'airmass, la brillanza del cielo usata e il `residual`
    (vedi sotto). Tutto si combina per broadcasting, quindi la griglia della
    notte si calcola in una chiamata.

    **Le quattro penalità sommano esattamente al totale**, perché sono
    *incrementali e in quest'ordine*: airmass sul cielo scuro allo zenit, poi
    la Luna su quel cielo, poi il crepuscolo su cielo più Luna, poi il
    trailing. L'ordine è una convenzione e va saputa: `pen_twilight` è «quanto
    aggiunge il crepuscolo *dato che* c'è già quella Luna», non «quanto
    costerebbe da solo». Il totale non dipende dall'ordine, la ripartizione fra
    Luna e crepuscolo sì.

    L'alternativa — misurare ciascun contributo sul cielo scuro, come se gli
    altri non ci fossero — è più intuitiva a leggersi e non somma: misurato,
    lasciava **0.2 mag** di scarto in una notte con quarto di Luna in
    crepuscolo e 0.76 con Luna piena. Una scomposizione che non torna è una
    scomposizione che non spiega, e la regola 5 chiede che spieghi.
    """
    alt = np.asarray(target_alt_deg, dtype=float)
    z = 90.0 - alt
    k = site.extinction_k
    t = setup.typical_exposure_s if exposure_s is None else np.asarray(exposure_s, dtype=float)

    # Sotto l'orizzonte l'airmass è infinita e tutto quel che segue è NaN o
    # −inf: è la risposta giusta e non un errore, quindi si tace il warning
    # invece di riempire il log dello screening. Chi chiama filtra sulla
    # maschera geometrica, che è l'unico posto in cui la domanda ha senso.
    x = airmass(alt)

    b_zenit = nanolambert(site.sky_zenith_mag)
    b_scuro = dark_sky_nl(site.sky_zenith_mag, z, k)
    b_luna = (moon_brightness_nl(
        phase_deg=0.0 if moon_phase_deg is None else moon_phase_deg,
        separation_deg=90.0 if moon_sep_deg is None else moon_sep_deg,
        moon_zenith_deg=90.0 - np.asarray(moon_alt_deg, dtype=float),
        target_zenith_deg=z, extinction_k=k,
    ) if moon_alt_deg is not None else np.zeros_like(b_scuro))
    b_crep = (twilight_excess_nl(b_scuro, sun_alt_deg, site.twilight_coeff)
              if sun_alt_deg is not None else np.zeros_like(b_scuro))
    b_tot = b_scuro + b_luna + b_crep

    with np.errstate(invalid="ignore", divide="ignore"):
        return _componi(site, setup, alt, x, t, b_zenit, b_scuro, b_luna, b_crep,
                        b_tot, motion_arcsec_min)


def _componi(site, setup, alt, x, t, b_zenit, b_scuro, b_luna, b_crep, b_tot,
             motion_arcsec_min):
    k = site.extinction_k
    guadagno_posa = SKY_LIMITED * np.log10(t / setup.vlim_ref_exposure_s)
    estinzione = k * (x - 1.0)
    fondo = SKY_LIMITED * np.log10(b_tot / b_zenit)
    pen_trailing = trailing_penalty(motion_arcsec_min, t, setup.typical_seeing_arcsec)

    eff = setup.vlim_ref + guadagno_posa - estinzione - fondo - pen_trailing

    pen_airmass = estinzione + SKY_LIMITED * np.log10(b_scuro / b_zenit)
    pen_moon = SKY_LIMITED * np.log10((b_scuro + b_luna) / b_scuro)
    pen_twilight = SKY_LIMITED * np.log10(b_tot / (b_scuro + b_luna))

    totale = setup.vlim_ref + guadagno_posa - eff
    residuo = totale - (pen_airmass + pen_moon + pen_twilight + pen_trailing)

    return {
        "eff_vlim": eff,
        # Per l'astrometria serve più segnale che per accorgersi che c'è
        # qualcosa: il delta è negativo e sta nel setup.
        "eff_vlim_astrometric": eff + setup.vlim_astrometric_delta,
        "pen_airmass": pen_airmass,
        "pen_moon": pen_moon,
        "pen_twilight": pen_twilight,
        "pen_trailing": pen_trailing,
        "residual": residuo,
        "airmass": x,
        "sky_mag": _sky_mag(b_tot),
        "exposure_s": t,
    }


def _sky_mag(nl):
    from core.visibility.sky import sky_magnitude

    return sky_magnitude(nl)


# --- il metro stabile ------------------------------------------------------
# Il radar ha bisogno di un limite che **non cambi con la Luna**: se la soglia
# degli stati si muovesse con il cielo di stanotte, ogni plenilunio farebbe
# uscire mezzo catalogo da OBSERVABLE e ogni novilunio lo farebbe rientrare —
# venti transizioni al mese che non dicono niente sull'oggetto.
# X = 1.5 è la condizione tipica di una posa buona: né allo zenit (che capita
# di rado) né all'orizzonte. Vedi docs/modelli.md §10.
REF_AIRMASS = 1.5


def altitude_for_airmass(x_target: float) -> float:
    """L'altezza a cui *la nostra* airmass vale `x_target`, in gradi.

    Si inverte per bisezione la Kasten & Young di `geometry.airmass` invece di
    usare `arccos(1/X)` della secante: la differenza a X = 1.5 è di due
    centesimi di grado, ma così il riferimento è coerente con l'unica airmass
    che il resto del codice conosce, e resta coerente se un domani la formula
    cambia.
    """
    lo, hi = 0.0, 90.0                      # altezza: X decresce salendo
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if airmass(mid) > x_target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def reference_limit(*, site: Site, setup: Setup, airmass_ref: float = REF_AIRMASS,
                    motion_arcsec_min: float = 0.0) -> dict:
    """`V_ref`: la profondità di quel setup in condizioni tipiche e ripetibili.

    X = 1.5, niente Luna, niente crepuscolo, posa tipica. **Non è una
    condizione reale**: è un metro. Le condizioni vere stanno in `eff_vlim`
    della finestra, che è un altro numero e non va confuso con questo.

    Restituisce il dizionario di `effective_limit` con valori scalari — la
    scomposizione viaggia anche qui, perché «da dove viene il V_ref di questo
    setup» è la prima domanda che si fa quando uno stato non torna (regola 5).
    """
    alt = altitude_for_airmass(airmass_ref)
    out = effective_limit(
        site=site, setup=setup, target_alt_deg=alt,
        motion_arcsec_min=motion_arcsec_min,
        exposure_s=setup.typical_exposure_s,
        moon_alt_deg=None, moon_phase_deg=None, moon_sep_deg=None, sun_alt_deg=None,
    )
    return {**{k: float(v) for k, v in out.items()}, "alt_deg": alt}


def required_exposure(v_mag, eff_vlim_at_ref, ref_exposure_s):
    """Quanto tempo serve per arrivare a `v_mag`, invertendo la scala in √t.

        t = t_ref · 10^[(V − eff_vlim(t_ref)) / 1.25]

    Per un oggetto già più brillante del limite viene meno del riferimento, ed
    è giusto: significa che basta meno posa.
    """
    v = np.asarray(v_mag, dtype=float)
    limite = np.asarray(eff_vlim_at_ref, dtype=float)
    return np.asarray(ref_exposure_s, dtype=float) * np.power(
        10.0, (v - limite) / SKY_LIMITED)


def exposure_plan(*, setup: Setup, v_mag, eff_vlim, motion_arcsec_min,
                  exposure_s=None, window_hours=None):
    """`n × t` invece di una posa sola: quante pose, quanto lunghe, e se ci stanno.

    Il singolo scatto è limitato dal trailing e dal massimo dello strumento; il
    numero di scatti da quanto segnale serve. Se il totale non entra nella
    finestra utile, l'oggetto è fuori portata **per quel setup** anche se
    `eff_vlim` da solo direbbe di sì — ed è esattamente il caso in cui
    un'apertura più grande vince: accorcia il tempo necessario, non il limite.
    """
    t_rif = setup.typical_exposure_s if exposure_s is None else exposure_s
    t_trail = max_exposure_for_trailing(
        motion_arcsec_min, setup.typical_seeing_arcsec, setup.pixel_scale_arcsec)
    t_sub = np.minimum(t_trail, setup.max_exposure_s)

    t_serve = required_exposure(v_mag, eff_vlim, t_rif)
    with np.errstate(invalid="ignore", divide="ignore"):
        n_sub = np.ceil(np.maximum(t_serve, 1e-9) / t_sub)
    n_sub = np.where(np.isfinite(n_sub), np.maximum(n_sub, 1.0), np.nan)

    totale_s = n_sub * t_sub
    sta_dentro = (totale_s / 3600.0 <= window_hours) if window_hours is not None else None

    return {
        "t_sub_s": t_sub,
        "n_subs": n_sub,
        "total_s": totale_s,
        "t_needed_s": t_serve,
        "t_trailing_max_s": t_trail,
        "fits_window": sta_dentro,
    }
