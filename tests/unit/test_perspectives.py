import json
import pytest
from pydantic import ValidationError
from seldon.data.database import make_engine, create_all, make_session_factory
from seldon.workspace.perspectives import export_graph, apply_graph, select_context, index_scenario
from seldon.workspace.perspectives.schemas import PerspectiveApply, Assessment
from seldon.workspace.service import WorkspaceConflict, WorkspaceService
from seldon.workspace.reports import generate_report, ReportRequest, report_file


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(sqlite_path=tmp_path / 'claims.db')
    create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def change(db, key, **kwargs):
    return apply_graph(db, PerspectiveApply(request_id=key, base_revision=export_graph(db)['revision'], agent='reviewer', reason='Evidence review', **kwargs))


def seed(db):
    return change(db, 'first', topics=[{'id': 'oil', 'name': 'Oil through Hormuz'}, {'id': 'shipping', 'name': 'Shipping'}, {'id': 'rates', 'name': 'Freight rates'}], sources=[{'id': 'a', 'name': 'Writer A', 'kind': 'writer'}, {'id': 'paper', 'name': 'Publication', 'kind': 'publication'}, {'id': 'owner', 'name': 'Holding group', 'kind': 'conglomerate'}], claims=[{'id': 'c1', 'topic_ids': ['oil'], 'source_ids': ['a'], 'source_url': 'https://example.org/a', 'statement': 'Fixture report: traffic fell.', 'retrieved_at': '2026-09-01T00:00:00Z', 'origin_id': 'wire-1'}, {'id': 'c2', 'topic_ids': ['shipping'], 'source_ids': ['paper'], 'source_url': 'https://example.org/b', 'statement': 'Fixture counterreport: traffic was unchanged.', 'retrieved_at': '2026-09-02T00:00:00Z', 'origin_id': 'wire-1'}], topic_links=[{'id': 'topic-link', 'source': 'oil', 'target': 'shipping', 'relationship': 'subtopic', 'rationale': 'Scope'}, {'id': 'topic-link-2', 'source': 'shipping', 'target': 'rates', 'relationship': 'related', 'rationale': 'Related issue'}], source_links=[{'id': 'writer-link', 'source': 'a', 'target': 'paper', 'relationship': 'writes_for', 'rationale': 'Byline', 'citations': ['https://example.org/byline']}, {'id': 'owner-link', 'source': 'owner', 'target': 'paper', 'relationship': 'owns', 'rationale': 'Filing', 'citations': ['https://example.org/filing']}], claim_links=[{'id': 'dispute', 'source': 'c1', 'target': 'c2', 'relationship': 'contradicts', 'rationale': 'Same measurement period; incompatible traffic estimates'}])


def test_conflicts_scope_assessments_and_history_survive_restart(factory):
    with factory() as db, db.begin():
        seed(db)
        graph = export_graph(db)
        assert not graph['assessments']  # A publication is not automatically a verified fact.
        view = select_context(graph, topic_id='oil', depth=0)
        assert {t['id'] for t in view['topics']} == {'oil'}
        assert {c['id'] for c in view['claims']} == {'c1', 'c2'}  # Keep counterevidence even across topic boundaries.
        assert len({c['origin_id'] for c in view['claims']}) == 1
        assert {s['id'] for s in select_context(graph, source_id='a', depth=1)['sources']} == {'a', 'paper'}
        assert 'owner' in {s['id'] for s in select_context(graph, source_id='a', depth=2)['sources']}
        change(db, 'review-1', assessments=[{'id': 'review-1', 'target_kind': 'source', 'target_id': 'a', 'assessed_at': '2026-09-02T12:00:00Z', 'scope': 'Gulf shipping', 'trust_percent': 65, 'rationale': 'Fixture methodological review', 'citations': ['https://example.org/method'], 'leanings': [{'dimension': 'regional security', 'position': 'Supports government security policy', 'region': 'Gulf regional politics', 'context': 'Shipping restrictions', 'citations': ['https://example.org/editorial']}]}])
        change(db, 'review-2', assessments=[{'id': 'review-2', 'target_kind': 'claim', 'target_id': 'c1', 'assessed_at': '2026-09-03T12:00:00Z', 'status': 'fact', 'trust_percent': 85, 'rationale': 'Fixture verified observation', 'verification_method': 'Compared dated raw logs and definitions', 'citations': ['https://example.org/logs']}])
        change(db, 'review-3', assessments=[{'id': 'review-3', 'target_kind': 'claim', 'target_id': 'c1', 'assessed_at': '2026-09-04T12:00:00Z', 'status': 'disputed', 'trust_percent': 40, 'rationale': 'New counterevidence', 'citations': ['https://example.org/correction']}])
    with factory() as db:
        graph = export_graph(db)
        assert len(graph['claims']) == 2 and len(graph['assessments']) == 3
        assert [a['status'] for a in graph['assessments'] if a['target_id'] == 'c1'] == ['fact', 'disputed']
        assert graph['assessments'][0]['assessor'] == 'reviewer'
        assert len(graph['history']) == 4


