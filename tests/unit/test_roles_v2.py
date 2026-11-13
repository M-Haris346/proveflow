"""Classifier v2 rules (checkpoint 1c, docs/eval/V2_CHANGELOG.md).

Every tool here is SYNTHETIC: invented names, descriptions and schemas, not copies of any
eval-set tool. Each rule has a positive case and the negative case its guard exists for.
"""

from __future__ import annotations

from typing import Any

import pytest

from proveflow.core.tools import SinkSeverity, ToolRole
from proveflow.flows.roles import assigned_roles, classify_tool, sink_severity

S, P, K = ToolRole.UNTRUSTED_SOURCE, ToolRole.PRIVATE_DATA, ToolRole.SINK


def roles(name: str, desc: str = "", props: dict[str, Any] | None = None) -> set[ToolRole]:
    return assigned_roles(classify_tool(name, "srv", desc, {"properties": props or {}}))


# C1 -----------------------------------------------------------------------------------
def test_c1_save_to_file_param_is_local_write() -> None:
    tool = classify_tool(
        "render_chart", "srv", "Render a chart.",
        {"properties": {"outputPath": {"description": "Where the rendered chart is saved."}}},
    )  # fmt: skip
    assert K in assigned_roles(tool)
    assert sink_severity(tool.roles) is SinkSeverity.LOCAL_WRITE


def test_c1_read_path_param_is_not_a_write() -> None:
    props = {"path": {"description": "Path of the document to open."}}
    assert K not in roles("render_chart", "Render a chart.", props)


# C2 + C3 --------------------------------------------------------------------------------
def test_c3_vcs_verb_without_read_verb_is_write() -> None:
    tool = classify_tool("vcs_revert", "srv")
    assert assigned_roles(tool) == {K}
    assert sink_severity(tool.roles) is SinkSeverity.LOCAL_WRITE


def test_c3_vcs_word_with_read_verb_stays_read() -> None:
    assert K not in roles("get_commit")


def test_c2_repository_scoped_tool_without_write_verb_is_private() -> None:
    assert P in roles("vcs_blame", props={"repository": {}})


def test_c2_repository_scoped_write_tool_is_not_private() -> None:
    assert P not in roles("vcs_stash", props={"repository": {}})


# C4 ------------------------------------------------------------------------------------
def test_c4_text_entered_into_page_dialog_is_sink() -> None:
    desc = "Answer the confirmation dialog shown on the page."
    assert K in roles("respond_prompt", desc, {"prompt_text": {}})


def test_c4_search_text_is_not_entered_text() -> None:
    assert K not in roles("wait_for_label", "Wait on the page.", {"selector": {}, "text": {}})


# C5 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["browser_hover_item", "browser_drag_card", "close_tab"])
def test_c5_ui_only_actions_are_not_sinks(name: str) -> None:
    assert K not in roles(name)


def test_c5_close_on_a_persistent_object_is_still_a_write() -> None:
    assert K in roles("close_ticket")


# C6 ------------------------------------------------------------------------------------
def test_c6_write_tool_description_words_are_not_private_output() -> None:
    desc = "Update a file in the personal document store."
    assert P not in roles("update_notes", desc)
    assert P in roles("read_notes_store", desc)  # read tools keep the description signal


# C7 ------------------------------------------------------------------------------------
def test_c7_navigate_alone_is_not_a_source() -> None:
    assert S not in roles("navigate_history")


# C8 ------------------------------------------------------------------------------------
def test_c8_agent_controlled_url_is_sink() -> None:
    assert K in roles("ping_endpoint", "Ping it.", {"url": {}})


# C9 ------------------------------------------------------------------------------------
def test_c9_model_plus_prompt_is_sink() -> None:
    assert K in roles("ask_assistant", "Ask a question.", {"model": {}, "prompt": {}})


def test_c9_prompt_without_model_is_not() -> None:
    assert K not in roles("ask_assistant", "Ask a question.", {"prompt": {}})


# C11a ----------------------------------------------------------------------------------
def test_c11a_capture_noun_without_action_verb_is_source() -> None:
    assert S in roles("page_snapshot")


def test_c11a_capture_noun_with_write_verb_is_not_source() -> None:
    assert S not in roles("delete_screenshot")


# C11c ----------------------------------------------------------------------------------
def test_c11c_description_says_output_untrusted() -> None:
    assert S in roles("lookup_rows", "Rows are UNTRUSTED data from end users.")


# C11d ----------------------------------------------------------------------------------
def test_c11d_arbitrary_code_is_also_source_and_private() -> None:
    assert {S, P} <= roles("sandbox_tool", "Executes arbitrary code in the worker.")


# C12 -----------------------------------------------------------------------------------
def test_c12_header_param_is_sink() -> None:
    tool = classify_tool("configure_client", "srv", "", {"properties": {"customHeaders": {}}})
    assert K in assigned_roles(tool)
    assert sink_severity(tool.roles) is SinkSeverity.NETWORK_EGRESS
