import logging

from asyncio import Lock
from logging.handlers import TimedRotatingFileHandler

## Logging

LOGFORMAT = "%(asctime)s  %(levelname)-10s %(message)s"
formatter = logging.Formatter(LOGFORMAT)

handler = TimedRotatingFileHandler("log/log.log", when="midnight", encoding="utf-8")
handler.setFormatter(formatter)
handler.setLevel(logging.DEBUG)

logger = logging.getLogger("Kamlbot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)


## asyncio locks

locks = {}

def get_lock(lock_name):
    if lock_name not in locks:
        locks[lock_name] = Lock()

    return locks[lock_name]

"""
    locking(lock)

Decorator that apply some `Lock` for the duration of the function.
"""
def locking(lock_name):
    lock = get_lock(lock_name)

    def _decorator(func):
        async def _locked_fn(*args, **kwargs):
            async with lock:
                res = await func(*args, **kwargs)
            return res
        
        return _locked_fn
    
    return _decorator


## Signal

signal_callbacks = {}

def callback(signal_name):
    def _decorator(func):
        connect(signal_name, func)
        return func
    return _decorator


def connect(signal_name, func):
    if signal_name not in signal_callbacks:
        signal_callbacks[signal_name] = []
    
    if func not in signal_callbacks[signal_name]:
        signal_callbacks[signal_name].append(func)


async def emit_signal(signal_name, *args, **kwargs):
    if signal_name in signal_callbacks:
        for func in signal_callbacks[signal_name]:
            await func(*args, **kwargs)



class ChainedDict:
    def __init__(self, key_to_mid, mid_to_value):
        self.key_to_mid = key_to_mid
        self.mid_to_value = mid_to_value

    def __getitem__(self, key):
        return self.mid_to_value[self.key_to_mid[key]]