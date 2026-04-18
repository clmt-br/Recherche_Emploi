@echo off
REM Build le .exe Windows via flet pack.
REM Pre-requis : `pip install pyinstaller flet[all]`
REM Le .exe genere ne contient PAS xelatex ni Claude Code CLI ni Python pour
REM les scrapers : a installer separement par chaque utilisateur.
REM Le CV_template.tex et le dossier Entreprises/ doivent etre A COTE du .exe.

cd /d "%~dp0"

echo Build de RechercheEmploi.exe...
flet pack app.py ^
    --name "RechercheEmploi" ^
    --hidden-import claude_agent_sdk ^
    --hidden-import keyring.backends.Windows ^
    --hidden-import win32ctypes ^
    --hidden-import win32ctypes.pywin32 ^
    --hidden-import win32ctypes.pywin32.win32cred

echo.
echo Build termine. Le .exe est dans dist\RechercheEmploi.exe
echo Distribuer : .exe + README.md + CV_template.tex + dossier Entreprises\
pause
