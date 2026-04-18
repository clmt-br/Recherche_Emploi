"""Pont asyncio <-> Flet.

Probleme : le Claude Agent SDK est purement async, et on veut lancer N agents
en parallele depuis un on_click() Flet (sync) sans bloquer l'UI.

Solution :
    - run_in_flet(page, coroutine) : lance une coro depuis un handler sync.
      Utilise page.run_task (Flet >= 0.25) si dispo, sinon fallback thread+loop.
    - ProgressChannel : queue asyncio commune ou les agents poussent des
      ProgressEvent ; un consumer dans l'UI les lit et met a jour les cards.

Usage type (cote UI) :
    channel = ProgressChannel()

    async def workflow():
        # Lancer N agents en parallele, qui pushent dans channel
        runner = asyncio.create_task(orchestrator.run_batch(ids, channel))
        async for ev in channel.consume():
            update_card(ev)
            page.update()
        await runner

    def on_click(e):
        run_in_flet(page, workflow())
"""
import asyncio
import threading
import traceback
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, Union


# ============================================================
# Evenements de progression
# ============================================================

@dataclass
class ProgressEvent:
    """Evenement remonte par un job parallele.

    kind possibles :
        "queued"     - offre placee en file
        "start"      - agent demarre pour cette offre
        "tool_use"   - un outil est appele (Bash, Edit, etc.)
        "text"       - extrait de texte assistant
        "validate"   - phase de validation post-generation
        "retry"      - retry intelligent (validation echouee)
        "done"       - fini OK -> passe en_cours
        "error"      - fini KO -> passe a_revoir
    """
    offre_id: int
    kind: str
    message: str = ""
    payload: Any = None


# ============================================================
# Canal de progression (queue asyncio)
# ============================================================

class ProgressChannel:
    """Queue asyncio + helpers pour rassembler N flux de progression.

    L'orchestrateur emit() depuis chaque agent, l'UI consume() en async-for.
    Sentinel None pour terminer proprement le consume.
    """

    def __init__(self):
        self.queue: asyncio.Queue[Optional[ProgressEvent]] = asyncio.Queue()
        self._closed = False

    async def emit(self, event: ProgressEvent):
        if not self._closed:
            await self.queue.put(event)

    async def close(self):
        """Signale au consumer d'arreter la boucle async-for."""
        if not self._closed:
            self._closed = True
            await self.queue.put(None)

    async def consume(self) -> AsyncIterator[ProgressEvent]:
        """Iterator async qui yield les events jusqu'a close()."""
        while True:
            event = await self.queue.get()
            if event is None:
                break
            yield event


# ============================================================
# Lanceur depuis handler sync Flet
# ============================================================

CoroOrFactory = Union[Awaitable, Callable[[], Awaitable]]


def run_in_flet(page, coro_or_factory: CoroOrFactory):
    """Lance une coroutine depuis un handler sync (on_click Flet).

    Accepte soit une coroutine deja construite, soit une coroutine function
    (sans argument). Capture les exceptions pour eviter les crash silencieux.
    """
    async def safe():
        try:
            if callable(coro_or_factory):
                await coro_or_factory()
            else:
                await coro_or_factory
        except Exception as ex:
            print(f"[run_in_flet] {type(ex).__name__}: {ex}")
            traceback.print_exc()

    # Flet >= 0.25 : page.run_task accepte un handler (coroutine function)
    if hasattr(page, "run_task"):
        try:
            page.run_task(safe)
            return
        except Exception as ex:
            print(f"[run_in_flet] page.run_task a echoue ({ex}), fallback thread")

    # Fallback : thread daemon + nouvelle event loop
    def thread_runner():
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(safe())
        finally:
            loop.close()

    threading.Thread(target=thread_runner, daemon=True).start()


# ============================================================
# POC mini (executable directement)
# ============================================================

async def _poc_producer(channel: ProgressChannel, offre_id: int, n: int = 3):
    """Demo : un job qui emit n events puis termine."""
    await channel.emit(ProgressEvent(offre_id, "start", f"Job {offre_id} demarre"))
    for i in range(n):
        await asyncio.sleep(0.1)
        await channel.emit(ProgressEvent(offre_id, "tool_use", f"Step {i+1}/{n}"))
    await channel.emit(ProgressEvent(offre_id, "done", f"Job {offre_id} termine"))


async def _poc_main():
    """Demo : 3 jobs paralleles, consumer prints les events."""
    channel = ProgressChannel()
    producers = asyncio.gather(
        _poc_producer(channel, 1, 3),
        _poc_producer(channel, 2, 2),
        _poc_producer(channel, 3, 4),
    )

    async def consumer():
        async for ev in channel.consume():
            print(f"  [{ev.offre_id}] {ev.kind}: {ev.message}")

    consumer_task = asyncio.create_task(consumer())
    await producers
    await channel.close()
    await consumer_task


if __name__ == "__main__":
    print("POC flet_async_bridge : 3 producteurs paralleles, 1 consumer")
    asyncio.run(_poc_main())
    print("OK")
