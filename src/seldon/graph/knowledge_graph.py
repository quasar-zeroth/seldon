"""KnowledgeGraph: NetworkX-based graph for entity and relation tracking."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

console = Console(stderr=True)

ENTITY_TYPES = {
    "Topic", "Article", "Ticker", "Prediction", "Bet",
    "Trade", "Source", "Company", "Sector", "Person", "Event",
}


class KnowledgeGraph:
    """Directed graph of entities and relations using NetworkX."""

    def __init__(self, path: str | Path = "data/knowledge_graph.json"):
        try:
            import networkx as nx
            self._nx = nx
        except ImportError:
            raise ImportError("networkx is required: uv add networkx")

        self.path = Path(path)
        self.graph: Any  # nx.DiGraph
        self.load()

    def load(self):
        """Load graph from JSON, or create a new empty graph."""
        if self.path.exists():
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.graph = self._nx.node_link_graph(
                    data,
                    directed=True,
                    multigraph=False,
                    edges="edges",
                )
                console.print(
                    f"[dim]Loaded knowledge graph: {self.graph.number_of_nodes()} nodes, "
                    f"{self.graph.number_of_edges()} edges[/dim]"
                )
                return
            except Exception as e:
                console.print(f"[yellow]Could not load graph from {self.path}: {e} — starting fresh[/yellow]")
        self.graph = self._nx.DiGraph()

    def save(self):
        """Serialize graph to JSON."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self._nx.node_link_data(self.graph, edges="edges")
        with open(self.path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def add_entity(
        self,
        entity_type: str,
        entity_id: str,
        **attrs,
    ) -> str:
        """
        Add a node to the graph.
        entity_type: one of ENTITY_TYPES
        entity_id: unique identifier for this entity
        **attrs: additional node attributes

        Returns the node ID used.
        """
        if entity_type not in ENTITY_TYPES:
            console.print(f"[yellow]Unknown entity type: {entity_type}[/yellow]")

        node_id = f"{entity_type}:{entity_id}"
        if self.graph.has_node(node_id):
            # Update attributes
            self.graph.nodes[node_id].update(attrs)
            self.graph.nodes[node_id]["entity_type"] = entity_type
            self.graph.nodes[node_id]["entity_id"] = entity_id
        else:
            self.graph.add_node(
                node_id,
                entity_type=entity_type,
                entity_id=entity_id,
                **attrs,
            )
        return node_id

    def add_relation(
        self,
        source: str,
        target: str,
        relation: str,
        **attrs,
    ):
        """
        Add a directed edge from source to target with a relation label.
        source/target should be node IDs (as returned by add_entity).
        """
        # Auto-create nodes if they don't exist
        for node in (source, target):
            if not self.graph.has_node(node):
                parts = node.split(":", 1)
                entity_type = parts[0] if len(parts) == 2 else "Unknown"
                entity_id = parts[1] if len(parts) == 2 else node
                self.graph.add_node(node, entity_type=entity_type, entity_id=entity_id)

        self.graph.add_edge(source, target, relation=relation, **attrs)

    def query_related(
        self,
        entity_id: str,
        relation: Optional[str] = None,
        depth: int = 2,
    ) -> list[dict]:
        """
        Find nodes related to entity_id within given depth.
        entity_id can be a full node id ("Type:id") or just the entity_id part.
        """
        # Resolve the node ID
        node_id = entity_id
        if not self.graph.has_node(node_id):
            # Try finding by entity_id attribute
            for n, data in self.graph.nodes(data=True):
                if data.get("entity_id") == entity_id:
                    node_id = n
                    break
            else:
                return []

        related = []
        visited = {node_id}

        # BFS up to depth
        frontier = [(node_id, 0)]
        while frontier:
            current, d = frontier.pop(0)
            if d >= depth:
                continue
            # Outgoing edges
            for _, neighbor, edge_data in self.graph.out_edges(current, data=True):
                if relation and edge_data.get("relation") != relation:
                    continue
                if neighbor not in visited:
                    visited.add(neighbor)
                    node_data = dict(self.graph.nodes[neighbor])
                    node_data["node_id"] = neighbor
                    node_data["relation_from_source"] = edge_data.get("relation", "")
                    related.append(node_data)
                    frontier.append((neighbor, d + 1))
            # Incoming edges
            for neighbor, _, edge_data in self.graph.in_edges(current, data=True):
                if relation and edge_data.get("relation") != relation:
                    continue
                if neighbor not in visited:
                    visited.add(neighbor)
                    node_data = dict(self.graph.nodes[neighbor])
                    node_data["node_id"] = neighbor
                    node_data["relation_to_source"] = edge_data.get("relation", "")
                    related.append(node_data)
                    frontier.append((neighbor, d + 1))

        return related

    def search(self, query: str) -> list[dict]:
        """
        Search for entities by substring match in node ID, entity_id, or any string attribute.
        Returns list of matching node dicts.
        """
        query_lower = query.lower()
        results = []
        for node_id, data in self.graph.nodes(data=True):
            # Check node_id
            if query_lower in node_id.lower():
                results.append({"node_id": node_id, **data})
                continue
            # Check all string attributes
            matched = False
            for val in data.values():
                if isinstance(val, str) and query_lower in val.lower():
                    matched = True
                    break
            if matched:
                results.append({"node_id": node_id, **data})
        return results

    def get_stats(self) -> dict:
        """Return entity counts by type and relation counts."""
        type_counts: dict[str, int] = {}
        relation_counts: dict[str, int] = {}

        for _, data in self.graph.nodes(data=True):
            et = data.get("entity_type", "Unknown")
            type_counts[et] = type_counts.get(et, 0) + 1

        for _, _, data in self.graph.edges(data=True):
            rel = data.get("relation", "unknown")
            relation_counts[rel] = relation_counts.get(rel, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "entity_counts": type_counts,
            "relation_counts": relation_counts,
        }

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get a single node's data."""
        if self.graph.has_node(node_id):
            return {"node_id": node_id, **dict(self.graph.nodes[node_id])}
        return None

    def export(self) -> dict:
        """Export full graph as dict."""
        return self._nx.node_link_data(self.graph, edges="edges")
