"""Brillanza del cielo: Krisciunas & Schaefer 1991, e il crepuscolo che è una stima.

Qui non c'è una verità da scaricare: la brillanza del cielo non è
un'effemeride, e il modello dichiara di suo un rms di 0.23 mag rispetto alle
misure. La verifica è quindi di tre tipi, tutti e tre necessari:

* **le formule contro il calcolo a mano**, coefficiente per coefficiente;
* **il comportamento fisico**: più Luna = più chiaro, Luna tramontata = niente,
  la somma è in flusso e non in magnitudine;
* **gli ordini di grandezza contro la letteratura**: con Luna piena alta il
  cielo in V sta fra 17 e 19 mag/arcsec², non a 21 e non a 15.

Il coefficiente del crepuscolo (0.55 mag/grado) non è verificato da niente: è
la domanda aperta n. 4 del memorandum, e i test qui sotto ne fissano la
*forma*, non il valore.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.visibility.sky import (
    SUN_ALT_DARK,
    TWILIGHT_COEFF_DEFAULT,
    dark_sky_nl,
    ks_airmass,
    moon_brightness_nl,
    nanolambert,
    sky_brightness,
    sky_magnitude,
)

ZENITH_MAG = 21.8       # Río Hurtado
K = 0.14


def test_le_due_conversioni_sono_l_una_l_inversa_dell_altra():
    for m in (18.0, 20.0, 21.6, 22.5):
        assert sky_magnitude(nanolambert(m)) == pytest.approx(m, abs=1e-12)
    # E il valore assoluto, non solo il giro: il cielo scuro di riferimento di
    # K&S è 79 nL, che nella loro relazione corrisponde a V = 21.587. Se le due
    # costanti venissero toccate una alla volta, questo salterebbe.
    assert nanolambert(21.587) == pytest.approx(79.0, rel=0.001)


def test_airmass_del_modello_e_la_sua_non_quella_buona():
    """K&S usano X = (1 − 0.96 sin²Z)^(−1/2): allo zenit 1, a 60° circa 1.98."""
    assert ks_airmass(0.0) == pytest.approx(1.0, abs=1e-12)
    assert ks_airmass(60.0) == pytest.approx(1 / np.sqrt(1 - 0.96 * 0.75), abs=1e-12)
    # Quanto si discosta da Kasten & Young, misurato: −5% a 60° di distanza
    # zenitale, −12% a 70°, −32% a 80°. Non è un difetto da correggere: è
    # l'approssimazione con cui K&S hanno *tarato* i loro coefficienti, e
    # sostituirla cambierebbe il modello senza migliorarlo. Le due restano
    # funzioni separate, e questo test lo mette per iscritto.
    from core.visibility.geometry import airmass

    assert ks_airmass(60.0) / airmass(30.0) == pytest.approx(0.948, abs=0.01)
    assert ks_airmass(80.0) / airmass(10.0) == pytest.approx(0.682, abs=0.01)


def test_cielo_scuro_allo_zenit_e_quello_dichiarato():
    """Senza Luna e senza Sole, allo zenit, il modello non deve inventare niente."""
    v = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=90.0)
    assert v == pytest.approx(ZENITH_MAG, abs=1e-9)


def test_verso_l_orizzonte_il_cielo_scuro_si_schiarisce():
    """Più atmosfera che emette (X) meno quella che assorbe: il netto schiarisce."""
    zenit = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=90.0)
    basso = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=30.0)
    assert basso < zenit                       # numericamente più piccolo = più chiaro
    assert 0.3 < zenit - basso < 1.0


def test_luna_piena_alta_e_il_cielo_che_ne_esce():
    """Ordini di grandezza dalla letteratura: fra 17 e 19 mag/arcsec².

    E la dipendenza dalla separazione ha la forma giusta: vicino alla Luna è
    peggio, il minimo di disturbo sta intorno ai 90°, e a grande separazione
    risale un po' per la retrodiffusione — che è nella f(ρ) di K&S, non un
    artefatto.
    """
    def v(sep):
        return float(sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K,
                                    target_alt_deg=60.0, moon_alt_deg=60.0,
                                    moon_phase_deg=0.0, moon_sep_deg=sep))

    assert 17.0 < v(10) < 18.0
    assert 18.0 < v(90) < 19.5
    assert v(10) < v(30) < v(60) < v(90)       # più lontano, più scuro
    assert v(120) < v(90)                      # retrodiffusione


def test_la_fase_conta_quanto_deve():
    """Dal plenilunio al quarto si guadagnano un paio di magnitudini di cielo."""
    comune = dict(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=60.0,
                  moon_alt_deg=60.0, moon_sep_deg=60.0)
    piena = float(sky_brightness(**comune, moon_phase_deg=0.0))
    quarto = float(sky_brightness(**comune, moon_phase_deg=90.0))
    falce = float(sky_brightness(**comune, moon_phase_deg=140.0))
    assert 1.5 < quarto - piena < 3.0
    assert falce > quarto > piena
    # Una falce sottile e lontana non deve rovinare la notte.
    assert falce > ZENITH_MAG - 1.5


def test_la_luna_sotto_l_orizzonte_non_penalizza():
    """Senza `if` nel modello: il termine di estinzione ci va da solo.

    È la proprietà che rende il modello utilizzabile su una griglia temporale
    senza casi speciali — e quella che un giorno qualcuno «ottimizzerà» con un
    if sbagliato.
    """
    senza = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=60.0)
    sotto = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=60.0,
                           moon_alt_deg=-5.0, moon_phase_deg=0.0, moon_sep_deg=60.0)
    assert sotto == pytest.approx(senza, abs=1e-9)

    # Appena sopra l'orizzonte l'estinzione la attenua, ma **meno di quanto
    # farebbe la realtà**: con l'airmass di K&S una Luna piena a 1° schiarisce
    # ancora di 2.6 mag, perché la loro X satura a 5 dove quella vera vale 38.
    # È un limite noto del modello, non un errore nostro, e va in fretta a zero
    # appena la Luna scende sotto l'orizzonte. Il test lo fissa perché il
    # giorno in cui i numeri sembreranno strani si sappia già perché.
    radente = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=60.0,
                             moon_alt_deg=1.0, moon_phase_deg=0.0, moon_sep_deg=60.0)
    assert float(senza) - float(radente) == pytest.approx(2.6, abs=0.2)


def test_la_somma_e_in_flusso_non_in_magnitudine():
    """Due sorgenti insieme fanno più luce di ciascuna: sembra ovvio, in
    magnitudini non lo è, ed è l'errore classico di questo modello."""
    b = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=60.0,
                       moon_alt_deg=50.0, moon_phase_deg=0.0, moon_sep_deg=45.0,
                       sun_alt_deg=-15.0, breakdown=True)
    assert b["total_nl"] == pytest.approx(
        dark_sky_nl(ZENITH_MAG, 30.0, K) + b["moon_nl"] + b["twilight_nl"])
    assert b["sky_mag"] < b["dark_mag"]
    # Quanto ciascuno ha schiarito il cielo, al netto dell'altro. Non sono le
    # penalità sul limite: quelle valgono la metà e le calcola `limits.py`.
    assert b["delta_moon_mag"] > 0 and b["delta_twilight_mag"] > 0
    assert b["dark_mag"] - b["sky_mag"] == pytest.approx(
        b["delta_moon_mag"] + b["delta_twilight_mag"], abs=1e-9)


