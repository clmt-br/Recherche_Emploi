"""Les 3 pages de l'app : Tableau de bord, Profil, Parametres.

Chaque fonction `*_page(page)` renvoie un Control Flet a placer dans le
container principal. La navigation est gouvernee depuis app.py.
"""
import asyncio
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import flet as ft

import calendar_ics
import concretize
import config
import db
import scan
import secrets_store
from agent_runner import DEFAULT_MODEL
from flet_async_bridge import ProgressChannel, ProgressEvent, run_in_flet
import orchestrator

STATUT_LABELS = {
    "rapport": "Rapport du jour",
    "en_cours": "Candidatures en cours",
    "envoyee": "Candidatures envoyées",
    "a_revoir": "À revoir (échec)",
}


# ---------- Page 1 : Tableau de bord ----------

def rapport_page(page: ft.Page) -> ft.Control:
    status_text = ft.Text("", color=ft.Colors.GREEN_700, size=13)
    progress = ft.ProgressBar(visible=False, width=400)
    current_statut = {"value": "rapport"}
    table_container = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)

    # Panneau de concretisation batch (CV+LM via Claude SDK)
    concretize_container, start_batch = _concretize_panel(page, lambda: refresh())

    def build_rows(offres):
        rows = []
        for o in offres:
            def make_opener(offre_id):
                return lambda e: _show_detail_dialog(page, offre_id, refresh)

            action_row = _action_buttons(page, o, refresh, status_text, start_batch)

            score_str = str(o.score) if o.score > 0 else "—"
            score_color = _score_color(o.score) if o.score > 0 else ft.Colors.GREY_400
            rows.append(ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(o.entreprise, weight=ft.FontWeight.W_500),
                                on_tap=make_opener(o.id)),
                    ft.DataCell(ft.Text(o.intitule), on_tap=make_opener(o.id)),
                    ft.DataCell(ft.Text(o.source, size=12, color=ft.Colors.GREY_700)),
                    ft.DataCell(ft.Text(score_str, weight=ft.FontWeight.BOLD,
                                        color=score_color)),
                    ft.DataCell(ft.Text(o.listed_date or o.date_scrape, size=12)),
                    ft.DataCell(action_row),
                ],
            ))
        return rows

    def refresh():
        offres = db.list_offres(current_statut["value"])
        if not offres:
            table_container.controls = [ft.Container(
                ft.Text("Aucune offre dans cette categorie.",
                       italic=True, color=ft.Colors.GREY_600),
                padding=20,
            )]
        else:
            table_container.controls = [ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Entreprise", weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Intitule", weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Source", weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Score", weight=ft.FontWeight.BOLD), numeric=True),
                    ft.DataColumn(ft.Text("Date", weight=ft.FontWeight.BOLD)),
                    ft.DataColumn(ft.Text("Action", weight=ft.FontWeight.BOLD)),
                ],
                rows=build_rows(offres),
                heading_row_color=ft.Colors.BLUE_GREY_50,
                column_spacing=25,
            )]
        page.update()

    def on_filter_change(e):
        if e.control.selected:
            current_statut["value"] = e.control.selected[0]
            refresh()

    def on_scan_click(e):
        scan_btn.disabled = True
        progress.visible = True
        progress.value = None
        status_text.value = "Lancement du scan (peut prendre plusieurs minutes)..."
        page.update()

        def progress_cb(msg: str):
            status_text.value = msg
            try:
                page.update()
            except Exception:
                pass

        def done_cb(nb: int, erreurs: list):
            progress.visible = False
            scan_btn.disabled = False
            if erreurs:
                status_text.value = f"Scan termine : {nb} nouvelles, erreurs sur : {', '.join(erreurs)}"
                status_text.color = ft.Colors.ORANGE_700
            else:
                status_text.value = f"Scan termine : {nb} nouvelles offres importees"
                status_text.color = ft.Colors.GREEN_700
            current_statut["value"] = "rapport"
            filter_bar.selected = ["rapport"]
            refresh()

        scan.run_full_scan(progress_cb, done_cb)

    filter_bar = ft.SegmentedButton(
        selected=["rapport"],
        allow_empty_selection=False,
        allow_multiple_selection=False,
        on_change=on_filter_change,
        segments=[
            ft.Segment(value=key, label=ft.Text(label))
            for key, label in STATUT_LABELS.items()
        ],
    )

    scan_btn = ft.ElevatedButton(
        "Lancer le scan",
        icon=ft.Icons.SEARCH,
        on_click=on_scan_click,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE),
    )

    refresh()

    return ft.Column([
        ft.Row([
            ft.Text("Tableau de bord candidatures",
                   size=22, weight=ft.FontWeight.BOLD),
            ft.Container(expand=True),
            scan_btn,
        ]),
        status_text,
        progress,
        ft.Row([filter_bar], scroll=ft.ScrollMode.AUTO),
        concretize_container,
        ft.Divider(),
        table_container,
    ], expand=True)


