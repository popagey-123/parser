import json
import re
import sys
import time
import os
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False
    print("[!] trafilatura не установлен. Для лучшего парсинга статей: pip install trafilatura lxml_html_clean")

sys.stdout.reconfigure(encoding='utf-8')

OUTPUT_DIR = r"D:\рф\venv\rag_chunks_annotated\хуесосы\газпром\output"
ARTICLES_DIR = os.path.join(OUTPUT_DIR, "articles")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ARTICLES_DIR, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """Убирает недопустимые символы из имени файла."""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name[:120].strip()


def scrape_instagram(username: str) -> dict:
    """Парсит Instagram профиль: посты, лайки, комментарии, тексты."""
    print(f"[Instagram] Паршу @{username}...")
    result = {
        "platform": "instagram",
        "username": username,
        "profile": {},
        "posts": [],
        "statistics": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # 1. Парсим профиль
        page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Извлекаем данные профиля из HTML
        html = page.content()

        # Парсим имя и кол-во подписчиков
        name_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        followers_match = re.search(r'(\d[\d\s]*)\s*подписчик', html)

        result["profile"]["full_name"] = name_match.group(1) if name_match else username
        result["profile"]["followers"] = followers_match.group(1).strip() if followers_match else "N/A"

        # Извлекаем ID постов из HTML
        post_ids = re.findall(r'href="/p/([A-Za-z0-9_-]+)/"', html)
        reel_ids = re.findall(r'href="/reel/([A-Za-z0-9_-]+)/"', html)
        all_ids = [(pid, "post") for pid in post_ids] + [(rid, "reel") for rid in reel_ids]

        print(f"[Instagram] Найдено {len(all_ids)} публикаций")

        # 2. Парсим каждый пост
        for post_id, post_type in all_ids:
            post_url = f"https://www.instagram.com/{post_type}/{post_id}/"
            try:
                page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                post_html = page.content()

                # OG данные
                og_title = re.search(r'<meta property="og:title" content="([^"]*)"', post_html)
                og_desc = re.search(r'<meta property="og:description" content="([^"]*)"', post_html)
                og_date = re.search(r'<meta property="og:article:published_time" content="([^"]*)"', post_html)
                og_image = re.search(r'<meta property="og:image" content="([^"]*)"', post_html)

                post_data = {
                    "id": post_id,
                    "url": post_url,
                    "type": post_type,
                    "date": og_date.group(1) if og_date else "",
                    "og_title": og_title.group(1) if og_title else "",
                    "og_description": og_desc.group(1) if og_desc else "",
                    "og_image": og_image.group(1) if og_image else "",
                    "likes": "",
                    "comments_count": "",
                    "caption": "",
                    "comments": []
                }

                # Парсим лайки и комментарии из OG
                if og_desc:
                    m = re.match(r"(\d+) likes, (\d+) comments", og_desc.group(1))
                    if m:
                        post_data["likes"] = m.group(1)
                        post_data["comments_count"] = m.group(2)

                # Парсим текст из OG title
                if og_title:
                    tm = re.search(r'в Instagram : "([^"]+)"', og_title.group(1))
                    if tm:
                        post_data["caption"] = tm.group(1)
                    else:
                        dm = re.search(r': "([^"]+)"', og_desc.group(1) if og_desc else "")
                        if dm:
                            post_data["caption"] = dm.group(1)

                # Парсим лайки из body
                if not post_data["likes"]:
                    bm = re.search(r'Начните переписку\.\n(\d+)\n\d+\s+(?:январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)', post_html)
                    if bm:
                        post_data["likes"] = bm.group(1)
                    else:
                        bm2 = re.search(r'Ответить\n(\d+)\n\d+\s+(?:январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)', post_html)
                        if bm2:
                            post_data["likes"] = bm2.group(1)

                # Парсим комментарии
                comment_pattern = re.compile(
                    r'(\w+)\s*\n\s*(\d+\s+нед\.)\s*\n(.+?)\s*\nНравится\s*\nОтветить',
                    re.DOTALL
                )
                for cm in comment_pattern.finditer(post_html):
                    if cm.group(1) != username:
                        post_data["comments"].append({
                            "author": cm.group(1),
                            "time": cm.group(2),
                            "text": cm.group(3).strip()
                        })

                result["posts"].append(post_data)
                print(f"  [+] {post_id} | {post_data['date'][:10]} | Лайки: {post_data['likes']} | Текст: {post_data['caption'][:50]}")

            except Exception as e:
                print(f"  [-] {post_id}: {e}")

        browser.close()

    # Статистика
    total_likes = sum(int(p["likes"]) for p in result["posts"] if p["likes"])
    total_comments = sum(int(p["comments_count"]) for p in result["posts"] if p["comments_count"])
    all_commenters = set()
    for p in result["posts"]:
        for c in p["comments"]:
            all_commenters.add(c["author"])

    result["statistics"] = {
        "total_posts": len(result["posts"]),
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_likes": round(total_likes / len(result["posts"]), 1) if result["posts"] else 0,
        "avg_comments": round(total_comments / len(result["posts"]), 1) if result["posts"] else 0,
        "unique_commenters": len(all_commenters),
        "commenters": sorted(list(all_commenters))
    }

    return result


def scrape_facebook(username: str) -> dict:
    """Парсит Facebook профиль: посты, лайки, комментарии."""
    print(f"[Facebook] Паршу @{username}...")
    result = {
        "platform": "facebook",
        "username": username,
        "profile": {},
        "posts": [],
        "statistics": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Пробуем разные форматы URL
        urls_to_try = [
            f"https://www.facebook.com/{username}",
            f"https://facebook.com/{username}",
        ]

        profile_url = None
        for url in urls_to_try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                html = page.content()
                if "page not found" not in html.lower() and "not available" not in html.lower():
                    profile_url = url
                    break
            except:
                continue

        if not profile_url:
            print("[Facebook] Профиль не найден или недоступен")
            return result

        # Парсим профиль
        html = page.content()
        name_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', html)

        result["profile"]["full_name"] = name_match.group(1) if name_match else username
        result["profile"]["description"] = desc_match.group(1) if desc_match else ""

        # Скроллим для загрузки постов
        prev_height = 0
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            time.sleep(2)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            prev_height = new_height

        # Парсим посты из HTML
        post_htmls = re.findall(
            r'<div[^>]*role="article"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*role="article"',
            html, re.DOTALL
        )

        # Альтернативный поиск постов
        if not post_htmls:
            post_htmls = re.findall(
                r'<div[^>]*class="[^"]*UFIMessage[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )

        print(f"[Facebook] Найдено {len(post_htmls)} постов")

        for i, post_html in enumerate(post_htmls[:20]):  # Лимит 20 постов
            try:
                # Извлекаем текст поста
                text_match = re.search(r'<span[^>]*>(.*?)</span>', post_html, re.DOTALL)
                post_text = text_match.group(1).strip() if text_match else ""

                # Извлекаем дату
                date_match = re.search(r'<span[^>]*>(\d+\s+\w+\s+\d+)</span>', post_html)
                post_date = date_match.group(1) if date_match else ""

                # Извлекаем лайки
                likes_match = re.search(r'(\d[\d,]*)\s*(?:likes|реакций|нравится)', post_html, re.IGNORECASE)
                post_likes = likes_match.group(1) if likes_match else ""

                # Извлекаем комментарии
                comments_match = re.search(r'(\d[\d,]*)\s*(?:comments|комментариев)', post_html, re.IGNORECASE)
                post_comments = comments_match.group(1) if comments_match else ""

                post_data = {
                    "id": str(i),
                    "url": profile_url,
                    "type": "post",
                    "date": post_date,
                    "caption": post_text[:200],
                    "likes": post_likes,
                    "comments_count": post_comments,
                    "comments": [],
                    "og_title": "",
                    "og_description": "",
                    "og_image": ""
                }

                result["posts"].append(post_data)
                print(f"  [+] Пост {i} | {post_date} | Лайки: {post_likes} | Текст: {post_text[:50]}")

            except Exception as e:
                print(f"  [-] Пост {i}: {e}")

        browser.close()

    # Статистика
    total_likes = sum(int(p["likes"].replace(",", "")) for p in result["posts"] if p["likes"])
    total_comments = sum(int(p["comments_count"].replace(",", "")) for p in result["posts"] if p["comments_count"])

    result["statistics"] = {
        "total_posts": len(result["posts"]),
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_likes": round(total_likes / len(result["posts"]), 1) if result["posts"] else 0,
        "avg_comments": round(total_comments / len(result["posts"]), 1) if result["posts"] else 0,
        "unique_commenters": 0,
        "commenters": []
    }

    return result


def scrape_vk(username: str) -> dict:
    """Парсит VK профиль: посты, лайки, комментарии."""
    print(f"[VK] Паршу @{username}...")
    result = {
        "platform": "vk",
        "username": username,
        "profile": {},
        "posts": [],
        "statistics": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Пробуем разные форматы URL
        urls_to_try = [
            f"https://vk.com/{username}",
            f"https://vk.com/id{username}" if username.isdigit() else None,
        ]

        profile_url = None
        for url in urls_to_try:
            if not url:
                continue
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                html = page.content()
                if "page_not_found" not in html and "Страница не найдена" not in html:
                    profile_url = url
                    break
            except:
                continue

        if not profile_url:
            print("[VK] Профиль не найден или недоступен")
            return result

        # Парсим профиль
        html = page.content()
        name_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', html)

        result["profile"]["full_name"] = name_match.group(1) if name_match else username
        result["profile"]["description"] = desc_match.group(1) if desc_match else ""

        # Скроллим для загрузки постов
        prev_height = 0
        for _ in range(5):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            time.sleep(2)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            prev_height = new_height

        # Парсим посты
        html = page.content()

        # Ищем посты по паттерну wall_post
        posts = re.findall(
            r'<div[^>]*class="[^"]*wall_post[^"]*"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*class="[^"]*wall_post',
            html, re.DOTALL
        )

        # Альтернативный поиск
        if not posts:
            posts = re.findall(
                r'<div[^>]*id="wall_post_\d+"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*id="wall_post_',
                html, re.DOTALL
            )

        print(f"[VK] Найдено {len(posts)} постов")

        for i, post_html in enumerate(posts[:20]):
            try:
                # Извлекаем текст
                text_match = re.search(r'<div[^>]*class="[^"]*wall_post_text[^"]*"[^>]*>(.*?)</div>', post_html, re.DOTALL)
                post_text = text_match.group(1).strip() if text_match else ""

                # Извлекаем дату
                date_match = re.search(r'<span[^>]*>(\d+\s+\w+\s+\d+)</span>', post_html)
                post_date = date_match.group(1) if date_match else ""

                # Извлекаем лайки
                likes_match = re.search(r'(\d[\d,]*)\s*(?:likes|нравится|лайков)', post_html, re.IGNORECASE)
                post_likes = likes_match.group(1) if likes_match else ""

                # Извлекаем комментарии
                comments_match = re.search(r'(\d[\d,]*)\s*(?:comments|комментариев)', post_html, re.IGNORECASE)
                post_comments = comments_match.group(1) if comments_match else ""

                post_data = {
                    "id": str(i),
                    "url": profile_url,
                    "type": "post",
                    "date": post_date,
                    "caption": post_text[:200],
                    "likes": post_likes,
                    "comments_count": post_comments,
                    "comments": [],
                    "og_title": "",
                    "og_description": "",
                    "og_image": ""
                }

                result["posts"].append(post_data)
                print(f"  [+] Пост {i} | {post_date} | Лайки: {post_likes} | Текст: {post_text[:50]}")

            except Exception as e:
                print(f"  [-] Пост {i}: {e}")

        browser.close()

    # Статистика
    total_likes = sum(int(p["likes"].replace(",", "")) for p in result["posts"] if p["likes"])
    total_comments = sum(int(p["comments_count"].replace(",", "")) for p in result["posts"] if p["comments_count"])

    result["statistics"] = {
        "total_posts": len(result["posts"]),
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_likes": round(total_likes / len(result["posts"]), 1) if result["posts"] else 0,
        "avg_comments": round(total_comments / len(result["posts"]), 1) if result["posts"] else 0,
        "unique_commenters": 0,
        "commenters": []
    }

    return result


def scrape_tiktok(username: str) -> dict:
    """Парсит TikTok профиль: видео, лайки, комментарии."""
    print(f"[TikTok] Паршу @{username}...")
    result = {
        "platform": "tiktok",
        "username": username,
        "profile": {},
        "posts": [],
        "statistics": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(f"https://www.tiktok.com/@{username}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            html = page.content()

            # Парсим профиль
            name_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
            desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', html)

            result["profile"]["full_name"] = name_match.group(1) if name_match else username
            result["profile"]["description"] = desc_match.group(1) if desc_match else ""

            # Парсим видео
            video_ids = re.findall(r'href="/@[^"]*/video/(\d+)"', html)
            print(f"[TikTok] Найдено {len(video_ids)} видео")

            for i, vid in enumerate(video_ids[:20]):
                try:
                    video_url = f"https://www.tiktok.com/@{username}/video/{vid}"
                    page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)

                    vhtml = page.content()
                    desc = re.search(r'<meta property="og:description" content="([^"]*)"', vhtml)
                    title = re.search(r'<meta property="og:title" content="([^"]*)"', vhtml)

                    post_data = {
                        "id": vid,
                        "url": video_url,
                        "type": "video",
                        "date": "",
                        "caption": (desc.group(1) if desc else "")[:200],
                        "likes": "",
                        "comments_count": "",
                        "comments": [],
                        "og_title": title.group(1) if title else "",
                        "og_description": desc.group(1) if desc else "",
                        "og_image": ""
                    }

                    result["posts"].append(post_data)
                    print(f"  [+] Видео {vid} | Текст: {post_data['caption'][:50]}")

                except Exception as e:
                    print(f"  [-] Видео {vid}: {e}")

        except Exception as e:
            print(f"[TikTok] Ошибка: {e}")

        browser.close()

    result["statistics"] = {
        "total_posts": len(result["posts"]),
        "total_likes": 0,
        "total_comments": 0,
        "avg_likes": 0,
        "avg_comments": 0,
        "unique_commenters": 0,
        "commenters": []
    }

    return result


def scrape_telegram(username: str) -> dict:
    """Парсит Telegram канал: посты, просмотры, реакции."""
    print(f"[Telegram] Паршу @{username}...")
    result = {
        "platform": "telegram",
        "username": username,
        "profile": {},
        "posts": [],
        "statistics": {}
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(f"https://t.me/{username}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            html = page.content()

            # Парсим профиль
            name_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
            desc_match = re.search(r'<meta property="og:description" content="([^"]*)"', html)

            result["profile"]["full_name"] = name_match.group(1) if name_match else username
            result["profile"]["description"] = desc_match.group(1) if desc_match else ""

            # Скроллим для загрузки постов
            prev_height = 0
            for _ in range(3):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(2)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == prev_height:
                    break
                prev_height = new_height

            html = page.content()

            # Парсим посты
            posts = re.findall(
                r'<div[^>]*class="[^"]*tgme_widget_message[^"]*"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*class="[^"]*tgme_widget_message',
                html, re.DOTALL
            )

            print(f"[Telegram] Найдено {len(posts)} постов")

            for i, post_html in enumerate(posts[:20]):
                try:
                    # Текст
                    text_match = re.search(r'<div[^>]*class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', post_html, re.DOTALL)
                    post_text = text_match.group(1).strip() if text_match else ""

                    # Дата
                    date_match = re.search(r'<time[^>]*datetime="([^"]*)"', post_html)
                    post_date = date_match.group(1) if date_match else ""

                    # Просмотры
                    views_match = re.search(r'(\d[\d,\.]*)\s*(?:views|просмотров)', post_html, re.IGNORECASE)
                    post_views = views_match.group(1) if views_match else ""

                    post_data = {
                        "id": str(i),
                        "url": f"https://t.me/{username}/{i+1}",
                        "type": "post",
                        "date": post_date,
                        "caption": post_text[:200],
                        "likes": post_views,
                        "comments_count": "",
                        "comments": [],
                        "og_title": "",
                        "og_description": "",
                        "og_image": ""
                    }

                    result["posts"].append(post_data)
                    print(f"  [+] Пост {i} | {post_date} | Просмотры: {post_views} | Текст: {post_text[:50]}")

                except Exception as e:
                    print(f"  [-] Пост {i}: {e}")

        except Exception as e:
            print(f"[Telegram] Ошибка: {e}")

        browser.close()

    result["statistics"] = {
        "total_posts": len(result["posts"]),
        "total_likes": 0,
        "total_comments": 0,
        "avg_likes": 0,
        "avg_comments": 0,
        "unique_commenters": 0,
        "commenters": []
    }

    return result


def scrape_article(url: str, favor_precision: bool = True) -> dict:
    """Парсит отдельную статью: извлекает текст, изображения, метаданные."""
    print(f"[Article] Паршу: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="ru-RU",
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            title = page.title()
            if not title or "Авторизация" in title or "Вход" in title:
                print(f"  [!] Страница авторизации: {url}")
                browser.close()
                return None

            print(f"  Заголовок: {title[:80]}")

            # Скролл для ленивой загрузки
            last_height = 0
            for _ in range(8):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.8)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            page.evaluate("window.scrollTo(0, 0)")

            html = page.content()

            # Извлекаем текст статьи
            text = None
            if HAS_TRAFILATURA:
                text = trafilatura.extract(
                    html,
                    include_comments=False,
                    include_tables=True,
                    include_links=False,
                    favor_precision=favor_precision,
                )
                if not text:
                    text = trafilatura.extract(html, favor_recall=True)

            if not text:
                # Fallback: извлекаем из <article> или <main>
                text = page.evaluate("""() => {
                    const article = document.querySelector('article, .article-content, .post-content, main, .content');
                    if (article) return article.innerText;
                    return document.body.innerText;
                }""")

            if not text:
                text = page.evaluate("() => document.body.innerText")

            print(f"  Текст: {len(text) if text else 0} символов")

            # Извлекаем изображения
            images = page.evaluate("""() => {
                const imgs = document.querySelectorAll('img');
                const result = [];
                for (const img of imgs) {
                    const src = img.src || '';
                    const alt = img.alt || '';
                    if (src && src !== 'about:blank' &&
                        !src.includes('avatar') && !src.includes('logo') &&
                        !src.includes('default') && !src.includes('icon')) {
                        result.push({src, alt});
                    }
                }
                return result;
            }""")

            # OG метаданные
            og_title = re.search(r'<meta property="og:title" content="([^"]*)"', html)
            og_desc = re.search(r'<meta property="og:description" content="([^"]*)"', html)
            og_image = re.search(r'<meta property="og:image" content="([^"]*)"', html)
            og_site = re.search(r'<meta property="og:site_name" content="([^"]*)"', html)

            # Автор и дата
            author_match = re.search(r'<meta property="article:author" content="([^"]*)"', html)
            date_match = re.search(r'<meta property="article:published_time" content="([^"]*)"', html)

            # Определяем источник
            parsed = urlparse(url)
            domain = parsed.netloc

            result = {
                "url": url,
                "domain": domain,
                "title": title,
                "og_title": og_title.group(1) if og_title else "",
                "og_description": og_desc.group(1) if og_desc else "",
                "og_image": og_image.group(1) if og_image else "",
                "og_site": og_site.group(1) if og_site else "",
                "author": author_match.group(1) if author_match else "",
                "published_date": date_match.group(1) if date_match else "",
                "text": text or "",
                "text_length": len(text) if text else 0,
                "images": images,
                "image_count": len(images),
            }

            # Сохраняем Markdown
            filename = sanitize_filename(title or "article") + ".md"
            filepath = os.path.join(ARTICLES_DIR, filename)

            lines = [f"# {title}\n", f"**URL:** {url}\n"]
            if result["author"]:
                lines.append(f"**Автор:** {result['author']}\n")
            if result["published_date"]:
                lines.append(f"**Дата:** {result['published_date']}\n")
            if result["og_site"]:
                lines.append(f"**Источник:** {result['og_site']}\n")
            lines.append("---\n")

            for img in images[:5]:
                lines.append(f"![{img['alt']}]({img['src']})\n")

            lines.append(text or "")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            print(f"  Сохранено: {filepath}")
            result["saved_path"] = filepath
            browser.close()
            return result

        except Exception as e:
            print(f"  [!] Ошибка: {e}")
            browser.close()
            return None


def scrape_articles_from_vk(username: str) -> list:
    """Находит и парсит статьи из VK профиля/сообщества."""
    print(f"[VK Articles] Ищу статьи в @{username}...")
    articles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(f"https://vk.com/{username}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Ищем ссылки на статьи VK (vk.com/@)
            article_links = page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="vk.com/@"]');
                const urls = new Set();
                for (const link of links) {
                    const href = link.href || '';
                    if (href.includes('vk.com/@')) {
                        urls.add(href);
                    }
                }
                return Array.from(urls);
            }""")

            print(f"[VK Articles] Найдено {len(article_links)} ссылок на статьи")

            for link in article_links[:20]:
                result = scrape_article(link)
                if result:
                    articles.append(result)
                time.sleep(1)

        except Exception as e:
            print(f"[VK Articles] Ошибка: {e}")

        browser.close()

    return articles


def scrape_articles_from_dzen(username: str) -> list:
    """Парсит статьи с Dzen канала."""
    print(f"[Dzen Articles] Паршу канал @{username}...")
    articles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            page.goto(f"https://dzen.ru/{username}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Скроллим для загрузки ссылок
            last_height = 0
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.5)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            # Ищем ссылки на статьи
            article_links = page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="/a/"]');
                const urls = new Set();
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    if (href.startsWith('/a/')) {
                        urls.add('https://dzen.ru' + href);
                    }
                }
                return Array.from(urls);
            }""")

            print(f"[Dzen Articles] Найдено {len(article_links)} ссылок на статьи")

            for link in article_links[:20]:
                result = scrape_article(link)
                if result:
                    articles.append(result)
                time.sleep(1)

        except Exception as e:
            print(f"[Dzen Articles] Ошибка: {e}")

        browser.close()

    return articles


def scrape_articles_batch(urls: list) -> list:
    """Парсит список URL статей."""
    print(f"[Articles] Паршу {len(urls)} статей...")
    articles = []

    for i, url in enumerate(urls):
        print(f"\n[{i+1}/{len(urls)}] ", end="")
        result = scrape_article(url)
        if result:
            articles.append(result)
        time.sleep(1)

    print(f"\n[Articles] Всего спаршено: {len(articles)}/{len(urls)}")
    return articles


def generate_articles_report(articles: list) -> str:
    """Генерирует отчёт по статьям."""
    if not articles:
        return "# Статьи\n\nСтатьи не найдены.\n"

    report = []
    report.append("# Спаршенные статьи")
    report.append("")
    report.append(f"**Всего статей:** {len(articles)}")
    report.append(f"**Всего текста:** {sum(a.get('text_length', 0) for a in articles):,} символов")
    report.append("")

    # Группировка по источникам
    by_domain = {}
    for a in articles:
        domain = a.get("domain", "unknown")
        if domain not in by_domain:
            by_domain[domain] = []
        by_domain[domain].append(a)

    report.append("## По источникам")
    report.append("")
    for domain, domain_articles in by_domain.items():
        report.append(f"### {domain} ({len(domain_articles)} статей)")
        report.append("")
        report.append("| № | Заголовок | Автор | Дата | Размер |")
        report.append("|---|-----------|-------|------|--------|")
        for i, a in enumerate(domain_articles, 1):
            title = (a.get("title", "") or "")[:60]
            author = a.get("author", "-") or "-"
            date = a.get("published_date", "")[:10] or "-"
            size = f"{a.get('text_length', 0):,}"
            report.append(f"| {i} | {title} | {author} | {date} | {size} |")
        report.append("")

    report.append("---")
    report.append("*Отчёт сгенерирован автоматически*")
    return "\n".join(report)
    """Генерирует сводный анализ по всем платформам."""
    report = []
    report.append("# Сводный анализ социальных сетей")
    report.append("")

    for res in all_results:
        platform = res["platform"].upper()
        username = res["username"]
        profile = res["profile"]
        stats = res["statistics"]

        report.append(f"## {platform}: @{username}")
        report.append("")
        report.append(f"- **Имя:** {profile.get('full_name', 'N/A')}")
        report.append(f"- **Описание:** {profile.get('description', 'N/A')[:100]}")
        report.append(f"- **Подписчики:** {profile.get('followers', 'N/A')}")
        report.append(f"- **Постов:** {stats.get('total_posts', 0)}")
        report.append(f"- **Лайков:** {stats.get('total_likes', 0)}")
        report.append(f"- **Комментариев:** {stats.get('total_comments', 0)}")
        report.append(f"- **Ср. лайков:** {stats.get('avg_likes', 0)}")
        report.append(f"- **Комментаторов:** {stats.get('unique_commenters', 0)}")
        report.append("")

        if res["posts"]:
            report.append("### Хронология публикаций")
            report.append("")
            report.append("| № | Дата | Тип | Лайки | Текст |")
            report.append("|---|------|-----|-------|-------|")
            for i, post in enumerate(res["posts"], 1):
                d = post.get("date", "")[:10]
                t = post.get("type", "")
                l = post.get("likes", "-") or "-"
                c = (post.get("caption", "") or "")[:60].replace("\n", " ")
                if not c:
                    c = "-"
                report.append(f"| {i} | {d} | {t} | {l} | {c} |")
            report.append("")

    report.append("---")
    report.append("*Отчёт сгенерирован автоматически*")
    return "\n".join(report)


def main():
    """Основная функция: парсит соцсети и статьи."""
    # Конфигурация: платформы и юзернеймы
    targets = {
        "instagram": ["danila_pgy"],
        "facebook": ["danila.pgy", "danila.permogorskiy"],
        "vk": ["danila_pgy", "danila.permogorskiy"],
        "tiktok": ["danila_pgy"],
        "telegram": ["danila_pgy"],
    }

    # Конфигурация статей
    article_sources = {
        # Прямые URL статей для парсинга
        "urls": [
            # "https://dzen.ru/a/example",
            # "https://vk.com/wall-123456_789",
            # "https://habr.com/ru/articles/123456/",
        ],
        # VK сообщества/профили для поиска статей
        "vk_users": [
            # "id123456",
        ],
        # Dzen каналы для поиска статей
        "dzen_channels": [
            # "id_example",
        ],
    }

    all_results = []
    all_articles = []

    # 1. Парсим соцсети
    print("=" * 50)
    print("ПАРСИНГ СОЦСЕТЕЙ")
    print("=" * 50)

    for platform, usernames in targets.items():
        for username in usernames:
            try:
                if platform == "instagram":
                    result = scrape_instagram(username)
                elif platform == "facebook":
                    result = scrape_facebook(username)
                elif platform == "vk":
                    result = scrape_vk(username)
                elif platform == "tiktok":
                    result = scrape_tiktok(username)
                elif platform == "telegram":
                    result = scrape_telegram(username)
                else:
                    print(f"[!] Неизвестная платформа: {platform}")
                    continue

                all_results.append(result)

                json_path = os.path.join(OUTPUT_DIR, f"{platform}_{username}_data.json")
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                print(f"[{platform}] Сохранено: {json_path}")

            except Exception as e:
                print(f"[{platform}] Ошибка @{username}: {e}")

            time.sleep(2)

    # 2. Парсим статьи
    print("\n" + "=" * 50)
    print("ПАРСИНГ СТАТЕЙ")
    print("=" * 50)

    # Прямые URL
    if article_sources["urls"]:
        articles = scrape_articles_batch(article_sources["urls"])
        all_articles.extend(articles)

    # VK статьи
    for vk_user in article_sources["vk_users"]:
        articles = scrape_articles_from_vk(vk_user)
        all_articles.extend(articles)

    # Dzen статьи
    for dzen_channel in article_sources["dzen_channels"]:
        articles = scrape_articles_from_dzen(dzen_channel)
        all_articles.extend(articles)

    # Сохраняем статьи
    if all_articles:
        articles_json = os.path.join(OUTPUT_DIR, "all_articles.json")
        with open(articles_json, "w", encoding="utf-8") as f:
            json.dump(all_articles, f, ensure_ascii=False, indent=2)
        print(f"\n[+] Статьи JSON: {articles_json}")

        articles_report = generate_articles_report(all_articles)
        articles_md = os.path.join(OUTPUT_DIR, "articles_report.md")
        with open(articles_md, "w", encoding="utf-8") as f:
            f.write(articles_report)
        print(f"[+] Статьи отчёт: {articles_md}")

    # 3. Генерируем сводный отчёт
    if all_results or all_articles:
        analysis = generate_analysis(all_results)

        if all_articles:
            analysis += "\n\n" + generate_articles_report(all_articles)

        md_path = os.path.join(OUTPUT_DIR, "multi_platform_analysis.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(analysis)
        print(f"\n[+] Сводный отчёт: {md_path}")

        combined = {
            "profiles": all_results,
            "articles": all_articles,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        combined_path = os.path.join(OUTPUT_DIR, "all_platforms_combined.json")
        with open(combined_path, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2)
        print(f"[+] Объединённый JSON: {combined_path}")


if __name__ == "__main__":
    main()