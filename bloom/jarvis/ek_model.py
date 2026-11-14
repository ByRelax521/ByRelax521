"""BLOOM EK — Gemini model adı sağlayıcısı (yedekli).

Google, 2.5 modellerini yalnızca geçmişte kullanmış hesaplara açık tutuyor (18 Eylül 2026 duyurusu); yeni anahtarlarda
`gemini-2.5-flash` 404 verebilir ve model adları sık değişiyor. Bu yüzden her EK çağrısı tek bir sabit ada bağlanmaz:
  · önce çalıştığı bilinen model (ek durumunda hatırlanır), sonra kullanıcının ayarı, sonra yeniden eskiye doğru adaylar denenir;
  · "model yok / erişim yok / kota doldu" türü hatalarda sıradaki aday denenir; başka hatalar (ağ, anahtar) hemen iletilir;
  · çalışan model hatırlanır, sonraki çağrılar doğrudan onu kullanır.
"""

from __future__ import annotations
from . import settings
from .log import log

ADAYLAR = ('gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemini-2.5-flash')
_ATLANIR = ('404', 'not_found', 'not found', 'no longer available', 'not supported', 'is not available', 'permission_denied',
            'does not have access', 'resource_exhausted', '429', 'quota', 'deprecated', 'unavailable for')


_SON = {'model': '', 'zaman': 0.0, 'hata': '', 'hata_zaman': 0.0, 'denenen': ''}


def son_model() -> str:
    """Teşhis için: son başarılı model, son denenen model ve son atlanma nedeni (düz metin)."""
    import time as _t
    s = []
    if _SON['model']:
        s.append(f'son başarılı model: {_SON["model"]} ({int(_t.time() - _SON["zaman"])} sn önce)')
    elif _hatirlanan():
        s.append(f'bu oturumda henüz çağrı yok; hatırlanan model: {_hatirlanan()}')
    if _SON['hata']:
        s.append(f'son model hatası: {_SON["hata"]} ({int(_t.time() - _SON["hata_zaman"])} sn önce)')
    return '; '.join(s) or 'model bilgisi yok'


def _hatirlanan() -> str:
    try:
        from . import ek
        return str(ek.ayar('gemini_model', '') or '')
    except Exception:
        return ''


def _hatirla(model: str) -> None:
    try:
        from . import ek
        if ek.ayar('gemini_model', '') != model:
            ek.ayar_yaz('gemini_model', model)
    except Exception:
        pass


def sirali(ayar_adi: str = '', varsayilan: str = '') -> list[str]:
    out = []
    for m in (_hatirlanan(), str(settings.get(ayar_adi) or '') if ayar_adi else '', *ADAYLAR, varsayilan):
        if m and m not in out:
            out.append(m)
    return out


def atlanabilir(exc: Exception) -> bool:
    s = (type(exc).__name__ + ' ' + str(exc)).lower()
    return any(k in s for k in _ATLANIR)


def uret(client, contents, config=None, ayar_adi: str = '', varsayilan: str = ''):
    """client.models.generate_content; model adayları sırayla denenir. İlk başarılı yanıtı döner."""
    son = None
    gecici_limit = None      # günlük olmayan 429: beklemekle geçer; en sonda bunu ilet ki çağıran bekleyip yeniden denesin
    for m in sirali(ayar_adi, varsayilan):
        try:
            kw = {'model': m, 'contents': contents}
            if config is not None:
                kw['config'] = config
            r = client.models.generate_content(**kw)
            _SON.update(model=m, zaman=__import__('time').time())
            _hatirla(m)
            return r
        except Exception as exc:
            son = exc
            _SON.update(hata=f'{m}: {type(exc).__name__} ' + ' '.join(str(exc).split())[:100], hata_zaman=__import__('time').time())
            if not atlanabilir(exc):
                raise
            s_ = (type(exc).__name__ + ' ' + str(exc)).lower()
            if ('429' in s_ or 'resource_exhausted' in s_ or 'quota' in s_) and not any(k in s_ for k in ('perday', 'per day', 'per_day', 'daily')) and gecici_limit is None:
                gecici_limit = exc
            log('ek_model: model atlandı', m, type(exc).__name__, str(exc)[:80])
    raise gecici_limit or son if (gecici_limit or son) else RuntimeError('Gemini modeli bulunamadı')
