"""
Run the Supervisor Agent on a JSON file and print the decision JSON.

    python scripts/run_supervisor.py sample_incident.json
    python scripts/run_supervisor.py sample_incident.json --mode gemini
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from kavach.agents.supervisor import SupervisorAgentClient  # noqa: E402
from kavach.schemas.supervisor import SupervisorIncidentInput  # noqa: E402
from kavach.services.supervisor.orchestrator import SupervisorOrchestrator  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Kavach Supervisor Agent (Process 3.0)")
    parser.add_argument("input_json", help="Path to the incident JSON file")
    parser.add_argument("--mode", choices=["mock", "gemini"], help="Override KAVACH_LLM_MODE")
    args = parser.parse_args()

    if args.mode:
        os.environ["KAVACH_LLM_MODE"] = args.mode

    raw = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    incident = SupervisorIncidentInput.model_validate(raw)

    client = SupervisorAgentClient()
    orchestrator = SupervisorOrchestrator(client)
    result = orchestrator.evaluate_incident(incident)

    print(json.dumps(result.model_dump(mode="json"), indent=2))
    print(f"\n# llm_mode={client.llm_mode} model={client.model_name if client.llm_mode == 'gemini' else '-'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
