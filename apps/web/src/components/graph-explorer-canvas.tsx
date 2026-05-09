"use client";

import ReactFlow, { Background, Controls, MiniMap, MarkerType, type Edge, type Node } from "reactflow";
import type { GraphEdge, GraphNode } from "../lib/api/types";

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId?: string;
  selectedEdgeId?: string;
  overlay?: "confidence" | "strength" | "importance" | "instability" | "scenario";
  layout?: "radial" | "grid" | "layers";
};

const typeColors: Record<string, string> = {
  entity: "#60a5fa",
  event: "#fb923c",
  topic: "#a78bfa",
  metric: "#22c55e",
  policy: "#fbbf24",
  actor: "#f472b6",
};

function nodePosition(index: number, total: number, layout: Props["layout"] = "radial", node?: GraphNode) {
  if (layout === "grid") {
    const columns = Math.ceil(Math.sqrt(Math.max(total, 1)));
    return { x: (index % columns) * 220, y: Math.floor(index / columns) * 150 };
  }
  if (layout === "layers") {
    const layerOrder = ["actor", "policy", "event", "topic", "metric", "entity"];
    const layer = Math.max(0, layerOrder.indexOf(node?.type ?? "entity"));
    return { x: layer * 240, y: (index % Math.max(4, Math.ceil(total / 3))) * 135 };
  }
  const radius = Math.max(170, Math.min(900, total * 28));
  const angle = (index / Math.max(total, 1)) * Math.PI * 2;
  return { x: Math.round(Math.cos(angle) * radius + radius + 80), y: Math.round(Math.sin(angle) * radius + radius + 40) };
}

function nodeBorder(node: GraphNode, selected?: boolean, overlay?: Props["overlay"]) {
  if (selected) return "3px solid #f8fafc";
  if (overlay === "instability") return `2px solid rgba(248, 113, 113, ${Math.max(0.25, 1 - node.stability_score)})`;
  if (overlay === "importance") return `2px solid rgba(96, 165, 250, ${Math.max(0.25, node.importance_score)})`;
  return `2px solid ${typeColors[node.type] ?? "#94a3b8"}`;
}

function edgeColor(edge: GraphEdge, overlay?: Props["overlay"]) {
  if (overlay === "confidence") return edge.confidence < 0.4 ? "#f87171" : edge.confidence < 0.7 ? "#fbbf24" : "#22c55e";
  if (overlay === "strength") return "#a78bfa";
  if (edge.direction === "positive") return "#22c55e";
  if (edge.direction === "negative") return "#f87171";
  return "#60a5fa";
}

export function GraphExplorerCanvas({ nodes, edges, selectedNodeId, selectedEdgeId, overlay = "confidence", layout = "radial" }: Props) {
  const dense = nodes.length > 40;
  const rfNodes: Node[] = nodes.map((node, index) => ({
    id: node.id,
    position: nodePosition(index, nodes.length, layout, node),
    data: { label: `${node.name}\n${node.type}` },
    style: {
      width: (dense ? 122 : 150) + Math.round(node.importance_score * (dense ? 24 : 42)),
      borderRadius: 18,
      padding: 12,
      color: "#eef2ff",
      background: "rgba(15, 23, 42, .92)",
      border: nodeBorder(node, node.id === selectedNodeId, overlay),
      boxShadow: node.id === selectedNodeId ? "0 0 0 6px rgba(96, 165, 250, .18)" : "0 10px 30px rgba(0,0,0,.25)",
      whiteSpace: "pre-line",
      fontSize: dense ? 10 : 12,
    },
  }));

  const rfEdges: Edge[] = edges.map((edge) => ({
    id: edge.id,
    source: edge.source_node_id,
    target: edge.target_node_id,
    label: `${edge.relationship_type} · ${Math.round(edge.confidence * 100)}%`,
    animated: edge.id === selectedEdgeId,
    markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor(edge, overlay) },
    style: {
      stroke: edgeColor(edge, overlay),
      strokeOpacity: Math.max(0.25, overlay === "confidence" ? edge.confidence : edge.strength),
      strokeWidth: 1 + Math.round(edge.strength * 5),
    },
    labelStyle: { fill: "#cbd5e1", fontSize: 11 },
    labelBgStyle: { fill: "rgba(7,10,18,.82)" },
  }));

  return <div className="graph-canvas" data-testid="reactflow-graph-canvas">
    <ReactFlow nodes={rfNodes} edges={rfEdges} fitView minZoom={0.2} maxZoom={1.8} nodesDraggable={false} nodesConnectable={false} elementsSelectable>
      <MiniMap pannable zoomable nodeColor={(node) => typeColors[String(node.data?.label || "").split("\n").at(-1) ?? ""] ?? "#64748b"} />
      <Controls showInteractive={false} />
      <Background color="rgba(148,163,184,.22)" gap={24} />
    </ReactFlow>
  </div>;
}
