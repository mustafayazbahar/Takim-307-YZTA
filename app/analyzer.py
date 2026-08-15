"""Gemini multimodal analiz katmanı.

Ekran görüntüsünü seçilen persona gözüyle analiz eder ve yapılandırılmış
JSON çıktı döndürür. JSON şeması zorunlu tutularak halüsinasyon riski
azaltılır (model serbest metin yerine şemaya uymak zorunda kalır).

Canlı demo dayanıklılığı (Demo Day'de jürinin kotaya takılması sonrası eklendi):
  * Birden fazla API anahtarı tanımlanabilir; biri kotaya takılırsa sıradakine
    otomatik geçilir (GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3...).
  * Aynı görüntü + persona kombinasyonu tekrar istenirse önbellekten döner;
    tekrarlı demolar kota yakmaz.
  * Tüm anahtarlar tükenirse ham hata yerine KotaAsildi fırlatılır; arayüz
    kullanıcıyı çevrimdışı galeri moduna yönlendirir.
"""

import hashlib
import json
import os
import time
from collections import OrderedDict

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from personas import GENEL_TALIMAT, PERSONAS


class KotaAsildi(RuntimeError):
    """Tanımlı tüm API anahtarlarının kotası dolduğunda fırlatılır."""


class ModelMesgul(RuntimeError):
    """Model geçici olarak yoğun (503) ve yedek modeller de yanıt vermediğinde."""


# --- Model seçimi -----------------------------------------------------------
# Tercih sırası: en yeni önce. Uygulama açılışında API'ye "hangi modeller
# kullanılabilir" diye sorulur ve bu listeden ilk eşleşen seçilir. Böylece
# Google yeni sürüm yayınladığında kod değişmeden yükseltme gerçekleşir,
# anahtar o modele erişemiyorsa da sessizce bir alt sürüme düşülür.
TERCIH_SIRASI = (
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3-flash",
    "gemini-2.5-flash",
)

# GEMINI_MODEL tanımlıysa otomatik seçim devre dışı kalır (elle sabitleme).
_ELLE_MODEL = os.getenv("GEMINI_MODEL", "").strip()
_COZULEN_MODEL: str | None = None
_MODEL_LISTESI: list[str] | None = None

# Geriye dönük uyumluluk: coordinator.py ve annotate.py bu adı içe aktarıyor.
DEFAULTS_MODEL = _ELLE_MODEL or TERCIH_SIRASI[-1]
MODEL = DEFAULTS_MODEL


def mevcut_modeller() -> list[str]:
    """API anahtarının erişebildiği metin üretimi modellerini döner (önbellekli)."""
    global _MODEL_LISTESI
    if _MODEL_LISTESI is not None:
        return _MODEL_LISTESI
    try:
        adlar = []
        for m in _istemci().models.list():
            ad = (getattr(m, "name", "") or "").removeprefix("models/")
            # Yalnızca içerik üretebilen modeller; gömme (embedding) modelleri elenir.
            eylemler = getattr(m, "supported_actions", None) or []
            if ad and (not eylemler or "generateContent" in eylemler):
                adlar.append(ad)
        _MODEL_LISTESI = sorted(set(adlar))
    except Exception:
        # Ağ/kota sorunu: bilinen listeyle devam et, uygulama durmasın.
        _MODEL_LISTESI = list(TERCIH_SIRASI)
    return _MODEL_LISTESI


def _modeli_coz() -> str:
    """Tercih sırasındaki ilk erişilebilir modeli seçer (bir kez hesaplanır)."""
    global _COZULEN_MODEL
    if _ELLE_MODEL:
        return _ELLE_MODEL
    if _COZULEN_MODEL:
        return _COZULEN_MODEL
    kullanilabilir = mevcut_modeller()
    for tercih in TERCIH_SIRASI:
        for ad in kullanilabilir:
            if ad.startswith(tercih):
                _COZULEN_MODEL = ad
                return ad
    _COZULEN_MODEL = TERCIH_SIRASI[-1]
    return _COZULEN_MODEL


def get_model() -> str:
    """Aktif modeli döner; Streamlit'ten yapılan seçim önceliklidir."""
    try:
        import streamlit as st

        secilen = st.session_state.get("secilen_model")
        if secilen:
            return secilen
    except Exception:
        pass
    return _modeli_coz()


