"""
API Versions Package.

Contains all API versions with their respective routers and schemas.
"""

from .v1 import v1_router

__all__ = ["v1_router"]
