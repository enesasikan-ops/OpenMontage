"""Propositions de modification du CŒUR, réservées au propriétaire.

Normalement, l'auto-amélioration (la nuit) ne touche JAMAIS aux fichiers du cœur.
Ce module ouvre une seule porte, étroite et surveillée : le propriétaire peut demander
explicitement à un renfort (Gemini) de PROPOSER un changement sur un fichier du cœur.

Garde-fous, non négociables :
- jamais déclenché tout seul : seulement sur demande explicite du propriétaire ;
- jamais `.env` (les secrets ne passent pas par là) ;
- toujours une PROPOSITION : on calcule le diff, on lance les tests dans une copie
  isolée, et RIEN n'est écrit tant que le propriétaire n'a pas validé le diff ;
- à l'application, l'ancien fichier est sauvegardé en .bak ;
- un changement du cœur ne se recharge pas à chaud : il faut redémarrer Jarvis.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from growth import PROTECTED

RACINE = Path(__file__).resolve().parent
# Modifiables sur proposition (le cœur), SAUF le fichier de secrets.
COEUR_MODIFIABLE = tuple(f for f in PROTECTED if f != ".env")
TEST_TIMEOUT_S = 600


def _extraire_code(reponse: str) -> str:
    """Récupère le contenu d'un bloc ```python ... ``` (ou le texte brut sinon)."""
    bloc = re.search(r"```[a-zA-Z0-9_]*\s*\n(.*?)```", reponse or "", re.DOTALL)
    return (bloc.group(1) if bloc else (reponse or "")).strip()


@dataclass
class CoreProposal:
    fichier: str
    ancien: str
    nouveau: str
    diff: str
    tests_ok: bool
    tests: str


class CoreImprover:
    """Fait proposer par `agent` (Gemini de préférence) un changement sur un fichier du cœur."""

    def __init__(self, agent, racine: Path = RACINE, tester: Callable | None = None):
        self.agent = agent
        self.racine = Path(racine).resolve()
        self.tester = tester or self._tester_en_isole

    def _chemin(self, fichier: str) -> Path:
        if fichier not in COEUR_MODIFIABLE:
            raise ValueError(f"« {fichier} » n'est pas un fichier du cœur modifiable sur proposition.")
        cible = (self.racine / fichier).resolve()
        if cible.parent != self.racine:        # anti-traversée : jamais hors de la racine
            raise ValueError("chemin invalide")
        if not cible.is_file():
            raise ValueError(f"fichier introuvable : {fichier}")
        return cible

    def proposer(self, fichier: str, consigne: str) -> CoreProposal:
        chemin = self._chemin(fichier)
        ancien = chemin.read_text(encoding="utf-8")
        prompt = (
            f"Voici le fichier `{fichier}` de Jarvis :\n\n```python\n{ancien}\n```\n\n"
            f"Modification demandée par le propriétaire : {consigne}\n\n"
            "Renvoie UNIQUEMENT le nouveau contenu COMPLET du fichier, dans un seul bloc "
            "```python ... ```. Ne change que ce qui est nécessaire ; garde le reste à l'identique."
        )
        nouveau = _extraire_code(self.agent.ask(prompt))
        if not nouveau:
            raise ValueError("le renfort n'a pas renvoyé de code exploitable")
        nouveau += "\n"  # un fichier source se termine toujours par une nouvelle ligne
        diff = "".join(difflib.unified_diff(
            ancien.splitlines(keepends=True), nouveau.splitlines(keepends=True),
            fromfile=f"{fichier} (actuel)", tofile=f"{fichier} (proposé)"))
        if not diff:
            return CoreProposal(fichier, ancien, nouveau, "", True, "aucun changement")
        tests_ok, tests = self.tester(fichier, nouveau)
        return CoreProposal(fichier, ancien, nouveau, diff, tests_ok, tests)

    def appliquer(self, proposal: CoreProposal) -> str:
        """À n'appeler qu'après validation du diff par le propriétaire."""
        chemin = self._chemin(proposal.fichier)
        if chemin.read_text(encoding="utf-8") != proposal.ancien:
            raise ValueError("le fichier a changé depuis la proposition : relance une proposition")
        sauvegarde = chemin.with_name(chemin.name + ".bak")
        sauvegarde.write_text(proposal.ancien, encoding="utf-8")
        chemin.write_text(proposal.nouveau, encoding="utf-8")
        return (f"{proposal.fichier} modifié (ancienne version dans {sauvegarde.name}). "
                "Redémarre Jarvis pour que le changement du cœur prenne effet.")

    def _tester_en_isole(self, fichier: str, nouveau: str) -> "tuple[bool, str]":
        """Copie le projet dans un dossier temporaire, applique le changement, lance les tests."""
        with tempfile.TemporaryDirectory() as d:
            copie = Path(d) / "jarvis"
            shutil.copytree(self.racine, copie, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".git", "venv", ".venv", "node_modules", "*.bak"))
            (copie / fichier).write_text(nouveau, encoding="utf-8")
            try:
                out = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", str(copie / "tests")],
                    capture_output=True, text=True, timeout=TEST_TIMEOUT_S, cwd=str(copie))
            except (OSError, subprocess.SubprocessError) as exc:
                return False, f"tests impossibles à lancer ({exc})"
            resume = (out.stdout or "").strip().splitlines()[-1:] or [""]
            return out.returncode == 0, resume[0]
