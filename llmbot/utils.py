"""This module provides various utility functions for our package."""


def safe_divide(x: float, y: float) -> float | None:
    """
    Safely divide a given number by another number.

    If the division is undefined, it returns None.

    Args:
        x (float): The dividend.
        y (float): The divisor.

    Returns:
        float | None: The result of the division if defined, otherwise None.

    >>> safe_divide(0, 0) is None
    True
    >>> safe_divide(1, 0) is None
    True
    >>> safe_divide(0, 1)
    0.0
    >>> safe_divide(1, 1)
    1.0
    """
    return (x / y) if y != 0 else None
