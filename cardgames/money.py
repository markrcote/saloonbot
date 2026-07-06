def dollars_to_cents(dollars):
    """Convert a dollar amount (int/float) to an integer number of cents."""
    return round(dollars * 100)


def cents_to_dollars(cents):
    """Convert integer cents to a whole-dollar integer (rounded).

    For human/LLM-facing contexts that only need whole-dollar granularity
    (e.g. an LLM betting prompt); use format_cents() when exact cents matter.
    """
    return round(cents / 100)


def format_cents(cents):
    """Format an integer number of cents as a dollar string, e.g. 12345 -> '123.45'."""
    return f"{cents / 100:.2f}"
