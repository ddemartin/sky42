"""Il pianificatore: tutto ciò che deve girare senza che nessuno lo chieda.

Sta **dentro il processo dell'app**, non in un cron separato. Un cron che apre
il database mentre l'interfaccia gira sarebbe un secondo scrittore su SQLite —
lo stesso ragionamento di stock42, e la ragione per cui non ci sono script da
mettere in crontab.

Tre scelte che vale la pena spiegare:

**I lavori pesanti girano in un processo separato** (`ProcessPoolExecutor` con
un solo posto). In un thread terrebbero il GIL e l'interfaccia diventerebbe
melmosa proprio mentre il catalogo si aggiorna. Uno solo alla volta perché il
Mac mini fa girare altro.

**Si controlla ogni 6 ore invece che a un orario preciso.** Le sorgenti si
aggiornano una volta al giorno ma a orari che si spostano: Lowell pubblica fra
le 08:00 e le 10:00 UT, «e nella data di Luna piena non prima delle 14:00».
Inseguire quegli orari è un bug che aspetta di succedere. Siccome il download è
condizionato all'ETag, un controllo che non trova niente costa una richiesta e
qualche kilobyte: si controlla spesso e si scarica solo quando serve.

**Al riavvio si recupera il tempo perso.** Un Mac mini si riavvia; APScheduler
da solo si limiterebbe a saltare le esecuzioni mancate. All'avvio si guarda
l'età dei dati e, se sono vecchi, si parte subito.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from apscheduler.executors.pool import ProcessPoolExecutor, ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from core.db import connect, get_setting
from core.timeutil import now_iso

log = logging.getLogger("sky42.scheduler")


@dataclass(frozen=True)
class JobSpec:
    name: str
    label: str
    func: Callable
    hours: int | None = None        # ogni N ore
    minutes: int | None = None      # oppure ogni N minuti (i watcher)
    cron: dict | None = None        # oppure un orario fisso (UTC)
    minute: int = 0
    heavy: bool = True              # in un processo a parte
    description: str = ""
    catchup_after_hours: float | None = None   # all'avvio, se i dati sono più vecchi
    # Come si misura l'età del *risultato* di questo job. Senza, si guarda
    # l'età dei dati della sorgente omonima — che vale per i sync e per nessun
    # altro: `night_plan` non ha una sorgente, ha una tabella che riempie.
    freshness: Callable[[], float | None] | None = None


def _jobs() -> list[JobSpec]:
    # Import qui e non in testa: il modulo viene caricato anche dai test, e
    # importare i servizi in testa creerebbe un ciclo con `jobs.py`.
    from services import (backup_service, candidate_service, ingest_service,
                          maintenance_service, night_service, radar_service,
                          screening_service, window_service)

    return [
        JobSpec("mpcorb_sync", "MPCORB extended", ingest_service.sync_mpcorb,
                hours=6, minute=5, catchup_after_hours=12,
                description="la fonte: identità, elementi, classe, ultima osservazione"),
        JobSpec("astorb_sync", "ASTORB", ingest_service.sync_astorb,
                hours=6, minute=20, catchup_after_hours=12,
                description="lo strato dell'incertezza CEU/PEU"),
        JobSpec("cometels_sync", "CometEls", ingest_service.sync_cometels,
                hours=6, minute=35, catchup_after_hours=12,
                description="le comete"),
        # Ogni sei ore e non una volta al giorno: il calcolo costa
        # millisecondi, e così la finestra di due settimane resta piena anche se
        # il Mac mini è stato spento per un giorno. `catchup_after_hours` la
        # rifà all'avvio se l'ultima è vecchia.
        JobSpec("night_plan", "Piano delle notti", night_service.run_night_plan,
                hours=6, minute=50, heavy=False, catchup_after_hours=12,
                freshness=night_service.plan_age_hours,
                description="crepuscoli e Luna per ogni sito attivo, due settimane avanti"),
        # Lo screening gira **dopo** i sync della notte e prima che qualcuno si
        # alzi: alle 02:10 UTC gli elementi sono quelli del giro delle 00:05 e
        # il Mac mini non ha nient'altro da fare. Un giro al giorno e non due:
        # le orbite cambiano una volta al giorno, e ricalcolare più spesso
        # riscriverebbe le stesse tracce.
        JobSpec("screening", "Screening", screening_service.run_screening,
                cron={"hour": 2}, minute=10, catchup_after_hours=36,
                freshness=screening_service.screening_age_hours,
                description="propaga la popolazione monitorata, scrive tracce e statistiche"),
        # Fra screening e radar, e non per comodità: legge `target_stats` (che
        # lo screening ha appena riscritto) e pubblica le ore utili che il radar
        # leggerà venti minuti dopo. Se non ha finito, il radar trova le
        # finestre di ieri e lo dice il loro `computed_at`: nessuno dei due
        # chiama l'altro.
        JobSpec("windows", "Finestre osservative", window_service.run_windows,
                cron={"hour": 2}, minute=20, catchup_after_hours=36,
                freshness=window_service.windows_age_hours,
                description="finestre e punteggio per (target × setup × notte), in massa"),
        # Mezz'ora dopo, che è molto più di quanto lo screening impieghi: se
        # per qualche motivo non ha finito, il radar legge le statistiche di
        # ieri e lo dice il loro `computed_at`. Un job non ne chiama un altro.
        JobSpec("radar_states", "Stati del radar", radar_service.run_radar,
                cron={"hour": 2}, minute=40, heavy=False, catchup_after_hours=36,
                freshness=radar_service.radar_age_hours,
                description="stati e transizioni per (target × setup), con isteresi"),
        # I due watcher che **perdono dati se non girano**: l'MPC riscrive le
        # liste e non conserva niente. Sono leggeri (10 kB per giro, con ETag) e
        # non pesanti, così girano anche mentre lo screening macina.
        JobSpec("neocp_poll", "Candidati NEOCP", candidate_service.poll_neocp,
                minutes=10, heavy=False, catchup_after_hours=1,
                freshness=lambda: candidate_service.poll_age_hours("NEOCP"),
                description="la lista dei candidati NEO, e la sua storia che nessun altro tiene"),
        JobSpec("pccp_poll", "Candidati cometari PCCP", candidate_service.poll_pccp,
                minutes=20, heavy=False, catchup_after_hours=2,
                freshness=lambda: candidate_service.poll_age_hours("PCCP"),
                description="la lista dei candidati cometari"),
        JobSpec("backup", "Backup dati non rigenerabili", backup_service.run_backup,
                cron={"hour": 3}, minute=0, heavy=False,
                description="candidati NEOCP, transizioni, osservazioni, watchlist"),
        JobSpec("housekeeping", "Manutenzione", maintenance_service.run_housekeeping,
                cron={"day_of_week": "sun", "hour": 4}, minute=0, heavy=False,
                description="pota i registri, riallinea le statistiche degli indici"),
    ]


class Scheduler:
    """Un solo pianificatore per processo. Si avvia da main.py."""

    def __init__(self) -> None:
        self._sched: BackgroundScheduler | None = None
        self.specs: dict[str, JobSpec] = {}

    # --- ciclo di vita ----------------------------------------------------

    def start(self) -> None:
        if self._sched is not None:
            return
        # Il client simulato dei test esegue main.py come `__main__` e ne
        # innesca gli `on_startup`: senza questa guardia una suite di test
        # accoderebbe download veri verso MPC e Lowell. Un test che tocca la
        # rete non è un test.
        import os

        if os.environ.get("SKY42_TESTING"):
            log.info("modo test: pianificatore non avviato")
            return
        if not get_setting("scheduler_enabled", True):
            log.info("pianificatore disattivato nelle impostazioni")
            return

        self._sched = BackgroundScheduler(
            executors={
                "default": ThreadPoolExecutor(1),
                # Un posto solo: i lavori pesanti non si accavallano mai, né
                # fra loro né con sé stessi.
                "heavy": ProcessPoolExecutor(1),
            },
            job_defaults={
                "coalesce": True,          # dopo uno spegnimento, una sola volta
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
            timezone=timezone.utc,
        )

        for spec in _jobs():
            self.specs[spec.name] = spec
            trigger, kwargs = self._trigger(spec)
            self._sched.add_job(
                spec.func, trigger, id=spec.name, name=spec.label,
                executor="heavy" if spec.heavy else "default", **kwargs,
            )
            if not self.is_enabled(spec.name):
                self._sched.pause_job(spec.name)

        self._sched.start()
        log.info("pianificatore avviato con %d lavori", len(self.specs))
        self._catchup()

    def shutdown(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None

    @staticmethod
    def _trigger(spec: JobSpec) -> tuple[str, dict]:
        if spec.minutes:
            return "cron", {"minute": f"*/{spec.minutes}"}
        if spec.hours:
            return "cron", {"hour": f"*/{spec.hours}", "minute": spec.minute}
        return "cron", {**(spec.cron or {}), "minute": spec.minute}

    # --- recupero all'avvio ------------------------------------------------

    def _catchup(self) -> None:
        """Dopo un riavvio: se i dati sono vecchi, si parte subito.

        Sfalsati di un minuto l'uno dall'altro, o all'accensione partirebbero
        tutti insieme — che è esattamente il momento in cui la macchina ha
        altro da fare.
        """
        from services.catalog_service import data_state

        state = data_state()
        delay = 1
        for spec in self.specs.values():
            if spec.catchup_after_hours is None or not self.is_enabled(spec.name):
                continue
            if spec.freshness is not None:
                age_h = spec.freshness()
            else:
                age_h = _age_hours((state.get(_source_of(spec.name)) or {}).get("ts"))
            if age_h is None or age_h > spec.catchup_after_hours:
                when = datetime.now(timezone.utc) + timedelta(minutes=delay)
                log.info("recupero all'avvio: %s (dati vecchi di %s)", spec.name,
                         "mai" if age_h is None else f"{age_h:.0f} h")
                self._sched.add_job(
                    spec.func, "date", run_date=when, id=f"{spec.name}:catchup",
                    name=f"{spec.label} (recupero)",
                    executor="heavy" if spec.heavy else "default",
                    replace_existing=True,
                )
                delay += 1

    # --- interrogazione e comandi -----------------------------------------

    @property
    def running(self) -> bool:
        return self._sched is not None and self._sched.running

    def is_enabled(self, name: str) -> bool:
        return bool(get_setting("job_enabled", {}).get(name, True))

    def set_enabled(self, name: str, enabled: bool) -> None:
        import json

        current = dict(get_setting("job_enabled", {}))
        current[name] = enabled
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO setting (key, value, updated_at) VALUES ('job_enabled', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (json.dumps(current), now_iso()),
            )
        finally:
            conn.close()
        if self._sched:
            (self._sched.resume_job if enabled else self._sched.pause_job)(name)

    def run_now(self, name: str) -> None:
        """Esegue subito, con lo stesso esecutore del lavoro pianificato."""
        spec = self.specs.get(name)
        if spec is None or self._sched is None:
            raise KeyError(name)
        self._sched.add_job(
            spec.func, "date", run_date=datetime.now(timezone.utc),
            id=f"{name}:manuale", name=f"{spec.label} (a mano)",
            executor="heavy" if spec.heavy else "default", replace_existing=True,
        )

    def status(self) -> list[dict]:
        """Riga per riga: quando gira, quando è girato, com'è finito."""
        last = _last_runs()
        out = []
        for name, spec in self.specs.items():
            job = self._sched.get_job(name) if self._sched else None
            prev = last.get(name, {})
            out.append({
                "name": name,
                "label": spec.label,
                "description": spec.description,
                "enabled": self.is_enabled(name),
                "cadenza": (f"ogni {spec.minutes} min" if spec.minutes
                            else f"ogni {spec.hours} h" if spec.hours
                            else _cron_label(spec)),
                "next_run": job.next_run_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                if job and job.next_run_time else None,
                "last_start": prev.get("started_at"),
                "last_status": prev.get("status"),
                "last_n": prev.get("n_processed"),
                "last_duration": prev.get("duration_s"),
                "last_error": prev.get("error"),
            })
        return out


def _cron_label(spec: JobSpec) -> str:
    c = spec.cron or {}
    giorni = {"sun": "domenica", "mon": "lunedì", "tue": "martedì", "wed": "mercoledì",
              "thu": "giovedì", "fri": "venerdì", "sat": "sabato"}
    if "day_of_week" in c:
        return f"{giorni.get(c['day_of_week'], c['day_of_week'])} {c.get('hour', 0):02d}:{spec.minute:02d} UTC"
    return f"ogni giorno {c.get('hour', 0):02d}:{spec.minute:02d} UTC"


def _source_of(job_name: str) -> str:
    return job_name.removesuffix("_sync")


def _age_hours(iso_ts: str | None) -> float | None:
    from core.timeutil import days_since

    d = days_since(iso_ts)
    return d * 24 if d is not None else None


def _last_runs() -> dict[str, dict]:
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT job_name, started_at, status, n_processed, duration_s, error
               FROM job_run r
               WHERE started_at = (SELECT max(started_at) FROM job_run
                                   WHERE job_name = r.job_name)"""
        ).fetchall()
        return {r["job_name"]: dict(r) for r in rows}
    finally:
        conn.close()


# Istanza unica, come in stock42.
scheduler = Scheduler()
