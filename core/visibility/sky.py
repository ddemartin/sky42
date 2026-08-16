"""Quanto è brillante il cielo: notte scura, Luna, crepuscolo.

Modello di **Krisciunas & Schaefer (1991)**, PASP 103, 1033, che è il modello
standard per la brillanza lunare in banda V e dichiara un rms di 0.23 mag
rispetto alle misure. Le formule stanno in docs/modelli.md §6; qui c'è il come.

Tre contributi che si sommano **in flusso** e non in magnitudine — le
magnitudini non si sommano, e sommarle è il modo più veloce per ottenere un
cielo più scuro aggiungendo la Luna:

* il cielo scuro del sito, alla distanza zenitale del bersaglio;
* la Luna, se è sopra l'orizzonte;
* il crepuscolo, che è l'unico pezzo empirico e dichiarato tale.

Il modulo non sa che cosa stia guardando (regola 4): riceve distanze zenitali e
separazioni angolari.
"""
from __future__ import annotations

import numpy as np

# Conversione fra magnitudine per arcosecondo quadrato e luminanza in
# nanoLambert, con le costanti **dell'articolo**. `_NL_B` è 0.4·ln10 =
# 0.92103404 arrotondato a cinque decimali: la differenza vale 1e-5 magnitudini
# e si tiene il valore pubblicato, perché la fedeltà al modello vale più di un
# decimillesimo. Le due costanti sono la stessa relazione scritta nei due
# versi: non se ne tocca una sola.
_NL_A, _NL_B = 20.7233, 0.92104
_NL_SCALE = 34.08

# Coefficiente empirico del crepuscolo: quante magnitudini di cielo si perdono
# per ogni grado di Sole sopra i −18°. **È il numero più debole del sistema**
# (MEMORANDUM, domanda aperta 4): una stima, non una misura, e vale ~1.7 mag a
# −15°. Sta qui come default e non come costante inchiodata perché dipende dal
# sito — aerosol, orizzonte, direzione rispetto al Sole — e il giorno in cui
# `setup_calibration` avrà abbastanza notti diventerà un campo di `Site`.
TWILIGHT_COEFF_DEFAULT = 0.55

# Sotto questa altezza il Sole non contribuisce più: è la definizione di notte
# astronomica, ed è la stessa soglia con cui `night.py` cerca i crepuscoli.
SUN_ALT_DARK = -18.0


def nanolambert(mag_arcsec2):
    """Da mag/arcsec² a nanoLambert. Più piccola la magnitudine, più luce."""
    m = np.asarray(mag_arcsec2, dtype=float)
    return _NL_SCALE * np.exp(_NL_A - _NL_B * m)


