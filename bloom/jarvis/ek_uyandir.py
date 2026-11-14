"""BLOOM EK — yerel uyandırma sözü ("Hey Bloom") dedektörü.

Ses bilgisayardan çıkmaz: üç küçük ONNX modeli (melspektrogram → konuşma gömmesi → "hey_jarvis" sınıflandırıcı,
openWakeWord, Apache-2.0) yerelde çalışır. Çalışması için `ek-wake` klasörü gerekir (JARVIS.exe'nin yanında):

    ek-wake/models/melspectrogram.onnx, embedding_model.onnx, hey_bloom_v0.1.onnx (ya da eski hey_jarvis_v0.1.onnx)
    ek-wake/lib/onnxruntime/...            (Windows için onnxruntime paketi, açılmış hâlde)

Klasör yoksa ya da yüklenemezse `yukle()` False döner ve BLOOM eskisi gibi (her zaman dinleyerek) çalışır.
"""

from __future__ import annotations
import os
import sys
import threading
import time
from pathlib import Path
from .log import log

KARE = 1280            # 80 ms @ 16 kHz
MODELLER = ('melspectrogram.onnx', 'embedding_model.onnx')
SINIFLAR = ('hey_bloom_v0.1.onnx', 'hey_jarvis_v0.1.onnx')      # önce "Hey Bloom"; yoksa eski "Hey Jarvis" modeline düşer


def sinif_dosyasi(d: Path) -> str | None:
    for s in SINIFLAR:
        try:
            if (d / 'models' / s).is_file():
                return s
        except OSError:
            pass
    return None


def klasorler() -> list[Path]:
    out = []
    env = os.environ.get('EK_WAKE_DIR')
    if env:
        out.append(Path(env))
    try:
        exe = Path(sys.executable).resolve().parent
        out += [exe / 'ek-wake', exe / '_internal' / 'ek-wake', exe.parent / 'ek-wake']
    except Exception:
        pass
    try:
        from . import paths
        out.append(Path(paths.DATA_DIR) / 'ek' / 'ek-wake')
    except Exception:
        pass
    return out


def bul() -> Path | None:
    for d in klasorler():
        try:
            if all((d / 'models' / m).is_file() for m in MODELLER) and sinif_dosyasi(d):
                return d
        except OSError:
            continue
    return None


