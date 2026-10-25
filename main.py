import os
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- FAKE WEB SERVER TO KEEP RENDER FREE TIER HAPPY ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Luca Picks Bot is alive!")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# Start the dummy server in a background thread
threading.Thread(target=run_server, daemon=True).start()
# -----------------------------------------------------

# Pull tokens directly from Render's Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

SPORTS_MAP = {
    "football": ("soccer_epl", "Premier League Football ⚽"),
    "nfl": ("americanfootball_nfl", "NFL Football 🏈"),
    "basketball": ("basketball_nba", "NBA Basketball 🏀"),
}

def calculate_implied_probs(home_odds, away_odds, draw_odds=None):
    if draw_odds:
        rh, rd, ra = 1 / home_odds, 1 / draw_odds, 1 / away_odds
        total = rh + rd + ra
        return (rh / total) * 100, (rd / total) * 100, (ra / total) * 100
    else:
        rh, ra = 1 / home_odds, 1 / away_odds
        total = rh + ra
        return (rh / total) * 100, (ra / total) * 100

def generate_signal(sport_code, sport_label, market_type, home, away, odds_dict, match_time):
    home_odds = odds_dict.get(home, 2.0)
    away_odds = odds_dict.get(away, 2.0)
    draw_odds = odds_dict.get("Draw", None)

    if sport_code == "soccer_epl":
        hp, dp, ap = calculate_implied_probs(home_odds, away_odds, draw_odds)
        if market_type == "win":
            return f"🦅 **LUCA PICKS: MATCH & WIN** 🦅\n{away} vs {home}\nKickoff: {match_time}\n\nWin Probabilities:\n• {home}: {hp:.1f}%\n• Draw: {dp:.1f}%\n• {away}: {ap:.1f}%"
        elif market_type == "goals":
            xg = round(1.3 + (hp / 100) * 0.9, 2)
            return f"⚽ **LUCA PICKS: GOALS & xG** ⚽\n{away} vs {home}\n\n• Expected Goals: {xg} Total\n• Over 2.5 Goals: 58%\n• BTTS: 53%"
        elif market_type == "corners":
            corners = round(9.5 + ((hp - ap) / 100) * 1.8, 1)
            return f"🚩 **LUCA PICKS: CORNERS** 🚩\n{away} vs {home}\n\n• Projected Corners: ~{corners}\n• Over 9.5 Corners: 59%"
        elif market_type == "cards":
            return f"🟨 **LUCA PICKS: CARDS** 🟨\n{away} vs {home}\n\n• Projected Yellow Cards: ~4.5\n• Over 3.5 Cards Edge: 71%"

    hp, ap = calculate_implied_probs(home_odds, away_odds)
    return f"🔥 **LUCA PICKS: {sport_label.upper()}** 🔥\n{away} vs {home} @ {match_time}\n\nWin Probability:\n• {home}: {hp:.1f}%\n• {away}: {ap:.1f}%"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚽ Premier League Football", callback_data="sport_football")],
        [InlineKeyboardButton("🏈 NFL Football", callback_data="sport_nfl")],
        [InlineKeyboardButton("🏀 NBA Basketball", callback_data="sport_basketball")],
    ]
    await update.message.reply_text("🦅 **Welcome to Luca Picks**\nSelect a sport to analyze live odds & stats:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("sport_"):
        key = data.replace("sport_", "")
        code, label = SPORTS_MAP[key]
        context.user_data["code"] = code
        context.user_data["label"] = label
        context.user_data["id"] = key

        if key == "football":
            keyboard = [
                [InlineKeyboardButton("Win Prob", callback_data="market_win"), InlineKeyboardButton("Goals", callback_data="market_goals")],
                [InlineKeyboardButton("Corners", callback_data="market_corners"), InlineKeyboardButton("Cards", callback_data="market_cards")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_home")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("Win Prob", callback_data="market_win"), InlineKeyboardButton("⬅️ Back", callback_data="back_home")]
            ]
        await query.edit_message_text(f"🎯 **{label} Selected**\nChoose a category:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data == "back_home":
        keyboard = [
            [InlineKeyboardButton("⚽ Premier League Football", callback_data="sport_football")],
            [InlineKeyboardButton("🏈 NFL Football", callback_data="sport_nfl")],
            [InlineKeyboardButton("🏀 NBA Basketball", callback_data="sport_basketball")],
        ]
        await query.edit_message_text("🦅 **Welcome to Luca Picks**\nSelect a sport to analyze live odds & stats:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    if data.startswith("market_"):
        m_type = data.replace("market_", "")
        code = context.user_data.get("code", "soccer_epl")
        label = context.user_data.get("label", "Football")
        s_id = context.user_data.get("id", "football")

        url = f"https://api.the-odds-api.com/v4/sports/{code}/odds/?apiKey={ODDS_API_KEY}&regions=uk,us&markets=h2h"
        try:
            res = requests.get(url)
            m_data = res.json()
            if not m_data:
                text = "❌ No upcoming matches found right now."
            else:
                match = m_data[0]
                home = match.get("home_team")
                away = match.get("away_team")
                time_raw = match.get("commence_time")
                match_time = datetime.strptime(time_raw, "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d @ %H:%M UTC") if time_raw else "Soon"
                
                odds = {}
                if match.get("bookmakers"):
                    odds = {o["name"]: o["price"] for o in match["bookmakers"][0]["markets"][0]["outcomes"]}
                text = generate_signal(code, label, m_type, home, away, odds, match_time)
        except Exception as e:
            text = f"Error loading data: {str(e)}"

        if s_id == "football":
            keyboard = [
                [InlineKeyboardButton("Win", callback_data="market_win"), InlineKeyboardButton("Goals", callback_data="market_goals")],
                [InlineKeyboardButton("Corners", callback_data="market_corners"), InlineKeyboardButton("Cards", callback_data="market_cards")],
                [InlineKeyboardButton("🔄 Change Sport", callback_data="back_home")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("Win", callback_data="market_win"), InlineKeyboardButton("🔄 Change Sport", callback_data="back_home")]
            ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Luca Picks bot is running with dummy web server...")
    app.run_polling()
    
