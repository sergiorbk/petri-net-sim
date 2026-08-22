"""V1 API routers."""

from .auth import router as auth_router
from .config import router as config_router
from .llm_credentials import router as llm_credentials_router
from .nets import router as nets_router
from .petri_objects import router as petri_objects_router
from .pnml import router as pnml_router
from .sessions import router as sessions_router
from .simulate import router as simulate_router
from .simulate_composed import router as simulate_composed_router

__all__ = [
    "auth_router",
    "config_router",
    "llm_credentials_router",
    "nets_router",
    "petri_objects_router",
    "pnml_router",
    "sessions_router",
    "simulate_router",
    "simulate_composed_router",
]
