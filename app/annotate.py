import json

from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from analyzer import cagir, get_model

KUTU_TALIMATI = """
Bu arayüz görüntüsünde aşağıda tarif edilen sorunlu bölgeleri bul.
Emin olamadığın bölgeyi listeye hiç ekleme; uydurma kutu üretme.
Sorunlu bölgeler:
"""


class BoundingBoxKutusu(BaseModel):
    etiket: str = Field(description="Bölgenin sıra numarası (1, 2, vb.)")
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax] 0-1000 normalize koordinatları")


class KutuKumesi(BaseModel):
    kutular: list[BoundingBoxKutusu] = Field(description="Bulunan sorunlu bölgelerin sınırlayıcı kutuları listesi")


def _kutulari_ciz(goruntu: Image.Image, kutular: list[dict]) -> Image.Image:
    """0-1000 ölçekli kutuları piksele çevirip numaralı çerçeveler çizer."""
    isaretli = goruntu.convert("RGB").copy()
    cizim = ImageDraw.Draw(isaretli)
    g, y = isaretli.size
    
    # Görsel boyutuna göre dinamik etiket font boyutu (yüksekliğin %2.5'i, min 14px)
    font_size = max(14, int(y * 0.025))
    try:
        font = ImageFont.load_default()
        # Sistem fontlarını dene
        for f_ad in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
            try:
                font = ImageFont.truetype(f_ad, font_size)
                break
            except IOError:
                continue
    except Exception:
        font = ImageFont.load_default()

    for kutu in kutular:
        try:
            ymin, xmin, ymax, xmax = kutu["box_2d"]
        except (KeyError, ValueError, TypeError):
            continue
        # Normalize (0-1000) → piksel; taşmalara karşı kırpılır.
        x1, y1 = max(0, xmin / 1000 * g), max(0, ymin / 1000 * y)
        x2, y2 = min(g, xmax / 1000 * g), min(y, ymax / 1000 * y)
        if x2 <= x1 or y2 <= y1:
            continue
        
        cizim.rectangle([x1, y1, x2, y2], outline=(220, 30, 30), width=4)
        etiket = str(kutu.get("etiket", "?"))
        
        # Etiket arka plan kutusu boyutunu hesapla
        try:
            left, top, right, bottom = font.getbbox(etiket)
            tw = right - left
            th = bottom - top
        except AttributeError:
            tw, th = len(etiket) * (font_size // 2), font_size
            
        cizim.rectangle([x1, y1, x1 + tw + 12, y1 + th + 10], fill=(220, 30, 30))
        cizim.text((x1 + 6, y1 + 4), etiket, font=font, fill=(255, 255, 255))
    return isaretli


def bolgeleri_isaretle(
    goruntu_bytes: bytes, mime_type: str, bolge_tarifleri: list[str]
) -> Image.Image | None:
    """Bölge tariflerinin kutularını Gemini'den ister, işaretli görüntü döner.

    Başarısız olursa (kota, parse hatası) None döner; çağıran taraf bunu
    "işaretleme yapılamadı" bilgisiyle karşılar.
    """
    if not bolge_tarifleri:
        return None
    liste = "\n".join(f"{i}. {t}" for i, t in enumerate(bolge_tarifleri, 1))
    try:
        # cagir(): kota dolarsa sıradaki API anahtarına otomatik geçer.
        yanit = cagir(
            lambda istemci: istemci.models.generate_content(
                model=get_model(),
                contents=[
                    types.Part.from_bytes(data=goruntu_bytes, mime_type=mime_type),
                    KUTU_TALIMATI + liste,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=KutuKumesi,
                ),
            )
        )
        data = json.loads(yanit.text)
        kutular = data.get("kutular", [])
        if not kutular:
            return None
        
        import io
        # List of BoundingBoxKutusu dicts
        kutular_sade = [{"etiket": k.get("etiket"), "box_2d": k.get("box_2d")} for k in kutular if "box_2d" in k]
        return _kutulari_ciz(Image.open(io.BytesIO(goruntu_bytes)), kutular_sade)
    except Exception:
        return None
