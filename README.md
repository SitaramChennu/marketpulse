# 📈 MarketPulse - Live Investments & Portfolio Intelligence

MarketPulse is a live market tracking and mutual fund portfolio intelligence web application built for Indian markets. It tracks real-time market movements across benchmark indices (Nifty 50, Sensex, Nifty Bank, Midcap, Smallcap) and computes live NAV estimations before AMFI releases official end-of-day data.

---

## ✨ Features

- **⚡ Live Estimated NAV**: Real-time estimations calculated during live market hours (9:15 AM to 3:30 PM IST).
- **💼 Universal Broker Support**: Enter holdings from any broker (Zerodha Coin, Groww, AngelOne, Upstox, Indmoney, CAMS, KFintech, AMC direct).
- **📅 Historical & Past Investment Calculator**: Accurately tracks long-term investments using historical NAV lookups without losing past profits.
- **🔐 Multi-User Authentication**: Private accounts, salted PBKDF2/SHA-256 hashed passwords, and secure session tokens.
- **📱 PWA & Mobile-First Design**: Installable on Android and iOS home screens with full-screen standalone app experience.
- **↩️ 8-Second Undo Restoration**: Accidentally removed a fund? Restore it with a single tap.
- **⭐ Live Watchlist & Smart Search**: Instant fuzzy search across 10,000+ mutual fund schemes in sub-100ms.

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, FastAPI, Uvicorn
- **Database**: SQLite (WAL mode, composite unique constraints)
- **Data Providers**: AMFI NAV Portal, Yahoo Finance Chart API, mfapi.in
- **Frontend**: Responsive Tailwind CSS, Vanilla JavaScript, HTML5 PWA
- **Deployment**: Docker, Render.yaml, Procfile

---

## 🚀 One-Click Deployment to Render (100% Free)

1. Fork or push this repository to your GitHub.
2. Sign in to [Render.com](https://render.com).
3. Click **New** ➔ **Web Service**.
4. Connect this GitHub repository (`marketpulse`).
5. Render will automatically detect the configuration:
   - **Environment**: `Python` or `Docker`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Click **Deploy Web Service**.
7. In ~60 seconds, your app will be live 24/7/365 with a permanent URL!

---

## 💻 Local Development

```bash
# 1. Clone repository
git clone https://github.com/SitaramChennu/marketpulse.git
cd marketpulse

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start application
python main.py
```

Open `http://localhost:8000` in your browser.
