from sqlite3 import Connection

from catalog.source import SourceRevision
from layout.codec import decode_positions, encode_positions
from layout.shape import row_slot_count
from layout.stripe import Stripe, StripeError
from publish.commit import commit_publication
from publish.package import PackageBuildError, build_package
from publish.receipt import PublicationReceipt


class InvalidWindow(ValueError):
    pass


def _project_stripe(stripe: Stripe, source_slots: int, first_slot: int, end_slot: int) -> Stripe:
    positions = decode_positions(stripe, source_slots)
    return encode_positions(
        (slot - first_slot, value)
        for slot, value in positions
        if first_slot <= slot < end_slot
    )


def _build_window(source: SourceRevision, start: int, stop: int) -> bytes:
    if type(start) is not int or type(stop) is not int or not 0 <= start <= stop <= len(source.rows):
        raise InvalidWindow('window must be inside the source row sequence')
    rows = source.rows[start:stop]
    first_slot = sum(map(row_slot_count, source.rows[:start]))
    end_slot = first_slot + sum(map(row_slot_count, rows))
    source_slots = end_slot + sum(map(row_slot_count, source.rows[stop:]))
    try:
        temperature = _project_stripe(source.temperature, source_slots, first_slot, end_slot)
        pressure = _project_stripe(source.pressure, source_slots, first_slot, end_slot)
    except StripeError as exc:
        raise PackageBuildError(f'invalid source stripe: {exc}') from exc
    return build_package(source.revision_id, start, stop, rows, temperature, pressure)


def publish_window(
    db: Connection, revision_id: int, start: int, stop: int
) -> tuple[int, PublicationReceipt]:
    """Publish a fixed source row window and return its committed receipt."""
    return commit_publication(db, revision_id, start, stop, lambda source: _build_window(source, start, stop))
