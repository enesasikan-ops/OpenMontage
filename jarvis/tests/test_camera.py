"""Tests des caméras par adresse de flux (ffmpeg et vision simulés)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import camera as cam  # noqa: E402
from camera import CameraBook, CameraManager, build_camera_tools  # noqa: E402

FRAME = b"\xff\xd8\xff image de camera"


def manager(tmp_path, describe=lambda f, q="": "Il y a du monde sur la plage.", grab=None):
    grab = grab if grab is not None else (lambda url: FRAME)
    return CameraManager(CameraBook(tmp_path / "cameras.json"), describe=describe, grab=grab)


def test_add_and_look_by_name(tmp_path):
    m = manager(tmp_path)
    assert "enregistrée" in m.add("Plage de Nice", "https://exemple.fr/plage.m3u8")
    assert m.look("plage de nice") == "Il y a du monde sur la plage."


def test_look_by_direct_url(tmp_path):
    grabbed = {}
    m = manager(tmp_path, grab=lambda url: grabbed.setdefault("url", url) or FRAME)
    m.look("https://exemple.fr/trafic.mjpg")
    assert grabbed["url"] == "https://exemple.fr/trafic.mjpg"


def test_add_rejects_non_url(tmp_path):
    m = manager(tmp_path)
    assert "lien de flux" in m.add("X", "pas une adresse")


def test_look_unknown_camera_lists_known(tmp_path):
    m = manager(tmp_path)
    m.add("plage", "https://exemple.fr/p.m3u8")
    out = m.look("montagne")
    assert "ne connais pas" in out and "plage" in out


def test_look_stream_unavailable(tmp_path):
    m = manager(tmp_path, grab=lambda url: None)
    m.add("plage", "https://exemple.fr/p.m3u8")
    assert "n'arrive pas à récupérer" in m.look("plage")


def test_look_without_vision(tmp_path):
    m = manager(tmp_path, describe=None)
    m.add("plage", "https://exemple.fr/p.m3u8")
    assert "vision n'est pas configurée" in m.look("plage")


def test_vision_error_is_friendly(tmp_path):
    def boom(frame, q=""):
        raise RuntimeError("modèle absent")

    m = manager(tmp_path, describe=boom)
    assert "n'arrive pas à analyser" in m.look("https://exemple.fr/p.m3u8")


def test_forget_and_list(tmp_path):
    m = manager(tmp_path)
    m.add("plage", "https://exemple.fr/p.m3u8")
    m.add("route", "https://exemple.fr/r.m3u8")
    assert "plage" in m.list_text() and "route" in m.list_text()
    assert "oublié" in m.forget("plage")
    assert "pas de caméra" in m.forget("plage")


def test_persists_on_disk(tmp_path):
    manager(tmp_path).add("plage", "https://exemple.fr/p.m3u8")
    m2 = CameraManager(CameraBook(tmp_path / "cameras.json"), describe=lambda f, q="": "ok")
    assert m2.book.find("plage") == "https://exemple.fr/p.m3u8"


def test_grab_frame_builds_ffmpeg_command():
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return NS(stdout=FRAME)

    assert cam.grab_frame("https://exemple.fr/p.m3u8", run=fake_run) == FRAME
    assert seen["cmd"][0] == "ffmpeg" and "https://exemple.fr/p.m3u8" in seen["cmd"]
    assert "-rtsp_transport" not in seen["cmd"]
    # RTSP : transport tcp ajouté
    cam.grab_frame("rtsp://cam/stream", run=fake_run)
    assert "-rtsp_transport" in seen["cmd"]


def test_grab_frame_handles_ffmpeg_missing():
    def missing(cmd, **kw):
        raise FileNotFoundError("ffmpeg")

    assert cam.grab_frame("https://exemple.fr/p.m3u8", run=missing) is None


def test_tools_registered(tmp_path):
    m = manager(tmp_path)
    tools = {t.name: t for t in build_camera_tools(m)}
    assert {"regarder_camera", "ajouter_camera", "lister_cameras", "oublier_camera"} <= set(tools)
    assert tools["regarder_camera"].confirm is None   # regarder une caméra publique : pas de confirmation
