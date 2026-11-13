"""Tableau de bord Jarvis : une page plein écran pour la télé (ou un navigateur).

    python dashboard.py

Un petit serveur local sert la page et lui envoie les vraies données de Jarvis
(heure, météo, rappels, courses, maison, sécurité, système), rafraîchies en continu.
Branche le mini-PC sur la télé en HDMI et ouvre http://localhost:8765 en plein écran.

Par défaut, le serveur n'écoute que sur l'ordinateur (localhost). Pour l'afficher
depuis une tablette sur ton réseau, mets JARVIS_ECRAN_HOTE=0.0.0.0 (voir le README).
"""

import json
import logging
import hmac
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import config  # noqa: E402
import persona  # noqa: E402
import skills  # noqa: E402

log = logging.getLogger("jarvis.ecran")
HTML_FILE = Path(__file__).parent / "dashboard.html"

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


class Cache:
    """Garde un résultat coûteux en mémoire pendant `ttl` secondes."""

    def __init__(self, ttl: float, produce: Callable, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.produce, self.clock = ttl, produce, clock
        self._value = None
        self._at = -1e9

    def get(self):
        now = self.clock()
        if now - self._at >= self.ttl:
            try:
                self._value = self.produce()
            except Exception as exc:  # une source en panne ne doit pas vider l'écran
                log.warning("source indisponible : %s", exc)
                self._value = self._value if self._value is not None else {}
            self._at = now
        return self._value


class StateProvider:
    """Assemble l'état affiché, avec des caches pour ne pas marteler le réseau."""

    def __init__(self, reminders, lists, home=None, sentinel=None,
                 now: Callable[[], datetime] = skills._now,
                 weather: Callable[[], str] = skills.weather,
                 pc_status: Callable[[], str] = skills.pc_status,
                 clock: Callable[[], float] = time.monotonic):
        self.reminders, self.lists, self.home, self.sentinel = reminders, lists, home, sentinel
        self.now = now
        self._weather = Cache(900, lambda: weather(), clock)       # météo : 15 min
        self._pc = Cache(30, lambda: pc_status(), clock)           # état PC : 30 s
        self._home = Cache(10, self._home_overview, clock)         # maison : 10 s
        self._security = Cache(120, self._security_overview, clock)  # sécurité : 2 min

    # --- Sources ---------------------------------------------------------------------

    def _home_overview(self) -> dict:
        if self.home is None or not self.home.configured:
            return {"configure": False, "appareils": []}
        states = self.home.states()
        devices, temps = [], []
        for e in states:
            domain = e["entity_id"].split(".")[0]
            if domain in ("light", "switch") and e.get("state") in ("on", "off"):
                devices.append({"nom": self.home._name(e), "etat": "on" if e["state"] == "on" else "off"})
            elif domain == "lock":
                devices.append({"nom": self.home._name(e),
                                "etat": "lock" if e.get("state") == "locked" else "unlock"})
            elif e["entity_id"].startswith("sensor.") \
                    and e.get("attributes", {}).get("unit_of_measurement") in ("°C", "C"):
                temps.append({"nom": self.home._name(e), "valeur": f"{e.get('state')}°"})
        return {"configure": True, "appareils": devices[:6], "temperatures": temps[:3]}

    def _security_overview(self) -> list[dict]:
        if self.sentinel is None:
            return []
        text = self.sentinel.report()
        out = []
        for part in text.split(". "):
            part = part.strip().rstrip(".")
            if not part:
                continue
            niveau = "crit" if part.startswith("ATTENTION") else "ok"
            out.append({"libelle": part.replace("ATTENTION, ", ""), "niveau": niveau})
        return out

    def _reminders_today(self) -> list[dict]:
        out = []
        for r in self.reminders.store.data.get("rappels", []):
            due = datetime.fromisoformat(r["echeance"])
            now = self.now()
            if due.date() == now.date() and due >= now:
                out.append({"heure": f"{due.hour:02d}:{due.minute:02d}", "texte": r["message"]})
        return sorted(out, key=lambda x: x["heure"])[:6]

    def _weather_parsed(self) -> dict:
        text = self._weather.get() if config.CITY and not config.OFFLINE else ""
        return {"texte": text} if isinstance(text, str) and text.startswith("À ") else {}

    # --- État complet ------------------------------------------------------------------

    def state(self) -> dict:
        now = self.now()
        courses = ""
        try:
            courses = self.lists.read("courses")
        except Exception:
            pass
        n_courses = len(courses.split(": ", 1)[1].split(", ")) if courses.startswith("Liste courses") else 0
        return {
            "heure": f"{now.hour:02d}:{now.minute:02d}",
            "date": f"{JOURS[now.weekday()]} {now.day} {MOIS[now.month - 1]}",
            "salutation": persona.greeting(now.hour),
            "titre": persona.title(),
            "meteo": self._weather_parsed(),
            "rappels": self._reminders_today(),
            "courses": n_courses,
            "maison": self._home.get(),
            "securite": self._security.get(),
            "pc": self._pc.get(),
        }


class Handler(BaseHTTPRequestHandler):
    provider: StateProvider = None  # injecté par make_server
    html: bytes = b""
    token: str = ""                 # si défini, exigé sur chaque requête (?jeton=...)

    def log_message(self, *args):  # silence : pas de log par requête
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _autorise(self, query: str) -> bool:
        if not self.token:            # pas de jeton configuré : accès libre (ex. en local)
            return True
        fourni = parse_qs(query).get("jeton", [""])[0]
        return hmac.compare_digest(fourni, self.token)  # comparaison à temps constant

    def do_GET(self):
        parsed = urlparse(self.path)
        if not self._autorise(parsed.query):
            self._send(401, b"jeton requis", "text/plain; charset=utf-8")
            return
        if parsed.path in ("/", "/index.html"):
            self._send(200, self.html, "text/html; charset=utf-8")
        elif parsed.path == "/api/etat":
            body = json.dumps(self.provider.state(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"introuvable", "text/plain; charset=utf-8")

    do_HEAD = do_GET


def make_server(provider: StateProvider, host: str, port: int,
                html_path: Path = HTML_FILE, token: str = "") -> ThreadingHTTPServer:
    handler = type("JarvisHandler", (Handler,),
                   {"provider": provider, "html": html_path.read_bytes(), "token": token})
    return ThreadingHTTPServer((host, port), handler)


def _datetime_now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from security import Sentinel
    from smarthome import SmartHome

    reminders = skills.Reminders(config.REMINDERS_FILE)
    lists = skills.Lists(config.LISTS_FILE)
    home = SmartHome()
    sentinel = Sentinel(config.SENTINEL_FILE) if config.SENTINEL else None
    provider = StateProvider(reminders, lists, home, sentinel)

    server = make_server(provider, config.DASHBOARD_HOST, config.DASHBOARD_PORT,
                         token=config.DASHBOARD_TOKEN)
    local = config.DASHBOARD_HOST in ("127.0.0.1", "localhost")
    where = "cet ordinateur uniquement" if local else f"le réseau ({config.DASHBOARD_HOST})"
    print(f"🖥️  Tableau de bord Jarvis sur http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}")
    print(f"   Accessible depuis : {where}. Ctrl+C pour arrêter.")
    if not local and not config.DASHBOARD_TOKEN:
        print("   ⚠️  Exposé au réseau SANS jeton : tout le monde sur le Wi-Fi peut le lire.")
        print("      Ajoute JARVIS_ECRAN_JETON=un_secret dans .env, puis ouvre /?jeton=un_secret")
    elif config.DASHBOARD_TOKEN:
        print(f"   🔒 Jeton requis : ouvre http://{config.DASHBOARD_HOST}:{config.DASHBOARD_PORT}/?jeton=...")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
