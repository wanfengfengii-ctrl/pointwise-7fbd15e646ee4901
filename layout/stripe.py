from dataclasses import dataclass


class StripeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StripeEntry:
    gap: int
    value: int


Stripe = tuple[StripeEntry, ...]


def parse_stripe(raw: object) -> Stripe:
    if not isinstance(raw, list):
        raise StripeError('stripe must be a list')
    entries = []
    for index, item in enumerate(raw):
        if not isinstance(item, list) or len(item) != 2:
            raise StripeError(f'entry {index} must contain a gap and a value')
        gap, value = item
        if type(gap) is not int or type(value) is not int:
            raise StripeError(f'entry {index} requires two integers')
        entries.append(StripeEntry(gap, value))
    return tuple(entries)


def stripe_to_wire(stripe: Stripe) -> list[list[int]]:
    return [[entry.gap, entry.value] for entry in stripe]
