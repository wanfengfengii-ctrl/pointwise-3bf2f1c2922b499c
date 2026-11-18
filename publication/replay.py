from dataclasses import dataclass

from corrections.changes import CorrectionTransaction


State = tuple[int, ...]
CompiledChanges = tuple[tuple[int, int, int], ...]
TransactionStates = tuple[tuple[str, tuple[State, ...]], ...]


@dataclass(frozen=True)
class ReplayResult:
    has_completion: bool
    after: TransactionStates


def _matches_old(state: State, changes: CompiledChanges) -> bool:
    return all(state[column] == old for column, old, _ in changes)


def _matches_new(state: State, changes: CompiledChanges) -> bool:
    return all(state[column] == new for column, _, new in changes)


def _apply(state: State, changes: CompiledChanges) -> State:
    updated = list(state)
    for column, _, new in changes:
        updated[column] = new
    return tuple(updated)


def _revert(state: State, changes: CompiledChanges) -> State:
    updated = list(state)
    for column, old, _ in changes:
        updated[column] = old
    return tuple(updated)


def _reachable_nodes(start: tuple[State, int], expand) -> set:
    seen = {start}
    stack = [start]
    while stack:
        for follower in expand(stack.pop()):
            if follower not in seen:
                seen.add(follower)
                stack.append(follower)
    return seen


def evaluate_replay(row_keys: tuple[str, ...], opening: State, closing: State,
                    transactions: tuple[CorrectionTransaction, ...]) -> ReplayResult:
    """重放所选事务：从日初表开始，每笔恰用一次，全部旧值同在当前表匹配才整笔
    生效，终点须等于日终表。在 (表状态, 已用事务掩码) 上分别求日初起的前向可达集
    和日终起的后向可达集；两集相交的节点即完整重放经过的节点。每笔事务的固定证据
    是它在所有完整重放中刚提交时的整表状态，去重排序。"""
    columns = {key: column for column, key in enumerate(row_keys)}
    patches = tuple(
        tuple((columns[change.key], change.old, change.new) for change in transaction.changes)
        for transaction in transactions
    )
    full = (1 << len(patches)) - 1

    def forward_steps(node: tuple[State, int]):
        state, mask = node
        for index, changes in enumerate(patches):
            bit = 1 << index
            if not mask & bit and _matches_old(state, changes):
                yield _apply(state, changes), mask | bit

    def backward_steps(node: tuple[State, int]):
        state, mask = node
        for index, changes in enumerate(patches):
            bit = 1 << index
            if mask & bit and _matches_new(state, changes):
                yield _revert(state, changes), mask ^ bit

    forward = _reachable_nodes((opening, 0), forward_steps)
    if (closing, full) not in forward:
        return ReplayResult(False, ())
    backward = _reachable_nodes((closing, full), backward_steps)
    after = []
    for index, (transaction, changes) in enumerate(zip(transactions, patches)):
        bit = 1 << index
        committed = set()
        for state, mask in forward:
            if mask & bit or not _matches_old(state, changes):
                continue
            committed_state = _apply(state, changes)
            if (committed_state, mask | bit) in backward:
                committed.add(committed_state)
        after.append((transaction.name, tuple(sorted(committed))))
    return ReplayResult(True, tuple(after))
