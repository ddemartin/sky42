"""Formati dell'interfaccia. Piccoli, ma è quello che si legge."""
from __future__ import annotations

from gui.layout import age_color, fmt_age, fmt_delay, fmt_int, fmt_num


def test_eta_leggibile():
    assert fmt_age(None) == "mai"
    assert fmt_age(0.0005) == "adesso"          # 43 secondi
    assert fmt_age(0.0208) == "30 min fa"
    assert fmt_age(0.0414) == "60 min fa"       # 59,6 min: non "adesso"
    assert fmt_age(0.5) == "12 h fa"
    assert fmt_age(9.0) == "9 giorni fa"
    assert fmt_age(400.0) == "1.1 anni fa"


def test_il_futuro_ha_parole_sue():
    """«fra 13 min fa» è stato in pagina: le due direzioni non si compongono
    dallo stesso pezzo di testo."""
    assert fmt_delay(None) == "mai"
    assert fmt_delay(0.0005) == "a momenti"          # 43 secondi
    assert fmt_delay(0.0208) == "fra 30 min"
    assert fmt_delay(0.5) == "fra 12 h"
    assert fmt_delay(9.0) == "fra 9 giorni"
    # Un lavoro che doveva partire e non è partito non si scrive «fra -3 min».
    assert fmt_delay(-0.0208) == "in ritardo di 30 min"
    assert "fa" not in fmt_delay(0.5) and "fra" not in fmt_age(0.5)


def test_colore_segue_la_freschezza():
    """I cataloghi si aggiornano ogni giorno: oltre la settimana è rosso."""
    assert age_color(None) == "grey"
    assert age_color(0.5) == "positive"
    assert age_color(4) == "warning"
    assert age_color(30) == "negative"


def test_migliaia_con_il_punto():
    assert fmt_int(1556465) == "1.556.465"
    assert fmt_int(None) == "—"
    assert fmt_num(None) == "—"
    assert fmt_num(3.31017, 3) == "3.310"
