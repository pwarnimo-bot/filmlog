# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entry point: ``python -m filmlog`` or the ``filmlog`` command."""

from __future__ import annotations

import sys


def main() -> int:
    from filmlog.app import run

    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
