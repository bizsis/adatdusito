"""OAuth codes/state must not enter the Uvicorn access log."""

import logging


class OAuthAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if (
                isinstance(args[2], str)
                and args[2].split("?", 1)[0] == "/api/v1/auth/google/callback"
            ):
                args[2] = "/api/v1/auth/google/callback"
                record.args = tuple(args)
        return True


def install_auth_log_filter():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, OAuthAccessFilter) for f in logger.filters):
        logger.addFilter(OAuthAccessFilter())
