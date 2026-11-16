"""Separate topic and source graphs, persisted as append-only AgentRun events.

Source contains a lock/revision row only; all graph data and old judgments stay in
versioned events. No provider or external network is used by this module.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
import networkx as nx
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from seldon.data.models import AgentRun, Source, ERGNode, KBEntry, Scenario
from .schemas import PerspectiveApply

PHASE = "perspective_graph"
LOCK_ID = str(uuid5(NAMESPACE_URL, "seldon/perspectives/lock"))
KINDS = ("topics", "sources", "claims", "topic_links", "source_links", "claim_links", "assessments")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def stable(kind, key):
    return str(uuid5(NAMESPACE_URL, f"seldon/perspectives/{kind}/{key}"))


def export_graph(db: Session) -> dict:
    maps = {kind: {} for kind in KINDS}
    history = []
    runs = list(db.scalars(select(AgentRun).where(AgentRun.phase == PHASE)))
    runs.sort(key=lambda r: (r.output or {}).get("sequence", 0))
    for run in runs:
        event = run.output or {}
        for kind in KINDS:
            for record in event.get("changes", {}).get(kind, []):
                maps[kind][record["id"]] = record
        history.append({"id": run.id, "sequence": event["sequence"], "agent": run.agent_id, "reason": run.input["reason"], "recorded_at": event["recorded_at"], "counts": {k: len(v) for k, v in event["changes"].items()}})
    data = {k: sorted(v.values(), key=lambda r: r["id"]) for k, v in maps.items()}
    data["revision"] = digest(data)
    data["history"] = history
    data["semantics"] = {"topic_dag": "Parent -> subtopic; acyclic. Related links are undirected cross-links, not causal dependencies.", "sources": "Ownership/affiliations are attributed, dated assertions, not evidence of guilt or automatic unreliability.", "scores": "Subjective, scoped assessments, not calibrated probabilities. Null means unassessed. Fact means an assessor recorded verification; it can be revised. No source score is inherited by a claim or affiliate.", "independence": "Repeated or syndicated claims do not constitute independent corroboration. Check origin_id, derived_from_claim_ids and ownership."}
    return data


def _lock(db):
    # Serialize all writers, including SQLite legacy transaction control.
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    dialect = connection.dialect.name
    insert = pg_insert if dialect == "postgresql" else sqlite_insert
    db.execute(insert(Source).values(id=LOCK_ID, source_type="perspective_registry", name="Topic/source graph revision lock", metadata_={}).on_conflict_do_nothing(index_elements=["id"]))
    db.execute(update(Source).where(Source.id == LOCK_ID).values(updated_at=Source.updated_at))


def apply_graph(db: Session, payload: PerspectiveApply) -> dict:
    from ..service import WorkspaceConflict
    _lock(db)
    with db.begin_nested():
        rid = stable("request", payload.request_id)
        fingerprint = digest(payload.model_dump(mode="json"))
        old = db.get(AgentRun, rid)
        if old:
            if old.input.get("request_hash") != fingerprint:
                raise WorkspaceConflict("Perspective request_id already used for different input")
            return {"revision": old.output["revision"], "run_id": rid, "replayed": True}
        before = export_graph(db)
        if before["revision"] != payload.base_revision:
            raise WorkspaceConflict("Perspective graph changed; export it again and reconcile")
        maps = {kind: {row["id"]: row for row in before[kind]} for kind in KINDS}
        changes = {kind: [] for kind in KINDS}
        now = datetime.now(timezone.utc).isoformat()
        for kind in KINDS:
            seen = set()
            for value in getattr(payload, kind):
                row = value.model_dump(mode="json")
                key = row["id"]
                if key in seen:
                    raise ValueError(f"Duplicate {kind} ID: {key}")
                seen.add(key)
                existing = maps[kind].get(key)
                # Assessments/claims are append-only. A correction is a new claim + supersedes link.
                if existing and kind in {"claims", "assessments"}:
                    comparable = {k: v for k, v in existing.items() if k not in {"recorded_at", "assessor"}}
                    if kind == "claims":
                        for field in ("topic_ids", "evidence_ids"):
                            if not set(comparable[field]) <= set(row[field]):
                                raise ValueError("Claim associations can only be added")
                            comparable[field] = row[field]
                    if row != comparable:
                        raise ValueError(f"{kind} are immutable; add a new record and retain the previous one")
                    if row == {k: v for k, v in existing.items() if k not in {"recorded_at", "assessor"}}:
                        continue
                if kind == "assessments":
                    if value.assessed_at > datetime.now(timezone.utc):
                        raise ValueError("Assessments cannot be dated in the future")
                    row.update(assessor=payload.agent, recorded_at=now)
                if existing == row:
                    continue
                maps[kind][key] = row
                changes[kind].append(row)

        def refs(keys, kind):
            missing = set(keys) - maps[kind].keys()
            if missing:
                raise ValueError(f"Unknown {kind}: {', '.join(sorted(missing))}")

        for topic in maps["topics"].values():
            for key in topic["entity_ids"]:
                if db.get(ERGNode, key) is None:
                    raise ValueError(f"Unknown research entity: {key}")
        for source in maps["sources"].values():
            for entity_id in source.get("entity_ids", []):
                if db.get(ERGNode, entity_id) is None:
                    raise ValueError(f"Unknown research entity: {entity_id}")
        for claim in maps["claims"].values():
            refs(claim["topic_ids"], "topics")
            refs(claim["source_ids"], "sources")
            refs(claim["derived_from_claim_ids"], "claims")
            if claim["id"] in claim["derived_from_claim_ids"]:
                raise ValueError("Claim cannot derive from itself")
            for key in claim["evidence_ids"]:
                if db.get(KBEntry, key) is None:
                    raise ValueError(f"Unknown research evidence: {key}")
        for key, node_kind in (("topic_links", "topics"), ("source_links", "sources"), ("claim_links", "claims")):
            pairs = set()
            for link in maps[key].values():
                refs([link["source"], link["target"]], node_kind)
                if link["source"] == link["target"]:
                    raise ValueError("Self relationships are not allowed")
                endpoints = [link["source"], link["target"]]
                if link["relationship"] in {"related", "contradicts", "supports", "affiliated_with"}:
                    endpoints.sort()
                pair = (*endpoints, link["relationship"], link.get("valid_from"), link.get("valid_until"))
                if pair in pairs:
                    raise ValueError(f"Duplicate relationship in {key}; reuse its ID")
                pairs.add(pair)
        dag = nx.DiGraph()
        dag.add_edges_from((r["source"], r["target"]) for r in maps["topic_links"].values() if r["relationship"] == "subtopic")
        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError("Topic hierarchy must be a DAG; use related for cross-links")
        supersessions = nx.DiGraph()
        supersessions.add_edges_from((r["source"], r["target"]) for r in maps["claim_links"].values() if r["relationship"] == "supersedes")
        if not nx.is_directed_acyclic_graph(supersessions):
            raise ValueError("Claim supersession must be acyclic")
        derivations = nx.DiGraph()
        derivations.add_edges_from((claim["id"], origin) for claim in maps["claims"].values() for origin in claim["derived_from_claim_ids"])
        if not nx.is_directed_acyclic_graph(derivations):
            raise ValueError("Claim derivation must be acyclic")
        for assessment in maps["assessments"].values():
            refs([assessment["target_id"]], "claims" if assessment["target_kind"] == "claim" else "sources")
        if not any(changes.values()):
            return {"revision": before["revision"], "replayed": False, "unchanged": True}
        after = {kind: sorted(rows.values(), key=lambda r: r["id"]) for kind, rows in maps.items()}
        revision = digest(after)
        run = AgentRun(id=rid, agent_id=payload.agent, phase=PHASE, status="completed", input={"request_id": payload.request_id, "request_hash": fingerprint, "reason": payload.reason}, output={"sequence": len(before["history"]) + 1, "recorded_at": now, "changes": changes, "revision": revision})
        db.add(run)
        db.flush()
        return {"revision": revision, "run_id": rid, "replayed": False}


def select_context(graph, *, topic_id=None, source_id=None, depth=4, entity_ids=(), evidence_ids=()):
    if not 0 <= depth <= 12:
        raise ValueError("Depth must be between 0 and 12")
    topics = {t["id"]: t for t in graph["topics"]}
    sources = {s["id"]: s for s in graph["sources"]}
    if topic_id and topic_id not in topics:
        raise KeyError("Topic not found")
    if source_id and source_id not in sources:
        raise KeyError("Source not found")
    selected = set(topics) if not (topic_id or source_id or entity_ids or evidence_ids) else set()
    if topic_id:
        network = nx.Graph()
        network.add_nodes_from(topics)
        network.add_edges_from((e["source"], e["target"]) for e in graph["topic_links"])
        selected.update(nx.single_source_shortest_path_length(network, topic_id, cutoff=depth))
    selected.update(t["id"] for t in topics.values() if set(t["entity_ids"]) & set(entity_ids))
    source_selected = set()
    if source_id:
        network = nx.Graph()
        network.add_nodes_from(sources)
        network.add_edges_from((e["source"], e["target"]) for e in graph["source_links"])
        source_selected.update(nx.single_source_shortest_path_length(network, source_id, cutoff=depth))
    claims = [c for c in graph["claims"] if set(c["topic_ids"]) & selected or set(c["source_ids"]) & source_selected or set(c["evidence_ids"]) & set(evidence_ids)]
    # Counterclaims and corrections must not disappear just because their publisher/topic differs.
    claim_ids = {c["id"] for c in claims}
    network = nx.Graph()
    network.add_nodes_from(c["id"] for c in graph["claims"])
    network.add_edges_from((e["source"], e["target"]) for e in graph["claim_links"])
    for key in list(claim_ids):
        claim_ids.update(nx.node_connected_component(network, key))
    claims = [c for c in graph["claims"] if c["id"] in claim_ids]
    if source_id:
        selected.update(t for c in claims for t in c["topic_ids"])
    source_selected.update(s for c in claims for s in c["source_ids"])
    # Include affiliation/ownership context without importing unrelated claims from those owners.
    for _ in range(0 if source_id else depth):
        extra = {end for e in graph["source_links"] if e["source"] in source_selected or e["target"] in source_selected for end in (e["source"], e["target"])}
        if extra <= source_selected:
            break
        source_selected.update(extra)
    if not (topic_id or source_id or entity_ids or evidence_ids):
        source_selected.update(sources)
    context = {"topics": [t for t in graph["topics"] if t["id"] in selected], "sources": [s for s in graph["sources"] if s["id"] in source_selected], "claims": claims}
    for kind, ids in (("topic_links", selected), ("source_links", source_selected), ("claim_links", claim_ids)):
        context[kind] = [e for e in graph[kind] if e["source"] in ids and e["target"] in ids]
    context["assessments"] = [a for a in graph["assessments"] if a["target_id"] in (claim_ids if a["target_kind"] == "claim" else source_selected)]
    context["revision"] = digest(context)
    context["semantics"] = graph["semantics"]
    return context


def research_context(db, nodes, evidence):
    return select_context(export_graph(db), entity_ids=[n.id for n in nodes], evidence_ids=[e.id for e in evidence]) if nodes or evidence else {}


def index_scenario(db: Session, scenario_id: str, *, agent="evidence-indexer", scope=None) -> dict:
    """Conservative automatic index: reported ≠ verified. Never infer ownership or ideology."""
    from ..knowledge import scoped_graph
    if not db.get(Scenario, scenario_id):
        raise KeyError("Scenario not found")
    _lock(db)
    existing = export_graph(db)
    view = scoped_graph(db, scenario_id, scope, include_perspectives=False)
    topics = {t["id"]: t for t in existing["topics"]}
    sources = {s["id"]: s for s in existing["sources"]}
    claims = {c["id"]: c for c in existing["claims"]}
    payload = {k: [] for k in KINDS}
    eid_topics = {}
    for node in view["nodes"]:
        tid = stable("entity-topic", node.id)
        topic = {"id": tid, "name": node.name, "description": node.description, "entity_ids": [node.id], "tags": node.tags or []}
        if tid not in topics:
            payload["topics"].append(topic)
        for eid in node.kb_entry_ids or []:
            eid_topics.setdefault(eid, []).append(tid)
    root = stable("scenario-topic", scenario_id)
    scenario = db.get(Scenario, scenario_id)
    if root not in topics:
        payload["topics"].append({"id": root, "name": scenario.name, "description": scenario.target_question})
    links = {e["id"] for e in existing["topic_links"]}
    for node in view["nodes"]:
        tid = stable("entity-topic", node.id)
        lid = stable("topic-link", f"{root}/{tid}")
        if lid not in links:
            payload["topic_links"].append({"id": lid, "source": root, "target": tid, "relationship": "subtopic", "rationale": "Research question includes this entity; this is not a causal edge."})
    for e in view["evidence"]:
        # One proposition snapshot can appear under many topics/questions. Evidence edits create a new claim.
        evidence_topics = sorted(set(eid_topics.get(e.id, []) + [root]))
        key = digest([e.id, e.version, e.content, e.source_url])
        cid = stable("evidence-claim", key)
        if cid in claims:
            prior = claims[cid]
            merged = sorted(set(prior["topic_ids"] + evidence_topics))
            if merged != prior["topic_ids"]:
                payload["claims"].append({**prior, "topic_ids": merged})
            continue
        sid = stable("source-name", e.source_name.casefold().strip())
        if sid not in sources:
            source = {"id": sid, "name": e.source_name[:255], "kind": "unknown", "description": "Imported source label; author/publisher identity and affiliations need verification."}
            payload["sources"].append(source)
            sources[sid] = source
        published = e.valid_from.replace(tzinfo=e.valid_from.tzinfo or timezone.utc).isoformat() if e.valid_from else None
        retrieved = (e.perspective_tags or {}).get("retrieved_at") or e.created_at.replace(tzinfo=e.created_at.tzinfo or timezone.utc).isoformat()
        reported = bool((e.source_url or "").startswith(("https://", "http://"))) and e.source_type != "assumption"
        payload["claims"].append({"id": cid, "topic_ids": evidence_topics, "statement": e.content, "source_ids": [sid], "source_url": e.source_url, "published_at": published, "retrieved_at": retrieved, "kind": "reported" if reported else "assumption", "evidence_ids": [e.id], "origin_id": e.source_url or f"evidence:{e.id}", "import_note": "Imported saved evidence, not newly verified. Original confidence remains in the research evidence; no calibrated trust score or fact label was inferred."})
        # Retain older evidence versions and make replacement explicit, without inventing a truth verdict.
        for old in claims.values():
            if e.id in old["evidence_ids"] and (old["statement"] != e.content or old["source_url"] != e.source_url):
                payload["claim_links"].append({"id": stable("supersedes", f"{cid}/{old['id']}"), "source": cid, "target": old["id"], "relationship": "supersedes", "rationale": "Research evidence was revised. Earlier attributed statement remains available."})
    if not any(payload.values()):
        return {"revision": existing["revision"], "unchanged": True}
    return apply_graph(db, PerspectiveApply.model_validate({**payload, "request_id": f"index-{scenario_id}-{digest(payload)[:40]}", "base_revision": existing["revision"], "agent": agent, "reason": "Index saved research as attributed, unverified claims; retain source/claim judgments separately."}))
