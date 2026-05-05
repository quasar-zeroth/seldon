# Foresight Engine — Multi-Agent Probabilistic Scenario Prediction System

## Architectural Plan & Design Document

---

## 1. System Philosophy

The core idea: break the massive problem of "predicting the future" into many small, bounded, composable tasks — each handled by a lightweight agent that defaults to a fast model (Haiku/Sonnet-class) and only escalates to a reasoning-heavy model (Opus-class) when the task genuinely demands it. The system should feel like a research team, not a monolith: each agent has a clear job, a clear input contract, and a clear output contract.

Every piece of data in the system is **temporally tagged** (when was it created/updated), **perspectivally tagged** (what lens was used: bull/bear, left/right, pro-west/non-west, etc.), and **provenance-tracked** (where did it come from, what agent produced it, what sources informed it).

---

## 2. Data Architecture — The Backbone

Before discussing agents, we need to nail down how data lives, because every agent reads from and writes to shared structures. Bad data architecture kills multi-agent systems.

### 2.1 Knowledge Base (KB)

**Purpose:** Persistent, versioned, semantically searchable store of all facts, observations, and summaries the system has gathered.

**Structure — Each KB Entry:**
```
KBEntry {
  id:                 string (uuid)
  content:            string (the actual information — a summarized fact or observation)
  content_embedding:  float[] (vector embedding for semantic search)
  source_type:        enum [user_input, web_search, news_article, forum, research_paper, api_data, feedback_correction]
  source_url:         string | null
  source_name:        string (e.g., "Reuters", "Reddit r/economics", "User")
  original_snippet:   string (the raw text this was derived from, for auditability)
  
  created_at:         datetime
  updated_at:         datetime
  valid_from:         datetime | null (when did this fact become true in the real world)
  valid_until:        datetime | null (when did this fact stop being true, if known)
  
  topics:             string[] (tags like "gold", "fed_policy", "inflation")
  entities:           string[] (specific entities: "Federal Reserve", "China", "COMEX")
  
  perspective_tags:   {
    sentiment:         float [-1.0 to 1.0] (bearish to bullish)
    political_lean:    float [-1.0 to 1.0] (left to right)
    geopolitical_lens: string | null (e.g., "pro-western", "global-south", "neutral")
    confidence:        float [0.0 to 1.0] (how reliable is this source generally)
  }
  
  scenario_ids:       string[] (which prediction scenarios reference this entry)
  superseded_by:      string | null (id of newer entry that replaces this one)
  version:            int
}
```

**Storage Recommendation:**
- **Primary store:** SQLite or PostgreSQL with a JSON column for flexible fields. Keep it simple early — a single `kb_entries` table.
- **Vector index:** A separate vector store (could be a simple FAISS index on disk, or Chroma/Qdrant if you want something turnkey). Maps `id → embedding` for semantic search.
- **File-based mirror (optional):** For human readability, maintain a folder of markdown files organized by topic. Each file is auto-generated from the DB. This is a *read-only view*, not the source of truth.

**Key Operations the KB Must Support:**
1. **Semantic search:** "Find entries similar to X" → vector similarity query
2. **Temporal filtering:** "What was known about gold prices between Jan–Mar 2025?" → date range query
3. **Delta detection:** "What's new since last time we looked at topic Y?" → compare `updated_at` against last query timestamp
4. **Provenance chain:** "Where did this fact come from?" → follow `source_url`, `source_type`
5. **Supersession tracking:** "Is this fact still current?" → check `superseded_by`
6. **Cross-scenario lookup:** "What entries are shared between the gold and recession scenarios?" → query on `scenario_ids`
7. **Perspective filtering:** "Show me only bearish takes on inflation" → filter on `perspective_tags.sentiment < -0.3`

**Additional Important KB Features:**
- **Contradiction detection:** When new info contradicts existing entries, flag both and let the Synthesis agent resolve it. Store contradictions explicitly — they're often more informative than agreements.
- **Decay scoring:** Facts age. A news article from 3 days ago is more relevant than one from 6 months ago for most fast-moving topics. Apply a configurable time-decay weight when retrieving entries. (Not deleting — just ranking.)
- **Confidence aggregation:** If 5 sources say X and 1 says not-X, the KB should surface that distribution, not just majority-vote.
- **Audit log:** Every write operation (create, update, supersede) is logged with timestamp, agent_id, and reason.

### 2.2 Entity-Relationship Graph (ERG)

**Purpose:** Stores extracted entities/events/topics and their causal/correlational relationships.

