from __future__ import annotations

from typing import Any

import pytest
from agent.dashboard.routes import router

from agent.dashboard import azure_devops_api


@pytest.mark.asyncio
async def test_work_item_metrics_url_encodes_project_and_counts_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    async def fake_post(
        actor_id: str,
        path: str,
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert actor_id == "entra:user"
        calls.append((path, body, params))
        if path.endswith("/_apis/wit/wiql"):
            return {"workItems": [{"id": 1}, {"id": 2}, {"id": 3}]}
        return {
            "value": [
                {"fields": {"System.State": "Done", "System.WorkItemType": "Bug"}},
                {"fields": {"System.State": "Active", "System.WorkItemType": "Task"}},
                {"fields": {"System.State": "Done", "System.WorkItemType": "Bug"}},
            ]
        }

    monkeypatch.setattr(azure_devops_api, "_ado_post", fake_post)

    metrics = await azure_devops_api.list_work_item_state_counts(
        "entra:user",
        "TryController 2.0",
        period="30d",
    )

    assert calls[0][0] == "/TryController%202.0/_apis/wit/wiql"
    assert calls[1][0] == "/TryController%202.0/_apis/wit/workitemsbatch"
    assert "@Today - 30" in calls[0][1]["query"]
    assert metrics["total"] == 3
    assert metrics["states"] == [
        {"name": "Done", "count": 2},
        {"name": "Active", "count": 1},
    ]
    assert metrics["types"] == [
        {"name": "Bug", "count": 2},
        {"name": "Task", "count": 1},
    ]


@pytest.mark.asyncio
async def test_recent_builds_url_encodes_project(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_get(
        actor_id: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seen.update({"actor_id": actor_id, "path": path, "params": params})
        return {
            "value": [
                {
                    "id": 10,
                    "buildNumber": "20260612.1",
                    "definition": {"name": "Android CI"},
                    "status": "completed",
                    "result": "succeeded",
                    "sourceBranch": "refs/heads/develop",
                    "requestedFor": {"displayName": "Cristian"},
                    "_links": {"web": {"href": "https://dev.azure.com/build/10"}},
                }
            ]
        }

    monkeypatch.setattr(azure_devops_api, "_ado_get", fake_get)

    builds = await azure_devops_api.list_recent_builds("entra:user", "VendaMas 2.0")

    assert seen["path"] == "/VendaMas%202.0/_apis/build/builds"
    assert seen["params"] == {"$top": 10, "queryOrder": "finishTimeDescending"}
    assert builds[0]["definition"] == "Android CI"
    assert builds[0]["source_branch"] == "develop"


def test_azure_usage_route_is_registered() -> None:
    assert any(
        getattr(route, "path", None) == "/dashboard/api/azure/usage" for route in router.routes
    )
