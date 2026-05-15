"""Optional Langfuse push for datasets and evaluation runs.

All Langfuse SDK use lives in this module so the rest of the skill stays
decoupled. Functions return None / False on missing config; callers check.
"""
import os
from typing import Optional

from langfuse import Langfuse

REQUIRED_ENV = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
HOST_ENV = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")


def is_configured() -> bool:
    if not all(os.environ.get(k) for k in REQUIRED_ENV):
        return False
    return any(os.environ.get(k) for k in HOST_ENV)


def missing_env_vars() -> list:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if not any(os.environ.get(k) for k in HOST_ENV):
        missing.append("LANGFUSE_HOST or LANGFUSE_BASE_URL")
    return missing


def get_client() -> Optional[Langfuse]:
    if not is_configured():
        return None
    return Langfuse()


def _dataset_exists(client, name: str) -> bool:
    try:
        client.get_dataset(name)
        return True
    except Exception:
        return False


def push_dataset(
    client,
    prompt_name: str,
    run_id: str,
    dataset: list,
    task_description: str,
    inputs_spec: dict,
) -> str:
    """Create-or-upsert the Langfuse dataset and its items.

    Uses deterministic item IDs so re-pushes are idempotent.
    """
    name = f"{prompt_name}-{run_id}"
    if _dataset_exists(client, name):
        print(f"⚠ Dataset {name} exists in Langfuse — upserting items from local")
    else:
        client.create_dataset(
            name=name,
            description=task_description,
            metadata={
                "prompt_name": prompt_name,
                "run_id": run_id,
                "dataset_size": len(dataset),
                "inputs_spec": inputs_spec,
            },
        )
    for i, case in enumerate(dataset):
        client.create_dataset_item(
            dataset_name=name,
            id=f"{prompt_name}-{run_id}-item-{i}",
            input=case["prompt_inputs"],
            expected_output=case["solution_criteria"],
            metadata={"scenario": case.get("scenario")},
        )
    return name


def push_run_case(
    client,
    dataset_name: str,
    item_index: int,
    run_id: str,
    version: str,
    prompt_name: str,
    rendered_prompt: str,
    output: str,
    score: int,
    reasoning: str,
    model: str,
    latency_ms: int,
) -> None:
    """Create a span + score for one evaluated case and link to its dataset run."""
    item_id = f"{prompt_name}-{run_id}-item-{item_index}"
    dataset = client.get_dataset(dataset_name)
    item = next((i for i in dataset.items if i.id == item_id), None)
    if item is None:
        raise ValueError(f"Dataset item {item_id} not found in {dataset_name}")
    with client.start_as_current_observation(
        name=f"{prompt_name}/{run_id}/{version}/case-{item_index}",
        as_type="span",
        input=rendered_prompt,
        output=output,
        metadata={"model": model, "latency_ms": latency_ms, "version": version, "raw_score": score},
    ) as span:
        trace_id = span.trace_id
        observation_id = span.id
    client.api.dataset_run_items.create(
        run_name=version,
        run_description=f"test_model={model}",
        metadata={"prompt_name": prompt_name, "run_id": run_id, "version": version, "test_model": model},
        dataset_item_id=item.id,
        trace_id=trace_id,
        observation_id=observation_id,
    )
    client.create_score(
        name="Task Quality",
        value=score / 10.0,
        trace_id=trace_id,
        comment=reasoning,
        data_type="NUMERIC",
    )


def flush_or_warn(client) -> bool:
    try:
        client.flush()
        return True
    except Exception as e:
        print(f"⚠ Langfuse flush failed: {e}")
        return False
