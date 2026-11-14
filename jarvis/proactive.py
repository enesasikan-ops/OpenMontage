"""Les initiatives de Jarvis : il parle en premier quand c'est utile.

- Briefing du matin (JARVIS_BRIEFING=08:00) : météo, rappels du jour, liste de
  courses, état du PC. S'il n'a pas pu être donné dans les 3 heures (PC éteint),
  il est sauté : pas de « bonjour » à 20 h.
- Alertes (JARVIS_ALERTES=1) : disque presque plein, antivirus désactivé,
  redémarrage conseillé. Chaque problème est signalé au plus une fois par jour.
- Heures de silence (JARVIS_SILENCE=22:00-07:00) : rien de tout cela la nuit.
- Sentinelle (JARVIS_SENTINELLE=1, voir security.py) : vérifiée toutes les 5 minutes ;
  les alertes critiques passent même la nuit, les simples nouveautés attendent le matin.

Les messages sont construits sans le modèle local : ils arrivent même s'il est occupé.
"""

import threading
from datetime import datetime, time as dtime, timedelta
from typing import Callable

import config
import persona
import skills
from skills import JsonStore, Lists, Reminders

BRIEFING_WINDOW = timedelta(hours=3)
ALERT_EVERY = timedelta(hours=1)
SECURITY_EVERY = timedelta(minutes=5)


def parse_time(text: str) -> dtime | None:
    try:
        hour, minute = text.strip().split(":")
        return dtime(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def in_quiet_hours(now: datetime, spec: str = "") -> bool:
    spec = config.QUIET_HOURS if spec == "" else spec
    start, _, end = spec.partition("-")
    start, end = parse_time(start), parse_time(end)
    if start is None or end is None or start == end:
        return False
    t = now.time()
    return start <= t < end if start < end else (t >= start or t < end)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1]


class Proactive(threading.Thread):
    def __init__(self, reminders: Reminders, lists: Lists, notify: Callable[[str], None],
                 now: Callable[[], datetime] = skills._now,
                 weather: Callable[[], str] = skills.weather,
                 alerts: Callable[[], dict] = skills.pc_alerts,
                 security: Callable[[], list] | None = None,
                 interval_s: float = 60):
        super().__init__(daemon=True, name="jarvis-initiatives")
        self.reminders, self.lists, self.notify = reminders, lists, notify
        self.now, self.weather, self.alerts = now, weather, alerts
        self.interval_s = interval_s
        self.state = JsonStore(config.PROACTIVE_FILE, {"dernier_briefing": "", "alertes": {}})
        self._halt = threading.Event()
        self._last_alert_check: datetime | None = None
        self.security = security
        self._last_security_check: datetime | None = None
        self._held: list[str] = []  # nouveautés non critiques, gardées pendant les heures de silence

    # --- Briefing ------------------------------------------------------------------

    def briefing_text(self, alerts: dict | None = None) -> str:
        now = self.now()
        parts = [persona.briefing_intro(now.hour)]
        if config.CITY and not config.OFFLINE:
            meteo = self.weather()
            if meteo.startswith("À "):
                parts.append(meteo)
        today = self.reminders.today()
        if today:
            parts.append("Au programme aujourd'hui : " + _join(today) + ".")
        else:
            parts.append("Aucun rappel prévu aujourd'hui.")
        courses = self.lists.read("courses")
        if courses.startswith("Liste courses"):
            count = len(courses.split(": ", 1)[1].split(", "))
            parts.append(f"La liste de courses compte {count} article{'s' if count > 1 else ''}.")
        alerts = self.alerts() if alerts is None else alerts
        if alerts:
            parts.append("À signaler : " + _join(list(alerts.values())) + ".")
        else:
            parts.append("L'ordinateur se porte bien.")
        return " ".join(parts)

    def _briefing_due(self, now: datetime) -> bool:
        at = parse_time(config.BRIEFING_TIME)
        if at is None or self.state.data.get("dernier_briefing") == now.date().isoformat():
            return False
        start = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        return start <= now < start + BRIEFING_WINDOW

    # --- Alertes ---------------------------------------------------------------------

    def _new_alerts(self, now: datetime, alerts: dict) -> list[str]:
        """Alertes pas encore signalées aujourd'hui ; les marque comme signalées."""
        today = now.date().isoformat()
        seen = self.state.data.setdefault("alertes", {})
        fresh = [text for key, text in alerts.items() if seen.get(key) != today]
        for key in alerts:
            seen[key] = today
        return fresh

    # --- Boucle ----------------------------------------------------------------------

    def _security_tick(self, now: datetime) -> None:
        """Sentinelle : les alertes critiques partent tout de suite, même la nuit."""
        if self.security is None:
            return
        due = (self._last_security_check is None
               or now - self._last_security_check >= SECURITY_EVERY)
        if due:
            self._last_security_check = now
            try:
                events = self.security()
            except Exception as exc:
                print(f"[sentinelle] {exc}")
                events = []
            critical = [text for is_critical, text in events if is_critical]
            self._held += [text for is_critical, text in events if not is_critical]
            if critical:
                self.notify(persona.security_alert() + " " + _join(critical) + ".")
        if self._held and not in_quiet_hours(now):
            self.notify(persona.security_info() + " " + _join(self._held) + ".")
            self._held = []

    def tick(self) -> None:
        now = self.now()
        self._security_tick(now)
        if in_quiet_hours(now):
            return
        # Relit l'état sur le disque : si le mode vocal et le bot Telegram tournent
        # tous les deux, le briefing n'est donné qu'une fois.
        self.state = JsonStore(config.PROACTIVE_FILE, {"dernier_briefing": "", "alertes": {}})
        with self.state.lock:
            try:
                if self._briefing_due(now):
                    alerts = self.alerts() if config.ALERTS else {}
                    self._new_alerts(now, alerts)  # déjà dites dans le briefing
                    self.state.data["dernier_briefing"] = now.date().isoformat()
                    self.state.save()
                    self.notify(self.briefing_text(alerts))
                    return
                check_due = (self._last_alert_check is None
                             or now - self._last_alert_check >= ALERT_EVERY)
                if config.ALERTS and check_due:
                    self._last_alert_check = now
                    fresh = self._new_alerts(now, self.alerts())
                    if fresh:
                        self.state.save()
                        self.notify(persona.alert_intro() + " " + _join(fresh) + ".")
            except Exception as exc:  # une initiative ratée ne doit pas arrêter Jarvis
                print(f"[initiatives] {exc}")

    def run(self) -> None:
        while not self._halt.is_set():
            self.tick()
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()
