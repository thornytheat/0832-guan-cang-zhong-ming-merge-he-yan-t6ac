"""跨组互认签发台——HTTP 端到端测试。"""

import pytest


@pytest.fixture
def recognition_client(tmp_path):
    from app.main import create_app
    app = create_app(tmp_path / 'runs.db', tmp_path / 'recognition.db')
    return app.test_client()


def group(gid, headcount_ok=True):
    return {'kind': 'group', 'group': gid, 'headcount_ok': headcount_ok}


def authority(gid, author, number):
    return {'kind': 'authority', 'group': gid, 'author': author, 'authority': number}


def recognize(claim, gid, author, peer_group, peer_author):
    return {'kind': 'recognize', 'claim': claim, 'group': gid, 'author': author,
            'peer_group': peer_group, 'peer_author': peer_author}


def revoke(claim):
    return {'kind': 'revoke', 'claim': claim}


def admit(client, events):
    return client.post('/api/recognition/events', json={'events': events})


def test_workbench_page_renders(recognition_client):
    response = recognition_client.get('/recognition')
    assert response.status_code == 200
    assert '跨组互认签发台'.encode() in response.data


def test_snapshot_starts_empty(recognition_client):
    body = recognition_client.get('/api/recognition').json
    assert body['status'] == {} and body['conflicts'] == [] and body['signoffs'] == []


def test_conflict_suspends_connected_groups_but_not_unrelated(recognition_client):
    client = recognition_client
    admit(client, [
        group('G1'), group('G2'), group('G3'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200), authority('G3', 'c1', 300),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        recognize('C23', 'G2', 'b1', 'G3', 'c1'),
    ])
    snapshot = client.get('/api/recognition').json
    assert snapshot['status'] == {'G1': 'SUSPENDED', 'G2': 'SUSPENDED', 'G3': 'SUSPENDED'}
    assert snapshot['conflicts'][0]['authorities'] == [100, 200, 300]
    # 冲突组件外新增一个无关联组，核验合格即可先签。
    admit(client, [group('G4'), authority('G4', 'd1', 400)])
    issued = client.post('/api/recognition/signoffs',
                         json={'group': 'G4', 'revision': 0, 'note': '无关联，核验合格'}).json
    assert issued['status'] == 'ISSUED'
    assert client.post('/api/recognition/signoffs',
                       json={'group': 'G1', 'revision': 0, 'note': '试图签发冲突组'}).status_code == 409


def test_same_author_id_without_recognition_stays_independent(recognition_client):
    client = recognition_client
    admit(client, [
        group('G1'), group('G2'),
        authority('G1', 'x', 100), authority('G2', 'x', 200),
    ])
    snapshot = client.get('/api/recognition').json
    assert snapshot['conflicts'] == []
    assert snapshot['status'] == {'G1': 'READY', 'G2': 'READY'}


def test_revoke_restores_ready_and_allows_signoff(recognition_client):
    client = recognition_client
    admit(client, [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ])
    assert client.get('/api/recognition').json['status']['G1'] == 'SUSPENDED'
    admit(client, [revoke('C12')])
    snapshot = client.get('/api/recognition').json
    assert snapshot['status'] == {'G1': 'READY', 'G2': 'READY'}
    assert snapshot['recognitions'] == [] and snapshot['revoked'] == ['C12']
    response = client.post('/api/recognition/signoffs',
                           json={'group': 'G1', 'revision': 0, 'note': '冲突解除后签发'})
    assert response.status_code == 200 and response.json['revision'] == 1


def test_combined_submission_applies_correction_first(recognition_client):
    client = recognition_client
    admit(client, [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
    ])
    # 更正先建立冲突，同批 G1 签发必须因重算后的 SUSPENDED 被拒。
    response = client.post('/api/recognition/submissions', json={
        'events': [recognize('C12', 'G1', 'a1', 'G2', 'b1')],
        'signoffs': [{'group': 'G1', 'revision': 0, 'note': '同批试图签发'}],
    })
    assert response.status_code == 409
    assert response.json['code'] == 'GROUP_NOT_RELEASABLE'
    # 原子回滚：互认事件未入账。
    assert client.get('/api/recognition').json['recognitions'] == []


def test_correction_invalidates_existing_signoff(recognition_client):
    client = recognition_client
    admit(client, [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 100),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ])
    client.post('/api/recognition/signoffs', json={'group': 'G1', 'revision': 0, 'note': '初次签发'})
    # 撤销互认触及 G1，旧结论失效。
    admit(client, [revoke('C12')])
    assert client.get('/api/recognition').json['signoffs'] == []
    stale = client.post('/api/recognition/signoffs',
                        json={'group': 'G1', 'revision': 1, 'note': '带旧版本重签'})
    assert stale.status_code == 409 and stale.json['code'] == 'STALE_RECOGNITION'


def test_validation_errors_map_to_422(recognition_client):
    client = recognition_client
    response = admit(client, [{'kind': 'group', 'group': 'G1', 'headcount_ok': 'yes'}])
    assert response.status_code == 422 and response.json['code'] == 'GROUP_FIELDS'
    response = client.post('/api/recognition/events', json={'events': 'not-a-list'})
    assert response.status_code == 422 and response.json['code'] == 'RECOGNITION_FIELDS'


def test_unknown_group_and_claim_return_404(recognition_client):
    client = recognition_client
    assert admit(client, [revoke('GHOST')]).status_code == 404
    response = client.post('/api/recognition/signoffs',
                           json={'group': 'G9', 'revision': 0, 'note': '未知分组'})
    assert response.status_code == 404 and response.json['code'] == 'GROUP_NOT_FOUND'


def test_state_persists_across_clients(tmp_path):
    from app.main import create_app
    first = create_app(tmp_path / 'runs.db', tmp_path / 'recognition.db').test_client()
    admit(first, [group('G1'), authority('G1', 'a1', 100)])
    second = create_app(tmp_path / 'runs.db', tmp_path / 'recognition.db').test_client()
    assert second.get('/api/recognition').json['groups'] == ['G1']
