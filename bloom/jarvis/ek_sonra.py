"""BLOOM EK — ertelenmiş komutlar: "şarkı bittikten sonra şunu aç", "10 dakika sonra müziği durdur", "21:30'da ...".

Koşullar : sarki_bitince · dakika_sonra · saat
Eylemler : sarki_cal · medya (durdur/devam/sonraki/önceki) · uygulama_ac · hatirlat · gorev (modele sonradan yaptırılacak serbest iş)
Şarkı bitişi Windows'un medya oturumundan (SMTC: çalan parça, süre, konum) izlenir; yalnızca bekleyen iş varken yoklanır.
Zamanlı işler yeniden başlatmada korunur; şarkı-bitişi işleri korunmaz (hangi şarkıya bağlı olduğu bilinemez).
"""

from __future__ import annotations
import json
import threading
import time
import uuid
import datetime as dt
from . import paths
from .log import log

IS_WIN = bool(getattr(paths, 'IS_WIN', False))
DOSYA = 'sonra.json'
GEC_TOLERANS = 600          # yeniden başlatınca bu kadar sn'ye kadar gecikmiş zamanlı iş hâlâ yapılır
BITIS_PAYI = 0.9            # kalan süre bu kadarsa "bitti" say
EYLEMLER = {'sarki_cal', 'medya', 'uygulama_ac', 'hatirlat', 'gorev'}
KOSULLAR = {'sarki_bitince', 'dakika_sonra', 'saat'}
_L = threading.RLock()
_S = {'isler': None, 'taban': None, 'sonraki': 0.0, 'dongu': False, 'uyan': threading.Event(), 'reg': None, 'kayit_hata': 0,
      'son_kayit': None}


def _ek():
    from . import ek
    return ek


def _yol():
    return _ek()._dir() / DOSYA


# --------------------------------------------------------------------------- kalıcılık
def _yukle() -> list[dict]:
    with _L:
        if _S['isler'] is None:
            try:
                raw = json.loads(_yol().read_text('utf-8'))
                isler = [j for j in raw if isinstance(j, dict) and j.get('kosul') == 'saat' or isinstance(j, dict) and j.get('kosul') == 'dakika_sonra']
            except Exception:
                isler = []
            _S['isler'] = isler
        return _S['isler']


def _kaydet() -> None:
    with _L:
        try:
            _yol().write_text(json.dumps([j for j in (_S['isler'] or []) if j.get('kosul') != 'sarki_bitince'], ensure_ascii=False), 'utf-8')
        except OSError as exc:
            log('ek_sonra: kaydedilemedi', exc)


def isler() -> list[dict]:
    return _yukle()


# --------------------------------------------------------------------------- Windows medya oturumu (SMTC)
def _betik() -> str:
    from .actions import win_media as wm
    ust = wm._GSMTC.split('$all = ')[0]
    return ust.replace('__ACTION__', 'now_playing') + r'''
$all = @($mgr.GetSessions())
if (-not $all.Count) { '{"none":true}'; return }
$playing = @($all | Where-Object { [string]$_.GetPlaybackInfo().PlaybackStatus -eq 'Playing' })
$s = if ($playing.Count) { $playing[0] } else { $mgr.GetCurrentSession() }
if (-not $s) { $s = $all[0] }
$p = Await ($s.TryGetMediaPropertiesAsync()) $PT
$t = $s.GetTimelineProperties()
$upd = 0.0
try { $upd = ([DateTimeOffset]::UtcNow - $t.LastUpdatedTime).TotalSeconds } catch {}
@{ app = $s.SourceAppUserModelId; title = $p.Title; artist = $p.Artist; status = [string]$s.GetPlaybackInfo().PlaybackStatus;
   pos = [double]$t.Position.TotalSeconds; end = [double]$t.EndTime.TotalSeconds; start = [double]$t.StartTime.TotalSeconds; upd = $upd; n = $all.Count } | ConvertTo-Json -Compress
'''


