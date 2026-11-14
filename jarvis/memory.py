"""Mémoire à long terme de Jarvis : une simple liste de faits dans un fichier JSON."""

import json
from pathlib import Path


class Memory:
    def __init__(self, path: Path):
        self.path = path
        self.facts: list[str] = self._load()

    def _load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[mémoire] Fichier illisible ({exc}), je repars d'une mémoire vide.")
            return []
        return [str(f) for f in data.get("faits", [])]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"faits": self.facts}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def remember(self, fact: str) -> str:
        fact = fact.strip()
        if not fact:
            return "Rien à retenir."
        if fact in self.facts:
            return "Je le savais déjà."
        self.facts.append(fact)
        self._save()
        return f"C'est noté : {fact}"

    def find(self, query: str) -> list[str]:
        q = query.lower().strip()
        return [f for f in self.facts if q and q in f.lower()]

    def forget(self, query: str) -> str:
        matches = self.find(query)
        if not matches:
            return f"Je n'ai rien en mémoire qui corresponde à « {query} »."
        self.facts = [f for f in self.facts if f not in matches]
        self._save()
        return "J'ai oublié : " + " ; ".join(matches)

    def as_text(self) -> str:
        if not self.facts:
            return "(rien pour l'instant)"
        return "\n".join(f"- {f}" for f in self.facts)
