"""Il reconcile dei siti: deriva, allinea, e non cancella mai.

I file di prova sono scritti nel formato che scrive un umano — date come date
YAML, chiavi facoltative assenti — perché è quello il formato che il modulo
incontrerà davvero.
"""
from __future__ import annotations

import textwrap

import pytest

from core.db import connect
from core.sites.reconcile import (
    ARCSEC_PER_MM,
    SiteConfigError,
    derive_optics,
    load_sites,
    reconcile,
)

SITO = """
code: cile-test
name: Río Hurtado, Cile
latitude: -30.4728
longitude: -70.7647
altitude_m: 1560
timezone: America/Santiago
sky_zenith_mag: 21.8
extinction_k: 0.14
horizon:
  - [0, 22]
  - [180, 30]

telescopes:
  - code: rc700
    name: RC 700
    aperture_mm: 700
    focal_length_mm: 4540
    design: Ritchey-Chrétien
    min_altitude_deg: 25

cameras:
  - code: qhy600m
    name: QHY600M Pro
    sensor: IMX455
    pixel_um: 3.76
    pixels_x: 9576
    pixels_y: 6388
    read_noise_e: 3.0

setups:
  - code: rc700-qhy600-bin2
    name: RC700 + QHY600 bin2 L
    telescope: rc700
    camera: qhy600m
    binning: 2
    filter: L
    vlim_ref: 21.3
    valid_from: 2026-01-01
    active: true
"""


@pytest.fixture()
def sites_dir(tmp_path):
    d = tmp_path / "sites"
    d.mkdir()
    (d / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    return d


def _riga(sql, params=()):
    conn = connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- i derivati, con il numero atteso ---------------------------------------


def test_scala_e_campo_dai_soli_ingredienti():
    """RC 700 (f = 4540 mm) + IMX455 (3.76 µm) in bin 2.

    Controllo indipendente dalla formula: 36.0 mm di sensore su 4540 mm di
    focale sono 36/4540 rad = 7.93e-3 rad = 27.3'. Se il campo esce diverso da
    quello, il fattore 206.265 o il binning sono sbagliati.
    """
    tel = {"focal_length_mm": 4540.0}
    cam = {"pixel_um": 3.76, "pixels_x": 9576, "pixels_y": 6388}
    setup = {"code": "x", "binning": 2, "focal_reducer": 1.0}

    d = derive_optics(tel, cam, setup)
    assert d["pixel_scale_arcsec"] == pytest.approx(0.34166, abs=1e-5)
    assert d["fov_x_arcmin"] == pytest.approx(27.27, abs=0.02)
    assert d["fov_y_arcmin"] == pytest.approx(18.19, abs=0.02)

    # Il lato lungo del sensore in millimetri, ricavato all'indietro dal campo.
    lato_mm = 9576 * 3.76 / 1000
    atteso_arcmin = (lato_mm / 4540) * (ARCSEC_PER_MM * 1000) / 60
    assert d["fov_x_arcmin"] == pytest.approx(atteso_arcmin, rel=1e-3)


def test_il_binning_non_cambia_il_campo():
    """Allarga il pixel e ne riduce il numero: il campo deve restare quello."""
    tel = {"focal_length_mm": 4540.0}
    cam = {"pixel_um": 3.76, "pixels_x": 9576, "pixels_y": 6388}
    uno = derive_optics(tel, cam, {"code": "x", "binning": 1, "focal_reducer": 1.0})
    due = derive_optics(tel, cam, {"code": "x", "binning": 2, "focal_reducer": 1.0})

    assert due["pixel_scale_arcsec"] == pytest.approx(2 * uno["pixel_scale_arcsec"])
    assert due["fov_x_arcmin"] == pytest.approx(uno["fov_x_arcmin"], rel=1e-9)


def test_il_riduttore_accorcia_la_focale():
    tel = {"focal_length_mm": 4540.0}
    cam = {"pixel_um": 3.76, "pixels_x": 9576, "pixels_y": 6388}
    pieno = derive_optics(tel, cam, {"code": "x", "binning": 1, "focal_reducer": 1.0})
    ridotto = derive_optics(tel, cam, {"code": "x", "binning": 1, "focal_reducer": 0.7})
    assert ridotto["fov_x_arcmin"] == pytest.approx(pieno["fov_x_arcmin"] / 0.7)


# --- lettura e verifica -----------------------------------------------------


def test_legge_il_sito_di_esempio_del_progetto():
    """Il file versionato in config/sites/ deve essere valido. È documentazione
    eseguibile: se qualcuno lo modifica sbagliando un campo, il test lo dice."""
    siti = load_sites()
    assert siti, "nessun sito in config/sites/"
    for sito in siti:
        assert sito["setups"], f"{sito['code']}: nessun setup"


def test_un_campo_sconosciuto_ferma_tutto(sites_dir):
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("latitude:", "latitide:"), encoding="utf-8"
    )
    with pytest.raises(SiteConfigError, match="latitide"):
        load_sites(sites_dir)


