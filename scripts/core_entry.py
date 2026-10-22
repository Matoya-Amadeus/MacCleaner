"""PyInstaller 入口 shim。

为什么要单独一个文件：直接把 `maccleaner/core_cli.py` 当脚本入口，PyInstaller 会以
`__main__` 跑它，里面的相对导入（`from . import __version__`）就炸了——
`ImportError: attempted relative import with no known parent package`（实测）。

这里只做一件事：以**包内模块**的身份调用真正的 main。
"""

from maccleaner.core_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
