"""Read-only, explicit provenance paths across otherwise separate graph layers."""
from urllib.parse import urlencode
import networkx as nx
from sqlalchemy import select
from seldon.data.models import ERGNode, KBEntry
from . import export_graph

KINDS = {'entity', 'topic', 'claim', 'source', 'evidence'}


def key(kind, id):
    return f'{kind}:{id}'


def build_connections(db):
    graph = export_graph(db)
    nodes, edges = {}, []
    def node(kind, id, name, description='', **extra):
        href = '/knowledge?' + urlencode({'id': id}) if kind == 'entity' else '/topics?' + urlencode({'id': id}) if kind == 'topic' else '/sources?' + urlencode({'id': id}) if kind == 'source' else '/connections?' + urlencode({'kind': kind, 'id': id, 'depth': 2})
        nodes[key(kind, id)] = dict(id=key(kind, id), record_id=id, kind=kind, name=name, description=description, href=href, **extra)
    def edge(a, b, relationship, description, reference=None):
        if a in nodes and b in nodes:
            edges.append(dict(id=f'{a}/{relationship}/{b}/{reference or ""}', source=a, target=b, relationship=relationship, description=description, reference=reference))
    entities = list(db.scalars(select(ERGNode)))
    evidence = list(db.scalars(select(KBEntry)))
    for n in entities:
        node('entity', n.id, n.name, n.description, scenario_ids=n.scenario_ids or [], tags=n.tags or [])
    for e in evidence:
        node('evidence', e.id, e.source_name, e.content, source_url=e.source_url)
    for t in graph['topics']:
        node('topic', t['id'], t['name'], t['description'])
    for s in graph['sources']:
        node('source', s['id'], s['name'], s['description'], source_kind=s['kind'])
    for c in graph['claims']:
        node('claim', c['id'], c['statement'][:100], c['statement'], source_url=c['source_url'])
    for t in graph['topics']:
        for id in t['entity_ids']:
            edge(key('topic',t['id']),key('entity',id),'describes','Topic explicitly describes this research entity.',t['id'])
    for s in graph['sources']:
        for id in s.get('entity_ids', []):
            edge(key('source',s['id']),key('entity',id),'identifies','Source identity explicitly matches this research entity.',s['id'])
    for n in entities:
        for id in n.kb_entry_ids or []:
            edge(key('evidence',id),key('entity',n.id),'used_for','Evidence is attached to this entity; this association does not establish truth.',id)
    for c in graph['claims']:
        ck=key('claim',c['id'])
        for id in c['topic_ids']:
            edge(ck,key('topic',id),'concerns','Claim is explicitly assigned to this topic.',c['id'])
        for id in c['source_ids']:
            edge(key('source',id),ck,'reports','Claim is attributed to this source.',c['id'])
        for id in c['evidence_ids']:
            edge(ck,key('evidence',id),'recorded_in','Claim links to this saved research evidence.',id)
        for id in c['derived_from_claim_ids']:
            edge(ck,key('claim',id),'derived_from','Shared origin; not independent corroboration.',c['id'])
    for collection, kind in [('topic_links','topic'),('source_links','source'),('claim_links','claim')]:
        for e in graph[collection]:
            detail=e['rationale']
            if kind=='source':
                detail += f" Status: {e['status']}; effective {e.get('valid_from') or 'unknown'} to {e.get('valid_until') or 'unknown'}."
            edge(key(kind,e['source']),key(kind,e['target']),e['relationship'],detail,e['id'])
    return nodes, edges


def connection_catalog(db):
    nodes, _ = build_connections(db)
    return {'nodes': sorted(({'id': n['record_id'], 'kind': n['kind'], 'name': n['name']} for n in nodes.values()),key=lambda n:(n['kind'],n['name'],n['id']))}


def connections(db, kind, id, *, depth=3, to_kind=None, to_id=None, limit=160):
    if kind not in KINDS or to_kind is not None and to_kind not in KINDS:
        raise ValueError('Unknown graph layer')
    if not 0<=depth<=12 or not 1<=limit<=500:
        raise ValueError('Depth must be 0–12; limit must be 1–500')
    if bool(to_kind) != bool(to_id):
        raise ValueError('Provide both destination kind and ID')
    nodes, edges=build_connections(db)
    root=key(kind,id)
    if root not in nodes:
        raise KeyError('Record not found')
    graph=nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from((e['source'],e['target']) for e in edges)
    distances=dict(nx.single_source_shortest_path_length(graph,root,cutoff=depth))
    ids=sorted(distances,key=lambda k:(distances[k],nodes[k]['kind'],nodes[k]['name'],k))
    path=[]
    target=key(to_kind,to_id) if to_kind else None
    if target and target not in nodes:
        raise KeyError('Destination not found')
    if target in distances:
        path=nx.shortest_path(graph,root,target)
    # A requested path must remain intact even when a high-degree neighborhood is capped.
    selected=list(dict.fromkeys(path+ids))[:limit]
    selected_set=set(selected)
    path_steps=[]
    for a,b in zip(path,path[1:]):
        relationships=[e for e in edges if {e['source'],e['target']}=={a,b}]
        path_steps.append({'from':nodes[a], 'to':nodes[b], 'relationships':relationships})
    return {'root':nodes[root], 'nodes':[{**nodes[k],'distance':distances[k]} for k in selected], 'edges':[e for e in edges if e['source'] in selected_set and e['target'] in selected_set], 'depth':depth, 'total_reachable':len(ids), 'truncated':len(ids)>len(selected), 'path':path_steps, 'path_found':bool(path) if target else None, 'semantics':'Paths show recorded provenance and associations in either direction, not causal influence, truth, or independent confirmation. Edge descriptions retain their actual direction. Historical/disputed affiliations remain labelled.'}
