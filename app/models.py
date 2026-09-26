from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from .signals import DEFAULT_SMALL_LIMIT

ENGINE_SHA = "d8f605c273e15cbdcb536ef8e4b076ef892172be"

PRESETS = {
    "ai": {
        "name": "Искусственный интеллект",
        "seeds": ["AI agents", "local AI models", "AI tools"],
        "excluded_categories": ["10", "17", "20"],
    },
    "tech": {
        "name": "Технологии",
        "seeds": ["new smartphones", "laptop review", "new gadgets"],
        "excluded_categories": ["10", "17"],
    },
    "film": {
        "name": "Кино и сериалы",
        "seeds": ["new movie trailer", "new series", "movie review"],
        "excluded_categories": [],
    },
    "custom": {"name": "Моё исследование", "seeds": [], "excluded_categories": []},
}


class ScanConfig(BaseModel):
    name: str = Field(default="Моё исследование", min_length=1, max_length=100)
    profile: Literal["ai", "tech", "film", "custom"] = "custom"
    seeds: list[str] = Field(min_length=1, max_length=6)
    language: Literal["ru", "en"] = "en"
    video_format: Literal["all", "shorts", "videos"] = "all"
    region: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    days: int = Field(default=30, ge=1, le=365)
    max_results: int = Field(default=100, ge=1, le=500)
    credential_id: str = Field(default="default", pattern=r"^[a-zA-Z0-9-]{1,64}$")
    min_views: int = Field(default=1000, ge=0, le=1_000_000_000)
    max_subscribers: int = Field(default=DEFAULT_SMALL_LIMIT, ge=0, le=1_000_000_000)
    min_duration: int = Field(default=0, ge=0, le=86400)
    max_duration: int = Field(default=0, ge=0, le=86400)
    excluded_words: list[str] = Field(default_factory=list, max_length=30)
    excluded_categories: list[str] = Field(default_factory=list, max_length=30)
    order: Literal["mixed", "viewCount", "date", "relevance"] = "mixed"
    extract_phrases: bool = True
    force: bool = False

    @field_validator("max_subscribers")
    @classmethod
    def small_channel_default(cls, value):
        # Legacy zero meant unrestricted; continuation now uses the owner's focus.
        return value or DEFAULT_SMALL_LIMIT

    @field_validator("max_results")
    @classmethod
    def full_pages(cls, value):
        # Legacy configurations (10/25) use a full page at the same search cost.
        return ((value + 49) // 50) * 50

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Введите название")
        return value.strip()

    @field_validator("seeds", "excluded_words")
    @classmethod
    def clean_terms(cls, values):
        clean = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if any(len(v) > 200 for v in clean):
            raise ValueError("Слишком длинный запрос")
        return clean

    @field_validator("excluded_categories")
    @classmethod
    def categories(cls, values):
        if any(not v.isdigit() or len(v) > 3 for v in values):
            raise ValueError("Категории задаются числовыми ID")
        return values


class StartScan(BaseModel):
    config: ScanConfig
    request_id: str = Field(pattern=r"^[a-zA-Z0-9-]{8,80}$")


class Budget(BaseModel):
    search_limit: int = Field(default=100, ge=0, le=100000)
    unit_limit: int = Field(default=10000, ge=0, le=1000000)


class Note(BaseModel):
    favorite: bool = False
    text: str = Field(default="", max_length=5000)


class ScheduleConfig(BaseModel):
    enabled: bool = False
    full_hours: Literal[4, 6, 12, 24] = 4
    monitor_minutes: Literal[30, 60, 120] = 30
    top_limit: Literal[50, 100, 200, 500] = 100
