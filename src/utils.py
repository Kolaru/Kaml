import logging
import os

from asyncio import Lock
from logging.handlers import TimedRotatingFileHandler


## Logging

# Create log directory if it doesn't already exist
os.makedirs("log", exist_ok=True)

LOGFORMAT = "%(asctime)s  %(levelname)-10s %(message)s"
formatter = logging.Formatter(LOGFORMAT)

handler = TimedRotatingFileHandler("log/log.log", when="midnight", encoding="utf-8")
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)

logger = logging.getLogger("Kamlbot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)


## asyncio locks
locks = {}  # Dictionary of all locks generated by `get_lock`.


def get_lock(lock_name):
    """Get the lock with the given name, create it if it doesn't already exists."""
    if lock_name not in locks:
        locks[lock_name] = Lock()

    return locks[lock_name]


def locking(lock_name):
    """Decorator factory that apply a lock for the duration of the function.

    This means that another function with the same lock can not run at the same
    time. It is used to avoid that an async function modify the data used by another
    async function (which may screw everything).
    """
    lock = get_lock(lock_name)

    def _decorator(func):
        async def _locked_fn(*args, **kwargs):
            async with lock:
                res = await func(*args, **kwargs)
            return res

        return _locked_fn

    return _decorator


## Signal
signal_callbacks = {}  # Dictionary of all signal callbacks.


def connect(signal_name, func):
    """Connect the function `func` to a signal.

    That means that when a signal of this name is emitted (using `emit_signal`),
    the function `func` will be executed.
    """
    if signal_name not in signal_callbacks:
        signal_callbacks[signal_name] = []

    if func not in signal_callbacks[signal_name]:
        signal_callbacks[signal_name].append(func)


async def emit_signal(signal_name, *args, **kwargs):
    """Emit a signal with, executing all functions connected to it.

    Additional arguments are passed down to the connected functions.
    """
    if signal_name in signal_callbacks:
        for func in signal_callbacks[signal_name]:
            await func(*args, **kwargs)


## Misc

class ChainedDict:
    """Class chaining two dicts."""
    def __init__(self, key_to_mid, mid_to_value):
        self.key_to_mid = key_to_mid
        self.mid_to_value = mid_to_value

    def __getitem__(self, key):
        return self.mid_to_value[self.key_to_mid[key]]


def partition(N, parts=2):
    """Return all partition of integer `N` in a fixed number of parts."""

    if parts == 1:
        yield (N,)
    else:
        for i in range(1, N):
            for p in partition(N - i, parts - 1):
                yield (i,) + p