def kayit_oku() -> dict | None:
    """Şu an çalan/seçili medya: {app,title,artist,status,pos,end,kalan} ya da None (yok/okunamadı)."""
    if not IS_WIN:
        return None
    try:
        from .actions import win_media as wm
        code, out = wm.run_powershell(_betik(), timeout=15)
        if code is None:
            raise OSError('zaman aşımı')
        d = json.loads(out.strip().splitlines()[-1])
    except Exception as exc:
        _S['kayit_hata'] += 1
        if _S['kayit_hata'] in (1, 10, 100):
            log('ek_sonra: medya oturumu okunamadı', type(exc).__name__, exc)
        return None
    _S['kayit_hata'] = 0
    if d.get('none'):
        return {'yok': True}
    pos, end, upd = float(d.get('pos') or 0), float(d.get('end') or 0), float(d.get('upd') or 0)
    cal = d.get('status') == 'Playing'
    simdi_pos = pos + (max(0.0, min(upd, 600.0)) if cal else 0.0)
    kalan = (end - simdi_pos) if end > 5 else None
    return {'app': d.get('app') or '', 'title': d.get('title') or '', 'artist': d.get('artist') or '', 'status': d.get('status') or '',
            'pos': simdi_pos, 'end': end, 'kalan': kalan}


def parca_anahtari(k: dict) -> str:
    return f'{k.get("app", "")}|{k.get("title", "")}|{k.get("artist", "")}'.lower()


def _parca_adi(k: dict) -> str:
    return ' — '.join(x for x in (k.get('title'), k.get('artist')) if x) or 'çalan parça'


# --------------------------------------------------------------------------- iş ekleme / listeleme
def _simdi() -> float:
    return time.time()


def _saat_ts(saat: str, simdi: float | None = None) -> float | None:
    from . import ek_fikir
    s = ek_fikir.saat_coz(saat)
    if not s:
        return None
    h, m = s.split(':')
    now = dt.datetime.fromtimestamp(simdi if simdi is not None else _simdi())
    hedef = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if hedef <= now:
        hedef += dt.timedelta(days=1)
    return hedef.timestamp()


def eylem_ozeti(j: dict) -> str:
    e, s = j.get('eylem'), j.get('sorgu', '')
    if e == 'sarki_cal':
        return f'“{s}” çal'
    if e == 'medya':
        return {'pause': 'müziği durdur', 'play': 'müziği devam ettir', 'next': 'sonraki parçaya geç', 'previous': 'önceki parçaya dön'}.get(j.get('medya_islem'), 'müziği yönet')
    if e == 'uygulama_ac':
        return f'{s} uygulamasını aç'
    if e == 'hatirlat':
        return f'hatırlat: {s}'
    return f'yap: {s}'


def kosul_ozeti(j: dict, now: float | None = None) -> str:
    now = _simdi() if now is None else now
    if j.get('kosul') == 'sarki_bitince':
        return 'şarkı bitince' + (f' ({j["parca"]})' if j.get('parca') else '')
    kalan = max(0, int(j.get('zaman', 0) - now))
    d = dt.datetime.fromtimestamp(j.get('zaman', now))
    if j.get('kosul') == 'saat':
        return f'{d:%H:%M}\'de ({kalan // 60} dk sonra)'
    return f'{max(1, round(kalan / 60))} dk sonra'


def ekle(kosul: str, eylem: str, sorgu: str = '', dakika: float | None = None, saat: str | None = None, medya_islem: str = '') -> str:
    kosul, eylem = (kosul or '').strip().lower(), (eylem or '').strip().lower()
    if kosul not in KOSULLAR:
        return 'Koşul anlaşılamadı: sarki_bitince, dakika_sonra ya da saat olmalı.'
    if eylem not in EYLEMLER:
        return 'Eylem anlaşılamadı: sarki_cal, medya, uygulama_ac, hatirlat ya da gorev olmalı.'
    sorgu = ' '.join(str(sorgu or '').split())[:300]
    if eylem in ('sarki_cal', 'uygulama_ac', 'hatirlat', 'gorev') and not sorgu:
        return 'Ne yapacağımı (şarkı/uygulama adı ya da talimat) söylemelisin.'
    if eylem == 'medya' and medya_islem not in ('pause', 'play', 'next', 'previous'):
        return 'Medya işlemi pause, play, next ya da previous olmalı.'
    j = {'id': uuid.uuid4().hex[:8], 'kosul': kosul, 'eylem': eylem, 'sorgu': sorgu, 'medya_islem': medya_islem, 'olusturma': _simdi()}
    now = _simdi()
    if kosul == 'dakika_sonra':
        try:
            dk = float(dakika)
        except (TypeError, ValueError):
            return 'Kaç dakika sonra olacağını söyle.'
        if not 0 < dk <= 24 * 60:
            return 'Süre 1 dakika ile 24 saat arasında olmalı.'
        j['zaman'] = now + dk * 60
    elif kosul == 'saat':
        ts = _saat_ts(saat or '', now)
        if ts is None:
            return 'Saati anlayamadım (ör. 21:30).'
        j['zaman'] = ts
    else:
        if not IS_WIN:
            return 'Şarkı bitişini yalnızca Windows\'ta izleyebiliyorum.'
        k = kayit_oku()
        if not k or k.get('yok'):
            return 'Şu an çalan bir şarkı/video görünmüyor; bu yüzden “bitince” diye bekleyemem. Ne zaman yapayım: dakika ya da saat söyler misin?'
        if k.get('status') not in ('Playing', 'Paused'):
            return 'Çalan bir parça algılayamadım; “şu kadar dakika sonra” diyebilirsin.'
        j['taban'] = parca_anahtari(k)
        j['parca'] = _parca_adi(k)
        j['bitis_var'] = k.get('kalan') is not None
        if k.get('kalan') is not None:
            j['tahmin'] = now + max(0.0, k['kalan'])
    with _L:
        _yukle().append(j)
        _kaydet()
    baslat()
    _S['uyan'].set()
    ek_txt = ''
    if kosul == 'sarki_bitince':
        ek_txt = '' if j.get('bitis_var') else ' (Bu uygulama parça süresini bildirmiyor; parça değişince/bitince yapacağım.)'
    return f'Tamam: {kosul_ozeti(j, now)} → {eylem_ozeti(j)}.{ek_txt}'