def _action_buttons(page, offre, refresh_cb, status_text, start_batch=None) -> ft.Row:
    def mover(new_statut):
        def handler(e):
            db.update_statut(offre.id, new_statut)
            status_text.value = f"Offre #{offre.id} -> {STATUT_LABELS[new_statut]}"
            refresh_cb()
        return handler

    def link_opener(url):
        return lambda e: page.launch_url(url)

    def on_concretize_one(e):
        if start_batch is not None:
            start_batch([offre.id])
        else:
            status_text.value = "Erreur : panneau de concretisation indisponible"
            status_text.color = ft.Colors.RED_700

    btns = [ft.IconButton(
        ft.Icons.INFO_OUTLINE, tooltip="Voir les détails",
        on_click=lambda e: _show_detail_dialog(page, offre.id, refresh_cb),
    )]
    has_cv_lm = bool(offre.cv_path) and bool(offre.lm_path)

    if offre.statut == "rapport":
        btns.append(ft.IconButton(
            ft.Icons.AUTO_AWESOME, tooltip="Concrétiser (CV+LM via Claude)",
            icon_color=ft.Colors.PURPLE_700,
            on_click=on_concretize_one,
        ))
    elif offre.statut == "en_cours":
        if has_cv_lm:
            # Concretisation faite par l'app -> envoi possible
            btns.append(ft.IconButton(
                ft.Icons.FOLDER_OPEN, tooltip="Ouvrir le dossier",
                icon_color=ft.Colors.BLUE_700,
                on_click=lambda e, p=offre.dossier_pc: subprocess.Popen(["explorer", p]) if p else None,
            ))
            btns.append(ft.IconButton(
                ft.Icons.SEND, tooltip="Marquer envoyée",
                on_click=lambda e: _show_send_dialog(page, offre.id, refresh_cb),
            ))
        else:
            # En_cours sans CV/LM = legacy (importe Notion ou interrompu)
            # -> on force a concretiser avant d'envoyer
            btns.append(ft.IconButton(
                ft.Icons.AUTO_AWESOME, tooltip="Concrétiser d'abord (CV/LM non générés)",
                icon_color=ft.Colors.PURPLE_700,
                on_click=on_concretize_one,
            ))
    elif offre.statut == "a_revoir":
        btns.append(ft.IconButton(
            ft.Icons.REFRESH, tooltip="Re-tenter la concrétisation",
            icon_color=ft.Colors.AMBER_700,
            on_click=on_concretize_one,
        ))
        if offre.dossier_pc:
            btns.append(ft.IconButton(
                ft.Icons.FOLDER_OPEN, tooltip="Ouvrir le dossier",
                icon_color=ft.Colors.GREY_700,
                on_click=lambda e, p=offre.dossier_pc: subprocess.Popen(["explorer", p]),
            ))
    btns.append(ft.IconButton(
        ft.Icons.OPEN_IN_NEW, tooltip="Ouvrir l'annonce",
        on_click=link_opener(offre.url),
    ))
    return ft.Row(btns, spacing=2)


def _score_color(score: int) -> str:
    if score >= 85:
        return ft.Colors.GREEN_700
    if score >= 70:
        return ft.Colors.ORANGE_700
    return ft.Colors.RED_700


# ---------- Panneau de concretisation (batch parallele Claude SDK) ----------

_KIND_COLORS = {
    "queued": ft.Colors.GREY_500,
    "start": ft.Colors.BLUE_500,
    "tool_use": ft.Colors.PURPLE_400,
    "text": ft.Colors.BLUE_GREY_400,
    "validate": ft.Colors.ORANGE_500,
    "retry": ft.Colors.AMBER_700,
    "done": ft.Colors.GREEN_700,
    "error": ft.Colors.RED_700,
}


def _concretize_panel(page, refresh_cb):
    """Panneau qui pilote la concretisation batch (CV+LM via Claude Agent SDK).

    Retourne :
        - container : le Control a inclure dans la page
        - start_batch(ids: list[int]) : fonction a appeler pour lancer un batch
    """
    title = ft.Text("Concrétisations en cours", size=14, weight=ft.FontWeight.BOLD)
    summary = ft.Text("", size=12, color=ft.Colors.GREY_700)

    live_column = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=300)
    cards = {}  # {offre_id: dict de widgets}
    active_count = {"value": 0}  # nb d'agents actifs en parallele

    container = ft.Container(
        ft.Column([
            ft.Row([title, ft.Container(expand=True), summary]),
            ft.Divider(height=4),
            live_column,
        ], spacing=4),
        padding=10,
        bgcolor=ft.Colors.BLUE_GREY_50,
        border_radius=8,
        visible=False,  # cache tant qu'aucune concretisation lancee
    )

    def _open_folder(folder_path: str):
        try:
            subprocess.Popen(["explorer", folder_path])
        except Exception as ex:
            print(f"Ouverture dossier KO : {ex}")

    def _make_card(offre_id, label):
        ring = ft.ProgressRing(width=18, height=18, stroke_width=2, value=None)
        kind_text = ft.Text("queued", size=10, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD)
        kind_chip = ft.Container(
            kind_text, bgcolor=ft.Colors.GREY_500,
            padding=ft.Padding(left=6, right=6, top=2, bottom=2),
            border_radius=4,
        )
        title_t = ft.Text(label, size=12, weight=ft.FontWeight.W_500)
        msg_t = ft.Text("...", size=11, color=ft.Colors.GREY_700,
                        no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS)
        folder_btn = ft.IconButton(
            ft.Icons.FOLDER_OPEN, tooltip="Ouvrir le dossier de la candidature",
            icon_color=ft.Colors.BLUE_700, icon_size=18,
            visible=False,  # apparait quand le folder est connu
        )
        card = ft.Container(
            ft.Row([
                ring,
                ft.Container(kind_chip, width=70),
                title_t,
                ft.Container(msg_t, expand=True),
                folder_btn,
            ], spacing=8),
            padding=ft.Padding(left=8, right=8, top=4, bottom=4),
            border=ft.Border.all(1, ft.Colors.BLUE_GREY_100),
            border_radius=6,
            bgcolor=ft.Colors.WHITE,
        )
        cards[offre_id] = {
            "card": card, "ring": ring,
            "kind_chip": kind_chip, "kind_text": kind_text,
            "msg": msg_t,
            "folder_btn": folder_btn,
            "folder_path": None,
        }
        return card

    def _update_card(ev):
        c = cards.get(ev.offre_id)
        if not c:
            return
        # Configurer le bouton dossier des qu'on a le chemin
        if isinstance(ev.payload, dict) and ev.payload.get("folder"):
            folder_path = ev.payload["folder"]
            c["folder_path"] = folder_path
            c["folder_btn"].on_click = lambda e, f=folder_path: _open_folder(f)
            c["folder_btn"].visible = True

        c["msg"].value = (ev.message or "")[:120]
        c["kind_text"].value = ev.kind
        c["kind_chip"].bgcolor = _KIND_COLORS.get(ev.kind, ft.Colors.GREY_500)
        if ev.kind == "done":
            c["ring"].value = 1.0
            c["ring"].color = ft.Colors.GREEN_700
        elif ev.kind == "error":
            c["ring"].value = 1.0
            c["ring"].color = ft.Colors.RED_700
        elif ev.kind in ("queued",):
            c["ring"].value = 0.0
        else:
            c["ring"].value = None  # indeterminate
        try:
            page.update()
        except Exception:
            pass

    def _refresh_summary():
        if active_count["value"] > 0:
            summary.value = f"{active_count['value']} en cours..."
        else:
            n_done = sum(1 for c in cards.values()
                         if c["kind_text"].value == "done")
            n_err = sum(1 for c in cards.values()
                        if c["kind_text"].value == "error")
            summary.value = f"Terminé : {n_done} OK / {n_err} KO"

    def start_batch(offre_ids: list[int]):
        if not offre_ids:
            return
        # ACCUMULER les cards (pas de reset) pour permettre de lancer
        # plusieurs concretisations en parallele depuis le tableau
        for oid in offre_ids:
            if oid in cards:
                continue  # deja en cours, ne pas dupliquer
            o = db.get_offre(oid)
            label = f"#{oid} {o.entreprise} - {o.intitule[:40]}" if o else f"#{oid} (introuvable)"
            live_column.controls.append(_make_card(oid, label))

        container.visible = True
        active_count["value"] += len(offre_ids)
        _refresh_summary()
        page.update()

        channel = ProgressChannel()

        async def workflow():
            runner = asyncio.create_task(
                orchestrator.run_batch(
                    offre_ids,
                    channel=channel,
                    close_channel_on_done=True,
                )
            )
            async for ev in channel.consume():
                _update_card(ev)
            await runner
            active_count["value"] -= len(offre_ids)
            _refresh_summary()
            try:
                refresh_cb()
                page.update()
            except Exception:
                pass

        run_in_flet(page, workflow)

    return container, start_batch


