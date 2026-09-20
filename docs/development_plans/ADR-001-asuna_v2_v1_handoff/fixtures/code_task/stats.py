"""INTENTIONALLY BUGGY fixture, not production code."""
def summarize_readings(values):
    values.sort()
    return values[0], values[-1], sum(values) / len(values)