def listele() -> str:
    js = isler()
    if not js:
        return 'Bekleyen ertelenmiş komut yok.'
    now = _simdi()
    return '\n'.join([f'{len(js)} bekleyen komut:'] + [f'- [{j["id"]}] {kosul_ozeti(j, now)}: {eylem_ozeti(j)}' for j in js])


def iptal(anahtar: str = '') -> str:
    a = (anahtar or '').strip().lower()
    with _L:
        js = _yukle()
        if not js:
            return 'İptal edilecek bekleyen komut yok.'
        if a in ('hepsi', 'tümü', 'tumu', 'all'):
            n = len(js)
            js.clear()
            _kaydet()
            return f'{n} bekleyen komut iptal edildi.'
        hit = [j for j in js if j['id'] == a or (a and a in eylem_ozeti(j).lower())]
        if not a and len(js) == 1:
            hit = list(js)
        if len(hit) != 1:
            return ('Hangisini? ' + '; '.join(f'[{j["id"]}] {eylem_ozeti(j)}' for j in js)) if hit or not a else 'Eşleşen komut bulamadım.'
        js.remove(hit[0])
        _kaydet()
        return f'İptal edildi: {kosul_ozeti(hit[0])} → {eylem_ozeti(hit[0])}'


# --------------------------------------------------------------------------- yürütme
def _kayit_reg(registry) -> None:
    _S['reg'] = registry


def _arac(ad: str, args: dict) -> str:
    reg = _S['reg']
    if reg is None:
        return 'Hata: araçlar hazır değil.'
    from .tools.registry import ToolContext
    sonuc, _ok = reg.call(ad, args, ToolContext())
    return sonuc


def _bildir(metin: str) -> None:
    ek = _ek()
    try:
        if ek.app is not None:
            ek.app.on_transcript('sys', metin)
    except Exception:
        pass
    ek._stage('[ERTELENMİŞ KOMUT SONUCU] ' + metin)


def uygula(j: dict) -> str:
    e = j['eylem']
    ek = _ek()
    log(f'ek_sonra: çalışıyor → {j["kosul"]} / {eylem_ozeti(j)}')
    if e == 'sarki_cal':
        r = _arac('play_media', {'query': j['sorgu'], 'provider': 'auto', 'autoplay': True})
    elif e == 'medya':
        r = _arac('media_control', {'action': j['medya_islem']})
    elif e == 'uygulama_ac':
        r = _arac('open_app', {'app_name': j['sorgu']})
    elif e == 'hatirlat':
        ek._announce(f'[ERTELENMİŞ KOMUT] Kullanıcı daha önce bu hatırlatmayı istemişti: “{j["sorgu"]}”. Şimdi kısaca hatırlat.')
        ek._hud('ekAlarm')
        return 'hatırlatıldı'
    else:
        ek._announce(f'[ERTELENMİŞ KOMUT] Kullanıcı daha önce şunu istemişti ve vakti geldi: “{j["sorgu"]}”. Şimdi araçlarınla yap, sonucu kısaca söyle.')
        return 'modele iletildi'
    _bildir(f'Ertelenmiş komut ({kosul_ozeti(j)}): {eylem_ozeti(j)} → {r}')
    return r


