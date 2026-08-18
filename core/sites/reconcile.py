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
* **Un rename dichiarato è un rename, non una morte e una nascita**
  (`previous_codes:`). Il `code` fa da identità, ma un'identità che si può
  editare non è un'identità: correggere un codice faceva sparire la riga
  vecchia (disattivata, con un `valid_to` che raccontava una dismissione mai
  avvenuta) e nascere una riga nuova con un id nuovo — e con lei si staccavano
  `setup_calibration`, `observation_log` e `state_transition`. La calibrazione
  in particolare spariva **in silenzio**: `_has_calibration` cerca per `code`,
  non la trovava più, e il `vlim_ref` dichiarato tornava a comandare su quello
  misurato. Con `previous_codes` la riga si rinomina sul posto e tutto resta
  attaccato al suo id.
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
    # Quando qualcuno ha riletto per l'ultima volta la scheda del fornitore.
    # Non è la data di modifica del file: è la data in cui una persona è andata
    # a *controllare* che questi numeri fossero ancora quelli. Le due cose
    # divergono — si corregge un commento senza riverificare niente.
    ("specs_checked_at", "str", None),
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
    # Quanto costa un'ora di quel setup. Su un telescopio remoto affittato il
    # tempo si paga, e senza questo numero il ranking consiglia sempre lo
    # strumento più grande: `n × t` di pose è anche un conto in valuta, e una
    # sessione da un'ora su un 20" non è la stessa decisione di una su un 17".
    # `None` = non si paga (telescopio proprio), che è diverso da zero.
    ("cost_per_hour", "num", None),
    ("currency", "str", None),
    ("valid_from", "str", None),
    ("valid_to", "str", None),
    ("active", "bool", True),
    ("notes", "str", None),
]

# Chiavi che il file può contenere oltre ai campi delle tabelle. Tutto il resto
# è un errore: un `latitide:` scritto storto deve fermare il reconcile, non
# essere ignorato in silenzio lasciando l'osservatorio all'equatore.
# `previous_codes` non è una colonna: è un'istruzione al reconcile («questa
# riga si chiamava così»), e per questo sta fra le chiavi extra invece che nelle
# tabelle dei campi. Vale per tutte e quattro le entità, perché tutte e quattro
# hanno un `code` che prima o poi qualcuno vorrà correggere.
_EXTRA_KEYS = {
    "observatory": {"telescopes", "cameras", "setups", "horizon", "previous_codes"},
    "setup": {"telescope", "camera", "previous_codes"},
    "telescope": {"previous_codes"},
    "camera": {"previous_codes"},
}


