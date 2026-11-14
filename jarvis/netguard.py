"""Garde-fou réseau contre le SSRF (Server-Side Request Forgery).

Empêche qu'on fasse ouvrir à Jarvis des adresses INTERNES (ta box, Ollama, Home
Assistant, l'API de métadonnées cloud…) via une URL glissée dans un message ou dans un
résultat de recherche. On résout le nom d'hôte et on refuse toute IP privée, locale ou
réservée.

Note : un nom DNS peut changer entre la vérification et la connexion (DNS rebinding).
Pour un assistant perso sur un réseau domestique, ce contrôle couvre l'essentiel ; pour
un durcissement total, il faudrait fixer l'IP résolue et l'utiliser pour la connexion.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _ip_interne(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True  # illisible = on refuse par prudence
    return (a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
            or a.is_multicast or a.is_unspecified)


def url_externe_sure(url: str, schemes: "tuple[str, ...]" = ("http", "https"),
                     resolveur=socket.getaddrinfo) -> "tuple[bool, str]":
    """(ok, raison). ok=True seulement si l'URL vise un hôte PUBLIC via un schéma autorisé."""
    p = urlparse((url or "").strip())
    if p.scheme not in schemes:
        return False, f"schéma non autorisé : {p.scheme or '(aucun)'}"
    host = p.hostname
    if not host:
        return False, "hôte manquant"
    # Une IP écrite en clair : on la teste directement.
    try:
        ipaddress.ip_address(host)
        return (False, f"adresse interne bloquée ({host})") if _ip_interne(host) else (True, "")
    except ValueError:
        pass
    # Un nom : on résout et on vérifie TOUTES les adresses renvoyées.
    try:
        infos = resolveur(host, None)
    except socket.gaierror:
        return False, "hôte introuvable"
    for info in infos:
        ip = info[4][0]
        if _ip_interne(ip):
            return False, f"adresse interne bloquée ({ip})"
    return True, ""
