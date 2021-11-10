import asyncio
import logging
import inspect
from functools import wraps

_LOGGER = logging.getLogger(__name__)


def logger(lvl="debug", prefix=""):
    """Function decorator, print on fn name and args at each invocation."""

    def wrap(f):
        def log_fn(args, kwargs):
            logger = f.__globals__.get("_LOGGER", _LOGGER)

            # Wrong attr lvl, logger doesn't have method lvl
            if logger_method := getattr(logger, lvl, False):

                # function args format as string
                func_args = inspect.signature(f).bind(*args, **kwargs).arguments
                func_args_str = ", ".join(
                    map("{0[0]} = {0[1]!r}".format, func_args.items())
                )

                logger_method(f"{prefix}%s ( %s )", f.__name__, func_args_str)

        # Manage normal anc coroutine function
        if asyncio.iscoroutinefunction(f):

            @wraps(f)
            async def wrap_f(*args, **kwargs):
                log_fn(args, kwargs)
                return await f(*args, **kwargs)

        else:

            @wraps(f)
            def wrap_f(*args, **kwargs):
                log_fn(args, kwargs)
                return f(*args, **kwargs)

        return wrap_f

    return wrap
