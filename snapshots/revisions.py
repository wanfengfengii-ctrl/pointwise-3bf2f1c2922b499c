from dataclasses import dataclass

from .rows import ObservationRow


@dataclass(frozen=True)
class Revision:
    revision_id: int
    day: str
    source: str
    rows: tuple[ObservationRow, ...]

    @property
    def row_keys(self) -> tuple[str, ...]:
        return tuple(row.key for row in self.rows)
