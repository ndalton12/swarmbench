import re


def normalize(value):
    value = re.sub(r"[\s-]+", "", value).upper()
    if not re.fullmatch(r"BL[0-9]{8}", value):
        raise ValueError("settlement reference must be BL followed by eight digits")
    return value
