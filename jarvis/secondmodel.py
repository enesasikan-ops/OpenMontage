"""Second modèle local — un outil de consultation en plus (ex. dolphin-llama3).

En plus de son cerveau et de son renfort, Jarvis peut consulter un AUTRE modèle qui
tourne en local sur Ollama (configuré via JARVIS_MODELE_SECONDAIRE). Utile pour un
deuxième avis local et privé, ou un modèle moins enclin aux refus abusifs.

Honnêteté : selon le modèle pointé (ex. dolphin-llama3, non censuré), les réponses ne
sont pas filtrées — Jarvis relaie ce que le modèle dit. Et c'est un outil de PAROLE :
il répond, il n'agit pas. Il ne contourne aucune confirmation ni aucun garde-fou du
cœur (ouvrir, déverrouiller, pare-feu… restent gated comme avant).
"""

from __future__ import annotations

import logging

log = logging.getLogger("jarvis.second")


def _champ(obj, nom, defaut=""):
    return obj.get(nom, defaut) if isinstance(obj, dict) else getattr(obj, nom, defaut)


class SecondModel:
    def __init__(self, modele: str, chat=None):
        self.modele = modele
        self._chat = chat or self._ollama      # chat(modele, messages) -> texte

    def _ollama(self, modele: str, messages: list) -> str:
        import ollama

        import config
        client = ollama.Client(host=config.OLLAMA_HOST)
        rep = client.chat(model=modele, messages=messages)
        return _champ(_champ(rep, "message", {}), "content", "").strip()

    def demander(self, question: str) -> str:
        if not (question or "").strip():
            return "Quelle est la question pour le modèle local ?"
        try:
            texte = self._chat(self.modele, [{"role": "user", "content": question}])
        except Exception:
            log.warning("second modèle (%s) injoignable", self.modele)
            return (f"Le modèle local « {self.modele} » n'a pas répondu "
                    f"(est-il installé ? ollama pull {self.modele}).")
        return (texte or "").strip() or "Le modèle local n'a rien renvoyé."


def build_second_model_tools(chat=None) -> list:
    from tools import Tool

    import config
    if not config.SECOND_MODEL:
        return []
    sm = SecondModel(config.SECOND_MODEL, chat=chat)

    return [Tool(
        name="demander_au_modele_local",
        description=(f"Consulte un second modèle local ({config.SECOND_MODEL}) pour un avis, "
                     "100 % hors ligne. À utiliser quand l'utilisateur demande ce modèle, ou "
                     "pour un deuxième avis local. Il répond mais n'agit pas sur la maison."),
        parameters={"type": "object",
                    "properties": {"question": {"type": "string",
                                   "description": "La question, reformulée clairement."}},
                    "required": ["question"]},
        run=lambda question: sm.demander(question),
    )]
