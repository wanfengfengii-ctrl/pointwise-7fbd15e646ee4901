from collections.abc import Iterable

from layout.stripe import Stripe, StripeEntry, StripeError


def decode_positions(stripe: Stripe, slot_count: int) -> tuple[tuple[int, int], ...]:
    if type(slot_count) is not int or slot_count < 0:
        raise StripeError('slot count must be a nonnegative integer')
    slot = -1
    positions = []
    for index, entry in enumerate(stripe):
        if not isinstance(entry, StripeEntry):
            raise StripeError(f'entry {index} is not a stripe entry')
        if type(entry.gap) is not int or entry.gap <= 0:
            raise StripeError(f'entry {index} requires a positive integer gap')
        if type(entry.value) is not int:
            raise StripeError(f'entry {index} requires an integer reading')
        slot += entry.gap
        if slot >= slot_count:
            raise StripeError(f'entry {index} reaches slot {slot} in a {slot_count}-slot shape')
        positions.append((slot, entry.value))
    return tuple(positions)


def encode_positions(positions: Iterable[tuple[int, int]]) -> Stripe:
    previous = -1
    entries = []
    for slot, value in positions:
        if type(slot) is not int or slot <= previous:
            raise StripeError('positions must be nonnegative and strictly increasing')
        if type(value) is not int:
            raise StripeError('a stripe reading must be an integer')
        entries.append(StripeEntry(slot - previous, value))
        previous = slot
    return tuple(entries)
