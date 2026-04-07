#!/usr/bin/env python3
from __future__ import annotations

import sys

import autodl_run
import autodl_setup


def main(argv: list[str] | None = None) -> int:
    passthrough_args = list(sys.argv[1:] if argv is None else argv)
    autodl_setup.main([])
    return autodl_run.main(passthrough_args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
