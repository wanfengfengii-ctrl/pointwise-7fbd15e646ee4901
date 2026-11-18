import json
from dataclasses import dataclass

from layout.shape import FurnaceRow, ShapeError, parse_shape, shape_to_wire
from layout.stripe import Stripe, StripeError, parse_stripe, stripe_to_wire


PACKAGE_FORMAT_VERSION = 1
_FIELDS = {'version', 'revision_id', 'start', 'stop', 'rows', 'temperature', 'pressure'}


class EnvelopeFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PackageEnvelope:
    revision_id: int
    start: int
    stop: int
    rows: tuple[FurnaceRow, ...]
    temperature: Stripe
    pressure: Stripe


def _check_binding(revision_id: int, start: int, stop: int, row_count: int) -> None:
    if type(revision_id) is not int or revision_id <= 0:
        raise EnvelopeFormatError('revision_id must be a positive integer')
    if type(start) is not int or type(stop) is not int or not 0 <= start <= stop:
        raise EnvelopeFormatError('package needs a valid half-open row window')
    if stop - start != row_count:
        raise EnvelopeFormatError('package row count differs from the window width')


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = {}
    for name, value in pairs:
        if name in fields:
            raise EnvelopeFormatError(f'duplicate field {name!r}')
        fields[name] = value
    return fields


def encode_envelope(package: PackageEnvelope) -> bytes:
    _check_binding(package.revision_id, package.start, package.stop, len(package.rows))
    wire = {
        'version': PACKAGE_FORMAT_VERSION,
        'revision_id': package.revision_id,
        'start': package.start,
        'stop': package.stop,
        'rows': shape_to_wire(package.rows),
        'temperature': stripe_to_wire(package.temperature),
        'pressure': stripe_to_wire(package.pressure),
    }
    try:
        return json.dumps(wire, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise EnvelopeFormatError('package cannot be represented as JSON') from exc


def decode_envelope(payload: bytes) -> PackageEnvelope:
    if not isinstance(payload, bytes):
        raise EnvelopeFormatError('package input must be bytes')
    try:
        wire = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_fields)
    except EnvelopeFormatError:
        raise
    except (ValueError, RecursionError) as exc:
        raise EnvelopeFormatError('package is not a UTF-8 JSON document') from exc
    if not isinstance(wire, dict) or wire.keys() != _FIELDS:
        raise EnvelopeFormatError('package fields do not match the versioned format')
    version = wire['version']
    if type(version) is not int or version != PACKAGE_FORMAT_VERSION:
        raise EnvelopeFormatError(f'unsupported package version {version!r}')
    try:
        rows = parse_shape(wire['rows'])
        temperature = parse_stripe(wire['temperature'])
        pressure = parse_stripe(wire['pressure'])
    except (ShapeError, StripeError) as exc:
        raise EnvelopeFormatError(str(exc)) from exc
    _check_binding(wire['revision_id'], wire['start'], wire['stop'], len(rows))
    return PackageEnvelope(wire['revision_id'], wire['start'], wire['stop'], rows, temperature, pressure)
