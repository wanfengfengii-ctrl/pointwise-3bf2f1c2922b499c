import sqlite3

from corrections.store import initialize_correction_store
from snapshots.store import initialize_revision_store

from .commit import initialize_publication_store
from .evidence import SealReceipt as SealReceipt
from .evidence import SealedDay as SealedDay
from .read import read_sealed_day as read_sealed_day
from .reconcile import seal_day as seal_day


def initialize_source(db: sqlite3.Connection, origin: str) -> None:
    initialize_publication_store(db, origin)
    initialize_revision_store(db)
    initialize_correction_store(db)
