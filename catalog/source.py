import json
from dataclasses import dataclass
from sqlite3 import Connection

from catalog.schema import is_record_id
from layout.shape import FurnaceRow, parse_shape, shape_to_wire
from layout.stripe import Stripe, parse_stripe, stripe_to_wire


@dataclass(frozen=True, slots=True)
class SourceRevision:
    revision_id: int
    batch_id: str
    declared_revision: str
    rows: tuple[FurnaceRow, ...]
    temperature: Stripe
    pressure: Stripe
    retired: bool


def store_revision(
    db: Connection,
    batch_id: str,
    declared_revision: str,
    rows: tuple[FurnaceRow, ...],
    temperature: Stripe,
    pressure: Stripe,
) -> int:
    """Append a validated snapshot in the caller's registration transaction."""
    observations = json.dumps(
        {
            'rows': shape_to_wire(rows),
            'temperature': stripe_to_wire(temperature),
            'pressure': stripe_to_wire(pressure),
        },
        separators=(',', ':'),
    )
    cursor = db.execute(
        'INSERT INTO source_revisions (batch_id, declared_revision, observations) VALUES (?, ?, ?)',
        (batch_id, declared_revision, observations),
    )
    return cursor.lastrowid


def load_revision(db: Connection, revision_id: int) -> SourceRevision | None:
    if not is_record_id(revision_id):
        return None
    entry = db.execute(
        '''SELECT batch_id, declared_revision, observations, retired
           FROM source_revisions WHERE revision_id = ?''',
        (revision_id,),
    ).fetchone()
    if entry is None:
        return None
    batch_id, declared_revision, observations, retired = entry
    wire = json.loads(observations)
    return SourceRevision(
        revision_id,
        batch_id,
        declared_revision,
        parse_shape(wire['rows']),
        parse_stripe(wire['temperature']),
        parse_stripe(wire['pressure']),
        bool(retired),
    )
