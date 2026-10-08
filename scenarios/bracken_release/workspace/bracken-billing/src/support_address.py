def clean_lines(lines):
    """Remove blank lines and trim the helpdesk label-printing feed."""
    return [line.strip() for line in lines if line.strip()]


def label(lines):
    cleaned = clean_lines(lines)
    if len(cleaned) > 6:
        raise ValueError("label has more than six lines")
    return "\n".join(cleaned)
