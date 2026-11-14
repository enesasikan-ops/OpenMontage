"""Archive cognitive — la mémoire « qui ne tient pas dans le prompt ».

Problème réel : la mémoire vive de Jarvis (faits, consignes) est chargée EN ENTIER dans
les instructions du modèle. Au bout de mois/années, ça dépasse la fenêtre de contexte.

Parade (l'idée de Letta/MemGPT, sans son lourd framework) : une ARCHIVE sur le disque,
qu'on ne charge JAMAIS en bloc. Jarvis y range ce qui est volumineux ou ancien (résumés
de conversations, notes, données de sécurité), et quand il a besoin d'un vieux souvenir,
il le CHERCHE et ne ramène que les quelques entrées pertinentes dans sa mémoire de travail.

Honnêteté : la recherche est par MOTS-CLÉS (locale, sans dépendance). Elle retrouve bien
ce qui partage du vocabulaire ; pour une recherche « par le sens » (paraphrases), l'étape
suivante serait des embeddings — à ajouter si le rappel devient insuffisant.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from pathlib import Path

_STOP = {"le", "la", "les", "un", "une", "des", "de", "du", "et", "a", "au", "aux", "en",
         "que", "qui", "quoi", "est", "sur", "pour", "dans", "avec", "il", "elle", "je",
         "tu", "ce", "se", "sa", "son", "ses", "mon", "ma", "mes", "ton", "ta", "the", "to"}


def _mots(texte: str) -> set:
    t = unicodedata.normalize("NFD", (texte or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return {m for m in "".join(c if c.isalnum() else " " for c in t).split()
            if len(m) > 2 and m not in _STOP}


class Archive:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.entrees: list = self._load()

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return data.get("entrees", []) if isinstance(data, dict) else []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"entrees": self.entrees}, ensure_ascii=False),
                                 "utf-8")
        except OSError:
            pass

    def archiver(self, texte: str, tags: str = "", quand: "str | None" = None) -> str:
        texte = (texte or "").strip()
        if not texte:
            return "Rien à archiver."
        self.entrees.append({"texte": texte, "tags": tags.strip(),
                             "date": quand or datetime.now().strftime("%Y-%m-%d")})
        self._save()
        return f"Archivé (je saurai le retrouver) : {texte[:80]}"

    def chercher(self, requete: str, n: int = 5) -> list:
        q = _mots(requete)
        if not q:
            return []
        notes = []
        for e in self.entrees:
            score = len(q & (_mots(e.get("texte", "")) | _mots(e.get("tags", ""))))
            if score:
                notes.append((score, e))
        notes.sort(key=lambda se: (se[0], se[1].get("date", "")), reverse=True)
        return [e for _, e in notes[:n]]


def build_archive_tools(archive: "Archive | None" = None) -> list:
    from tools import Tool

    import config
    archive = archive or Archive(config.ARCHIVE_FILE)

    def chercher_dans_memoire(sujet: str) -> str:
        trouve = archive.chercher(sujet)
        if not trouve:
            return f"Je ne retrouve rien dans mes archives au sujet de « {sujet} »."
        lignes = [f"- ({e.get('date', '?')}) {e['texte']}" for e in trouve]
        return "Voici ce que je retrouve dans mes archives :\n" + "\n".join(lignes)

    return [
        Tool(name="archiver_note",
             description=("Range une information volumineuse ou destinée au LONG terme dans l'archive "
                          "(résumé, note, donnée à ne jamais oublier). Elle ne charge pas le prompt : "
                          "Jarvis la RETROUVERA en cherchant. À distinguer de « retenir » (fait bref courant)."),
             parameters={"type": "object",
                         "properties": {"texte": {"type": "string", "description": "l'information à archiver"},
                                        "tags": {"type": "string", "description": "mots-clés (facultatif)"}},
                         "required": ["texte"]},
             run=lambda texte, tags="": archive.archiver(texte, tags)),
        Tool(name="chercher_dans_memoire",
             description=("Cherche un vieux souvenir dans l'archive (des mois/années en arrière). "
                          "« qu'est-ce que je t'avais dit sur… ? », « retrouve mes notes sur… »."),
             parameters={"type": "object",
                         "properties": {"sujet": {"type": "string", "description": "le sujet à retrouver"}},
                         "required": ["sujet"]},
             run=chercher_dans_memoire),
    ]
