'''Ayarlar › Hakkında sekmesinin ve TAKİP ET penceresinin içeriği: yapan, profiller, teşekkürler.

Değiştirmek için yalnızca bu dosyayı düzenlemek yeter; HUD buradan okur.
'''

from __future__ import annotations
import platform
import re
import unicodedata
from typing import Any
from urllib.parse import quote, urlencode
from . import VERSION, paths
CREATOR = 'Alp Ünlü'
FIRST = CREATOR.split()[0]
TAGLINE = "JARVIS V4'ü tasarlayıp geliştiren kişi. Yeni özellikleri, perde arkasını ve bir sonraki sürümü önce sosyal medyada gösteriyor."
LINKS = [{'name': 'Instagram', 'handle': '@alppunlu', 'url': 'https://www.instagram.com/alppunlu/', 'note': 'Reels, yeni özellikler ve perde arkası', 'at': "Instagram'da"}, {'name': 'TikTok', 'handle': '@alppunlu', 'url': 'https://www.tiktok.com/@alppunlu', 'note': 'Kısa videolar ve denemeler', 'at': "TikTok'ta"}, {'name': 'YouTube', 'handle': '@alpunlu', 'url': 'https://www.youtube.com/@alpunlu', 'note': 'Uzun videolar, kurulum ve topluluk', 'at': "YouTube'da"}, {'name': 'GitHub', 'handle': 'alpunlu12-commits', 'url': 'https://github.com/alpunlu12-commits', 'note': 'İndirmeler ve eski sürümler', 'at': "GitHub'da"}]
REPORT_URL = 'https://unlualp.com/jarvis/sorun/'
PRIVACY_URL = 'https://unlualp.com/jarvis/masaustu/gizlilik/'
SUPPORT_MAIL = 'destek@unlualp.com'
IPHONE_APP = True
INTRO = 'JARVIS V4, aşağıdaki kişilerin, projelerin ve açık kaynak topluluğunun emeği üzerine kuruldu. Hepsine teşekkürler.'
CREDITS = [{'group': 'TASARIM VE MİMARİ', 'items': [{'who': 'Arthur Kes', 'role': 'Arayüz ilhamı', 'what': 'Arayüzün görsel dili ve hareket kuralları onun projesinden, izniyle uyarlandı.', 'link': 'Instagram @arthur_kes', 'url': 'https://www.instagram.com/arthur_kes/'}, {'who': 'Fatihmakes', 'role': 'İlk mimari', 'what': "JARVIS'in ilk sürümlerinin mimarı.", 'link': 'github.com/FatihMakes', 'url': 'https://github.com/FatihMakes'}]}, {'group': 'YAPAY ZEKÂ VE SES', 'items': [{'who': 'Google Gemini', 'role': 'Gemini Live API', 'what': 'Gerçek zamanlı ses, konuşma ve görme; üç çipin de beyni.'}]}, {'group': 'HARİTA VE VERİ', 'items': [{'who': 'OpenStreetMap katkıcıları', 'role': 'Harita verisi · ODbL', 'what': 'Harita, yer arama ve yol tarifi.'}, {'who': 'Leaflet', 'role': 'Harita kütüphanesi · BSD-2', 'what': 'Paneldeki ve büyük haritadaki çizim.'}, {'who': 'wttr.in', 'role': 'Hava durumu', 'what': 'Anlık hava ve üç günlük tahmin.'}, {'who': 'Wikimedia Commons · NASA', 'role': 'Kamu malı arşiv', 'what': 'Hikâyedeki arşiv fotoğrafları ve gece ışıkları haritası.'}]}, {'group': 'YAZILIM', 'items': [{'who': 'Cloudflare', 'role': 'cloudflared · Apache 2.0', 'what': 'Telefondan her yerden bağlanma tüneli.'}, {'who': 'pywebview · PyObjC · sounddevice', 'role': 'Açık kaynak', 'what': 'Pencere, macOS köprüsü ve ses.'}]}, {'group': 'İLHAM', 'items': [{'who': 'Marvel', 'role': 'Karakterler', 'what': 'JARVIS, FRIDAY ve ULTRON; bitmeyen ilham.'}]}]
DISCLAIMER = "JARVIS, FRIDAY ve ULTRON Marvel'ın karakterleridir. Bu proje resmî değildir; kâr amacı gütmeyen bir hayran yapımıdır."

def prompt_block() -> str:
    """Kişisel kullanım: modele 'yapan' bilgisi verilmez."""

    return ''

def _fold(text: str) -> str:
    '''Küçük harf, şapkasız, ı/İ → i (reminders._fold gibi).'''

    text = unicodedata.normalize('NFKD', (text or '').replace('ı', 'i').replace('İ', 'i'))
    return ' '.join(''.join((c for c in text if not unicodedata.combining(c))).casefold().split())

_ASKED = re.compile('|'.join(('\\s*'.join(_fold(CREATOR).split()), '\\bkim(ler)?\\s+(\\w+\\s+){0,2}(yapti|yapmis|yaratti|yaratmis|gelistir\\w*|tasarla\\w*|kodla\\w*|programla\\w*|uretti|uretmis|yazdi|yazmis)', '\\b(yapim|yarati|gelistiri|tasarim)ci\\w*', '\\b(yapan|yaratan|gelistiren|tasarlayan)\\w*\\s+(\\w+\\s+)?(kim|nere)', '\\bkimin\\s+(eseri|yapimi|uygulamasi|urunu)|\\buygulama\\w*\\s+(kimin|sahibi)|\\bkim\\s+tarafindan', '\\bwho\\s+(made|created|built|developed|designed)\\b|\\byour\\s+(creator|developer|maker)\\b')))

def asked(said: str) -> bool:
    """Kapalı: kullanıcının sözü hiçbir zaman 'yapanı soruyor' sayılmaz."""

    return False

def other_person(said: str) -> bool:
    """Kapalı: 'Alp' diye bir ad özel sayılmaz (rehberdeki kişi olabilir)."""

    return False

def key_mail() -> str:
    """Kapalı: başkasına yazma bağlantısı yok."""

    return ''

def as_dict() -> dict[str, Any]:
    """Hakkında/yapan/teşekkür/iletişim içeriği boş; yalnızca arayüzün kullandığı iphone_app bayrağı kalır."""

    return {'creator': '', 'tagline': '', 'links': [], 'report': '', 'privacy': '', 'intro': '', 'credits': [], 'disclaimer': '', 'mail': '', 'key_mail': '', 'iphone_app': IPHONE_APP}
