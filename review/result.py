from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PointReading:
    temperature: int | None
    pressure: int | None


@dataclass(frozen=True, slots=True)
class TrayReview:
    points: tuple[PointReading, ...]


@dataclass(frozen=True, slots=True)
class FurnaceReview:
    row_number: int
    trays: tuple[TrayReview | None, ...] | None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    rows: tuple[FurnaceReview, ...]
