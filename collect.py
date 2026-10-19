#!/usr/bin/env python3
"""Günlük AI haber toplayıcı.

YouTube (Data API), Reddit (RSS), GitHub (arama API) ve Hacker News (Algolia)
kaynaklarından son 48 saatin içeriğini toplar ve data/latest.md + data/latest.json
dosyalarına yazar. Sadece standart kütüphane kullanır (transkript için opsiyonel
youtube-transcript-api hariç). Her bölüm bağımsız çalışır; biri düşerse diğerleri devam eder.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "ai-news-collector/1.0 (personal daily digest)"
NOW = dt.datetime.now(dt.timezone.utc)
SINCE = NOW - dt.timedelta(hours=48)
SINCE_ISO = SINCE.strftime("%Y-%m-%dT%H:%M:%SZ")
WEEK_AGO = (NOW - dt.timedelta(days=7)).strftime("%Y-%m-%d")

YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")

YT_QUERIES_EN = [
    "Claude Code", "Claude plugin", "Claude skills", "MCP server",
    "ChatGPT new feature", "OpenAI Codex", "AI agent automation", "vibe coding", "n8n AI agent",
]
YT_QUERIES_TR = [
    "Claude Code", "Claude yapay zeka", "ChatGPT yeni özellik",
    "yapay zeka otomasyon", "n8n yapay zeka", "yapay zeka ajanı",
]
SUBREDDITS = [
    "ClaudeAI", "ClaudeCode", "ChatGPT", "OpenAI", "mcp", "n8n",
    "LocalLLaMA", "vibecoding", "ChatGPTCoding",
]
GH_QUERIES = [
    ("MCP sunucuları", f"topic:mcp created:>{WEEK_AGO}"),
    ("Claude Code eklenti/skill", f"claude code in:name,description,topics created:>{WEEK_AGO}"),
    ("AI agent", f"topic:ai-agents created:>{WEEK_AGO}"),
]

errors = []
result = {"generated_at": NOW.isoformat(), "youtube": [], "reddit": [], "github": [], "hackernews": []}


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def http_json(url, headers=None):
    return json.loads(http_get(url, headers))


def http_get_retry(url, tries=3, base_wait=20):
    """429 (Too Many Requests) gelirse bekleyip yeniden dener."""
    for attempt in range(1, tries + 1):
        try:
            return http_get(url)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries:
                time.sleep(base_wait * attempt)
                continue
            raise


TR_CHARS = re.compile(r"[ğüşıöçĞÜŞİÖÇ]")
AI_RELEVANT = re.compile(
    r"claude|anthropic|openai|chatgpt|gpt|llm|mcp|agent|gemini|codex|copilot|cursor|n8n|"
    r"\bai\b|artificial intelligence|machine learning|vibe cod|prompt|model",
    re.I,
)


def clean(text, n=300):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[: n - 1] + "…" if len(text) > n else text


# ---------------- YouTube ----------------
def transcript_for(video_id):
    """Best-effort transkript. YouTube bulut IP'lerini sık engeller; başarısız olursa boş döner."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception:
        return ""
    try:
        try:
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=["tr", "en"])
            parts = [s.text for s in fetched]
        except AttributeError:
            parts = [s["text"] for s in YouTubeTranscriptApi.get_transcript(video_id, languages=["tr", "en"])]
        return clean(" ".join(parts), 6000)
    except Exception:
        return ""


