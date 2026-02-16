# Template: new function with semantic region (for specs TASK-001+)
# Copy and adjust SPEC_ID, REGION_NAME, REQ, Source, and implementation.

# [START SPEC:{SPEC_ID}:{REGION_NAME}]
# REQ: {Brief requirement from spec, e.g. "pot_cap = base * 5%"}
# Source: {SPEC_FILE.md, section name}
# CRITICAL: {Optional: what not to change without game balance review}


def critical_function(arg: int) -> int:
    """Docstring as usual."""
    # implementation
    return arg


# [END SPEC:{SPEC_ID}]
