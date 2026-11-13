"""Tests du tripwire d'intégrité du cœur."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_integrity import CoreIntegrity  # noqa: E402

FICHIERS = ("a.py", "b.py")


def _mettre_en_place(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    return CoreIntegrity(tmp_path / "ref.json", racine=tmp_path, fichiers=FICHIERS)


def test_pas_d_alerte_au_depart(tmp_path):
    ci = _mettre_en_place(tmp_path)
    assert ci.verifier() == []


def test_detecte_une_modification(tmp_path):
    ci = _mettre_en_place(tmp_path)
    (tmp_path / "a.py").write_text("x = 999  # modifié\n", encoding="utf-8")
    alertes = ci.verifier()
    assert any(critique and "MODIFIÉ" in msg and "a.py" in msg for critique, msg in alertes)


def test_detecte_une_suppression(tmp_path):
    ci = _mettre_en_place(tmp_path)
    (tmp_path / "b.py").unlink()
    assert any("SUPPRIMÉ" in msg and "b.py" in msg for _, msg in ci.verifier())


def test_alerte_persiste_jusqu_au_rebase(tmp_path):
    ci = _mettre_en_place(tmp_path)
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert ci.verifier()          # alerte tant qu'on n'a pas accepté
    ci.rebaser()                  # le propriétaire accepte le nouvel état
    assert ci.verifier() == []    # plus d'alerte


def test_reference_persiste_entre_redemarrages(tmp_path):
    ref = tmp_path / "ref.json"
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    CoreIntegrity(ref, racine=tmp_path, fichiers=FICHIERS)   # pose la référence
    (tmp_path / "a.py").write_text("x = piraté\n", encoding="utf-8")  # modifié hors ligne
    ci2 = CoreIntegrity(ref, racine=tmp_path, fichiers=FICHIERS)       # « redémarrage »
    assert any("MODIFIÉ" in msg for _, msg in ci2.verifier())          # détecté quand même
