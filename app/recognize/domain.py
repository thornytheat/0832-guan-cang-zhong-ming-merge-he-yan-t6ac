"""跨组互认签发台的纯领域逻辑。

编目规则（对应需求逐条落地）：

* 互认记录把不同组的本地作者指向同一人；同一互认组件内出现两个不同的
  非零权威编号即构成权威冲突（AUTHORITY_CONFLICT）。
* 冲突沿互认关系传播：组件内所有组一并暂缓，与冲突组件无互认关联的
  合格组不受牵连，可以先签。
* 不同组的本地作者编号碰巧相同，但没有互认边连接时不视为同一人，
  冲突不传播，各组各自核验。
* 权威编号 0 表示未确认，不参与冲突判定。
* 撤销互认关系的更正记录按事件顺序入账后整体重算：冲突解除且组内核验
  合格的组恢复待签。
* 同一批次同时提交更正与签发时，更正先入账并重算，受影响组的旧结论
  随即失去签发资格（由账本层的结论版本失效机制保证）。
"""

UNCONFIRMED = 0


class RecognitionError(ValueError):
    """可映射为 HTTP 4xx 的领域校验错误。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _ref(group, author):
    return f'{group}/{author}'


class Registry:
    """累积事件并按需重算的互认登记册。"""

    def __init__(self):
        self.groups = {}              # gid -> headcount_ok
        self.authority = {}           # "group/author" -> 非零权威编号或 0
        self.edges = {}               # claim_id -> (ref_a, ref_b)，仅存有效互认
        self.revoked = set()          # 已撤销的 claim_id
        self.revoked_edges = {}       # claim_id -> 撤销前的端点，供影响面判定
        self.sequence = 0             # 已入账事件数（账本乐观锁依据）

    # ------------------------------------------------------------------ 入账
    def apply(self, event):
        kind = event.get('kind')
        if kind == 'group':
            self._apply_group(event)
        elif kind == 'authority':
            self._apply_authority(event)
        elif kind == 'recognize':
            self._apply_recognize(event)
        elif kind == 'revoke':
            self._apply_revoke(event)
        else:
            raise RecognitionError('RECOGNITION_EVENT_UNKNOWN')
        self.sequence += 1
        return self.sequence

    def _apply_group(self, event):
        gid = self._required(event, 'group')
        headcount_ok = event.get('headcount_ok')
        if not isinstance(headcount_ok, bool):
            raise RecognitionError('GROUP_FIELDS')
        self.groups[gid] = headcount_ok

    def _apply_authority(self, event):
        ref = self._ref_known(event)
        number = event.get('authority')
        if type(number) is not int or number < 0:
            raise RecognitionError('AUTHORITY_FIELDS')
        self.authority[ref] = number

    def _apply_recognize(self, event):
        claim = self._required(event, 'claim')
        ref_a = self._ref_known(event, 'group', 'author')
        ref_b = self._ref_known(event, 'peer_group', 'peer_author')
        if ref_a == ref_b:
            raise RecognitionError('SELF_RECOGNITION')
        # 已撤销的互认关系为终态：重放旧 recognize 事件也不能让它复活，
        # 重新登记同一编号必须显式拒绝，提示编目员改用新 claim。
        if claim in self.revoked:
            raise RecognitionError('CLAIM_REVOKED')
        self.edges[claim] = (ref_a, ref_b)

    def _apply_revoke(self, event):
        claim = self._required(event, 'claim')
        if claim not in self.edges:
            raise RecognitionError('CLAIM_NOT_FOUND')
        self.revoked_edges[claim] = self.edges.pop(claim)
        self.revoked.add(claim)

    def affected_groups(self, event):
        """事件直接牵连到的组；这些组的旧签发结论在事件入账后失效。

        必须在 ``apply`` 之后调用：撤销事件的端点取自撤销前留存的快照。
        """
        kind = event.get('kind')
        if kind == 'group':
            return {self._required(event, 'group')}
        if kind == 'authority':
            return {self._required(event, 'group')}
        if kind == 'recognize':
            return {self._required(event, 'group'),
                    self._required(event, 'peer_group')}
        if kind == 'revoke':
            claim = self._required(event, 'claim')
            if claim not in self.revoked_edges:
                raise RecognitionError('CLAIM_NOT_FOUND')
            ref_a, ref_b = self.revoked_edges[claim]
            return {ref_a.split('/', 1)[0], ref_b.split('/', 1)[0]}
        raise RecognitionError('RECOGNITION_EVENT_UNKNOWN')

    def _ref_known(self, event, group_key='group', author_key='author'):
        gid = self._required(event, group_key)
        if gid not in self.groups:
            raise RecognitionError('GROUP_NOT_FOUND')
        author = self._required(event, author_key)
        ref = _ref(gid, author)
        if ref not in self.authority:
            self.authority[ref] = UNCONFIRMED
        return ref

    @staticmethod
    def _required(event, key):
        value = event.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise RecognitionError('RECOGNITION_FIELDS')
        return value

    # ------------------------------------------------------------------ 重算
    def components(self):
        """返回互认图的连通组件列表，每个组件为作者引用的集合。"""
        adjacency = {}
        for ref_a, ref_b in self.edges.values():
            adjacency.setdefault(ref_a, set()).add(ref_b)
            adjacency.setdefault(ref_b, set()).add(ref_a)
        seen, components = set(), []
        for start in adjacency:
            if start in seen:
                continue
            stack, component = [start], set()
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                component.add(node)
                stack.extend(adjacency[node])
            components.append(component)
        # 没有任何互认边的作者各自成独立组件，保证状态覆盖全部登记作者。
        for ref in self.authority:
            if ref not in seen:
                components.append({ref})
        return components

    def conflict_components(self):
        """返回 (组件, 互斥权威编号列表) 的冲突组件，组件只计算一次。"""
        result = []
        for component in self.components():
            numbers = sorted({self.authority[ref]
                              for ref in component if self.authority.get(ref)})
            if len(numbers) > 1:
                result.append((component, numbers))
        return result

    def conflicts(self):
        """返回冲突明细：组件序号 -> 该组件上互斥的非零权威编号。"""
        return {index: numbers for index, (_, numbers)
                in enumerate(self.conflict_components())}

    def groups_in_conflict(self):
        touched = set()
        for component, _ in self.conflict_components():
            touched.update(ref.split('/', 1)[0] for ref in component)
        return touched

    def conflicts_evidence(self):
        evidence = []
        for component, numbers in self.conflict_components():
            refs = set(component)
            edges = sorted(claim for claim, (a, b) in self.edges.items()
                           if a in refs and b in refs)
            evidence.append(dict(authors=sorted(component),
                                 authorities=numbers, claims=edges))
        return evidence

    def status(self):
        """计算每个组的工作台状态。

        READY      组内核验合格且不在任何权威冲突组件上，可签发；
        HELD       组内核验不合格（人数等内部核验未通过）；
        SUSPENDED  组内核验合格但被互认权威冲突牵连，暂缓；
        冲突组件内本身核验不合格的组仍记 HELD（内部问题优先暴露）。
        """
        tainted = self.groups_in_conflict()
        result = {}
        for gid, headcount_ok in sorted(self.groups.items()):
            if not headcount_ok:
                result[gid] = 'HELD'
            elif gid in tainted:
                result[gid] = 'SUSPENDED'
            else:
                result[gid] = 'READY'
        return result

    def releasable(self, gids):
        """给定组集合是否当前全部具备签发资格。"""
        status = self.status()
        return bool(gids) and all(status.get(gid) == 'READY' for gid in gids)

    def snapshot(self):
        return dict(sequence=self.sequence,
                    groups=sorted(self.groups),
                    recognitions=sorted(self.edges),
                    revoked=sorted(self.revoked),
                    conflicts=self.conflicts_evidence(),
                    status=self.status())
