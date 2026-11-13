"""Tests du mode mains libres et de la personnalité (sans micro)."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import handsfree as hf  # noqa: E402
import persona  # noqa: E402

FRAME = hf.FRAME


@pytest.mark.parametrize("text, named, rest", [
    ("Jarvis, quelle heure est-il ?", True, "quelle heure est-il ?"),
    ("Qu'en penses-tu, Jarvis ?", True, "Qu'en penses-tu"),
    ("Bonjour Anne, ici Jarvie.", True, "Bonjour Anne, ici"),
    ("Dis Djarvis allume la lumière", True, "Dis allume la lumière"),
    ("J'arvis, la météo", True, "la météo"),
    ("Jarvis.", True, ""),
    ("Jarvis ?", True, ""),
    ("On mange quoi ce soir ?", False, "On mange quoi ce soir ?"),
    ("J'arrive dans cinq minutes", False, "J'arrive dans cinq minutes"),
    ("Il a servi le service", False, "Il a servi le service"),
])
def test_split_wake(text, named, rest):
    assert hf.split_wake(text) == (named, rest)


def test_sleep_and_noise_detection():
    assert hf.is_sleep("Merci") and hf.is_sleep("ce sera tout")
    assert not hf.is_sleep("merci de me rappeler demain à huit heures de sortir")
    assert hf.is_noise("Sous-titres réalisés par la communauté d'Amara.org")
    assert hf.is_noise("...") and not hf.is_noise("Quelle heure est-il ?")


def silence(n):
    return [np.zeros(FRAME, dtype=np.float32)] * n


def speech(n, level=0.2):
    rng = np.random.default_rng(0)
    return [(rng.standard_normal(FRAME) * level).astype(np.float32) for _ in range(n)]


def test_segmenter_cuts_one_utterance_per_phrase():
    seg = hf.Segmenter()
    frames = silence(20) + speech(40) + silence(40) + speech(20) + silence(40)
    out = [a for a in (seg.feed(f) for f in frames) if a is not None]
    assert len(out) == 2
    # 40 blocs de voix + pré-écoute + silence de fin
    assert 40 * FRAME <= len(out[0]) <= (40 + 10 + 27) * FRAME


def test_segmenter_ignores_clicks_and_quiet_noise():
    seg = hf.Segmenter()
    frames = silence(10) + speech(1) + silence(30) + speech(60, level=0.003) + silence(30)
    assert all(seg.feed(f) is None for f in frames)


def test_segmenter_cuts_very_long_speech():
    seg = hf.Segmenter(max_frames=100)
    out = [a for a in (seg.feed(f) for f in speech(250)) if a is not None]
    assert len(out) == 2 and len(out[0]) == 100 * FRAME


class ScriptedListener:
    """Chaque phrase détectée est « transcrite » par le texte suivant du script."""

    def __init__(self, texts):
        self.texts = list(texts)

    def transcribe(self, audio):
        return self.texts.pop(0)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(texts, n_utterances=None):
    n = len(texts) if n_utterances is None else n_utterances
    frames = []
    for _ in range(n):
        frames += speech(20) + silence(40)
    clock = Clock()
    hands = hf.HandsFree(ScriptedListener(texts), frames, clock=clock, awake_s=30, log=lambda s: None)
    return hands, clock


def test_ignores_talk_until_name_is_said():
    hands, _ = make(["On mange quoi ce soir ?", "Je ne sais pas.", "Jarvis, quel temps fait-il ?"])
    assert hands.next_command() == "quel temps fait-il ?"


def test_bare_name_returns_none_then_follow_up_without_name():
    hands, _ = make(["Jarvis.", "quelle heure est-il"])
    assert hands.next_command() is None
    assert hands.next_command() == "quelle heure est-il"


def test_follow_up_window_expires():
    hands, clock = make(["Jarvis, bonjour", "et demain ?", "phrase ignorée", "Jarvis, encore toi"])
    assert hands.next_command() == "bonjour"
    hands.spoke()
    clock.t = 10
    assert hands.next_command() == "et demain ?"      # dans les 30 s : pas besoin du nom
    hands.spoke()
    clock.t = 100                                      # 90 s plus tard : il faut redire Jarvis
    assert hands.next_command() == "encore toi"


def test_sleep_closes_the_window():
    hands, _ = make(["Jarvis, salut", "phrase ignorée", "Jarvis, reviens"])
    hands.next_command()
    hands.spoke()
    hands.sleep()
    assert hands.next_command() == "reviens"


def test_whisper_hallucination_is_not_a_command():
    hands, _ = make(["Jarvis, salut", "Sous-titres réalisés par la communauté d'Amara.org", "et la météo ?"])
    hands.next_command()
    hands.spoke()
    assert hands.next_command() == "et la météo ?"


def test_muted_while_jarvis_speaks():
    frames = speech(20) + silence(40) + speech(20) + silence(40)
    flushed = []
    hands = hf.HandsFree(ScriptedListener(["Jarvis, vraie question"]), frames,
                         flush=lambda: flushed.append(1), clock=Clock(), log=lambda s: None)
    hands.mute()
    it = hands._frames
    for _ in range(60):                 # Jarvis parle : ces 60 blocs sont jetés
        frame = next(it)
        assert hands._muted.is_set()
        hands.segmenter.reset()
        del frame
    hands.spoke()
    assert flushed == [1] and hands.awake
    assert hands.next_command() == "vraie question"


def test_end_of_audio_raises_eof():
    hands, _ = make(["rien pour jarvis… en fait si"], n_utterances=0)
    with pytest.raises(EOFError):
        hands.next_command()


# --- Personnalité ---

def test_film_persona(monkeypatch):
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    assert persona.greeting(9) == "Bonjour Monsieur. Tous les systèmes sont opérationnels. Que puis-je pour vous ?"
    assert persona.greeting(21).startswith("Bonsoir Monsieur")
    assert persona.greeting(2).startswith("Vous veillez tard")
    assert persona.wake_ack() == "Oui, Monsieur ?"
    assert "vouvoies" in persona.character() and "« Monsieur »" in persona.character()
    assert "Claude" in persona.asking_claude()


def test_title_defaults_to_first_name_and_friend_style(monkeypatch):
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "")
    monkeypatch.setattr(config, "USER_NAME", "Enes")
    assert persona.wake_ack() == "Oui, Enes ?"
    monkeypatch.setattr(config, "STYLE", "ami")
    assert persona.greeting(9) == "Bonjour Enes, je t'écoute."
    assert "tutoies" in persona.character()


def test_system_prompt_carries_the_persona(tmp_path, monkeypatch):
    from brain import system_prompt
    from memory import Memory

    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "Madame")
    prompt = system_prompt(Memory(tmp_path / "m.json"))
    assert "majordome" in prompt and "« Madame »" in prompt and "demander_a_claude" in prompt
