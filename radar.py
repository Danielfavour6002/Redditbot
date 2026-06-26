import os
import time
import threading
import re
import requests
from openai import OpenAI
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# Client & API Token Provisioning
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Track subreddits individually to keep payload requests lightweight
SUBREDDITS = [
    "GymMotivation", "Fitness30Plus", "HomeGym", 
    "WeightLossAdvice", "xxfitness", "bodyweightfitness", 
    "nutrition", "gains", "strengthtraining"
]

KEYWORDS = [
    "accountability", "routine tracking", "need a coach", 
    "form check", "staying consistent", "workout plan", "home workout"
]

seen_post_links = set()

# --- LIGHTWEIGHT WEB FRAMEWORK BINDING FOR RENDER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "AI Fitness Radar Proxy Engine is operational.", 200

def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
# ----------------------------------------------------------------

def generate_ai_coach_comment(post_title, post_body):
    system_prompt = (
        "You are an elite, empathetic personal fitness coach specializing in real-time "
        "interactive training, form correction, and habit building. Draft a professional, "
        "supportive Reddit comment addressing the user's explicit problem. Provide high-value, "
        "actionable tips instantly. Keep it conversational, engaging, and structured with clean bullet points. "
        "Do not pitch an app or include placeholders. Max 2-3 concise paragraphs."
    )
    user_content = f"Post Title: {post_title}\n\nPost Content: {post_body}"
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.7,
            timeout=15.0  
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[-] OpenAI Processing Failure: {e}", flush=True)
        return None

def send_telegram_alert(subreddit, title, url, ai_draft):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    message_text = (
        f"🚨 *New Match in r/{subreddit}*\n"
        f"📌 *Title:* {title}\n\n"
        f"🔗 *Post Link:* {url}\n\n"
        f"🤖 *Suggested AI Draft:* \n"
        f"```\n{ai_draft}\n```"
    )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(telegram_url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"[+] Alert successfully pushed to Telegram for: {title[:20]}...", flush=True)
        else:
            print(f"[-] Telegram Gateway Error: {res.status_code}", flush=True)
    except Exception as e:
        print(f"[-] Telegram Connection Timeout: {e}", flush=True)

def clean_html_tags(raw_html_string):
    if not raw_html_string:
        return ""
    clean_text = re.sub(r'<[^>]*>', '', raw_html_string)
    return clean_text.strip()

def poll_reddit_via_proxy():
    global seen_post_links
    print("[^] Background Proxy polling loop initiated...", flush=True)
    
    while True:
        for sub in SUBREDDITS:
            reddit_rss = f"https://www.reddit.com/r/{sub}/new/.rss"
            # Proxy parser service URL
            proxy_url = f"https://api.rss2json.com/v1/api.json?rss_url={reddit_rss}"
            
            try:
                response = requests.get(proxy_url, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    items = data.get("items", [])
                    
                    for item in items:
                        link = item.get("link", "")
                        if link in seen_post_links:
                            continue
                            
                        title = item.get("title", "")
                        description = item.get("description", "")
                        body_text = clean_html_tags(description)
                        
                        content_pool = f"{title} {body_text}".lower()
                        print(f"[Scanning] r/{sub} -> {title[:40]}...", flush=True)
                        
                        if any(keyword in content_pool for keyword in KEYWORDS):
                            print(f"[*] Match found via Proxy! Generating draft...", flush=True)
                            ai_draft = generate_ai_coach_comment(title, body_text)
                            if ai_draft:
                                send_telegram_alert(sub, title, link, ai_draft)
                        
                        seen_post_links.add(link)
                else:
                    print(f"[-] Proxy returned status code {response.status_code} for r/{sub}", flush=True)
            except Exception as e:
                print(f"[-] Proxy network exception for r/{sub}: {e}", flush=True)
            
            # 5-second break between subreddits to be a good internet citizen
            time.sleep(5)
            
        print("[~] Complete lap processed. Main loop sleeping for 90 seconds...", flush=True)
        time.sleep(90)

if __name__ == "__main__":
    # Warm up cache so old posts aren't triggered on launch
    print("[*] Cold-start cache warming via proxy...", flush=True)
    for sub in SUBREDDITS:
        try:
            res = requests.get(f"https://api.rss2json.com/v1/api.json?rss_url=https://www.reddit.com/r/{sub}/new/.rss", timeout=10)
            if res.status_code == 200:
                for item in res.json().get("items", []):
                    seen_post_links.add(item.get("link"))
        except Exception:
            pass
    print(f"[+] Cache warmed. Skipped {len(seen_post_links)} baseline posts.", flush=True)

    # Launch Flask for Render's web bind interface
    threading.Thread(target=run_flask_server, daemon=True).start()
    
    # Enter core tracker loop
    poll_reddit_via_proxy()