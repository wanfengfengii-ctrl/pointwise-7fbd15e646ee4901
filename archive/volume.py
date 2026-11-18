"""整单成员卷的封装格式。

每卷是 UTF-8 JSON 对象，除对应 V1 窗口的 revision_id、start、stop、
rows、temperature、pressure 外，还嵌入 order_id 与 station 表明签发
归属与序位。因此即使两张单的某卷源修订、边界和正文完全相同，卷字节
也各自不同，复核时不会混收。
"""

import json
from dataclasses import dataclass

from layout.shape import FurnaceRow, ShapeError, parse_shape, shape_to_wire
from layout.stripe import Stripe, StripeError, parse_stripe, stripe_to_wire


VOLUME_FORMAT_VERSION = 1
_FIELDS = {'version', 'order_id', 'revision_id', 'station', 'start', 'stop', 'rows', 'temperature', 'pressure'}


class VolumeFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VolumeEnvelope:
    order_id: int
    revision_id: int
    station: int
    start: int
    stop: int
    rows: tuple[FurnaceRow, ...]
    temperature: Stripe
    pressure: Stripe


def _check_binding(order_id: int, revision_id: int, station: int, start: int, stop: int, row_count: int) -> None:
    if type(order_id) is not int or order_id <= 0:
        raise VolumeFormatError('order_id must be a positive integer')
    if type(revision_id) is not int or revision_id <= 0:
        raise VolumeFormatError('revision_id must be a positive integer')
    if type(station) is not int or station < 0:
        raise VolumeFormatError('station must be a nonnegative integer')
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop:
        raise VolumeFormatError('volume needs a nonempty half-open row window')
    if stop - start != row_count:
        raise VolumeFormatError('volume row count differs from the window width')


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = {}
    for name, value in pairs:
        if name in fields:
            raise VolumeFormatError(f'duplicate field {name!r}')
        fields[name] = value
    return fields


def encode_volume(volume: VolumeEnvelope) -> bytes:
    _check_binding(volume.order_id, volume.revision_id, volume.station, volume.start, volume.stop, len(volume.rows))
    wire = {
        'version': VOLUME_FORMAT_VERSION,
        'order_id': volume.order_id,
        'revision_id': volume.revision_id,
        'station': volume.station,
        'start': volume.start,
        'stop': volume.stop,
        'rows': shape_to_wire(volume.rows),
        'temperature': stripe_to_wire(volume.temperature),
        'pressure': stripe_to_wire(volume.pressure),
    }
    try:
        return json.dumps(wire, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise VolumeFormatError('volume cannot be represented as JSON') from exc


def decode_volume(payload: bytes) -> VolumeEnvelope:
    if not isinstance(payload, bytes):
        raise VolumeFormatError('volume input must be bytes')
    try:
        wire = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_fields)
    except VolumeFormatError:
        raise
    except (ValueError, RecursionError) as exc:
        raise VolumeFormatError('volume is not a UTF-8 JSON document') from exc
    if not isinstance(wire, dict) or wire.keys() != _FIELDS:
        raise VolumeFormatError('volume fields do not match the order format')
    version = wire['version']
    if type(version) is not int or version != VOLUME_FORMAT_VERSION:
        raise VolumeFormatError(f'unsupported volume version {version!r}')
    try:
        rows = parse_shape(wire['rows'])
        temperature = parse_stripe(wire['temperature'])
        pressure = parse_stripe(wire['pressure'])
    except (ShapeError, StripeError) as exc:
        raise VolumeFormatError(str(exc)) from exc
    _check_binding(wire['order_id'], wire['revision_id'], wire['station'], wire['start'], wire['stop'], len(rows))
    return VolumeEnvelope(
        wire['order_id'], wire['revision_id'], wire['station'],
        wire['start'], wire['stop'], rows, temperature, pressure,
    )
