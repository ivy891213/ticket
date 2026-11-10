# 三鷹吉卜力美術館門票監控（非官方）

## 監控設定
- 2026/12/9–12/14，優先 12/10；2 人。
- 每 5 分鐘由 GitHub Actions **嘗試**檢查；排程可能延遲或暫停。
- 僅在頁面出現**明確可預約字樣**時寄送「疑似有票」通知。程式**無法保證兩張票的實際庫存**。
- 不登入、不破解 CAPTCHA、不繞過封鎖、不自動購票。

## 1. 建立 GitHub Repository
1. 登入 GitHub → New repository，命名 `ghibli-monitor`，設為 **Public**（GitHub Pages 免費方案較方便）。
2. 將本 ZIP 解壓縮後的**所有檔案（含隱藏的 `.github` 資料夾）**上傳到 repo 根目錄，提交至 `main` 分支。
3. Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save。
4. Settings → Pages → Build and deployment → Source 選 **GitHub Actions**。

## 2. 設定 Email
到 Settings → Secrets and variables → Actions → New repository secret，逐一加入：

| Secret | Gmail 範例 |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | 你的 Gmail 地址 |
| `SMTP_PASSWORD` | Google **應用程式密碼**（不是一般登入密碼；需符合 Google 的雙步驟驗證與應用程式密碼申請條件） |
| `SMTP_FROM` | 你的 Gmail 地址 |
| `ALERT_TO` | 你想收到提醒的 Email |

其他郵件服務可使用其 SMTP 設定；公司信箱可能不支援 SMTP 密碼登入。**不要把密碼寫在 config.json 或 commit 到 GitHub。**

## 3. 啟動
1. Actions → `Check Ghibli tickets` → Run workflow → Run workflow。
2. 第一次執行成功後，開啟 Settings → Pages 顯示的網址，通常是 `https://你的帳號.github.io/ghibli-monitor/`。
3. 每次檢查後網站會顯示最新狀態及最近 100 筆紀錄。排程非即時，可能有延遲。
4. 如果狀態持續為「未偵測到明確開放訊號」，**不代表售完**，可能是 Lawson 網頁結構與偵測器不符。需要人工檢查網頁內容並調整解析規則。

## 4. 重要限制與故障排除
- Lawson 可能需要 Cookie、互動或有防機器人措施；本工具不繞過這些機制，遇到驗證請人工到官方頁面操作。
- **目前無法從此環境連線測試 Lawson 網址**，所以尚未驗證頁面實際 DOM、日期和座位選擇結構。此專案是可部署的監控骨架，不是已驗證成功的庫存偵測器。
- 日期偵測採保守文字匹配，可能漏報；即使寄信也**不代表已確認兩張可買**。
- GitHub Pages 是公開網站，`public/status.json` 會顯示檢查結果及監控日期，但不會包含 SMTP secrets。
- GitHub Actions 的 `*/5` 是最短常見排程間隔，**不保證**每五分鐘準時執行；repo 無活動時排程可能被停用。
- 如果 Actions 無法 push，檢查 workflow permissions；如果 Pages 部署失敗，確認 Pages Source 已選 GitHub Actions。
- 監控完成後可到 Actions 停用工作流程，以免持續消耗資源。

## 5. 調整日期與網址
編輯 `config.json`。預設監控 6 個日期，`priority_date` 僅在網頁標示優先，不會自動預訂。
