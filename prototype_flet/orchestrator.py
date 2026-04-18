"""Orchestrateur de batch : lance N agents en parallele avec semaphore + gather.

Usage type (depuis l'UI) :
    channel = ProgressChannel()

    async def workflow():
        runner = asyncio.create_task(
            orchestrator.run_batch([5, 12, 47], channel)
        )
        async for ev in channel.consume():
            update_card(ev)
            page.update()
        results = await runner
        # Afficher recap (cout, succes, echecs)

    def on_click(e):
        run_in_flet(page, workflow())
"""
import asyncio
from typing import Optional

import config
import db
from agent_runner import RunResult, run_one
from flet_async_bridge import ProgressChannel, ProgressEvent

DEFAULT_CONCURRENCY = 3


async def run_batch(
    offre_ids: list[int],
    channel: Optional[ProgressChannel] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    model: Optional[str] = None,
    close_channel_on_done: bool = True,
) -> list[RunResult]:
    """Concretise N offres en parallele avec un semaphore.

    Args:
        offre_ids : liste d'ids d'offres a concretiser
        channel : ProgressChannel partage (cree un nouveau si None)
        concurrency : nb d'agents simultanes (defaut 3)
        model : modele Claude a utiliser pour TOUS les agents (defaut SDK default)
        close_channel_on_done : si True, ferme le channel a la fin (sentinel None
            pour stopper le consumer). Mettre False si tu reutilises le channel.

    Retourne la liste des RunResult dans l'ordre de offre_ids.
    """
    if channel is None:
        channel = ProgressChannel()

    profile = config.load_profile()
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _bounded(offre_id: int) -> RunResult:
        offre = db.get_offre(offre_id)
        if offre is None:
            await channel.emit(ProgressEvent(
                offre_id, "error", f"Offre #{offre_id} introuvable",
            ))
            return RunResult(ok=False, offre_id=offre_id, error="Offre introuvable")

        await channel.emit(ProgressEvent(
            offre_id, "queued", f"En file : {offre.entreprise} - {offre.intitule[:50]}",
        ))
        async with semaphore:
            kwargs = {"model": model} if model else {}
            return await run_one(offre, profile, channel, **kwargs)

    tasks = [asyncio.create_task(_bounded(oid)) for oid in offre_ids]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=False)
    finally:
        if close_channel_on_done:
            await channel.close()

    return results


async def run_all_drafts(
    channel: Optional[ProgressChannel] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    model: Optional[str] = None,
) -> list[RunResult]:
    """Concretise TOUTES les offres avec statut 'draft'."""
    drafts = db.list_offres(statut="draft")
    if not drafts:
        if channel is not None:
            await channel.emit(ProgressEvent(0, "done", "Aucun draft a traiter"))
            await channel.close()
        return []
    return await run_batch(
        [o.id for o in drafts],
        channel=channel,
        concurrency=concurrency,
        model=model,
    )


# ============================================================
# Smoke test (sans appel API)
# ============================================================

if __name__ == "__main__":
    # Verif que les imports passent et que l'API est coherente
    import inspect
    print("run_batch signature:", inspect.signature(run_batch))
    print("run_all_drafts signature:", inspect.signature(run_all_drafts))

    # Verif qu'on a au moins une offre dans la DB pour un dry run
    drafts = db.list_offres(statut="draft")
    print(f"Drafts dispos : {len(drafts)}")
    rapport = db.list_offres(statut="rapport")
    print(f"Offres en rapport : {len(rapport)}")
    print("OK orchestrator")
