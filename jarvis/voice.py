"""Oreilles (Whisper) et voix (Piper) de Jarvis. Tout tourne en local."""

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import config

SAMPLE_RATE = 16000
YES_WORDS = ("oui", "ouais", "ok", "okay", "vas-y", "vas y", "confirme", "d'accord", "go")


class Listener:
    """Enregistre au micro (appuyer sur Entrée pour parler, Entrée pour finir)."""

    def __init__(self, model_size: str = config.WHISPER_MODEL):
        from faster_whisper import WhisperModel  # import tardif : lourd à charger

        print(f"[voix] Chargement de Whisper « {model_size} »...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def record(self):
        """Enregistre au micro et renvoie le son (float32, mono, 16 kHz)."""
        import numpy as np
        import sounddevice as sd

        chunks: list = []

        def callback(indata, frames, time, status):  # noqa: ARG001
            chunks.append(indata.copy())

        input("🎤 Appuie sur Entrée pour parler...")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
            input("🔴 Je t'écoute. Entrée pour terminer.")
        if not chunks:
            return np.zeros(0, dtype="float32")
        return np.concatenate(chunks)[:, 0]

    def transcribe(self, audio) -> str:
        """Transcrit un son float32 mono 16 kHz (sans passer par un fichier)."""
        if len(audio) < SAMPLE_RATE // 4:  # moins d'un quart de seconde : rien à écouter
            return ""
        segments, _ = self.model.transcribe(audio, language="fr", vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    def listen(self) -> str:
        return self.transcribe(self.record())


class Speaker:
    """Lit un texte à voix haute avec Piper."""

    def __init__(self, voice_path: Path = config.PIPER_VOICE):
        if shutil.which("piper") is None:
            raise RuntimeError("La commande « piper » est introuvable : pip install piper-tts")
        if not voice_path.exists():
            raise RuntimeError(f"Voix introuvable : {voice_path}. Lance ./installer.sh")
        self.voice_path = voice_path

    def say(self, text: str) -> None:
        if not text.strip():
            return
        path = Path(tempfile.mkstemp(suffix=".wav")[1])
        try:
            subprocess.run(
                ["piper", "--model", str(self.voice_path), "--output_file", str(path)],
                input=text.encode("utf-8"), check=True, capture_output=True,
            )
            self._play(path)
        except subprocess.CalledProcessError as exc:
            print(f"[voix] Piper a échoué : {exc.stderr.decode(errors='ignore')[-300:]}")
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _play(path: Path) -> None:
        if platform.system() == "Darwin":
            subprocess.run(["afplay", str(path)], check=False)
            return
        import sounddevice as sd
        import soundfile as sf

        data, rate = sf.read(str(path))
        sd.play(data, rate)
        sd.wait()


def is_yes(text: str) -> bool:
    t = text.lower()
    return any(word in t for word in YES_WORDS) and "non" not in t.split()