def test_il_crepuscolo_ha_la_forma_dichiarata():
    """Lineare nell'altezza del Sole, nulla sotto i −18°, e con la sua stima.

    Il *valore* del coefficiente non è verificato da niente: qui si fissa la
    forma, così quando arriverà la misura si cambierà un numero e non un
    modello.
    """
    def v(h):
        return float(sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K,
                                    target_alt_deg=90.0, sun_alt_deg=h))

    assert v(SUN_ALT_DARK) == pytest.approx(ZENITH_MAG, abs=1e-9)
    assert v(-20.0) == pytest.approx(ZENITH_MAG, abs=1e-9)      # più giù non schiarisce
    # L'identità «ΔV magnitudini» non è esatta a precisione di macchina ma a
    # 1e-5: la costante 0.92104 dell'articolo è 0.4·ln10 = 0.92103404 arrotondata
    # a cinque decimali. Si tengono le costanti pubblicate — la fedeltà al
    # modello vale più di un decimillesimo di magnitudine.
    assert ZENITH_MAG - v(-15.0) == pytest.approx(3 * TWILIGHT_COEFF_DEFAULT, abs=1e-4)
    assert ZENITH_MAG - v(-12.0) == pytest.approx(6 * TWILIGHT_COEFF_DEFAULT, abs=1e-4)


def test_il_coefficiente_del_crepuscolo_si_puo_cambiare_per_sito():
    """Il giorno in cui sarà misurato, sarà un numero e non una riscrittura."""
    misurato = float(sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K,
                                    target_alt_deg=90.0, sun_alt_deg=-15.0,
                                    twilight_coeff=0.40))
    assert ZENITH_MAG - misurato == pytest.approx(3 * 0.40, abs=1e-4)

    from core.visibility.site import Site

    assert Site(latitude=0, longitude=0).twilight_coeff is None, \
        "`None` significa «non misurato qui», non «zero»"


def test_funziona_su_array():
    """La griglia della notte in una chiamata sola."""
    alt = np.linspace(20, 80, 5)
    sep = np.linspace(20, 120, 5)
    v = sky_brightness(zenith_mag=ZENITH_MAG, extinction_k=K, target_alt_deg=alt,
                       moon_alt_deg=40.0, moon_phase_deg=30.0, moon_sep_deg=sep,
                       sun_alt_deg=-16.0)
    assert v.shape == (5,)
    assert np.all(np.isfinite(v))


def test_i_pezzi_contro_il_calcolo_a_mano():
    """Le formule di K&S, coefficiente per coefficiente, senza scorciatoie."""
    alpha, rho, z_luna, z_target = 60.0, 50.0, 40.0, 30.0

    i_star = 10 ** (-0.4 * (3.84 + 0.026 * alpha + 4e-9 * alpha**4))
    f_rho = 10**5.36 * (1.06 + np.cos(np.radians(rho)) ** 2) + 10 ** (6.15 - rho / 40.0)
    atteso = (f_rho * i_star
              * 10 ** (-0.4 * K * ks_airmass(z_luna))
              * (1 - 10 ** (-0.4 * K * ks_airmass(z_target))))

    assert moon_brightness_nl(alpha, rho, z_luna, z_target, K) == pytest.approx(atteso)