# ---------- Dialogs ----------

def _show_detail_dialog(page, offre_id: int, refresh_cb):
    o = db.get_offre(offre_id)
    if not o:
        return

    chips = ft.Row(wrap=True, spacing=5, run_spacing=5)
    for s in o.matched_skills:
        chips.controls.append(ft.Container(
            ft.Text(s, size=11, color=ft.Colors.BLUE_900),
            bgcolor=ft.Colors.BLUE_50, padding=ft.Padding(8, 2, 8, 2),
            border_radius=12,
        ))
    for r in o.reasons:
        chips.controls.append(ft.Container(
            ft.Text(r, size=11, color=ft.Colors.GREEN_900),
            bgcolor=ft.Colors.GREEN_50, padding=ft.Padding(8, 2, 8, 2),
            border_radius=12,
        ))

    content = ft.Column([
        ft.Row([
            ft.Text(o.entreprise, size=18, weight=ft.FontWeight.BOLD),
            ft.Container(expand=True),
            ft.Container(
                ft.Text(f"Score {o.score}", color=ft.Colors.WHITE,
                       weight=ft.FontWeight.BOLD, size=12),
                bgcolor=_score_color(o.score),
                padding=ft.Padding(10, 4, 10, 4),
                border_radius=10,
            ),
        ]),
        ft.Text(o.intitule, size=14, italic=True),
        ft.Row([
            ft.Text(f"Source : {o.source}", size=12, color=ft.Colors.GREY_700),
            ft.Text(f"Lieu : {o.location}", size=12, color=ft.Colors.GREY_700),
            ft.Text(f"Contrat : {o.contract}", size=12, color=ft.Colors.GREY_700),
        ], spacing=15, wrap=True),
        ft.Row([
            ft.Text(f"Publié : {o.listed_date}", size=12, color=ft.Colors.GREY_700),
            ft.Text(f"Exp. min : {o.experience_min} ans", size=12, color=ft.Colors.GREY_700),
        ], spacing=15),
        chips,
        ft.Divider(),
        ft.Text("Description", weight=ft.FontWeight.BOLD, size=13),
        ft.Container(
            ft.Text(o.description or "(pas de description)", selectable=True, size=12),
            bgcolor=ft.Colors.GREY_50, padding=12, border_radius=6,
        ),
    ], scroll=ft.ScrollMode.AUTO, spacing=8, width=800, height=500,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Détails de l'offre"),
        content=content,
        actions=[
            ft.TextButton("Ouvrir l'annonce",
                         on_click=lambda e: page.launch_url(o.url)),
            ft.TextButton("Fermer", on_click=lambda e: page.pop_dialog()),
        ],
    )
    page.show_dialog(dlg)


def _show_send_dialog(page, offre_id: int, refresh_cb):
    o = db.get_offre(offre_id)
    if not o:
        return

    from datetime import timedelta
    status_line = ft.Text("", size=12, color=ft.Colors.GREEN_700)
    today = datetime.now()
    relance_date = today + timedelta(days=15)

    def on_confirm(e):
        date_envoi = today.strftime("%Y-%m-%d")
        date_relance = relance_date.strftime("%Y-%m-%d")
        db.mark_envoyee(offre_id, date_envoi, date_relance)

        # Générer le .ics dans le dossier candidature si présent, sinon à la racine prototype
        folder = Path(o.dossier_pc) if o.dossier_pc and Path(o.dossier_pc).exists() \
                 else Path(__file__).parent
        ics_path = calendar_ics.save_ics(o, folder, today)
        status_line.value = f"Envoi enregistré. Relance .ics : {ics_path.name}"
        page.update()
        # Ferme la boite apres 1 seconde et refresh
        def close_and_refresh():
            import time
            time.sleep(1)
            try:
                page.pop_dialog()
                refresh_cb()
            except Exception:
                pass
        threading.Thread(target=close_and_refresh, daemon=True).start()

    content = ft.Column([
        ft.Text(f"Entreprise : {o.entreprise}", size=13),
        ft.Text(f"Poste : {o.intitule}", size=13),
        ft.Divider(),
        ft.Text(f"Date d'envoi : {today:%d/%m/%Y}", size=13, weight=ft.FontWeight.BOLD),
        ft.Text(f"Relance prévue : {relance_date:%d/%m/%Y} à 14h (J+15)",
                size=13, color=ft.Colors.BLUE_700),
        ft.Text("Un fichier .ics sera généré pour import dans Google Calendar.",
                size=11, italic=True, color=ft.Colors.GREY_700),
        status_line,
    ], spacing=10, width=500)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Confirmer l'envoi"),
        content=content,
        actions=[
            ft.TextButton("Annuler", on_click=lambda e: page.pop_dialog()),
            ft.ElevatedButton(
                "Confirmer envoi", icon=ft.Icons.SEND,
                on_click=on_confirm,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE),
            ),
        ],
    )
    page.show_dialog(dlg)


