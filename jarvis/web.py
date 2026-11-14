"""Navigation web de Jarvis : recherche et lecture de pages, en local (DuckDuckGo).

Pas de clé, pas de compte. Désactivé en mode hors ligne.
"""

import re
import urllib.request
from typing import Callable

import config

MAX_RESULTS = 5
PAGE_CHARS = 2000


def _ddgs_search(query: str, n: int) -> list[dict]:
    from ddgs import DDGS

    return DDGS().text(query, max_results=n, region="fr-fr")


def _get(key: str, *names: str) -> Callable[[dict], str]:
    def pick(d: dict) -> str:
        for name in names:
            if d.get(name):
                return str(d[name])
        return ""
    return pick


_title = _get("title", "title")
_body = _get("body", "body", "snippet", "description")
_href = _get("href", "href", "url", "link")


def search(query: str, searcher: Callable[[str, int], list[dict]] = _ddgs_search) -> str:
    """Cherche sur le web et renvoie les meilleurs résultats (titre, extrait, source)."""
    if config.OFFLINE:
        return "Je suis en mode hors ligne : pas de recherche web."
    query = query.strip()
    if not query:
        return "Que veux-tu que je cherche ?"
    try:
        results = searcher(query, MAX_RESULTS) or []
    except Exception:
        return "Je n'arrive pas à faire la recherche pour le moment."
    if not results:
        return f"Je n'ai rien trouvé pour « {query} »."
    lines = []
    for r in results[:MAX_RESULTS]:
        title, body, href = _title(r), _body(r), _href(r)
        if not (title or body):
            continue
        source = re.sub(r"^https?://(www\.)?", "", href).split("/")[0] if href else ""
        lines.append(f"- {title} : {body}" + (f" (source : {source})" if source else ""))
    return "Voici ce que j'ai trouvé :\n" + "\n".join(lines) if lines else f"Rien d'exploitable pour « {query} »."


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
            .replace("&gt;", ">").replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (assistant personnel)"})
    with urllib.request.urlopen(req, timeout=12) as response:  # noqa: S310 (URL fournie par l'utilisateur)
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(600_000).decode(charset, errors="ignore")


def read_page(url: str, fetch: Callable[[str], str] = _fetch) -> str:
    """Ouvre une page web et renvoie son texte (début), pour que Jarvis la résume."""
    if config.OFFLINE:
        return "Je suis en mode hors ligne : je ne peux pas ouvrir de page web."
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if fetch is _fetch:  # pour un vrai accès réseau : refuser les adresses internes (anti-SSRF)
        from netguard import url_externe_sure
        ok, raison = url_externe_sure(url)
        if not ok:
            return f"Je refuse d'ouvrir cette adresse : {raison}."
    try:
        text = _strip_html(_fetch(url) if fetch is _fetch else fetch(url))
    except Exception:
        return f"Je n'arrive pas à ouvrir « {url} »."
    if not text:
        return "Cette page ne contient pas de texte lisible."
    return text[:PAGE_CHARS] + ("…" if len(text) > PAGE_CHARS else "")


def build_web_tools() -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(name="chercher_sur_le_web",
             description=("Cherche une information récente ou factuelle sur internet "
                          "(actualité, horaires, prix, définition, « cherche X »). À utiliser "
                          "quand tu ne connais pas la réponse ou qu'elle peut avoir changé."),
             parameters=obj({"recherche": {**s, "description": "Les mots-clés à chercher."}}, ["recherche"]),
             run=lambda recherche: search(recherche)),
        Tool(name="lire_page_web",
             description="Ouvre une page web précise (dont tu as l'adresse) et en lit le contenu pour le résumer.",
             parameters=obj({"url": {**s, "description": "L'adresse de la page (https://...)."}}, ["url"]),
             run=lambda url: read_page(url)),
    ]
