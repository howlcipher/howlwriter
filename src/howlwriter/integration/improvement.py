"""Optional content-free observations from Writer workflows."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from importlib import import_module
import logging
import os
from types import SimpleNamespace
from uuid import uuid4

from howlwriter import __version__

_RUN = ContextVar("howlloop_writer_run", default=None)
_LOG = logging.getLogger(__name__)


@contextmanager
def observe(operation, **metadata):
    if not os.environ.get("HOWLLOOP_STORE"):
        yield SimpleNamespace(result="ok", detail=None, validation=None)
        return
    try:
        producer = import_module("howlloop.producer")
    except ImportError:
        _LOG.warning("HowlLoop is unavailable in the Writer environment")
        yield SimpleNamespace(result="ok", detail=None, validation=None)
        return
    current_run = _RUN.get()
    token = _RUN.set(current_run or str(uuid4()))
    try:
        with producer.observe("writer", operation, run_id=_RUN.get(), version=__version__, **metadata) as observation:
            yield observation
    finally:
        _RUN.reset(token)


def measured(operation):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not os.environ.get("HOWLLOOP_STORE"):
                return function(*args, **kwargs)
            with observe(operation) as observation:
                try:
                    return function(*args, **kwargs)
                except RuntimeError as exc:
                    if isinstance(exc.__cause__, ImportError):
                        observation.detail = "dependency"
                        observation.result = "unavailable"
                    raise
        return wrapped
    return decorate


def validation(operation, passed):
    if not os.environ.get("HOWLLOOP_STORE"):
        return
    with observe(operation, measure_duration=False) as observation:
        observation.validation = ("passed" if passed else "failed") if passed is not None else "unavailable"
        observation.result = {True: "ok", False: "failed", None: "unavailable"}[passed]
        if passed is False:
            observation.detail = "validation"
