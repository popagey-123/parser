import json
import threading
import time
import os
import sys
from flask import Flask, render_template, request, jsonify, send_file

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ngrok для публичного доступа
NGROK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ngrok.exe")

app = Flask(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

task_status = {
    "running": False,
    "progress": "",
    "logs": [],
    "result": None,
    "error": None,
}


def run_task(mode, params):
    global task_status
    task_status["running"] = True
    task_status["progress"] = "Запуск..."
    task_status["logs"] = []
    task_status["error"] = None
    task_status["result"] = None

    log = []

    def add_log(msg):
        task_status["logs"].append(msg)
        task_status["progress"] = msg

    try:
        if mode == "social":
            from multi_platform_scraper import (
                scrape_instagram, scrape_facebook, scrape_vk,
                scrape_tiktok, scrape_telegram, generate_analysis
            )
            results = []
            platform = params.get("platform", "instagram")
            username = params.get("username", "")

            add_log(f"Паршу {platform}: @{username}...")

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
                raise ValueError(f"Неизвестная платформа: {platform}")

            results.append(result)

            json_path = os.path.join(OUTPUT_DIR, f"{platform}_{username}_data.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            analysis = generate_analysis(results)
            md_path = os.path.join(OUTPUT_DIR, f"{platform}_{username}_analysis.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(analysis)

            task_status["result"] = {
                "type": "social",
                "platform": platform,
                "username": username,
                "posts_count": len(result.get("posts", [])),
                "total_likes": result.get("statistics", {}).get("total_likes", 0),
                "json_path": json_path,
                "md_path": md_path,
            }
            add_log(f"Готово! Постов: {len(result.get('posts', []))}, Лайков: {result.get('statistics', {}).get('total_likes', 0)}")

        elif mode == "article":
            from multi_platform_scraper import scrape_article, generate_articles_report
            urls = [u.strip() for u in params.get("urls", "").split("\n") if u.strip()]

            if not urls:
                raise ValueError("Укажите хотя бы один URL")

            articles = []
            for i, url in enumerate(urls):
                add_log(f"[{i+1}/{len(urls)}] Паршу: {url}")
                result = scrape_article(url)
                if result:
                    articles.append(result)
                time.sleep(1)

            if articles:
                articles_json = os.path.join(OUTPUT_DIR, "articles_batch.json")
                with open(articles_json, "w", encoding="utf-8") as f:
                    json.dump(articles, f, ensure_ascii=False, indent=2)

                report = generate_articles_report(articles)
                report_path = os.path.join(OUTPUT_DIR, "articles_batch_report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)

                task_status["result"] = {
                    "type": "article",
                    "count": len(articles),
                    "total_text": sum(a.get("text_length", 0) for a in articles),
                    "json_path": articles_json,
                    "md_path": report_path,
                }
                add_log(f"Готово! Спаршено: {len(articles)}/{len(urls)} статей")
            else:
                raise ValueError("Не удалось спарсить ни одной статьи")

        elif mode == "dzen":
            from multi_platform_scraper import scrape_articles_from_dzen, generate_articles_report
            channel = params.get("channel", "")
            add_log(f"Паршу Dzen канал: @{channel}...")
            articles = scrape_articles_from_dzen(channel)

            if articles:
                articles_json = os.path.join(OUTPUT_DIR, f"dzen_{channel}.json")
                with open(articles_json, "w", encoding="utf-8") as f:
                    json.dump(articles, f, ensure_ascii=False, indent=2)
                report = generate_articles_report(articles)
                report_path = os.path.join(OUTPUT_DIR, f"dzen_{channel}_report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)
                task_status["result"] = {
                    "type": "dzen",
                    "channel": channel,
                    "count": len(articles),
                    "json_path": articles_json,
                    "md_path": report_path,
                }
                add_log(f"Готово! Найдено: {len(articles)} статей")
            else:
                raise ValueError("Статьи не найдены")

        elif mode == "vk_articles":
            from multi_platform_scraper import scrape_articles_from_vk, generate_articles_report
            username = params.get("username", "")
            add_log(f"Ищу статьи в VK: @{username}...")
            articles = scrape_articles_from_vk(username)

            if articles:
                articles_json = os.path.join(OUTPUT_DIR, f"vk_{username}_articles.json")
                with open(articles_json, "w", encoding="utf-8") as f:
                    json.dump(articles, f, ensure_ascii=False, indent=2)
                report = generate_articles_report(articles)
                report_path = os.path.join(OUTPUT_DIR, f"vk_{username}_articles_report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report)
                task_status["result"] = {
                    "type": "vk_articles",
                    "username": username,
                    "count": len(articles),
                    "json_path": articles_json,
                    "md_path": report_path,
                }
                add_log(f"Готово! Найдено: {len(articles)} статей")
            else:
                raise ValueError("Статьи не найдены")

    except Exception as e:
        task_status["error"] = str(e)
        add_log(f"Ошибка: {e}")
    finally:
        task_status["running"] = False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(task_status)


@app.route("/api/run", methods=["POST"])
def api_run():
    if task_status["running"]:
        return jsonify({"error": "Задача уже выполняется"}), 400

    data = request.json
    mode = data.get("mode", "social")
    params = data.get("params", {})

    thread = threading.Thread(target=run_task, args=(mode, params))
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/files")
def api_files():
    files = []
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            fpath = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(fpath):
                files.append({
                    "name": f,
                    "size": os.path.getsize(fpath),
                    "modified": time.ctime(os.path.getmtime(fpath)),
                })
    return jsonify(files)


@app.route("/download/<filename>")
def download_file(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        return send_file(filepath, as_attachment=True)
    return "Файл не найден", 404


@app.route("/api/file-content/<filename>")
def api_file_content(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(filepath) and os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        ext = filename.rsplit(".", 1)[-1].lower()
        return jsonify({"content": content, "type": ext})
    return "Файл не найден", 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Запуск сервера: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)