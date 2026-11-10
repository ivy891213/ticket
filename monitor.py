"""Read-only Lawson ticket watcher; no login, CAPTCHA solving, or purchases."""
import json, os, re, smtplib, ssl, time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
STATE = ROOT / 'state.json'
PUBLIC = ROOT / 'public'
PUBLIC.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc).isoformat(timespec='seconds')
OPEN = re.compile(r'(?i)(available|vacancies|vacancy|tickets? available|予約可能|空席あり|残席あり|受付中|購入可能|販売中|残り[1-9１-９])')
CLOSED = re.compile(r'(?i)(sold\s*out|unavailable|fully\s*booked|no\s*tickets|受付終了|完売|予定枚数終了|販売終了|空席なし|満席|×|✕|受付前)')
BLOCK = re.compile(r'(?i)(captcha|access denied|403 forbidden|bot detection|アクセスが集中|不正なアクセス|しばらくしてから|認証してください)')

def load_state():
    try:
        value = json.loads(STATE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def send_email(items):
    host = os.getenv('SMTP_HOST', '')
    sender, recipient = os.getenv('SMTP_FROM', ''), os.getenv('ALERT_TO', '')
    if not all([host, sender, recipient, os.getenv('SMTP_USER'), os.getenv('SMTP_PASSWORD')]):
        return 'not_configured'
    msg = EmailMessage()
    msg['From'], msg['To'] = sender, recipient
    msg['Subject'] = '【吉卜力門票提醒】疑似開放名額（請人工確認）'
    msg.set_content('偵測到疑似開放日期，尚未證實可購買 2 張：\n' + '\n'.join(items) + '\n\n請到官方網站確認：\n' + CONFIG['url'])
    port = int(os.getenv('SMTP_PORT', '465'))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=25) as server:
            server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            server.send_message(msg)
    return 'sent'

def inspect(html):
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(['script', 'style', 'noscript', 'svg']):
        el.decompose()
    text = soup.get_text(' ', strip=True)
    if BLOCK.search(text[:8000]):
        return 'blocked', [], '頁面要求驗證或限制存取；停止本次查詢'
    if len(text) < 70:
        return 'unknown', [], '頁面內容不足，無法判斷票況'
    found = []
    for date in CONFIG['dates']:
        formats = [f'{int(date[5:7])}/{int(date[8:10])}', f'{int(date[5:7])}月{int(date[8:10])}日', date]
        candidates = []
        for tag in soup.find_all(string=True):
            s = str(tag).strip()
            if len(s) > 180 or not any(f in s for f in formats):
                continue
            parent = tag.parent
            for _ in range(3):
                if parent is None:
                    break
                snippet = parent.get_text(' ', strip=True)
                if 12 <= len(snippet) <= 320:
                    candidates.append(snippet)
                parent = parent.parent
        for snippet in candidates:
            if OPEN.search(snippet) and not CLOSED.search(snippet):
                found.append({'date': date, 'evidence': snippet[:180], 'quantity_verified': False})
                break
    if found:
        return 'possible', found, '日期附近有開放字樣；尚未確認可購買 2 張'
    return 'no_confirmed', [], '沒有明確開放訊號；不代表售完'

def check_page():
    # One normal browser navigation, followed by at most one retry for transient transport errors.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            for attempt in range(2):
                context = browser.new_context(locale='ja-JP', timezone_id='Asia/Tokyo', viewport={'width': 1280, 'height': 900})
                page = context.new_page()
                try:
                    response = page.goto(CONFIG['url'], wait_until='domcontentloaded', timeout=45000)
                    if response is None:
                        return 'unknown', [], '未取得 HTTP 回應'
                    code = response.status
                    if code in (403, 429):
                        return 'blocked', [], f'HTTP {code}：網站限制存取，不重試'
                    if code >= 400:
                        return 'error', [], f'HTTP {code}'
                    page.wait_for_timeout(3500)
                    return inspect(page.content())
                except Exception as exc:
                    message = str(exc).splitlines()[0][:180]
                    transient = any(x in message for x in ('ERR_HTTP2_PROTOCOL_ERROR', 'ERR_CONNECTION_RESET', 'ERR_TIMED_OUT', 'Timeout'))
                    if attempt == 0 and transient:
                        print('Transient navigation error; one retry after 8 seconds:', message)
                        time.sleep(8)
                        continue
                    return 'error', [], '頁面連線失敗：' + message
                finally:
                    context.close()
        finally:
            browser.close()

def main():
    state = load_state()
    try:
        status, found, note = check_page()
    except Exception as exc:
        status, found, note = 'error', [], str(exc).splitlines()[0][:180]
    keys = [item['date'] for item in found]
    previous = set(state.get('last_available', []))
    new = [item for item in found if item['date'] not in previous]
    email_status = 'not_needed'
    if new:
        try:
            email_status = send_email([f"{item['date']}：{item['evidence']}" for item in new])
        except Exception as exc:
            email_status = 'failed: ' + str(exc).splitlines()[0][:130]
    if status == 'possible':
        # Only mark a new date as notified after successful email delivery.
        if email_status == 'sent':
            state['last_available'] = sorted(previous | set(keys))
        elif not new:
            state['last_available'] = keys
    elif status == 'no_confirmed':
        state['last_available'] = []
    state.update(last_checked_utc=NOW, status=status, note=note, found=found, email_status=email_status)
    state['history'] = ([{'at': NOW, 'status': status, 'found_dates': keys, 'email': email_status}] + state.get('history', []))[:100]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    (PUBLIC / 'status.json').write_text(json.dumps({'config': CONFIG, **state}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': status, 'found': keys, 'email': email_status, 'note': note}, ensure_ascii=False))

if __name__ == '__main__':
    main()
