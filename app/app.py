"""CogniTrace — Bilişsel Yük ve Erişilebilirlik Analiz Ajanı (Sprint 2, birleşik arayüz).

Şükran'ın premium panel tasarımı + ajan altyapısının tamamı:
koordinatör ajan, URL'den yakalama, axe-core, görsel işaretleme, galeri,
disleksi simülasyonu, PDF rapor.

Çalıştırma:  streamlit run app.py   (app klasörünün içinden)
"""

import io
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import feedback
import gallery
from analyzer import KotaAsildi, ModelMesgul, analiz_et
from annotate import bolgeleri_isaretle
from coordinator import koordine_et
from dyslexia_sim import disleksi_metni
from personas import PERSONAS
from simulation import DONUSUM_MATRISLERI, simule_et

load_dotenv()

# --- LOGO: repo içinden, herkeste çalışır (assets/ klasörüne koyun) ---
_ASSET_DIZINI = Path(__file__).parent / "assets"


def logo_yolu(tema: str) -> str | None:
    """Temaya uygun logo varyantını döner; yoksa genel logoya düşer."""
    adaylar = [
        f"cognitrace_logo_{'koyu' if tema == 'Koyu' else 'acik'}.png",
        "cognitrace_logo.png",
        "cognitrace_logo.ico",
    ]
    for ad in adaylar:
        p = _ASSET_DIZINI / ad
        if p.exists():
            return str(p)
    return None


LOGO_YOLU = logo_yolu("Koyu")  # sayfa ikonu için başlangıç değeri

