"""Bootstrap for the fixed local user used by AUTH_MODE=single_user.

Single-user mode has no login: every request that doesn't carry its own
valid credentials (JWT or API key) is treated as one well-known local
account, so nets, Petri objects, and API keys created through the UI all
land on a real, ordinary ``User`` row instead of a synthetic in-memory one.
That keeps every other part of the system (ownership checks, foreign keys,
MCP-over-HTTP API keys) unchanged.

Because the account lives at a fixed, public email address
(``LOCAL_USER_EMAIL``), a deployment that ever ran reachable by an
untrusted party in multi-user mode could already have a row registered at
that address -- planted there through ordinary signup, before the
deployment ever switched to single_user mode. If this module blindly
adopted whatever row sits at that email, an attacker who squatted the
address earlier would silently become "the" local user of every future
single-user session. ``ensure_local_user`` guards against that with a
marker (see ``_BOOTSTRAP_MARKER_KEY`` below) that only this function ever
writes, and refuses to proceed if a pre-existing row doesn't carry it.
"""

import secrets

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.infrastructure.postgres.models.user import User
from src.infrastructure.postgres.repositories import UserRepository
from src.services.auth.auth_service import hash_password

logger = get_logger()

LOCAL_USER_EMAIL = "local@petri-net-sim.local"
LOCAL_USER_NAME = "Local User"

# Marker recorded in User.metadata_ (a JSONB column) on the row this
# function creates, and checked against any row it finds already sitting
# at LOCAL_USER_EMAIL.
#
# Why an attacker who only has signup access cannot produce this marker,
# even if they read this source file and know the exact key and value:
#
#   * POST /api/v1/auth/signup is bound to SignupRequest, which carries
#     only email/password/name -- there is no field through which a caller
#     can set arbitrary user metadata.
#   * AuthService.register_with_password (the handler behind that route)
#     calls UserRepository.create() without a `metadata` argument, so
#     every signup-created row is stored with metadata_ == {}, always --
#     regardless of what the caller submits.
#   * The Google OAuth signup path (OAuthManager.authenticate) creates
#     rows the same way: no metadata is ever set.
#   * The only other writer of metadata_ is PATCH /api/v1/auth/me, which
#     (a) requires already being authenticated as that row -- itself only
#     reachable after a signup/OAuth create that never planted the marker
#     -- and (b) only ever merges a fixed set of keys (display_name,
#     work_type, custom_instructions, integrations), never this one, and
#     never clears existing keys it doesn't touch.
#
# So this is a capability gap, not a secrecy bet: knowing the marker's
# name and value grants no path to writing it, because no reachable API
# surface accepts caller-supplied metadata at all. (A verification scheme
# based on the password hash was considered and rejected: bcrypt truncates
# its input at 72 bytes, and SignupRequest.password allows up to 128
# characters, so a signup submission that merely reuses the first 72 bytes
# of a hypothetical "secret" plaintext would hash identically -- that
# approach leaks exactly the amount of collision room the metadata
# approach avoids entirely.)
_BOOTSTRAP_MARKER_KEY = "_local_user_bootstrap"
_BOOTSTRAP_MARKER_VALUE = "ensure_local_user"


class LocalUserBootstrapError(RuntimeError):
    """Raised when the row at LOCAL_USER_EMAIL was not created by this module.

    This means the email was registered through some other path (most
    likely signup, while the deployment was reachable in multi-user mode)
    before single-user mode ever ran. Adopting that row would hand
    whoever created it silent, permanent control of the local account, so
    startup refuses to proceed.
    """


def _is_own_bootstrap_row(user: User) -> bool:
    meta = user.metadata_ or {}
    return meta.get(_BOOTSTRAP_MARKER_KEY) == _BOOTSTRAP_MARKER_VALUE


async def ensure_local_user(session: AsyncSession) -> User:
    """Get or create the single fixed local user.

    Idempotent and safe to call on every request: the common case is a
    cheap lookup by email. The password hash is bcrypt over a random token
    that is generated once and immediately discarded, so the row can never
    be logged into through the normal password flow (which single-user mode
    disables anyway) -- it exists only as the ownership anchor.

    A race between two concurrent first-requests (or a request racing the
    startup bootstrap in core/lifecycle.py) is resolved by retrying the
    lookup after a unique-constraint failure on the second insert.

    Raises:
        LocalUserBootstrapError: a row already exists at LOCAL_USER_EMAIL
            but doesn't carry this module's marker, i.e. it was created by
            some other path (see module docstring). This function is
            called eagerly at startup (core/lifecycle.py), so this
            surfaces as a boot failure rather than a runtime 500.
    """
    repo = UserRepository(session)

    existing = await repo.get_by_email(LOCAL_USER_EMAIL)
    if existing:
        if not _is_own_bootstrap_row(existing):
            logger.error(
                "AUTH_MODE=single_user: a user already exists at %s but "
                "was not created by ensure_local_user (missing bootstrap "
                "marker). Refusing to adopt it -- this looks like the "
                "email was registered through signup before single-user "
                "mode was enabled. Remove or rename that account, then "
                "restart.",
                LOCAL_USER_EMAIL,
            )
            raise LocalUserBootstrapError(
                f"Refusing to start: a pre-existing account at "
                f"{LOCAL_USER_EMAIL!r} was not created by the single-user "
                f"bootstrap and may belong to someone else."
            )
        return existing

    try:
        user = await repo.create(
            email=LOCAL_USER_EMAIL,
            name=LOCAL_USER_NAME,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            metadata={_BOOTSTRAP_MARKER_KEY: _BOOTSTRAP_MARKER_VALUE},
        )
        await session.commit()
        return user
    except IntegrityError:
        await session.rollback()
        existing = await repo.get_by_email(LOCAL_USER_EMAIL)
        if existing:
            if not _is_own_bootstrap_row(existing):
                logger.error(
                    "AUTH_MODE=single_user: lost the create race for %s "
                    "against a row without the bootstrap marker. Refusing "
                    "to adopt it.",
                    LOCAL_USER_EMAIL,
                )
                raise LocalUserBootstrapError(
                    f"Refusing to start: a pre-existing account at "
                    f"{LOCAL_USER_EMAIL!r} was not created by the "
                    f"single-user bootstrap and may belong to someone else."
                )
            return existing
        raise
