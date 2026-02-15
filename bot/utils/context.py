from contextvars import ContextVar

# Context variable to track database actions within a request
db_actions_ctx: ContextVar[list[str] | None] = ContextVar("db_actions", default=None)


def add_db_action(action: str):
    """Helper to add an action to the current context if it exists."""
    actions = db_actions_ctx.get()
    if actions is not None:
        actions.append(action)