def sky_magnitude(nl):
    """Da nanoLambert a mag/arcsec². L'inversa esatta di `nanolambert`."""
    b = np.asarray(nl, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (_NL_A - np.log(b / _NL_SCALE)) / _NL_B
    return m


def ks_airmass(zenith_deg):
    """L'airmass **del modello**: X(Z) = (1 − 0.96 sin²Z)^(−1/2).

    Non è Kasten & Young, ed è di proposito: Krisciunas & Schaefer hanno tarato
    i loro coefficienti con *questa* approssimazione, e sostituirla con una più
    accurata cambierebbe il modello senza migliorarlo. Le due formule restano
    quindi separate — una per l'estinzione del bersaglio, questa per la
    diffusione della luce lunare.

    Scarti misurati rispetto a Kasten & Young: −0.6% a 30° di distanza
    zenitale, −5% a 60°, −12% a 70°, −32% a 80°. La conseguenza pratica è che
    una Luna piena a un grado sull'orizzonte risulta ancora capace di
    schiarire il cielo di 2.6 mag, dove la realtà la estinguerebbe di più: è un
    limite noto del modello, sta in un test, e sparisce appena la Luna tramonta.
    """
    z = np.radians(np.asarray(zenith_deg, dtype=float))
    s = np.sin(z)
    with np.errstate(invalid="ignore"):
        x = np.power(np.maximum(1.0 - 0.96 * s * s, 1e-6), -0.5)
    return x


def moon_brightness_nl(phase_deg, separation_deg, moon_zenith_deg,
                       target_zenith_deg, extinction_k):
    """Contributo della Luna in nanoLambert (K&S 1991, eq. 15 e seguenti).

        I*   = 10^(−0.4 (3.84 + 0.026|α| + 4e−9 α⁴))
        f(ρ) = 10^5.36 (1.06 + cos²ρ) + 10^(6.15 − ρ/40)
        B    = f(ρ) · I* · 10^(−0.4 k X_luna) · [1 − 10^(−0.4 k X_target)]

    Il fattore `10^(−0.4 k X_luna)` è la ragione per cui **una Luna piena sotto
    l'orizzonte non penalizza**: si estingue da sola, senza bisogno di un `if`.
    L'unico `if` è quello esplicito per Z_luna > 90°, dove X non ha più senso.
    """
    alpha = np.abs(np.asarray(phase_deg, dtype=float))
    rho = np.radians(np.asarray(separation_deg, dtype=float))
    z_luna = np.asarray(moon_zenith_deg, dtype=float)
    z_target = np.asarray(target_zenith_deg, dtype=float)
    k = np.asarray(extinction_k, dtype=float)

    i_star = np.power(10.0, -0.4 * (3.84 + 0.026 * alpha + 4e-9 * alpha**4))
    f_rho = 10**5.36 * (1.06 + np.cos(rho) ** 2) + np.power(10.0, 6.15 - np.degrees(rho) / 40.0)

    estinzione_luna = np.power(10.0, -0.4 * k * ks_airmass(z_luna))
    diffusione = 1.0 - np.power(10.0, -0.4 * k * ks_airmass(z_target))

    b = f_rho * i_star * estinzione_luna * diffusione
    return np.where(z_luna < 90.0, b, 0.0)


def dark_sky_nl(zenith_mag, target_zenith_deg, extinction_k):
    """Il cielo scuro alla distanza zenitale del bersaglio.

        B(Z) = B_zenit · 10^(−0.4 k (X−1)) · X

    Due effetti opposti: verso l'orizzonte si guarda attraverso più atmosfera
    che *emette* (il fattore X) ma anche che *assorbe* (l'estinzione). Il netto
    è che il cielo si schiarisce un po' e poi torna a scurirsi molto in basso.
    """
    x = ks_airmass(target_zenith_deg)
    k = np.asarray(extinction_k, dtype=float)
    return nanolambert(zenith_mag) * np.power(10.0, -0.4 * k * (x - 1.0)) * x


def twilight_excess_nl(base_nl, sun_alt_deg, coeff=None):
    """Il crepuscolo come *aggiunta* di flusso, non come sottrazione di magnitudini.

        ΔV = coeff · (h_Sole + 18)        per h_Sole > −18°

    Espresso come flusso: `B_extra = B_scuro · (10^(0.4 ΔV) − 1)`. Scritto così,
    senza Luna il risultato è esattamente «cielo scuro meno ΔV magnitudini», e
    con la Luna i due contributi si sommano come fanno le luci vere. La
    sottrazione diretta in magnitudine sarebbe più corta e conterebbe due volte
    la parte già illuminata.

    Resta la formula più debole del sistema: `coeff` è una stima da tarare.

    **Vale nel crepuscolo, e non oltre.** È lineare per costruzione, quindi al
    tramonto del Sole (h = 0) dichiara 9.9 magnitudini di cielo in più: un
    numero senza senso fisico, che nessuno però legge, perché a quel punto ogni
    setup ha già escluso l'istante con `sun_alt_max_deg`. Non c'è un tetto
    artificiale: metterlo nasconderebbe il fatto che il modello è tarato per la
    fascia da −18° a −10°, che è la sola in cui si osserva davvero.
    """
    h = np.asarray(sun_alt_deg, dtype=float)
    c = TWILIGHT_COEFF_DEFAULT if coeff is None else coeff
    delta_v = np.maximum(0.0, np.asarray(c, dtype=float) * (h - SUN_ALT_DARK))
    return np.asarray(base_nl, dtype=float) * (np.power(10.0, 0.4 * delta_v) - 1.0)


def sky_brightness(*, zenith_mag, extinction_k, target_alt_deg,
                   moon_alt_deg=None, moon_phase_deg=None, moon_sep_deg=None,
                   sun_alt_deg=None, twilight_coeff=None, breakdown=False):
    """Brillanza del cielo in mag/arcsec², nella direzione del bersaglio.

    Con `breakdown=True` restituisce un dizionario con i pezzi separati: senza
    la scomposizione non si capisce *perché* un cielo era brutto, e la regola 5
    dice che un numero senza il suo perché non si tara (e infatti il
    coefficiente del crepuscolo va tarato).
    """
    z_target = 90.0 - np.asarray(target_alt_deg, dtype=float)

    scuro = dark_sky_nl(zenith_mag, z_target, extinction_k)

    luna = np.zeros_like(scuro)
    if moon_alt_deg is not None:
        luna = moon_brightness_nl(
            phase_deg=0.0 if moon_phase_deg is None else moon_phase_deg,
            separation_deg=90.0 if moon_sep_deg is None else moon_sep_deg,
            moon_zenith_deg=90.0 - np.asarray(moon_alt_deg, dtype=float),
            target_zenith_deg=z_target,
            extinction_k=extinction_k,
        )

    crepuscolo = np.zeros_like(scuro)
    if sun_alt_deg is not None:
        crepuscolo = twilight_excess_nl(scuro, sun_alt_deg, twilight_coeff)

    totale = scuro + luna + crepuscolo
    v = sky_magnitude(totale)

    if not breakdown:
        return v
    return {
        "sky_mag": v,
        "dark_mag": sky_magnitude(scuro),
        # Le penalità sono differenze di magnitudine: quanto ciascun contributo
        # ha schiarito il cielo rispetto a quello scuro da solo. Positive =
        # peggiorano. Sono le stesse che finiranno in `pen_moon` e
        # `pen_twilight` di `observation_window`.
        "pen_moon": sky_magnitude(scuro) - sky_magnitude(scuro + luna),
        "pen_twilight": sky_magnitude(scuro + luna) - v,
        "moon_nl": luna,
        "twilight_nl": crepuscolo,
        "total_nl": totale,
    }