# ---------- Page 2 : Profil (sous-onglets riches) ----------

PROFIL_SECTIONS = {
    "identite": "Identité",
    "formation": "Formation",
    "experiences": "Expériences",
    "interets": "Intérêts",
    "ambitions": "Profil & ambitions",
    "cibles": "Cibles & exclusions",
    "cadres": "Cadres positionnement",
    "regles": "Règles rédaction",
}


def profil_page(page: ft.Page) -> ft.Control:
    profile = config.load_profile()
    for k, v in config.DEFAULT_PROFILE.items():
        profile.setdefault(k, v if not isinstance(v, (dict, list)) else (v.copy() if isinstance(v, dict) else list(v)))

    status = ft.Text("", color=ft.Colors.GREEN_700, size=12)
    current_section = {"name": "identite"}

    # nav_row et section_scroll sont rebuild a chaque switch d'onglet
    # (mais leurs references restent stables, donc le tree reste valide)
    nav_row = ft.Row(wrap=True, spacing=6)
    section_scroll = ft.Column(
        spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    def rebuild():
        nav_row.controls = [
            _tab_button(k, lbl, current_section["name"] == k, switch)
            for k, lbl in PROFIL_SECTIONS.items()
        ]
        section_ctrl = _build_profil_section(
            page, current_section["name"], profile, rebuild_section=rebuild
        )
        section_scroll.controls = [section_ctrl]
        try:
            nav_row.update()
            section_scroll.update()
        except Exception:
            pass  # 1er build : pas encore dans le tree

    def switch(name: str):
        current_section["name"] = name
        rebuild()

    def on_save(e):
        config.save_profile(profile)
        status.value = f"Profil enregistre dans {config.PROFILE_PATH.name}"
        status.color = ft.Colors.GREEN_700
        try:
            page.update()
        except Exception:
            pass

    rebuild()  # build initial des controls de nav_row et section_scroll

    return ft.Column([
        ft.Row([
            ft.Text("Profil candidat", size=22, weight=ft.FontWeight.BOLD),
            ft.Container(expand=True),
            ft.ElevatedButton(
                "Enregistrer tout", icon=ft.Icons.SAVE, on_click=on_save,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE),
            ),
            status,
        ]),
        ft.Text(
            "Ces informations alimentent les prompts Claude SDK et les templates CV/LM. "
            "Pour un autre utilisateur : effacer profile.yaml et remplir ce formulaire.",
            size=11, color=ft.Colors.GREY_700,
        ),
        ft.Divider(),
        nav_row,
        ft.Divider(),
        section_scroll,
    ], expand=True, spacing=8)


def _tab_button(key: str, label: str, active: bool, on_click_cb) -> ft.Control:
    """Bouton-onglet base sur ElevatedButton/TextButton standard."""
    if active:
        return ft.ElevatedButton(
            label,
            on_click=lambda e: on_click_cb(key),
            style=ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE_600,
                color=ft.Colors.WHITE,
            ),
        )
    return ft.TextButton(
        label,
        on_click=lambda e: on_click_cb(key),
    )


def _build_profil_section(page, name: str, profile: dict, rebuild_section) -> ft.Control:
    """Renvoie le Control de la section selectionnee."""
    if name == "identite":
        return _section_simple_dict(profile, "identite", [
            ("nom", "Nom complet"),
            ("email", "Email"),
            ("telephone", "Téléphone"),
            ("localisation", "Localisation"),
            ("mobilite", "Mobilité géographique"),
            ("disponibilite", "Disponibilité"),
        ])
    if name == "formation":
        return _section_simple_dict(profile, "formation", [
            ("ecole", "École"),
            ("cursus", "Cursus / spécialité"),
            ("prepa", "Prépa"),
            ("international", "Expérience internationale (cursus)"),
            ("specialite", "Spécialité"),
            ("contenu_cursus", "Contenu du cursus", True),
        ])
    if name == "experiences":
        return _section_list_cards(
            page, profile, "experiences",
            empty_factory=config.empty_experience,
            card_renderer=_experience_card,
            edit_dialog=_show_experience_dialog,
            rebuild_section=rebuild_section,
        )
    if name == "interets":
        return _section_list_cards(
            page, profile, "interets_complementaires",
            empty_factory=config.empty_interet,
            card_renderer=_interet_card,
            edit_dialog=_show_interet_dialog,
            rebuild_section=rebuild_section,
        )
    if name == "ambitions":
        return _section_ambitions(profile)
    if name == "cibles":
        return _section_cibles(profile)
    if name == "cadres":
        return _section_list_cards(
            page, profile, "cadres_positionnement",
            empty_factory=config.empty_cadre,
            card_renderer=_cadre_card,
            edit_dialog=_show_cadre_dialog,
            rebuild_section=rebuild_section,
        )
    if name == "regles":
        return _section_regles(profile)
    return ft.Text(f"Section inconnue : {name}")


# ---------- Sections simples (dict de champs) ----------

