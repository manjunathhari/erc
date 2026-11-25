"""The simulated-arms label (R2-B).

While any arm is a stub binding, or does not declare itself a real configuration, every output of the
kit carries this exact text. It is left off only when every arm, the floor included, declares itself real.
"""
from .arms import StubMemory

LABEL = "simulated arms (stub), not a Stage 4 comparison"


class LabelMissing(ValueError):
    """An output of a simulated run lacks the label."""


def _arm_is_simulated(arm):
    if isinstance(arm, StubMemory):
        return True
    return getattr(arm, "simulated", None) is not False


def is_simulated(arms):
    """True if any arm is a stub or has not declared itself real. No arms at all counts as simulated."""
    arms = list(arms)
    if not arms:
        return True
    return any(_arm_is_simulated(a) for a in arms)


def label_for(arms):
    """The label for a run of these arms, or None when every arm declares itself real."""
    return LABEL if is_simulated(arms) else None
