from . import jordan

RULESETS = {"jordan": jordan}


def get_rules(name: str = "jordan"):
    return RULESETS[name]
