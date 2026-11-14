"""Tests de la voix : la prosodie (pose, pauses, expressivité) est transmise à Piper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import voice  # noqa: E402


def _speaker(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "find_program", lambda name: "/usr/bin/piper")
    voix = tmp_path / "voix.onnx"
    voix.write_bytes(b"")                 # fichier de voix factice
    return voice.Speaker(voice_path=voix)


def test_prosodie_transmise_a_piper(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PIPER_VITESSE", 1.06)
    monkeypatch.setattr(config, "PIPER_PAUSES", 0.35)
    monkeypatch.setattr(config, "PIPER_EXPRESSIVITE", 0.7)
    cmd = _speaker(tmp_path, monkeypatch).command(tmp_path / "out.wav")
    assert cmd[cmd.index("--length_scale") + 1] == "1.06"       # plus posé
    assert cmd[cmd.index("--sentence_silence") + 1] == "0.35"   # respiration
    assert cmd[cmd.index("--noise_scale") + 1] == "0.7"         # intonation


def test_la_voix_et_la_sortie_sont_dans_la_commande(tmp_path, monkeypatch):
    sp = _speaker(tmp_path, monkeypatch)
    cmd = sp.command(tmp_path / "out.wav")
    assert "--model" in cmd and str(sp.voice_path) in cmd
    assert cmd[cmd.index("--output_file") + 1].endswith("out.wav")
