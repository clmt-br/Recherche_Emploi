# Recherche Emploi - Application desktop

Application Python qui automatise la recherche d'emploi : scrape APEC,
LinkedIn, WTTJ ; prépare CV LaTeX + lettre de motivation DOCX adaptés à
chaque offre via Claude Code ; suit le pipeline `rapport → en cours →
envoyée` avec relances calendrier.

**Une seule action utilisateur** par candidature : clic sur ✨ Concrétiser.
L'agent Claude lit ton profil, explore le site de l'entreprise, génère le
CV personnalisé et la lettre, vérifie em-dash/accents/mise en page, et
dépose les fichiers. Concrétisations en parallèle (jusqu'à 5 simultanées).

---

## Prérequis (à installer une fois)

### 1. Python 3.11+

[Télécharge Python](https://www.python.org/downloads/). Pendant l'install,
coche **"Add Python to PATH"**.

### 2. MikTeX (compilation LaTeX du CV)

[Télécharge MikTeX](https://miktex.org) (~500 MB). Au premier lancement,
accepte les installations automatiques de packages.

Vérification : `xelatex --version` dans un terminal.

### 3. Claude Code CLI + abonnement Pro/Max

```
npm install -g @anthropic-ai/claude-code
claude       # connexion : ouvre une page browser pour login
```

Vérification : retape `claude` dans un terminal — ça doit ouvrir Claude Code
normalement (= tu es loggé).

L'app **réutilise ton abonnement Claude Code** — aucune clé API à configurer,
aucun coût additionnel. Juste les rate limits de ton forfait (Max = 50
messages / 5h).

### 4. (Optionnel) Cookie LinkedIn

Pour activer le scraper LinkedIn :
1. Ouvre [linkedin.com](https://www.linkedin.com) connecté
2. F12 → Application → Cookies → linkedin.com
3. Copie la valeur de `li_at` (longue chaîne alphanumérique)

Tu la saisiras dans Paramètres ou le wizard d'onboarding. Sans cookie,
LinkedIn est sauté ; APEC et WTTJ continuent de fonctionner.

---

## Installation

Tu as 2 modes au choix :

### Mode A — `.exe` (recommandé, plus simple)

Aucune installation Python nécessaire pour lancer l'app. **Mais** tu dois
installer Python quand même pour les scrapers (étape suivante).

Le `.exe` `RechercheEmploi.exe` est dans le dossier — double-clic suffit
pour lancer l'app.

⚠️ **Le scan d'offres** (bouton "Lancer le scan") lance les scrapers Python
en subprocess. Tu dois donc avoir Python installé + faire :
```
pip install -r OUTILS/requirements.txt
```

### Mode B — Code source (avancé)

```
pip install -r prototype_flet/requirements.txt
pip install -r OUTILS/requirements.txt
```

Lancer : `python prototype_flet/app.py` ou double-clic sur
`prototype_flet/launch.bat`.

## Personnalisation du CV

Le fichier `CV_template.tex` est ton template LaTeX. **Avant le premier
usage**, ouvre-le et remplace tous les `[PLACEHOLDERS]` par tes infos :
nom, email, téléphone, expériences, formation, compétences.

Compile-le une fois pour vérifier :
```
xelatex CV_template.tex
```
Tu dois obtenir un `CV_template.pdf` d'**une seule page**.

> Astuce : tu peux renommer en `CV_<TonNom>_base.tex` si tu veux. Configure
> le nom dans `prototype_flet/settings.yaml` (clé `cv_base_filename`).

## Premier lancement

**Mode .exe** : double-clic sur `RechercheEmploi.exe`.

**Mode code source** : `python prototype_flet/app.py` ou double-clic sur
`prototype_flet/launch.bat` (lance via `pythonw.exe` = pas de fenêtre
console résiduelle).

Au premier démarrage, le **wizard d'onboarding** te guide en 3 étapes :
1. Cookie LinkedIn (optionnel)
2. Vérification xelatex
3. Indication d'aller remplir ton profil

Va ensuite dans **l'onglet Profil** (icône à gauche) et remplis tes 8
sections : identité, formation, expériences, intérêts, ambitions, cibles,
cadres positionnement, règles rédaction.

**Le profil est vide à l'installation** — tu saisis tes propres infos.
Clique "Enregistrer tout" en haut à droite quand tu as fini. Les données
sont sauvegardées dans `profile.yaml` à côté de l'app.

Tu peux aussi pré-remplir l'onglet Paramètres : mots-clés de recherche
pour les scrapers (ex: "ingenieur mecanique, conception"), heure du scan,
modèle Claude (Sonnet par défaut).

## Workflow type

1. **Onglet Tableau** → "Lancer le scan" : scrape APEC + LinkedIn + WTTJ
   (2-5 min). Les nouvelles offres apparaissent en **Rapport du jour**.

2. Pour chaque offre intéressante du Rapport, clique l'icône ✨ violette
   "Concrétiser". L'agent Claude démarre — tu vois sa progression dans le
   panneau "Concrétisations en cours" (ProgressRing + état + bouton 📁
   pour ouvrir le dossier).

3. Tu peux concrétiser plusieurs offres en parallèle (clique successivement).
   Les cards s'accumulent.

4. Quand l'agent a fini, l'offre passe en **Candidatures en cours** avec ses
   fichiers `CV_<INI>_<Entreprise>.pdf` et `LM_<INI>_<Entreprise>.docx` dans
   le dossier `Entreprises/<Entreprise>/<Slug>/`.

5. Audite, envoie le mail manuellement, puis clique ✉️ "Marquer envoyée".
   Un fichier `.ics` est généré pour la relance J+15 (double-clic = import
   dans Google Calendar).

## Paramètres (onglet Paramètres)

- **Modèle Claude** : Sonnet 4.6 (recommandé), Opus 4.7 (qualité max),
  Haiku 4.5 (rapide). Couvert par ton forfait.
- **Concurrence agents** : 1-5 simultanés. Plus haut = plus rapide mais
  attention aux rate limits du forfait.
- **Cookie LinkedIn** : modifiable
- **Mots-clés, départements, sources actives** : pilotent les scrapers
- **Heure du scan** + **Programmer la tâche Windows** : automatisation L-V

---

## Architecture technique

```
RechercheEmploi/
  CV_template.tex          ← template LaTeX (à adapter une fois)
  prototype_flet/
    app.py                 ← entrypoint Flet + onboarding bascule
    pages.py               ← UI : Tableau, Profil, Paramètres
    db.py                  ← SQLite local (offres, formulations, app_meta)
    config.py              ← profile.yaml + settings.yaml
    scan.py                ← subprocess parallèle des scrapers
    agent_runner.py        ← lance UN agent Claude SDK + retry intelligent
    orchestrator.py        ← lance N agents en parallèle (Semaphore + gather)
    prompt_builder.py      ← system + user prompts depuis profile.yaml
    validators.py          ← vérifs post-gen (PDF 1p, em dash, accents, ATS)
    mcp_tools.py           ← outils MCP custom (anti-répétition LM)
    flet_async_bridge.py   ← pont asyncio ↔ Flet
    secrets_store.py       ← Windows Credential Manager (cookie LinkedIn)
    onboarding.py          ← wizard 3 étapes
    concretize.py          ← helpers filesystem
    calendar_ics.py        ← export .ics relance J+15
  OUTILS/
    apec_batch.py          ← scraper APEC (API publique)
    linkedin_batch.py      ← scraper LinkedIn (API Voyager + cookie)
    wttj_batch.py          ← scraper WTTJ (Algolia publique)
    merge_sources.py       ← fusion + déduplication des 3 sources
```

### Flow de génération

```
clic ✨ Concrétiser
   |
   v
orchestrator.run_batch([id])
   |
   v
agent_runner.run_one(offre, profile)
   |
   |--> copie CV_template.tex → folder/CV_<INI>_<slug>.tex
   |--> prompt_builder.build_system_prompt(profile, formulations)
   |--> prompt_builder.build_user_prompt(offre, folder, ...)
   |
   v
ClaudeSDKClient (bypassPermissions, login Claude Code)
   |
   |--> async for msg : stream texte / outils → cards UI
   |
   v
validators.run_all(folder)
   |
   |--> compile xelatex OK ? PDF=1page ? em-dash absents ?
   |    accents OK ? mots-clés ATS injectés ?
   |
   v
Si OK → DB statut=en_cours
Si KO → retry intelligent (1 fois) avec format_errors_for_retry
       sinon statut=a_revoir (visible dans le filtre "À revoir")
```

---

## Troubleshooting

### "xelatex not found"
Installer MikTeX et ajouter au PATH. Vérifier `xelatex --version` dans cmd.

### "Invalid API key" dans `agent_log.txt`
Une variable d'env `ANTHROPIC_API_KEY` traîne quelque part. L'app la
supprime au démarrage, mais vérifie tes variables d'env Windows utilisateur
(menu Démarrer → "Variables d'environnement") et supprime-la si présente.
L'app utilise ton login Claude Code, pas de clé API.

### LinkedIn 401/403
Le cookie a expiré (~1 an de validité). Récupère un nouveau `li_at` (F12) et
mets-le à jour dans Paramètres.

### Compilation LaTeX échoue
Le retry intelligent corrige souvent. Sinon ouvre le `.tex` dans le dossier
candidature et compile manuellement avec
`xelatex -interaction=nonstopmode <fichier>.tex` pour voir l'erreur.

### "Em dash détectés" en validation
Le retry intelligent corrige automatiquement. Sinon édition manuelle du
`.tex` : remplacer `--` ou `---` par un tiret simple `-` ou une virgule.

### Page Profil affiche un grand espace gris
Bug Flet 0.84 ListView corrigé. Si vous voyez encore ce comportement,
mettez à jour Flet : `pip install --upgrade flet`.

---

## Crédits

Application développée avec [Claude Code](https://claude.com/claude-code).
Template LaTeX adaptable, UI Flet, scrapers APEC/LinkedIn/WTTJ, génération
agentique CV/LM via Claude Agent SDK.
