#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Điểm vào độc lập của bộ PatchX rodata-bypass (main hiển thị riêng).

Chạy:
    python3 rodata_bypass_main.py SO --flow static  --string X --new Y
    python3 rodata_bypass_main.py SO --flow dynamic --string X --new Y --mode pointer
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from patchx_core.rodata_bypass import main

if __name__ == "__main__":
    sys.exit(main())