def _bitti_mi(j: dict, k: dict | None, now: float) -> bool:
    """Şarkı-bitişi işi için: çalan parça bitti ya da değişti mi?"""
    if k is None:
        return False
    if k.get('yok'):
        return True                      # oturum tamamen kapandı
    if parca_anahtari(k) != j.get('taban'):
        return True                      # başka parçaya geçti
    if k.get('status') in ('Stopped', 'Closed'):
        return True
    kalan = k.get('kalan')
    if kalan is not None and k.get('status') == 'Playing' and kalan <= BITIS_PAYI:
        return True
    return False


def _yoklama_araligi(k: dict | None) -> float:
    if k and not k.get('yok') and k.get('kalan') is not None and k.get('status') == 'Playing':
        kalan = k['kalan']
        if kalan > 40:
            return min(20.0, kalan - 30)
        if kalan > 12:
            return 5.0
        return 1.0
    return 6.0


def kontrol(now: float | None = None) -> list[dict]:
    """Bir tur: vakti gelen zamanlı işler + (varsa) şarkı-bitişi işleri. Çalıştırılanları döndürür."""
    now = _simdi() if now is None else now
    yapilacak = []
    with _L:
        js = _yukle()
        for j in list(js):
            if j['kosul'] in ('saat', 'dakika_sonra') and now >= j['zaman']:
                js.remove(j)
                if now - j['zaman'] <= GEC_TOLERANS:
                    yapilacak.append(j)
                else:
                    log('ek_sonra: çok geciken iş atlandı', eylem_ozeti(j))
        bitis = [j for j in js if j['kosul'] == 'sarki_bitince']
    if bitis and now >= _S['sonraki']:
        k = kayit_oku()
        _S['son_kayit'] = k
        _S['sonraki'] = now + _yoklama_araligi(k)
        for j in bitis:
            if k is None:
                continue
            if _bitti_mi(j, k, now):
                with _L:
                    if j in js:
                        js.remove(j)
                        yapilacak.append(j)
    with _L:
        for j in list(js):
            if j['kosul'] == 'sarki_bitince' and now - j['olusturma'] > 6 * 3600:
                js.remove(j)
        if yapilacak:
            _kaydet()
    for j in yapilacak:
        try:
            uygula(j)
        except Exception as exc:
            log('ek_sonra: iş çalıştırılamadı', type(exc).__name__, exc)
            try:
                _bildir(f'Ertelenmiş komut yapılamadı: {eylem_ozeti(j)}')
            except Exception:
                pass
    return yapilacak


def _bekleme(now: float) -> float:
    js = _yukle()
    if not js:
        return 3600.0
    ts = [j['zaman'] - now for j in js if j['kosul'] in ('saat', 'dakika_sonra')]
    if any(j['kosul'] == 'sarki_bitince' for j in js):
        ts.append(max(0.5, _S['sonraki'] - now))
    return max(0.5, min(ts + [30.0]))


def _dongu() -> None:
    while True:
        try:
            now = _simdi()
            kontrol(now)
            bekle = _bekleme(_simdi())
        except Exception as exc:
            log('ek_sonra: döngü hatası', type(exc).__name__, exc)
            bekle = 5.0
        _S['uyan'].wait(bekle)
        _S['uyan'].clear()


def baslat() -> None:
    with _L:
        if _S['dongu']:
            return
        _S['dongu'] = True
        n = len(_yukle())
    threading.Thread(target=_dongu, daemon=True, name='ek-sonra').start()
    if n:
        log(f'ek_sonra: {n} bekleyen komut yüklendi')


# --------------------------------------------------------------------------- yapay zekâ aracı
def arac(a, _c=None) -> str:
    a = a or {}
    islem = str(a.get('islem') or 'ekle').strip().lower()
    try:
        if islem in ('listele', 'liste'):
            return listele()
        if islem in ('iptal', 'sil'):
            return iptal(str(a.get('no') or a.get('sorgu') or ''))
        return ekle(a.get('kosul', ''), a.get('eylem', ''), a.get('sorgu', ''), a.get('dakika'), a.get('saat'), str(a.get('medya_islem') or ''))
    except Exception as exc:
        log('ek_sonra: araç hatası', type(exc).__name__, exc)
        return 'Ertelenmiş komut şu an kurulamadı.'


def istem_notu() -> str:
    js = isler()
    if not js:
        return ''
    return '[BEKLEYEN ERTELENMİŞ KOMUTLAR]\n' + '\n'.join(f'- {kosul_ozeti(j)}: {eylem_ozeti(j)}' for j in js[:6])
