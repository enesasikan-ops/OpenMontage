"""Mémoire associative — les « connexions » entre les souvenirs de Jarvis.

Honnêteté d'abord : ceci ne touche PAS aux poids du modèle local (ils sont figés dans
Ollama). Ce qu'on améliore, c'est la MÉMOIRE autour du cerveau — le vrai sens de
« connexions neuronales » au niveau cognitif : au lieu de se rappeler chaque fait isolé,
Jarvis relie les souvenirs entre eux. On cherche un sujet, il ramène le souvenir pertinent
ET ceux qui y sont liés (« tu m'avais aussi dit que… »).

Deux régimes, sans rien casser :
- Par défaut : liens par MOTS partagés (local, zéro dépendance) — on réutilise le
  tokeniseur de archive.py.
- Si un modèle d'embeddings Ollama est configuré (config.EMBED_MODEL, ex. nomic-embed-text) :
  liens SÉMANTIQUES (par le sens, pas seulement le vocabulaire). En cas d'échec ou
  d'absence, on retombe proprement sur les mots partagés.

Tout reste 100 % local. Rien ne part dans le cloud.
"""

from __future__ import annotations

import json
import logging
import math
import urllib.request
from typing import Callable

from archive import _mots   # tokeniseur normalisé + stopwords (DRY)

log = logging.getLogger("jarvis.liens")

_CAP_EMBED = 200       # au-delà, on reste en mode mots (éviter des centaines d'appels Ollama)
_SEUIL_MOTS = 2        # nb minimal de mots partagés pour qu'un lien existe
_SEUIL_COS = 0.55      # similarité cosinus minimale (mode embeddings) pour un lien