# --- Çıktı şemaları ---------------------------------------------------------
class SorunluAlan(BaseModel):
    bolge: str = Field(description="Ekrandaki konum tarifi, örn: 'sağ üst köşedeki menü'")
    sorun: str = Field(description="Sorunun açıklaması")
    onem: str = Field(description="Önem derecesi. Olası değerler: yuksek, orta, dusuk")


class PersonaAnalizCiktisi(BaseModel):
    bilissel_yuk_skoru: int = Field(
        ge=1, le=100, description="1-100 arası tamsayı; 1=çok rahat, 100=aşırı yorucu"
    )
    genel_degerlendirme: str = Field(description="2-3 cümlelik özet")
    sorunlu_alanlar: list[SorunluAlan] = Field(description="En fazla 5 sorunlu alan listesi")
    oneriler: list[str] = Field(description="Somut, uygulanabilir iyileştirme önerileri listesi")
    pozitif_yonler: list[str] = Field(description="Arayüzün bu persona için iyi yaptığı şeyler")


# --- Anahtar havuzu ve istemci ---------------------------------------------
def _anahtarlari_topla() -> list[str]:
    """GEMINI_API_KEY, GEMINI_API_KEY_2, ... sırasıyla toplanır."""
    anahtarlar = []
    ilk = os.getenv("GEMINI_API_KEY", "").strip()
    if ilk:
        anahtarlar.append(ilk)
    for i in range(2, 11):
        ek = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if ek:
            anahtarlar.append(ek)
    return anahtarlar


_ISTEMCILER: dict[int, genai.Client] = {}
_AKTIF = 0


def anahtar_sayisi() -> int:
    """Tanımlı API anahtarı sayısı (arayüzde bilgi amaçlı)."""
    return len(_anahtarlari_topla())


def _istemci() -> genai.Client:
    """Aktif anahtarın istemcisini döner; istemciler tekrar kullanılır.

    (Her çağrıda yeni istemci oluşturmak "client has been closed" hatasına
    yol açıyordu; bu yüzden örnekler saklanıyor.)
    """
    anahtarlar = _anahtarlari_topla()
    if not anahtarlar:
        raise RuntimeError(
            "GEMINI_API_KEY bulunamadı. Yerelde app/.env dosyasına, bulutta "
            "Streamlit Secrets alanına ekleyin "
            "(anahtar https://aistudio.google.com adresinden ücretsiz alınır)."
        )
    if _AKTIF not in _ISTEMCILER:
        _ISTEMCILER[_AKTIF] = genai.Client(api_key=anahtarlar[_AKTIF])
    return _ISTEMCILER[_AKTIF]


def _kota_hatasi_mi(hata: Exception) -> bool:
    """Hata mesajından kota/hız sınırı ihlali olup olmadığını anlar."""
    metin = str(hata).lower()
    return any(
        im in metin
        for im in ("resource_exhausted", "429", "quota", "rate limit", "exceeded")
    )


def _gecici_hata_mi(hata: Exception) -> bool:
    """Sunucu kaynaklı geçici hata mı? (503 yoğunluk, 500, zaman aşımı)

    Kota hatasından farklıdır: anahtar değiştirmek işe yaramaz, beklemek veya
    başka bir modele düşmek gerekir.
    """
    metin = str(hata).lower()
    return any(
        im in metin
        for im in ("unavailable", "503", "500", "overloaded", "high demand",
                   "internal error", "deadline")
    )


def _sonraki_anahtara_gec() -> bool:
    """Sıradaki anahtara geçer; başka anahtar kalmadıysa False döner."""
    global _AKTIF
    if _AKTIF + 1 < len(_anahtarlari_topla()):
        _AKTIF += 1
        return True
    return False


def _model_zinciri() -> list[str]:
    """Denenecek modeller: aktif model, ardından tercih sırasındaki alt sürümler.

    Yeni çıkan modeller yoğunluk nedeniyle 503 verebiliyor; bu zincir sayesinde
    uygulama sessizce kararlı bir sürüme düşer.
    """
    zincir = [get_model()]
    kullanilabilir = mevcut_modeller()
    for tercih in TERCIH_SIRASI:
        for ad in kullanilabilir:
            if ad.startswith(tercih) and ad not in zincir:
                zincir.append(ad)
                break
    return zincir


