"""Compétences supplémentaires de Jarvis : rappels, calcul, météo, listes, état du PC.

Tout est local, sauf la météo (voir `meteo`), coupée en mode hors ligne.
"""

import ast
import json
import math
import operator
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config
from tools import Tool

# --- Petit stockage JSON partagé -------------------------------------------------


class JsonStore:
    def __init__(self, path: Path, default: Any):
        self.path = path
        self.lock = threading.Lock()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.data = default

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


# --- Rappels -----------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _when_text(due: datetime, now: datetime) -> str:
    if due.date() == now.date():
        day = "aujourd'hui"
    elif due.date() == (now + timedelta(days=1)).date():
        day = "demain"
    else:
        day = f"le {due.day:02d}/{due.month:02d}"
    return f"{day} à {due.hour}h{due.minute:02d}"


class Reminders:
    """Rappels enregistrés sur le disque : ils survivent à un redémarrage."""

    def __init__(self, path: Path, now: Callable[[], datetime] = _now):
        self.store = JsonStore(path, {"prochain_id": 1, "rappels": []})
        self.now = now

    def add(self, message: str, dans_minutes: float | None = None, date_heure: str = "") -> str:
        now = self.now()
        if dans_minutes not in (None, ""):
            try:
                due = now + timedelta(minutes=float(dans_minutes))
            except (TypeError, ValueError):
                return "Durée illisible : donne un nombre de minutes."
        elif date_heure:
            try:
                due = datetime.fromisoformat(date_heure.strip().replace(" ", "T"))
            except ValueError:
                return "Date illisible. Format attendu : AAAA-MM-JJ HH:MM (ex. 2026-11-14 08:30)."
            if due.tzinfo is None:
                due = due.replace(tzinfo=now.tzinfo)
        else:
            return "Il me faut une durée (dans_minutes) ou une date (date_heure)."
        if due <= now:
            return "Ce moment est déjà passé : je n'ai rien programmé."
        with self.store.lock:
            rid = self.store.data["prochain_id"]
            self.store.data["prochain_id"] = rid + 1
            self.store.data["rappels"].append(
                {"id": rid, "message": message.strip(), "echeance": due.isoformat()})
            self.store.save()
        return f"Rappel n°{rid} programmé {_when_text(due, now)} : {message.strip()}"

    def list_text(self) -> str:
        now = self.now()
        with self.store.lock:
            items = sorted(self.store.data["rappels"], key=lambda r: r["echeance"])
        if not items:
            return "Aucun rappel en attente."
        return "\n".join(
            f"n°{r['id']} : {r['message']} ({_when_text(datetime.fromisoformat(r['echeance']), now)})"
            for r in items)

    def cancel(self, numero: int) -> str:
        try:
            numero = int(numero)
        except (TypeError, ValueError):
            return "Numéro de rappel illisible."
        with self.store.lock:
            before = len(self.store.data["rappels"])
            self.store.data["rappels"] = [r for r in self.store.data["rappels"] if r["id"] != numero]
            if len(self.store.data["rappels"]) == before:
                return f"Je n'ai pas de rappel n°{numero}."
            self.store.save()
        return f"Rappel n°{numero} annulé."

    def today(self) -> list[str]:
        """Rappels prévus d'ici la fin de la journée, avec leur heure."""
        now = self.now()
        with self.store.lock:
            items = sorted(self.store.data["rappels"], key=lambda r: r["echeance"])
        out = []
        for r in items:
            due = datetime.fromisoformat(r["echeance"])
            if due.date() == now.date():
                out.append(f"{r['message']} à {due.hour}h{due.minute:02d}")
        return out

    def pop_due(self) -> list[str]:
        """Retire et renvoie les rappels arrivés à échéance."""
        now = self.now()
        with self.store.lock:
            due = [r for r in self.store.data["rappels"]
                   if datetime.fromisoformat(r["echeance"]) <= now]
            if due:
                self.store.data["rappels"] = [r for r in self.store.data["rappels"] if r not in due]
                self.store.save()
        return [r["message"] for r in due]


