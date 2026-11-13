"""La vision de Jarvis : décrire une image (ex. la vue du drone, une capture d'écran).

Deux voies, choisies avec JARVIS_VISION dans .env :
- "local"  : un modèle qui voit, tournant sur l'ordinateur via Ollama (ex. qwen2.5-vl,
             llama3.2-vision, moondream). Gratuit, privé, hors ligne.
- "gemini" : Gemini (Google), qui lit les images. Rapide et bon, mais passe par internet.
- "auto"   : local si un modèle de vision est réglé, sinon Gemini si une clé est là.

La vision LOCALE est préférée : rien ne sort de l'ordinateur.
"""

import logging

import config

log = logging.getLogger("jarvis.vision")

DEFAULT_QUESTION = "Décris ce que tu vois sur cette image, en une ou deux phrases, en français."


def _field(obj, name, default=""):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


class VisionRouter:
    def __init__(self, ollama_client=None, gemini=None):
        self._ollama = ollama_client
        self.gemini = gemini

    # --- Disponibilité ---------------------------------------------------------------

    @property
    def mode(self) -> str:
        wanted = config.VISION
        if wanted == "local":
            return "local" if config.VISION_MODEL else "none"
        if wanted == "gemini":
            return "gemini" if (self.gemini and self.gemini.available) else "none"
        # auto : le local d'abord (privé), sinon Gemini
        if config.VISION_MODEL:
            return "local"
        if self.gemini and self.gemini.available:
            return "gemini"
        return "none"

    @property
    def available(self) -> bool:
        return self.mode != "none"

    def unavailable_reason(self) -> str:
        return ("la vision n'est pas configurée : installe un modèle qui voit "
                "(ex. ollama pull qwen2.5-vl, puis JARVIS_MODELE_VISION=qwen2.5-vl), "
                "ou configure Gemini")

    # --- Description ------------------------------------------------------------------

    def _ollama_client(self):
        if self._ollama is None:
            import ollama

            self._ollama = ollama.Client(host=config.OLLAMA_HOST)
        return self._ollama

    def _describe_local(self, image: bytes, question: str) -> str:
        response = self._ollama_client().chat(
            model=config.VISION_MODEL,
            messages=[{"role": "user", "content": question, "images": [image]}],
        )
        text = _field(_field(response, "message", {}), "content", "").strip()
        return text or "Je ne distingue rien de particulier."

    def describe(self, image: bytes, question: str = "") -> str:
        if not image:
            return "Je n'ai pas d'image à analyser."
        question = question or DEFAULT_QUESTION
        mode = self.mode
        if mode == "none":
            return "Je reçois l'image, mais " + self.unavailable_reason() + "."
        try:
            if mode == "local":
                return self._describe_local(image, question)
            return self.gemini.describe_image(image, question)
        except Exception as exc:
            log.warning("vision (%s) : %s", mode, exc)
            if mode == "local":
                return (f"Le modèle de vision « {config.VISION_MODEL} » n'a pas répondu. "
                        "Est-il installé ? (ollama pull " + config.VISION_MODEL + ")")
            return "Je n'arrive pas à analyser l'image pour le moment."


def build_router(gemini=None) -> VisionRouter:
    return VisionRouter(gemini=gemini)
