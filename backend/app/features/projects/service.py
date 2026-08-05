from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.features.projects.schemas import (
    PriceComparison,
    ProductComparisonItem,
    ProductComparisonResponse,
    ProductCreate,
    ProductResponse,
    ProductRole,
    ProductUpdate,
    ResearchProjectCreate,
    ResearchProjectResponse,
    ResearchProjectUpdate,
)


class ProjectStore(Protocol):
    def create_project(self, data: dict[str, object]) -> dict[str, object]: ...

    def list_projects(self) -> list[dict[str, object]]: ...

    def get_project(self, project_id: UUID) -> dict[str, object]: ...

    def update_project(self, project_id: UUID, data: dict[str, object]) -> dict[str, object]: ...

    def create_product(self, data: dict[str, object]) -> dict[str, object]: ...

    def list_products(self, project_id: UUID) -> list[dict[str, object]]: ...

    def get_product(self, project_id: UUID, product_id: UUID) -> dict[str, object]: ...

    def update_product(
        self, project_id: UUID, product_id: UUID, data: dict[str, object]
    ) -> dict[str, object]: ...

    def document_coverage(self, project_id: UUID) -> tuple[dict[str, int], dict[str, int]]: ...


class ProjectService:
    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    async def create_project(self, payload: ResearchProjectCreate) -> ResearchProjectResponse:
        record = await asyncio.to_thread(self._store.create_project, payload.model_dump())
        return ResearchProjectResponse.model_validate(record)

    async def list_projects(self) -> list[ResearchProjectResponse]:
        records = await asyncio.to_thread(self._store.list_projects)
        return [ResearchProjectResponse.model_validate(record) for record in records]

    async def get_project(self, project_id: UUID) -> ResearchProjectResponse:
        record = await asyncio.to_thread(self._store.get_project, project_id)
        return ResearchProjectResponse.model_validate(record)

    async def update_project(
        self, project_id: UUID, payload: ResearchProjectUpdate
    ) -> ResearchProjectResponse:
        data = payload.model_dump(exclude_unset=True)
        if not data:
            return await self.get_project(project_id)
        if "status" in data:
            data["status"] = data["status"].value
        record = await asyncio.to_thread(self._store.update_project, project_id, data)
        return ResearchProjectResponse.model_validate(record)

    async def create_product(self, project_id: UUID, payload: ProductCreate) -> ProductResponse:
        await asyncio.to_thread(self._store.get_project, project_id)
        data = payload.model_dump(mode="json")
        data["project_id"] = str(project_id)
        record = await asyncio.to_thread(self._store.create_product, data)
        return ProductResponse.model_validate(record)

    async def list_products(self, project_id: UUID) -> list[ProductResponse]:
        await asyncio.to_thread(self._store.get_project, project_id)
        records = await asyncio.to_thread(self._store.list_products, project_id)
        return [ProductResponse.model_validate(record) for record in records]

    async def update_product(
        self, project_id: UUID, product_id: UUID, payload: ProductUpdate
    ) -> ProductResponse:
        data = payload.model_dump(mode="json", exclude_unset=True)
        if not data:
            record = await asyncio.to_thread(self._store.get_product, project_id, product_id)
        else:
            record = await asyncio.to_thread(
                self._store.update_product, project_id, product_id, data
            )
        return ProductResponse.model_validate(record)

    async def compare_products(self, project_id: UUID) -> ProductComparisonResponse:
        await asyncio.to_thread(self._store.get_project, project_id)
        records, coverage = await asyncio.gather(
            asyncio.to_thread(self._store.list_products, project_id),
            asyncio.to_thread(self._store.document_coverage, project_id),
        )
        products = [ProductResponse.model_validate(record) for record in records]
        total, indexed = coverage
        own_count = sum(product.role == ProductRole.OWN for product in products)
        competitor_count = sum(product.role == ProductRole.COMPETITOR for product in products)
        return ProductComparisonResponse(
            project_id=project_id,
            own_product_count=own_count,
            competitor_product_count=competitor_count,
            price_comparisons=self._price_comparisons(products),
            products=[
                ProductComparisonItem(
                    product=product,
                    document_count=total.get(str(product.id), 0),
                    indexed_document_count=indexed.get(str(product.id), 0),
                )
                for product in products
            ],
        )

    @staticmethod
    def _price_comparisons(products: list[ProductResponse]) -> list[PriceComparison]:
        grouped: dict[str, dict[ProductRole, list[Decimal]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for product in products:
            if product.price is not None and product.currency:
                grouped[product.currency][product.role].append(product.price)

        comparisons: list[PriceComparison] = []
        for currency, values in sorted(grouped.items()):
            own_prices = values[ProductRole.OWN]
            competitor_prices = values[ProductRole.COMPETITOR]
            own_average = sum(own_prices) / len(own_prices) if own_prices else None
            competitor_average = (
                sum(competitor_prices) / len(competitor_prices) if competitor_prices else None
            )
            difference = (
                own_average - competitor_average
                if own_average is not None and competitor_average is not None
                else None
            )
            comparisons.append(
                PriceComparison(
                    currency=currency,
                    own_average=own_average,
                    competitor_average=competitor_average,
                    difference=difference,
                )
            )
        return comparisons
