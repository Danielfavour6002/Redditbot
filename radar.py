import os
import time
import threading
import re
import requests
import feedparser
from openai import OpenAI
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# Client & API Token Provisioning
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Mask script signatures with an explicit, responsible bot header pattern
CUSTOM_USER_AGENT = "FitnessCoachRadarBot/1.0 (Contact: local-dev-env)"

# DEBUG FIX: Broken into smaller sub-clusters to slide beneath Reddit's rate-limiting firewall
SUBREDDIT_GROUPS = [
    "GymMotivation+Fitness30Plus",
    "HomeGym+WeightLossAdvice",
    "xxfitness+leangains",
    "bodyweightfitness+nutrition",
    "gains+strengthtraining"
]

KEYWORDS = [
    "accountability", "routine tracking", "need a coach", 
    "form check", "staying consistent", "workout plan", "home workout"
]

seen_post_links = set()

# --- LIGHTWEIGHT WEB FRAMEWORK BINDING FOR RENDER FREE TIERS ---
app = Flask(__name__)

@app.route('/')
def home():
    return "AI Fitness Radar Engine is operational.", 200

def run_flask_server():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
# ----------------------------------------------------------------

def generate_ai_coach_comment(post_title, post_body):
    """Processes post content using OpenAI with explicit timeout handling to mitigate network drops."""
    system_prompt = (
        "You are an elite, empathetic personal fitness coach specializing in real-time "
        "interactive training, form correction, and habit building. Draft a professional, "
        "supportive Reddit comment addressing the user's explicit problem. Provide high-value, "
        "actionable tips instantly. Keep it conversational, engaging, and structured with clean bullet points. "
        "Do not pitch an app or include placeholders. Max 2-3 concise paragraphs."
    )
    user_content = f"Post Title: {post_title}\n\nPost Content: {post_body}"
    
    try:
        # BUG FIX: Explicit timeout parameter added to prevent connection stalls
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

def send_telegram_alert(subreddit_cluster, title, url, ai_draft):
    """Routes target tracking metrics and drafted content directly to your Telegram bot."""
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # Clean the cluster name for visual clarity in notifications
    clean_sub_display = subreddit_cluster.replace("+", ", ")
    if len(clean_sub_display) > 30:
        clean_sub_display = "Fitness Multifeed"

    message_text = (
        f"🚨 *New Match in [{clean_sub_display}]*\n"
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
    """Strips HTML escape markup and brackets embedded inside Reddit RSS payloads."""
    if not raw_html_string:
        return ""
    clean_text = re.sub(r'<[^>]*>', '', raw_html_string)
    clean_text = clean_text.replace('&lt;', '<').replace('&gt;', '>')
    clean_text = re.sub(r'<[^>]*>', '', clean_text)
    return clean_text.strip()

def poll_reddit_rss_feed():
    """Continuously evaluates target subreddit cluster feeds via RSS stream filters."""
    global seen_post_links
    print("[^] Background RSS polling loop initiated...", flush=True)
    
    while True:
        for combo in SUBREDDIT_GROUPS:
            url = f"https://www.reddit.com/r/{combo}/new/.rss"
            try:
                feed = feedparser.parse(url, agent=CUSTOM_USER_AGENT)
                
                # BUG FIX: Detect 429 rate limit statuses explicitly
                if hasattr(feed, 'status') and feed.status == 429:
                    print(f"[-] Reddit Rate Limit (429) hit for cluster: {combo}. Backing off...", flush=True)
                    time.sleep(10)
                    continue
                
                if feed.bozo and not feed.entries:
                    print(f"[-] Connection dropped or empty payload for: {combo}", flush=True)
                    continue
                
                for entry in feed.entries:
                    link = entry.get("link", "")
                    
                    if link in seen_post_links:
                        continue
                    
                    title = entry.get("title", "")
                    summary_payload = entry.get("summary", "")
                    body_text = clean_html_tags(summary_payload)
                    
                    content_pool = f"{title} {body_text}".lower()
                    
                    print(f"[Scanning] {combo} -> {title[:40]}...", flush=True)
                    
                    if any(keyword in content_pool for keyword in KEYWORDS):
                        print(f"[*] Match detected on keyword! Generating draft...", flush=True)
                        
                        ai_draft = generate_ai_coach_comment(title, body_text)
                        if ai_draft:
                            send_telegram_alert(combo, title, link, ai_draft)
                        else:
                            print("[-] Message skipped due to OpenAI error.", flush=True)
                    
                    seen_post_links.add(link)
            except Exception as e:
                print(f"[-] Operational runtime failure parsing cluster data: {e}", flush=True)
            
            # BUG FIX: Pushed from 3s to 5s to prevent slamming the server with quick requests
            time.sleep(5)
        
        print("[~] Lap completed. Main thread entering sleep cycle...", flush=True)
        time.sleep(60)

if __name__ == "__main__":
    # 1. Initialize cold cache array to avoid alerting on historical postings
    print("[*] Performing cold-start RSS cache warming...", flush=True)
    for target_group in SUBREDDIT_GROUPS:
        try:
            f = feedparser.parse(f"https://www.reddit.com/r/{target_group}/new/.rss", agent=CUSTOM_USER_AGENT)
            for entry in f.entries:
                seen_post_links.add(entry.get("link"))
        except Exception:
            pass
    print(f"[+] Cache warmed. Skipped {len(seen_post_links)} historical posts.", flush=True)

    # 2. Open concurrent Flask thread mapping for the free hosting environment proxy
    threading.Thread(target=run_flask_server, daemon=True).start()
    
    # 3. Hand processing loop execution controls back to the primary engine thread
    poll_reddit_rss_feed()