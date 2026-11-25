"""跨组互认签发台——账本事务与签发结论测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.recognize.domain import RecognitionError
from app.recognize.store import RecognitionStore


def group(gid, headcount_ok=True):
    return {'kind': 'group', 'group': gid, 'headcount_ok': headcount_ok}


def authority(gid, author, number):
    return {'kind': 'authority', 'group': gid, 'author': author, 'authority': number}


def recognize(claim, gid, author, peer_group, peer_author):
    return {'kind': 'recognize', 'claim': claim, 'group': gid, 'author': author,
            'peer_group': peer_group, 'peer_author': peer_author}


def revoke(claim):
    return {'kind': 'revoke', 'claim': claim}


def base_events():
    return [
        group('G1'), group('G2'), group('G3'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 200),
        authority('G3', 'c1', 300),
    ]


def sign(gid, revision=0, note='核对无误，同意签发'):
    return {'group': gid, 'revision': revision, 'note': note}


@pytest.fixture
def store(tmp_path):
    return RecognitionStore(tmp_path / 'recognition.sqlite3')


@pytest.fixture
def ready_store(store):
    store.admit(base_events())
    return store


def test_events_persist_and_replay(ready_store):
    snapshot = ready_store.snapshot()
    assert snapshot['groups'] == ['G1', 'G2', 'G3']
    assert snapshot['status'] == {'G1': 'READY', 'G2': 'READY', 'G3': 'READY'}
    assert snapshot['signoffs'] == []


def test_ready_group_can_be_issued(ready_store):
    output = ready_store.signoff(sign('G1'))
    assert output == dict(gid='G1', status='ISSUED', base_seq=6, revision=1,
                          note='核对无误，同意签发')
    assert ready_store.list_signoffs() == [output]


def test_suspended_group_cannot_be_issued(store):
    store.admit([*base_events(), recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    with pytest.raises(RecognitionError, match='GROUP_NOT_RELEASABLE'):
        store.signoff(sign('G1'))
    assert store.list_signoffs() == []


def test_unknown_group_signoff_rejected(ready_store):
    with pytest.raises(RecognitionError, match='GROUP_NOT_FOUND'):
        ready_store.signoff(sign('G9'))


def test_note_length_validated(ready_store):
    with pytest.raises(RecognitionError, match='RECOGNITION_FIELDS'):
        ready_store.signoff(sign('G1', note='短'))


# 规则 2 的工作台视角：无关联合格组先签，牵连组暂缓。
def test_unrelated_group_issued_while_conflict_holds_others(store):
    store.admit([*base_events(), recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    issued = store.signoff(sign('G3'))
    assert issued['status'] == 'ISSUED'
    snapshot = store.snapshot()
    assert snapshot['status']['G1'] == 'SUSPENDED'
    assert [row['gid'] for row in snapshot['signoffs']] == ['G3']


# 规则 4：撤销互认后重算，冲突解除且核验合格的组恢复待签并可签发。
def test_revoke_restores_group_to_ready_for_signoff(store):
    store.admit([*base_events(), recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    store.admit([revoke('C12')])
    snapshot = store.snapshot()
    assert snapshot['status'] == {'G1': 'READY', 'G2': 'READY', 'G3': 'READY'}
    assert store.signoff(sign('G1'))['status'] == 'ISSUED'


def test_revoke_invalidates_prior_signoff_of_affected_group(store):
    # G1、G2 互认且权威一致，可以签发；之后撤销互认，旧结论依据已变化而失效。
    store.admit([
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 100),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ])
    store.signoff(sign('G1'))
    store.admit([revoke('C12')])
    assert store.list_signoffs() == []
    # 失效后重新签发需要从 revision 0 开始。
    with pytest.raises(RecognitionError, match='STALE_RECOGNITION'):
        store.signoff(sign('G1', revision=1))
    assert store.signoff(sign('G1', revision=0))['revision'] == 1


def test_unaffected_group_keeps_signoff_when_other_group_changes(store):
    store.admit(base_events())
    store.signoff(sign('G3'))
    # 只触及 G1/G2 的互认更正不应让 G3 的结论失效。
    store.admit([recognize('C12', 'G1', 'a1', 'G2', 'b1')])
    rows = store.list_signoffs()
    assert [row['gid'] for row in rows] == ['G3']


# 规则 5：同批提交更正与签发，更正先入账；受影响组的旧结论失去资格。
def test_submit_applies_correction_before_signoff(store):
    store.admit(base_events())
    # 更正先建立 G1-G2 权威冲突，同批 G1 的新签发请求必须看到暂缓状态。
    with pytest.raises(RecognitionError, match='GROUP_NOT_RELEASABLE'):
        store.submit([recognize('C12', 'G1', 'a1', 'G2', 'b1')], [sign('G1')])
    # 整体回滚：事件与签发都不落库。
    snapshot = store.snapshot()
    assert snapshot['recognitions'] == []
    assert snapshot['signoffs'] == []


def test_submit_correction_invalidates_stale_revision_in_same_batch(store):
    store.admit([
        group('G1'), group('G2'),
        authority('G1', 'a1', 100), authority('G2', 'b1', 100),
        recognize('C12', 'G1', 'a1', 'G2', 'b1'),
    ])
    store.signoff(sign('G1'))
    # 同批撤销互认并带着旧 revision=1 重签：更正先入账使旧结论失去资格，
    # 乐观锁拦截该请求；整个事务回滚，撤销与重签都不落库。
    with pytest.raises(RecognitionError, match='STALE_RECOGNITION'):
        store.submit([revoke('C12')], [sign('G1', revision=1)])
    snapshot = store.snapshot()
    assert snapshot['recognitions'] == ['C12']
    assert [row['gid'] for row in snapshot['signoffs']] == ['G1']
    # 更正单独入账后，受影响组的旧结论按受影响范围失效，需从 revision 0 重签。
    store.admit([revoke('C12')])
    assert store.list_signoffs() == []
    assert store.snapshot()['status']['G1'] == 'READY'
    assert store.signoff(sign('G1', revision=0))['revision'] == 1


def test_submit_is_atomic_across_multiple_signoffs(store):
    store.admit(base_events())
    with pytest.raises(RecognitionError):
        # G2 在建立冲突后不可签，G3 的合法请求也要随事务一起回滚。
        store.submit([recognize('C12', 'G1', 'a1', 'G2', 'b1')],
                     [sign('G3'), sign('G2')])
    assert store.snapshot()['signoffs'] == []


def test_submit_multiple_valid_signoffs_together(ready_store):
    _, issued = ready_store.submit([], [sign('G1'), sign('G2')])
    assert sorted(row['gid'] for row in issued) == ['G1', 'G2']


def test_optimistic_lock_rejects_concurrent_revision(ready_store):
    ready_store.signoff(sign('G1'))
    update = sign('G1', revision=1, note='来源已更新，重新签发')
    ready_store.signoff(update)
    with pytest.raises(RecognitionError, match='STALE_RECOGNITION'):
        ready_store.signoff(update)


def test_parallel_first_signoff_has_single_winner(ready_store):
    barrier = Barrier(4)

    def attempt():
        barrier.wait(3)
        try:
            return ready_store.signoff(sign('G1'))['status']
        except RecognitionError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))
    assert sorted(results).count('ISSUED') == 1
    assert results.count('STALE_RECOGNITION') == 3
    assert len(ready_store.list_signoffs()) == 1


def test_invalid_event_rolls_back_whole_batch(store):
    before = store.snapshot()['sequence']
    with pytest.raises(RecognitionError, match='CLAIM_NOT_FOUND'):
        store.admit([revoke('GHOST')])
    assert store.snapshot()['sequence'] == before


def test_empty_submission_rejected(store):
    with pytest.raises(RecognitionError, match='RECOGNITION_FIELDS'):
        store.submit([], [])
