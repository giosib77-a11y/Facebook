"""`app` logger-ის კონფიგურაცია — stdout, LOG_LEVEL დონე.

uvicorn მხოლოდ საკუთარ `uvicorn*` logger-ებს აყენებს; `app`-ზე handler/level რომ არ იყოს,
INFO ჩანაწერები production-ში იკარგება (T22). root-ს არ ვეხებით, რომ uvicorn-ის ხაზები არ გაორმაგდეს.
"""
import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_HANDLER_FLAG = "_app_stdout_handler"


def setup_logging(level_name: str = "INFO") -> None:
    """Idempotent: განმეორებით გამოძახება (reload) handler-ს არ ამატებს, მხოლოდ level-ს ანახლებს."""
    level = logging.getLevelName((level_name or "INFO").strip().upper())
    if not isinstance(level, int):
        level = logging.INFO

    log = logging.getLogger("app")
    log.setLevel(level)
    log.propagate = False
    if not any(getattr(h, _HANDLER_FLAG, False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, _HANDLER_FLAG, True)
        log.addHandler(handler)
