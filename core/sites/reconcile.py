"""Da `config/sites/*.yml` alle tabelle dell'hardware. Idempotente, e non cancella mai.

Gli YAML sono la fonte di verità; il database è un indice che si rifà da solo.
Il reconcile legge tutti i file, li verifica **tutti prima di scrivere
qualunque cosa**, e poi applica in una transazione sola: un file rotto lascia
il database esattamente com'era, invece di applicare metà configurazione e
fermarsi a metà — che è il modo in cui si scopre, tre settimane dopo, che un
setup ha il telescopio giusto e la camera di prima.

Due regole del progetto vivono qui dentro:

* **L'hardware non si cancella mai** (regola 3). Una voce sparita dallo YAML
  diventa `active = 0` con `valid_to` a oggi. `observation_log` punta a
  `setup(id)`, e fra tre anni «con quale campo era stata presa quell'immagine»
  deve avere una risposta.
* **Scala e campo sono derivati**, mai letti dal file. Scriverli a mano è il
  modo più facile per avere un campo che non corrisponde a quello delle
  immagini; qui vengono da focale, riduttore, pixel e binning e basta.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import yaml

from core import config
from core.db import connect, transaction

log = logging.getLogger("sky42.sites")

# Radianti → arcosecondi, in millimetri: 206265 arcsec/rad diviso 1000.
# pixel_scale = 206.265 * pixel_um * binning / focale_effettiva_mm
ARCSEC_PER_MM = 206.265


class SiteConfigError(ValueError):
    """Configurazione non valida. Il messaggio dice *quale file* e *quale voce*."""


# --- descrizione dichiarativa dei campi -------------------------------------
# Una tabella invece di venti `if`: quando il formato cresce si aggiunge una
# riga, e l'errore di validazione resta uguale per tutti i campi.
#
#   (nome, tipo, default)   default `_REQ` = obbligatorio, `None` = colonna NULL

_REQ = object()

_OBSERVATORY = [
    ("code", "str", _REQ),
    ("name", "str", _REQ),
    ("mpc_code", "str", None),
    ("latitude", "num", _REQ),
    ("longitude", "num", _REQ),
    ("altitude_m", "num", 0.0),
    ("timezone", "str", _REQ),
    ("sky_zenith_mag", "num", 21.6),
    ("extinction_k", "num", 0.16),
    ("valid_from", "str", None),
    ("valid_to", "str", None),
    ("active", "bool", True),
    ("notes", "str", None),
]

_TELESCOPE = [
    ("code", "str", _REQ),
    ("name", "str", _REQ),
    ("aperture_mm", "num", _REQ),
    ("focal_length_mm", "num", _REQ),
    ("design", "str", None),
    ("min_altitude_deg", "num", 20.0),
    ("max_track_rate_arcsec_min", "num", None),
    ("meridian_flip", "bool", False),
    ("valid_from", "str", None),
    ("valid_to", "str", None),
    ("active", "bool", True),
    ("notes", "str", None),
]

_CAMERA = [
    ("code", "str", _REQ),
    ("name", "str", _REQ),
    ("sensor", "str", None),
    ("pixel_um", "num", _REQ),
    ("pixels_x", "int", _REQ),
    ("pixels_y", "int", _REQ),
    ("read_noise_e", "num", None),
    ("dark_e_s", "num", None),
    ("full_well_e", "num", None),
    ("valid_from", "str", None),
    ("valid_to", "str", None),
    ("active", "bool", True),
    ("notes", "str", None),
]

_SETUP = [
    ("code", "str", _REQ),
    ("name", "str", _REQ),
    ("binning", "int", 1),
    ("filter", "str", None),
    ("focal_reducer", "num", 1.0),
    ("vlim_ref", "num", _REQ),
    ("vlim_ref_exposure_s", "num", 120.0),
    ("vlim_astrometric_delta", "num", -0.5),
    ("typical_exposure_s", "num", 120.0),
    ("max_exposure_s", "num", 600.0),
    ("max_airmass", "num", 2.2),
    ("min_altitude_deg", "num", None),
    ("typical_seeing_arcsec", "num", 2.0),
    ("sun_alt_max_deg", "num", -15.0),
    ("valid_from", "str", None),
    ("valid_to", "str", None),
    ("active", "bool", True),
    ("notes", "str", None),
]

# Chiavi che il file può contenere oltre ai campi delle tabelle. Tutto il resto
# è un errore: un `latitide:` scritto storto deve fermare il reconcile, non
# essere ignorato in silenzio lasciando l'osservatorio all'equatore.
_EXTRA_KEYS = {
    "observatory": {"telescopes", "cameras", "setups", "horizon"},
    "setup": {"telescope", "camera"},
    "telescope": set(),
    "camera": set(),
}


def _take(node: dict, spec: list[tuple], kind: str, where: str) -> dict:
    """Verifica un nodo YAML contro la sua tabella di campi e lo normalizza."""
    if not isinstance(node, dict):
        raise SiteConfigError(f"{where}: mi aspettavo una mappa, non {type(node).__name__}")

    noti = {n for n, _, _ in spec} | _EXTRA_KEYS[kind]
    for chiave in node:
        if chiave not in noti:
            raise SiteConfigError(f"{where}: campo sconosciuto '{chiave}'")

    out: dict = {}
    for name, tipo, default in spec:
        if name not in node or node[name] is None:
            if default is _REQ:
                raise SiteConfigError(f"{where}: manca il campo obbligatorio '{name}'")
            out[name] = default
            continue
        value = node[name]
        try:
            if tipo == "num":
                out[name] = float(value)
            elif tipo == "int":
                out[name] = int(value)
            elif tipo == "bool":
                out[name] = 1 if bool(value) else 0
            else:
                out[name] = str(value)
        except (TypeError, ValueError):
            raise SiteConfigError(
                f"{where}: '{name}' dovrebbe essere {tipo}, trovato {value!r}"
            ) from None

    # `valid_from: 2026-01-01` YAML lo legge come `datetime.date`, e `str()` di
    # una date è già ISO: nelle colonne di testo finisce nel formato giusto.
    return out


# --- lettura e verifica -----------------------------------------------------


def load_sites(sites_dir: Path | None = None) -> list[dict]:
    """Legge e verifica tutti gli YAML. Non tocca il database.

    Restituisce una lista di siti normalizzati; solleva `SiteConfigError` al
    primo problema, con il nome del file e il campo.
    """
    sites_dir = Path(sites_dir or config.SITES_DIR)
    if not sites_dir.is_dir():
        raise SiteConfigError(f"la cartella dei siti non esiste: {sites_dir}")

    files = sorted(p for p in sites_dir.iterdir() if p.suffix in (".yml", ".yaml"))
    if not files:
        raise SiteConfigError(f"nessun file di sito in {sites_dir}")

    sites: list[dict] = []
    visti: dict[str, str] = {}          # code → file, per tutte le entità

    def registra(code: str, path: Path, cosa: str) -> None:
        if code in visti:
            raise SiteConfigError(
                f"{path.name}: il codice '{code}' ({cosa}) è già usato in {visti[code]}. "
                "I codici sono chiavi stabili e devono essere unici."
            )
        visti[code] = path.name

    for path in files:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            raise SiteConfigError(f"{path.name}: file vuoto")
        obs = _take(raw, _OBSERVATORY, "observatory", path.name)
        registra(obs["code"], path, "osservatorio")

        horizon = raw.get("horizon")
        if horizon is not None:
            if not isinstance(horizon, list) or not all(
                isinstance(p, (list, tuple)) and len(p) == 2 for p in horizon
            ):
                raise SiteConfigError(
                    f"{path.name}: 'horizon' dev'essere una lista di coppie [azimut, altezza]"
                )
            obs["horizon_json"] = json.dumps([[float(a), float(h)] for a, h in horizon])
        else:
            obs["horizon_json"] = None

        telescopi = {}
        for node in raw.get("telescopes") or []:
            t = _take(node, _TELESCOPE, "telescope", f"{path.name} → telescopes")
            registra(t["code"], path, "telescopio")
            telescopi[t["code"]] = t

        camere = {}
        for node in raw.get("cameras") or []:
            c = _take(node, _CAMERA, "camera", f"{path.name} → cameras")
            registra(c["code"], path, "camera")
            camere[c["code"]] = c

        setups = []
        for node in raw.get("setups") or []:
            s = _take(node, _SETUP, "setup", f"{path.name} → setups")
            registra(s["code"], path, "setup")
            for campo, disponibili, cosa in (
                ("telescope", telescopi, "telescopio"),
                ("camera", camere, "camera"),
            ):
                riferimento = node.get(campo)
                if riferimento not in disponibili:
                    raise SiteConfigError(
                        f"{path.name} → setup '{s['code']}': {cosa} '{riferimento}' "
                        f"non dichiarato in questo file (ci sono: "
                        f"{', '.join(sorted(disponibili)) or 'nessuno'})"
                    )
            s["telescope"] = node["telescope"]
            s["camera"] = node["camera"]
            if s["binning"] < 1:
                raise SiteConfigError(f"{path.name} → setup '{s['code']}': binning < 1")
            if s["focal_reducer"] <= 0:
                raise SiteConfigError(
                    f"{path.name} → setup '{s['code']}': focal_reducer dev'essere > 0"
                )
            setups.append(s)

        obs["file"] = path.name
        obs["telescopes"] = list(telescopi.values())
        obs["cameras"] = list(camere.values())
        obs["setups"] = setups
        sites.append(obs)

    return sites


# --- i derivati -------------------------------------------------------------


def derive_optics(telescope: dict, camera: dict, setup: dict) -> dict:
    """Scala del pixel e campo, dagli unici numeri che li determinano.

        focale_eff  = focal_length_mm × focal_reducer
        pixel_scale = 206.265 × pixel_um × binning / focale_eff      arcsec/px
        fov         = pixel_scale × (pixel / binning) / 60           arcmin

    Il binning compare due volte perché fa due cose opposte: allarga il pixel e
    riduce il loro numero. Il campo, giustamente, non cambia.
    """
    focale = telescope["focal_length_mm"] * setup["focal_reducer"]
    if focale <= 0:
        raise SiteConfigError(f"setup '{setup['code']}': focale effettiva non positiva")
    binning = setup["binning"]
    scala = ARCSEC_PER_MM * camera["pixel_um"] * binning / focale
    return {
        "pixel_scale_arcsec": scala,
        "fov_x_arcmin": scala * (camera["pixels_x"] // binning) / 60.0,
        "fov_y_arcmin": scala * (camera["pixels_y"] // binning) / 60.0,
    }


# --- scrittura --------------------------------------------------------------


def _uguale(vecchio, nuovo) -> bool:
    """Confronto tollerante sui reali: 0.34166... riletto da SQLite è lo stesso numero."""
    if isinstance(vecchio, float) or isinstance(nuovo, float):
        if vecchio is None or nuovo is None:
            return vecchio is nuovo
        return abs(float(vecchio) - float(nuovo)) <= 1e-12 * max(1.0, abs(float(nuovo)))
    return vecchio == nuovo


def _upsert(conn, table: str, values: dict, report: dict) -> int:
    """INSERT o UPDATE per `code`, e restituisce l'id. Non cancella niente.

    Si scrive **solo ciò che è davvero cambiato**: un UPDATE incondizionato
    riuscirebbe sempre, e il rendiconto direbbe «aggiornati 4» a ogni giro
    anche senza aver toccato un file. Il rendiconto serve proprio a distinguere
    i due casi.
    """
    esiste = conn.execute(f"SELECT * FROM {table} WHERE code=?", (values["code"],)).fetchone()

    if esiste is None:
        cols = list(values)
        conn.execute(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [values[c] for c in cols],
        )
        report["creati"].append(f"{table}:{values['code']}")
        return int(conn.execute(f"SELECT id FROM {table} WHERE code=?",
                                (values["code"],)).fetchone()["id"])

    diverse = {c: v for c, v in values.items()
               if c != "code" and not _uguale(esiste[c], v)}
    if diverse:
        conn.execute(
            f"UPDATE {table} SET {','.join(f'{c}=?' for c in diverse)} WHERE code=?",
            list(diverse.values()) + [values["code"]],
        )
        report["aggiornati"].append(f"{table}:{values['code']}")
    return int(esiste["id"])


def _deactivate_missing(conn, table: str, tenuti: set[str], report: dict) -> None:
    """Quello che non è più nello YAML esce di servizio, non sparisce.

    `valid_to` si scrive solo se è vuoto: la data di dismissione è quella della
    prima volta che ce ne siamo accorti, e un secondo reconcile non deve
    spostarla in avanti ogni giorno.
    """
    oggi = date.today().isoformat()
    righe = conn.execute(f"SELECT id, code, active, valid_to FROM {table}").fetchall()
    for r in righe:
        if r["code"] in tenuti or not r["active"]:
            continue
        conn.execute(
            f"UPDATE {table} SET active=0, valid_to=COALESCE(valid_to, ?) WHERE id=?",
            (oggi, r["id"]),
        )
        report["disattivati"].append(f"{table}:{r['code']}")


def _has_calibration(conn, setup_code: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM setup_calibration c JOIN setup s ON s.id = c.setup_id
           WHERE s.code = ? LIMIT 1""",
        (setup_code,),
    ).fetchone()
    return row is not None


