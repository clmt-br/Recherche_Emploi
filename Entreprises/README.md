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

Exemple concret : pour Clément Bouillier qui postule chez Thales sur un
poste "Chef de projet coûts" :

```
Entreprises/
  Thales/
    Chef_de_projet_couts/
      CV_CB_Thales.pdf
      CV_CB_Thales.tex
      LM_CB_Thales.docx
      agent_log.txt
```

Plusieurs candidatures pour la même entreprise sont possibles (un sous-dossier
par offre).

**Tu peux supprimer / déplacer / archiver les sous-dossiers comme tu veux**
— l'app les recrée si tu re-tentes une concrétisation.