def collect_youtube():
    if not YT_KEY:
        errors.append("YouTube: YOUTUBE_API_KEY tanımlı değil, bu bölüm atlandı.")
        return
    seen = {}
    for lang, queries in (("tr", YT_QUERIES_TR), ("en", YT_QUERIES_EN)):
        for q in queries:
            params = {
                "part": "snippet", "type": "video", "order": "viewCount",
                "publishedAfter": SINCE_ISO, "maxResults": 8, "q": q, "key": YT_KEY,
            }
            if lang == "tr":
                params.update({"relevanceLanguage": "tr", "regionCode": "TR"})
            else:
                params.update({"relevanceLanguage": "en"})
            try:
                data = http_json("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params))
            except Exception as e:
                errors.append(f"YouTube arama '{q}' ({lang}) başarısız: {e}")
                continue
            for item in data.get("items", []):
                vid = item["id"].get("videoId")
                if vid and vid not in seen:
                    seen[vid] = {"lang": lang, "query": q}
    if not seen:
        return
    ids = list(seen)
    videos = []
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        try:
            data = http_json(
                "https://www.googleapis.com/youtube/v3/videos?"
                + urllib.parse.urlencode({"part": "snippet,statistics", "id": ",".join(chunk), "key": YT_KEY})
            )
        except Exception as e:
            errors.append(f"YouTube detay çekilemedi: {e}")
            continue
        for v in data.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            # Dil tespiti: Türkçe sorguyla gelen videoyu sadece gerçekten Türkçe ise TR say
            audio = (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").lower()
            looks_tr = audio.startswith("tr") or bool(TR_CHARS.search(sn.get("title", "") + sn.get("description", "")[:200]))
            if seen[v["id"]]["lang"] == "tr" and not looks_tr:
                continue  # Türkçe aramada gelen ama Türkçe olmayan videoyu at
            if seen[v["id"]]["lang"] == "en" and audio and not audio.startswith("en") and not audio.startswith("tr"):
                continue  # İngilizce aramada gelen Tayca vb. videoları at
            videos.append({
                "id": v["id"],
                "url": f"https://www.youtube.com/watch?v={v['id']}",
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "published": sn.get("publishedAt", ""),
                "views": int(st.get("viewCount", 0)),
                "lang": seen[v["id"]]["lang"],
                "query": seen[v["id"]]["query"],
                "description": clean(sn.get("description", ""), 350),
            })
    videos.sort(key=lambda x: x["views"], reverse=True)
    top = [v for v in videos if v["lang"] == "tr"][:10] + [v for v in videos if v["lang"] == "en"][:15]
    for v in top[:8]:  # sadece en üst 8 video için transkript dene
        v["transcript"] = transcript_for(v["id"])
    result["youtube"] = top


# ---------------- Reddit ----------------
ATOM = {"a": "http://www.w3.org/2005/Atom"}


def collect_reddit():
    ok = 0
    for sub in SUBREDDITS:
        url = f"https://www.reddit.com/r/{sub}/top/.rss?t=day&limit=10"
        try:
            root = ET.fromstring(http_get_retry(url))
        except Exception as e:
            errors.append(f"Reddit r/{sub} çekilemedi: {e}")
            time.sleep(6)
            continue
        ok += 1
        time.sleep(6)  # Reddit'in hız sınırına takılmamak için istekler arası bekleme
        for entry in root.findall("a:entry", ATOM)[:8]:
            link = entry.find("a:link", ATOM)
            content = entry.findtext("a:content", default="", namespaces=ATOM)
            text = re.sub(r"<[^>]+>", " ", content)
            result["reddit"].append({
                "subreddit": sub,
                "title": clean(entry.findtext("a:title", default="", namespaces=ATOM), 200),
                "url": link.get("href") if link is not None else "",
                "updated": entry.findtext("a:updated", default="", namespaces=ATOM),
                "summary": clean(text, 250),
            })
    if ok == 0:
        errors.append("Reddit: hiçbir subreddit çekilemedi (Reddit bulut IP'sini engelliyor olabilir).")


# ---------------- GitHub ----------------
def collect_github():
    headers = {"Accept": "application/vnd.github+json"}
    if GH_TOKEN:
        headers["Authorization"] = f"Bearer {GH_TOKEN}"
    seen = set()
    for label, q in GH_QUERIES:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": 8}
        )
        try:
            data = http_json(url, headers)
        except Exception as e:
            errors.append(f"GitHub '{label}' aranamadı: {e}")
            continue
        for r in data.get("items", []):
            if r["full_name"] in seen:
                continue
            seen.add(r["full_name"])
            result["github"].append({
                "category": label,
                "name": r["full_name"],
                "url": r["html_url"],
                "stars": r["stargazers_count"],
                "created": r["created_at"],
                "description": clean(r.get("description") or "", 220),
                "language": r.get("language") or "",
            })


# ---------------- Hacker News ----------------
def collect_hn():
    seen = set()
    for q in ["Claude", "MCP", "OpenAI", "AI agent", "Show HN AI"]:
        url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({
            "query": q, "tags": "story", "numericFilters": f"created_at_i>{int(SINCE.timestamp())},points>15",
            "hitsPerPage": 8,
        })
        try:
            data = http_json(url)
        except Exception as e:
            errors.append(f"Hacker News '{q}' çekilemedi: {e}")
            continue
        for h in data.get("hits", []):
            if h["objectID"] in seen:
                continue
            if not AI_RELEVANT.search(h.get("title", "")):
                continue  # AI ile ilgisiz başlıkları ele
            seen.add(h["objectID"])
            result["hackernews"].append({
                "title": h.get("title", ""),
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "discussion": f"https://news.ycombinator.com/item?id={h['objectID']}",
                "points": h.get("points", 0),
                "comments": h.get("num_comments", 0),
            })
    result["hackernews"].sort(key=lambda x: x["points"], reverse=True)
    result["hackernews"] = result["hackernews"][:15]


# ---------------- Çıktı ----------------
def write_outputs():
    os.makedirs("data", exist_ok=True)
    with open("data/latest.json", "w", encoding="utf-8") as f:
        json.dump({**result, "errors": errors}, f, ensure_ascii=False, indent=2)

    L = [f"# Ham veri – {NOW.strftime('%Y-%m-%d %H:%M')} UTC", "",
         "Son 48 saat. Otomatik toplandı; yorum içermez.", ""]
    if errors:
        L += ["## Toplama hataları (bu kaynaklar eksik olabilir)"] + [f"- {e}" for e in errors] + [""]

    L.append("## YouTube (izlenmeye göre)")
    for v in result["youtube"]:
        L.append(f"- [{v['lang'].upper()}] [{v['title']}]({v['url']}) – {v['channel']} – {v['views']:,} izlenme – {v['published'][:10]}")
        if v["description"]:
            L.append(f"  - Açıklama: {v['description']}")
        if v.get("transcript"):
            L.append(f"  - Transkript (kısaltılmış): {v['transcript']}")
    L.append("")

    L.append("## Reddit (günün en çok oylananları)")
    for r in result["reddit"]:
        L.append(f"- r/{r['subreddit']}: [{r['title']}]({r['url']})")
        if r["summary"]:
            L.append(f"  - {r['summary']}")
    L.append("")

    L.append("## GitHub (son 7 günde açılan, yıldıza göre)")
    for g in result["github"]:
        L.append(f"- [{g['category']}] [{g['name']}]({g['url']}) – {g['stars']} yıldız – {g['language']} – {g['description']}")
    L.append("")

    L.append("## Hacker News (son 48 saat, puana göre)")
    for h in result["hackernews"]:
        L.append(f"- [{h['title']}]({h['url']}) – {h['points']} puan, {h['comments']} yorum – [tartışma]({h['discussion']})")
    L.append("")

    with open("data/latest.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    for fn in (collect_youtube, collect_reddit, collect_github, collect_hn):
        try:
            fn()
        except Exception as e:  # hiçbir bölüm tüm çalışmayı düşürmesin
            errors.append(f"{fn.__name__} beklenmedik hata: {e}")
    write_outputs()
    print(f"Tamam. YouTube={len(result['youtube'])} Reddit={len(result['reddit'])} "
          f"GitHub={len(result['github'])} HN={len(result['hackernews'])} Hata={len(errors)}")
