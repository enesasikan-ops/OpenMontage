# Comment Jarvis s'améliore (en continu, mais en sécurité)

Jarvis progresse avec le temps : ce qu'il ne sait pas faire aujourd'hui, il pourra le
faire demain. Mais **jamais en réécrivant son propre code tout seul** — chaque
amélioration passe par des tests et par ton accord.

## La boucle

```
1. Jarvis bute sur quelque chose  ──► il l'écrit dans son journal d'améliorations
   (« note que tu devrais pouvoir faire X », ou il le note lui-même)
                 │
                 ▼
2. De temps en temps, Claude (le mentor) lit le journal
   (« Jarvis, améliore-toi »)      ──► il écrit la nouvelle capacité + des tests
                 │
                 ▼
3. Les tests tournent.            ──► TOI, tu relis et tu valides.
                 │
                 ▼
4. La nouvelle capacité entre dans Jarvis. Il sait faire la chose. ✅
```

## Au quotidien

- **Jarvis note ses limites** : quand il ne sait pas faire quelque chose, il utilise
  `noter_a_ameliorer`. Tu peux aussi lui dire « note que tu devrais pouvoir… ».
- **Voir la liste** : « Jarvis, montre ta liste d'améliorations » (`journal_ameliorations`).
  Les idées les plus souvent redemandées remontent en premier.
- Le journal est un simple fichier local : `~/.jarvis/ameliorations.json`.

## Lancer une amélioration (toi + Claude)

Quand tu veux, demande au mentor de s'en occuper :

> « Jarvis, regarde ta liste d'améliorations et ajoute-toi la plus demandée. »

En mode mentor (`JARVIS_MENTOR=1`), Claude Code :
1. lit le journal,
2. écrit le nouveau code et **ses tests**, dans l'atelier,
3. te montre ce qu'il a fait,
4. et **tu décides** si ça entre dans Jarvis (rien n'est ajouté sans ton accord).

## Se mettre à jour

- **Nouveaux modèles** : quand un meilleur modèle local sort, `ollama pull <modèle>` et
  Jarvis devient plus malin, sans changer son code.
- **Nouvelles versions du code** : `git pull` récupère les améliorations validées.

## Mode plus autonome (le mentor écrit presque tout)

Avec le mode mentor activé (`JARVIS_MENTOR=1`), Jarvis a l'outil **`ameliorer_jarvis`** :

> « Jarvis, améliore-toi » (ou « ajoute-toi la capacité la plus demandée »)

Claude Code fait alors **en autonomie** : il prend l'idée (ou la plus demandée du journal),
conçoit la capacité, écrit le code **et ses tests**, lance les tests, documente — tout seul,
dans l'atelier. Tu n'as rien à écrire.

Ce qui reste à toi : **relire et activer**. Le code auto-écrit attend dans l'atelier ; tu le
valides avant qu'il entre dans le Jarvis qui pilote le drone, les caméras et le PC.

Deux règles en dur que l'auto-amélioration ne peut pas enfreindre :
- elle **ne modifie jamais** le cœur sensible (`config.py`, `drone.py`, `security.py`,
  la logique de confirmation, `.env`...) ;
- elle **ne retire jamais** une confirmation avant une action dangereuse.

## Les garde-fous (importants)

- Jarvis **ne modifie pas son propre code sans supervision**. Il propose, un humain dispose.
- Chaque ajout a **des tests** : on vérifie que la nouveauté marche et ne casse rien.
- Les nouvelles capacités qui **agissent** (envoyer, piloter, supprimer) gardent la règle
  de Jarvis : **confirmation avant** les actions sensibles.
- C'est de l'amélioration **encadrée**, pas une IA qui se réécrit seule — par choix de
  sécurité, surtout sur une machine qui pilote un drone, des caméras et l'ordinateur.
