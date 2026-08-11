"""Pure current-session data-egress cancellation boundary."""


class EgressPaused(RuntimeError):
    """A disabled capability refused admission for a new provider request."""
