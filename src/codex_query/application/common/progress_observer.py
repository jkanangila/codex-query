from collections.abc import Callable
from typing import TypeVar

# Type variable for step identifiers (Enum members, Literals, or strings)
StepT = TypeVar("StepT")


class ProgressObserver[StepT]:
    """Tracks overall progress across multi-step execution workflows.

    Calculates a weighted completion percentage based on relative step weights
    and executes an optional callback whenever step progress is updated.
    Accepts custom Enum or Literal types for type-safe step identifiers.
    """

    def __init__(
        self,
        step_weights: dict[StepT, float],
        callback: Callable[[float, str], None] | None = None,
    ) -> None:
        """Initializes observer with step weights and progress callback.

        Args:
            step_weights: Dict mapping step keys (Enum/Literal/str) to
                numerical weights. Automatically scaled to 100%.
            callback: Optional function formatted as
                callback(overall_pct, message).

        Raises:
            ValueError: If step_weights is empty or total weight is <= 0.
        """
        if not step_weights:
            raise ValueError("step_weights must contain at least one step.")

        # Calculate total weight to normalize all steps to a 100% scale
        total_weight = sum(step_weights.values())
        if total_weight <= 0:
            raise ValueError("Total weight of all steps must be > 0.")

        # Normalize step weights so they sum to 100.0
        self.weights: dict[StepT, float] = {
            step: (weight / total_weight) * 100.0
            for step, weight in step_weights.items()
        }

        self.callback = callback

        # Initialize step progress state (0.0 fraction = 0% complete)
        self.step_fractions: dict[StepT, float] = {step: 0.0 for step in self.weights}

    def update_step(
        self, step_name: StepT, current: int, total: int, message: str = ""
    ) -> None:
        """Updates progress within a specific step and calculates total pct.

        Args:
            step_name: Identifier of the registered workflow step.
            current: Completed work count within the step.
            total: Total expected work count for the step.
            message: Optional status string forwarded to callback.

        Raises:
            KeyError: If step_name is not registered in step_weights.
        """
        # Ensure the updated step exists in the weight mapping
        if step_name not in self.weights:
            raise KeyError(f"Step '{step_name}' is not registered in workflow weights.")

        # Clamp progress in [0.0, 1.0]. Total <= 0 sets 1.0 (complete).
        fraction = 1.0 if total <= 0 else min(max(current / total, 0.0), 1.0)

        # Update step completion fraction
        self.step_fractions[step_name] = fraction

        # Calculate overall percentage by summing weighted contributions
        overall = sum(
            self.weights[step] * self.step_fractions[step] for step in self.weights
        )

        # Trigger update callback if provided, rounded to 2 decimals
        if self.callback:
            self.callback(round(overall, 2), message)
