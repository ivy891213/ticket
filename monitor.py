"""Conservative ticket page watcher. Never purchases, logs in, or bypasses anti-bot."""
import json, os, re, smtplib, ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
STATE = ROOT / 'state.json'
PUBLIC = ROOT / 'public'
PUBLIC.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat(timespec='seconds')
# Never infer availability from an unlabeled circle or merely an enabled date button.
OPEN = re.compile(r'(?i)(available|vacancies|vacancy|tickets? available|予約可能|空席あり|残席あり|受付中|購入可能|販売中|残り[1-9１-９])')
CLOSED = re.compile(r'(?i)(sold\s*out|unavailable|fully\s*booked|no\s*tickets|受付終了|完売|予定枚数終了|販売終了|空席なし|満席|×|✕|受付前)')
BLOCK = re.compile(r'(?i)(captcha|access denied|403 forbidden|bot detection|アクセスが集中|不正なアクセス|しばらくしてから|認証してください)')
DATE_FORMATS = [lambda d: f'{int(d[5:7])}/{int(d[8:10])}', lambda d: f'{int(d[5:7])}月{int(d[8:10])}日', lambda d: d]

def load_state():
    try: return json.loads(STATE.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError): return {'last_available': [], 'history': []}

def send_email(items):
    host = os.getenv('SMTP_HOST', '')
    sender, recipient = os.getenv('SMTP_FROM', ''), os.getenv('ALERT_TO', '')
    if not all([host, sender, recipient, os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD')]):
        return 'not_configured'
    msg = EmailMessage()
    msg['From'], msg['To'] = sender, recipient
    msg['Subject'] = '【吉卜力門票提醒】可能出現可預約名額（請立即人工確認）'
    msg.set_content('偵測到以下疑似開放名額（尚未證實可一次購買 2 張）：\n' + '\n'.join(items) + '\n\n請立即至官方頁面確認 2 人可購買：\n' + CONFIG['url'] + '\n\n這不是訂票成功通知。')
    port = int(os.getenv('SMTP_PORT', '465'))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=25) as server:
            server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD']); server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD']); server.send_message(msg)
    return 'sent'

def inspect(html):
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(['script','style','noscript','svg']): el.decompose()
    text = soup.get_text(' ', strip=True)
    if BLOCK.search(text[:8000]): return 'blocked', [], '疑似驗證或反機器人頁面'
    if len(text) < 70: return 'unknown', [], '頁面文字過少或內容動態載入'
    found = []
    for date in CONFIG['dates']:
        # Use a small ancestor / nearby textual window to avoid matching a global availability legend.
        formats = DATE_FORMATS
        candidates = []
        for tag in soup.find_all(string=True):
            s = str(tag).strip()
            if any(f(date) in s for f in formats):
                if len(s) > 180: continue
                parent = tag.parent
                for _ in range(3):
                    if parent is None: break
                    snippet = parent.get_text(' ', strip=True)
                    if 12 <= len(snippet) <= 320: candidates.append(snippet)
                    parent = parent.parent
        # Avoid broad page matches: require date + affirmative status in same compact node,
        # and reject if any negative status appears in the same node.
        for snippet in candidates:
            if OPEN.search(snippet) and not CLOSED.search(snippet):
                found.append({'date': date, 'evidence': snippet[:180], 'quantity_verified': False})
                break
    if found: return 'possible', found, '日期附近出現開放字樣；2人名額未確認'
    return 'no_confirmed', [], '沒有偵測到明確可預約訊號；不等於確認售完'

def main():
    state = load_state()
    status, found, note = 'unknown', [], ''
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(locale='en-US', timezone_id='Asia/Tokyo', viewport={'width':1280,'height':900})
            response = page.goto(CONFIG['url'], wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(5500)
            html = page.content()
            if response and response.status >= 400:
                status, note = 'blocked' if response.status in (403,429) else 'error', f'HTTP {response.status}'
            else: status, found, note = inspect(html)
            browser.close()
    except Exception as exc:
        status, note = 'error', str(exc)[:200]
    keys = [f['date'] for f in found]
    previous = set(state.get('last_available', []))
    new = [f for f in found if f['date'] not in previous]
    email_status = 'not_needed'
    if new:
        try: email_status = send_email([f"{f['date']}：{f['evidence']}" for f in new])
        except Exception as exc: email_status = 'failed: ' + str(exc)[:150]
    # Only remember notified dates if message was sent. Failed email will retry.
    if status == 'possible':
        state['last_available'] = keys if email_status in ('sent','not_needed') else sorted(previous)
    # Do not reset dedup on blocked / unknown checks (prevents repeat spam).
    elif status == 'no_confirmed': state['last_available'] = []
    state['last_checked_utc'] = NOW
    state['status'] = status
    state['note'] = note
    state['found'] = found
    state['email_status'] = email_status
    state['history'] = ([{'at': NOW, 'status': status, 'found_dates': keys, 'email': email_status}] + state.get('history', []))[:100]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    (PUBLIC / 'status.json').write_text(json.dumps({'config': CONFIG, **state}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': status, 'found': keys, 'email': email_status, 'note': note}, ensure_ascii=False))

if __name__ == '__main__': main()
