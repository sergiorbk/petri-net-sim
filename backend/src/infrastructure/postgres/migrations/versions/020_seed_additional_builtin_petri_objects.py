"""Seed additional built-in petri_objects from new domain pattern classes

Revision ID: 020_seed_additional_builtin_petri_objects
Revises: 019_api_key_llm_credential_binding
Create Date: 2026-05-16

Adds 6 new user-friendly patterns that were added to the domain layer after
the initial seed (migration 012). Only practical, low-complexity patterns are
included so they are easy to drag onto the canvas and connect to a net.
"""

import uuid
from typing import Sequence, Union

from alembic import op

revision: str = "020_seed_extra_petri_objects"
down_revision: Union[str, None] = "019_api_key_llm_cred_binding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _build_templates() -> list[dict]:
    from src.domain.models.net import PetriNet
    from src.domain.patterns import (
        BoundedQueuePattern,
        MergePattern,
        DuplicatePattern,
        BatchPattern,
        UnbatchPattern,
        ForkJoinPattern,
    )

    catalog: list[tuple[type, str, str]] = [
        (
            BoundedQueuePattern,
            "BoundedQueue",
            "Queue with a finite capacity limit; excess tokens are blocked.",
        ),
        (
            MergePattern,
            "Merge",
            "Combines tokens arriving from multiple input streams into one output.",
        ),
        (
            DuplicatePattern,
            "Duplicate",
            "Copies each incoming token to multiple output branches simultaneously.",
        ),
        (
            BatchPattern,
            "Batch",
            "Accumulates N tokens and releases them as a single batch token.",
        ),
        (
            UnbatchPattern,
            "Unbatch",
            "Splits one batch token back into N individual tokens.",
        ),
        (
            ForkJoinPattern,
            "ForkJoin",
            "Forks work into parallel branches and waits until all complete before joining.",
        ),
    ]

    templates: list[dict] = []
    for pattern_cls, display_name, description in catalog:
        net = PetriNet(name=display_name)
        instance = pattern_cls()
        result = instance.apply(net=net, instance_name=display_name, x=0.0, y=0.0)
        payload = net.model_dump(mode="json")
        payload["interface"] = {
            "input_place_id": result.interface.input_place_id,
            "output_place_id": result.interface.output_place_id,
        }
        templates.append(
            {
                "name": display_name,
                "description": description,
                "template_data": payload,
            }
        )
    return templates


def upgrade() -> None:
    import json

    templates = _build_templates()
    conn = op.get_bind()

    insert_sql = """
        INSERT INTO petri_objects (
            id, user_id, is_builtin, name, description, template_data,
            preview_svg, created_at, updated_at
        )
        VALUES (
            :id, NULL, true, :name, :description, CAST(:template_data AS jsonb),
            NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT DO NOTHING
    """

    from sqlalchemy import text

    for tpl in templates:
        conn.execute(
            text(insert_sql),
            {
                "id": str(uuid.uuid4()),
                "name": tpl["name"],
                "description": tpl["description"],
                "template_data": json.dumps(tpl["template_data"]),
            },
        )


def downgrade() -> None:
    names = (
        "BoundedQueue",
        "Merge",
        "Duplicate",
        "Batch",
        "Unbatch",
        "ForkJoin",
    )
    placeholders = ", ".join(f"'{n}'" for n in names)
    op.execute(
        f"DELETE FROM petri_objects WHERE is_builtin = true AND name IN ({placeholders})"
    )
