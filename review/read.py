import hashlib

from archive.envelope import EnvelopeFormatError, PackageEnvelope, decode_envelope
from archive.manifest import ManifestFormatError, MemberBinding, OrderManifest, decode_manifest
from archive.volume import VolumeEnvelope, VolumeFormatError, decode_volume
from layout.shape import row_slot_count
from layout.stripe import StripeError
from review.assemble import assemble_result
from review.result import ReviewResult
from review.validate import PackageValidationError, validate_package


def read_package(payload: bytes) -> ReviewResult:
    """Validate and read a detached package without accessing the source catalog."""
    try:
        package = decode_envelope(payload)
        slot_count = validate_package(package)
        return assemble_result(package, slot_count)
    except (EnvelopeFormatError, StripeError) as exc:
        raise PackageValidationError(str(exc)) from exc


def _bind_members(plan: OrderManifest, volumes: object) -> tuple[bytes, ...]:
    """Match arrived bytes to manifest members by digest, never by arrival order."""
    if not isinstance(volumes, (list, tuple)):
        raise PackageValidationError('order volumes must arrive as a list or tuple of member bytes')
    if len(volumes) != len(plan.volumes):
        raise PackageValidationError('arrived volume count differs from the manifest members')
    claimed = {}
    for item in volumes:
        if not isinstance(item, bytes):
            raise PackageValidationError('each arrived volume must be bytes')
        digest = hashlib.sha256(item).hexdigest()
        if digest in claimed:
            raise PackageValidationError('an arrived volume duplicates another')
        claimed[digest] = item
    ordered = []
    for member in plan.volumes:
        payload = claimed.get(member.sha256)
        if payload is None:
            raise PackageValidationError('a manifest member is missing or a foreign volume arrived')
        ordered.append(payload)
    return tuple(ordered)


def _check_member(plan: OrderManifest, member: MemberBinding, volume: VolumeEnvelope) -> None:
    if volume.order_id != plan.order_id:
        raise PackageValidationError('volume order does not match the manifest')
    if volume.revision_id != plan.revision_id:
        raise PackageValidationError('volume revision does not match the manifest')
    if volume.station != member.station:
        raise PackageValidationError('volume station does not match the manifest')
    if (volume.start, volume.stop) != (member.start, member.stop):
        raise PackageValidationError('volume window does not match the manifest')
    cost = sum(1 + row_slot_count(row) for row in volume.rows)
    if cost != plan.costs[member.station]:
        raise PackageValidationError('volume content does not match the manifest cost')


def read_order(manifest: bytes, volumes) -> ReviewResult:
    """Validate a detached order offline and merge its members in source row order.

    Every manifest member must arrive exactly once; any bad manifest, missing,
    extra, duplicate, foreign or corrupt volume rejects the whole order.
    """
    try:
        plan = decode_manifest(manifest)
        ordered = _bind_members(plan, volumes)
        rows = []
        for member, payload in zip(plan.volumes, ordered):
            volume = decode_volume(payload)
            _check_member(plan, member, volume)
            envelope = PackageEnvelope(
                volume.revision_id, volume.start, volume.stop,
                volume.rows, volume.temperature, volume.pressure,
            )
            slot_count = validate_package(envelope)
            rows.extend(assemble_result(envelope, slot_count).rows)
        return ReviewResult(tuple(rows))
    except (ManifestFormatError, VolumeFormatError, StripeError) as exc:
        raise PackageValidationError(str(exc)) from exc
