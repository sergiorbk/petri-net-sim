"""
API Version 1.

Common application endpoints (auth, user management).
Released: 2024-01-01
"""

from fastapi import APIRouter

from .routers import (
    auth_router,
    config_router,
    llm_credentials_router,
    nets_router,
    petri_objects_router,
    pnml_router,
    sessions_router,
    simulate_composed_router,
    simulate_router,
)

from .routers.training import router as training_router

v1_router = APIRouter(prefix="/v1", tags=["v1"])
v1_router.include_router(training_router)
v1_router.include_router(auth_router)
v1_router.include_router(config_router)
v1_router.include_router(llm_credentials_router)
v1_router.include_router(sessions_router)
v1_router.include_router(nets_router)
v1_router.include_router(petri_objects_router)
v1_router.include_router(pnml_router)
v1_router.include_router(simulate_router)
v1_router.include_router(simulate_composed_router)

__all__ = ["v1_router"]
