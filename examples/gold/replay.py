"""Replay frozen, agent-authored gold research; no network or model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.workspace.schemas import WorkspaceApply
from seldon.workspace.service import WorkspaceService, render_markdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/gold-example.db"))
    parser.add_argument("--out", type=Path, default=Path("data/gold-example"))
    args = parser.parse_args()
    engine = make_engine(sqlite_path=args.db)
    create_all(engine)
    factory = make_session_factory(engine)
    source = Path(__file__).parent
    with factory() as db, db.begin():
        state = WorkspaceService(db).start(
            "Where will gold price be in 6 months?",
            "2027-03-28",
            name="Gold: researched snapshot 2026-09-28",
        )
    id = state["scenario"]["id"]
    args.out.mkdir(parents=True, exist_ok=True)
    for filename in ("01-research.json", "02-expand.json", "03-forecast.json"):
        with factory() as db, db.begin():
            service = WorkspaceService(db)
            state = service.export(id)
            payload = json.loads((source / filename).read_text())
            payload.update(scenario_id=id, base_revision=state["revision"])
            service.apply(WorkspaceApply.model_validate(payload))
            (args.out / filename).write_text(json.dumps(payload, indent=2) + "\n")
    with factory() as db:
        state = WorkspaceService(db).export(id)
    (args.out / "workspace.json").write_text(json.dumps(state, indent=2) + "\n")
    (args.out / "report.md").write_text(render_markdown(state))
    engine.dispose()
    print(
        json.dumps(
            {
                "scenario_id": id,
                "database": str(args.db.resolve()),
                "report": str((args.out / "report.md").resolve()),
                "nodes": len(state["nodes"]),
                "edges": len(state["edges"]),
                "prediction_id": state["predictions"][-1]["id"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
