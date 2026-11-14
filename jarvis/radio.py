"""Radio logicielle (RTL-SDR) — avions au-dessus (ADS-B) et météo locale (rtl_433).

Une clé SDR (~25 €) + antenne sur le serveur capte des signaux radio publics. Deux usages,
sobres et légitimes :
- ADS-B (1090 MHz, via dump1090) : les avions diffusent EN CLAIR leur position et altitude,
  pour la sécurité aérienne. Jarvis dit lequel vous survole. Donnée publique, reçue par
  tous les trackers de vol.
- rtl_433 (433/868 MHz) : TES capteurs (station météo, sondes) → une météo hyperlocale
  gratuite, sans API ni internet.

NON construits, et refusés :
- le pistage des véhicules par leur capteur TPMS (ID unique → suivre qui passe dans la rue,
  à leur insu : c'est de la surveillance de tiers) ;
- le ciblage de l'appareil d'une personne nommée (« la station du voisin »). Les relevés
  d'ambiance restent des données d'environnement anonymes.

Honnêteté ADS-B : le signal donne l'indicatif, la position et l'altitude — PAS la
destination. Jarvis ne l'invente pas (une route « → New York » demanderait une base de
vols en ligne, à ajouter séparément si tu le veux).
"""

from __future__ import annotations

import json
import logging
import math
from typing import Callable

import config

log = logging.getLogger("jarvis.radio")

PIEDS_EN_METRES = 0.3048
_CAPS = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest"]


def _haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _cap_fr(track) -> str:
    try:
        return _CAPS[int((float(track) % 360) / 45 + 0.5) % 8]
    except (TypeError, ValueError):
        return ""


def avions(data: dict, lat: float, lon: float) -> list:
    """Avions avec position, triés du plus proche au plus loin."""
    out = []
    for a in (data or {}).get("aircraft", []):
        if a.get("lat") is None or a.get("lon") is None:
            continue
        alt_pieds = a.get("alt_baro", a.get("altitude"))
        if alt_pieds in (None, "ground"):
            continue
        dist = _haversine(lat, lon, a["lat"], a["lon"])
        out.append({
            "vol": (a.get("flight") or a.get("hex", "?")).strip(),
            "altitude_m": round(float(alt_pieds) * PIEDS_EN_METRES),
            "distance_km": round(dist, 1),
            "cap": _cap_fr(a.get("track")),
        })
    return sorted(out, key=lambda x: x["distance_km"])


def survol(data: dict, lat: float, lon: float, rayon_km: float) -> "dict | None":
    proches = [a for a in avions(data, lat, lon) if a["distance_km"] <= rayon_km]
    return proches[0] if proches else None


def message_survol(a: dict) -> str:
    ou = "juste au-dessus de vous" if a["distance_km"] <= 2 else f"à environ {a['distance_km']} km"
    cap = f", cap {a['cap']}" if a["cap"] else ""
    return (f"Le vol {a['vol']} vous survole {ou}, à {a['altitude_m']} m d'altitude{cap}. "
            "(Indicatif et altitude publics ; la destination n'est pas dans le signal.)")


def _fetch_json(url: str) -> dict:
    import urllib.request

    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def build_radio_tools(home=None, fetch: "Callable | None" = None) -> list:
    from tools import Tool

    fetch = fetch or _fetch_json
    outils = []

    if config.ADSB:
        def avion_au_dessus() -> str:
            if not (config.ADSB_LAT or config.ADSB_LON):
                return "Je n'ai pas les coordonnées de la maison (JARVIS_LAT / JARVIS_LON)."
            try:
                data = fetch(config.ADSB_URL)
            except Exception:
                return "Je ne capte pas le récepteur ADS-B pour l'instant (dump1090 est-il lancé ?)."
            a = survol(data, config.ADSB_LAT, config.ADSB_LON, config.ADSB_RAYON_KM)
            if a is None:
                return "Aucun avion dans le ciel au-dessus de nous en ce moment."
            return message_survol(a)

        outils.append(Tool(
            name="avion_au_dessus",
            description=("Dit quel avion de ligne survole la maison en ce moment (ADS-B, donnée "
                         "publique). « quel avion passe au-dessus ? », « c'est quoi cet avion ? »."),
            parameters={"type": "object", "properties": {}, "required": []},
            run=avion_au_dessus))

    if config.METEO_RADIO and home is not None and getattr(home, "configured", False):
        def meteo_radio() -> str:
            try:
                etats = {e["entity_id"]: e.get("state") for e in home.states()}
            except Exception:
                return "Je n'arrive pas à lire les capteurs radio."
            m = config.METEO_RADIO
            morceaux = []
            for cle, unite in (("temperature", "°C"), ("humidite", "%"), ("pression", "hPa")):
                ent = m.get(cle)
                if ent and etats.get(ent) not in (None, "unavailable", "unknown"):
                    morceaux.append(f"{etats[ent]} {unite}")
            if not morceaux:
                return "Mes capteurs météo radio ne renvoient rien pour l'instant."
            return "Météo locale (radio) : " + ", ".join(morceaux) + "."

        outils.append(Tool(
            name="meteo_radio",
            description=("Donne la météo captée par tes propres capteurs radio (rtl_433) : "
                         "température, humidité, pression. Local, sans internet."),
            parameters={"type": "object", "properties": {}, "required": []},
            run=meteo_radio))

    return outils
