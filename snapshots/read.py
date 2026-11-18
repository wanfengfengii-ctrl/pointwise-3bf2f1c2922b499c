import sqlite3

from .revisions import Revision
from .rows import valid_record_number
from .store import load_revision


def read_revision(db: sqlite3.Connection, revision_id: int) -> Revision | None:
    if not valid_record_number(revision_id):
        return None
    return load_revision(db, revision_id)
