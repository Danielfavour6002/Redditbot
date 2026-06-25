import os
import time
import threading
import requests
import feedparser
from openai import OpenAI
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# Client & API Setup
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Clean, descriptive Bot-style User-Agent as required by modern web scrapers
CUSTOM_USER_AGENT = "FitnessCoachRadarBot/1.0 (Contact: local-dev-env)"

# Config targets
# Group your subreddits into massive "combo" strings (Max 5 or 6 per string)
SUBREDDIT_GROUPS = [
    "GymMotivation+Fitness30Plus+HomeGym+WeightLossAdvice+xxfitness",
    "gains+leangains+bodyweightfitness+nutrition+strengthtraining"
]
KEYWORDS = [
    "accountability", "routine tracking", "need a coach", 
    "form check", "staying consistent", "workout plan", "home workout"
]

seen_post_links = set()

# Flask Workaround for Render Free Tier Web Binding
app = Flask(__name__)

@app.route('/')
def home():
    return "AI Fitness Radar RSS Service is online.", 200

def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

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
            temperature=0.7
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
            print(f"[+] Alert sent to Telegram for: {title[:20]}...", flush=True)
        else:
            print(f"[-] Telegram Gateway Error: {res.status_code}", flush=True)
    except Exception as e:
        print(f"[-] Telegram Connection Timeout: {e}", flush=True)

def poll_reddit_rss_feed():
    global seen_post_links
    print("[^] Background RSS polling loop initiated...", flush=True)
    
    while True:
        for combo in SUBREDDIT_GROUPS:
            # This pulls 5 subreddits at the exact same time in ONE request!
            url = f"https://www.reddit.com/r/{combo}/new/.rss"
            try:
                feed = feedparser.parse(url, agent=CUSTOM_USER_AGENT)
                # Use feedparser to pull and parse the stream natively
                
                # Check if we were blocked or got an empty response
                if feed.bozo and not feed.entries:
                    print(f"[-] Unable to poll r/{combo} via RSS. Blocked or broken feed.", flush=True)
                    continue
                
                for entry in feed.entries:
                    link = entry.get("link", "")
                    
                    if link in seen_post_links:
                        continue
                    
                    title = entry.get("title", "")
                    # RSS summaries contain HTML; strip or grab text if available
                    body = entry.get("summary", "")
                    
                    content_pool = (title + " " + body).lower()
                    if any(keyword in content_pool for keyword in KEYWORDS):
                        print(f"[*] RSS Match detected in r/{combo}: '{title[:25]}...'", flush=True)
                        
                        ai_draft = generate_ai_coach_comment(title, body)
                        if ai_draft:
                            send_telegram_alert(combo, title, link, ai_draft)
                    
                    seen_post_links.add(link)
            except Exception as e:
                print(f"[-] Error parsing RSS payload for r/{combo}: {e}", flush=True)
            
            time.sleep(2)
        
        print("[~] Run complete. Sleeping for 60 seconds...", flush=True)
        time.sleep(60)

if __name__ == "__main__":
    print("[*] Performing cold-start RSS cache warming...", flush=True)
    for target_sub in SUBREDDIT_GROUPS:
        try:
            f = feedparser.parse(f"https://www.reddit.com/r/{target_sub}/new/.rss", agent=CUSTOM_USER_AGENT)
            for entry in f.entries:
                seen_post_links.add(entry.get("link"))
        except Exception:
            pass
    print(f"[+] Cache warmed. Skipped {len(seen_post_links)} historical posts.", flush=True)

    # Spawn Web API Thread for Render's requirements
    threading.Thread(target=run_flask_server, daemon=True).start()
    # TEMP TEST LINE - Delete this after your phone pings!

    # Launch Core Reddit RSS Poller Loop
    poll_reddit_rss_feed()