def _verifica_fuso(tz: str, dove: str) -> None:
    """Il fuso dev'essere un nome IANA vero, e si controlla **qui**.

    Non è pedanteria: `America/Utah` non esiste (il fuso dello Utah è
    `America/Denver`), il reconcile lo accettava senza fiatare, e il guasto
    saltava fuori molto più tardi — dentro `night_events`, cioè dentro un job
    di fondo alle tre di notte, con un `ZoneInfoNotFoundError` che non nomina
    né il file né il sito. Il reconcile verifica tutto e poi scrive
    (MEMORANDUM 2026-08-16): un fuso inventato è esattamente il genere di cosa
    che deve fermarlo.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise SiteConfigError(
            f"{dove}: fuso orario sconosciuto '{tz}'. Serve un nome IANA "
            f"(«America/Denver», «America/Santiago», «Europe/Rome»), non il "
            f"nome dello stato o della regione."
        ) from exc


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
    ex: dict[str, str] = {}             # code dismesso da un rename → file

    def registra(code: str, path: Path, cosa: str) -> None:
        if code in visti:
            raise SiteConfigError(
                f"{path.name}: il codice '{code}' ({cosa}) è già usato in {visti[code]}. "
                "I codici sono chiavi stabili e devono essere unici."
            )
        visti[code] = path.name

    def rinomina(node: dict, code: str, path: Path, cosa: str) -> list[str]:
        """Verifica `previous_codes` e lo restituisce come lista di stringhe.

        Due controlli, e nessuno dei due è pedanteria:

        * un codice non può essere insieme il **vecchio** nome di una riga e il
          nome attuale di un'altra. `previous_codes: [cile-rc700]` in un file
          mentre un altro file dichiara ancora `code: cile-rc700` chiederebbe di
          rinominare una riga viva, cioè di far cambiare identità all'hardware
          di qualcun altro;
        * lo stesso vecchio codice non può essere reclamato da due entità: la
          riga è una, e non si sa a chi darla.

        L'ordine dei file è alfabetico e la verifica incrociata avviene alla
        fine (`_verifica_rinomine`), perché il file che *usa* un codice può
        essere letto dopo quello che lo reclama.
        """
        grezzo = node.get("previous_codes")
        if grezzo is None:
            return []
        if isinstance(grezzo, str):     # un codice solo si scrive anche senza lista
            grezzo = [grezzo]
        if not isinstance(grezzo, list) or not all(isinstance(x, str) for x in grezzo):
            raise SiteConfigError(
                f"{path.name} → {cosa} '{code}': 'previous_codes' dev'essere una "
                f"lista di codici, trovato {grezzo!r}"
            )
        for vecchio in grezzo:
            if vecchio == code:
                raise SiteConfigError(
                    f"{path.name} → {cosa} '{code}': 'previous_codes' contiene il "
                    f"codice attuale. Un rename verso se stesso non è un rename."
                )
            if vecchio in ex:
                raise SiteConfigError(
                    f"{path.name} → {cosa} '{code}': il codice dismesso '{vecchio}' "
                    f"è già reclamato in {ex[vecchio]}. La riga da rinominare è una."
                )
            ex[vecchio] = path.name
        return grezzo

    for path in files:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            raise SiteConfigError(f"{path.name}: file vuoto")
        obs = _take(raw, _OBSERVATORY, "observatory", path.name)
        registra(obs["code"], path, "osservatorio")
        obs["_previous"] = rinomina(raw, obs["code"], path, "osservatorio")
        _verifica_fuso(obs["timezone"], path.name)

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
            t["_previous"] = rinomina(node, t["code"], path, "telescopio")
            telescopi[t["code"]] = t

        camere = {}
        for node in raw.get("cameras") or []:
            c = _take(node, _CAMERA, "camera", f"{path.name} → cameras")
            registra(c["code"], path, "camera")
            c["_previous"] = rinomina(node, c["code"], path, "camera")
            camere[c["code"]] = c

        setups = []
        for node in raw.get("setups") or []:
            s = _take(node, _SETUP, "setup", f"{path.name} → setups")
            registra(s["code"], path, "setup")
            s["_previous"] = rinomina(node, s["code"], path, "setup")
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

    # Alla fine, quando tutti i file sono stati letti: un codice reclamato come
    # «vecchio nome» non può essere il nome attuale di qualcos'altro.
    for vecchio, dove in ex.items():
        if vecchio in visti:
            raise SiteConfigError(
                f"{dove}: 'previous_codes' contiene '{vecchio}', che è il codice "
                f"attuale di una voce in {visti[vecchio]}. Un rename sposta una "
                f"riga, non ne sequestra una viva."
            )

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


def _apply_rename(conn, table: str, code: str, previous: list[str], report: dict) -> None:
    """Rinomina sul posto la riga che si chiamava in un altro modo.

    Va chiamata **prima** dell'upsert: dopo, il codice nuovo esisterebbe già e
    ci sarebbero due righe per lo stesso strumento. È tutto qui il senso della
    funzione — l'`UPDATE ... SET code=?` tiene l'`id`, e con l'id restano
    attaccate `setup_calibration`, `observation_log` e `state_transition`.

    Tre casi, e due non fanno niente:

    * il codice nuovo **non** c'è e uno dei vecchi sì → si rinomina. È il caso
      per cui la funzione esiste;
    * il codice nuovo c'è già → il rename è stato applicato in un giro
      precedente, e il reconcile dev'essere idempotente. Ma se c'è **anche** una
      riga con un codice vecchio, allora lo strumento è già diviso in due (di
      solito perché il rename è stato fatto senza dichiararlo, e il giro prima
      ha disattivato la riga vecchia): non si fondono da sole — quale id
      sopravvive è una domanda con conseguenze su tre tabelle di storia — ma si
      dice a voce alta, invece di lasciare il fantasma lì in silenzio;
    * nessuna delle due c'è → è hardware nuovo, e `previous_codes` si riferisce
      a una riga che non è mai esistita in questo database. Succede a chi parte
      da un database vuoto con gli YAML già rinominati, ed è normale.
    """
    if not previous:
        return
    nuovo = conn.execute(f"SELECT id FROM {table} WHERE code=?", (code,)).fetchone()
    vecchie = [r for r in conn.execute(
        f"SELECT id, code, active FROM {table} "
        f"WHERE code IN ({','.join('?' * len(previous))})", previous).fetchall()]

    if nuovo is not None:
        for r in vecchie:
            log.warning(
                "%s '%s' e '%s' esistono tutti e due: il rename è arrivato dopo che "
                "il database aveva già creato la riga nuova. Le due righe non si "
                "fondono da sole — id %d resta con la sua storia.",
                table, r["code"], code, r["id"])
            report["rinomine_tardive"].append(f"{table}:{r['code']}→{code}")
        return

    if not vecchie:
        return
    if len(vecchie) > 1:
        raise SiteConfigError(
            f"{table} '{code}': 'previous_codes' trova più di una riga "
            f"({', '.join(r['code'] for r in vecchie)}). Quale sia lo strumento "
            f"non lo può decidere il reconcile."
        )

    r = vecchie[0]
    # `valid_to` si azzera **solo** se la riga era stata disattivata proprio
    # dall'assenza che il rename adesso spiega. Una riga dismessa sul serio e
    # poi rinominata resta dismessa: sarà `active: false` nello YAML a dirlo.
    conn.execute(f"UPDATE {table} SET code=? WHERE id=?", (code, r["id"]))
    report["rinominati"].append(f"{table}:{r['code']}→{code}")
    log.info("%s: rinominato '%s' → '%s' (id %d, storia conservata)",
             table, r["code"], code, r["id"])


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
        "creati": [], "aggiornati": [], "disattivati": [], "rinominati": [],
        "rinomine_tardive": [], "vlim_tenuti": [], "siti": len(sites),
    }

    conn = connect()
    try:
        with transaction(conn):
            codici = {"observatory": set(), "telescope": set(),
                      "camera": set(), "setup": set()}

            for site in sites:
                obs_cols = {k: v for k, v in site.items()
                            if k not in ("telescopes", "cameras", "setups", "file",
                                         "_previous")}
                _apply_rename(conn, "observatory", site["code"], site["_previous"], report)
                obs_id = _upsert(conn, "observatory", obs_cols, report)
                codici["observatory"].add(site["code"])

                telescopi = {}
                for t in site["telescopes"]:
                    telescopi[t["code"]] = t
                    _apply_rename(conn, "telescope", t["code"], t["_previous"], report)
                    cols = {k: v for k, v in t.items() if k != "_previous"}
                    t_id = _upsert(conn, "telescope", {**cols, "observatory_id": obs_id},
                                   report)
                    t["_id"] = t_id
                    codici["telescope"].add(t["code"])

                camere = {}
                for c in site["cameras"]:
                    camere[c["code"]] = c
                    _apply_rename(conn, "camera", c["code"], c["_previous"], report)
                    c["_id"] = _upsert(
                        conn, "camera",
                        {k: v for k, v in c.items() if k != "_previous"}, report)
                    codici["camera"].add(c["code"])

                for s in site["setups"]:
                    tel, cam = telescopi[s["telescope"]], camere[s["camera"]]
                    # Prima di ogni altra cosa, e in particolare **prima** di
                    # `_has_calibration`: quella cerca per `code`, e su un setup
                    # appena rinominato non troverebbe le misure che invece ci
                    # sono, riportando il `vlim_ref` dichiarato sopra a quello
                    # tarato sul campo.
                    _apply_rename(conn, "setup", s["code"], s["_previous"], report)
                    cols = {k: v for k, v in s.items()
                            if k not in ("telescope", "camera", "_previous")}
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
        "reconcile siti: %d creati, %d aggiornati, %d rinominati, %d disattivati",
        len(report["creati"]), len(report["aggiornati"]),
        len(report["rinominati"]), len(report["disattivati"]),
    )
    return report
