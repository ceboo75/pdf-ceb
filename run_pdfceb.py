"""Lanceur de PDF Ceb (point d'entrée de l'exécutable Windows)."""
import os
import sys

# En mode fenêtré (sans console), Windows ne fournit pas de sorties standard :
# on les redirige pour que les bibliothèques puissent y écrire sans erreur.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from pdfceb.app import main  # noqa: E402

if __name__ == "__main__":
    main()
