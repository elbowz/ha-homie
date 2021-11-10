from . import TRUE, FALSE


def str2bool(val: str):
    return val == TRUE


def bool2str(val: bool):
    return TRUE if val else FALSE