class ReminderWatcher(threading.Thread):
    """Surveille les rappels en arrière-plan et prévient quand l'heure arrive."""

    def __init__(self, reminders: Reminders, notify: Callable[[str], None], interval_s: float = 5):
        super().__init__(daemon=True, name="jarvis-rappels")
        self.reminders = reminders
        self.notify = notify
        self.interval_s = interval_s
        self._halt = threading.Event()

    def tick(self) -> None:
        for message in self.reminders.pop_due():
            try:
                self.notify(f"⏰ Rappel : {message}")
            except Exception as exc:  # un rappel raté ne doit pas arrêter la surveillance
                print(f"[rappels] Impossible d'envoyer le rappel : {exc}")

    def run(self) -> None:
        while not self._halt.is_set():
            self.tick()
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()


# --- Calcul ------------------------------------------------------------------------

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {"sqrt": math.sqrt, "racine": math.sqrt, "abs": abs, "round": round,
          "arrondi": round, "min": min, "max": max}
_CONSTS = {"pi": math.pi}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 200 or abs(left) > 1e6):
            raise ValueError("puissance trop grande")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("expression non autorisée")


def calculate(expression: str) -> str:
    """Calcule une expression arithmétique, sans jamais exécuter de code."""
    expr = expression.strip().replace("×", "*").replace("÷", "/").replace("^", "**")
    expr = re.sub(r"(\d)\s*%", r"\1/100", expr)
    if not re.search(r"[a-zA-Z]", expr):  # « 3,5 » = 3.5, sauf dans min(1, 2)
        expr = re.sub(r"(\d),(\d)", r"\1.\2", expr)
    if len(expr) > 200:
        return "Calcul trop long."
    try:
        value = _eval(ast.parse(expr, mode="eval").body)
    except ZeroDivisionError:
        return "Division par zéro impossible."
    except (ValueError, SyntaxError, TypeError, OverflowError):
        return f"Je ne sais pas calculer « {expression} »."
    if isinstance(value, float):
        value = round(value, 6)
        if value == int(value):
            value = int(value)
    return f"{expression.strip()} = {str(value).replace('.', ',')}"


# --- Météo -----------------------------------------------------------------------------

WEATHER_CODES = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant", 51: "bruine légère", 53: "bruine",
    55: "bruine forte", 61: "pluie faible", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "pluie verglaçante", 71: "neige faible", 73: "neige",
    75: "fortes chutes de neige", 77: "grésil", 80: "averses", 81: "averses",
    82: "fortes averses", 85: "averses de neige", 86: "averses de neige",
    95: "orage", 96: "orage avec grêle", 99: "orage avec grêle",
}


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "assistant-vocal"})
    for attempt in (1, 2):  # une seconde chance en cas de coupure passagère
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (URL fixe, https)
                return json.loads(response.read().decode("utf-8"))
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1)
    raise OSError("inatteignable")


def weather(ville: str = "", fetch: Callable[[str], dict] = _fetch_json) -> str:
    """Météo du jour et de demain via open-meteo.com (gratuit, sans compte).

    Seul le nom de la ville est envoyé à ce service.
    """
    if config.OFFLINE:
        return "Je suis en mode hors ligne : pas de météo."
    ville = (ville or config.CITY).strip()
    if not ville:
        return "Pour quelle ville ? (Tu peux régler JARVIS_VILLE dans .env.)"
    try:
        geo = fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&language=fr&name="
                    + urllib.parse.quote(ville))
        if not geo.get("results"):
            return f"Je ne trouve pas la ville « {ville} »."
        place = geo["results"][0]
        data = fetch(
            "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=2"
            f"&latitude={place['latitude']}&longitude={place['longitude']}"
            "&current=temperature_2m,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max")
        cur, day = data["current"], data["daily"]

        def sky(code: int) -> str:
            return WEATHER_CODES.get(code, "temps variable")

        return (
            f"À {place['name']} : {round(cur['temperature_2m'])} degrés, {sky(cur['weather_code'])}, "
            f"vent {round(cur['wind_speed_10m'])} km/h. "
            f"Aujourd'hui : de {round(day['temperature_2m_min'][0])} à {round(day['temperature_2m_max'][0])} degrés, "
            f"{day['precipitation_probability_max'][0]} % de risque de pluie. "
            f"Demain : {sky(day['weather_code'][1])}, de {round(day['temperature_2m_min'][1])} à "
            f"{round(day['temperature_2m_max'][1])} degrés, "
            f"{day['precipitation_probability_max'][1]} % de risque de pluie.")
    except Exception:
        return "Je n'arrive pas à récupérer la météo pour le moment."


# --- Listes (courses, idées...) -------------------------------------------------------------