**Structure — Nodes:**
```
ERGNode {
  id:                 string (uuid)
  name:               string (e.g., "US Federal Funds Rate")
  type:               enum [entity, event, topic, metric, policy, actor]
  description:        string (1–3 sentence summary of what this node represents)
  
  current_state:      string | null (brief description of current status)
  state_updated_at:   datetime
  
  kb_entry_ids:       string[] (links to supporting KB entries)
  scenario_ids:       string[] (which scenarios use this node)
  
  created_at:         datetime
  updated_at:         datetime
  
  stability_score:    float [0.0 to 1.0] (how stable is this node's state — computed during prediction)
  importance_score:   float [0.0 to 1.0] (how many other nodes depend on it)
}
```

**Structure — Edges:**
```
ERGEdge {
  id:                 string (uuid)
  source_node_id:     string
  target_node_id:     string
  
  relationship_type:  enum [causes, correlates_with, depends_on, constrains, enables, opposes, amplifies, dampens]
  
  description:        string (SPECIFIC: "If the Fed raises rates by 50bps, gold prices tend to drop 3-8% within 2 weeks")
  
  strength:           float [0.0 to 1.0] (how strong is this relationship)
  confidence:         float [0.0 to 1.0] (how confident are we this relationship exists)
  lag:                string | null (time delay: "2-4 weeks", "immediate", "6-12 months")
  direction:          enum [positive, negative, complex] (does source increase → target increase, decrease, or it's complicated)
  
  evidence_kb_ids:    string[] (KB entries that support this edge)
  
  created_at:         datetime
  updated_at:         datetime
  scenario_ids:       string[]
}
```

**Storage:**
- A relational DB works fine (nodes table + edges table). You do not need a graph database unless the graph exceeds ~100k nodes, which is unlikely for most scenarios.
- Export to NetworkX (Python) or similar for traversal algorithms (DFS/BFS for prediction propagation).
- Persist graph snapshots as versioned JSON files so you can diff graphs over time.

**Graph Reuse Across Scenarios:**
- Nodes and edges have `scenario_ids[]`. A node like "US Inflation Rate" might belong to both the "gold-price" and "recession" scenarios.
- When creating a new scenario, the system queries existing nodes/edges and suggests: "These 14 nodes and 23 edges from your gold-price graph are relevant to your recession scenario. Import them?"
- Imported nodes maintain links to their origin scenario — updates propagate.

### 2.3 Scenario Predictions Store

```
Scenario {
  id:                 string
  name:               string (e.g., "Gold Price 6-Month Outlook")
  description:        string
  created_at:         datetime
  updated_at:         datetime
  status:             enum [active, paused, archived, completed]
  
  target_question:    string ("What will gold price be in 6 months?")
  time_horizon:       string ("6 months")
  
  erg_snapshot_id:     string (version of the graph used)
  kb_snapshot_at:      datetime (KB state at time of prediction)
}

ScenarioPrediction {
  id:                 string
  scenario_id:        string
  created_at:         datetime (when this prediction was generated)
  
  predicted_outcomes: [
    {
      outcome:         string ("Gold rises to $2800–3000/oz")
      probability:     float [0.0 to 1.0]
      confidence:      float [0.0 to 1.0] (how confident is the system in its own probability estimate)
      key_drivers:     string[] (node_ids that most influence this outcome)
      key_assumptions: string[] (what must be true for this to happen)
      stability:       enum [stable, moderately_stable, unstable]
      reasoning_trace: string (step-by-step reasoning)
    }
  ]
  
  traversal_log:      object (full DFS/BFS traversal data — which nodes were visited, what was predicted at each)
}

FeedbackEntry {
  id:                 string
  scenario_id:        string
  prediction_id:      string
  
  actual_outcome:     string (what actually happened)
  recorded_at:        datetime
  comparison:         string (how prediction compared to reality)
  
  missed_factors:     string[] (things the system didn't account for)
  graph_corrections:  [ { action: "add_node" | "add_edge" | "modify_edge" | "remove_edge", details: object } ]
  lessons_learned:    string
}
```

---

## 3. Agent Architecture — Detailed Breakdown

### Design Principle: The "Coordinator + Specialists" Pattern

Each major phase (Context Gathering, Extraction, Graph Building, Prediction, Feedback) has:
- A **Coordinator Agent** (Sonnet-class) that manages the workflow, decides what to do next, and orchestrates sub-agents.
- Multiple **Specialist Agents** (Haiku-class by default, escalate to Sonnet/Opus when needed) that do one bounded task.

