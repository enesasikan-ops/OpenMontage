"""Mode mains libres : dis « Jarvis » dans une phrase, il répond, puis reste à
l'écoute quelques secondes pour la suite — sans toucher au clavier.

Tout se passe sur l'ordinateur : le micro est découpé en phrases (détection de
voix par le volume), chaque phrase est transcrite par Whisper, et Jarvis ne
réagit que si son nom est prononcé ou si la conversation est en cours.
Ce qui n'est pas adressé à Jarvis est jeté aussitôt, jamais enregistré.
"""

import queue
import re
import threading
import time
from collections import deque
from typing import Callable, Iterable, Iterator

import config

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms

# « Jarvis » tel que Whisper l'entend parfois : Jarvie, Jarvi, Djarvis, Gervis, J'arvis...
WAKE_RE = re.compile(r"\b(?:d?j'?|g|ch)[ae]r+v[iy](?:sse|ss|ce|s|e|x|z)?\b[\s,.!?:;…-]*", re.IGNORECASE)
SLEEP_RE = re.compile(r"\b(merci|ce sera tout|c'est tout|au revoir|bonne nuit|laisse tomber)\b",
                      re.IGNORECASE)


def split_wake(text: str) -> tuple[bool, str]:
    """(nom prononcé ?, phrase sans le nom)."""
    if not WAKE_RE.search(text):
        return False, text.strip()
    rest = WAKE_RE.sub(" ", text)
    rest = re.sub(r"\s+", " ", rest).strip(" ,.;:-")
    return True, rest if re.search(r"\w", rest) else ""


# Phrases que Whisper invente parfois sur du bruit ou du silence.
HALLUCINATIONS = ("sous-titres", "sous-titrage", "amara.org", "merci d'avoir regardé", "abonnez-vous")


def is_noise(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in HALLUCINATIONS) or not re.search(r"\w{2,}", low)


def is_sleep(text: str) -> bool:
    """« Merci Jarvis », « ce sera tout » : fin de la conversation."""
    return bool(SLEEP_RE.search(text)) and len(text.split()) <= 5


class Segmenter:
    """Découpe un flux audio en phrases, d'après le volume."""

    def __init__(self, start_frames: int = 3, end_frames: int = 27, preroll: int = 10,
                 max_frames: int = 660, min_level: float = 0.012):
        self.start_frames, self.end_frames, self.max_frames = start_frames, end_frames, max_frames
        self.min_level = min_level
        self.noise = 0.004
        self._pre: deque = deque(maxlen=preroll)
        self.reset()

    def reset(self) -> None:
        self._pre.clear()
        self._buf: list = []
        self._loud = 0
        self._quiet = 0
        self._speaking = False

    def feed(self, frame):
        """Ajoute 30 ms de son ; renvoie la phrase complète quand elle se termine, sinon None."""
        import numpy as np

        level = float(np.sqrt(np.mean(frame ** 2))) if len(frame) else 0.0
        loud = level > max(self.min_level, self.noise * 3)
        if not self._speaking:
            self._pre.append(frame)
            if loud:
                self._loud += 1
                if self._loud >= self.start_frames:
                    self._speaking, self._buf, self._quiet = True, list(self._pre), 0
            else:
                self._loud = 0
                self.noise = 0.95 * self.noise + 0.05 * level  # s'adapte au bruit ambiant
            return None
        self._buf.append(frame)
        self._quiet = 0 if loud else self._quiet + 1
        if self._quiet >= self.end_frames or len(self._buf) >= self.max_frames:
            audio = np.concatenate(self._buf)
            self.reset()
            return audio
        return None


class MicSource:
    """Micro en continu (sounddevice). Les blocs de 30 ms arrivent dans une file."""

    def __init__(self):
        import sounddevice as sd

        self.q: queue.Queue = queue.Queue()
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                     blocksize=FRAME, callback=self._callback)
        self.stream.start()

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        self.q.put(indata[:, 0].copy())

    def frames(self) -> Iterator:
        while True:
            yield self.q.get()

    def flush(self) -> None:
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


class HandsFree:
    def __init__(self, listener, frames: Iterable, flush: Callable[[], None] = lambda: None,
                 clock: Callable[[], float] = time.monotonic,
                 awake_s: float = config.AWAKE_SECONDS, log: Callable[[str], None] = print):
        self.listener = listener
        self._frames = iter(frames)
        self._flush = flush
        self.clock = clock
        self.awake_s = awake_s
        self.log = log
        self.segmenter = Segmenter()
        self.awake_until = 0.0
        self._muted = threading.Event()

    # --- Jarvis ne doit pas s'écouter parler ---------------------------------

    def mute(self) -> None:
        self._muted.set()

    def spoke(self) -> None:
        """À appeler quand Jarvis a fini de parler : on rouvre le micro et on
        reste à l'écoute pour la suite de la conversation."""
        self._flush()
        self.segmenter.reset()
        self.awake_until = self.clock() + self.awake_s
        self._muted.clear()

    def sleep(self) -> None:
        self.awake_until = 0.0

    @property
    def awake(self) -> bool:
        return self.clock() < self.awake_until

    # --- Écoute ------------------------------------------------------------------

    def next_utterance(self) -> str:
        """Prochaine phrase entendue (quelle qu'elle soit), transcrite."""
        for frame in self._frames:
            if self._muted.is_set():
                self.segmenter.reset()
                continue
            audio = self.segmenter.feed(frame)
            if audio is None:
                continue
            text = self.listener.transcribe(audio)
            if text:
                return text
        raise EOFError

    def next_command(self) -> str | None:
        """Prochaine phrase adressée à Jarvis.

        Renvoie la phrase (sans le nom), ou None si on a juste dit « Jarvis ».
        """
        while True:
            text = self.next_utterance()
            named, rest = split_wake(text)
            if named:
                self.awake_until = self.clock() + self.awake_s
                return rest or None
            if self.awake and not is_noise(text):
                return rest
            # Pas pour Jarvis : on jette, sans rien garder ni afficher.
