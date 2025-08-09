from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse, StreamingResponse # EKLENDİ: StreamingResponse
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

# Logging yapılandırması
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# Sabit token (Bunu güncel tutmalısın)
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbnYiOiJMSVZFIiwiaXBiIjoiMCIsImNnZCI6IjA5M2Q3MjBhLTUwMmMtNDFlZC1hODBmLTJiODE2OTg0ZmI5NSIsImNzaCI6IlRSS1NUIiwiZGN0IjoiM0VGNzUiLCJkaSI6ImE2OTliODNmLTgyNmItNGQ5OS05MzYxLWM4YTMxMzIxOGQ0NiIsInNnZCI6Ijg5NzQxZmVjLTFkMzMtNGMwMC1hZmNkLTNmZGFmZTBiNmEyZCIsInNwZ2QiOiIxNTJiZDUzOS02MjIwLTQ0MjctYTkxNS1iZjRiZDA2OGQ3ZTgiLCJpY2giOiIwIiwiaWRtIjoiMCIsImlhIjoiOjpmZmZmOjEwLjAuMC4yMDYiLCJhcHYiOiIxLjAuMCIsImFibiI6IjEwMDAiLCJuYmYiOjE3NDUxNTI4MjUsImV4cCI6MTc0NTE1Mjg4NSwiaWF0IjoxNzQ1MTUyODI1fQ.OSlafRMxef4EjHG5t6TqfAQC7y05IiQjwwgf6yMUS9E"

# Önbellekleme için değişkenler
kanallar_cache: Optional[List[Dict[str, Any]]] = None
cache_son_guncelleme: Optional[datetime] = None
CACHE_SURESI = timedelta(hours=1)

async def kanallari_getir() -> List[Dict[str, Any]]:
    global kanallar_cache, cache_son_guncelleme
    simdiki_zaman = datetime.now()
    if kanallar_cache and cache_son_guncelleme and (simdiki_zaman - cache_son_guncelleme < CACHE_SURESI):
        logging.info("Kanal listesi önbellekten getirildi.")
        return kanallar_cache
    logging.info("Önbellek boş veya süresi dolmuş. API'den yeni kanal listesi çekiliyor...")
    headers = {"Authorization": AUTH_TOKEN}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://core-api.kablowebtv.com/api/channels", headers=headers, timeout=10.0)
            r.raise_for_status()
            data = r.json()
            kanallar_cache = data.get("Data", {}).get("AllChannels", [])
            cache_son_guncelleme = simdiki_zaman
            logging.info(f"{len(kanallar_cache)} kanal başarıyla çekildi ve önbelleğe alındı.")
            return kanallar_cache
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            raise HTTPException(status_code=401, detail="Token geçersiz veya süresi dolmuş!")
        else:
            raise HTTPException(status_code=e.response.status_code, detail=f"API'den veri alınamadı: {e}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"API'ye bağlanırken bir hata oluştu: {e}")
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"API'den gelen veri formatı beklenmedik: {e}")


# ==============================================================================
# 🆕 YENİ: EXO PLAYER VE DİĞER MODERN OYNATICILAR İÇİN STREAMING UÇ NOKTASI
# ==============================================================================
@app.get("/stream/{channel_id}")
async def stream_channel(channel_id: str):
    kanallar = await kanallari_getir()
    if channel_id.endswith('.m3u8'):
        channel_id = channel_id[:-5]
    try:
        id_int = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Geçersiz ID formatı.")
    if not (1 <= id_int <= len(kanallar)):
        raise HTTPException(status_code=404, detail=f"Geçersiz ID.")
    stream_url = kanallar[id_int - 1].get("StreamData", {}).get("HlsStreamUrl")
    if not stream_url:
        raise HTTPException(status_code=404, detail=f"Yayın adresi bulunamadı.")

    async def stream_generator():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", stream_url, timeout=30.0) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.HTTPError as e:
            logging.error(f"Kaynak yayını alırken hata: {e}")
            return
    
    return StreamingResponse(stream_generator(), media_type="application/x-mpegURL")


# ==============================================================================
# ESKİ KODLARINIZ (Değişiklik yapılmadı, diğer sistemlerle uyumluluk için duruyor)
# ==============================================================================

@app.get("/ac")
async def kanal_ac(id: Optional[str] = Query(None), isim: Optional[str] = Query(None)):
    kanallar = await kanallari_getir()
    if not id and not isim:
        raise HTTPException(status_code=400, detail="ID veya isim gerekli.")
    if id:
        if id.endswith('.m3u8'):
            id = id[:-5]
        try:
            id_int = int(id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz ID formatı.")
        if 1 <= id_int <= len(kanallar):
            stream_url = kanallar[id_int-1].get("StreamData", {}).get("HlsStreamUrl")
            if not stream_url:
                raise HTTPException(status_code=404, detail=f"Yayın adresi bulunamadı.")
            return RedirectResponse(stream_url)
        raise HTTPException(status_code=404, detail=f"Geçersiz ID.")
    if isim:
        aranan_isim = isim.lower().replace(" ", "_")
        for kanal in kanallar:
            kanal_adi = kanal.get("Name", "").lower().replace(" ", "_")
            if aranan_isim in kanal_adi:
                stream_url = kanal.get("StreamData", {}).get("HlsStreamUrl")
                if not stream_url:
                    continue
                return RedirectResponse(stream_url)
        raise HTTPException(status_code=404, detail=f"'{isim}' kanalı bulunamadı!")

@app.get("/logo")
async def logo_goster(id: Optional[int] = Query(None), isim: Optional[str] = Query(None)):
    kanallar = await kanallari_getir()
    if id and 1 <= id <= len(kanallar):
        logo_url = kanallar[id-1].get("Logo")
        if logo_url: return RedirectResponse(logo_url)
    if isim:
        for kanal in kanallar:
            if isim.lower() in kanal.get("Name", "").lower():
                logo_url = kanal.get("Logo")
                if logo_url: return RedirectResponse(logo_url)
    raise HTTPException(status_code=404, detail="Logo bulunamadı!")

@app.get("/liste.m3u")
async def m3u_olustur():
    kanallar = await kanallari_getir()
    m3u_lines = ["#EXTM3U"]
    for idx, kanal in enumerate(kanallar, 1):
        # ⚠️ UYARI: liste.m3u dosyasındaki linkler ExoPlayer'da ÇALIŞMAYACAK!
        # Çünkü bu liste, sizin YENİ /stream/ linklerinizi değil, doğrudan KabloTV linklerini içerir.
        # Bu listeyi ExoPlayer harici bir oynatıcıda kullanabilirsiniz.
        # ExoPlayer'a kanalları tek tek /stream/ linki ile vermelisiniz.
        stream_url = kanal.get("StreamData", {}).get("HlsStreamUrl", "")
        if stream_url:
            kanal_adi = kanal.get("Name", f"Kanal {idx}")
            logo_url = kanal.get("Logo", "")
            m3u_lines.append(f'#EXTINF:-1 tvg-id="{idx}" tvg-name="{kanal_adi}" tvg-logo="{logo_url}",{kanal_adi}')
            m3u_lines.append(stream_url)
    return PlainTextResponse("\n".join(m3u_lines))

@app.get("/")
async def ana_sayfa():
    return {"mesaj": "ExoPlayer Uyumlu Yayın Servisi", "yeni_kullanim": "ExoPlayer için '/stream/ID' formatını kullanın. Örnek: /stream/2"}
