"""Appairage de Jarvis avec la Freebox (à lancer UNE fois, sur ton réseau).

    python appairer_freebox.py

1. Jarvis demande l'autorisation à la Freebox.
2. VA VALIDER sur l'écran de la Freebox (flèche « oui »).
3. Le script affiche un JETON : copie-le dans .env (JARVIS_FREEBOX_JETON).

Rien ne sort de la maison : l'API Freebox est locale.
"""

import json
import time
import urllib.request

import config

APP = {"app_id": "jarvis", "app_name": "Jarvis", "app_version": "1.0", "device_name": "Serveur Jarvis"}


def _post(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(config.FREEBOX_URL.rstrip("/") + path, data=data,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("Demande d'autorisation envoyée à la Freebox…")
    rep = _post("/api/v4/login/authorize/", APP)
    if not rep.get("success"):
        print("Échec :", rep.get("msg"))
        return
    app_token = rep["result"]["app_token"]
    track_id = rep["result"]["track_id"]
    print("➡️  VALIDEZ maintenant sur l'écran de la Freebox (flèche « oui »)…")

    for _ in range(60):
        time.sleep(2)
        etat = _post(f"/api/v4/login/authorize/{track_id}")
        statut = etat.get("result", {}).get("status")
        if statut == "granted":
            print("\n✅ Appairé ! Mets cette ligne dans ton .env :\n")
            print(f"JARVIS_FREEBOX_JETON={app_token}\n")
            return
        if statut in ("denied", "timeout"):
            print("\n❌ Refusé ou expiré. Relance et valide sur l'écran.")
            return
        print("  …en attente de validation sur la Freebox")
    print("Temps écoulé. Relance le script.")


if __name__ == "__main__":
    main()
