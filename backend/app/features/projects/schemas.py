from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ProjectStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProductRole(StrEnum):
    OWN = "OWN"
    COMPETITOR = "COMPETITOR"


class ResearchProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    target_platform: str | None = Field(default=None, max_length=80)
    target_audience: str | None = Field(default=None, max_length=500)


class ResearchProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=120)
    target_platform: str | None = Field(default=None, max_length=80)
    target_audience: str | None = Field(default=None, max_length=500)
    status: ProjectStatus | None = None


class ResearchProjectResponse(BaseModel):
    id: UUID
    name: str
    category: str | None
    target_platform: str | None
    target_audience: str | None
    status: ProjectStatus
    created_at: str
    updated_at: str


class ProductCreate(BaseModel):
    role: ProductRole
    name: str = Field(min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, max_length=120)
    external_url: HttpUrl | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=5000)
    attributes: dict[str, object] = Field(default_factory=dict)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, max_length=120)
    external_url: HttpUrl | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=5000)
    attributes: dict[str, object] | None = None


class ProductResponse(BaseModel):
    id: UUID
    project_id: UUID
    role: ProductRole
    name: str
    brand_name: str | None
    external_url: str | None
    price: Decimal | None
    currency: str | None
    description: str | None
    attributes: dict[str, object]
    created_at: str
    updated_at: str


class ProductComparisonItem(BaseModel):
    product: ProductResponse
    document_count: int
    indexed_document_count: int


class PriceComparison(BaseModel):
    currency: str
    own_average: Decimal | None
    competitor_average: Decimal | None
    difference: Decimal | None


class ProductComparisonResponse(BaseModel):
    project_id: UUID
    own_product_count: int
    competitor_product_count: int
    price_comparisons: list[PriceComparison]
    products: list[ProductComparisonItem]
