# PDF Ceb

Boîte à outils PDF pour Windows, inspirée des fonctionnalités d'iLovePDF, **entièrement locale** : aucun fichier
n'est envoyé sur Internet.

## Installer

1. Ouvrez l'onglet **Releases** du dépôt et téléchargez `PDF-Ceb.exe`.
2. Double-cliquez dessus. Aucune installation n'est nécessaire ; vous pouvez le ranger où vous voulez
   (et l'épingler à la barre des tâches).
3. Au premier lancement, si Windows affiche « Windows a protégé votre ordinateur », cliquez sur
   **Informations complémentaires** puis **Exécuter quand même** (l'exécutable n'est pas signé numériquement).

## Fonctionnalités

| Catégorie | Outils |
|---|---|
| Organiser | Fusionner (PDF et images, signets par fichier) · Diviser (plages, toutes les N pages, page par page) · Supprimer des pages · Extraire des pages · Organiser (glisser-déposer, rotation, pages vierges, ajout d'autres PDF) |
| Optimiser | Compresser (faible / recommandée / forte, traitement par lot) · Réparer |
| Convertir | Images → PDF (format, orientation, marges) · PDF → images JPG/PNG · Extraction des images contenues |
| Modifier | Modification du texte existant (ligne ou paragraphe, police d'origine reconnue, alignement et justification conservés) · Éditeur visuel (texte, image, rectangle, ellipse, ligne, flèche, dessin, surligneur, cache blanc, commentaire) · Faire pivoter · Numéroter les pages · Filigrane texte ou image · Rogner (souris, marges, automatique) · Remplir un formulaire |
| Sécurité | Protéger (AES 256, autorisations) · Déverrouiller · Signer (dessin, saisie, image, signatures mémorisées) · Caviarder (suppression définitive, recherche d'un mot dans tout le document) · Comparer deux versions (rapport PDF) |

Le fichier d'origine n'est jamais modifié : chaque opération enregistre un nouveau fichier.

### Bon à savoir

- **Modifier le texte** : fonctionne sur les PDF « natifs » (exportés depuis Word, LibreOffice, un logiciel métier…),
  pas sur les documents scannés. Le rendu est identique à l'original lorsque la police du document est installée
  sur l'ordinateur (Arial, Calibri, Times New Roman, Cambria…) ou intégrée complètement au PDF ; sinon une police
  proche est utilisée et l'éditeur l'indique. Toute modification invalide une éventuelle signature électronique.

- **Cache blanc ou caviardage ?** Le cache blanc masque visuellement une zone (pour réécrire par-dessus) mais le
  texte reste présent dans le fichier. Le **caviardage** supprime réellement le texte, les images et les tracés.
- **Signature** : il s'agit d'une signature visuelle (image apposée), pas d'une signature électronique certifiée.
- **Comparer** : la comparaison porte sur le texte ; elle ne détecte rien sur un document scanné.

## Développement

```
pip install -r requirements.txt
python run_pdfceb.py              # lancer l'application
python -m pytest tests            # tests du moteur
python -m pdfceb.app --selftest-ui sortie   # test automatique de l'interface + captures
```

La compilation Windows est faite par GitHub Actions (`.github/workflows/build.yml`) : tests, compilation PyInstaller,
vérification de l'exécutable, puis publication dans **Releases** sous le numéro de version défini dans
`pdfceb/__init__.py` (une nouvelle version est créée dès que ce numéro change).

Moteur PDF : [PyMuPDF](https://pymupdf.readthedocs.io/) (licence AGPL, usage personnel). Interface : PySide6 (Qt).
