"""OpenAI-compatible API protocol package."""


def get_openai_v1_router():
    """Lazy-build the OpenAI v1 router to avoid circular imports.

    Schemas in ``src.openai_api.v1.schemas`` can be imported freely;
    the router (which depends on ``src.core.dependencies``) is only
    constructed when this function is called.
    """
    from fastapi import APIRouter

    from .v1.routers.chat import router as chat_router

    openai_v1_router = APIRouter(prefix="/v1", tags=["openai"])
    openai_v1_router.include_router(chat_router)
    return openai_v1_router


__all__ = ["get_openai_v1_router"]
