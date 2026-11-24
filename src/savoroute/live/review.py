"""Explicit human-source review of web leads for a controlled beta.

A search citation alone does not establish a restaurant's cuisine or location.
The registry is an operator-curated allow/deny decision on an *exact* lead and
cited URL. It never fetches URLs and never silently approves model output.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from savoroute.live.contracts import WebRestaurant
from savoroute.live.validation import (
    _country_key,
    _normalize,
    _region_key,
    _safe_url,
    canonical_cuisine,
)


class ReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=80)
    region: str = Field(max_length=80)
    country: str = Field(max_length=80)
    cuisine: str = Field(min_length=2, max_length=80)
    source_url: str = Field(max_length=2048)
    decision: Literal["pending", "approved", "rejected"]
    reviewer: str = Field(default="", max_length=100)
    reviewed_on: str = ""
    evidence_url: str = Field(default="", max_length=2048)
    evidence_note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def valid_review(self) -> ReviewRecord:
        if _safe_url(self.source_url) is None:
            raise ValueError("review source URL must be a public HTTPS URL")
        if self.decision != "pending":
            if len(self.reviewer.strip()) < 3 or not self.reviewed_on:
                raise ValueError("completed review requires a reviewer and date")
            try:
                reviewed = date.fromisoformat(self.reviewed_on)
            except ValueError as exc:
                raise ValueError("invalid review date") from exc
            if reviewed > date.today():
                raise ValueError("future review date")
            if self.decision == "approved":
                if _safe_url(self.evidence_url) is None or len(self.evidence_note.strip()) < 15:
                    raise ValueError("approval requires a public evidence URL and explanatory note")
        return self


def review_key(item: ReviewRecord | WebRestaurant) -> tuple[str, ...]:
    """Pin a judgment to the full identity and actual supporting source."""
    safe_url = _safe_url(item.source_url)
    if safe_url is None:
        raise ValueError("Unsafe review URL")
    return (
        _normalize(item.name), _normalize(item.city), _region_key(item.region),
        _country_key(item.country), canonical_cuisine(item.cuisine), safe_url,
    )


@dataclass(frozen=True)
class LiveReviewRegistry:
    reviews: dict[tuple[str, ...], ReviewRecord]
    max_age_days: int = 90

    @classmethod
    def load(cls, path: str | Path) -> LiveReviewRegistry:
        source = Path(path)
        state = source.lstat()
        if not stat.S_ISREG(state.st_mode) or state.st_size > 512_000:
            raise ValueError("review registry must be a regular JSON file no larger than 512 KB")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema_version", "records"}:
            raise ValueError("review registry must contain schema_version and records")
        if data["schema_version"] != 1 or not isinstance(data["records"], list):
            raise ValueError("unsupported review registry version")
        if len(data["records"]) > 1000:
            raise ValueError("too many review records")
        result: dict[tuple[str, ...], ReviewRecord] = {}
        for entry in data["records"]:
            record = ReviewRecord.model_validate(entry)
            key = review_key(record)
            if key in result:
                raise ValueError("duplicate human review of same lead and source")
            result[key] = record
        return cls(result)

    def admissible(self, lead: WebRestaurant, *, today: date | None = None) -> bool:
        """Only fresh, explicitly approved exact-source leads can be displayed."""
        record = self.reviews.get(review_key(lead))
        if record is None or record.decision != "approved":
            return False
        age = (today or date.today()) - date.fromisoformat(record.reviewed_on)
        return timedelta(days=0) <= age <= timedelta(days=self.max_age_days)

    def filter(self, leads: list[WebRestaurant]) -> list[WebRestaurant]:
        return [lead for lead in leads if self.admissible(lead)]