def test_un_setup_che_punta_a_una_camera_inesistente(sites_dir):
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("camera: qhy600m", "camera: qhy268m"), encoding="utf-8"
    )
    with pytest.raises(SiteConfigError, match="qhy268m"):
        load_sites(sites_dir)


def test_codici_duplicati_fra_file(sites_dir):
    (sites_dir / "copia.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    with pytest.raises(SiteConfigError, match="già usato"):
        load_sites(sites_dir)


def test_un_fuso_inventato_ferma_il_reconcile(sites_dir):
    """Caso vero del 2026-08-17: un file nuovo con `America/Utah`, che non
    esiste — lo Utah sta in `America/Denver`. Il reconcile lo accettava e il
    guasto saltava fuori molto dopo, dentro `night_events`, cioè in un job di
    fondo alle tre di notte e con un errore che non nomina né il file né il
    sito. Il reconcile verifica tutto **e poi** scrive."""
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("timezone: America/Santiago",
                                      "timezone: America/Utah"), encoding="utf-8")
    with pytest.raises(SiteConfigError, match="fuso orario sconosciuto"):
        load_sites(sites_dir)


def test_il_costo_orario_e_facoltativo_e_arriva_nel_database(db, sites_dir):
    """Un telescopio proprio non ha listino: `None` significa «non si paga», ed
    è diverso da zero."""
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("    active: true\n",
                                      "    cost_per_hour: 42.5\n    currency: EUR\n"
                                      "    active: true\n", 1),
        encoding="utf-8")
    reconcile(sites_dir)
    riga = _riga("SELECT cost_per_hour, currency FROM setup")
    assert riga["cost_per_hour"] == 42.5 and riga["currency"] == "EUR"


def test_manca_un_campo_obbligatorio(sites_dir):
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("    vlim_ref: 21.3\n", ""), encoding="utf-8"
    )
    with pytest.raises(SiteConfigError, match="vlim_ref"):
        load_sites(sites_dir)


# --- scrittura --------------------------------------------------------------


def test_reconcile_scrive_tutto(db, sites_dir):
    report = reconcile(sites_dir)
    assert len(report["creati"]) == 4          # sito, telescopio, camera, setup
    assert report["aggiornati"] == []

    s = _riga("SELECT * FROM setup WHERE code='rc700-qhy600-bin2'")
    assert s["pixel_scale_arcsec"] == pytest.approx(0.34166, abs=1e-5)
    assert s["fov_x_arcmin"] == pytest.approx(27.27, abs=0.02)
    assert s["valid_from"] == "2026-01-01"     # non "2026-01-01 00:00:00"
    assert s["max_airmass"] == 2.2             # default dello schema, non nel file
    assert s["min_altitude_deg"] is None       # eredita dal telescopio

    o = _riga("SELECT * FROM observatory WHERE code='cile-test'")
    assert o["horizon_json"] == "[[0.0, 22.0], [180.0, 30.0]]"
    assert o["active"] == 1


def test_reconcile_e_idempotente(db, sites_dir):
    reconcile(sites_dir)
    secondo = reconcile(sites_dir)
    assert secondo["creati"] == []
    assert secondo["aggiornati"] == []
    assert secondo["disattivati"] == []


