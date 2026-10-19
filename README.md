# AI haber toplayıcı

Her gece 06:30'da (İstanbul) YouTube, Reddit, GitHub ve Hacker News'ten son 48 saatin içeriğini toplar ve `data/latest.md` dosyasına yazar. Sabah 07:50'de çalışan bülten görevi bu dosyayı okuyup Notion'a özetler.

## Kurulum (yaklaşık 10 dakika)

1. **Yeni bir GitHub deposu aç.** Adı örneğin `ai-news-collector`. **Public** olsun (içinde sadece zaten herkese açık başlıklar ve linkler olacak, gizli bir şey yok; bülten görevi dosyayı anahtarsız okuyabilsin diye).
2. Bu klasördeki tüm dosyaları depoya yükle (`collect.py`, `README.md`, `.github/workflows/collect.yml`).
3. **YouTube API anahtarı al (ücretsiz):**
   - https://console.cloud.google.com adresinde bir proje oluştur.
   - "APIs & Services" > "Library" > **YouTube Data API v3** > Enable.
   - "Credentials" > "Create credentials" > **API key**.
   - Günlük ücretsiz kota 10.000 birim; bu script günde yaklaşık 1.600 birim kullanır.
4. Depoda **Settings > Secrets and variables > Actions > New repository secret**:
   - Name: `YOUTUBE_API_KEY`, Value: aldığın anahtar.
5. Depoda **Actions** sekmesi > `collect-ai-news` > **Run workflow** ile bir kez elle çalıştır.
6. Bittiğinde `data/latest.md` dosyasını aç, içeriği kontrol et. Üstte "Toplama hataları" başlığı varsa hangi kaynağın çekilemediğini orada yazar.

## Notlar

- **Reddit** bazen GitHub'ın sunucu IP'lerini engeller (403/429). Öyle olursa dosyanın üstünde hata olarak görünür, diğer kaynaklar etkilenmez.
- **YouTube transkripti** en iyi çaba ile denenir. YouTube bulut IP'lerinde sık engeller; alınamazsa video başlık, kanal, izlenme ve açıklama ile listelenir.
- Aranan konular ve subreddit'ler `collect.py` dosyasının en üstündeki listelerde. Orayı düzenleyerek kaynakları değiştirebilirsin.
- İlk çalıştırma sonrası dosyanın ham linki şu formatta olur: `https://raw.githubusercontent.com/<kullanıcı>/<depo>/main/data/latest.md` (bülten görevi bunu okuyacak).