def test_atomic_cycles_replays_stale_and_immutable_records(factory):
    with factory() as db, db.begin():
        seed(db)
        before = export_graph(db)
        payload = PerspectiveApply(request_id='bad', base_revision=before['revision'], agent='a', reason='cycle', sources=[{'id':'must-not-persist','name':'X'}], topic_links=[{'id':'cycle','source':'shipping','target':'oil','relationship':'subtopic','rationale':'cycle'}])
        with pytest.raises(ValueError, match='DAG'):
            apply_graph(db, payload)
        assert export_graph(db)['revision'] == before['revision']
        request = PerspectiveApply(request_id='good', base_revision=before['revision'], agent='a', reason='related cross-link', topic_links=[{'id':'related','source':'rates','target':'oil','relationship':'related','rationale':'cross-link'}])
        apply_graph(db, request)
        assert apply_graph(db, request)['replayed']
        with pytest.raises(WorkspaceConflict):
            apply_graph(db, request.model_copy(update={'reason':'different'}))
        with pytest.raises(WorkspaceConflict):
            apply_graph(db, request.model_copy(update={'request_id':'stale'}))
        changed = {**before['claims'][0], 'statement': 'Silent overwrite'}
        with pytest.raises(ValueError, match='immutable'):
            change(db, 'overwrite', claims=[changed])
        with pytest.raises(ValueError, match='Unknown sources'):
            change(db, 'dangling', source_links=[{'id':'bad','source':'a','target':'absent','relationship':'owns','rationale':'x','citations':['https://example.org/'] }])
        assert 'must-not-persist' not in {s['id'] for s in export_graph(db)['sources']}


def test_judgments_require_provenance():
    base = dict(id='a', target_kind='claim', target_id='c', assessed_at='2026-09-01T00:00:00Z', rationale='Evidence')
    for extra in ({'trust_percent': 101}, {'trust_percent': 50}, {'status': 'fact'}, {'status': 'fact', 'citations': ['https://example.org/']}):
        with pytest.raises(ValidationError):
            Assessment(**base, **extra)
    with pytest.raises(ValidationError):
        Assessment(**{**base, 'target_kind': 'source', 'status': 'fact'})


def test_index_reuses_claims_and_report_snapshot_keeps_old_judgments(factory):
    from seldon.data.repositories import GraphRepository, KBRepository
    from seldon.workspace.knowledge import freeze_graph, scoped_graph, knowledge_revision
    with factory() as db, db.begin():
        service = WorkspaceService(db)
        first = service.start('AI capex?', '2027')
        sid = first['scenario']['id']
        evidence = KBRepository(db).create_entry(content='Original claim', source_name='Outlet', source_url='https://example.org/e', scenario_ids=[sid])
        node = GraphRepository(db).create_node(name='AI investment', type='topic', kb_entry_ids=[evidence.id], scenario_ids=[sid])
        index_scenario(db, sid)
        assert index_scenario(db, sid)['unchanged']
        graph = export_graph(db)
        cid = graph['claims'][0]['id']
        assert graph['sources'][0]['kind'] == 'unknown'
        second = service.start('GPU demand?', '2027')['scenario']['id']
        node.scenario_ids = [sid, second]
        evidence.scenario_ids = [sid, second]
        db.flush()
        index_scenario(db, second)
        assert len(export_graph(db)['claims']) == 1
        view = scoped_graph(db, sid)
        old_revision = knowledge_revision(view)
        snapshot = freeze_graph(db, sid, view, agent='test', reason='before review')
        report = generate_report(db, sid, ReportRequest(request_id='original'))
        old_report = report_file(db, report['id'], 'detailed.md')['content']
        change(db, 'review', assessments=[{'id':'disputed','target_id':cid,'target_kind':'claim','assessed_at':'2026-09-02T00:00:00Z','status':'disputed','rationale':'Disagree with source', 'citations':['https://example.org/review']}])
        assert knowledge_revision(scoped_graph(db,sid)) != old_revision
        assert snapshot.snapshot['perspectives']['assessments'] == []
        assert report_file(db, report['id'], 'detailed.md')['content'] == old_report
        KBRepository(db).update_entry(evidence.id, content='Corrected claim')
        index_scenario(db,sid)
        assert len(export_graph(db)['claims']) == 2
        assert export_graph(db)['claim_links'][0]['relationship'] == 'supersedes'
        assert 'disputed' in service.export(sid)['perspectives']['assessments'][0]['status']


