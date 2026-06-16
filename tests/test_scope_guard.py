from __future__ import annotations

from langchain_core.tools import StructuredTool

from agent.composition.scope_guard import enforce_profile_scope


def _project_tool(name: str = "repo_list_repos_by_project") -> StructuredTool:
    def _run(project: str = "") -> str:
        return f"ran:{project}"

    async def _arun(project: str = "") -> str:
        return f"ran:{project}"

    return StructuredTool.from_function(func=_run, coroutine=_arun, name=name, description="d")


def _repo_tool(name: str = "repo_get") -> StructuredTool:
    def _run(repository: str = "") -> str:
        return f"repo:{repository}"

    async def _arun(repository: str = "") -> str:
        return f"repo:{repository}"

    return StructuredTool.from_function(func=_run, coroutine=_arun, name=name, description="d")


def _no_arg_tool(name: str = "search_code") -> StructuredTool:
    def _run() -> str:
        return "ok"

    async def _arun() -> str:
        return "ok"

    return StructuredTool.from_function(func=_run, coroutine=_arun, name=name, description="d")


async def test_blocks_out_of_scope_project() -> None:
    [guarded] = enforce_profile_scope([_project_tool()], allowed_projects=["TryController 2.0"])
    out = await guarded.ainvoke({"project": "DevSecOps"})
    assert "Blocked" in out
    assert "DevSecOps" in out


async def test_allows_in_scope_project() -> None:
    [guarded] = enforce_profile_scope([_project_tool()], allowed_projects=["TryController 2.0"])
    assert await guarded.ainvoke({"project": "TryController 2.0"}) == "ran:TryController 2.0"


async def test_tool_without_project_arg_passes() -> None:
    [guarded] = enforce_profile_scope([_no_arg_tool()], allowed_projects=["TryController 2.0"])
    assert await guarded.ainvoke({}) == "ok"


async def test_guid_project_value_passes() -> None:
    # An opaque id cannot be validated against profile *names* → allowed.
    [guarded] = enforce_profile_scope([_project_tool()], allowed_projects=["TryController 2.0"])
    guid = "12345678-1234-1234-1234-123456789abc"
    assert await guarded.ainvoke({"project": guid}) == f"ran:{guid}"


async def test_blocks_out_of_scope_repo() -> None:
    [guarded] = enforce_profile_scope(
        [_repo_tool()], allowed_projects=["P"], allowed_repos=["AppMóvil"]
    )
    assert "Blocked" in await guarded.ainvoke({"repository": "OtherRepo"})
    assert await guarded.ainvoke({"repository": "AppMóvil"}) == "repo:AppMóvil"


def test_noop_when_nothing_to_enforce() -> None:
    tool = _project_tool()
    result = enforce_profile_scope([tool], allowed_projects=[], allowed_repos=[])
    assert result == [tool]  # unwrapped, same object
