from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

# Logging yapılandırması
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Sabit token (Sen güncelleyeceksin)
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbnYiOiJMSVZFIiwiaXBiIjoiMCIsImNnZCI6IjA5M2Q3MjBhLTUwMmMtNDFlZC1hODBmLTJiODE2OTg0ZmI5NSIsImNzaCI6IlRSS1NUIiwiZGN0IjoiM0VGNzUiLCJkaSI6ImE2OTliODNmLTgyNmItNGQ5OS05MzYxLWM4YTMxMzIxOGQ0NiIsInNnZCI6Ijg5NzQxZmVjLTFkMzMtNGMwMC1hZmNkLTNmZGFmZTBiNmEyZCIsInNwZ2QiOiIxNTJiZDUzOS02MjIwLTQ0MjctYTkxNS1iZjRiZDA2OGQ3ZTgiLCJpY2giOiIwIiwiaWRtIjoiMCIsImlhIjoiOjpmZmZmOjEwLjAuMC4yMDYiLCJhcHYiOiIxLjAuMCIsImFibiI6IjEwMDAiLCJuYmYiOjE3NDUxNTI4MjUsImV4cCI6MTc0NTE1Mjg4NSwiaWF0IjoxNzQ1MTUyODI1fQ.OSlafRMxef4EjHG5t6TqfAQC7y05IiQjwwgf6yMUS9E"

# --- YENİ: Önbellekleme için değişkenler ---
kanallar_cache: Optional[List[Dict[str, Any]]] = None
cache_son_guncelleme: Optional[datetime] = None
CACHE_SURESI = timedelta(hours=1)  # Önbelleği 1 saat geçerli tut

