import re


def extract_path_params(path: str, pattern: str) -> dict:
    regex_pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    regex_pattern = f"^{regex_pattern}$"

    match = re.match(regex_pattern, path)

    if match:
        return match.groupdict()
    else:
        return {}
