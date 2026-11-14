"""Intégration Freebox (API locale) — savoir qui est sur le Wi-Fi, repérer les inconnus.

La Freebox expose une API sur le réseau local. Après un APPAIRAGE unique (tu valides une
fois sur l'écran de la Freebox — voir appairer_freebox.py), Jarvis obtient un jeton
d'application, ouvre une session (défi/réponse HMAC), et peut lister les appareils
connectés. Il compare à ta liste d'appareils connus et t'alerte sur un INCONNU.

Lecture d'abord : cette brique OBSERVE (qui est là). Isoler un appareil au niveau de la
Freebox est possible via l'API mais dépend du modèle — on l'ajoutera sur confirmation,
pas en aveugle. Tout reste local : le jeton vit dans .env, rien ne sort de la maison.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import config

log = logging.getLogger("jarvis.freebox")


def mot_de_passe_session(app_token: str, challenge: str) -> str:
    """Réponse au défi Freebox : HMAC-SHA1(app_token, challenge) en hexadécimal."""
    return hmac.new(app_token.encode(), challenge.encode(), hashlib.sha1).hexdigest()


def normaliser_hotes(hosts: list) -> list:
    """Transforme la réponse 'lan/browser' en [{nom, mac, actif}]."""
    out = []
    for h in hosts or []:
        mac = (h.get("l2ident") or {}).get("id") or h.get("id") or ""
        out.append({"nom": h.get("primary_name") or mac or "inconnu",
                    "mac": mac.lower(), "actif": bool(h.get("active"))})
    return out


def classer(hotes: list, connus) -> dict:
    """Sépare les appareils ACTIFS en connus / inconnus (connus = noms ou MAC)."""
    ref = {str(x).strip().lower() for x in connus}
    actifs = [h for h in hotes if h["actif"]]
    inconnus = [h for h in actifs if h["mac"] not in ref and h["nom"].lower() not in ref]
    connus_actifs = [h for h in actifs if h not in inconnus]
    return {"inconnus": inconnus, "connus": connus_actifs}


class FreeboxClient:
    def __init__(self, base_url: str, app_token: str, request=None, app_id: str = "jarvis"):
        self.base = (base_url or "").rstrip("/")
        self.app_token = app_token
        self.app_id = app_id
        self._request = request or self._http
        self._session = ""

    def _http(self, method: str, path: str, headers=None, body=None):
        import json
        import urllib.request

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def _resultat(self, reponse: dict):
        if not isinstance(reponse, dict) or not reponse.get("success", False):
            raise RuntimeError((reponse or {}).get("msg", "réponse Freebox invalide"))
        return reponse.get("result")

    def ouvrir_session(self) -> str:
        defi = self._resultat(self._request("GET", "/api/v4/login/"))
        mdp = mot_de_passe_session(self.app_token, defi["challenge"])
        res = self._resultat(self._request("POST", "/api/v4/login/session/",
                                           body={"app_id": self.app_id, "password": mdp}))
        self._session = res["session_token"]
        return self._session

    def _auth(self) -> dict:
        if not self._session:
            self.ouvrir_session()
        return {"X-Fbx-App-Auth": self._session}

    def appareils(self) -> list:
        hosts = self._resultat(self._request("GET", "/api/v4/lan/browser/pub/", headers=self._auth()))
        return normaliser_hotes(hosts)


def build_freebox_tools(client: "FreeboxClient | None" = None) -> list:
    from tools import Tool

    if not config.FREEBOX_TOKEN:
        return []
    client = client or FreeboxClient(config.FREEBOX_URL, config.FREEBOX_TOKEN)

    def appareils_wifi() -> str:
        try:
            hotes = client.appareils()
        except Exception as exc:
            return f"Je n'arrive pas à joindre la Freebox ({exc}). Est-elle appairée ?"
        c = classer(hotes, config.FREEBOX_CONNUS)
        lignes = [f"{len(c['connus'])} appareil(s) connu(s) connecté(s)."]
        if c["inconnus"]:
            noms = ", ".join(f"{h['nom']} ({h['mac']})" for h in c["inconnus"])
            lignes.append(f"⚠️ {len(c['inconnus'])} INCONNU(S) sur le Wi-Fi : {noms}.")
        else:
            lignes.append("Aucun inconnu : le Wi-Fi est sain.")
        return " ".join(lignes)

    return [Tool(
        name="appareils_wifi",
        description=("Liste les appareils connectés au Wi-Fi via la Freebox et signale les "
                     "INCONNUS. « qui est sur le Wi-Fi ? », « y a-t-il un intrus ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=appareils_wifi,
    )]
