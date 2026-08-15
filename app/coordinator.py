"""Koordinatör Ajan (backlog 3.5 — AI Agent orkestrasyonu).

Persona ajanlarının JSON çıktılarını alır ve BEŞİNCİ bir Gemini çağrısıyla
sentezler: gerekçeli genel skor, ortak sorunlar, önceliklendirilmiş eylem
planı ve yönetici özeti üretir. Düz ortalama değil, muhakeme katmanıdır —
"dört uzman raporunu okuyup sentez yazan başhekim".

LLM'e ulaşılamazsa (kota/ağ) deterministik birleştirmeye düşer; uygulama
asla boş kalmaz (demo sigortası).
"""

import json

from google.genai import types
from pydantic import BaseModel, Field

from analyzer import cagir
from personas import PERSONAS

SENTEZ_TALIMATI = """
Sen, farklı nöroçeşitlilik uzmanlarının raporlarını birleştiren koordinatör
erişilebilirlik uzmanısın. Aşağıda aynı web arayüzü için persona uzmanlarının
JSON raporları var. Görevin bunları SENTEZLEMEK — özetlemek değil:

- Birden fazla uzmanın işaret ettiği bölgeler en yüksek önceliği alır.
- Genel skoru düz ortalama ALMA; sorunların şiddetine ve kaç personayı
  etkilediğine göre gerekçeli belirle.
- Çelişki varsa (bir persona için iyi, diğeri için kötü olan tasarım) bunu
  açıkça belirt.
- Uygun eylemler için 'kod_onerisi' alanına 2-4 satırlık örnek CSS düzeltmesi
  yaz; anlamlı bir kod önerisi yoksa boş string bırak.
"""


class OncelikliEylem(BaseModel):
    oncelik: str = Field(description="Öncelik derecesi. Olası değerler: yuksek, orta, dusuk")
    sorun: str = Field(description="Bölge + sorunun kısa tarifi")
    etkilenen_personalar: list[str] = Field(description="Etkilenen persona isimleri listesi")
    oneri: str = Field(description="Somut iyileştirme adımı")
    kod_onerisi: str = Field(default="", description="Mümkünse 2-4 satırlık örnek CSS düzeltmesi; yoksa boş string")


class CoordinatorSentezCiktisi(BaseModel):
    genel_skor: int = Field(ge=1, le=100, description="1-100 arası tamsayı; 1=çok rahat, 100=aşırı yorucu")
    skor_gerekcesi: str = Field(description="Skoru neden böyle belirlediğinin 1-2 cümlelik açıklaması")
    yonetici_ozeti: str = Field(description="Arayüzün genel durumunun 2-3 cümlelik özeti")
    ortak_sorunlar: list[str] = Field(description="Birden fazla personayı etkileyen sorunlar listesi")
    oncelikli_eylemler: list[OncelikliEylem] = Field(description="Öncelik sırasına göre eylem planı listesi")
    celiskiler: list[str] = Field(description="Personalar arası çelişen bulgular varsa liste, yoksa boş liste")
    gelisim_yorumu: str | None = Field(default=None, description="Geçmiş analize göre ilerleme/gelişme yorumu. Geçmiş analiz verilmediyse null olmalı.")


def _deterministik_birlestir(sonuclar: dict[str, dict]) -> dict:
    """LLM'siz yedek birleştirme: ortalama skor + yüksek önemli sorunların listesi."""
    skorlar = [int(s.get("bilissel_yuk_skoru", 0)) for s in sonuclar.values()]
    eylemler = []
    for anahtar, sonuc in sonuclar.items():
        for alan in sonuc.get("sorunlu_alanlar", []):
            if alan.get("onem") == "yuksek":
                eylemler.append({
                    "oncelik": "yuksek",
                    "sorun": f"{alan.get('bolge', '?')}: {alan.get('sorun', '')}",
                    "etkilenen_personalar": [PERSONAS[anahtar]["ad"]],
                    "oneri": "",
                })
    return {
        "genel_skor": round(sum(skorlar) / len(skorlar)) if skorlar else 0,
        "skor_gerekcesi": "Persona skorlarının aritmetik ortalaması (yedek mod).",
        "yonetici_ozeti": "Koordinatör LLM'e ulaşılamadığı için bulgular kural "
                          "tabanlı birleştirildi; persona raporları yukarıda eksiksizdir.",
        "ortak_sorunlar": [],
        "oncelikli_eylemler": eylemler[:5],
        "celiskiler": [],
        "gelisim_yorumu": None,
        "_yedek_mod": True,
    }


def koordine_et(sonuclar: dict[str, dict], gecmis_rapor: dict | None = None) -> dict:
    """Persona sonuçlarını koordinatör ajanla sentezler; hata halinde yedek moda düşer."""
    if not sonuclar:
        raise ValueError("Sentezlenecek persona sonucu yok.")

    # Tek persona seçiliyse ve geçmiş rapor yoksa, sentezlenecek çokluk yok; skoru doğrudan aktar.
    if len(sonuclar) == 1 and not gecmis_rapor:
        tek = next(iter(sonuclar.values()))
        return {
            "genel_skor": int(tek.get("bilissel_yuk_skoru", 0)),
            "skor_gerekcesi": "Tek persona analiz edildi; skor doğrudan o personaya aittir.",
            "yonetici_ozeti": tek.get("genel_degerlendirme", ""),
            "ortak_sorunlar": [],
            "oncelikli_eylemler": [
                {
                    "oncelik": a.get("onem", "orta"),
                    "sorun": f"{a.get('bolge', '?')}: {a.get('sorun', '')}",
                    "etkilenen_personalar": [PERSONAS[k]["ad"] for k in sonuclar],
                    "oneri": "",
                }
                for a in tek.get("sorunlu_alanlar", [])
            ],
            "celiskiler": [],
            "gelisim_yorumu": None,
            "_yedek_mod": False,
        }

    # Persona raporlarını okunur adlarla paketleyip sentez çağrısına gönder.
    rapor_paketi = json.dumps(
        {PERSONAS[k]["ad"]: v for k, v in sonuclar.items()}, ensure_ascii=False
    )
    
    prompt = SENTEZ_TALIMATI + "\n\nPersona raporları:\n" + rapor_paketi
    if gecmis_rapor:
        prompt += "\n\nÖnemli: Lütfen bu analizi aşağıdaki geçmiş analiz raporu ile karşılaştırarak 'gelisim_yorumu' alanını doldur:\n" + json.dumps(gecmis_rapor, ensure_ascii=False)

    try:
        # cagir(): kota dolarsa sıradaki API anahtarına otomatik geçer.
        yanit = cagir(
            lambda istemci, aktif_model: istemci.models.generate_content(
                model=aktif_model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CoordinatorSentezCiktisi,
                ),
            )
        )
        rapor = json.loads(yanit.text)
        rapor["_yedek_mod"] = False
        return rapor
    except Exception:
        return _deterministik_birlestir(sonuclar)
