"""Scenario registry. Order here is the order the arena runs."""

from arena.scenarios import (
    cicd_control_plane,
    cloudformation_stack,
    event_pipeline,
    finops_cost_report,
    iam_guardrails,
    platform_inventory,
    serverless_todo,
    static_site,
)

ALL = [
    static_site.scenario,
    serverless_todo.scenario,
    event_pipeline.scenario,
    cloudformation_stack.scenario,
    platform_inventory.scenario,
    finops_cost_report.scenario,
    cicd_control_plane.scenario,
    iam_guardrails.scenario,
]