def test_cli_roundtrip_and_no_provider(factory, tmp_path, capsys):
    from seldon.cli import main
    path=tmp_path/'cli.db'
    assert main(['research','--db',str(path),'perspectives','export']) == 0
    graph=json.loads(capsys.readouterr().out)
    payload=tmp_path/'change.json'
    payload.write_text(json.dumps(dict(request_id='cli',base_revision=graph['revision'],agent='cli',reason='Topic seed',topics=[dict(id='oil',name='Oil through Hormuz') ])))
    assert main(['research','--db',str(path),'perspectives','apply',str(payload)]) == 0
    capsys.readouterr()
    output=tmp_path/'graph.md'
    assert main(['research','--db',str(path),'perspectives','export','--topic','oil','--depth','0','--format','markdown','--out',str(output)]) == 0
    assert 'Oil through Hormuz' in output.read_text()


def test_http_handlers_validation_history_and_markdown(factory):
    # Invoke sync route handlers directly: no provider, socket or thread portal.
    from fastapi import HTTPException
    from seldon.workspace.perspectives.api import build_router
    router = build_router(lambda: None)
    endpoints = {r.name: r.endpoint for r in router.routes}
    with factory() as db:
        graph = endpoints['export'](topic_id=None, source_id=None, depth=4, format='json', db=db)
    payload = PerspectiveApply(request_id='http',base_revision=graph['revision'],agent='test',reason='HTTP request',topics=[{'id':'oil','name':'Oil through Hormuz'}])
    with factory() as db:
        result = endpoints['apply'](payload, db=db)
    with factory() as db:
        response = endpoints['export'](topic_id='oil',source_id=None,depth=0,format='markdown',db=db)
        assert 'Oil through Hormuz' in response.body.decode()
        event = endpoints['history'](run_id=result['run_id'],db=db)
        assert event['event']['changes']['topics'][0]['name'] == 'Oil through Hormuz'
        assert endpoints['catalog'](db=db)['nodes'][0]['id'] == 'oil'
        assert endpoints['connection_view'](kind='topic',id='oil',depth=0,to_kind=None,to_id=None,db=db)['root']['name'] == 'Oil through Hormuz'
        with pytest.raises(HTTPException) as exc:
            endpoints['connection_view'](kind='topic',id='missing',depth=0,to_kind=None,to_id=None,db=db)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            endpoints['connection_view'](kind='topic',id='oil',depth=0,to_kind='source',to_id=None,db=db)
        assert exc.value.status_code == 422
        with pytest.raises(HTTPException) as exc:
            endpoints['history'](run_id='absent',db=db)
        assert exc.value.status_code == 404
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            endpoints['apply'](payload.model_copy(update={'request_id':'stale'}),db=db)
        assert exc.value.status_code == 409
    with factory() as db:
        revision = export_graph(db)['revision']
    with factory() as db:
        with pytest.raises(HTTPException) as exc:
            endpoints['apply'](PerspectiveApply(request_id='bad',base_revision=revision,agent='test',reason='bad',assessments=[{'id':'a','target_id':'absent','target_kind':'claim','assessed_at':'2026-09-01T00:00:00Z','rationale':'missing'}]),db=db)
        assert exc.value.status_code == 422


def test_connections_explain_entity_topic_source_paths(factory):
    from seldon.data.repositories import GraphRepository, KBRepository
    from seldon.workspace.perspectives.connections import connections, connection_catalog
    with factory() as db, db.begin():
        sid=WorkspaceService(db).start('Shipping?', 'Now')['scenario']['id']
        e=KBRepository(db).create_entry(content='Reported traffic',source_name='Port authority',source_url='https://example.org/traffic',scenario_ids=[sid])
        n=GraphRepository(db).create_node(name='Hormuz traffic',type='metric',kb_entry_ids=[e.id],scenario_ids=[sid])
        index_scenario(db,sid)
        graph=export_graph(db)
        source=graph['sources'][0]
        view=connections(db,'entity',n.id,depth=4,to_kind='source',to_id=source['id'])
        assert view['path_found']
        assert {'entity','source','topic','claim','evidence'} <= {n['kind'] for n in view['nodes']}
        assert view['path'][0]['from']['record_id']==n.id
        assert view['path'][-1]['to']['record_id']==source['id']
        assert all(s['relationships'] for s in view['path'])
        assert not connections(db,'entity',n.id,depth=1,to_kind='source',to_id=source['id'])['path_found']
        assert len(connections(db,'entity',n.id,depth=0)['nodes'])==1
        assert any(r['id']==n.id for r in connection_catalog(db)['nodes'])
        with pytest.raises(KeyError):
            connections(db,'entity','absent')
        with pytest.raises(ValueError):
            connections(db,'entity',n.id,to_id='partial')
        change(db,'match-source',sources=[{**source,'entity_ids':[n.id]}])
        assert connections(db,'source',source['id'],depth=1,to_kind='entity',to_id=n.id)['path_found']
        with pytest.raises(ValueError, match='Unknown research entity'):
            change(db,'bad-source-match',sources=[{**source,'entity_ids':['missing']}])
        assert connections(db,'source',source['id'],depth=1,to_kind='entity',to_id=n.id)['path_found']
        from seldon.workspace.knowledge import search_library
        assert search_library(db,entity_id=n.id)['total']==1
        assert search_library(db,entity_id='missing')['total']==0