async def kanallari_getir() -> List[Dict[str, Any]]:
    global kanallar_cache, cache_son_guncelleme
    
    simdiki_zaman = datetime.now()
    
    # Önbellek geçerli mi kontrol et
    if kanallar_cache and cache_son_guncelleme and (simdiki_zaman - cache_son_guncelleme < CACHE_SURESI):
        logging.info("Kanal listesi önbellekten getirildi.")
        return kanallar_cache

    # Önbellek boş veya süresi dolmuşsa, API'den yeniden çek
    logging.info("Önbellek boş veya süresi dolmuş. API'den yeni kanal listesi çekiliyor...")
    headers = {"Authorization": AUTH_TOKEN}
    
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://core-api.kablowebtv.com/api/channels",
                headers=headers,
                timeout=10.0 # İstek için 10 saniye zaman aşımı ekle
            )
            r.raise_for_status() # 2xx dışındaki durum kodları için hata fırlat
            
            data = r.json()
            
            # API'den gelen veriyi önbelleğe al
            kanallar_cache = data.get("Data", {}).get("AllChannels", [])
            cache_son_guncelleme = simdiki_zaman
            
            logging.info(f"{len(kanallar_cache)} kanal başarıyla çekildi ve önbelleğe alındı.")
            return kanallar_cache

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Token geçersiz veya süresi dolmuş! Lütfen AUTH_TOKEN'i güncelleyin.")
        else:
            raise HTTPException(status_code=e.response.status_code, detail=f"API'den veri alınamadı: {e}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"API'ye bağlanırken bir hata oluştu: {e}")
    except (KeyError, TypeError, ValueError) as e: # ValueError'ı da ekleyerek JSON parse hatalarını yakala
        raise HTTPException(status_code=500, detail=f"API'den gelen veri formatı beklenmedik veya bozuk: {e}")


# 🔴 Kanal Açma
@app.get("/ac")
async def kanal_ac(
    id: Optional[str] = Query(None),
    isim: Optional[str] = Query(None)
):
    kanallar = await kanallari_getir()
    
    if not id and not isim:
        raise HTTPException(status_code=400, detail="Kanal bulmak için 'id' veya 'isim' parametresi zorunludur.")

    if id:
        if id.endswith('.m3u8'):
            id = id[:-5]
        
        try:
            id_int = int(id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz ID formatı! ID sayısal bir değer olmalıdır.")
        
        if 1 <= id_int <= len(kanallar):
            stream_url = kanallar[id_int-1].get("StreamData", {}).get("HlsStreamUrl")
            if not stream_url:
                raise HTTPException(status_code=404, detail=f"ID {id_int} için yayın adresi bulunamadı.")
            return RedirectResponse(stream_url)
        
        raise HTTPException(status_code=404, detail=f"Geçersiz ID! Lütfen 1 ile {len(kanallar)} arasında bir değer girin.")
    
    if isim:
        aranan_isim = isim.lower().replace(" ", "_")
        for kanal in kanallar:
            kanal_adi = kanal.get("Name", "").lower().replace(" ", "_")
            if aranan_isim in kanal_adi:
                stream_url = kanal.get("StreamData", {}).get("HlsStreamUrl")
                if not stream_url:
                    continue
                return RedirectResponse(stream_url)
        raise HTTPException(status_code=404, detail=f"'{isim}' adıyla eşleşen bir kanal bulunamadı!")

# 🖼️ Logo Göster
@app.get("/logo")
async def logo_goster(
    id: Optional[int] = Query(None),
    isim: Optional[str] = Query(None)
):
    kanallar = await kanallari_getir()
    
    if id and 1 <= id <= len(kanallar):
        # DEĞİŞTİ: Logo URL'sini .get() ile güvenli bir şekilde alıyoruz.
        logo_url = kanallar[id-1].get("Logo")
        if logo_url:
            return RedirectResponse(logo_url)
    
    if isim:
        for kanal in kanallar:
            if isim.lower() in kanal.get("Name", "").lower():
                # DEĞİŞTİ: Logo URL'sini .get() ile güvenli bir şekilde alıyoruz.
                logo_url = kanal.get("Logo")
                if logo_url:
                    return RedirectResponse(logo_url)
    
    raise HTTPException(status_code=404, detail="Kanal veya logo bulunamadı!")

# 📺 M3U Playlist
@app.get("/liste.m3u")
async def m3u_olustur():
    kanallar = await kanallari_getir()
    m3u_lines = ["#EXTM3U"]
    
    for idx, kanal in enumerate(kanallar, 1):
        stream_url = kanal.get("StreamData", {}).get("HlsStreamUrl", "")
        if stream_url:
            # --- DEĞİŞTİ: kanal["Name"] ve kanal["Logo"] yerine .get() kullanıldı ---
            # Bu, Name veya Logo anahtarı eksik olsa bile kodun çökmesini engeller.
            kanal_adi = kanal.get("Name", f"İsimsiz Kanal {idx}")
            logo_url = kanal.get("Logo", "")
            
            m3u_lines.append(f'#EXTINF:-1 tvg-id="{idx}" tvg-name="{kanal_adi}" tvg-logo="{logo_url}",{kanal_adi}')
            m3u_lines.append(stream_url)
    
    return PlainTextResponse("\n".join(m3u_lines))

# 🏠 Ana Sayfa
@app.get("/")
async def ana_sayfa():
    cache_status = "Önbellek boş."
    if kanallar_cache is not None and cache_son_guncelleme is not None:
        cache_status = f"Önbellekte {len(kanallar_cache)} kanal var. Son güncelleme: {cache_son_guncelleme.strftime('%Y-%m-%d %H:%M:%S')}"

    return {
        "mesaj": "Kablonet TV Yayın Servisi",
        "kullanim": {
            "/ac?id=3": "ID'si 3 olan kanalı açar.",
            "/ac?id=3.m3u8": "ID'si 3 olan kanalı .m3u8 uzantılı açar.",
            "/ac?isim=show_tv": "Adında 'show_tv' geçen kanalı açar.",
            "/logo?id=5": "ID'si 5 olan kanalın logosunu gösterir.",
            "/liste.m3u": "Tüm kanallar için IPTV playlist dosyası oluşturur."
        },
        "onbellek_durumu": cache_status,
        "uyari": "Token süresi dolduğunda 'AUTH_TOKEN' değişkenini güncellemeyi unutmayın! Uygulamanın yeniden başlatılması gerekebilir."
    }
