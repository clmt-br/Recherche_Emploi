"""Outils MCP custom exposes au Claude Agent SDK.

Deux outils :
    - mcp__formulations__record_formulation : ecrit en DB les formulations
      utilisees dans une LM, pour alimenter la banque anti-repetition
    - mcp__formulations__lookup_formulations : lit les N dernieres
      formulations utilisees, pour interdire leur reutilisation

Le serveur MCP est in-process (pas de subprocess), tres leger.
Voir : https://github.com/anthropics/claude-agent-sdk-python#mcp
"""
from claude_agent_sdk import tool, create_sdk_mcp_server

import db


@tool(
    "record_formulation",
    "Enregistre les formulations utilisees dans la nouvelle lettre de motivation, "
    "pour alimenter la banque anti-repetition. A appeler en fin de generation.",
    {
        "job_id": str,
        "entreprise": str,
        "ouverture": str,
        "formule_familiere": str,
        "transition": str,
        "cloture": str,
    },
)
async def record_formulation(args):
    db.record_formulation(
        job_id=args.get("job_id", ""),
        entreprise=args.get("entreprise", ""),
        ouverture=args.get("ouverture", ""),
        formule_familiere=args.get("formule_familiere", ""),
        transition=args.get("transition", ""),
        cloture=args.get("cloture", ""),
    )
    return {
        "content": [{
            "type": "text",
            "text": f"Formulations enregistrees pour {args.get('entreprise', '?')}.",
        }]
    }


@tool(
    "lookup_formulations",
    "Retourne les N dernieres formulations utilisees dans des lettres de motivation precedentes. "
    "Utilise pour eviter les repetitions (varier ouverture, formule familiere, transition, cloture).",
    {"limit": int},
)
async def lookup_formulations(args):
    limit = args.get("limit") or 30
    items = db.list_recent_formulations(limit=limit)
    if not items:
        return {
            "content": [{
                "type": "text",
                "text": "Aucune formulation enregistree pour le moment - tu peux utiliser des formulations standards.",
            }]
        }
    lines = ["Formulations DEJA UTILISEES (a NE PAS reutiliser) :", ""]
    lines.append("| Entreprise | Ouverture | Formule familiere | Transition | Cloture |")
    lines.append("|---|---|---|---|---|")
    for f in items:
        ent = (f.get("entreprise") or "")[:30]
        ouv = (f.get("ouverture") or "").replace("\n", " ")[:60]
        ff = (f.get("formule_familiere") or "").replace("\n", " ")[:60]
        tr = (f.get("transition") or "").replace("\n", " ")[:40]
        cl = (f.get("cloture") or "").replace("\n", " ")[:40]
        lines.append(f"| {ent} | {ouv} | {ff} | {tr} | {cl} |")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# Serveur MCP in-process, a passer dans ClaudeAgentOptions.mcp_servers
formulations_server = create_sdk_mcp_server(
    name="formulations",
    version="1.0.0",
    tools=[record_formulation, lookup_formulations],
)


# Helper pour la liste des outils a autoriser dans allowed_tools
TOOL_NAMES = [
    "mcp__formulations__record_formulation",
    "mcp__formulations__lookup_formulations",
]


if __name__ == "__main__":
    import asyncio

    async def _smoke_test():
        # Test direct des handlers via .handler (le decorateur @tool wrappe en SdkMcpTool)
        out = await record_formulation.handler({
            "job_id": "test_smoke",
            "entreprise": "TestSmoke",
            "ouverture": "Accroche test",
            "formule_familiere": "test familier",
            "transition": "test transition",
            "cloture": "test cloture",
        })
        print("record_formulation OK :", out["content"][0]["text"])

        out = await lookup_formulations.handler({"limit": 3})
        print("\nlookup_formulations OK :")
        print(out["content"][0]["text"])

        # Cleanup
        import sqlite3
        con = sqlite3.connect(db.DB_PATH)
        con.execute("DELETE FROM formulations_utilisees WHERE job_id = 'test_smoke'")
        con.commit()
        con.close()
        print("\nNettoyage OK")

    asyncio.run(_smoke_test())