_DENEME_SAYISI = 3  # aynı model için yeniden deneme adedi


def cagir(islev):
    """Model çağrısını dayanıklı biçimde yürütür.

    islev: (istemci, model) alıp model yanıtını döndüren fonksiyon.

    Sırasıyla:
      * Kota hatası (429)  -> sıradaki API anahtarına geçer, hepsi dolarsa KotaAsildi
      * Geçici hata (503)  -> artan bekleme ile yeniden dener, ısrar ederse alt modele düşer
      * Diğer hatalar      -> olduğu gibi yükseltilir (gizlenmez)
    """
    son_hata: Exception | None = None
    for model in _model_zinciri():
        for deneme in range(_DENEME_SAYISI):
            try:
                return islev(_istemci(), model)
            except Exception as hata:
                son_hata = hata
                if _kota_hatasi_mi(hata):
                    if _sonraki_anahtara_gec():
                        continue  # aynı model, yeni anahtar
                    raise KotaAsildi(
                        "Tanımlı tüm API anahtarlarının günlük kotası doldu. "
                        "Kayıtlı analizleri görmek için galeri modunu kullanabilir "
                        "veya yeni bir anahtar tanımlayabilirsiniz."
                    ) from hata
                if _gecici_hata_mi(hata):
                    if deneme < _DENEME_SAYISI - 1:
                        time.sleep(1.5 * (2 ** deneme))  # 1.5s, 3s
                        continue
                    break  # bu modelde ısrar etme, zincirdeki alt modele geç
                raise
    raise ModelMesgul(
        "Model şu anda yoğun ve yedek modeller de yanıt vermedi. "
        "Birkaç dakika sonra tekrar deneyin; bu arada galeri modundan kayıtlı "
        "analizleri inceleyebilirsiniz."
    ) from son_hata


# --- Sonuç önbelleği --------------------------------------------------------
# Aynı görüntü aynı persona ile tekrar analiz edilirse model çağrısı yapılmaz.
# Demo sırasında aynı sayfanın defalarca gösterilmesi kotayı tüketmesin diye.
_ONBELLEK: OrderedDict[str, dict] = OrderedDict()
_ONBELLEK_SINIRI = 64


def _onbellek_anahtari(goruntu: bytes, persona: str, html: str | None, model: str) -> str:
    ozet = hashlib.sha256(goruntu).hexdigest()[:32]
    html_ozet = hashlib.sha256((html or "").encode()).hexdigest()[:12]
    return f"{ozet}|{persona}|{html_ozet}|{model}"


def onbellegi_temizle() -> None:
    """Arayüzden 'yeniden analiz et' istendiğinde çağrılır."""
    _ONBELLEK.clear()


def analiz_et(
    goruntu_bytes: bytes,
    mime_type: str,
    persona_anahtari: str,
    html_kodu: str | None = None,
    onbellek_kullan: bool = True,
) -> dict:
    """Tek persona için görüntü (+ opsiyonel HTML) analizi yapar, dict döner."""
    persona = PERSONAS[persona_anahtari]
    model = get_model()

    anahtar = _onbellek_anahtari(goruntu_bytes, persona_anahtari, html_kodu, model)
    if onbellek_kullan and anahtar in _ONBELLEK:
        _ONBELLEK.move_to_end(anahtar)
        return _ONBELLEK[anahtar]

    icerik: list = [
        types.Part.from_bytes(data=goruntu_bytes, mime_type=mime_type),
        persona["prompt"] + "\n" + GENEL_TALIMAT,
    ]
    # HTML/CSS verilmişse yapısal analiz için ekle (token limiti için kırpılır).
    if html_kodu:
        icerik.append(
            "Ek olarak sayfanın kaynak kodu (yapısal sorunları da denetle):\n"
            "```html\n" + html_kodu[:20000] + "\n```"
        )

    yanit = cagir(
        lambda istemci, aktif_model: istemci.models.generate_content(
            model=aktif_model,
            contents=icerik,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PersonaAnalizCiktisi,
            ),
        )
    )
    sonuc = json.loads(yanit.text)

    _ONBELLEK[anahtar] = sonuc
    if len(_ONBELLEK) > _ONBELLEK_SINIRI:
        _ONBELLEK.popitem(last=False)
    return sonuc
