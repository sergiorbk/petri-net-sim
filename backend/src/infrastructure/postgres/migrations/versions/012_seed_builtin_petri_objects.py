"""Seed built-in petri_objects rows from domain pattern classes

Revision ID: 012_seed_builtin_petri_objects
Revises: 011_add_petri_objects
Create Date: 2026-04-18

The migration imports pattern classes lazily inside ``upgrade()`` to avoid
pulling the domain layer into Alembic's module graph at config time.

Each pattern is instantiated at (0, 0) in a fresh PetriNet, serialized
via Pydantic, and paired with its PatternInterface declaration.  Rows
are inserted with ``is_builtin=true`` and ``user_id=NULL``.

Idempotent: the insert uses ``ON CONFLICT DO NOTHING`` against the
partial unique index on ``(lower(name))`` where ``is_builtin = true``.
"""

import uuid
from typing import Sequence, Union

from alembic import op

revision: str = "012_seed_builtin_petri_objects"
down_revision: Union[str, None] = "011_add_petri_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _build_templates() -> list[dict]:
    """Instantiate each pattern and return its serialized template_data."""
    # Lazy imports — domain layer should not load during Alembic init.
    from src.domain.models.net import PetriNet
    from src.domain.patterns import (
        AssemblyPattern,
        BufferPattern,
        ControllerPattern,
        ConveyorPattern,
        ConveyorWorkstationPattern,
        FeedbackLoopPattern,
        GeneratorPattern,
        MachinePattern,
        PriorityChoicePattern,
        QualityCheckPattern,
        RouterPattern,
        TerminatorPattern,
        ThresholdActivationPattern,
        TransportAgentPattern,
    )

    catalog: list[tuple[type, str, str]] = [
        (GeneratorPattern, "Generator", "Creates tokens at fixed or random intervals (arrivals)."),
        (MachinePattern, "Machine", "Multi-channel processing station with queue and release."),
        (TerminatorPattern, "Terminator", "Sink that removes tokens leaving the system."),
        (BufferPattern, "Buffer", "Bounded queue that regulates flow between stages."),
        (ControllerPattern, "Controller", "Gates token flow through a guarded immediate transition."),
        (AssemblyPattern, "Assembly", "Combines N input tokens into a single assembled token."),
        (RouterPattern, "Router", "Distributes tokens along weighted output branches."),
        (PriorityChoicePattern, "PriorityChoice", "Chooses the highest-priority enabled branch."),
        (ThresholdActivationPattern, "ThresholdActivation", "Fires only once the input reaches a threshold."),
        (QualityCheckPattern, "QualityCheck", "Splits a stream into good/bad based on probability."),
        (FeedbackLoopPattern, "FeedbackLoop", "Returns a fraction of output back upstream."),
        (ConveyorPattern, "Conveyor", "Fixed-delay transport between two locations."),
        (ConveyorWorkstationPattern, "ConveyorWorkstation", "Inline processing station on a conveyor."),
        (TransportAgentPattern, "TransportAgent", "Cyclic pickup/move/release/return resource."),
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
    op.execute(
        "DELETE FROM petri_objects WHERE is_builtin = true AND user_id IS NULL"
    )
