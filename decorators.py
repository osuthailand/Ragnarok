from typing import Callable
from objects import services


def register_task() -> Callable:
    def wrapper(cb: Callable) -> None:
        services.registered_tasks.append({"func": cb})

    return wrapper
