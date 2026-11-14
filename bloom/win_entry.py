"""JARVIS.exe'nin giriş noktası (PyInstaller bunu çalıştırır; bkz. scripts/build_win.py).

`python -m jarvis` ile aynı yol: jarvis/__main__.py (tek örnek kilidi, konsolsuz günlük, hata kutusu).
"""

import runpy
runpy.run_module('jarvis', run_name='__main__', alter_sys=True)
