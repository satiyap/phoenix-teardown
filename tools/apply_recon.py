"""One-shot: write Phase 1 recon findings into each projects/*/facts.yaml.

Fills project metadata (repo, docs, licence, evidence class, depth) and the
Q-section licence probes, which are the only probes answerable from recon.

Everything else stays 'unknown' — recon does not license architectural claims.

    ./.venv/bin/python tools/apply_recon.py
"""

from __future__ import annotations

import re

from probes import PROJECTS_DIR, REPO_ROOT

READ_ON = "2026-08-26"

# slug -> metadata confirmed via GitHub API on READ_ON
RECON: dict[str, dict] = {
    "google-ax": dict(
        repo="https://github.com/google/ax", docs="https://agentexecutor.io",
        license="Apache-2.0", license_verdict="REFERENCE_ONLY",
        evidence_class="A", depth="deep",
        one_line="Distributed harness runtime that provisions isolated, suspendable/resumable environments to execute harnesses and agents.",
        stars=1970, pushed="2026-08-20",
        q2="No enterprise-only components found in repo.",
        q6="REFERENCE_ONLY — Apache-2.0 permits embedding, but Go and pre-1.0 with breaking changes expected; external PRs paused.",
    ),
    "omnigent": dict(
        repo="https://github.com/omnigent-ai/omnigent", docs="https://omnigent.ai",
        license="Apache-2.0", license_verdict="INTEGRATE",
        evidence_class="A", depth="deep",
        one_line="Open-source meta-harness providing a common orchestration layer over Claude Code, Codex, Cursor, OpenCode, Hermes and Pi.",
        stars=9290, pushed="2026-08-26",
        q2="Hosted Omnigent Cloud is commercial; harness layer is open.",
        q6="INTEGRATE — Apache-2.0, closest precedent for our adapter thesis (ADR-0004).",
    ),
    "ag2": dict(
        repo="https://github.com/ag2ai/ag2", docs="https://docs.ag2.ai",
        license="Apache-2.0", license_verdict="REFERENCE_ONLY",
        evidence_class="A", depth="deep",
        one_line="Formerly AutoGen; self-described open-source AgentOS focused on multi-agent conversation patterns.",
        stars=4890, pushed="2026-08-25",
        q2="None found.",
        q6="REFERENCE_ONLY — Apache-2.0, but carries framework opinions we do not want internally.",
    ),
    "letta": dict(
        repo="https://github.com/letta-ai/letta-code", docs="https://docs.letta.com",
        license="Apache-2.0", license_verdict="REFERENCE_ONLY",
        evidence_class="A", depth="deep",
        one_line="Stateful agents with long-lived memory and identity; harness, App Server and channels in TypeScript.",
        stars=3122, pushed="2026-08-26",
        q2="Letta Cloud (hosted memory, identity, cross-device continuity) is commercial and closed.",
        q6="REFERENCE_ONLY — Apache-2.0. NOTE: source moved from letta-ai/letta to letta-ai/letta-code; Python V1 server retired to 'archive' branch. Cite repo and branch explicitly.",
    ),
    "openhands": dict(
        repo="https://github.com/OpenHands/OpenHands",
        docs="https://docs.all-hands.dev",
        license="MIT", license_verdict="INTEGRATE",
        evidence_class="A", depth="deep",
        one_line="AI-driven software development agent with a sandboxed execution runtime.",
        stars=85139, pushed="2026-08-26",
        q2="OpenHands Cloud is commercial; runtime and agent are open.",
        q6="INTEGRATE — MIT. Org renamed from All-Hands-AI to OpenHands.",
    ),
    "cloudflare-agents": dict(
        repo="https://github.com/cloudflare/agents",
        docs="https://developers.cloudflare.com/agents/",
        license="MIT", license_verdict="REFERENCE_ONLY",
        evidence_class="A", depth="deep",
        one_line="Framework for building stateful agents on Cloudflare Workers, backed by Durable Objects.",
        stars=5488, pushed="2026-08-26",
        q2="Depends on Cloudflare's commercial platform (Workers, Durable Objects).",
        q6="REFERENCE_ONLY — MIT, but the durable actor model is inseparable from Durable Objects.",
    ),
    "langgraph": dict(
        repo="https://github.com/langchain-ai/langgraph",
        docs="https://langchain-ai.github.io/langgraph/",
        license="MIT", license_verdict="INTEGRATE",
        evidence_class="A", depth="deep",
        one_line="Graph-based runtime for building resilient agents with pluggable checkpointers.",
        stars=40479, pushed="2026-08-26",
        q2="LangSmith server is closed; LangGraph Platform is commercial. Checkpointers and graph runtime are open.",
        q6="INTEGRATE — MIT for the runtime. libs/checkpoint-conformance is a durability specification worth close reading.",
    ),
    "pydantic-ai": dict(
        repo="https://github.com/pydantic/pydantic-ai", docs="https://ai.pydantic.dev",
        license="MIT", license_verdict="INTEGRATE",
        evidence_class="A", depth="deep",
        one_line="Type-driven agent framework in the Pydantic idiom.",
        stars=19505, pushed="2026-08-26",
        q2="Pydantic Logfire (hosted observability) is commercial.",
        q6="INTEGRATE — MIT.",
    ),
    "google-agent-platform": dict(
        repo="https://github.com/google/adk-python",
        docs="https://google.github.io/adk-docs/",
        license="Apache-2.0", license_verdict="INTEGRATE",
        evidence_class="B", depth="deep",
        one_line="Agent Development Kit plus the managed Vertex AI Agent Engine control plane.",
        stars=21292, pushed="2026-08-26",
        q2="Vertex AI Agent Engine control plane is closed. ADK is open.",
        q6="INTEGRATE — ADK is Apache-2.0; managed plane is class B evidence only.",
    ),
    "groupmind": dict(
        license_verdict="unknown", evidence_class="C", depth="recon",
        one_line="Not located: no substantive public repository found.",
        q6="Not assessable — project could not be located. Questions reassigned to Omnigent and HumanLayer (see recon.md).",
    ),
    "microsoft-agent-framework": dict(
        repo="https://github.com/microsoft/agent-framework",
        docs="https://learn.microsoft.com/en-us/agent-framework/",
        license="MIT", license_verdict="REFERENCE_ONLY",
        evidence_class="A", depth="targeted",
        one_line="Framework for building, orchestrating and deploying agents; successor to the Semantic Kernel and AutoGen lineage.",
        stars=13122, pushed="2026-08-26",
        q2="Azure AI Foundry is the commercial hosted counterpart.",
        q6="REFERENCE_ONLY — MIT, but strongly .NET/Azure-shaped.",
    ),
    "aws-agentcore": dict(
        repo="https://github.com/aws/bedrock-agentcore-sdk-python",
        docs="https://docs.aws.amazon.com/bedrock-agentcore/",
        license="Apache-2.0", license_verdict="REFERENCE_ONLY",
        evidence_class="B", depth="targeted",
        one_line="Managed AWS primitives for running agents in production: runtime, identity, gateway, memory.",
        stars=755, pushed="2026-08-25",
        q2="Managed runtime, identity, gateway and memory are all closed. Only SDK, CLI and starter toolkit are open.",
        q6="REFERENCE_ONLY — SDK is Apache-2.0; the interesting control plane is closed and docs-only.",
    ),
    "humanlayer": dict(
        repo="https://github.com/humanlayer/humanlayer",
        docs="https://humanlayer.dev/docs",
        license="Apache-2.0", license_verdict="INTEGRATE",
        evidence_class="A", depth="targeted",
        one_line="Approval and human-oversight layer for autonomous agents.",
        stars=11337, pushed="2026-06-19",
        q2="HumanLayer Cloud is commercial.",
        q6="INTEGRATE — Apache-2.0. GitHub reports NOASSERTION; LICENSE file is verbatim Apache-2.0 with a non-standard title line. Verified manually.",
    ),
    "agent-control": dict(
        license_verdict="unknown", evidence_class="C", depth="recon",
        one_line="Not located: ambiguous name, no identifiable project.",
        q6="Not assessable — project could not be located. Questions reassigned to Omnigent and AWS AgentCore (see recon.md).",
    ),
}