def _section_simple_dict(profile, root_key: str, fields_def: list) -> ft.Control:
    """Genere un formulaire 2-colonnes pour un dict simple key->str."""
    section = profile.setdefault(root_key, {})

    controls = []
    pair_buffer = []

    def make_handler(key):
        def h(e):
            section[key] = e.control.value
        return h

    for entry in fields_def:
        key, label = entry[0], entry[1]
        multiline = len(entry) > 2 and entry[2]
        tf = ft.TextField(
            label=label,
            value=str(section.get(key, "") or ""),
            multiline=multiline,
            min_lines=1,
            max_lines=4 if multiline else 1,
            on_change=make_handler(key),
            expand=True,
        )
        if multiline:
            # multiline prend toute la largeur
            if pair_buffer:
                controls.append(ft.Row(pair_buffer, spacing=15))
                pair_buffer = []
            controls.append(tf)
        else:
            pair_buffer.append(tf)
            if len(pair_buffer) == 2:
                controls.append(ft.Row(pair_buffer, spacing=15))
                pair_buffer = []
    if pair_buffer:
        controls.append(ft.Row(pair_buffer, spacing=15))

    return ft.Column(controls, spacing=10,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# ---------- Section "Profil & ambitions" ----------

def _section_ambitions(profile) -> ft.Control:
    section = profile.setdefault("profil_ambitions", {})

    def on_change_str(key):
        return lambda e: section.__setitem__(key, e.control.value)

    def on_change_list(key):
        return lambda e: section.__setitem__(
            key, [s.strip() for s in e.control.value.split("\n") if s.strip()]
        )

    return ft.Column([
        ft.Row([
            ft.TextField(
                label="Cible prioritaire (taille entreprise)",
                value=section.get("cible_prioritaire_taille", ""),
                on_change=on_change_str("cible_prioritaire_taille"),
                expand=True,
            ),
            ft.TextField(
                label="ESN / presta",
                value=section.get("esn_presta", ""),
                on_change=on_change_str("esn_presta"),
                expand=True,
            ),
        ], spacing=15),
        ft.TextField(
            label="Raison de cette cible",
            value=section.get("raison_cible", ""),
            multiline=True, min_lines=1, max_lines=4,
            on_change=on_change_str("raison_cible"),
        ),
        ft.TextField(
            label="Ouverture postes (un par ligne)",
            value="\n".join(section.get("ouverture_postes", []) or []),
            multiline=True, min_lines=2, max_lines=8,
            on_change=on_change_list("ouverture_postes"),
        ),
        ft.TextField(
            label="Contexte de départ précédent",
            value=section.get("contexte_depart", ""),
            multiline=True, min_lines=1, max_lines=4,
            on_change=on_change_str("contexte_depart"),
        ),
    ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# ---------- Section "Cibles & exclusions" ----------

def _section_cibles(profile) -> ft.Control:
    section = profile.setdefault("cibles", {})

    def on_change_str(key):
        return lambda e: section.__setitem__(key, e.control.value)

    def on_change_list(key):
        return lambda e: section.__setitem__(
            key, [s.strip() for s in e.control.value.split("\n") if s.strip()]
        )

    return ft.Column([
        ft.TextField(
            label="Postes à conserver dans le rapport (un par ligne)",
            value="\n".join(section.get("postes_a_conserver", []) or []),
            multiline=True, min_lines=2, max_lines=10,
            on_change=on_change_list("postes_a_conserver"),
        ),
        ft.TextField(
            label="Exclusions strictes (un par ligne)",
            value="\n".join(section.get("exclusions_strictes", []) or []),
            multiline=True, min_lines=2, max_lines=8,
            on_change=on_change_list("exclusions_strictes"),
        ),
        ft.TextField(
            label="Exception sur intitulés commerciaux (règle à respecter)",
            value=section.get("exception_intitule_commercial", ""),
            multiline=True, min_lines=1, max_lines=5,
            on_change=on_change_str("exception_intitule_commercial"),
        ),
        ft.Row([
            ft.TextField(
                label="Zone prioritaire",
                value=section.get("zone_prioritaire", ""),
                on_change=on_change_str("zone_prioritaire"),
                expand=True,
            ),
            ft.TextField(
                label="Zone acceptable",
                value=section.get("zone_acceptable", ""),
                on_change=on_change_str("zone_acceptable"),
                expand=True,
            ),
        ], spacing=15),
    ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# ---------- Section "Regles redaction" ----------

def _section_regles(profile) -> ft.Control:
    section = profile.setdefault("regles_redaction", {})

    def on_change_list(key):
        return lambda e: section.__setitem__(
            key, [s.strip() for s in e.control.value.split("\n") if s.strip()]
        )

    def on_change_bool(key):
        return lambda e: section.__setitem__(key, e.control.value)

    return ft.Column([
        ft.TextField(
            label="À NE JAMAIS dire dans CV/LM (un par ligne)",
            value="\n".join(section.get("ne_jamais_dire", []) or []),
            multiline=True, min_lines=2, max_lines=8,
            on_change=on_change_list("ne_jamais_dire"),
            helper="Phrases ou mots formellement interdits dans la génération",
        ),
        ft.TextField(
            label="Vocabulaire spécifique / nuances importantes (un par ligne)",
            value="\n".join(section.get("vocabulaire_specifique", []) or []),
            multiline=True, min_lines=2, max_lines=8,
            on_change=on_change_list("vocabulaire_specifique"),
        ),
        ft.Row([
            ft.Switch(
                label="Tirets longs interdits (— et –)",
                value=section.get("tirets_long_interdits", True),
                on_change=on_change_bool("tirets_long_interdits"),
            ),
            ft.Switch(
                label="Accents typographiques obligatoires",
                value=section.get("accents_obligatoires", True),
                on_change=on_change_bool("accents_obligatoires"),
            ),
        ], spacing=20, wrap=True),
    ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# ---------- Section liste de cartes (generique) ----------

def _section_list_cards(page, profile, key: str, empty_factory,
                        card_renderer, edit_dialog, rebuild_section) -> ft.Control:
    items = profile.setdefault(key, [])

    cards = []
    for idx, item in enumerate(items):
        cards.append(card_renderer(
            item,
            on_edit=lambda e, i=idx: edit_dialog(page, items, i, rebuild_section),
            on_delete=lambda e, i=idx: _confirm_delete(page, items, i, rebuild_section),
        ))

    def on_add(e):
        items.append(empty_factory())
        edit_dialog(page, items, len(items) - 1, rebuild_section)

    cards.append(ft.OutlinedButton(
        "Ajouter", icon=ft.Icons.ADD, on_click=on_add,
    ))

    return ft.Column(cards, spacing=10,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def _confirm_delete(page, items, idx, rebuild_section):
    item = items[idx]
    label = item.get("entreprise") or item.get("nom") or item.get("titre") or f"item #{idx}"

    def do_delete(e):
        items.pop(idx)
        page.pop_dialog()
        rebuild_section()

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Supprimer ?"),
        content=ft.Text(f"Confirmer la suppression de : {label}"),
        actions=[
            ft.TextButton("Annuler", on_click=lambda e: page.pop_dialog()),
            ft.ElevatedButton(
                "Supprimer", icon=ft.Icons.DELETE,
                on_click=do_delete,
                style=ft.ButtonStyle(bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE),
            ),
        ],
    )
    page.show_dialog(dlg)


# ---------- Cards renderers ----------

NIVEAU_COLORS = {
    "maximiser": ft.Colors.GREEN_600,
    "mentionner": ft.Colors.BLUE_600,
    "minimiser": ft.Colors.GREY_600,
}


def _experience_card(exp, on_edit, on_delete) -> ft.Control:
    niveau = exp.get("niveau_mise_en_avant", "mentionner")
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(exp.get("entreprise", "(sans nom)"),
                       size=15, weight=ft.FontWeight.BOLD),
                ft.Container(
                    ft.Text(niveau, size=10, color=ft.Colors.WHITE,
                           weight=ft.FontWeight.BOLD),
                    bgcolor=NIVEAU_COLORS.get(niveau, ft.Colors.GREY_600),
                    padding=ft.Padding(8, 2, 8, 2), border_radius=10,
                ),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.EDIT, tooltip="Modifier", on_click=on_edit),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Supprimer",
                             on_click=on_delete, icon_color=ft.Colors.RED_600),
            ]),
            ft.Row([
                ft.Text(exp.get("lieu", ""), size=11, color=ft.Colors.GREY_700),
                ft.Text(exp.get("periode", ""), size=11, color=ft.Colors.GREY_700),
                ft.Text(exp.get("type_contrat", ""), size=11, color=ft.Colors.GREY_700),
            ], spacing=15, wrap=True),
            ft.Text(exp.get("mission", ""), size=12,
                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=4),
        bgcolor=ft.Colors.GREY_50, padding=12, border_radius=8,
        border=ft.Border.all(1, ft.Colors.GREY_300),
    )


def _interet_card(it, on_edit, on_delete) -> ft.Control:
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(it.get("titre", "(sans titre)"),
                       size=14, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.EDIT, tooltip="Modifier", on_click=on_edit),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Supprimer",
                             on_click=on_delete, icon_color=ft.Colors.RED_600),
            ]),
            ft.Text(it.get("description", ""), size=12,
                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"Pertinent si : {it.get('pertinent_si', '')}",
                   size=11, italic=True, color=ft.Colors.GREY_700),
        ], spacing=4),
        bgcolor=ft.Colors.GREY_50, padding=12, border_radius=8,
        border=ft.Border.all(1, ft.Colors.GREY_300),
    )