class Dedektor:
    """Akış hâlinde çalışır: besle(pcm16) → bu çağrıda görülen en yüksek skor (0..1)."""

    def __init__(self) -> None:
        self.hata = ''
        self.sinif = ''
        self.hazir = False
        self._lock = threading.Lock()
        self._np = None
        self._mel = self._emb = self._clf = None
        self.son_ms = 0.0
        self.k = 1                  # son 6 adımda en az k adım eşiği geçmeli (yalnız Hey Bloom modelinde 3)
        self._son = []

    # ------------------------------------------------------------------ yükleme
    def yukle(self) -> bool:
        if self.hazir:
            return True
        with self._lock:
            if self.hazir:
                return True
            try:
                d = bul()
                if d is None:
                    self.hata = 'ek-wake klasörü bulunamadı'
                    return False
                lib = d / 'lib'
                if lib.is_dir() and str(lib) not in sys.path:
                    sys.path.insert(0, str(lib))
                    capi = lib / 'onnxruntime' / 'capi'
                    if capi.is_dir() and hasattr(os, 'add_dll_directory'):
                        try:
                            os.add_dll_directory(str(capi))
                        except OSError:
                            pass
                import numpy as np
                import onnxruntime as ort
                so = ort.SessionOptions()
                so.inter_op_num_threads = 1
                so.intra_op_num_threads = 1
                so.log_severity_level = 3
                mk = lambda n: ort.InferenceSession(str(d / 'models' / n), sess_options=so,  # noqa: E731
                                                    providers=['CPUExecutionProvider'])
                self.sinif = sinif_dosyasi(d)
                self.k = 3 if 'bloom' in self.sinif else 1
                self._mel, self._emb, self._clf = (mk(MODELLER[0]), mk(MODELLER[1]), mk(self.sinif))
                self._np = np
                self._clf_in = self._clf.get_inputs()[0].name
                self.sifirla()
                self.hazir = True
                self.hata = ''
                log('ek: uyandırma modeli yüklendi', str(d))
                return True
            except Exception as exc:
                self.hata = f'{type(exc).__name__}: {exc}'[:200]
                log('ek: uyandırma modeli yüklenemedi', self.hata)
                return False

    def sifirla(self) -> None:
        np = self._np
        self._ham = np.zeros(0, dtype=np.int16)
        self._meltamp = np.ones((76, 32), dtype=np.float32)
        gurultu = np.random.default_rng(7).integers(-1000, 1000, 16000 * 4).astype(np.int16)
        self._ozellik = self._gomme_toplu(gurultu)
        self._artik = np.zeros(0, dtype=np.int16)
        self._son = []

    # ------------------------------------------------------------------ çekirdek
    def _melspec(self, x):
        np = self._np
        out = self._mel.run(None, {'input': x.astype(np.float32)[None, :]})[0]
        return np.squeeze(out) / 10.0 + 2.0

    def _gomme_toplu(self, x):
        np = self._np
        spec = self._melspec(x)
        pencereler = [spec[i:i + 76] for i in range(0, spec.shape[0], 8) if spec[i:i + 76].shape[0] == 76]
        batch = np.expand_dims(np.array(pencereler), axis=-1).astype(np.float32)
        return self._emb.run(None, {'input_1': batch})[0].reshape(len(pencereler), 96)

    def besle(self, pcm: bytes) -> float:
        """16 kHz, 16 bit, tek kanal PCM. 80 ms'lik kareler tamamlandıkça skorlar; en yükseği döner."""
        if not self.hazir or not pcm:
            return 0.0
        np = self._np
        t0 = time.perf_counter()
        x = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype=np.int16)
        if self._artik.size:
            x = np.concatenate((self._artik, x))
            self._artik = np.zeros(0, dtype=np.int16)
        n = (x.size // KARE) * KARE
        if n < KARE:
            self._artik = x.copy()
            return 0.0
        self._artik = x[n:].copy()
        x = x[:n]
        en_iyi = 0.0
        for i in range(0, n, KARE):
            kare = x[i:i + KARE]
            self._ham = np.concatenate((self._ham, kare))[-(KARE + 480 + 1280):]
            if self._ham.size < KARE + 480:
                continue
            try:
                mel = self._melspec(self._ham[-(KARE + 480):])
                self._meltamp = np.vstack((self._meltamp, mel))[-970:]
                pencere = self._meltamp[-76:].astype(np.float32)[None, :, :, None]
                gom = self._emb.run(None, {'input_1': pencere})[0].reshape(1, 96)
                self._ozellik = np.vstack((self._ozellik, gom))[-120:]
                girdi = self._ozellik[-16:][None, :, :].astype(np.float32)
                skor = float(self._clf.run(None, {self._clf_in: girdi})[0].reshape(-1)[0])
                self._son.append(skor)
                del self._son[:-6]
                if len(self._son) >= self.k:
                    guc = sorted(self._son, reverse=True)[self.k - 1]       # k'inci en yüksek = en az k adım bu skorun üstünde
                    if guc > en_iyi:
                        en_iyi = guc
            except Exception as exc:
                self.hata = f'{type(exc).__name__}: {exc}'[:200]
                log('ek: uyandırma çıkarımı başarısız, kapatılıyor', self.hata)
                self.hazir = False
                return 0.0
        self.son_ms = (time.perf_counter() - t0) * 1000.0
        return en_iyi


_D = Dedektor()


def dedektor() -> Dedektor:
    return _D
