import { getJson } from "./client";
import type { GraphEdge, GraphNode } from "./types";
export const graphApi = { nodes: () => getJson<GraphNode[]>("/graph/nodes"), node: (id: string) => getJson<GraphNode>(`/graph/nodes/${id}`), edges: () => getJson<GraphEdge[]>("/graph/edges") };