def _cadre_card(c, on_edit, on_delete) -> ft.Control:
    declencheurs = ", ".join(c.get("declencheurs", []) or [])
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(c.get("nom", "(sans nom)"),
                       size=14, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.EDIT, tooltip="Modifier", on_click=on_edit),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Supprimer",
                             on_click=on_delete, icon_color=ft.Colors.RED_600),
            ]),
            ft.Text(f"Déclencheurs : {declencheurs[:100]}",
                   size=11, color=ft.Colors.GREY_700),
            ft.Text(c.get("motivation", ""), size=12,
                   max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(f"{len(c.get('regles_strictes', []))} règles strictes définies",
                   size=11, italic=True, color=ft.Colors.ORANGE_700),
        ], spacing=4),
        bgcolor=ft.Colors.GREY_50, padding=12, border_radius=8,
        border=ft.Border.all(1, ft.Colors.GREY_300),
    )


# ---------- Edit dialogs ----------

def _show_experience_dialog(page, items: list, idx: int, rebuild_section):
    exp = items[idx]
    f = {
        "entreprise": ft.TextField(label="Entreprise", value=exp.get("entreprise", ""), expand=True),
        "lieu": ft.TextField(label="Lieu", value=exp.get("lieu", ""), expand=True),
        "periode": ft.TextField(label="Période", value=exp.get("periode", ""), expand=True),
        "type_contrat": ft.TextField(label="Type de contrat", value=exp.get("type_contrat", ""), expand=True),
        "niveau": ft.Dropdown(
            label="Niveau de mise en avant",
            value=exp.get("niveau_mise_en_avant", "mentionner"),
            options=[
                ft.DropdownOption("maximiser"),
                ft.DropdownOption("mentionner"),
                ft.DropdownOption("minimiser"),
            ],
        ),
        "mission": ft.TextField(label="Mission principale", value=exp.get("mission", ""),
                                multiline=True, min_lines=2, max_lines=6),
        "methodologie": ft.TextField(label="Méthodologie", value=exp.get("methodologie", ""),
                                     multiline=True, min_lines=1, max_lines=5),
        "competences": ft.TextField(label="Compétences (une par ligne)",
                                    value="\n".join(exp.get("competences", []) or []),
                                    multiline=True, min_lines=2, max_lines=8),
        "referentiels": ft.TextField(label="Référentiels / normes (un par ligne)",
                                     value="\n".join(exp.get("referentiels", []) or []),
                                     multiline=True, min_lines=1, max_lines=5),
        "contexte": ft.TextField(label="Contexte / équipe", value=exp.get("contexte", ""),
                                 multiline=True, min_lines=1, max_lines=4),
        "notes": ft.TextField(label="Notes / règles spéciales (à respecter en CV/LM)",
                              value=exp.get("notes", ""),
                              multiline=True, min_lines=2, max_lines=6,
                              helper="Ex : RCC-M est un code, jamais 'coordination journalière'..."),
    }

    def on_save(e):
        exp.update({
            "entreprise": f["entreprise"].value,
            "lieu": f["lieu"].value,
            "periode": f["periode"].value,
            "type_contrat": f["type_contrat"].value,
            "niveau_mise_en_avant": f["niveau"].value,
            "mission": f["mission"].value,
            "methodologie": f["methodologie"].value,
            "competences": [s.strip() for s in f["competences"].value.split("\n") if s.strip()],
            "referentiels": [s.strip() for s in f["referentiels"].value.split("\n") if s.strip()],
            "contexte": f["contexte"].value,
            "notes": f["notes"].value,
        })
        page.pop_dialog()
        rebuild_section()

    def on_cancel(e):
        # Si l'item était vide (juste créé), on l'enlève à l'annulation
        if not exp.get("entreprise"):
            items.pop(idx)
        page.pop_dialog()
        rebuild_section()

    content = ft.Column([
        ft.Row([f["entreprise"], f["lieu"]], spacing=15),
        ft.Row([f["periode"], f["type_contrat"]], spacing=15),
        f["niveau"],
        f["mission"], f["methodologie"],
        f["competences"], f["referentiels"],
        f["contexte"], f["notes"],
    ], scroll=ft.ScrollMode.AUTO, spacing=10, width=900, height=600,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Expérience"),
        content=content,
        actions=[
            ft.TextButton("Annuler", on_click=on_cancel),
            ft.ElevatedButton("Enregistrer", icon=ft.Icons.SAVE, on_click=on_save,
                              style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE)),
        ],
    )
    page.show_dialog(dlg)