Escalation rule: A specialist flags when it's uncertain (confidence < threshold), encounters contradictions, or the task is inherently complex (multi-step reasoning, nuanced judgment). The coordinator then re-routes to a stronger model.

---

### PHASE 1: Context Gathering

#### Agent 1.1 — Query Decomposer
- **Model:** Haiku (fast, this is pattern-matching)
- **Input:** User's original query/context + any user-supplied documents
- **Job:** Break the user's question into:
  - Primary topic (e.g., "gold price prediction")
  - Related sub-topics to investigate (e.g., "Fed monetary policy", "USD strength", "geopolitical risk", "central bank gold buying", "mining supply", "ETF flows")
  - Temporal scope (what time period matters)
  - User-specified constraints (e.g., "only use my provided data", "focus on technical analysis")
- **Output:** A structured search plan — a list of 5–20 sub-queries to investigate
- **Escalation:** If the topic is highly ambiguous or the user's question is vague, escalate to Sonnet for better decomposition

#### Agent 1.2 — Information Retriever
- **Model:** Haiku (it's just calling tools and doing light filtering)
- **Input:** One sub-query from the search plan
- **Job:** Execute web searches, news API calls, forum scrapes, etc. For each sub-query:
  - Run 2–3 search variations
  - Fetch top N results
  - Do a quick relevance check (is this actually about what we're looking for?)
  - Extract the key content (strip boilerplate, ads, navigation)
- **Output:** Raw retrieved documents with metadata (source, date, URL)
- **Note:** Run multiple instances in parallel (one per sub-query) for speed. This agent is stateless and idempotent.

#### Agent 1.3 — Information Summarizer
- **Model:** Sonnet (summarization quality matters a lot)
- **Input:** One raw retrieved document + the original query context
- **Job:**
  - Summarize the document into discrete factual claims (not a paragraph summary — bullet-point facts)
  - Tag each fact with: date relevance, entities mentioned, sentiment/perspective
  - Flag any claims that seem surprising, contradictory to common knowledge, or particularly important
- **Output:** A list of structured `KBEntryCandidate` objects
- **Escalation:** If the document is long, technical, or contains nuanced arguments (e.g., a research paper), escalate to Opus for deeper comprehension

#### Agent 1.4 — Deduplication & Delta Detector
- **Model:** Haiku (mostly embedding comparison + simple logic)
- **Input:** List of `KBEntryCandidate` objects + existing KB entries (retrieved via semantic search)
- **Job:**
  - For each candidate, search the KB for semantically similar entries (cosine similarity > 0.85)
  - If near-duplicate found: skip, or if the candidate adds nuance/updates the existing entry, mark as an update
  - If contradiction found: flag both entries for review
  - If genuinely new: mark for insertion
- **Output:** Three lists: `new_entries`, `updates_to_existing`, `contradictions_detected`
- **Escalation:** Contradictions are sent to Sonnet for resolution — it decides which is more likely correct and why

#### Agent 1.5 — KB Writer
- **Model:** None (this is pure code, no LLM needed)
- **Input:** Approved new entries and updates
- **Job:** Write to the KB database, update embeddings, update the vector index, log all changes to the audit trail

#### Agent 1.0 — Context Gathering Coordinator
- **Model:** Sonnet
- **Input:** User query + current state of the KB for relevant topics
- **Job:** Orchestrates agents 1.1–1.5 in a loop:
  1. Call Query Decomposer to generate search plan
  2. Dispatch Information Retrievers (parallel)
  3. Collect results, send to Summarizers (parallel)
  4. Run Dedup/Delta detection
  5. Write to KB
  6. **Decide: do we have enough?** Check coverage: are all sub-topics covered? Are there obvious gaps? Did any retrieved info reveal new sub-topics we should investigate?
  7. If gaps remain → generate new sub-queries, go to step 2
  8. If sufficient → signal completion, pass control to Phase 2
- **Termination criteria:**
  - Diminishing returns: last round of searches added < 5% new information
  - Maximum rounds reached (configurable, default 3–5)
  - All sub-topics have at least N entries each

---

### PHASE 2: Entity, Event & Topic Extraction

#### Agent 2.1 — Entity Extractor
- **Model:** Haiku
- **Input:** A batch of KB entries (5–10 at a time)
- **Job:** Extract named entities: organizations, people, countries, financial instruments, policies, technologies, etc. Output structured entity objects with type and brief description.
- **Output:** List of candidate `ERGNode` objects (type = entity)

#### Agent 2.2 — Event Extractor
- **Model:** Haiku
- **Input:** Same KB entry batches
- **Job:** Extract events: things that happened, are happening, or might happen. Include temporal markers (past, ongoing, scheduled, speculative).
- **Output:** List of candidate `ERGNode` objects (type = event)

#### Agent 2.3 — Topic & Theme Extractor
- **Model:** Sonnet (themes require more abstract reasoning)
- **Input:** The full set of KB entries for this scenario + the user's original question
- **Job:** Identify higher-level themes and macro-topics that cut across individual facts. Examples: "deglobalization trend", "AI disruption in labor markets", "central bank credibility erosion"
- **Output:** List of candidate `ERGNode` objects (type = topic)

#### Agent 2.4 — Node Deduplicator & Merger
- **Model:** Haiku
- **Input:** All candidate nodes from 2.1, 2.2, 2.3 + existing ERG nodes
- **Job:** Merge duplicates (e.g., "The Fed" and "Federal Reserve" and "US Federal Reserve" → one node). Link new nodes to existing ones where they already exist.
- **Output:** Deduplicated node list, with `is_new` flags

#### Agent 2.0 — Extraction Coordinator
- **Model:** Sonnet
- **Input:** KB entries + existing ERG
- **Job:** Runs extractors, merges results, then does a **completeness check**: "Given the user's question about gold prices, are we missing any obviously important entities/events/topics?" If yes, generates targeted queries for Phase 1 to fill gaps. This is where the Phase 1 → Phase 2 → Phase 1 loop happens.

---

### PHASE 3: Relationship Graph Construction

#### Agent 3.1 — Pairwise Relationship Detector
- **Model:** Sonnet (relationship detection needs decent reasoning)
- **Input:** A pair of ERG nodes + relevant KB entries for both
- **Job:** Determine:
  - Is there a meaningful relationship between these two nodes?
  - If yes: what type? (causes, correlates, depends_on, constrains, enables, opposes, amplifies, dampens)
  - How strong is it? (0.0–1.0)
  - What's the specific mechanism? (This is the crucial part — must be concrete, not vague)
  - What's the time lag?
  - What's the direction? (A↑ → B↑, or A↑ → B↓, or complex)
- **Output:** A candidate `ERGEdge` or null if no meaningful relationship
- **Scaling concern:** For N nodes, there are N×(N-1)/2 possible pairs. For 50 nodes that's 1,225 pairs. Mitigation:
  - First pass: Haiku does a quick "is there any plausible relationship?" filter. This eliminates ~70–80% of pairs.
  - Second pass: Sonnet does detailed analysis on the remaining pairs.
- **Escalation:** For complex, multi-causal relationships (e.g., "How does China's Belt and Road Initiative affect gold prices?"), escalate to Opus.

#### Agent 3.2 — Graph Consistency Checker
- **Model:** Sonnet
- **Input:** The full graph (nodes + edges)
- **Job:** Check for:
  - Contradictory edges (A causes B, but also A opposes B)
  - Missing obvious relationships (two nodes that clearly should be connected but aren't)
  - Circular dependencies that don't make sense
  - Orphan nodes (connected to nothing — should they be removed or connected?)
  - Overly dense clusters vs. disconnected sub-graphs
- **Output:** A list of corrections and suggestions

#### Agent 3.3 — Importance Scorer
- **Model:** Haiku (this is mostly graph-algorithm work)
- **Input:** The full graph
- **Job:** Compute node importance (similar to PageRank — nodes with many important incoming/outgoing edges rank higher). Also compute edge importance.
- **Output:** Updated `importance_score` on all nodes

#### Agent 3.0 — Graph Construction Coordinator
- **Model:** Sonnet
- **Job:** Orchestrates 3.1–3.3. After graph is built, checks if new nodes are implied by discovered relationships (e.g., "We found that node A and node B are both influenced by something we haven't explicitly represented — should we add a new node?"). If yes → loop back to Phase 2 → Phase 1.

---

### THE CONVERGENCE LOOP (Phases 1–3)

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│  User Query                                         │
│       │                                             │
│       ▼                                             │
│  ┌─────────────────┐                                │
│  │  Phase 1:       │◄──── new sub-queries ──────┐   │
│  │  Context        │                            │   │
│  │  Gathering      │                            │   │
│  └───────┬─────────┘                            │   │
│          │ KB entries                            │   │
│          ▼                                      │   │
│  ┌─────────────────┐                            │   │
│  │  Phase 2:       │                            │   │
│  │  Entity/Event   │──── gaps found? ───────────┘   │
│  │  Extraction     │                            │   │
│  └───────┬─────────┘                            │   │
│          │ ERG nodes                            │   │
│          ▼                                      │   │
│  ┌─────────────────┐                            │   │
│  │  Phase 3:       │                            │   │
│  │  Relationship   │──── new nodes needed? ─────┘   │
│  │  Graph Building │                                │
│  └───────┬─────────┘                                │
│          │                                          │
│          ▼                                          │
│  Convergence check:                                 │
│  - New nodes added this round < threshold?          │
│  - Max iterations reached?                          │
│  - Coverage score > target?                         │
│          │                                          │
│      YES ▼                                          │
│  ┌─────────────────┐                                │
│  │  Phase 4:       │                                │
│  │  Prediction     │                                │
│  └─────────────────┘                                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Convergence Agent (Sonnet):**
- Runs after each full loop of Phases 1–3
- Tracks: number of new nodes added, number of new edges added, number of new KB entries, number of contradictions resolved
- Decides: continue looping or proceed to prediction
- Configurable: `max_iterations`, `min_new_info_threshold`, `coverage_target`

---

### PHASE 4: Prediction Engine

This is the most intellectually complex phase. It needs careful decomposition.

#### Agent 4.1 — Node State Predictor
- **Model:** Sonnet (default), Opus (for high-importance nodes or complex ones)
- **Input:** One ERG node + its KB entries + its immediate neighbors in the graph + the scenario's target question
- **Job:** For this node, predict what changes could happen to it in the scenario's time horizon. Output 2–5 possible state changes, each with a probability.
- **Output:**
  ```
  NodePrediction {
    node_id: string
    predictions: [
      {
        predicted_change:  string ("Fed raises rates by 25bps")
        probability:       float
        reasoning:         string
        time_frame:        string ("next 3 months")
      }
    ]
  }
  ```
- **Escalation rule:** If `node.importance_score > 0.7`, use Opus. If the node has > 5 incoming edges (highly connected), use Opus.

#### Agent 4.2 — Graph Traversal Simulator
- **Model:** Sonnet
- **Input:** The full ERG + all NodePredictions from 4.1 + a "starting condition" (one specific predicted change at one node)
- **Job:** Simulate a DFS/BFS traversal starting from a changed node:
  1. Start: "Node A changes to state X"
  2. For each outgoing edge from A: use the edge's description to predict the downstream effect on the target node. Combine with the target node's own independent predictions.
  3. Continue traversal — propagate effects through the graph.
  4. At each step, track the cumulative probability (multiply along the chain, with appropriate adjustments for independence assumptions).
  5. Detect **instability**: if a predicted change at node B would cause effects that loop back and contradict the original change at node A, flag this path as unstable.
  6. Detect **convergence**: if multiple independent paths lead to the same predicted state for a node, that prediction is more robust.
- **Output:** A `TraversalResult` — a tree of predicted cascading effects with probabilities and stability flags.
- **Note:** This agent should be called many times — once per "starting condition" (each node × each predicted change). This is the combinatorial core.

#### Agent 4.3 — Instability Analyzer
- **Model:** Opus (this requires deep reasoning about feedback loops and contradictions)
- **Input:** All traversal results flagged as unstable
- **Job:** Analyze why the instability exists:
  - Is it a genuine feedback loop in the real world? (e.g., "stock prices drop → panic selling → prices drop more")
  - Is it a modeling error? (an edge that's too strong, or a missing dampening mechanism)
  - What would resolve the instability? (a new node that acts as a stabilizer?)
- **Output:** Revised predictions for unstable paths, or graph corrections

#### Agent 4.4 — Scenario Synthesizer
- **Model:** Opus (synthesis of many prediction threads into coherent scenarios requires top-tier reasoning)
- **Input:** All traversal results + instability analysis + the original target question
- **Job:** Cluster the many traversal results into 3–7 coherent scenarios:
  - Each scenario is a consistent, plausible "story of the future"
  - Assign overall probability to each scenario
  - Identify the key branching points (which nodes' outcomes determine which scenario unfolds)
  - Identify key assumptions for each scenario
  - Identify which scenarios are stable vs. fragile
  - Rank scenarios by probability and by impact
- **Output:** The final `ScenarioPrediction` object (written to the Predictions Store)
- **Critical quality check:** Do the probabilities of all scenarios sum to ~1.0? If not, are we missing a scenario, or are probabilities miscalibrated?

#### Agent 4.0 — Prediction Coordinator
- **Model:** Sonnet
- **Job:** Orchestrates 4.1–4.4. Manages the combinatorial explosion by:
  - Pruning low-importance nodes from traversal (only simulate starting conditions for nodes with `importance_score > threshold`)
  - Batching traversals by sub-graph clusters
  - Setting time budgets

---

### PHASE 5: Feedback & Learning

#### Agent 5.1 — Outcome Monitor
- **Model:** Haiku (mostly search + comparison)
- **Input:** A past prediction + current date
- **Job:** Search for what actually happened. Compare predicted outcomes to actual outcomes. Generate a structured comparison.
- **Output:** `FeedbackEntry` candidate

#### Agent 5.2 — Root Cause Analyzer
- **Model:** Opus (this is the hardest reasoning task — understanding *why* a prediction was wrong)
- **Input:** A `FeedbackEntry` showing a significant prediction miss
- **Job:**
  - Was the graph missing a node? (a factor we didn't consider)
  - Was an edge wrong? (relationship was weaker/stronger/different than modeled)
  - Was a node state prediction wrong? (we predicted X would happen to this entity but Y happened instead)
  - Was it a black swan? (genuinely unforeseeable)
  - Generate specific corrections: add this node, modify this edge, adjust this relationship strength
- **Output:** A list of graph corrections + a `lesson_learned` narrative + updated confidence scores for relevant edges

#### Agent 5.3 — Calibration Tracker
- **Model:** Haiku (statistical computation)
- **Input:** Historical predictions and their outcomes
- **Job:** Track calibration: "When we say 70% probability, does the event happen ~70% of the time?" Compute calibration curves and identify systematic biases (e.g., are we consistently overconfident? Do we under-weight certain types of events?)
- **Output:** Calibration report + suggested adjustments to prediction probabilities

#### Agent 5.0 — Feedback Coordinator
- **Model:** Sonnet
- **Job:** Runs on a schedule (or on-demand) for each active scenario. Orchestrates 5.1–5.3. Ensures corrections are applied to the KB and ERG. Decides whether a scenario needs re-prediction based on how much new info has come in.

---

## 4. Cross-Scenario Intelligence

### Shared Graph Manager
- **Model:** Sonnet
- **Job:** When a new scenario is created, this agent:
  1. Analyzes the target question
  2. Searches all existing ERG nodes/edges across all scenarios
  3. Identifies relevant nodes/edges for the new scenario
  4. Proposes a "starter graph" composed of existing shared nodes + new scenario-specific nodes
  5. When a shared node is updated in one scenario, flags all other scenarios that use it for potential re-evaluation

### Cross-Scenario Correlation Detector
- **Model:** Sonnet
- **Job:** Periodically analyzes all active scenarios to find:
  - Shared dependencies (both gold and recession predictions depend heavily on Fed policy)
  - Contradictory predictions (scenario A assumes strong dollar, scenario B assumes weak dollar — are they using inconsistent assumptions?)
  - Synergies (a prediction made in scenario A would be useful input for scenario B)

---

## 5. Data Flow Between Agents — The Message Bus

Agents communicate via a structured message format:

```
AgentMessage {
  id:           string
  from_agent:   string (agent identifier)
  to_agent:     string | "coordinator"
  timestamp:    datetime
  message_type: enum [task_request, task_result, escalation, error, status_update]
  
  payload:      object (type-specific data)
  
  trace_id:     string (groups all messages belonging to one end-to-end run)
  parent_msg_id: string | null (for request-response pairing)
}
```

**Implementation options (in order of simplicity):**
1. **Simple:** Function calls within a single Python process. Agents are just functions/classes. "Messages" are just function arguments and return values. Start here.
2. **Medium:** A task queue (like Celery or even a simple Redis queue). Agents are workers. Good for parallelism.
3. **Complex:** A proper event bus (Kafka, NATS). Only if you're running this at scale with many concurrent scenarios.

**Recommendation: Start with option 1.** You can refactor to option 2 later when you need parallelism for the Information Retriever agents.

---

## 6. Model Selection Strategy

| Agent | Default Model | Escalation Trigger | Escalated Model |
|-------|--------------|-------------------|-----------------|
| 1.1 Query Decomposer | Haiku | Ambiguous query | Sonnet |
| 1.2 Information Retriever | Haiku | Never (tool-calling only) | — |
| 1.3 Information Summarizer | Sonnet | Long/technical docs | Opus |
| 1.4 Dedup & Delta Detector | Haiku | Contradictions found | Sonnet |
| 2.1 Entity Extractor | Haiku | Never | — |
| 2.2 Event Extractor | Haiku | Never | — |
| 2.3 Topic/Theme Extractor | Sonnet | Never | — |
| 2.4 Node Deduplicator | Haiku | Ambiguous merges | Sonnet |
| 3.1 Relationship Detector | Sonnet | Complex multi-causal | Opus |
| 3.2 Graph Consistency | Sonnet | Never | — |
| 4.1 Node State Predictor | Sonnet | High-importance nodes | Opus |
| 4.2 Graph Traversal Sim | Sonnet | Deep/complex graphs | Opus |
| 4.3 Instability Analyzer | Opus | Always Opus | — |
| 4.4 Scenario Synthesizer | Opus | Always Opus | — |
| 5.2 Root Cause Analyzer | Opus | Always Opus | — |
| 5.3 Calibration Tracker | Haiku | Never (statistical) | — |
| All Coordinators | Sonnet | Never | — |

**Cost estimation principle:** ~70% of agent calls should be Haiku, ~25% Sonnet, ~5% Opus. The Opus calls are few but high-value.

---

## 7. Additional Features for Improved Prediction Performance

### 7.1 Adversarial Red Team Agent
- **Model:** Opus
- A dedicated agent that tries to *break* the prediction. It asks:
  - "What is the strongest argument against the top-predicted scenario?"
  - "What assumption, if wrong, would most change the outcome?"
  - "What historical analogy suggests a different outcome?"
- Forces the system to stress-test its own predictions. The Scenario Synthesizer must address the Red Team's objections.

### 7.2 Historical Analogy Matcher
- **Model:** Sonnet
- Searches for historical situations that are structurally similar to the current scenario. ("This pattern of rising rates + high debt + commodity shock is similar to 1973–74.")
- Uses the historical outcome to inform (not determine) current predictions.
- Adds a `historical_analogies` field to scenario predictions.

### 7.3 Base Rate Anchoring
- Before any AI-driven prediction, compute base rates from historical data:
  - "How often has gold risen > 10% in a 6-month period historically?" → This becomes a prior that the prediction should update from, not ignore.
  - "How often do recessions follow an inverted yield curve within 18 months?" → Base rate.
- Agent 4.1 (Node State Predictor) receives the base rate as input and must justify any significant deviation from it.

### 7.4 Sentiment Drift Tracker
- **Model:** Haiku
- Continuously monitors news/forum sentiment on key topics. Tracks the *change* in sentiment over time, not just the level.
- Rapid sentiment shifts are often leading indicators.
- Outputs a `sentiment_velocity` metric for each topic.

### 7.5 Assumption Registry
- Every prediction has explicit assumptions. The system maintains a registry:
  ```
  Assumption {
    id: string
    statement: "The Fed will not cut rates before Q3 2025"
    used_in_scenarios: string[]
    still_valid: boolean
    last_checked: datetime
    invalidated_by: string | null (KB entry that contradicts it)
  }
  ```
- A lightweight Haiku agent periodically checks if assumptions are still valid against new KB entries. If an assumption breaks, all dependent scenarios are flagged for re-prediction.

### 7.6 Uncertainty Quantification Layer
- Don't just predict probabilities — predict the *confidence in those probabilities*.
- A prediction of "60% chance of recession, confidence: high" is very different from "60% chance of recession, confidence: low."
- Low-confidence predictions should trigger more research (loop back to Phase 1) rather than being reported as-is.

### 7.7 Expert Perspective Simulator
- **Model:** Opus
- For high-importance predictions, simulate what different expert archetypes would say:
  - "A macro hedge fund manager would argue..."
  - "A central bank economist would say..."
  - "A gold bug / commodity trader perspective is..."
- Not to reach consensus, but to surface perspectives the system might be anchored away from.
- This directly supports the multi-perspective tagging system (bull/bear, left/right, etc.).

### 7.8 Information Value Calculator
- Before running Phase 1 searches, estimate the *value of information*: "If we could learn X, how much would that change our prediction?"
- Focus research effort on high-value unknowns rather than gathering more data on things already well-understood.
- **Model:** Sonnet — analyzes the graph to find nodes with high importance but low confidence.

### 7.9 Scenario Versioning & Diff
- Every time a prediction is re-run, store the full snapshot.
- Provide a "diff" view: "What changed from v1 to v2 of this prediction?"
  - New nodes added
  - Edges modified
  - Probability shifts
  - New information that drove the change
- This is invaluable for understanding how the system's thinking evolves.

### 7.10 Cascade Risk Scorer
- For each node in the graph, compute: "If this node changes unexpectedly, how much chaos does it cause in the rest of the graph?"
- Nodes that cause high cascade risk when they change are "keystone nodes" — they deserve extra monitoring and more careful prediction.
- This is basically a sensitivity analysis on the graph.

---

## 8. Execution Plan — Build Order

**Phase A: Foundation (Week 1–2)**
1. Set up project structure, database schema (KB + ERG + Predictions)
2. Build the embedding pipeline (a simple function: text → vector)
3. Build the KB read/write layer
4. Build a simple agent runner (function that calls an LLM with a system prompt + input, parses structured output)

**Phase B: Context Gathering (Week 3–4)**
5. Build Agent 1.1 (Query Decomposer) — test with sample queries
6. Build Agent 1.2 (Information Retriever) — integrate with search APIs
7. Build Agent 1.3 (Summarizer) + Agent 1.4 (Dedup)
8. Build Agent 1.5 (KB Writer)
9. Build Agent 1.0 (Coordinator) — wire the loop together
10. End-to-end test: "Tell me about gold prices" → KB populated

**Phase C: Extraction & Graph (Week 5–6)**
11. Build Agents 2.1–2.4 (Extractors + Dedup)
12. Build Agent 2.0 (Extraction Coordinator)
13. Build Agent 3.1 (Relationship Detector) — this is the hardest single agent
14. Build Agents 3.2–3.3
15. Build Agent 3.0 (Graph Coordinator)
16. Wire the convergence loop (Phases 1–3)

**Phase D: Prediction (Week 7–8)**
17. Build Agent 4.1 (Node State Predictor)
18. Build Agent 4.2 (Graph Traversal Simulator) — start with simple BFS
19. Build Agents 4.3–4.4
20. Build Agent 4.0 (Prediction Coordinator)
21. End-to-end test: query → KB → ERG → predictions

**Phase E: Feedback & Polish (Week 9–10)**
22. Build Agents 5.1–5.3
23. Build cross-scenario intelligence
24. Build the additional features (7.1–7.10), prioritized by impact
25. Build a simple UI or CLI for interacting with scenarios

**Iterate from here.** Each additional feature (red team, historical analogy, etc.) is a standalone addition that plugs into the existing pipeline.

---

## 9. Key Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Combinatorial explosion in graph traversal | Prediction phase takes too long / costs too much | Prune low-importance nodes; set traversal depth limits; batch by sub-graph |
| LLM hallucination in relationship detection | Spurious edges in graph → bad predictions | Every edge must cite specific KB entries as evidence; Graph Consistency Checker validates |
| Overconfidence in predictions | Misleading output | Base rate anchoring; Calibration Tracker; Red Team Agent; always show confidence alongside probability |
| KB grows too large / noisy | Slow retrieval; diluted signal | Decay scoring; periodic pruning of superseded entries; relevance-weighted retrieval |
| Agent coordination complexity | Hard to debug; agents talking past each other | Start with simple function calls (no message bus); strong type contracts; comprehensive logging |
| Cost runaway from Opus calls | Budget blown | Hard limits on Opus calls per scenario run; Opus only for nodes where importance > threshold |
| Circular reasoning in feedback | System reinforces its own biases | Feedback agent must use *external* ground truth, not the system's own predictions |

---

## 10. Summary: What Makes This System Better Than a Single LLM Call

1. **Decomposition:** No single LLM call can do research + extraction + graph building + prediction well. Specialization wins.
2. **Iterative refinement:** The convergence loop ensures depth, not just breadth. The system goes deeper until it runs out of new information.
3. **Explicit structure:** The ERG makes relationships visible, debuggable, and modifiable. A single LLM's "reasoning" is a black box.
4. **Calibration:** The feedback loop + calibration tracker means the system gets better over time with real-world data.
5. **Reusability:** Shared graphs across scenarios mean the system accumulates institutional knowledge.
6. **Perspective diversity:** Forced multi-perspective analysis (bull/bear, expert archetypes) counteracts anchoring bias.
7. **Auditability:** Every prediction can be traced back through traversal logs → graph edges → KB entries → original sources. No "trust me, the AI said so."