def _cos_termes(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def _cos(u: list, v: list) -> float:
    num = sum(x * y for x, y in zip(u, v))
    na = math.sqrt(sum(x * x for x in u))
    nb = math.sqrt(sum(y * y for y in v))
    return num / (na * nb) if na and nb else 0.0


def ollama_embed(textes: list) -> list:
    """Embeddings via l'Ollama LOCAL (stdlib, aucune dépendance). Lève en cas d'échec."""
    import config
    url = config.OLLAMA_HOST.rstrip("/") + "/api/embeddings"
    out = []
    for t in textes:
        req = urllib.request.Request(
            url, data=json.dumps({"model": config.EMBED_MODEL, "prompt": t}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310 (hôte local de confiance)
            out.append(json.loads(r.read().decode("utf-8")).get("embedding"))
    return out


class AssociativeMemory:
    """Relie des souvenirs ({texte, origine}) entre eux, par mots partagés ou par le sens."""

    def __init__(self, items: list, embed: "Callable[[list], list] | None" = None,
                 seuil_mots: int = _SEUIL_MOTS, seuil_cos: float = _SEUIL_COS, cap: int = _CAP_EMBED):
        self.items = [dict(it) for it in items if (it.get("texte") or "").strip()]
        self.seuil_mots = seuil_mots
        self.seuil_cos = seuil_cos
        self._embed = embed
        self._termes = [_mots(it["texte"]) for it in self.items]
        self._vecs = self._calculer_vecteurs(cap)

    def _calculer_vecteurs(self, cap: int) -> "list | None":
        if not self._embed or not self.items or len(self.items) > cap:
            return None
        try:
            vecs = self._embed([it["texte"] for it in self.items])
        except Exception:
            log.warning("embeddings indisponibles : repli sur les mots partagés", exc_info=True)
            return None
        if not vecs or len(vecs) != len(self.items) or not all(vecs):
            return None
        return vecs

    def _vec_sujet(self, sujet: str) -> "list | None":
        if self._vecs is None or not self._embed:
            return None
        try:
            v = self._embed([sujet])
            return v[0] if v and v[0] else None
        except Exception:
            return None

    def _lien(self, i: int, j: int) -> "float | None":
        """Force du lien entre deux souvenirs, ou None s'il n'y a pas de lien."""
        if self._vecs is not None:
            sc = _cos(self._vecs[i], self._vecs[j])
            return sc if sc >= self.seuil_cos else None
        partages = len(self._termes[i] & self._termes[j])
        return float(partages) if partages >= self.seuil_mots else None

    def _voisins(self, i: int, exclure: set, k: int) -> list:
        scores = []
        for j in range(len(self.items)):
            if j == i or j in exclure:
                continue
            force = self._lien(i, j)
            if force is not None:
                scores.append((force, j))
        scores.sort(reverse=True)
        return [j for _, j in scores[:k]]

    def relier(self, sujet: str, n: int = 3, voisins: int = 3) -> dict:
        sujet = (sujet or "").strip()
        if not sujet or not self.items:
            return {"sujet": sujet, "ancres": []}
        s_termes, s_vec = _mots(sujet), self._vec_sujet(sujet)

        def pertinence(i: int) -> float:
            if s_vec is not None and self._vecs is not None:
                return _cos(s_vec, self._vecs[i])
            return _cos_termes(s_termes, self._termes[i])

        classes = sorted(range(len(self.items)), key=pertinence, reverse=True)
        ancres = [i for i in classes if pertinence(i) > 0][:n]
        resultat = []
        for i in ancres:
            liens = self._voisins(i, exclure=set(ancres), k=voisins)
            resultat.append({
                "texte": self.items[i]["texte"],
                "origine": self.items[i].get("origine", ""),
                "liens": [{"texte": self.items[j]["texte"], "origine": self.items[j].get("origine", "")}
                          for j in liens],
            })
        return {"sujet": sujet, "ancres": resultat}

    def texte_rappel(self, sujet: str) -> str:
        r = self.relier(sujet)
        if not r["ancres"]:
            return ""
        lignes = []
        for a in r["ancres"]:
            orig = f"  [{a['origine']}]" if a["origine"] else ""
            lignes.append(f"• {a['texte']}{orig}")
            for lien in a["liens"]:
                lignes.append(f"    ↳ lié : {lien['texte']}")
        return "\n".join(lignes)


def _items_memoire(memory) -> list:
    """Rassemble les souvenirs des trois sources locales : faits, archive, personnes."""
    import config
    items = [{"texte": f, "origine": "fait"} for f in getattr(memory, "facts", [])]
    try:
        from archive import Archive
        for e in Archive(config.ARCHIVE_FILE).entrees:
            if e.get("texte"):
                items.append({"texte": e["texte"], "origine": "archive"})
    except Exception:
        log.debug("archive illisible pour le rappel associatif", exc_info=True)
    try:
        from people import PeopleMemory
        for nom, faits in PeopleMemory(config.PEOPLE_FILE).data.items():
            for f in faits:
                items.append({"texte": f, "origine": f"à propos de {nom}"})
    except Exception:
        log.debug("mémoire des personnes illisible pour le rappel associatif", exc_info=True)
    return items


def build_link_tools(memory) -> list:
    from tools import Tool
    import config

    embed = ollama_embed if getattr(config, "EMBED_MODEL", "") else None

    def relier_souvenirs(sujet: str) -> str:
        am = AssociativeMemory(_items_memoire(memory), embed=embed)
        txt = am.texte_rappel(sujet)
        if not txt:
            return f"Je ne relie rien de particulier à « {sujet} » pour l'instant."
        return "Voici ce que je relie :\n" + txt

    return [
        Tool(
            name="relier_souvenirs",
            description=("Rappel ASSOCIATIF : à partir d'un sujet, ramène le souvenir pertinent ET "
                         "ceux qui y sont LIÉS (mémoire, archive, personnes). À utiliser pour « relie "
                         "ce que tu sais sur… », « à quoi ça te fait penser… », faire des rapprochements."),
            parameters={"type": "object",
                        "properties": {"sujet": {"type": "string", "description": "le sujet de départ"}},
                        "required": ["sujet"]},
            run=relier_souvenirs,
        ),
    ]