def set_project_field(text: str, field: str, value: str) -> str:
    """Set a field inside the top-level 'project:' block."""
    if value is None:
        return text
    escaped = str(value).replace('"', '\\"')
    rendered = f'"{escaped}"' if re.search(r"[:#]", str(value)) else escaped
    pattern = re.compile(rf"^(  {field}:)(.*)$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda m: f"{m.group(1)} {rendered}", text, count=1)
    # Append inside project block, before the first blank-line-then-'probes:'.
    return text.replace("\nprobes:", f"  {field}: {rendered}\nprobes:", 1)


def set_probe(text: str, pid: str, verdict: str, note: str, evidence: str) -> str:
    """Replace a probe stub with an answered entry."""
    note_escaped = note.replace('"', '\\"')
    block = (
        f"  {pid}:\n"
        f"    verdict: {verdict}\n"
        f'    note: "{note_escaped}"\n'
        f'    evidence: "{evidence}"'
    )
    pattern = re.compile(
        rf"^  {pid}:\n    verdict:.*\n    note:.*\n    evidence:.*$",
        re.MULTILINE,
    )
    if not pattern.search(text):
        return text
    return pattern.sub(block, text, count=1)


def main() -> int:
    updated = 0
    for slug, data in RECON.items():
        path = PROJECTS_DIR / slug / "facts.yaml"
        if not path.exists():
            print(f"  ! missing {slug}")
            continue
        text = path.read_text()

        for field in ("repo", "docs", "license", "license_verdict",
                      "evidence_class", "depth", "one_line"):
            if field in data:
                text = set_project_field(text, field, data[field])
        text = set_project_field(text, "read_on", READ_ON)

        cite = (
            f"{data['repo']} (GitHub API, read {READ_ON}; "
            f"{data['stars']}\u2605, pushed {data['pushed']})"
            if data.get("repo") else
            f"GitHub search and direct repo probing, {READ_ON}: not located"
        )

        # Q1 licence, Q2 enterprise-only, Q6 verdict are recon-answerable.
        if data.get("license"):
            text = set_probe(text, "Q1", "first_class",
                             f"{data['license']}.", cite)
        else:
            text = set_probe(text, "Q1", "unknown",
                             "Project not located; no licence to assess.", cite)

        if data.get("q2"):
            verdict = "absent" if "none found" in data["q2"].lower() else "first_class"
            if not data.get("repo"):
                verdict = "unknown"
            text = set_probe(text, "Q2", verdict, data["q2"], cite)

        text = set_probe(
            text, "Q6",
            "first_class" if data.get("repo") else "unknown",
            data["q6"], cite,
        )
        # No copyleft anywhere in the set — worth recording explicitly.
        if data.get("license"):
            text = set_probe(
                text, "Q5", "absent",
                "No network copyleft. Apache-2.0/MIT only across the whole study.",
                cite,
            )

        path.write_text(text)
        updated += 1
        print(f"  + {slug}")

    print(f"\n{updated} facts.yaml updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
