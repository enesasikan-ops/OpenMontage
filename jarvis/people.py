"""Mémoire par personne : ce que Jarvis sait de vos proches.

« Retiens que Carlos aime le café sans sucre. » → « Que sais-tu sur Carlos ? »
Distinct de la mémoire générale (memory.py, des faits sur toi) : ici, des faits
rattachés à une personne nommée. Reste 100 % local, dans un fichier JSON.
"""

from __future__ import annotations

import json
from pathlib import Path


def _cle(nom: str) -> str:
    return (nom or "").strip().lower()


class PeopleMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, list[str]] = self._load()

    def _load(self) -> dict:
        try:
            brut = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError):
            return {}
        return {str(k): [str(f) for f in v] for k, v in brut.items() if isinstance(v, list)}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def remember(self, personne: str, fait: str) -> str:
        cle, fait = _cle(personne), (fait or "").strip()
        if not cle or not fait:
            return "Dis-moi qui, et quoi retenir."
        faits = self.data.setdefault(cle, [])
        if fait in faits:
            return f"Je le savais déjà sur {personne.strip().capitalize()}."
        faits.append(fait)
        self._save()
        return f"C'est noté sur {personne.strip().capitalize()} : {fait}"

    def about(self, personne: str) -> str:
        faits = self.data.get(_cle(personne))
        if not faits:
            return f"Je ne sais rien sur {personne.strip().capitalize()}."
        p = personne.strip().capitalize()
        return f"Ce que je sais sur {p} : " + " ; ".join(faits) + "."

    def forget(self, personne: str, recherche: str = "") -> str:
        cle = _cle(personne)
        faits = self.data.get(cle)
        if not faits:
            return f"Je ne sais rien sur {personne.strip().capitalize()}."
        r = (recherche or "").strip().lower()
        if not r:                                   # tout oublier sur la personne
            del self.data[cle]
            self._save()
            return f"J'ai tout oublié sur {personne.strip().capitalize()}."
        restants = [f for f in faits if r not in f.lower()]
        if len(restants) == len(faits):
            return f"Rien qui corresponde à « {recherche} » sur {personne.strip().capitalize()}."
        if restants:
            self.data[cle] = restants
        else:
            del self.data[cle]
        self._save()
        return f"Oublié sur {personne.strip().capitalize()}."

    def known(self) -> list[str]:
        return sorted(self.data.keys())


def build_people_tools(memory: "PeopleMemory | None" = None) -> list:
    from tools import Tool
    import config

    memory = memory or PeopleMemory(config.PEOPLE_FILE)
    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(name="retenir_sur_personne",
             description=("Retient un fait sur une personne nommée (goûts, relation, détails). "
                          "Ex. « retiens que Carlos aime le café sans sucre »."),
             parameters=obj({"personne": {**s, "description": "le prénom/nom"},
                             "fait": {**s, "description": "ce qu'il faut retenir sur elle"}},
                            ["personne", "fait"]),
             run=memory.remember),
        Tool(name="que_sais_tu_sur",
             description="Donne ce que Jarvis sait d'une personne nommée (« que sais-tu sur Carlos ? »).",
             parameters=obj({"personne": {**s, "description": "le prénom/nom"}}, ["personne"]),
             run=memory.about),
        Tool(name="oublier_sur_personne",
             description="Oublie un fait (ou tout) sur une personne. Laisse « recherche » vide pour tout oublier.",
             parameters=obj({"personne": {**s, "description": "le prénom/nom"},
                             "recherche": {**s, "description": "le fait à oublier (vide = tout)"}},
                            ["personne"]),
             run=lambda personne, recherche="": memory.forget(personne, recherche)),
    ]