def _show_interet_dialog(page, items, idx, rebuild_section):
    it = items[idx]
    f = {
        "titre": ft.TextField(label="Titre", value=it.get("titre", "")),
        "description": ft.TextField(label="Description", value=it.get("description", ""),
                                    multiline=True, min_lines=2, max_lines=6),
        "competences": ft.TextField(label="Compétences (une par ligne)",
                                    value="\n".join(it.get("competences", []) or []),
                                    multiline=True, min_lines=2, max_lines=6),
        "pertinent_si": ft.TextField(
            label="Pertinent si l'offre mentionne",
            value=it.get("pertinent_si", ""),
            helper="Ex : électronique, automatisme, mécatronique",
        ),
    }

    def on_save(e):
        it.update({
            "titre": f["titre"].value,
            "description": f["description"].value,
            "competences": [s.strip() for s in f["competences"].value.split("\n") if s.strip()],
            "pertinent_si": f["pertinent_si"].value,
        })
        page.pop_dialog()
        rebuild_section()

    def on_cancel(e):
        if not it.get("titre"):
            items.pop(idx)
        page.pop_dialog()
        rebuild_section()

    content = ft.Column(list(f.values()),
                        scroll=ft.ScrollMode.AUTO, spacing=10, width=850, height=450,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    dlg = ft.AlertDialog(
        modal=True, title=ft.Text("Intérêt complémentaire"),
        content=content,
        actions=[
            ft.TextButton("Annuler", on_click=on_cancel),
            ft.ElevatedButton("Enregistrer", icon=ft.Icons.SAVE, on_click=on_save,
                              style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE)),
        ],
    )
    page.show_dialog(dlg)


def _show_cadre_dialog(page, items, idx, rebuild_section):
    c = items[idx]
    f = {
        "nom": ft.TextField(label="Nom du cadre",
                            value=c.get("nom", ""),
                            helper="Ex : GTB / Gestion Technique Bâtiment"),
        "declencheurs": ft.TextField(
            label="Mots-clés déclencheurs dans les offres (un par ligne)",
            value="\n".join(c.get("declencheurs", []) or []),
            multiline=True, min_lines=2, max_lines=6,
        ),
        "motivation": ft.TextField(
            label="Motivation à restituer dans la LM",
            value=c.get("motivation", ""),
            multiline=True, min_lines=2, max_lines=8,
        ),
        "acquis_theoriques": ft.TextField(
            label="Acquis théoriques (un par ligne)",
            value="\n".join(c.get("acquis_theoriques", []) or []),
            multiline=True, min_lines=2, max_lines=8,
        ),
        "acquis_pratiques": ft.TextField(
            label="Acquis pratiques (un par ligne)",
            value="\n".join(c.get("acquis_pratiques", []) or []),
            multiline=True, min_lines=2, max_lines=6,
        ),
        "regles_strictes": ft.TextField(
            label="Règles STRICTES de rédaction (une par ligne)",
            value="\n".join(c.get("regles_strictes", []) or []),
            multiline=True, min_lines=2, max_lines=8,
            helper="Ex : 'JAMAIS présenter BACnet/Modbus comme compétence pratique'",
        ),
    }

    def on_save(e):
        c.update({
            "nom": f["nom"].value,
            "declencheurs": [s.strip() for s in f["declencheurs"].value.split("\n") if s.strip()],
            "motivation": f["motivation"].value,
            "acquis_theoriques": [s.strip() for s in f["acquis_theoriques"].value.split("\n") if s.strip()],
            "acquis_pratiques": [s.strip() for s in f["acquis_pratiques"].value.split("\n") if s.strip()],
            "regles_strictes": [s.strip() for s in f["regles_strictes"].value.split("\n") if s.strip()],
        })
        page.pop_dialog()
        rebuild_section()

    def on_cancel(e):
        if not c.get("nom"):
            items.pop(idx)
        page.pop_dialog()
        rebuild_section()

    content = ft.Column(list(f.values()),
                        scroll=ft.ScrollMode.AUTO, spacing=10, width=900, height=600,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    dlg = ft.AlertDialog(
        modal=True, title=ft.Text("Cadre de positionnement"),
        content=content,
        actions=[
            ft.TextButton("Annuler", on_click=on_cancel),
            ft.ElevatedButton("Enregistrer", icon=ft.Icons.SAVE, on_click=on_save,
                              style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE)),
        ],
    )
    page.show_dialog(dlg)


# ---------- Page 3 : Parametres ----------

MODELES_CLAUDE = [
    ("claude-sonnet-4-6", "Sonnet 4.6 (recommandé - équilibre coût/qualité)"),
    ("claude-opus-4-7", "Opus 4.7 (qualité max, ~3x plus cher)"),
    ("claude-haiku-4-5", "Haiku 4.5 (le plus rapide, qualité réduite)"),
]


