"""Container startup import check used by safe update scripts."""

from .auth import record_security_event
from .main import app as application


def main() -> None:
    if not callable(record_security_event) or not application.title:
        raise RuntimeError("Backend import contract is incomplete")
    print("Backend import preflight passed")


if __name__ == "__main__":
    main()
