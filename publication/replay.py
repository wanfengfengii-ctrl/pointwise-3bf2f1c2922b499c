from dataclasses import dataclass

from corrections.changes import CorrectionTransaction


State = tuple[int, ...]
CompiledChanges = tuple[tuple[int, int, int], ...]
TransactionStates = tuple[tuple[str, tuple[State, ...]], ...]


@dataclass(frozen=True)
class ReplayResult:
    has_completion: bool
    after: TransactionStates


def _positional_samples(domains: tuple[State, ...], changes: CompiledChanges) -> tuple[State, ...]:
    written = {column: (new,) for column, _, new in changes}
    columns = tuple(written.get(column, values) for column, values in enumerate(domains))
    height = max(map(len, columns), default=1)
    return tuple(tuple(values[min(index, len(values) - 1)] for values in columns)
                 for index in range(height))


def evaluate_replay(row_keys: tuple[str, ...], opening: State, closing: State,
                    transactions: tuple[CorrectionTransaction, ...]) -> ReplayResult:
    columns = {key: column for column, key in enumerate(row_keys)}
    patches = tuple(
        tuple((columns[change.key], change.old, change.new) for change in transaction.changes)
        for transaction in transactions
    )
    domains = [{value} for value in opening]
    pending = patches
    while pending:
        deferred = []
        for changes in pending:
            if all(old in domains[column] for column, old, _ in changes):
                for column, _, new in changes:
                    domains[column].add(new)
            else:
                deferred.append(changes)
        if len(deferred) == len(pending):
            return ReplayResult(False, ())
        pending = tuple(deferred)
    if any(wanted not in values for wanted, values in zip(closing, domains)):
        return ReplayResult(False, ())

    sorted_domains = tuple(tuple(sorted(values)) for values in domains)
    after = tuple((transaction.name, _positional_samples(sorted_domains, changes))
                  for transaction, changes in zip(transactions, patches))
    return ReplayResult(True, after)
