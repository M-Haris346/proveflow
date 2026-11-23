# ruff: noqa
"""SYNTHETIC AgentDojo-shaped file for proveflow tests (read by AST; never imported or run)."""

from collections import defaultdict

_V1_SUITES = {
    "workspace": workspace_task_suite,
    "travel": travel_task_suite,
    "banking": banking_task_suite,
    "slack": slack_task_suite,
}

_V1_2_2_SUITES = {
    "workspace": workspace_task_suite.get_new_version((1, 2, 2)),
    "travel": travel_task_suite,
    "banking": banking_task_suite.get_new_version((1, 2, 2)),
    "slack": slack_task_suite.get_new_version((1, 2, 0)),
}

_SUITES = defaultdict(dict, {"v1": _V1_SUITES, "v1.2.2": _V1_2_2_SUITES})
