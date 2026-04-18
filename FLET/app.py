"""Point d'entree de l'app Flet - Centre de controle recherche d'emploi.

Lancement dev   : python app.py
Packaging .exe  : flet pack app.py --name "RechercheEmploi"
                  (ou flet build windows pour la chaine de build moderne)

L'app utilise le Claude Agent SDK qui s'appuie sur le CLI `claude` deja
installe et logge (forfait Claude Pro/Max). Pas de cle API a configurer.
Au premier lancement, un wizard d'onboarding configure le cookie LinkedIn
(optionnel) et indique d'aller remplir le profil.
"""
import os
import shutil
import subprocess
import sys

import flet as ft

# ---- Supprimer les fenetres console des subprocess (Windows) ----
# Le Claude Agent SDK lance `claude` en subprocess via asyncio, qui par defaut
# affiche une fenetre console Windows. On patche TOUS les chemins :
#   - subprocess.Popen (sync)
#   - asyncio.create_subprocess_exec / create_subprocess_shell (async)
# avec CREATE_NO_WINDOW + STARTUPINFO wShowWindow=SW_HIDE.
if sys.platform == "win32":
    import asyncio
    import asyncio.subprocess as _async_subp

    _CREATE_NO_WINDOW = 0x08000000
    _SW_HIDE = 0
    _STARTF_USESHOWWINDOW = 0x00000001

    _hidden_si = subprocess.STARTUPINFO()
    _hidden_si.dwFlags |= _STARTF_USESHOWWINDOW
    _hidden_si.wShowWindow = _SW_HIDE

    def _hide_window_kwargs(kwargs):
        kwargs.setdefault("creationflags", 0)
        kwargs["creationflags"] |= _CREATE_NO_WINDOW
        if "startupinfo" not in kwargs:
            kwargs["startupinfo"] = _hidden_si
        return kwargs

    # 1) subprocess.Popen sync
    _original_popen = subprocess.Popen

    class _NoWindowPopen(_original_popen):
        def __init__(self, *args, **kwargs):
            _hide_window_kwargs(kwargs)
            super().__init__(*args, **kwargs)

    subprocess.Popen = _NoWindowPopen

    # 2) asyncio create_subprocess_exec / shell
    _orig_async_exec = asyncio.create_subprocess_exec
    _orig_async_shell = asyncio.create_subprocess_shell

    async def _patched_async_exec(*args, **kwargs):
        _hide_window_kwargs(kwargs)
        return await _orig_async_exec(*args, **kwargs)

    async def _patched_async_shell(*args, **kwargs):
        _hide_window_kwargs(kwargs)
        return await _orig_async_shell(*args, **kwargs)

    asyncio.create_subprocess_exec = _patched_async_exec
    asyncio.create_subprocess_shell = _patched_async_shell
    _async_subp.create_subprocess_exec = _patched_async_exec
    _async_subp.create_subprocess_shell = _patched_async_shell

import db
import onboarding
import pages


def _force_claude_code_auth():
    """Supprime ANTHROPIC_API_KEY de l'env pour forcer l'utilisation du login
    Claude Code (forfait Pro/Max).

    Sans cette ligne, si une variable d'env ANTHROPIC_API_KEY traine quelque
    part (Windows env vars utilisateur, scripts d'init), le SDK essaierait
    de l'utiliser et facturerait par token. On veut explicitement utiliser
    le forfait existant.
    """
    if "ANTHROPIC_API_KEY" in os.environ:
        del os.environ["ANTHROPIC_API_KEY"]


def _xelatex_banner() -> ft.Control | None:
    """Banner d'alerte si xelatex absent du PATH."""
    if shutil.which("xelatex"):
        return None
    return ft.Container(
        ft.Row([
            ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE_700),
            ft.Text(
                "xelatex non detecte - la compilation des CV en PDF echouera. "
                "Installe MikTeX (https://miktex.org) puis redemarre l'app.",
                size=12, color=ft.Colors.ORANGE_900,
            ),
        ]),
        bgcolor=ft.Colors.ORANGE_50,
        padding=8,
        border=ft.Border.only(bottom=ft.BorderSide(2, ft.Colors.ORANGE_700)),
    )


def main(page: ft.Page):
    page.title = "Recherche Emploi - Centre de controle"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.services.append(ft.Window(width=1200, height=800, min_width=900, min_height=600))

    db.init_db()
    _force_claude_code_auth()
    # Cleanup au demarrage : si l'app a ete fermee pendant une concretisation,
    # les offres concernees deviennent "a_revoir" pour que l'user puisse re-tenter
    n_dead = db.cleanup_dead_agents()
    if n_dead:
        print(f"[startup] {n_dead} concretisation(s) interrompue(s) marquee(s) a_revoir")

    # ----- Onboarding au premier lancement -----
    if not db.get_meta("onboarding_done"):
        def _on_onboarding_done():
            page.controls.clear()
            _build_main_ui(page)
            page.update()

        page.add(onboarding.show_wizard(page, _on_onboarding_done))
        return

    _build_main_ui(page)


def _build_main_ui(page: ft.Page):
    """Construit l'UI principale (rail + content) apres onboarding.

    Les 3 pages sont creees UNE SEULE FOIS au premier chargement et mises en
    cache. Switch d'onglet = swap du content_area sur la page existante.
    Cela preserve l'etat (notamment les concretisations en cours dans
    rapport_page) entre les navigations.
    """
    content_area = ft.Container(padding=20, expand=True)
    pages_cache = {}  # {index: Control}

    def _build_page(index: int):
        if index == 0:
            return pages.rapport_page(page)
        if index == 1:
            return pages.profil_page(page)
        if index == 2:
            return pages.parametres_page(page)
        return ft.Text(f"Page inconnue : {index}")

    def load_page(index: int):
        try:
            if index not in pages_cache:
                pages_cache[index] = _build_page(index)
            content_area.content = pages_cache[index]
        except Exception as ex:
            import traceback
            tb = traceback.format_exc()
            content_area.content = ft.Column([
                ft.Text(f"Erreur de chargement de la page {index}",
                        color=ft.Colors.RED_700, weight=ft.FontWeight.BOLD, size=16),
                ft.Container(
                    ft.Text(tb, size=11, selectable=True, font_family="Consolas"),
                    bgcolor=ft.Colors.RED_50, padding=12, border_radius=6,
                ),
            ], scroll=ft.ScrollMode.AUTO)
        page.update()

    def on_nav(e):
        load_page(e.control.selected_index)

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=80,
        group_alignment=-0.9,
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.DASHBOARD_OUTLINED,
                selected_icon=ft.Icons.DASHBOARD,
                label="Tableau",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.PERSON_OUTLINE,
                selected_icon=ft.Icons.PERSON,
                label="Profil",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Parametres",
            ),
        ],
        on_change=on_nav,
        bgcolor=ft.Colors.BLUE_GREY_50,
    )

    body = ft.Row(
        [rail, ft.VerticalDivider(width=1), content_area],
        expand=True,
    )

    banner = _xelatex_banner()
    if banner is not None:
        page.add(ft.Column([banner, body], expand=True, spacing=0))
    else:
        page.add(body)

    load_page(0)


if __name__ == "__main__":
    ft.run(main)