class Lists:
    def __init__(self, path: Path):
        self.store = JsonStore(path, {})

    @staticmethod
    def _key(name: str) -> str:
        return (name or "courses").strip().lower()

    def add(self, element: str, liste: str = "courses") -> str:
        key, element = self._key(liste), element.strip()
        if not element:
            return "Rien à ajouter."
        with self.store.lock:
            items = self.store.data.setdefault(key, [])
            if element.lower() in (i.lower() for i in items):
                return f"« {element} » est déjà dans la liste {key}."
            items.append(element)
            self.store.save()
        return f"Ajouté à la liste {key} : {element}"

    def read(self, liste: str = "courses") -> str:
        key = self._key(liste)
        with self.store.lock:
            items = list(self.store.data.get(key, []))
            names = sorted(k for k, v in self.store.data.items() if v)
        if not items:
            others = f" Listes existantes : {', '.join(names)}." if names else ""
            return f"La liste {key} est vide.{others}"
        return f"Liste {key} : " + ", ".join(items)

    def remove(self, element: str, liste: str = "courses") -> str:
        key, needle = self._key(liste), element.strip().lower()
        with self.store.lock:
            items = self.store.data.get(key, [])
            kept = [i for i in items if needle not in i.lower()] if needle else items
            removed = [i for i in items if i not in kept]
            if not removed:
                return f"Je ne trouve pas « {element} » dans la liste {key}."
            self.store.data[key] = kept
            self.store.save()
        return f"Retiré de la liste {key} : {', '.join(removed)}"


# --- État du PC -----------------------------------------------------------------------------


def _defender_status(run: Callable = subprocess.run) -> str:
    """État de l'antivirus Windows Defender (Windows uniquement, lecture seule)."""
    if platform.system() != "Windows":
        return ""
    try:
        out = run(
            ["powershell", "-NoProfile", "-Command",
             "Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,"
             "AntivirusSignatureAge | ConvertTo-Json"],
            capture_output=True, text=True, timeout=20)
        info = json.loads(out.stdout)
    except Exception:
        return "Antivirus : état inconnu (je n'arrive pas à interroger Windows Defender)."
    if not info.get("AntivirusEnabled") or not info.get("RealTimeProtectionEnabled"):
        return "ATTENTION : la protection antivirus en temps réel est désactivée."
    age = info.get("AntivirusSignatureAge", 0)
    if age > 3:
        return f"Antivirus actif, mais ses définitions ont {age} jours : lance Windows Update."
    return "Antivirus actif et à jour."


def pc_alerts(run: Callable = subprocess.run) -> dict[str, str]:
    """Problèmes qui méritent de prévenir l'utilisateur : {clé: message}. Ne modifie rien."""
    import psutil

    alerts = {}
    disk = shutil.disk_usage(Path.home())
    if disk.free / disk.total < 0.1:
        alerts["disque"] = f"le disque est presque plein, il ne reste que {disk.free / 1e9:.0f} Go"
    defender = _defender_status(run)
    if defender.startswith("ATTENTION"):
        alerts["antivirus"] = "la protection antivirus en temps réel est désactivée"
    elif "définitions" in defender:
        alerts["antivirus_ancien"] = "les définitions de l'antivirus datent, un passage par Windows Update s'impose"
    days = (time.time() - psutil.boot_time()) / 86400
    if days > 14:
        alerts["redemarrage"] = (f"l'ordinateur tourne depuis {days:.0f} jours, "
                                 "un redémarrage terminerait les mises à jour")
    return alerts


def pc_status(run: Callable = subprocess.run) -> str:
    """Résumé de la santé de l'ordinateur. Ne modifie rien."""
    import psutil

    parts = []
    disk = shutil.disk_usage(Path.home())
    free_go = disk.free / 1e9
    parts.append(f"Disque : {free_go:.0f} Go libres sur {disk.total / 1e9:.0f}"
                 + (" (ATTENTION : presque plein)" if disk.free / disk.total < 0.1 else ""))
    mem = psutil.virtual_memory()
    parts.append(f"Mémoire : {mem.used / 1e9:.0f} Go utilisés sur {mem.total / 1e9:.0f}")
    parts.append(f"Processeur : {psutil.cpu_percent(interval=0.5):.0f} % d'utilisation")
    days = (time.time() - psutil.boot_time()) / 86400
    parts.append(f"Allumé depuis {days:.0f} jour(s)"
                 + (" : un redémarrage finirait les mises à jour" if days > 14 else ""))
    defender = _defender_status(run)
    if defender:
        parts.append(defender)
    return ". ".join(parts) + "."


