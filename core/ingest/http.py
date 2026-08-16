"""L'unico modulo che scarica file dall'esterno.

Tre proprietà che nessun ingestore deve reimplementare:

  * **download condizionato**: ETag e If-Modified-Since. Se la sorgente non è
    cambiata non si scaricano 170 MB per scoprirlo;
  * **scrittura atomica**: si scrive su `.part` e si rinomina alla fine, così
    un'interruzione non lascia mai un catalogo mezzo scritto che il parser
    leggerebbe come buono;
  * **tracciamento**: ogni scaricamento lascia una riga in `catalog_version`
    con hash e dimensione, e ogni chiamata una in `external_call`.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from core import config
from core.db import connect
from core.timeutil import now_iso

log = logging.getLogger("sky42.ingest.http")


@dataclass
class Download:
    source: str
    path: Path
    sha256: str
    size_bytes: int
    etag: str | None
    last_modified: str | None
    changed: bool          # False = la sorgente non è cambiata, si riusa il file locale
    version_id: int | None


def last_version(source: str) -> dict | None:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM catalog_version WHERE source=? ORDER BY downloaded_at DESC LIMIT 1",
            (source,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def fetch(source: str, url: str, filename: str, force: bool = False,
          dest_dir: Path | None = None) -> Download:
    """Scarica `url` in data/catalogs/`filename` se è cambiato.

    Con `force=True` scarica comunque (serve dopo un import fallito a metà: il
    file locale c'è ma il database no). `dest_dir` serve a chi non è un
    catalogo — le effemeridi planetarie vanno in data/ephem — e passa comunque
    di qui: il download condizionato, la scrittura atomica e la riga in
    `external_call` valgono per tutto ciò che entra dall'esterno.
    """
    config.ensure_dirs()
    dest = (dest_dir or config.CATALOG_DIR) / filename
    prev = last_version(source)

    headers = {"User-Agent": config.USER_AGENT}
    if prev and dest.exists() and not force:
        if prev.get("etag"):
            headers["If-None-Match"] = prev["etag"]
        if prev.get("last_modified"):
            headers["If-Modified-Since"] = prev["last_modified"]

    started = time.monotonic()
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    size = 0

    with httpx.Client(timeout=config.HTTP_TIMEOUT, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as resp:
            _log_call(source, url, resp.status_code, started, cached=resp.status_code == 304)

            if resp.status_code == 304:
                log.info("%s: non modificato (304), riuso %s", source, dest.name)
                return Download(source, dest, prev["sha256"], prev["size_bytes"],
                                prev.get("etag"), prev.get("last_modified"),
                                changed=False, version_id=prev["id"])

            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(1 << 20):
                    fh.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

            etag = resp.headers.get("etag")
            last_mod = resp.headers.get("last-modified")

    sha = digest.hexdigest()

    # Stesso contenuto con ETag diverso: capita quando il server rigenera il
    # file identico. Non è un aggiornamento e non deve far ripartire un import.
    if prev and prev["sha256"] == sha and dest.exists():
        tmp.unlink(missing_ok=True)
        log.info("%s: contenuto identico al precedente, nessun import", source)
        return Download(source, dest, sha, size, etag, last_mod,
                        changed=False, version_id=prev["id"])

    tmp.replace(dest)
    version_id = _record_version(source, url, etag, last_mod, sha, size, dest)
    log.info("%s: scaricato %.1f MB in %.1fs", source, size / 1e6, time.monotonic() - started)
    return Download(source, dest, sha, size, etag, last_mod, changed=True, version_id=version_id)


def mark_imported(version_id: int | None, n_records: int) -> None:
    if version_id is None:
        return
    conn = connect()
    try:
        conn.execute(
            "UPDATE catalog_version SET imported_at=?, n_records=? WHERE id=?",
            (now_iso(), n_records, version_id),
        )
    finally:
        conn.close()


def _record_version(source, url, etag, last_mod, sha, size, dest) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            """INSERT INTO catalog_version
               (source, url, etag, last_modified, sha256, size_bytes, downloaded_at, local_path)
               VALUES (?,?,?,?,?,?,?,?)""",
            (source, url, etag, last_mod, sha, size, now_iso(), str(dest)),
        )
        return int(cur.lastrowid)
    finally:
        conn.close()


def _log_call(service, endpoint, status, started, cached=False):
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO external_call (service, endpoint, called_at, status, duration_ms, cached)
               VALUES (?,?,?,?,?,?)""",
            (service, endpoint, now_iso(), status,
             (time.monotonic() - started) * 1000, int(cached)),
        )
    finally:
        conn.close()
