import logging
import os

from logging.handlers import TimedRotatingFileHandler


## Logging

# Create log directory if it doesn't already exist
os.makedirs("log", exist_ok=True)

LOGFORMAT = "%(asctime)s  %(levelname)-10s %(message)s"
formatter = logging.Formatter(LOGFORMAT, datefmt="%Y-%m-%d %H:%M:%S")

handler = TimedRotatingFileHandler("log/log.log", when="midnight",
                                   encoding="utf-8")
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger("Kamlbot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.addHandler(console_handler)


## Signal
signal_callbacks = {}  # Dictionary of all signal callbacks.


def connect(signal_name, func):
    """
    Connect the function `func` to a signal.

    That means that when a signal of this name is emitted (using `emit_signal`),
    the function `func` will be executed.

    Arguments
    =========
    signal_name: str
        Unique identifier of the signal to which to connect.
    func: async function
        The callback function to be exectued when the signal is emitted.
    """
    if signal_name not in signal_callbacks:
        signal_callbacks[signal_name] = []

    if func not in signal_callbacks[signal_name]:
        signal_callbacks[signal_name].append(func)


async def emit_signal(signal_name, *args, **kwargs):
    """
    Emit a signal executing all functions connected to it.

    Additional arguments are passed down to the connected functions.

    Arguments
    =========
    signal_name: str
        Unique identifier of the signal to be emitted.

    Other arguments, both positional and keyword arguments are passed as is
    to all the functions connected to that signal.
    """
    if signal_name in signal_callbacks:
        for func in signal_callbacks[signal_name]:
            await func(*args, **kwargs)


## Misc
def partition(N, parts=2):
    """
    Return all partition of integer `N` in a fixed number of parts.

    Arguments
    =========
    N: int
        Integer to partition.
    parts: int
        The number of parts in which to partition `N`.
    """

    if parts == 1:
        yield (N,)
    else:
        for i in range(1, N):
            for p in partition(N - i, parts - 1):
                yield (i,) + p