# --- Déclaration des outils -------------------------------------------------------------------


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def build_skills(reminders: Reminders, lists: Lists, sentinel=None) -> list[Tool]:
    s = {"type": "string"}
    security_tools = []
    if sentinel is not None:
        from security import start_antivirus_scan

        security_tools = [
            Tool(
                name="rapport_securite",
                description=("Fait le point sur la sécurité de l'ordinateur : programmes qui acceptent des "
                             "connexions du réseau, appareils sur le réseau local, pare-feu, menaces "
                             "détectées, comptes administrateur. À utiliser pour « rapport de sécurité », "
                             "« sommes-nous en sécurité ? », « quelqu'un nous attaque ? »."),
                parameters=_obj({}, []),
                run=sentinel.report,
            ),
            Tool(
                name="analyse_antivirus",
                description="Lance une analyse antivirus rapide de l'ordinateur avec Windows Defender.",
                parameters=_obj({}, []),
                run=start_antivirus_scan,
                confirm=lambda: "Je vais lancer une analyse antivirus rapide de l'ordinateur.",
            ),
        ]
    return security_tools + [
        Tool(
            name="rappeler",
            description=("Programme un rappel : Jarvis préviendra l'utilisateur le moment venu. "
                         "Donne SOIT dans_minutes (ex. « dans 20 minutes » → 20, « dans 2 heures » → 120), "
                         "SOIT date_heure au format AAAA-MM-JJ HH:MM (utilise d'abord heure_et_date "
                         "pour connaître la date du jour)."),
            parameters=_obj({
                "message": {**s, "description": "Ce qu'il faut rappeler."},
                "dans_minutes": {"type": "number", "description": "Délai en minutes."},
                "date_heure": {**s, "description": "Date et heure précises, AAAA-MM-JJ HH:MM."},
            }, ["message"]),
            run=reminders.add,
        ),
        Tool(
            name="lister_rappels",
            description="Liste les rappels en attente, avec leur numéro.",
            parameters=_obj({}, []),
            run=reminders.list_text,
        ),
        Tool(
            name="annuler_rappel",
            description="Annule un rappel à partir de son numéro (voir lister_rappels).",
            parameters=_obj({"numero": {"type": "integer", "description": "Numéro du rappel."}}, ["numero"]),
            run=reminders.cancel,
        ),
        Tool(
            name="calculer",
            description=("Calcule exactement une opération (addition, pourcentage, division, puissance, "
                         "racine...). À utiliser pour TOUT calcul au lieu de calculer de tête. "
                         "Exemples : « 1250 * 0.2 », « 15% * 80 », « sqrt(144) »."),
            parameters=_obj({"expression": {**s, "description": "L'opération, en chiffres."}}, ["expression"]),
            run=calculate,
        ),
        Tool(
            name="meteo",
            description="Donne la météo actuelle et les prévisions d'aujourd'hui et de demain pour une ville.",
            parameters=_obj({"ville": {**s, "description": "Nom de la ville (vide = ville habituelle)."}}, []),
            run=weather,
        ),
        Tool(
            name="ajouter_a_la_liste",
            description="Ajoute un élément à une liste (courses par défaut, ou idées, films, etc.).",
            parameters=_obj({
                "element": {**s, "description": "L'élément à ajouter."},
                "liste": {**s, "description": "Nom de la liste (défaut : courses)."},
            }, ["element"]),
            run=lists.add,
        ),
        Tool(
            name="lire_liste",
            description="Lit le contenu d'une liste (courses par défaut).",
            parameters=_obj({"liste": {**s, "description": "Nom de la liste (défaut : courses)."}}, []),
            run=lists.read,
        ),
        Tool(
            name="retirer_de_la_liste",
            description="Retire un élément d'une liste (quand il est acheté ou fait).",
            parameters=_obj({
                "element": {**s, "description": "L'élément à retirer."},
                "liste": {**s, "description": "Nom de la liste (défaut : courses)."},
            }, ["element"]),
            run=lists.remove,
        ),
        Tool(
            name="etat_du_pc",
            description=("Donne la santé de l'ordinateur : disque, mémoire, processeur, durée "
                         "d'allumage et état de l'antivirus."),
            parameters=_obj({}, []),
            run=pc_status,
        ),
    ]
