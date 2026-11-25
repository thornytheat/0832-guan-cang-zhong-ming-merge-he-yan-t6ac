"""跨组互认签发台——领域重算规则测试。"""

import pytest

from app.recognize.domain import Registry, RecognitionError


def build(events):
    registry = Registry()
    for event in events:
        registry.apply(event)
    return registry


def group(gid, headcount_ok=True):
    return {'kind': 'group', 'group': gid, 'headcount_ok': headcount_ok}


def authority(gid, author, number):
    return {'kind': 'authority', 'group': gid, 'author': author, 'authority': number}


def recognize(claim, gid, author, peer_group, peer_author):
    return {'kind': 'recognize', 'claim': claim, 'group': gid, 'author': author,
            'peer_group': peer_group, 'peer_author': peer_author}


def revoke(claim):
    return {'kind': 'revoke', 'claim': claim}


def three_groups():
    return [
        group('G1'), group('G2'), group('G3'), group('G4'),
        authority('G1', 'a1', 100),
        authority('G2', 'b1', 200),
        authority('G3', 'c1', 300),
        authority('G4', 'd1', 400),
    ]


# 规则 1：互认记录挂到不同权威编号即权威冲突，组内人数合格也不能签。
def test_recognized_authors_with_different_authority_conflict():
    registry = build([*three_groups(), recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    conflicts = registry.conflicts_evidence()
    assert len(conflicts) == 1
    assert conflicts[0]['authorities'] == [100, 200]
    assert conflicts[0]['claims'] == ['C12']
    status = registry.status()
    assert status['G1'] == 'SUSPENDED'
    assert status['G2'] == 'SUSPENDED'
    assert registry.releasable(['G1']) is False


def test_same_authority_through_recognition_stays_ready():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 100),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ]
    registry = build(events)
    assert registry.conflicts() == {}
    assert registry.status() == {'G1': 'READY', 'G2': 'READY'}
    assert registry.releasable(['G1', 'G2']) is True


def test_unconfirmed_authority_zero_never_conflicts():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'a1', 0), authority('G2', 'b1', 200),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ]
    registry = build(events)
    assert registry.conflicts() == {}
    assert registry.status()['G1'] == 'READY'


# 规则 2：冲突经互认关系传到第三组，牵连组一并暂缓；无关联的合格组先签。
def test_conflict_propagates_through_recognition_chain():
    events = [
        *three_groups(),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        recognize('C23', 'G2', 'b1', 'G3', 'c1'),
    ]
    registry = build(events)
    status = registry.status()
    assert status['G1'] == 'SUSPENDED'
    assert status['G2'] == 'SUSPENDED'
    assert status['G3'] == 'SUSPENDED'
    # G4 与冲突组件没有任何互认关联，核验合格即可先签。
    assert status['G4'] == 'READY'
    assert registry.releasable(['G4']) is True
    assert registry.releasable(['G4', 'G1']) is False


def test_conflict_propagates_via_intermediate_zero_authority_group():
    events = [
        group('G1'), group('G2'), group('G3'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 0),
        authority('G3', 'c1', 300),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        recognize('C23', 'G2', 'b1', 'G3', 'c1'),
    ]
    registry = build(events)
    assert set(registry.groups_in_conflict()) == {'G1', 'G2', 'G3'}
    assert all(state == 'SUSPENDED' for state in registry.status().values())


# 规则 3：编号碰巧相同但无互认证据，不视为同一人，冲突不传播，各自核验。
def test_same_local_author_number_without_recognition_is_independent():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'x', 100), authority('G2', 'x', 200),
    ]
    registry = build(events)
    # 两个引用各自成独立组件，编号相同不产生连接。
    assert registry.conflicts() == {}
    assert registry.status() == {'G1': 'READY', 'G2': 'READY'}


