"""Authentication service module."""

from src.services.auth.api_key_service import ApiKeyService
from src.services.auth.auth_service import AuthService, hash_password, verify_password
from src.services.auth.jwt_service import JWTService
from src.services.auth.local_user import LOCAL_USER_EMAIL, LOCAL_USER_NAME, ensure_local_user
from src.services.auth.oauth_manager import OAuthManager
from src.services.auth.oauth_service import GoogleOAuthProvider, OAuthProvider, OAuthUserInfo

__all__ = [
    "ApiKeyService",
    "AuthService",
    "GoogleOAuthProvider",
    "JWTService",
    "LOCAL_USER_EMAIL",
    "LOCAL_USER_NAME",
    "OAuthManager",
    "OAuthProvider",
    "OAuthUserInfo",
    "ensure_local_user",
    "hash_password",
    "verify_password",
]
