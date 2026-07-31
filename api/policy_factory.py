import logging
from os import getenv

from flask import g
from inuits_policy_based_auth import PolicyFactory, RequestContext
from inuits_policy_based_auth.authentication.policies.token_based_policies.authlib_flask_oauth2_policy import (
    AuthlibFlaskOauth2Policy,
)
from inuits_policy_based_auth.contexts.user_context import UserContext
from inuits_policy_based_auth.exceptions import NoUserContextException

logger = logging.getLogger(__name__)


def init_policy_factory():
    allowed_issuers = getenv("ALLOWED_ISSUERS")
    _policy_factory.register_authentication_policy(
        "transcode-service",
        AuthlibFlaskOauth2Policy(
            logger,
            {"id": "email"},
            getenv("STATIC_ISSUER"),
            getenv("STATIC_PUBLIC_KEY"),
            allowed_issuers.split(",") if allowed_issuers else None,
        ),
    )
    _policy_factory.register_authorization_policy(
        "transcode-service",
        None,  # pyright: ignore #ty: ignore[invalid-argument-type]
    )
    _policy_factory.set_fallback_key_for_policy_mapping("transcode-service")


def authenticate(request_context: RequestContext):
    global _policy_factory  # noqa: PLW0602
    return _policy_factory.authenticate(request_context)


def get_user_context() -> UserContext:
    user_context = g.get("user_context")
    if not user_context:
        raise NoUserContextException()

    return user_context


def user_context_setter(user_context):
    g.user_context = user_context


_policy_factory = PolicyFactory(user_context_setter)
