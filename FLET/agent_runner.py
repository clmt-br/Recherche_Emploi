"""Pilote un agent Claude SDK pour generer CV+LM d'une offre, avec retry intelligent.

Le module expose `run_one(offre, ...)` : une coroutine qui
    1. Cree le dossier cible (Entreprises/<X>/<slug>/) et y copie le CV base
    2. Construit system + user prompts depuis profile.yaml et la banque formulations
    3. Lance ClaudeSDKClient en mode bypassPermissions (zero prompt UI)
    4. Streame les messages SDK -> ProgressChannel (mises a jour live de l'UI)
    5. Lance les validators post-generation
    6. Retry une fois si validation echoue, en re-injectant les erreurs precises
    7. Met a jour la DB (cv_path, lm_path, statut, validation_report, etc.)

Tous les events SDK sont aussi logues dans <folder>/agent_log.txt pour debug.

Utilise par orchestrator.py pour le batch parallele.
"""
import asyncio
import json
import re
import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

import db
import mcp_tools
from concretize import _slugify, prepare_folder
from flet_async_bridge import ProgressChannel, ProgressEvent
from prompt_builder import build_system_prompt, build_user_prompt
from validators import format_errors_for_retry, run_all, ValidationReport


DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TURNS_PER_AGENT = 30
MAX_RETRY_ATTEMPTS = 2  # 1 generation + 1 retry maxi

import paths


# Le CV base a utiliser. Cherche dans cet ordre :
#   1. settings.yaml -> "cv_base_filename"
#   2. CV_CBouillier_base.tex (legacy, profil Clement)
#   3. CV_template.tex (template generique distribue)
def _resolve_cv_base_path() -> Path:
    import config
    project_root = paths.project_dir()
    settings = config.load_settings()
    candidates = []
    custom = settings.get("cv_base_filename", "").strip()
    if custom:
        candidates.append(custom)
    candidates += ["CV_CBouillier_base.tex", "CV_template.tex"]
    for name in candidates:
        p = project_root / name
        if p.exists():
            return p
    # Fallback (n'existera pas mais evite une exception immediate)
    return project_root / "CV_template.tex"


CV_BASE_PATH = _resolve_cv_base_path()


def _candidate_initials(profile: dict) -> str:
    """Extrait les initiales du candidat depuis profile.identite.nom.

    'Clement Bouillier' -> 'CB', 'Jean-Marc Dupont' -> 'JMD'.
    """
    nom = (profile.get("identite", {}) or {}).get("nom", "").strip()
    if not nom:
        return "Candidat"
    parts = re.split(r"[\s\-]+", nom)
    initials = "".join(p[0].upper() for p in parts if p)
    return initials or "Candidat"