def parametres_page(page: ft.Page) -> ft.Control:
    settings = config.load_settings()
    status = ft.Text("", color=ft.Colors.GREEN_700)
    li_status = ft.Text("", size=12, color=ft.Colors.GREY_700)

    # ----- Champs scan -----
    fields = {
        "scan_heure": ft.TextField(
            label="Heure du scan automatique (HH:MM)",
            value=settings.get("scan_heure", ""),
        ),
        "scan_jours": ft.TextField(
            label="Jours d'exécution",
            value=settings.get("scan_jours", ""),
        ),
        "score_minimum_draft": ft.TextField(
            label="Score minimum pour création de drafts",
            value=str(settings.get("score_minimum_draft", 80)),
            keyboard_type=ft.KeyboardType.NUMBER,
        ),
        "mots_cles": ft.TextField(
            label="Mots-clés de recherche (séparés par virgules)",
            value=settings.get("mots_cles", ""),
            multiline=True, min_lines=1, max_lines=4,
        ),
        "departements_idf": ft.TextField(
            label="Départements cibles",
            value=settings.get("departements_idf", ""),
        ),
        "rayon_km": ft.TextField(
            label="Rayon géographique (km)",
            value=str(settings.get("rayon_km", 50)),
            keyboard_type=ft.KeyboardType.NUMBER,
        ),
        "sources_actives": ft.TextField(
            label="Sources actives",
            value=settings.get("sources_actives", ""),
        ),
    }

    # ----- Reglages Claude SDK (modele + concurrence) -----
    # Auth = login Claude Code (forfait Pro/Max) - pas de cle API
    model_dropdown = ft.Dropdown(
        label="Modèle Claude par défaut",
        value=settings.get("claude_model", DEFAULT_MODEL),
        options=[ft.DropdownOption(key=k, text=v) for k, v in MODELES_CLAUDE],
    )

    concurrency_slider = ft.Slider(
        label="Agents en parallèle : {value}",
        min=1, max=5, divisions=4,
        value=settings.get("concurrence_agents", 3),
    )

    # ----- Champ Cookie LinkedIn (secret) -----
    li_field = ft.TextField(
        label="Cookie LinkedIn (li_at)",
        value="**********" if secrets_store.has_secret(secrets_store.LINKEDIN_LI_AT) else "",
        password=True,
        can_reveal_password=True,
        hint_text="F12 dans Chrome > Application > Cookies > linkedin.com > li_at",
    )
    if secrets_store.has_secret(secrets_store.LINKEDIN_LI_AT):
        li_status.value = "Cookie LinkedIn enregistré"
        li_status.color = ft.Colors.GREEN_700

    def on_save(e):
        data = {k: v.value for k, v in fields.items()}
        try:
            data["score_minimum_draft"] = int(data["score_minimum_draft"])
            data["rayon_km"] = int(data["rayon_km"])
        except ValueError:
            status.value = "Erreur : score et rayon doivent être des nombres"
            status.color = ft.Colors.RED_700
            page.update()
            return

        # Settings Claude SDK (non secrets)
        data["claude_model"] = model_dropdown.value
        data["concurrence_agents"] = int(concurrency_slider.value)

        config.save_settings(data)

        # Secret cookie LinkedIn
        li_val = li_field.value.strip()
        if li_val and not li_val.startswith("****"):
            secrets_store.set_secret(secrets_store.LINKEDIN_LI_AT, li_val)
            li_status.value = "Cookie LinkedIn mis à jour"
            li_status.color = ft.Colors.GREEN_700
            li_field.value = "**********"
        elif not li_val:
            secrets_store.delete_secret(secrets_store.LINKEDIN_LI_AT)
            li_status.value = "Cookie LinkedIn supprimé"
            li_status.color = ft.Colors.GREY_700

        status.value = f"Paramètres enregistrés ({config.SETTINGS_PATH.name} + Credential Manager)"
        status.color = ft.Colors.GREEN_700
        page.update()

    def on_schedule_task(e):
        """Crée la tâche planifiée Windows via schtasks."""
        import subprocess
        heure = fields["scan_heure"].value.strip()
        if not heure or ":" not in heure:
            status.value = "Erreur : heure invalide (format HH:MM)"
            status.color = ft.Colors.RED_700
            page.update()
            return
        script_path = Path(__file__).parent / "app.py"
        task_name = "RechercheEmploi_ScanQuotidien"
        cmd = [
            "schtasks", "/Create", "/F",
            "/SC", "WEEKLY",
            "/D", "MON,TUE,WED,THU,FRI",
            "/ST", heure,
            "/TN", task_name,
            "/TR", f'pythonw.exe "{script_path}"',
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                status.value = f"Tâche planifiée '{task_name}' créée pour {heure} (L-V)"
                status.color = ft.Colors.GREEN_700
            else:
                status.value = f"Erreur schtasks : {result.stderr.strip()[:100]}"
                status.color = ft.Colors.RED_700
        except Exception as ex:
            status.value = f"Erreur : {ex}"
            status.color = ft.Colors.RED_700
        page.update()

    return ft.Column([
        ft.Text("Paramètres",
                size=22, weight=ft.FontWeight.BOLD),

        ft.Text("Claude (génération CV+LM)", size=15,
                weight=ft.FontWeight.BOLD, color=ft.Colors.PURPLE_700),
        ft.Text(
            "L'app utilise ton login Claude Code (forfait Pro/Max) - aucun "
            "coût additionnel par appel. Vérifie que tu es loggé : `claude` au terminal.",
            size=11, color=ft.Colors.GREY_700,
        ),
        model_dropdown,
        ft.Text("Concurrence : nombre d'agents Claude simultanés pendant un batch",
                size=11, color=ft.Colors.GREY_700),
        concurrency_slider,

        ft.Divider(),
        ft.Text("LinkedIn (cookie de session)", size=15,
                weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700),
        ft.Text(
            "Optionnel. Sans cookie, le scraper LinkedIn sera sauté "
            "(les autres sources continuent de fonctionner).",
            size=11, color=ft.Colors.GREY_700,
        ),
        li_field,
        li_status,

        ft.Divider(),
        ft.Text("Scan automatique des offres", size=15,
                weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_700),
        *fields.values(),

        ft.Divider(),
        ft.Row([
            ft.ElevatedButton(
                "Enregistrer", icon=ft.Icons.SAVE, on_click=on_save,
                style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN_600, color=ft.Colors.WHITE),
            ),
            ft.OutlinedButton(
                "Programmer la tâche Windows", icon=ft.Icons.SCHEDULE,
                on_click=on_schedule_task,
            ),
            status,
        ], wrap=True),
    ], scroll=ft.ScrollMode.AUTO, expand=True, spacing=10,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