def reconcile(sites_dir: Path | None = None) -> dict:
    """Allinea il database agli YAML e restituisce il rendiconto di cosa è cambiato.

    Idempotente: eseguito due volte di fila, la seconda non cambia niente.
    """
    sites = load_sites(sites_dir)      # tutto verificato *prima* di aprire la transazione

    report: dict = {
        "creati": [], "aggiornati": [], "disattivati": [],
        "vlim_tenuti": [], "siti": len(sites),
    }

    conn = connect()
    try:
        with transaction(conn):
            codici = {"observatory": set(), "telescope": set(),
                      "camera": set(), "setup": set()}

            for site in sites:
                obs_cols = {k: v for k, v in site.items()
                            if k not in ("telescopes", "cameras", "setups", "file")}
                obs_id = _upsert(conn, "observatory", obs_cols, report)
                codici["observatory"].add(site["code"])

                telescopi = {}
                for t in site["telescopes"]:
                    telescopi[t["code"]] = t
                    t_id = _upsert(conn, "telescope", {**t, "observatory_id": obs_id}, report)
                    t["_id"] = t_id
                    codici["telescope"].add(t["code"])

                camere = {}
                for c in site["cameras"]:
                    camere[c["code"]] = c
                    c["_id"] = _upsert(conn, "camera", c, report)
                    codici["camera"].add(c["code"])

                for s in site["setups"]:
                    tel, cam = telescopi[s["telescope"]], camere[s["camera"]]
                    cols = {k: v for k, v in s.items() if k not in ("telescope", "camera")}
                    cols.update(derive_optics(tel, cam, s))
                    cols["observatory_id"] = obs_id
                    cols["telescope_id"] = tel["_id"]
                    cols["camera_id"] = cam["_id"]

                    # Il limite dichiarato è una stima iniziale; dove ci sono
                    # misure vere, comandano quelle. Riportare il file sopra la
                    # calibrazione significherebbe buttare via ogni notte di
                    # taratura al primo `git pull`.
                    if _has_calibration(conn, s["code"]):
                        misurato = conn.execute(
                            "SELECT vlim_ref FROM setup WHERE code=?", (s["code"],)
                        ).fetchone()
                        cols["vlim_ref"] = misurato["vlim_ref"]
                        report["vlim_tenuti"].append(s["code"])

                    _upsert(conn, "setup", cols, report)
                    codici["setup"].add(s["code"])

            # L'ordine conta: prima i setup, poi ciò che referenziano.
            for table in ("setup", "telescope", "camera", "observatory"):
                _deactivate_missing(conn, table, codici[table], report)
    finally:
        conn.close()

    log.info(
        "reconcile siti: %d creati, %d aggiornati, %d disattivati",
        len(report["creati"]), len(report["aggiornati"]), len(report["disattivati"]),
    )
    return report