def _log(folder: Path, msg: str):
    """Append une ligne timestampee dans agent_log.txt du folder."""
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        with open(folder / "agent_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass  # le log ne doit jamais faire echouer l'agent


@dataclass
class RunResult:
    ok: bool
    offre_id: int
    cv_path: str = ""
    lm_path: str = ""
    parsed: Optional[dict] = None
    report: Optional[ValidationReport] = None
    cost_usd: float = 0.0
    error: str = ""


# ============================================================
# Extraction du JSON final
# ============================================================

JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
JSON_NAKED_RE = re.compile(r"(\{(?:[^{}]|\{[^{}]*\})*\})", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """Extrait le bloc JSON final d'un texte assistant."""
    if not text:
        return None
    # 1. Bloc ```json ... ```
    m = JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. JSON nu (premier objet trouve)
    for m in JSON_NAKED_RE.finditer(text):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict) and ("cv_path" in obj or "lm_path" in obj):
                return obj
        except json.JSONDecodeError:
            continue
    return None


# ============================================================
# Lancement d'un agent
# ============================================================

async def _run_agent(
    user_prompt: str,
    options: ClaudeAgentOptions,
    offre_id: int,
    channel: ProgressChannel,
    folder: Path,
) -> tuple[str, float]:
    """Lance UN agent (un tour de query/receive_response).

    Retourne (final_text, cost_usd). Le final_text est le DERNIER bloc texte
    de l'AssistantMessage final (typiquement le JSON de sortie).
    Tous les events sont logues dans folder/agent_log.txt.
    """
    final_text = ""
    cost = 0.0
    n_messages = 0
    n_tool_uses = 0

    _log(folder, "=== USER PROMPT ===")
    _log(folder, user_prompt[:1000] + ("..." if len(user_prompt) > 1000 else ""))
    _log(folder, "=== STREAM START ===")

    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(user_prompt)
            async for msg in client.receive_response():
                n_messages += 1
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            final_text = block.text
                            snippet = block.text.strip().replace("\n", " ")[:160]
                            _log(folder, f"TEXT: {block.text[:300]}")
                            if snippet:
                                await channel.emit(ProgressEvent(
                                    offre_id, "text", snippet,
                                ))
                        elif isinstance(block, ToolUseBlock):
                            n_tool_uses += 1
                            tool_label = block.name.replace("mcp__formulations__", "")
                            detail = ""
                            try:
                                inp = block.input or {}
                                if block.name == "Bash":
                                    detail = (inp.get("command", "") or "")[:80]
                                elif block.name in ("Read", "Edit", "Write"):
                                    detail = (inp.get("file_path", "") or "")[-60:]
                                elif block.name == "WebFetch":
                                    detail = (inp.get("url", "") or "")[-80:]
                            except Exception:
                                pass
                            msg_short = f"{tool_label}" + (f" : {detail}" if detail else "")
                            _log(folder, f"TOOL: {block.name} input={json.dumps(block.input or {}, ensure_ascii=False)[:300]}")
                            await channel.emit(ProgressEvent(
                                offre_id, "tool_use", msg_short,
                            ))
                elif isinstance(msg, ToolResultBlock):
                    # Loguer le resultat (utile pour debug erreurs xelatex)
                    content = getattr(msg, "content", "")
                    if isinstance(content, list):
                        content_str = " ".join(
                            c.get("text", str(c)) if isinstance(c, dict) else str(c)
                            for c in content
                        )
                    else:
                        content_str = str(content)
                    is_error = getattr(msg, "is_error", False)
                    _log(folder, f"TOOL_RESULT (error={is_error}): {content_str[:500]}")
                elif isinstance(msg, ResultMessage):
                    cost = float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
                    _log(folder, f"=== RESULT cost=${cost:.4f} ===")
                    # ResultMessage termine la conversation
                    break
                else:
                    _log(folder, f"OTHER: {type(msg).__name__}")
    except Exception as ex:
        tb = traceback.format_exc()
        _log(folder, f"=== EXCEPTION ===\n{tb}")
        raise

    _log(folder, f"=== STREAM END ({n_messages} msgs, {n_tool_uses} tool calls) ===")
    _log(folder, f"=== FINAL TEXT ({len(final_text)} chars) ===")
    _log(folder, final_text or "(vide - aucun texte assistant)")

    return final_text, cost


# ============================================================
# Construction des options SDK
# ============================================================

def _build_options(
    profile: dict,
    formulations: list[dict],
    folder: Path,
    model: str = DEFAULT_MODEL,
) -> ClaudeAgentOptions:
    """Construit ClaudeAgentOptions a partir du profil et du dossier cible."""
    return ClaudeAgentOptions(
        system_prompt=build_system_prompt(profile, formulations),
        cwd=str(folder),
        permission_mode="bypassPermissions",
        allowed_tools=[
            "Read", "Write", "Edit", "Bash", "WebFetch", "Glob", "Grep",
        ] + mcp_tools.TOOL_NAMES,
        mcp_servers={"formulations": mcp_tools.formulations_server},
        model=model,
        max_turns=MAX_TURNS_PER_AGENT,
        # Permettre aux outils de lire le CV base + le repertoire racine du projet
        add_dirs=[str(CV_BASE_PATH.parent)],
    )


# ============================================================
# Point d'entree principal : run_one
# ============================================================

async def run_one(
    offre,
    profile: dict,
    channel: Optional[ProgressChannel] = None,
    model: str = DEFAULT_MODEL,
) -> RunResult:
    """Genere CV+LM pour UNE offre avec retry intelligent (max 2 tentatives).

    Args:
        offre : db.Offre
        profile : dict charge depuis profile.yaml
        channel : ProgressChannel pour streamer les events vers l'UI (optionnel)
        model : modele Claude a utiliser

    Met a jour la DB : cv_path, lm_path, validation_report, statut (en_cours ou a_revoir),
    last_error, concretize_attempts.
    """
    if channel is None:
        channel = ProgressChannel()  # silencieux, pas consume

    # 1. Preparation du dossier + pre-copie du CV base
    folder = prepare_folder(offre)
    db.set_dossier_pc(offre.id, str(folder))

    company_slug = _slugify(offre.entreprise, max_len=30) or "Entreprise"
    initials = _candidate_initials(profile)
    cv_tex_target = folder / f"CV_{initials}_{company_slug}.tex"
    if not cv_tex_target.exists():
        try:
            shutil.copy2(CV_BASE_PATH, cv_tex_target)
            _log(folder, f"CV base copie : {CV_BASE_PATH.name} -> {cv_tex_target.name}")
        except Exception as ex:
            _log(folder, f"Erreur copie CV base : {ex}")

    # Reset le log si nouveau run (premiere tentative)
    log_path = folder / "agent_log.txt"
    log_path.write_text(
        f"=== Concretisation {offre.entreprise} - {offre.intitule} ===\n"
        f"Date: {datetime.now().isoformat()}\n"
        f"Folder: {folder}\n"
        f"CV base copie: {cv_tex_target.name}\n\n",
        encoding="utf-8",
    )

    await channel.emit(ProgressEvent(
        offre.id, "start", f"{offre.entreprise} : preparation",
        payload={"folder": str(folder)},
    ))

    # 2. Construction des prompts et options
    formulations = db.list_recent_formulations(limit=30)
    options = _build_options(profile, formulations, folder, model=model)

    user_prompt = build_user_prompt(offre, folder, CV_BASE_PATH, cv_tex_target.name)

    total_cost = 0.0
    last_report: Optional[ValidationReport] = None
    parsed: Optional[dict] = None
    final_text = ""

    expected_keywords = list(offre.matched_skills or [])

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        await channel.emit(ProgressEvent(
            offre.id, "start", f"Tentative {attempt}/{MAX_RETRY_ATTEMPTS}",
        ))
        _log(folder, f"\n=== TENTATIVE {attempt}/{MAX_RETRY_ATTEMPTS} ===")
        db.update_concretize_progress(offre.id, attempts_increment=True)

        try:
            final_text, cost = await _run_agent(
                user_prompt, options, offre.id, channel, folder,
            )
            total_cost += cost
        except Exception as ex:
            _log(folder, f"=== EXCEPTION RUN_AGENT ===\n{traceback.format_exc()}")
            await channel.emit(ProgressEvent(offre.id, "error", f"Agent KO : {ex}"))
            db.update_concretize_progress(
                offre.id,
                last_error=f"{type(ex).__name__}: {ex}",
                new_statut="a_revoir",
            )
            return RunResult(ok=False, offre_id=offre.id, error=str(ex), cost_usd=total_cost)

        # 3. Tentative de parser le JSON final
        parsed = _extract_json(final_text)

        # 4. Validation post-generation
        await channel.emit(ProgressEvent(offre.id, "validate", "Verification CV/LM..."))
        last_report = run_all(folder, expected_keywords=expected_keywords)

        if last_report.ok:
            # Succes
            await channel.emit(ProgressEvent(
                offre.id, "done",
                f"OK ({last_report.pages_pdf}p, ATS {last_report.ats_score})",
                payload={"cost_usd": total_cost},
            ))
            db.update_concretize_progress(
                offre.id,
                cv_path=last_report.cv_path,
                lm_path=last_report.lm_path,
                validation_report=last_report.to_dict(),
                last_error="",
                new_statut="en_cours",
            )
            # Parser et logger les formulations si present (au cas ou l'agent
            # n'a pas appele record_formulation lui-meme)
            _maybe_record_formulations(offre, parsed)
            return RunResult(
                ok=True,
                offre_id=offre.id,
                cv_path=last_report.cv_path,
                lm_path=last_report.lm_path,
                parsed=parsed,
                report=last_report,
                cost_usd=total_cost,
            )

        # 5. Echec : preparer le retry intelligent
        if attempt < MAX_RETRY_ATTEMPTS:
            await channel.emit(ProgressEvent(
                offre.id, "retry",
                f"Validation KO ({len(last_report.errors)} erreurs) - retry",
            ))
            user_prompt = format_errors_for_retry(last_report)
            # On REUTILISE le client (en fait on en cree un nouveau dans _run_agent)
            # Le retry est sans state, mais le folder contient les fichiers donc
            # l'agent peut les Read et corriger.

    # Echec apres tous les retries
    err_msg = "; ".join((last_report.errors if last_report else ["Echec inconnu"])[:3])
    await channel.emit(ProgressEvent(
        offre.id, "error", f"Echec apres {MAX_RETRY_ATTEMPTS} tentatives : {err_msg}",
        payload={"cost_usd": total_cost},
    ))
    db.update_concretize_progress(
        offre.id,
        cv_path=last_report.cv_path if last_report else "",
        lm_path=last_report.lm_path if last_report else "",
        validation_report=last_report.to_dict() if last_report else {},
        last_error=err_msg,
        new_statut="a_revoir",
    )
    return RunResult(
        ok=False,
        offre_id=offre.id,
        cv_path=last_report.cv_path if last_report else "",
        lm_path=last_report.lm_path if last_report else "",
        parsed=parsed,
        report=last_report,
        cost_usd=total_cost,
        error=err_msg,
    )


def _maybe_record_formulations(offre, parsed: Optional[dict]):
    """Si l'agent n'a pas appele mcp record_formulation, on essaye nous-meme
    a partir du JSON parse."""
    if not parsed or "formulations_utilisees" not in parsed:
        return
    f = parsed["formulations_utilisees"]
    if not isinstance(f, dict):
        return
    # On regarde si la derniere formulation enregistree concerne deja cette offre
    recent = db.list_recent_formulations(limit=3)
    if recent and recent[0].get("entreprise") == offre.entreprise:
        return  # deja enregistre par l'agent
    db.record_formulation(
        job_id=str(offre.id),
        entreprise=offre.entreprise,
        ouverture=f.get("ouverture", ""),
        formule_familiere=f.get("formule_familiere", ""),
        transition=f.get("transition", ""),
        cloture=f.get("cloture", ""),
    )


# ============================================================
# Smoke test (sans appeler vraiment l'API)
# ============================================================

if __name__ == "__main__":
    import config

    profile = config.load_profile()
    formulations = db.list_recent_formulations(limit=5)
    folder = Path(__file__).parent / "_smoke_test_folder"
    folder.mkdir(exist_ok=True)

    options = _build_options(profile, formulations, folder)
    print(f"system_prompt length: {len(options.system_prompt)} chars")
    print(f"allowed_tools: {options.allowed_tools}")
    print(f"mcp_servers: {list(options.mcp_servers.keys())}")
    print(f"model: {options.model}")
    print(f"cwd: {options.cwd}")
    print(f"permission_mode: {options.permission_mode}")
    print(f"add_dirs: {options.add_dirs}")
    print("OK : options construites correctement")

    # Test _extract_json
    text = '''Voici le resultat :
```json
{
  "cv_path": "/tmp/cv.pdf",
  "lm_path": "/tmp/lm.docx",
  "score_ats_estime": 85,
  "formulations_utilisees": {"ouverture": "test"}
}
```'''
    parsed = _extract_json(text)
    print(f"\n_extract_json : {parsed}")
    assert parsed and parsed.get("score_ats_estime") == 85, "JSON parse failed"
    print("OK : _extract_json marche")

    # Cleanup
    import shutil
    if folder.exists():
        shutil.rmtree(folder)