st.set_page_config(
    page_title="CogniTrace - Erişilebilirlik Paneli",
    page_icon=LOGO_YOLU or "🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- PDF: Türkçe karakter destekli font kaydı (ş, ğ, İ için şart) ---
def _pdf_fontu() -> str:
    adaylar = [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for yol in adaylar:
        if Path(yol).exists():
            try:
                pdfmetrics.registerFont(TTFont("TurkceFont", yol))
                return "TurkceFont"
            except Exception:
                continue
    return "Helvetica"


def pdf_olustur(genel_skor, erisilebilirlik, analiz_sonuclari, rapor, axe_ihlalleri, dosya_adi):
    """Analiz sonuçlarını kurumsal PDF'e dönüştürür — yalnızca GERÇEK veriler."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    font = _pdf_fontu()
    hikaye = []
    stiller = getSampleStyleSheet()
    mor, koyu, gri = (colors.HexColor(r) for r in ("#7C3AED", "#1A0F30", "#F5EEFF"))

    baslik_s = ParagraphStyle("B", parent=stiller["Heading1"], fontName=font,
                              fontSize=22, leading=26, textColor=mor, spaceAfter=15)
    alt_s = ParagraphStyle("A", parent=stiller["Heading2"], fontName=font,
                           fontSize=13, leading=17, textColor=koyu,
                           spaceBefore=12, spaceAfter=8, keepWithNext=True)
    p_s = ParagraphStyle("P", parent=stiller["Normal"], fontName=font, fontSize=10,
                         leading=14, textColor=colors.HexColor("#333333"), spaceAfter=8)

    hikaye.append(Paragraph("CogniTrace — Erişilebilirlik Değerlendirme Raporu", baslik_s))
    hikaye.append(Paragraph(f"<b>Analiz Edilen:</b> {dosya_adi}", p_s))

    if analiz_sonuclari:
        veri = [
            [Paragraph("<b>Metrik</b>", p_s), Paragraph("<b>Değer</b>", p_s)],
            [Paragraph("Genel Bilişsel Yük Skoru", p_s), Paragraph(f"{genel_skor} / 100", p_s)],
            [Paragraph("Erişilebilirlik Puanı", p_s), Paragraph(f"%{erisilebilirlik}", p_s)],
            [Paragraph("Analiz Edilen Persona", p_s), Paragraph(str(len(analiz_sonuclari)), p_s)],
        ]
        if axe_ihlalleri is not None:
            veri.append([Paragraph("axe-core WCAG İhlali (kural tabanlı)", p_s),
                         Paragraph(str(len(axe_ihlalleri)), p_s)])
        tablo = Table(veri, colWidths=[250, 250])
        tablo.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (1, 0), gri),
            ("TEXTCOLOR", (0, 0), (1, 0), mor),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#EAE5F5")),
        ]))
        hikaye.append(tablo)
        hikaye.append(Spacer(1, 16))

        hikaye.append(Paragraph("Persona Denetim Bulguları", alt_s))
        for anahtar, sonuc in analiz_sonuclari.items():
            p = PERSONAS[anahtar]
            hikaye.append(Paragraph(
                f"<b>{p['ad']} (Bilişsel Yük: {sonuc.get('bilissel_yuk_skoru', 0)}/100)</b>", alt_s))
            hikaye.append(Paragraph(sonuc.get("genel_degerlendirme", ""), p_s))
            for alan in sonuc.get("sorunlu_alanlar", []):
                hikaye.append(Paragraph(
                    f"• [{alan.get('onem', 'orta').upper()}] <b>{alan.get('bolge', '?')}</b> — "
                    f"{alan.get('sorun', '')}", p_s))
            hikaye.append(Spacer(1, 8))

        if rapor:
            hikaye.append(Paragraph("Koordinatör Ajan — Öncelikli Eylem Planı", alt_s))
            hikaye.append(Paragraph(rapor.get("yonetici_ozeti", ""), p_s))
            for i, e in enumerate(rapor.get("oncelikli_eylemler", []), 1):
                satir = f"{i}. [{e.get('oncelik', '?').upper()}] {e.get('sorun', '')}"
                if e.get("oneri"):
                    satir += f" → {e['oneri']}"
                hikaye.append(Paragraph(satir, p_s))
    else:
        hikaye.append(Paragraph(
            "Henüz analiz gerçekleştirilmedi. Analiz sonrası bu rapor gerçek "
            "bulgularla dolacaktır.", p_s))

    doc.build(hikaye)
    buffer.seek(0)
    return buffer.getvalue()


# --- OTURUM DURUMU ---
durum = st.session_state
durum.setdefault("tema", "Koyu")
durum.setdefault("sol_panel_acik", True)
durum.setdefault("giris_yapildi", False)
durum.setdefault("aktif_sekme", "Analiz Paneli")
durum.setdefault("analiz_sonuclari_state", {})
durum.setdefault("rapor_state", None)
durum.setdefault("genel_skor_state", 0)
durum.setdefault("engelsiz_skor_state", 100)
durum.setdefault("isaretli_state", None)

# Streamlit'in YERLEŞİK temasını oturum temasıyla eşitle: CSS yalnızca bizim
# kartları boyar; açılır menüler, dosya yükleyici ve üst şerit gibi native
# bileşenler base temadan renk alır. Resmî çalışma anı API'si olmadığı için
# dahili config kancası kullanılır; kırılırsa uygulama düşmez.
_istenen_base = "dark" if durum["tema"] == "Koyu" else "light"
try:
    if st._config.get_option("theme.base") != _istenen_base:
        st._config.set_option("theme.base", _istenen_base)
        st.rerun()
except Exception:
    pass

# Tema netleştikten sonra logoyu temaya uygun varyantla değiştir.
LOGO_YOLU = logo_yolu(durum["tema"])

# --- TEMA CSS (Şükran'ın tasarımı) ---
_genis = "280px" if durum["sol_panel_acik"] else "80px"
if durum["tema"] == "Açık":
    _pal = dict(arka="#FAF9FC", panel="#FFFFFF", kenar="#EAE5F5", metin="#1A0F30",
                kart="background: #FFFFFF; border: 1px solid #EAE5F5;",
                persona="background:#F5EEFF; border:1px solid #D9C3F5; color:#4A154B;",
                hover="background-color:#F5EEFF !important; color:#7C3AED !important;",
                yukle="background:#FFFFFF !important;", yazi="#4A154B")
else:
    _pal = dict(arka="#06080F", panel="#0B0D16", kenar="#1A1F35", metin="#F3F4F6",
                kart="background: rgba(13,17,30,0.8); backdrop-filter: blur(12px); "
                     "border: 1px solid rgba(255,255,255,0.05);",
                persona="background:rgba(124,58,237,0.1); border:1px solid "
                        "rgba(124,58,237,0.2); color:#D8B4FE;",
                hover="background-color:rgba(124,58,237,0.1) !important; "
                      "color:#D8B4FE !important;",
                yukle="background:rgba(10,15,30,0.6) !important;", yazi="#F3F4F6")

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
    * {{ font-family: 'Plus Jakarta Sans', sans-serif !important; }}
    /* İkon fontlarını global font ezmesinden muaf tut — yoksa ikonlar
       ("upload", "keyboard_arrow_down"...) ham metin olarak görünür. */
    span[data-testid="stIconMaterial"],
    [class*="material-symbols"],
    [class*="material-icons"] {{
        font-family: 'Material Symbols Rounded' !important;
    }}
    .stApp {{ background-color: {_pal['arka']} !important; color: {_pal['metin']} !important; }}
    section[data-testid="stSidebar"] {{
        background-color: {_pal['panel']} !important;
        border-right: 1px solid {_pal['kenar']} !important;
        width: {_genis} !important; min-width: {_genis} !important; max-width: {_genis} !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        overflow-x: hidden !important;
    }}
    div[data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
    div[data-testid="stSidebar"] button {{
        background-color: transparent !important; border: none !important;
        box-shadow: none !important; color: {_pal['metin']} !important;
        padding: 8px 12px !important; border-radius: 8px !important;
        transition: all 0.2s ease !important;
    }}
    div[data-testid="stSidebar"] button:hover {{ {_pal['hover']} }}
    .glass-card {{
        {_pal['kart']} border-radius: 16px; padding: 24px; margin-bottom: 20px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.2);
    }}
    .persona-sidebar-card {{
        {_pal['persona']} padding: 12px; border-radius: 10px; margin-bottom: 10px;
    }}
    div[data-testid="stFileUploader"] {{
        {_pal['yukle']} border: 2px dashed #7C3AED !important;
        border-radius: 16px !important; padding: 20px !important;
    }}
    div[data-testid="stFileUploader"] div, div[data-testid="stFileUploader"] span,
    div[data-testid="stFileUploader"] p {{ color: {_pal['yazi']} !important; }}
    button[key="analyze_btn"] {{
        background: linear-gradient(135deg, #7C3AED 0%, #A855F7 100%) !important;
        border: none !important; color: white !important; font-weight: 700 !important;
        padding: 16px 32px !important; border-radius: 12px !important;
        box-shadow: 0 4px 20px rgba(124,58,237,0.4) !important;
    }}
    .badge-critical {{
        background-color: #EF4444; color: white; padding: 4px 8px;
        border-radius: 6px; font-size: 0.75rem; font-weight: bold;
    }}
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    if durum["sol_panel_acik"]:
        c1, c2 = st.columns([7, 3])
        with c1:
            if LOGO_YOLU:
                st.image(LOGO_YOLU, width=220)
            else:
                st.markdown("## 🧠 CogniTrace")
        with c2:
            if st.button("«", help="Paneli Daralt"):
                durum["sol_panel_acik"] = False
                st.rerun()
    else:
        if st.button("»", help="Paneli Genişlet", use_container_width=True):
            durum["sol_panel_acik"] = True
            st.rerun()

    for nav in ({"ad": "Analiz Paneli", "ikon": "🔎"}, {"ad": "Gelişim Analitiği", "ikon": "📈"},
                {"ad": "Geri Bildirim", "ikon": "💬"},
                {"ad": "Ayarlar", "ikon": "⚙️"}, {"ad": "Kullanıcı Profili", "ikon": "👤"}):
        etiket = f"{nav['ikon']} {nav['ad']}" if durum["sol_panel_acik"] else nav["ikon"]
        if st.button(etiket, use_container_width=True, key=f"nav_{nav['ad']}"):
            durum["aktif_sekme"] = nav["ad"]
            st.rerun()

    if durum["sol_panel_acik"]:
        st.markdown("---")
        st.markdown("### 👥 Aktif Personalar")
        for p in PERSONAS.values():
            ozet = p.get("aciklama") or (p["prompt"].splitlines()[0][:70] + "...")
            st.markdown(
                f'<div class="persona-sidebar-card"><strong>{p["emoji"]} {p["ad"]}</strong><br/>'
                f'<small>{ozet}</small></div>',
                unsafe_allow_html=True,
            )

# --- ÜST BAŞLIK ---
col_baslik, col_sag = st.columns([7, 3])
with col_baslik:
    cl, ct = st.columns([2.2, 7.8])
    with cl:
        if LOGO_YOLU:
            st.image(LOGO_YOLU, width=160)
        else:
            st.markdown("# 🧠")
    with ct:
        st.markdown(
            "<div style='padding-top:15px;'><h1 style='margin:0; font-weight:800; "
            "font-size:2.6rem;'>CogniTrace</h1></div>", unsafe_allow_html=True)
        st.caption("Nöroçeşitli kullanıcılar için erişilebilirlik ve bilişsel yük ölçüm istasyonu — Takım 307")
with col_sag:
    c_tema, c_profil = st.columns(2)
    with c_tema:
        tema_secimi = st.selectbox("Tema", ["Koyu", "Açık"],
                                   index=0 if durum["tema"] == "Koyu" else 1,
                                   label_visibility="collapsed")
        if tema_secimi != durum["tema"]:
            durum["tema"] = tema_secimi
            st.rerun()
    with c_profil:
        if durum["giris_yapildi"]:
            if st.button("🚪 Çıkış", use_container_width=True):
                durum["giris_yapildi"] = False
                st.rerun()
        elif st.button("👤 Giriş", use_container_width=True):
            durum["aktif_sekme"] = "Kullanıcı Profili"
            st.rerun()

st.divider()

# --- ANALİZ PANELİ ---
if durum["aktif_sekme"] == "Analiz Paneli":
    st.markdown("""
    <div class="glass-card" style="text-align:center; background: linear-gradient(135deg,
    rgba(124,58,237,0.1) 0%, rgba(168,85,247,0.1) 100%);">
        <h2 style="margin:0 0 10px 0; font-weight:700;">Yapay Zeka Destekli Erişilebilirlik Analizi 🚀</h2>
        <p style="margin:0; opacity:0.8;">Ekran görüntüsü yükleyin, URL yakalayın veya galeriden
        örnek açın — persona ajanları + koordinatör sentezi + kural tabanlı doğrulama.</p>
    </div>
    """, unsafe_allow_html=True)

    col_girdi, col_ayar = st.columns([1, 1])
    with col_girdi:
        st.markdown("### 📂 Girdi Kaynağı")
        girdi_modu = st.radio("Kaynak", ["📸 Dosya", "🌐 URL", "📁 Galeri"],
                              horizontal=True, label_visibility="collapsed")
        if girdi_modu == "📸 Dosya":
            dosya = st.file_uploader("Sürükleyin veya seçin (PNG, JPG)", type=["png", "jpg", "jpeg"])
            if dosya:
                durum["goruntu"] = dosya.getvalue()
                durum["mime"] = dosya.type or "image/png"
                durum["dosya_adi"] = dosya.name
                durum["html"] = None
                durum["axe"] = None
        elif girdi_modu == "🌐 URL":
            url = st.text_input("Site adresi", placeholder="ornek.gov.tr")
            tam_sayfa = st.checkbox("Tam sayfa (uzun görüntü)", value=False)
            if st.button("📥 Sayfayı Yakala", use_container_width=True) and url:
                try:
                    from web_capture import sayfa_yakala
                    with st.spinner("Sayfa ziyaret ediliyor..."):
                        y = sayfa_yakala(url, tam_sayfa=tam_sayfa)
                    durum["goruntu"], durum["mime"] = y["png"], "image/png"
                    durum["html"], durum["axe"] = y["html"], y["axe"]
                    durum["dosya_adi"] = url
                    st.success("Yakalandı ✓ — HTML kod analizi otomatik dahil")
                except Exception as hata:
                    st.error(f"Yakalama başarısız: {hata}")
        else:
            ornekler = gallery.listele()
            if not ornekler:
                st.info("Galeri boş — analiz sonrası '💾 Galeriye kaydet' ile örnek ekleyin.")
            else:
                secilen_ornek = st.selectbox("Kayıtlı örnek", ornekler)
                if st.button("📂 Örneği Aç", use_container_width=True):
                    g_bytes, g_sonuclar, g_rapor = gallery.yukle(secilen_ornek)
                    durum["goruntu"], durum["mime"] = g_bytes, "image/png"
                    durum["html"], durum["axe"] = None, None
                    durum["dosya_adi"] = secilen_ornek
                    durum["analiz_sonuclari_state"] = g_sonuclar
                    durum["rapor_state"] = g_rapor
                    if g_rapor:
                        durum["genel_skor_state"] = int(g_rapor.get("genel_skor", 0))
                        durum["engelsiz_skor_state"] = 100 - durum["genel_skor_state"]
                    st.info("📁 Kayıtlı analiz yüklendi (API çağrısı yapılmadı).")

    with col_ayar:
        st.markdown("### 🛠️ Yapılandırma ve Personalar")
        secilen_personalar = st.multiselect(
            "Hedef Personalar", options=list(PERSONAS.keys()), default=list(PERSONAS.keys()),
            format_func=lambda k: f"{PERSONAS[k]['emoji']} {PERSONAS[k]['ad']}")
        simulasyon_tipi = st.selectbox("Renk Körlüğü Simülasyonu",
                                       ["(kapalı)"] + list(DONUSUM_MATRISLERI))
        # Geçmiş Analiz Karşılaştırma (Ajan Hafızası)
        ornekler_liste = gallery.listele()
        if ornekler_liste:
            secilen_gecmis = st.selectbox(
                "🧠 Hafıza: Önceki Sürümle Karşılaştır (Gelişim Raporu)",
                ["(karşılaştırma yok)"] + ornekler_liste
            )
        else:
            secilen_gecmis = "(karşılaştırma yok)"
        with st.expander("📖 Disleksi metin simülasyonu"):
            metin = st.text_area("Bir paragraf yapıştırın", height=80, key="dys")
            if metin:
                st.write(disleksi_metni(metin))
                st.caption("Basitleştirilmiş empati aracı; deneyim kişiden kişiye değişir.")

    if durum.get("goruntu"):
        goruntu = Image.open(io.BytesIO(durum["goruntu"]))
        cg1, cg2 = st.columns(2)
        with cg1:
            st.markdown("**Orijinal Görünüm**")
            st.image(goruntu, use_container_width=True)
        with cg2:
            if simulasyon_tipi != "(kapalı)":
                st.markdown(f"**Simüle Edilen Görünüm ({simulasyon_tipi.capitalize()})**")
                st.image(simule_et(goruntu, simulasyon_tipi), use_container_width=True)
            else:
                st.markdown("**Renk Körlüğü Filtre Simülasyonu**")
                st.info("Simülasyon türü seçerek renk körü kullanıcıların gözünden bakın.")

        if durum.get("axe"):
            with st.expander(f"🧪 axe-core kural taraması — {len(durum['axe'])} WCAG ihlali "
                             "(çapraz doğrulama)"):
                rozet = {"critical": "🔴", "serious": "🟠", "moderate": "🟡", "minor": "🟢"}
                for ih in durum["axe"]:
                    st.markdown(f"- {rozet.get(ih['etki'], '⚪')} **{ih['kural']}** "
                                f"({ih['etki']}): {ih['aciklama']} — {ih['eleman_sayisi']} eleman")

        st.markdown("<br/>", unsafe_allow_html=True)
        baslat = st.button("Analizi Gerçekleştir 🚀", key="analyze_btn", use_container_width=True)

        if baslat and not secilen_personalar:
            st.warning("En az bir persona seçin.")
        elif baslat:
            adimlar = ["Görüntü Hazır ✅", "Persona Ajanları 🤖", "Koordinatör Sentezi 🧭",
                       "Kural Taraması 🧪", "Bölge İşaretleme 📍", "Rapor Hazır 🎉"]
            for kolon, adim in zip(st.columns(6), adimlar, strict=True):
                kolon.markdown(
                    f"<div style='background:rgba(124,58,237,0.15); border:1px solid #7C3AED; "
                    f"padding:10px; border-radius:8px; text-align:center; font-weight:600; "
                    f"font-size:0.85rem;'>{adim}</div>", unsafe_allow_html=True)
            st.markdown("<br/>", unsafe_allow_html=True)

            from concurrent.futures import ThreadPoolExecutor

            sonuclar: dict[str, dict] = {}
            with st.spinner("Persona ajanları arayüzü eşzamanlı denetliyor..."):
                with ThreadPoolExecutor() as executor:
                    futures = {
                        executor.submit(analiz_et, durum["goruntu"], durum["mime"],
                                        anahtar, durum.get("html")): anahtar
                        for anahtar in secilen_personalar
                    }
                    kota_doldu = False
                    model_mesgul = False
                    for future in futures:
                        anahtar = futures[future]
                        try:
                            sonuclar[anahtar] = future.result()
                        except KotaAsildi:
                            kota_doldu = True
                        except ModelMesgul:
                            model_mesgul = True
                        except Exception as hata:
                            st.error(f"Analiz başarısız ({PERSONAS[anahtar]['ad']}): {hata}")

            # Model yoğunluğu: geçici durum, tekrar denemeye yönlendir.
            if model_mesgul:
                st.warning(
                    "⏳ **Model şu anda yoğun.** Google tarafında geçici bir "
                    "yoğunluk var (503). Sistem otomatik olarak yeniden denedi ve "
                    "yedek modele düştü, yine de yanıt alınamadı. Birkaç dakika "
                    "sonra tekrar deneyin veya **Ayarlar** sayfasından daha kararlı "
                    "bir model seçin."
                )

            # Kota bittiğinde ham hata yerine yönlendirici mesaj göster.
            if kota_doldu:
                st.warning(
                    "⏳ **Günlük API kotası doldu.** Yeni analiz şu an yapılamıyor — "
                    "sol taraftan **📁 Galeri** kaynağını seçerek kayıtlı analizleri "
                    "inceleyebilirsiniz. Kota her gün sıfırlanır."
                )

            if sonuclar:
                with st.spinner("Koordinatör ajan bulguları sentezliyor..."):
                    gecmis_rapor = None
                    if secilen_gecmis != "(karşılaştırma yok)":
                        try:
                            _, _, g_rapor = gallery.yukle(secilen_gecmis)
                            gecmis_rapor = g_rapor
                        except Exception:
                            pass
                    rapor = koordine_et(sonuclar, gecmis_rapor=gecmis_rapor)
                tarifler = [f"{a.get('bolge', '')}: {a.get('sorun', '')}"
                            for s in sonuclar.values()
                            for a in s.get("sorunlu_alanlar", [])
                            if a.get("onem") in ("yuksek", "orta")][:6]
                with st.spinner("Sorunlu bölgeler görüntü üzerinde işaretleniyor..."):
                    durum["isaretli_state"] = bolgeleri_isaretle(
                        durum["goruntu"], durum["mime"], tarifler)
                durum["analiz_sonuclari_state"] = sonuclar
                durum["rapor_state"] = rapor
                durum["genel_skor_state"] = int(rapor.get("genel_skor", 0))
                durum["engelsiz_skor_state"] = 100 - durum["genel_skor_state"]
    else:
        st.info("💡 Başlamak için görüntü yükleyin, URL yakalayın veya galeriden örnek açın.")

    # --- RAPORLAMA İSTASYONU ---
    st.markdown("---")
    st.markdown("<h2 style='font-weight:700;'>📊 Değerlendirme ve Raporlama İstasyonu</h2>",
                unsafe_allow_html=True)

    sonuclar_var = bool(durum["analiz_sonuclari_state"])
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.markdown(f"""
        <div class="glass-card"><span style="font-size:0.9rem; opacity:0.7;">🧠 GENEL BİLİŞSEL YÜK</span>
        <h2 style="margin:5px 0 0 0; color:#E11D48;">{durum['genel_skor_state'] if sonuclar_var else '—'}/100</h2>
        <span style="font-size:0.8rem; opacity:0.6;">Koordinatör ajan sentezi</span></div>
        """, unsafe_allow_html=True)
    with kpi2:
        st.markdown(f"""
        <div class="glass-card"><span style="font-size:0.9rem; opacity:0.7;">♿ ERİŞİLEBİLİRLİK PUANI</span>
        <h2 style="margin:5px 0 0 0; color:#10B981;">{('%' + str(durum['engelsiz_skor_state'])) if sonuclar_var else '—'}</h2>
        <span style="font-size:0.8rem; opacity:0.6;">100 − bilişsel yük</span></div>
        """, unsafe_allow_html=True)
    with kpi3:
        axe_sayi = len(durum["axe"]) if durum.get("axe") is not None else None
        st.markdown(f"""
        <div class="glass-card"><span style="font-size:0.9rem; opacity:0.7;">🧪 WCAG İHLALİ (axe-core)</span>
        <h2 style="margin:5px 0 0 0; color:#F59E0B;">{axe_sayi if axe_sayi is not None else '—'}</h2>
        <span style="font-size:0.8rem; opacity:0.6;">{'Kural tabanlı tarama' if axe_sayi is not None else 'URL modunda ölçülür'}</span></div>
        """, unsafe_allow_html=True)
    with kpi4:
        st.markdown(f"""
        <div class="glass-card"><span style="font-size:0.9rem; opacity:0.7;">👥 ANALİZ EDİLEN PERSONA</span>
        <h2 style="margin:5px 0 0 0; color:#3B82F6;">{len(durum['analiz_sonuclari_state']) if sonuclar_var else '—'}</h2>
        <span style="font-size:0.8rem; opacity:0.6;">Uzman ajan raporu</span></div>
        """, unsafe_allow_html=True)

    if sonuclar_var:
        col_g, col_r = st.columns(2)
        with col_g:
            st.markdown("### Genel Erişilebilirlik Puanı")
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number", value=durum["engelsiz_skor_state"],
                gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#7C3AED"},
                       "steps": [{"range": [0, 50], "color": "#FCA5A5"},
                                 {"range": [50, 80], "color": "#FDE68A"},
                                 {"range": [80, 100], "color": "#A7F3D0"}]}))
            fig_gauge.update_layout(paper_bgcolor="rgba(0,0,0,0)",
                                    font={"color": "gray", "family": "Plus Jakarta Sans"})
            st.plotly_chart(fig_gauge, use_container_width=True)
        with col_r:
            st.markdown("### Persona Uyum Boyutları")
            eksenler, degerler = [], []
            for anahtar, sonuc in durum["analiz_sonuclari_state"].items():
                eksenler.append(PERSONAS[anahtar]["ad"])
                degerler.append(100 - int(sonuc.get("bilissel_yuk_skoru", 0)))
            fig_radar = go.Figure(go.Scatterpolar(
                r=degerler, theta=eksenler, fill="toself", line_color="#7C3AED"))
            fig_radar.update_layout(
                polar={"radialaxis": {"visible": True, "range": [0, 100]}},
                showlegend=False, paper_bgcolor="rgba(0,0,0,0)",
                font={"color": "gray", "family": "Plus Jakarta Sans"})
            st.plotly_chart(fig_radar, use_container_width=True)

        # Koordinatör raporu
        rapor = durum["rapor_state"] or {}
        st.markdown("### 🧭 Koordinatör Ajan Raporu")
        if rapor.get("_yedek_mod"):
            st.info("Koordinatör LLM'e ulaşılamadı; deterministik birleştirme kullanıldı.")
        st.write(rapor.get("yonetici_ozeti", ""))
        if rapor.get("gelisim_yorumu"):
            st.success(f"📈 **Gelişim Analizi (Ajan Hafızası):** {rapor['gelisim_yorumu']}")
        if rapor.get("skor_gerekcesi"):
            st.caption(f"Skor gerekçesi: {rapor['skor_gerekcesi']}")
        for i, e in enumerate(rapor.get("oncelikli_eylemler", []), 1):
            r = {"yuksek": "🔴", "orta": "🟡", "dusuk": "🟢"}.get(e.get("oncelik", ""), "⚪")
            satir = f"{i}. {r} {e.get('sorun', '')}"
            if e.get("oneri"):
                satir += f" → **{e['oneri']}**"
            st.markdown(satir)
            if e.get("kod_onerisi"):
                st.code(e["kod_onerisi"], language="css")

        if durum.get("isaretli_state") is not None:
            st.markdown("### 📍 Sorunlu Bölgeler Görüntü Üzerinde")
            _, orta, _ = st.columns([1, 2, 1])
            with orta:
                st.image(durum["isaretli_state"], use_container_width=True)
                st.caption("Büyütmek için görüntünün üzerine gelip ⛶ simgesine tıklayın.")

        st.markdown("### 📋 Persona Bulguları")
        for anahtar, sonuc in durum["analiz_sonuclari_state"].items():
            p = PERSONAS.get(anahtar)
            if not p:
                continue
            st.markdown(f"#### {p['emoji']} {p['ad']} — {sonuc.get('bilissel_yuk_skoru', 0)}/100")
            for alan in sonuc.get("sorunlu_alanlar", []):
                st.markdown(f"""
                <div class="glass-card" style="margin-bottom:10px; border-left:5px solid #EF4444;">
                    <span class="badge-critical">{alan.get('onem', 'orta').upper()} ETKİ</span>
                    <strong style="margin-left:10px;">Bölge: {alan.get('bolge', 'Genel')}</strong>
                    <p style="margin:10px 0 0 0; opacity:0.9;">{alan.get('sorun', '')}</p>
                </div>""", unsafe_allow_html=True)
            if not sonuc.get("sorunlu_alanlar"):
                st.success(f"{p['ad']} personası için kritik engel tespit edilmedi.")
            if sonuc.get("oneriler"):
                with st.expander(f"💡 {p['ad']} önerileri"):
                    for o in sonuc["oneriler"]:
                        st.markdown(f"- {o}")

        # PDF + galeri
        st.markdown("### 📥 Rapor ve Kayıt")
        cp, cgal1, cgal2 = st.columns([2, 2, 1])
        with cp:
            pdf_ad = durum.get("dosya_adi", "analiz")
            pdf_data = pdf_olustur(durum["genel_skor_state"], durum["engelsiz_skor_state"],
                                   durum["analiz_sonuclari_state"], durum["rapor_state"],
                                   durum.get("axe"), pdf_ad)
            st.download_button("PDF Raporu İndir 📥", data=pdf_data,
                               file_name=f"CogniTrace_Rapor_{str(pdf_ad).split('.')[0][:40]}.pdf",
                               mime="application/pdf", use_container_width=True)
        with cgal1:
            galeri_adi = st.text_input("Galeri adı", placeholder="ornek-haber-sitesi",
                                       label_visibility="collapsed")
        with cgal2:
            if st.button("💾 Kaydet", use_container_width=True) and galeri_adi and durum.get("goruntu"):
                ad = gallery.kaydet(galeri_adi, durum["goruntu"],
                                    durum["analiz_sonuclari_state"], durum["rapor_state"])
                st.success(f"galeri/{ad} ✓")
    else:
        st.info("Grafikler, koordinatör raporu ve PDF çıktısı analiz sonrası burada görünecek.")

elif durum["aktif_sekme"] == "Gelişim Analitiği":
    st.markdown("### 📈 Gelişim Analitiği ve Analiz Geçmişi")
    st.write("Sitede yapılan erişilebilirlik ve bilişsel yük iyileştirmelerini zaman içinde takip edin.")

    ornekler = gallery.listele()
    if not ornekler:
        st.info("Henüz kaydedilmiş analiz bulunmuyor. Bir analizi gerçekleştirdikten sonra '💾 Kaydet' butonu ile galeriye ekleyebilirsiniz.")
    else:
        # Plot score trend
        tarihler = []
        genel_skorlar = []
        persona_skorlari = {p["ad"]: [] for p in PERSONAS.values()}
        
        for ad in ornekler:
            try:
                _, g_sonuclar, g_rapor = gallery.yukle(ad)
                tarihler.append(ad)
                if g_rapor:
                    genel_skorlar.append(g_rapor.get("genel_skor", 0))
                else:
                    genel_skorlar.append(0)
                
                for k, p in PERSONAS.items():
                    if k in g_sonuclar:
                        persona_skorlari[p["ad"]].append(g_sonuclar[k].get("bilissel_yuk_skoru", 0))
                    else:
                        persona_skorlari[p["ad"]].append(0)
            except Exception:
                continue
        
        if tarihler:
            fig = go.Figure()
            # Genel Bilişsel Yük Skoru
            fig.add_trace(go.Scatter(
                x=tarihler, y=genel_skorlar,
                mode="lines+markers",
                name="Genel Bilişsel Yük Skoru",
                line=dict(color="#EF4444", width=3)
            ))
            # Persona bazlı skorlar
            for p_ad, skorlar in persona_skorlari.items():
                fig.add_trace(go.Scatter(
                    x=tarihler, y=skorlar,
                    mode="lines+markers",
                    name=f"{p_ad} Bilişsel Yükü",
                    line=dict(dash="dash")
                ))
            
            fig.update_layout(
                title="Bilişsel Yük Trend Analizi (Düşük Skor = Daha İyi Erişilebilirlik)",
                xaxis_title="Analiz Versiyonları / Sayfalar",
                yaxis_title="Bilişsel Yük Skoru",
                yaxis=dict(range=[0, 100]),
                paper_bgcolor="rgba(0,0,0,0)",
                font={"family": "Plus Jakarta Sans"}
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # Show a summary list of saved items
            st.markdown("#### Kayıtlı Analiz Detayları")
            for ad in ornekler:
                with st.expander(f"📁 {ad}"):
                    try:
                        _, g_sonuclar, g_rapor = gallery.yukle(ad)
                        if g_rapor:
                            st.write(f"**Genel Bilişsel Yük Skoru:** {g_rapor.get('genel_skor', 0)}/100")
                            st.write(f"**Yönetici Özeti:** {g_rapor.get('yonetici_ozeti', '')}")
                        st.write("**Persona Bulguları:**")
                        for k, v in g_sonuclar.items():
                            st.write(f"- {PERSONAS[k]['ad']}: {v.get('bilissel_yuk_skoru', 0)}/100")
                    except Exception as e:
                        st.error(f"Hata: {e}")

elif durum["aktif_sekme"] == "Geri Bildirim":
    st.markdown("### 💬 Geri Bildirim")
    st.write("CogniTrace'i değerlendirin — görüşleriniz ürünü şekillendiriyor.")
    with st.form("geri_bildirim_formu"):
        gb_ad = st.text_input("İsim (opsiyonel)")
        gb_puan = st.slider("Genel puanınız", 1, 5, 4)
        gb_mesaj = st.text_area("Görüşleriniz", height=120)
        gonderildi = st.form_submit_button("Gönder 📨")
    if gonderildi and gb_mesaj.strip():
        feedback.kaydet(gb_ad, gb_puan, gb_mesaj)
        st.success("Teşekkürler! Geri bildiriminiz kaydedildi.")
    kayitlar = feedback.listele()
    if kayitlar:
        with st.expander(f"Gelen geri bildirimler ({len(kayitlar)})"):
            for k in reversed(kayitlar):
                st.markdown(f"**{k['ad']}** — {'⭐' * k['puan']} · {k['tarih']}")
                st.markdown(k["mesaj"])
                st.divider()

elif durum["aktif_sekme"] == "Ayarlar":
    st.markdown("### ⚙️ Sistem Ayarları")
    
    # 1. AI Model Ayarları
    st.markdown("####  Yapay Zeka Model Yapılandırması")
    from analyzer import anahtar_sayisi, get_model, mevcut_modeller, onbellegi_temizle
    current_model = get_model()

    # Model listesi API'den canlı çekilir: Google yeni sürüm yayınladığında
    # kod değişmeden listede belirir.
    with st.spinner("Kullanılabilir modeller alınıyor..."):
        modeller = mevcut_modeller()
    if current_model not in modeller:
        modeller.insert(0, current_model)

    secilen_model = st.selectbox(
        "Kullanılacak Gemini Modeli",
        options=modeller,
        index=modeller.index(current_model),
        help="Liste, API anahtarınızın erişebildiği modellerden canlı olarak alınır. "
             "Varsayılan olarak erişilebilen en yeni Flash sürümü seçilir."
    )
    if secilen_model != durum.get("secilen_model"):
        durum["secilen_model"] = secilen_model
        st.success(f"Model güncellendi: {secilen_model}")
        st.rerun()

    st.markdown("---")

    # 1b. Kota ve önbellek durumu
    st.markdown("#### 🔑 API Anahtarı ve Kota Yönetimi")
    _anahtar_adet = anahtar_sayisi()
    st.info(
        f"Tanımlı API anahtarı: **{_anahtar_adet}**. Bir anahtarın kotası dolduğunda "
        "sistem otomatik olarak sıradakine geçer. Ek anahtar tanımlamak için "
        "`GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` ... değişkenlerini kullanın "
        "(yerelde .env, bulutta Streamlit Secrets)."
    )
    if st.button("🔄 Analiz önbelleğini temizle", use_container_width=True):
        onbellegi_temizle()
        st.success("Önbellek temizlendi; sonraki analiz modele yeniden sorulacak.")

    st.markdown("---")

    # 2. Galeri & Hafıza Veri Yönetimi
    st.markdown("#### 🧹 Veri ve Geçmiş Yönetimi")
    st.info("Kayıtlı analiz geçmişi ve galeri verilerini buradan sıfırlayabilirsiniz.")
    
    if "silme_onayi" not in durum:
        durum["silme_onayi"] = False

    if not durum["silme_onayi"]:
        if st.button("🚨 Tüm Analiz Geçmişini Sil", type="secondary", use_container_width=True):
            durum["silme_onayi"] = True
            st.rerun()
    else:
        st.warning("⚠️ Tüm analiz geçmişini ve kayıtlı verileri silmek istediğinize emin misiniz? Bu işlem geri alınamaz!")
        col_onay1, col_onay2 = st.columns(2)
        with col_onay1:
            if st.button("Evet, Tamamen Sil", type="primary", use_container_width=True):
                import shutil
                from gallery import GALERI_YOL
                if GALERI_YOL.exists():
                    try:
                        shutil.rmtree(GALERI_YOL)
                        GALERI_YOL.mkdir(parents=True, exist_ok=True)
                        st.success("Tüm analiz geçmişi ve galeri temizlendi!")
                    except Exception as e:
                        st.error(f"Hata oluştu: {e}")
                durum["silme_onayi"] = False
                st.rerun()
        with col_onay2:
            if st.button("İptal Et", type="secondary", use_container_width=True):
                durum["silme_onayi"] = False
                st.rerun()

elif durum["aktif_sekme"] == "Kullanıcı Profili":
    st.markdown("### 👤 Kullanıcı Girişi (demo)")
    kullanici = st.text_input("Kullanıcı Adı", value="")
    if st.button("Giriş Yap", type="primary") and kullanici:
        durum["giris_yapildi"] = True
        st.success(f"Başarıyla giriş yapıldı: {kullanici}")
        st.rerun()

# --- FOOTER ---
st.markdown("<br/><br/>", unsafe_allow_html=True)
st.markdown(
    f"""
    <div style="text-align: center; padding: 20px 0; margin-top: 40px; 
                border-top: 1px solid {_pal['kenar']}; opacity: 0.7; font-size: 0.85rem;">
        <p style="margin: 0; font-weight: 500;">🧠 <strong>CogniTrace</strong> — Erişilebilirlik & Bilişsel Yük Analiz İstasyonu</p>
        <p style="margin: 5px 0 0 0; font-size: 0.75rem;">© 2026 Takım 307. Tüm Hakları Saklıdır.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
