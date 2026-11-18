import hashlib
import sqlite3
from sqlite3 import Connection

from archive.manifest import MemberBinding, OrderManifest, encode_manifest
from archive.orders import next_order_id, store_order
from catalog.lifecycle import load_available_revision
from catalog.schema import write_transaction
from catalog.source import SourceRevision
from layout.codec import decode_positions, encode_positions
from layout.shape import row_slot_count
from layout.stripe import Stripe, StripeError
from publish.commit import PublicationCommitError, commit_publication
from publish.package import PackageBuildError, build_package, build_volume
from publish.plan import plan_cuts, row_costs
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


def _check_order_window(source: SourceRevision, start: int, stop: int) -> None:
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop <= len(source.rows):
        raise InvalidWindow('order window must be a nonempty half-open slice of the source row sequence')


def _check_order_caps(caps: object) -> None:
    if not isinstance(caps, (list, tuple)) or not caps:
        raise ValueError('order caps must be a nonempty list of positive integers')
    if any(type(cap) is not int or cap < 1 for cap in caps):
        raise ValueError('order caps must be a nonempty list of positive integers')


def _build_volume(source: SourceRevision, order_id: int, station: int, start: int, stop: int) -> bytes:
    rows = source.rows[start:stop]
    first_slot = sum(map(row_slot_count, source.rows[:start]))
    end_slot = first_slot + sum(map(row_slot_count, rows))
    source_slots = end_slot + sum(map(row_slot_count, source.rows[stop:]))
    try:
        temperature = _project_stripe(source.temperature, source_slots, first_slot, end_slot)
        pressure = _project_stripe(source.pressure, source_slots, first_slot, end_slot)
    except StripeError as exc:
        raise PackageBuildError(f'invalid source stripe: {exc}') from exc
    return build_volume(order_id, source.revision_id, station, start, stop, rows, temperature, pressure)


def publish_order(
    db: Connection, revision_id: int, start: int, stop: int, caps: list[int]
) -> tuple[int, bytes]:
    """Issue one whole order partitioned across stations and commit it atomically.

    Return ``(order_id, manifest)``. The manifest and every member volume are
    stored in a single transaction: any storage or commit failure rolls the
    whole order back, and the order can be issued again once the fault clears.
    """
    try:
        with write_transaction(db):
            source = load_available_revision(db, revision_id)
            _check_order_window(source, start, stop)
            _check_order_caps(caps)
            planned = plan_cuts(row_costs(source.rows[start:stop]), caps)
            if planned is None:
                raise ValueError('no feasible partition stays within the station caps')
            cuts, costs = planned
            order_id = next_order_id(db)
            volumes = []
            bindings = []
            first = start
            for station, last in enumerate([start + cut for cut in cuts] + [stop]):
                payload = _build_volume(source, order_id, station, first, last)
                volumes.append(payload)
                bindings.append(MemberBinding(station, first, last, hashlib.sha256(payload).hexdigest()))
                first = last
            manifest = encode_manifest(OrderManifest(
                order_id,
                source.revision_id,
                start,
                stop,
                tuple(start + cut for cut in cuts),
                costs,
                tuple(bindings),
            ))
            store_order(db, order_id, source.revision_id, start, stop, manifest, volumes)
    except sqlite3.Error as exc:
        raise PublicationCommitError(f'order publication could not be committed: {exc}') from exc
    return order_id, manifest
