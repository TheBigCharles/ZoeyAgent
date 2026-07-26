"""Memory inspection routes for local debugging."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from app.config import (
    AppDependencies,
    MEMORY_QUERY_FAILED,
    MEMORY_STORE_UNAVAILABLE,
    StructuredAppError,
    exception_details,
    get_app_dependencies,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/semantic")
async def inspect_semantic_memory(
    user_id: str = Query(..., min_length=1),
    query: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    dependencies: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return await _inspect_memory(
        memory_type="semantic",
        user_id=user_id,
        query=query,
        limit=limit,
        dependencies=dependencies,
    )


@router.get("/episodic")
async def inspect_episodic_memory(
    user_id: str = Query(..., min_length=1),
    query: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    dependencies: AppDependencies = Depends(get_app_dependencies),
) -> dict[str, Any]:
    return await _inspect_memory(
        memory_type="episodic",
        user_id=user_id,
        query=query,
        limit=limit,
        dependencies=dependencies,
    )


async def _inspect_memory(
    *,
    memory_type: Literal["semantic", "episodic"],
    user_id: str,
    query: str | None,
    limit: int,
    dependencies: AppDependencies,
) -> dict[str, Any]:
    store = dependencies.store
    if store is None:
        raise StructuredAppError(
            code=MEMORY_STORE_UNAVAILABLE,
            message="Long-term memory store is not enabled",
            status_code=503,
        )

    try:
        if memory_type == "semantic":
            items = await store.search_semantic(user_id, query, limit=limit)
        else:
            items = await store.search_episodic(user_id, query, limit=limit)
    except StructuredAppError:
        raise
    except Exception as exc:
        raise StructuredAppError(
            code=MEMORY_QUERY_FAILED,
            message="Memory query failed",
            details=exception_details(exc),
        ) from exc

    return {
        "memory_type": memory_type,
        "user_id": user_id,
        "query": query,
        "limit": limit,
        "count": len(items),
        "items": items,
    }
