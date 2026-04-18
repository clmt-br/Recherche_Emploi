@echo off
REM Lance l'app en arriere-plan sans garder de fenetre de terminal ouverte.
REM Double-clic sur ce fichier pour demarrer l'app.
cd /d "%~dp0"
start "" /B pythonw.exe app.py
