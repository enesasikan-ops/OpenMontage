# Sécurité de Jarvis — modèle de menaces

Ce document décrit la surface d'attaque de Jarvis, les protections en place et les zones à
tester. Il est destiné à un **test de sécurité autorisé, sur sa propre instance** (celle du
propriétaire). Il ne contient pas d'exploit : c'est une carte pour un audit défensif.

> Si le dépôt est **public**, ce document l'est aussi. Il décrit le modèle de sécurité, pas
> des secrets. Pour une instance personnelle, garder le dépôt **privé** reste conseillé.

## Vue d'ensemble

Jarvis tourne **en local** sur la machine du propriétaire. Un modèle local (Ollama) décide
et appelle des outils ; un renfort (Claude/Gemini) est sollicité pour le difficile. Tout ce
qui est sensible passe par une **confirmation** du propriétaire.

## Frontières de confiance

| Zone | Confiance | Remarque |
|---|---|---|
| Modèle local + outils | moyenne | le LLM choisit les outils ; une injection peut l'orienter |
| Renfort Claude/Gemini (CLI/API) | externe | sort du réseau ; ne reçoit jamais de secret |
| Plugins (`plugins/`) | **exécutés avec tous les droits** | voir « RCE par conception » |
| Messages entrants (Telegram/Signal) | non fiables | filtrés à un seul expéditeur autorisé |
| Pages web / caméras / domotique | non fiables | données externes, jamais des instructions |
| `.env` (secrets) | critique | hors git, jamais envoyé à un service externe |

## Points d'entrée (à tester en priorité)

1. **Bots Telegram / Signal** — l'entrée principale. Auth : un seul ID (Telegram) ou un seul
   numéro (Signal). À tester : usurpation d'expéditeur, messages d'un autre compte, abus des
   commandes (`valide`, `cœur …`), injection de prompt visant à déclencher un outil sensible.
2. **Tableau de bord HTTP** (`dashboard.py`) — par défaut sur `127.0.0.1` (local). Exposable
   au réseau ; dans ce cas un **jeton** est requis (`JARVIS_ECRAN_JETON`). À tester : accès
   sans jeton quand exposé, fuite d'infos (rappels, listes, état maison), 404/401.
3. **Lecture de page web** (`web.py`) — garde-fou **anti-SSRF** : refuse les adresses
   internes (box, Ollama, Home Assistant, métadonnées cloud) et les schémas non http(s).
   À tester : contournement (redirections, DNS rebinding, IPv6, encodages d'IP).
4. **Caméras** (`camera.py`) — ffmpeg restreint à `rtsp/http/https` avec liste blanche de
   protocoles (pas de `file://`). À tester : lecture de fichiers locaux, protocoles exotiques.
5. **Renfort via CLI** (`claude_bridge.py`) — `subprocess` **sans shell**, entrée par stdin,
   clés d'API retirées de l'environnement du sous-processus. À tester : injection d'arguments.
6. **Auto-amélioration** (`growth.py`) — code écrit par l'IA, **jamais appliqué sans ✅**,
   fichiers du cœur interdits. À tester : échappement de l'atelier, écriture hors dossier.
7. **Propositions de cœur** (`core_proposals.py`) — réservé au propriétaire, diff + tests
   isolés + validation obligatoire ; `.env` exclu. À tester : traversée de chemin, application
   sans validation, fichier modifié entre proposition et application (déjà contrôlé).
8. **Domotique / drone** — actions réelles. À tester : déclenchement sans confirmation.

## Protections en place

- **Un seul interlocuteur** autorisé par bot (ID / numéro).
- **Confirmation** du propriétaire pour toute action sensible (le LLM ne peut pas l'outrepasser).
- **Fichiers du cœur protégés** : l'auto-amélioration ne les touche jamais ; modifiables
  seulement via une proposition relue et validée par le propriétaire.
- **Secrets** dans `.env` (hors git) ; `.env.example` vide ; jamais d'e-mail/nom envoyé dehors.
- **Anti-SSRF** (`netguard.py`) sur la lecture de page ; **ffmpeg** sans accès disque.
- **Tableau de bord** : local par défaut, jeton à temps constant si exposé.
- **Validation de noms** (plugins, propositions) et **anti-traversée de chemin**.
- **Rien n'est appliqué sans un humain** : génération → sandbox → tests → ✅.
- **Cybersurveillance continue** (`cyberwatch.py`) : en boucle, la sentinelle machine
  **et** un **tripwire d'intégrité du cœur** (`core_integrity.py`) qui alerte si un fichier
  du cœur est modifié/supprimé hors du circuit validé. Après un changement légitime, le
  propriétaire « rebase » la référence (commande `rebase cœur`). Limite : la référence est
  un fichier local — un attaquant qui modifie le code peut aussi la modifier ; c'est un
  signal précoce, à compléter par des droits de fichiers stricts et un compte dédié.
- **Défense active** (`defense.py`, sur la machine, jamais offensive) : journal horodaté
  des alertes critiques (preuves) et **copie saine du cœur** restaurable si on le trafique
  (`restaure cœur <fichier>`, sur confirmation ; `sauvegarde cœur` pour refaire la référence
  après une install/mise à jour saine). Pas de « hack back » : aucune action contre un tiers.
- ~360 tests automatisés, dont des tests de sécurité dédiés.

## RCE par conception (le risque principal, assumé)

Un plugin est du **code Python exécuté avec les droits de Jarvis**. C'est voulu (c'est ainsi
qu'on ajoute des capacités). La défense est **procédurale** : ne charger que du code relu, et
l'approbation humaine avant activation. Quiconque réussit à faire exécuter du code comme
plugin obtient l'exécution complète. C'est la cible n°1 d'un test : par où du code non relu
pourrait-il entrer et être chargé.

## Limites connues

- **DNS rebinding** : l'anti-SSRF vérifie à la résolution, pas à la connexion. Pour un
  durcissement total, fixer l'IP résolue.
- **Injection de prompt** : une page/un message malveillant peut tenter d'orienter le LLM ;
  la barrière finale reste la confirmation humaine sur les actions sensibles.
- Jarvis a autant de pouvoir que la machine : domotique, drone, fichiers. L'isoler (compte
  dédié, pare-feu, réseau séparé pour les objets) réduit l'impact d'une compromission.

## Signaler une faille

Ne pas ouvrir d'issue publique. Contacter directement le propriétaire du dépôt.
