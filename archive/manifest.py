"""整单清单与成员绑定。

清单是 UTF-8 JSON 对象。可读字段 order_id、revision_id、start、stop、
cuts、costs 之外，volumes 按工位次序列出每个成员的 station、行窗口
[start, stop) 和卷字节的 SHA-256 摘要。成员身份只靠摘要匹配清单裁定，
不按到件顺序或文件名推定；每卷内部又嵌入 order_id、station 与窗口，
复核时逐字段与清单对质，并按卷内行重新核算成本与 costs 对质，清单
由此绑定实际签发的成员字节。整单提交时清单行与全部卷行在同一个
BEGIN IMMEDIATE 事务里写入，单号在事务内预定（MAX+1），任一处存储
或提交失败都整体回滚，不留整单、成员或成功记录。
"""

import json
from dataclasses import dataclass


MANIFEST_FORMAT_VERSION = 1
_FIELDS = {'version', 'order_id', 'revision_id', 'start', 'stop', 'cuts', 'costs', 'volumes'}
_MEMBER_FIELDS = {'station', 'start', 'stop', 'sha256'}
_HEX_DIGITS = set('0123456789abcdef')


class ManifestFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MemberBinding:
    station: int
    start: int
    stop: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OrderManifest:
    order_id: int
    revision_id: int
    start: int
    stop: int
    cuts: tuple[int, ...]
    costs: tuple[int, ...]
    volumes: tuple[MemberBinding, ...]


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = {}
    for name, value in pairs:
        if name in fields:
            raise ManifestFormatError(f'duplicate field {name!r}')
        fields[name] = value
    return fields


def encode_manifest(manifest: OrderManifest) -> bytes:
    wire = {
        'version': MANIFEST_FORMAT_VERSION,
        'order_id': manifest.order_id,
        'revision_id': manifest.revision_id,
        'start': manifest.start,
        'stop': manifest.stop,
        'cuts': list(manifest.cuts),
        'costs': list(manifest.costs),
        'volumes': [
            {
                'station': member.station,
                'start': member.start,
                'stop': member.stop,
                'sha256': member.sha256,
            }
            for member in manifest.volumes
        ],
    }
    try:
        return json.dumps(wire, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ManifestFormatError('manifest cannot be represented as JSON') from exc


def _check_digest(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX_DIGITS for char in value):
        raise ManifestFormatError('member sha256 must be 64 lowercase hex characters')
    return value


def _check_member(raw: object, station: int) -> MemberBinding:
    if not isinstance(raw, dict) or raw.keys() != _MEMBER_FIELDS:
        raise ManifestFormatError('member fields do not match the order format')
    if type(raw['station']) is not int or raw['station'] != station:
        raise ManifestFormatError('member station does not match the manifest order')
    start, stop = raw['start'], raw['stop']
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop:
        raise ManifestFormatError('member needs a nonempty half-open row window')
    return MemberBinding(station, start, stop, _check_digest(raw['sha256']))


def decode_manifest(payload: bytes) -> OrderManifest:
    if not isinstance(payload, bytes):
        raise ManifestFormatError('manifest input must be bytes')
    try:
        wire = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique_fields)
    except ManifestFormatError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ManifestFormatError('manifest is not a UTF-8 JSON document') from exc
    if not isinstance(wire, dict) or wire.keys() != _FIELDS:
        raise ManifestFormatError('manifest fields do not match the order format')
    version = wire['version']
    if type(version) is not int or version != MANIFEST_FORMAT_VERSION:
        raise ManifestFormatError(f'unsupported manifest version {version!r}')
    order_id, revision_id = wire['order_id'], wire['revision_id']
    if type(order_id) is not int or order_id <= 0:
        raise ManifestFormatError('order_id must be a positive integer')
    if type(revision_id) is not int or revision_id <= 0:
        raise ManifestFormatError('revision_id must be a positive integer')
    start, stop = wire['start'], wire['stop']
    if type(start) is not int or type(stop) is not int or not 0 <= start < stop:
        raise ManifestFormatError('manifest needs a nonempty half-open row window')
    cuts = wire['cuts']
    if not isinstance(cuts, list) or any(type(cut) is not int for cut in cuts):
        raise ManifestFormatError('cuts must be a list of row positions')
    if any(cut <= start or cut >= stop for cut in cuts):
        raise ManifestFormatError('cuts must stay inside the window')
    if any(earlier >= later for earlier, later in zip(cuts, cuts[1:])):
        raise ManifestFormatError('cuts must strictly increase')
    costs = wire['costs']
    if not isinstance(costs, list) or not costs or any(type(cost) is not int or cost < 1 for cost in costs):
        raise ManifestFormatError('costs must be a nonempty list of positive integers')
    if len(costs) != len(cuts) + 1:
        raise ManifestFormatError('costs do not match the cut count')
    members = wire['volumes']
    if not isinstance(members, list) or len(members) != len(costs):
        raise ManifestFormatError('members do not match the station count')
    volumes = tuple(_check_member(raw, station) for station, raw in enumerate(members))
    if volumes[0].start != start or volumes[-1].stop != stop:
        raise ManifestFormatError('member windows do not cover the manifest window')
    if any(earlier.stop != later.start for earlier, later in zip(volumes, volumes[1:])):
        raise ManifestFormatError('member windows must be contiguous')
    if [member.stop for member in volumes[:-1]] != list(cuts):
        raise ManifestFormatError('member windows do not match the manifest cuts')
    return OrderManifest(order_id, revision_id, start, stop, tuple(cuts), tuple(costs), volumes)