def test_same_author_id_but_conflict_elsewhere_does_not_taint():
    events = [
        group('G1'), group('G2'), group('G3'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        authority('G3', 'a1', 300),  # 与 G1 的本地作者编号碰巧相同
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ]
    registry = build(events)
    assert registry.status()['G3'] == 'READY'


# 组内核验不合格（人数对不上）优先记 HELD，不被 SUSPENDED 掩盖。
def test_headcount_failure_holds_group_even_inside_conflict():
    events = [
        group('G1', headcount_ok=False), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ]
    registry = build(events)
    assert registry.status() == {'G1': 'HELD', 'G2': 'SUSPENDED'}


# 规则 4：晚到的撤销更正解除互认关系后重算，合格组恢复待签。
def test_revoke_recognition_recomputes_and_restores_ready():
    events = [
        *three_groups(),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        recognize('C23', 'G2', 'b1', 'G3', 'c1'),
    ]
    registry = build(events)
    assert all(registry.status()[g] == 'SUSPENDED' for g in ('G1', 'G2', 'G3'))
    registry.apply(revoke('C12'))
    status = registry.status()
    # G1 脱离冲突组件恢复待签；G2-G3 仍挂在同一冲突组件上。
    assert status['G1'] == 'READY'
    assert status['G2'] == 'SUSPENDED'
    assert status['G3'] == 'SUSPENDED'
    assert registry.releasable(['G1']) is True
    assert 'C12' in registry.revoked


def test_revoke_all_claims_clears_conflict_entirely():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        revoke('C12'),
    ]
    registry = build(events)
    assert registry.conflicts() == {}
    assert registry.edges == {}
    assert registry.status() == {'G1': 'READY', 'G2': 'READY'}


def test_revoke_unknown_claim_is_rejected():
    registry = build([group('G1')])
    with pytest.raises(RecognitionError, match='CLAIM_NOT_FOUND'):
        registry.apply(revoke('GHOST'))


def test_authority_correction_recomputes_conflict():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ]
    registry = build(events)
    assert registry.status()['G1'] == 'SUSPENDED'
    # 晚到的权威编号更正把 G2 改成与 G1 一致，冲突解除。
    registry.apply(authority('G2', 'b1', 100))
    assert registry.conflicts() == {}
    assert registry.status() == {'G1': 'READY', 'G2': 'READY'}


def test_snapshot_reports_full_workbench_state():
    registry = build([*three_groups(), recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    snapshot = registry.snapshot()
    assert snapshot['sequence'] == len(three_groups()) + 1
    assert snapshot['groups'] == ['G1', 'G2', 'G3', 'G4']
    assert snapshot['recognitions'] == ['C12']
    assert snapshot['conflicts'][0]['authorities'] == [100, 200]
    assert snapshot['status']['G4'] == 'READY'


def test_unknown_event_kind_and_bad_fields_rejected():
    registry = Registry()
    with pytest.raises(RecognitionError, match='RECOGNITION_EVENT_UNKNOWN'):
        registry.apply({'kind': 'nope'})
    with pytest.raises(RecognitionError, match='GROUP_FIELDS'):
        registry.apply({'kind': 'group', 'group': 'G1', 'headcount_ok': 'yes'})


def test_recognition_requires_registered_group():
    registry = build([group('G1')])
    with pytest.raises(RecognitionError, match='GROUP_NOT_FOUND'):
        registry.apply(recognize('C1', 'G1', 'a1', 'G9', 'z1'))


def test_self_recognition_rejected():
    registry = build([group('G1'), authority('G1', 'a1', 0)])
    with pytest.raises(RecognitionError, match='SELF_RECOGNITION'):
        registry.apply(recognize('C1', 'G1', 'a1', 'G1', 'a1'))


def test_revoked_claim_cannot_be_reopened():
    events = [
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 100),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
        revoke('C12'),
    ]
    registry = build(events)
    with pytest.raises(RecognitionError, match='CLAIM_REVOKED'):
        registry.apply(recognize('C12', 'G1', 'a1', 'G2', 'b1'))
    # 终态撤销在异常后仍然保持。
    assert registry.edges == {} and 'C12' in registry.revoked
