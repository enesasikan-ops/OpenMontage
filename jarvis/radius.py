"""Surveillance de l'authentification Wi-Fi (FreeRADIUS / 802.1X).

FreeRADIUS est un démon : Jarvis ne le lance pas, il LIT son journal d'authentification
et te renseigne — combien de connexions réussies, et surtout les tentatives REJETÉES
(appareil inconnu, certificat révoqué, échec EAP, victime d'Evil Twin repoussée).

C'est la couche de surveillance par-dessus le 802.1X : l'auth forte est appliquée par
FreeRADIUS + les points d'accès ; Jarvis, lui, te prévient quand quelque chose est
refusé. Lecture seule, local.
"""

from __future__ import annotations

import re

_OK = re.compile(r"Login OK")
_REJET = re.compile(r"Login incorrect|rejected|Access-Reject|invalid", re.I)
_MAC = re.compile(r"cli\s+(?P<mac>[0-9A-Fa-f][0-9A-Fa-f:\-]{10,})")
_ID = re.compile(r"\[(?P<id>[^\]]*)\]")


def _mac(ligne: str) -> str:
    m = _MAC.search(ligne)
    return m.group("mac").lower().replace("-", ":") if m else ""


def analyser_ligne(ligne: str) -> "dict | None":
    """Extrait {resultat: ok|rejet, identite, mac} d'une ligne d'auth FreeRADIUS, ou None."""
    if _OK.search(ligne):
        resultat = "ok"
    elif _REJET.search(ligne):
        resultat = "rejet"
    else:
        return None
    ident = _ID.search(ligne)
    return {"resultat": resultat,
            "identite": (ident.group("id") if ident else "") or "inconnu",
            "mac": _mac(ligne)}


def resume(lignes: list) -> dict:
    ok, rejets = 0, []
    for ligne in lignes:
        ev = analyser_ligne(ligne)
        if ev is None:
            continue
        if ev["resultat"] == "ok":
            ok += 1
        else:
            rejets.append(ev)
    return {"ok": ok, "rejets": rejets}


def rapport(res: dict) -> str:
    base = f"Authentification Wi-Fi (RADIUS) : {res['ok']} connexion(s) réussie(s)"
    if not res["rejets"]:
        return base + ", aucun rejet. Réseau sain."
    derniers = "; ".join(f"{r['identite']} ({r['mac'] or 'MAC ?'})" for r in res["rejets"][-5:])
    return (base + f", ⚠️ {len(res['rejets'])} REJET(S). "
            f"Derniers refus : {derniers}. Un appareil inconnu ou un certificat non valide ?")


def _lire_tail(chemin: str, n: int = 400) -> list:
    from collections import deque

    with open(chemin, encoding="utf-8", errors="ignore") as f:
        return list(deque(f, maxlen=n))


def build_radius_tools(lire=None) -> list:
    from tools import Tool

    import config
    if not config.RADIUS:
        return []
    lire = lire or (lambda: _lire_tail(config.RADIUS_LOG))

    def point_auth_wifi() -> str:
        try:
            lignes = lire()
        except FileNotFoundError:
            return (f"Je ne trouve pas le journal RADIUS ({config.RADIUS_LOG}). "
                    "FreeRADIUS tourne-t-il, et le chemin est-il correct ?")
        except Exception:
            return "Je n'arrive pas à lire le journal d'authentification."
        return rapport(resume(lignes))

    return [Tool(
        name="point_authentification_wifi",
        description=("Fait le point sur l'authentification Wi-Fi 802.1X (FreeRADIUS) : "
                     "connexions réussies et tentatives REJETÉES. « des rejets d'auth ? », "
                     "« qui a été refusé sur le Wi-Fi ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=point_auth_wifi,
    )]