def test_una_modifica_al_file_aggiorna_solo_quella(db, sites_dir):
    reconcile(sites_dir)
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("focal_length_mm: 4540", "focal_length_mm: 3200"),
        encoding="utf-8",
    )
    report = reconcile(sites_dir)

    assert report["aggiornati"] == ["telescope:rc700", "setup:rc700-qhy600-bin2"]
    # Il derivato segue la focale senza che nessuno lo riscriva a mano.
    s = _riga("SELECT pixel_scale_arcsec FROM setup WHERE code='rc700-qhy600-bin2'")
    assert s["pixel_scale_arcsec"] == pytest.approx(0.484722, abs=1e-5)  # 206.265·3.76·2/3200


def test_quello_che_sparisce_dal_file_si_disattiva_e_resta(db, sites_dir):
    """Regola 3: l'hardware non si cancella mai. `observation_log` punta lì."""
    reconcile(sites_dir)
    id_prima = _riga("SELECT id FROM setup WHERE code='rc700-qhy600-bin2'")["id"]

    senza_setup = textwrap.dedent(SITO).split("setups:")[0]
    (sites_dir / "cile.yml").write_text(senza_setup, encoding="utf-8")
    report = reconcile(sites_dir)

    assert report["disattivati"] == ["setup:rc700-qhy600-bin2"]
    s = _riga("SELECT * FROM setup WHERE code='rc700-qhy600-bin2'")
    assert s is not None, "il setup è stato cancellato: la storia è persa"
    assert s["id"] == id_prima, "l'id è cambiato: i riferimenti storici puntano altrove"
    assert s["active"] == 0
    assert s["valid_to"] is not None


def test_la_data_di_dismissione_non_si_sposta(db, sites_dir):
    """Il secondo reconcile non deve riscrivere `valid_to` a oggi ogni giorno."""
    reconcile(sites_dir)
    senza_setup = textwrap.dedent(SITO).split("setups:")[0]
    (sites_dir / "cile.yml").write_text(senza_setup, encoding="utf-8")
    reconcile(sites_dir)
    quando = _riga("SELECT valid_to FROM setup WHERE code='rc700-qhy600-bin2'")["valid_to"]

    conn = connect()
    try:
        conn.execute("UPDATE setup SET valid_to='2020-01-01' WHERE code='rc700-qhy600-bin2'")
    finally:
        conn.close()
    reconcile(sites_dir)
    assert _riga("SELECT valid_to FROM setup WHERE code='rc700-qhy600-bin2'")["valid_to"] \
        == "2020-01-01" != quando


def test_active_false_nel_file_disattiva_senza_cancellare(db, sites_dir):
    reconcile(sites_dir)
    (sites_dir / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("active: true", "active: false"), encoding="utf-8"
    )
    reconcile(sites_dir)
    assert _riga("SELECT active FROM setup WHERE code='rc700-qhy600-bin2'")["active"] == 0


def test_il_limite_misurato_batte_quello_dichiarato(db, sites_dir):
    """Se ci sono misure, il file non le sovrascrive: sarebbe buttare via una notte."""
    reconcile(sites_dir)
    conn = connect()
    try:
        setup_id = conn.execute(
            "SELECT id FROM setup WHERE code='rc700-qhy600-bin2'").fetchone()["id"]
        conn.execute(
            """INSERT INTO setup_calibration (setup_id, measured_at, exposure_s, faintest_mag)
               VALUES (?, '2026-08-16T03:00:00Z', 120, 20.7)""",
            (setup_id,),
        )
        conn.execute("UPDATE setup SET vlim_ref=20.7 WHERE id=?", (setup_id,))
    finally:
        conn.close()

    report = reconcile(sites_dir)
    assert report["vlim_tenuti"] == ["rc700-qhy600-bin2"]
    assert _riga("SELECT vlim_ref FROM setup WHERE code='rc700-qhy600-bin2'")["vlim_ref"] == 20.7


def test_un_file_rotto_non_scrive_niente(db, sites_dir):
    """Verifica *prima*, scrittura poi: un secondo file invalido non deve
    lasciare metà configurazione applicata."""
    (sites_dir / "rotto.yml").write_text("code: altro\nname: x\n", encoding="utf-8")
    with pytest.raises(SiteConfigError):
        reconcile(sites_dir)
    assert _riga("SELECT count(*) AS n FROM observatory")["n"] == 0
