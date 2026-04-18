"""Wizard d'onboarding au premier lancement.

3 etapes simples :
    1. Cookie LinkedIn (optionnel)
    2. Verification xelatex (auto)
    3. "Va remplir ton profil dans l'onglet Profil"

L'auth Claude utilise le login Claude Code (forfait Pro/Max), donc pas
d'etape "cle API" - rien a configurer cote utilisateur.

Quand termine -> db.set_meta("onboarding_done", "true") et bascule sur l'app.
Re-jouable depuis Parametres ("Refaire l'onboarding") via show_wizard().
"""
import shutil

import flet as ft

import db
import secrets_store


def show_wizard(page: ft.Page, on_done):
    """Affiche le wizard plein-ecran. Appelle on_done() a la fin."""
    state = {"step": 1}

    title = ft.Text("Bienvenue dans Recherche Emploi",
                    size=24, weight=ft.FontWeight.BOLD,
                    color=ft.Colors.PURPLE_700)
    subtitle = ft.Text("", size=14, color=ft.Colors.GREY_700)
    body = ft.Container(padding=20)
    nav = ft.Row(spacing=10)
    progress = ft.Text("", size=12, color=ft.Colors.GREY_600)

    container = ft.Container(
        ft.Column([
            title, subtitle, ft.Divider(),
            body, ft.Divider(),
            ft.Row([progress, ft.Container(expand=True), nav]),
        ], scroll=ft.ScrollMode.AUTO, spacing=10),
        padding=40,
        expand=True,
    )

    # ============================================================
    # Step 1 : cookie LinkedIn (optionnel)
    # ============================================================
    def render_step_1():
        subtitle.value = "Étape 1/3 - Cookie LinkedIn (optionnel)"
        li_field = ft.TextField(
            label="Cookie li_at (laisse vide pour skip LinkedIn)",
            password=True, can_reveal_password=True, width=500,
        )

        def on_save(e):
            val = li_field.value.strip()
            if val:
                secrets_store.set_secret(secrets_store.LINKEDIN_LI_AT, val)
            state["step"] += 1
            render()

        body.content = ft.Column([
            ft.Text("Le scraper LinkedIn utilise ton cookie de session pour "
                    "interroger l'API interne LinkedIn (legal pour ton propre compte).",
                    size=13),
            ft.Text("Comment recuperer le cookie :", size=12, weight=ft.FontWeight.BOLD),
            ft.Text("1. Ouvre linkedin.com et connecte-toi", size=12),
            ft.Text("2. F12 > Application > Cookies > linkedin.com", size=12),
            ft.Text("3. Copie la valeur de 'li_at' (longue chaine alphanumerique)", size=12),
            ft.Container(height=10),
            li_field,
            ft.Text("Sans ce cookie, LinkedIn sera saute - les autres sources "
                    "(APEC, WTTJ) continuent de marcher.",
                    size=11, italic=True, color=ft.Colors.GREY_700),
        ], spacing=8)

        if secrets_store.has_secret(secrets_store.LINKEDIN_LI_AT):
            li_field.value = "**********"

        next_btn.disabled = False
        next_btn.text = "Suivant (avec LinkedIn ou non)"
        next_btn.on_click = on_save

    # ============================================================
    # Step 2 : verif xelatex
    # ============================================================
    def render_step_2():
        subtitle.value = "Étape 2/3 - Vérification de l'environnement (xelatex)"
        xelatex_path = shutil.which("xelatex")
        if xelatex_path:
            content = ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700, size=32),
                    ft.Text(f"xelatex détecté : {xelatex_path}",
                            size=14, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.GREEN_700),
                ]),
                ft.Text("Tu pourras compiler les CV LaTeX en PDF directement depuis l'app.",
                        size=12),
            ])
            next_btn.disabled = False
        else:
            content = ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.WARNING, color=ft.Colors.ORANGE_700, size=32),
                    ft.Text("xelatex non détecté dans le PATH",
                            size=14, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.ORANGE_700),
                ]),
                ft.Text("L'app ne pourra pas compiler les CV LaTeX en PDF tant que "
                        "MikTeX (ou TeX Live) n'est pas installé.", size=13),
                ft.Text("Recommandé : installer MikTeX (https://miktex.org).",
                        size=12, color=ft.Colors.BLUE_700),
                ft.Text("Après installation, redémarre l'app et le test repassera vert.",
                        size=12, italic=True),
                ft.Text("Tu peux continuer sans xelatex pour le moment - "
                        "la concrétisation échouera juste à la compilation PDF.",
                        size=11, italic=True, color=ft.Colors.GREY_700),
            ])
            next_btn.disabled = False  # on autorise quand meme

        body.content = content

    # ============================================================
    # Step 3 : aller remplir le profil + rappel auth Claude Code
    # ============================================================
    def render_step_3():
        subtitle.value = "Étape 3/3 - Profil et Claude Code"
        body.content = ft.Column([
            ft.Text("Pour générer tes CV personnalisés, l'app a besoin de "
                    "connaître ton parcours.", size=14),
            ft.Container(height=10),
            ft.Text("Après ce wizard, va dans l'onglet 'Profil' (icône à gauche) "
                    "et remplis :", size=13),
            ft.Text("- Identité (nom, email, localisation)", size=12),
            ft.Text("- Formation", size=12),
            ft.Text("- Au moins 1 expérience professionnelle", size=12),
            ft.Text("- Tes cibles d'emploi", size=12),
            ft.Container(height=10),
            ft.Text("L'app est pré-remplie avec un exemple (Clément Bouillier). "
                    "Tu peux supprimer ses champs et saisir les tiens.",
                    size=12, italic=True, color=ft.Colors.GREY_700),
            ft.Divider(),
            ft.Text("Authentification Claude :", size=13, weight=ft.FontWeight.BOLD,
                    color=ft.Colors.PURPLE_700),
            ft.Text("L'app utilise ton login Claude Code (forfait Pro/Max) - "
                    "aucun coût additionnel. Vérifie que tu es loggé en tapant "
                    "`claude` dans un terminal (s'ouvre normalement = OK).",
                    size=12, color=ft.Colors.GREY_800),
        ], spacing=8)
        next_btn.disabled = False
        next_btn.text = "Terminer l'onboarding"

    # ============================================================
    # Navigation
    # ============================================================
    next_btn = ft.ElevatedButton(
        "Suivant",
        icon=ft.Icons.ARROW_FORWARD,
        style=ft.ButtonStyle(bgcolor=ft.Colors.PURPLE_700, color=ft.Colors.WHITE),
    )
    back_btn = ft.OutlinedButton("Retour", icon=ft.Icons.ARROW_BACK)

    def on_back(e):
        if state["step"] > 1:
            state["step"] -= 1
            render()

    def on_next(e):
        if state["step"] < 3:
            state["step"] += 1
            render()
        else:
            # Fin de l'onboarding
            db.set_meta("onboarding_done", "true")
            on_done()

    back_btn.on_click = on_back
    next_btn.on_click = on_next

    def render():
        progress.value = f"Étape {state['step']}/3"
        back_btn.disabled = (state["step"] == 1)
        next_btn.on_click = on_next
        next_btn.text = "Suivant"

        if state["step"] == 1:
            render_step_1()
        elif state["step"] == 2:
            render_step_2()
        elif state["step"] == 3:
            render_step_3()
        nav.controls = [back_btn, next_btn]
        page.update()

    render()
    return container
