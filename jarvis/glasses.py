"""Lunettes connectées comme interface pour Jarvis (OpenGlass / Brilliant Labs Monocle).

Tu bricoles dans le garage, les mains pleines de cambouis. Tu regardes le moteur :
« Jarvis, quelle est cette pièce ? » La caméra des lunettes envoie l'image au serveur
de la maison, Jarvis l'analyse, et renvoie un texte COURT que les lunettes affichent
sur le verre : « C'est le filtre à huile. »

Découplage volontaire (comme robot.py l'est de ROS) : Jarvis fournit le CERVEAU via un
petit service HTTP local ; le firmware des lunettes gère le transport (BLE/Wi-Fi), la
capture et l'affichage sur le verre. Les lunettes font :

    POST http://maison:8766/voir?jeton=XXX&q=quelle+est+cette+piece
    (corps = l'image JPEG brute)      -> réponse : texte court à afficher

La vision réutilise VisionRouter : locale d'abord (rien ne sort), Gemini en secours.
Le service exige un jeton dès qu'il écoute au-delà de l'ordinateur local.
"""

from __future__ import annotations

import hmac
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

import config

log = logging.getLogger("jarvis.lunettes")

MAX_IMAGE = 8 * 1024 * 1024     # 8 Mo : une photo de lunettes est petite
MAX_CAR = 120                   # un verre n'affiche qu'une ligne ou deux

QUESTION_DEFAUT = ("Tu regardes à travers les lunettes de l'utilisateur. Identifie l'objet "
                   "principal au centre de l'image et réponds en une phrase très courte, en français.")


def reponse_courte(texte: str, max_car: int = MAX_CAR) -> str:
    """Condense la réponse de la vision pour tenir sur le verre."""
    t = " ".join((texte or "").split())
    if len(t) <= max_car:
        return t
    coupe = t[:max_car]
    if " " in coupe:
        coupe = coupe[:coupe.rfind(" ")]
    return coupe.rstrip(" ,;:.") + "…"


def question_lunettes(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return QUESTION_DEFAUT
    return (f"Tu regardes à travers les lunettes de l'utilisateur. Réponds à sa question "
            f"« {q} » en une phrase très courte et directe, en français.")


class GlassesVision:
    """Analyse une image venue des lunettes et renvoie un texte prêt à afficher."""

    def __init__(self, describe: "Callable[[bytes, str], str] | None"):
        self.describe = describe     # describe(image, question) -> str (VisionRouter.describe)

    def analyser(self, image: bytes, question: str = "") -> str:
        if not image:
            return "Je n'ai pas reçu d'image."
        if self.describe is None:
            return "La vision n'est pas configurée (voir JARVIS_VISION)."
        try:
            texte = self.describe(image, question_lunettes(question))
        except Exception:
            log.exception("analyse de l'image des lunettes")
            return "Analyse impossible pour l'instant."
        return reponse_courte(texte)


# --- Service HTTP local -------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    vision: "GlassesVision" = None   # injecté par make_server
    token: str = ""

    def log_message(self, *args):    # pas de log par requête
        pass

    def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _autorise(self, query: str) -> bool:
        if not self.token:           # pas de jeton : seulement en local (voir _sur_de_demarrer)
            return True
        fourni = parse_qs(query).get("jeton", [""])[0]
        return hmac.compare_digest(fourni, self.token)

    def do_GET(self):
        if urlparse(self.path).path == "/sante":      # sonde de vie, sans jeton (aucune donnée)
            self._send(200, b"ok")
        else:
            self._send(404, b"introuvable")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/voir":
            self._send(404, b"introuvable")
            return
        if not self._autorise(parsed.query):
            self._send(401, "jeton requis".encode("utf-8"))
            return
        try:
            longueur = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            longueur = 0
        if longueur <= 0:
            self._send(400, "image manquante".encode("utf-8"))
            return
        if longueur > MAX_IMAGE:
            self._send(413, "image trop lourde".encode("utf-8"))
            return
        image = self.rfile.read(longueur)
        question = parse_qs(parsed.query).get("q", [""])[0]
        texte = self.vision.analyser(image, question)
        self._send(200, texte.encode("utf-8"))


def make_server(vision: GlassesVision, host: str, port: int, token: str = "") -> ThreadingHTTPServer:
    handler = type("LunettesHandler", (Handler,), {"vision": vision, "token": token})
    return ThreadingHTTPServer((host, port), handler)


def _est_local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "")


def sur_de_demarrer(host: str, token: str) -> "str | None":
    """Renvoie None si c'est sûr, sinon la raison du refus."""
    if not _est_local(host) and not token:
        return ("Le service lunettes écouterait sur le réseau sans jeton : refusé. "
                "Mets un JARVIS_LUNETTES_JETON, ou garde l'hôte en local (127.0.0.1).")
    return None


def make_glasses_vision(gemini=None) -> GlassesVision:
    from vision import VisionRouter

    router = VisionRouter(gemini=gemini)
    return GlassesVision(router.describe if router.available else None)


def demarrer_lunettes(gemini=None) -> dict:
    """Démarre le service lunettes dans un fil, si activé et sûr. Pour les bots."""
    if not config.GLASSES:
        return {"statut": "coupé"}
    raison = sur_de_demarrer(config.GLASSES_HOST, config.GLASSES_TOKEN)
    if raison:
        log.warning(raison)
        return {"statut": "erreur", "message": raison}
    vision = make_glasses_vision(gemini)
    try:
        server = make_server(vision, config.GLASSES_HOST, config.GLASSES_PORT, config.GLASSES_TOKEN)
    except OSError as exc:
        log.warning("service lunettes : %s", exc)
        return {"statut": "erreur", "message": str(exc)}
    threading.Thread(target=server.serve_forever, name="jarvis-lunettes", daemon=True).start()
    log.info("👓 Service lunettes à l'écoute sur %s:%d", config.GLASSES_HOST, config.GLASSES_PORT)
    return {"statut": "succès", "message": f"Lunettes à l'écoute ({config.GLASSES_HOST}:{config.GLASSES_PORT})"}
