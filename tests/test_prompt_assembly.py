"""Golden tests for the modular system-prompt assembly (hierarchy + modes).

These guard against the regressions that motivated the rewrite: an inverted
authority hierarchy (repo AGENTS.md overriding the system prompt), the absence of
a consultative mode, and provider policy leaking into the brand-neutral engine.
"""

from on_core.prompt import construct_system_prompt


def test_workspace_mode_has_development_pack() -> None:
    prompt = construct_system_prompt(working_dir="/work", mode="workspace")
    assert "Mode: Workspace (development)" in prompt
    assert "/work" in prompt
    assert "Mode: Consultative" not in prompt


def test_consultative_mode_is_advisory_and_makes_no_workspace_claims() -> None:
    prompt = construct_system_prompt(mode="consultative")
    assert "Mode: Consultative" in prompt
    assert "no local filesystem or shell access" in prompt
    assert "Mode: Workspace (development)" not in prompt
    # Consultative must NOT force a tool call every turn (that breaks advisory mode).
    assert "not required to call a tool every turn" in prompt


def test_authority_hierarchy_makes_agents_md_advisory_not_overriding() -> None:
    prompt = construct_system_prompt(working_dir="/work")
    assert "Instruction authority" in prompt
    assert "advisory only" in prompt
    # The inverted-authority wording must be gone.
    assert "same authority as this system prompt" not in prompt
    assert "CRITICAL FAILURE" not in prompt


def test_integration_policy_injected_only_when_provided() -> None:
    marker = "AZURE-DEVOPS-POLICY-MARKER"
    with_policy = construct_system_prompt(
        working_dir="/work", integration_policy=f"### Integration\n{marker}"
    )
    without_policy = construct_system_prompt(working_dir="/work")
    assert marker in with_policy
    assert marker not in without_policy


def test_integration_policy_precedes_mode_pack() -> None:
    # The physical assembly order must match the declared authority hierarchy:
    # integration policy (layer 3) appears before the mode pack (layer 5).
    marker = "AZURE-DEVOPS-POLICY-MARKER"
    prompt = construct_system_prompt(
        working_dir="/work",
        mode="workspace",
        integration_policy=f"### Integration\n{marker}",
    )
    assert prompt.index(marker) < prompt.index("Mode: Workspace (development)")


def test_software_engineering_discipline_pack_present() -> None:
    # The neutral SWE identity/discipline pack is always present, before the mode pack,
    # and introduces no brand (Azure/Android/Entra) of its own.
    from on_core.prompt import SOFTWARE_ENGINEERING

    prompt = construct_system_prompt(working_dir="/work", mode="workspace")
    assert "Software engineering discipline" in prompt
    assert "Understand before changing" in prompt
    assert prompt.index("Software engineering discipline") < prompt.index(
        "Mode: Workspace (development)"
    )
    for brand in ("Azure", "Android", "Entra"):
        assert brand not in SOFTWARE_ENGINEERING


def test_operating_context_injected_only_when_provided() -> None:
    marker = "OPERATING-CONTEXT-MARKER"
    with_ctx = construct_system_prompt(
        working_dir="/work", operating_context=f"## Operating context\n{marker}"
    )
    without_ctx = construct_system_prompt(working_dir="/work")
    assert marker in with_ctx
    assert marker not in without_ctx


def test_operating_context_between_integration_and_mode() -> None:
    # Physical order must match the authority hierarchy:
    # integration (3) < operating context (4) < mode (5).
    integration = "AZURE-DEVOPS-POLICY-MARKER"
    ctx = "OPERATING-CONTEXT-MARKER"
    prompt = construct_system_prompt(
        working_dir="/work",
        mode="workspace",
        integration_policy=f"### Integration\n{integration}",
        operating_context=f"## Operating context\n{ctx}",
    )
    assert prompt.index(integration) < prompt.index(ctx)
    assert prompt.index(ctx) < prompt.index("Mode: Workspace (development)")


def test_human_approval_gate_present_in_both_modes() -> None:
    for mode in ("workspace", "consultative"):
        prompt = construct_system_prompt(working_dir="/work", mode=mode)
        assert "Human-approval gate" in prompt
        assert "never assume approval" in prompt.lower()


def test_repo_custom_instructions_present_but_subordinate() -> None:
    prompt = construct_system_prompt(
        working_dir="/work", repo_custom_instructions="Prefer pytest over unittest."
    )
    assert "Repository-specific Custom Instructions" in prompt
    assert "Prefer pytest over unittest." in prompt
    assert "subordinate to the layers above" in prompt


def test_instruction_source_boundary_is_stated() -> None:
    prompt = construct_system_prompt(mode="consultative")
    assert "information, not instructions" in prompt
