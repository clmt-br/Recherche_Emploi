# Dossier des candidatures

Chaque concrétisation crée automatiquement un sous-dossier ici, organisé
ainsi :

```
Entreprises/
  <NomEntreprise>/
    <Slug_offre>/
      CV_<INI>_<EntrepriseSlug>.pdf      ← CV adapté
      CV_<INI>_<EntrepriseSlug>.tex      ← source LaTeX
      LM_<INI>_<EntrepriseSlug>.docx     ← lettre de motivation
      agent_log.txt                       ← log de génération (debug)
      relance_<...>.ics                   ← (après envoi) relance J+15
```

Exemple concret : si tu t'appelles Marie Curie et postules chez Thales sur un
poste "Chef de projet coûts" :

```
Entreprises/
  Thales/
    Chef_de_projet_couts/
      CV_MC_Thales.pdf
      CV_MC_Thales.tex
      LM_MC_Thales.docx
      agent_log.txt
```

Les initiales `<INI>` viennent de `profile.identite.nom`.

Plusieurs candidatures pour la même entreprise sont possibles (un sous-dossier
par offre).

**Tu peux supprimer / déplacer / archiver les sous-dossiers comme tu veux**
— l'app les recrée si tu re-tentes une concrétisation.
