import colored
from typing import Any


class Asora:
    DEBUG = colored.fg(107)
    INFO = colored.fg(111)
    CHAT = colored.fg(177)
    WARNING = colored.fg(130)
    ERROR = colored.fg(124)

    RESET = colored.attr("reset")


def info(msg: Any) -> None:
    print(f"[{Asora.INFO}info{Asora.RESET}]\t  {msg}")


def chat(msg: Any) -> None:
    print(f"[{Asora.CHAT}chat{Asora.RESET}]\t  {msg}")


def debug(msg: Any) -> None:
    print(f"[{Asora.DEBUG}debug{Asora.RESET}]\t  {msg}")


def warn(msg: Any) -> None:
    print(f"[{Asora.WARNING}warn{Asora.RESET}]\t  {msg}")


def error(msg: Any) -> None:
    print(f"[{Asora.ERROR}error{Asora.RESET}]\t  {msg}")


def fail(msg: Any) -> None:
    print(f"[{Asora.ERROR}fail{Asora.RESET}]\t  {msg}")
