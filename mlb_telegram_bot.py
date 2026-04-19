"""
MLB Telegram Alert Bot
- Alerta cuando un equipo lleva 3+ carreras en el inning 4, 5 o 6
- Sigue enviando actualizaciones de ese partido hasta que termine

Requisitos:
    pip install requests

Configuración:
    1. Rellena TELEGRAM_TOKEN y CHAT_ID abajo
"""

import requests
import time
import logging
from datetime import datetime, timezone

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = "8210715470:AAEMKEXZdYj-I1Na1dP5KxxqDtDnUtqt48o"
CHAT_ID        = "8185770049"

TARGET_INNINGS  = {4, 5, 6}    # Innings donde se activa el seguimiento
MIN_RUN_LEAD    = 2             # Alerta con 3+ carreras de ventaja (> 2)
POLL_INTERVAL   = 45            # Segundos entre chequeos
# ──────────────────────────────────────────────────────────────────────────────

MLB_API = "https://statsapi.mlb.com/api/v1"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# game_pk → último marcador enviado, ej: "Cubs 5 - Cardinals 2"
tracking: dict[int, str] = {}


def send_telegram(msg: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info(f"✅ Enviado: {msg[:80]}...")
    except Exception as e:
        log.error(f"❌ Error Telegram: {e}")


def get_live_games() -> list[dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (
        f"{MLB_API}/schedule"
        f"?sportId=1&date={today}"
        f"&hydrate=linescore&gameType=R"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        dates = r.json().get("dates", [])
        return dates[0].get("games", []) if dates else []
    except Exception as e:
        log.error(f"❌ Error MLB API: {e}")
        return []


def inning_suffix(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def check_games() -> None:
    games = get_live_games()
    active_pks = set()

    for game in games:
        abstract  = game.get("status", {}).get("abstractGameCode", "")
        detailed  = game.get("status", {}).get("detailedState", "")
        game_pk   = game["gamePk"]
        home_team = game["teams"]["home"]["team"]["name"]
        away_team = game["teams"]["away"]["team"]["name"]
        linescore = game.get("linescore", {})
        home_runs = linescore.get("teams", {}).get("home", {}).get("runs", 0)
        away_runs = linescore.get("teams", {}).get("away", {}).get("runs", 0)
        inning    = linescore.get("currentInning", 0)
        state     = linescore.get("inningState", "")   # Top/Middle/Bottom/End

        # ── Partido terminado ─────────────────────────────────────────────────
        if abstract == "F" and game_pk in tracking:
            if home_runs > away_runs:
                winner, w_runs, l_runs = home_team, home_runs, away_runs
            else:
                winner, w_runs, l_runs = away_team, away_runs, home_runs

            send_telegram(
                f"🏁 <b>PARTIDO TERMINADO</b>\n"
                f"{away_team} @ {home_team}\n\n"
                f"🏆 Ganador: <b>{winner}</b>\n"
                f"📊 Final: <b>{away_runs}-{home_runs}</b>"
            )
            del tracking[game_pk]
            continue

        if abstract != "L":
            continue   # No está en vivo todavía

        active_pks.add(game_pk)
        score_key = f"{away_runs}-{home_runs}-{inning}-{state}"

        # ── Ya en seguimiento → envía update solo si cambió algo ──────────────
        if game_pk in tracking:
            if tracking[game_pk] == score_key:
                continue  # Sin cambios, no molesta

            lead = abs(home_runs - away_runs)
            if home_runs > away_runs:
                leader, trailer = home_team, away_team
                score_str = f"{home_runs}-{away_runs}"
            elif away_runs > home_runs:
                leader, trailer = away_team, home_team
                score_str = f"{away_runs}-{home_runs}"
            else:
                leader, trailer, score_str = None, None, f"{home_runs}-{away_runs}"

            if leader:
                msg = (
                    f"🔄 <b>UPDATE</b> — {inning_suffix(inning)} inning ({state})\n"
                    f"{away_team} @ {home_team}\n\n"
                    f"📊 <b>{leader}</b> {score_str} <b>{trailer}</b>\n"
                    f"{'➕' if lead > MIN_RUN_LEAD else '⚠️'} Ventaja: <b>{lead} carreras</b>"
                )
            else:
                msg = (
                    f"🔄 <b>UPDATE</b> — {inning_suffix(inning)} inning ({state})\n"
                    f"{away_team} @ {home_team}\n\n"
                    f"📊 <b>Empate {score_str}</b> ⚠️"
                )

            send_telegram(msg)
            tracking[game_pk] = score_key
            continue

        # ── Partido nuevo → verificar si cumple criterio de entrada ───────────
        if inning not in TARGET_INNINGS:
            continue

        lead = abs(home_runs - away_runs)
        if lead <= MIN_RUN_LEAD:
            continue

        if home_runs > away_runs:
            leader, trailer = home_team, away_team
            score_str = f"{home_runs}-{away_runs}"
        else:
            leader, trailer = away_team, home_team
            score_str = f"{away_runs}-{home_runs}"

        send_telegram(
            f"⚾ <b>MLB ALERTA</b> — {inning_suffix(inning)} inning ({state})\n"
            f"{away_team} @ {home_team}\n\n"
            f"🏆 <b>{leader}</b> lidera {score_str} <b>{trailer}</b>\n"
            f"📊 Ventaja: <b>{lead} carreras</b>\n\n"
            f"👀 <i>Siguiendo este partido hasta el final...</i>"
        )
        tracking[game_pk] = score_key

    # Limpia partidos que ya no aparecen en la API (edge case)
    for pk in list(tracking.keys()):
        if pk not in active_pks:
            del tracking[pk]

    log.info(f"Chequeo OK — {len(tracking)} partido(s) en seguimiento activo")


def main() -> None:
    log.info("🤖 Bot MLB iniciado.")
    send_telegram(
        "🤖 <b>MLB Alert Bot activo</b>\n"
        "Alertas: 3+ carreras de ventaja en innings 4, 5 o 6.\n"
        "Seguimiento continuo hasta que termine el partido."
    )
    while True:
        try:
            check_games()
        except Exception as e:
            log.error(f"Error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
