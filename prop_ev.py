#!/usr/bin/env python3
# prop_ev.py — PropPulse+ v2025.3
# L20-weighted projection + FantasyPros DvP + Auto position + Manual odds entry

import requests
import pandas as pd
import numpy as np
from scipy.stats import norm
import os, json, time
from datetime import datetime, timezone
from dvp_updater import load_dvp_data

dvp_data = load_dvp_data()

# ===============================
# CONFIG
# ===============================
def load_settings():
    default = {
        "default_sportsbook": "Fliff",
        "default_region": "us",
        "data_path": "data/",
        "injury_api_key": "YOUR_SPORTSDATAIO_KEY",
        "balldontlie_api_key": "YOUR_BALLDONTLIE_KEY",
        "cache_hours": 24
    }
    path = "settings.json"

    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=4)
        print("[Config] Created new settings.json.")
        return default

    with open(path, "r") as f:
        settings = json.load(f)

    for k, v in default.items():
        if k not in settings:
            settings[k] = v

    os.makedirs(settings["data_path"], exist_ok=True)
    return settings


# ===============================
# EV / ODDS HELPERS
# ===============================
def american_to_prob(odds):
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)

def net_payout(odds):
    return 100 / abs(odds) if odds < 0 else odds / 100

def ev_sportsbook(p, odds):
    return p * net_payout(odds) - (1 - p)


# ===============================
# INJURY STATUS
# ===============================
def get_injury_status(player_name, api_key):
    if not api_key or "YOUR_SPORTSDATAIO_KEY" in api_key:
        return None
    try:
        url = "https://api.sportsdata.io/v4/nba/scores/json/Players"
        r = requests.get(url, headers={"Ocp-Apim-Subscription-Key": api_key}, timeout=8)
        if r.status_code != 200:
            return None
        for p in r.json():
            if player_name.lower() in p.get("Name", "").lower():
                return p.get("InjuryStatus", None)
    except Exception:
        return None
    return None

def _parse_min_to_float(x):
    # Convert "MM:SS" → float minutes; pass through numeric minutes
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str) and ":" in x:
        try:
            mm, ss = x.split(":")
            return float(mm) + float(ss)/60.0
        except Exception:
            return None
    try:
        return float(x)
    except Exception:
        return None


# ===============================
# PLAYER LOGS FETCHER (BallDon'tLie + ESPN + BBRef)
# ===============================
def fetch_player_logs(player_name, save_dir="data"):
    import re
    os.makedirs(save_dir, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}

    # 1️⃣ BallDon'tLie v2
    try:
        search_url = f"https://api.balldontlie.io/v2/players?search={player_name}"
        res = requests.get(search_url, headers=headers, timeout=10)
        res.raise_for_status()
        players = res.json().get("data", [])
        if not players:
            raise Exception("Player not found")
        player_id = players[0]["id"]

        stats_url = f"https://api.balldontlie.io/v2/stats?player_ids[]={player_id}&per_page=100"
        r = requests.get(stats_url, headers=headers, timeout=10)
        r.raise_for_status()
        games = r.json().get("data", [])
        if not games:
            raise Exception("No games")

        df = pd.json_normalize(games)
        keep = ["game.date", "pts", "reb", "ast", "fg3m", "min"]
        df = df[keep]
        df.columns = ["DATE", "PTS", "REB", "AST", "FG3M", "MIN"]
        df["DATE"] = pd.to_datetime(df["DATE"]).dt.date
        path = os.path.join(save_dir, f"{player_name.replace(' ', '_')}.csv")
        df.to_csv(path, index=False)
        print(f"[Logs] ✅ Saved {len(df)} logs for {player_name} → {path}")
        return df

    except Exception as e:
        print(f"[Logs] ⚠️ BallDon'tLie failed: {e}")

    # 2️⃣ ESPN backup
    try:
        name_slug = "-".join(re.findall(r"[a-zA-Z]+", player_name.lower()))
        url = f"https://www.espn.com/nba/player/gamelog/_/id/{name_slug}"
        tables = pd.read_html(url)
        df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
        df.columns = [c.upper() for c in df.columns]
        rename_map = {"PTS": "PTS", "REB": "REB", "AST": "AST", "3PM": "FG3M", "MIN": "MIN"}
        df = df.rename(columns=rename_map)
        df = df[[c for c in ["PTS", "REB", "AST", "FG3M", "MIN"] if c in df.columns]]
        path = os.path.join(save_dir, f"{player_name.replace(' ', '_')}.csv")
        df.to_csv(path, index=False)
        print(f"[Logs] ✅ ESPN backup saved for {player_name} → {path}")
        return df
    except Exception as e:
        print(f"[Logs] ⚠️ ESPN failed: {e}")

    # 3️⃣ Basketball Reference Backup — working fallback
    try:
        last = player_name.split()[-1].lower()
        first = player_name.split()[0].lower()
        bbref_stub = last[:5] + first[:2] + "01"
        url = f"https://www.basketball-reference.com/players/{last[0]}/{bbref_stub}/gamelog/2025"
        tables = pd.read_html(url)
        df = max(tables, key=lambda t: t.shape[0] * t.shape[1])
        df.columns = [str(c).upper() for c in df.columns]
        df = df.rename(columns={"PTS": "PTS", "TRB": "REB", "AST": "AST", "3P": "FG3M", "MP": "MIN"})
        df = df[[c for c in ["PTS", "REB", "AST", "FG3M", "MIN"] if c in df.columns]]
        df = df.apply(pd.to_numeric, errors="coerce").fillna(0)
        df = df[df["REB"] < 20]  # sanity cap to avoid broken tables
        path = os.path.join(save_dir, f"{player_name.replace(' ', '_')}.csv")
        df.to_csv(path, index=False)
        print(f"[Logs] ✅ BBRef backup saved for {player_name} → {path}")
        return df
    except Exception as e:
        print(f"[Logs] ❌ BBRef failed for {player_name}: {e}")

    print(f"[Logs] 🚫 Could not fetch logs for {player_name}.")
    return None



# ===============================
# L20-WEIGHTED MODEL
# ===============================
def l20_weighted_mean(vals: pd.Series) -> float:
    if len(vals) == 0:
        return 0.0
    season_mean = float(pd.to_numeric(vals, errors="coerce").fillna(0).mean())
    last20 = pd.to_numeric(vals.tail(20), errors="coerce").fillna(0)
    l20_mean = float(last20.mean()) if len(last20) > 0 else season_mean
    return 0.60 * l20_mean + 0.40 * season_mean


def grade_probabilities(df, stat_col, line, proj_mins, avg_mins, injury_status=None, dvp_mult=1.0):
    if stat_col not in df.columns:
        if stat_col == "REB+AST":
            df["REB+AST"] = df["REB"] + df["AST"]
        elif stat_col == "PRA":
            df["PRA"] = df["PTS"] + df["REB"] + df["AST"]
        else:
            raise KeyError(f"Missing stat {stat_col}")

    vals = pd.to_numeric(df[stat_col], errors="coerce").fillna(0.0)
    n = len(vals)
    std = float(vals.std(ddof=0)) if n > 1 else 1.0
    mean = l20_weighted_mean(vals)
    mean *= (proj_mins / avg_mins) if avg_mins > 0 else 1.0
    if injury_status and str(injury_status).lower() not in ["active", "probable"]:
        mean *= 0.9
    mean *= float(dvp_mult)

    print(f"[Model] DvP applied: {dvp_mult:.3f} | Adjusted mean → {mean:.2f}")

    p_norm = 1 - norm.cdf(line, mean, std)
    p_emp = float(np.mean(vals > line)) if n > 0 else 0.5
    p_final = 0.8 * p_norm + 0.2 * p_emp
    return p_final, n, mean


# ===============================
# POSITION DETECTION
# ===============================
def _bdl_headers():
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9"
    }

def get_player_position_auto(player_name, df_logs=None):
    headers = _bdl_headers()
    try:
        url = f"https://api.balldontlie.io/v2/players?search={player_name}"
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
        if data:
            pos = (data[0].get("position") or "").strip().upper()
            if pos in ["PG","SG","SF","PF","C"]:
                print(f"[Position] Pulled from BallDon'tLie: {pos}")
                return pos
    except Exception as e:
        print(f"[Position] ⚠️ BallDon'tLie lookup failed: {e}")

    def avg(col):
        if df_logs is None or col not in df_logs.columns:
            return 0.0
        return pd.to_numeric(df_logs[col], errors="coerce").fillna(0).mean()

    a_ast, a_reb, a_pts = avg("AST"), avg("REB"), avg("PTS")
    if a_ast >= 7: return "PG"
    if a_ast >= 4 and a_reb < 6: return "SG"
    if a_reb >= 9: return "C"
    if a_reb >= 7: return "PF"
    if a_reb >= 5: return "SF"
    return "SG"


# ===============================
# UPCOMING OPPONENT DETECTION (BallDon'tLie)
# ===============================
def get_upcoming_opponent_abbr(player_name):
    headers = _bdl_headers()
    try:
        pr = requests.get(f"https://api.balldontlie.io/v2/players?search={player_name}",
                          headers=headers, timeout=10)
        pr.raise_for_status()
        pdata = pr.json().get("data", [])
        if not pdata:
            return None
        team = pdata[0].get("team") or {}
        team_id = team.get("id")
        if not team_id:
            return None

        today = datetime.now(timezone.utc)
        year = today.year if today.month >= 10 else today.year - 1

        games = []
        page = 1
        while True:
            gurl = (f"https://api.balldontlie.io/v2/games?"
                    f"team_ids[]={team_id}&seasons[]={year}&per_page=100&page={page}&postseason=false")
            gr = requests.get(gurl, headers=headers, timeout=10)
            gr.raise_for_status()
            payload = gr.json()
            batch = payload.get("data", [])
            if not batch:
                break
            games.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        if not games:
            return None

        def to_date(iso):
            try:
                return datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
            except Exception:
                return None

        today_d = today.date()
        future = [(to_date(g.get("date", "")), g) for g in games]
        future = [(d, g) for (d, g) in future if d and d >= today_d]
        if not future:
            return None
        future.sort(key=lambda x: x[0])

        next_g = future[0][1]
        home = next_g.get("home_team", {}) or {}
        away = next_g.get("visitor_team", {}) or {}
        opp_abbr = away.get("abbreviation") if home.get("id") == team_id else home.get("abbreviation")
        return opp_abbr

    except Exception as e:
        print(f"[Schedule] ⚠️ Could not fetch upcoming opponent: {e}")
        return None


# ===============================
# DvP MULTIPLIER
# ===============================
def get_dvp_multiplier(opponent_abbr, position, stat_key):
    try:
        if not opponent_abbr or not position or not stat_key:
            return 1.0
        team_dict = dvp_data.get(opponent_abbr.upper(), {})
        pos_dict  = team_dict.get(position.upper(), {})
        rank      = pos_dict.get(stat_key.upper(), None)
        if rank is None:
            return 1.0
        return 1.1 - (rank - 1) / 300
    except Exception:
        return 1.0


# ===============================
# MAIN
# ===============================
def main():
    settings = load_settings()
    print("🧠 PropPulse+ Model v2025.3 — Player Prop EV Analyzer")
    print("==============================\n")

    player = input("Player name: ").strip()
    stat = input("Stat (PTS / REB / AST / REB+AST / PRA / FG3M): ").strip().upper()
    line = float(input("Line: "))
    odds = int(input("Sportsbook odds (e.g. -110): "))

    path = os.path.join(settings["data_path"], f"{player.replace(' ', '_')}.csv")
    need_refresh = not os.path.exists(path) or (time.time() - os.path.getmtime(path))/3600 > 24

    if need_refresh:
        print(f"[Data] ⏳ Refreshing logs for {player}...")
        df = fetch_player_logs(player, save_dir=settings["data_path"])
        if df is None:
            print(f"[Logs] ❌ Could not fetch logs for {player}.")
            return
    else:
        df = pd.read_csv(path)
        print(f"[Data] Loaded {len(df)} games from {path}")

    if "MIN" in df.columns:
        df["MIN"] = pd.to_numeric(df["MIN"], errors="coerce").fillna(0)
        avg_mins = df["MIN"].mean() if len(df["MIN"]) > 0 else 30
    else:
        avg_mins = 30
    proj_mins = avg_mins

    inj = get_injury_status(player, settings.get("injury_api_key"))
    print(f"[Injury] {player} status: {inj or 'Healthy ✅'}")

    pos = get_player_position_auto(player, df_logs=df)
    print(f"[Position] Auto-detected: {pos}")

    opp = get_upcoming_opponent_abbr(player)
    if opp:
        print(f"[Schedule] Upcoming opponent auto-detected: {opp}")
    else:
        print("[Schedule] Could not auto-detect opponent; using neutral DvP (1.00).")

    dvp_mult = get_dvp_multiplier(opp, pos, stat) if opp else 1.0
    print(f"[DvP] {opp or 'N/A'} vs {pos} on {stat} → multiplier {dvp_mult:.3f}")

    try:
        p_model, n_games, proj_stat = grade_probabilities(df, stat, line, proj_mins, avg_mins, inj, dvp_mult)
    except Exception as e:
        print(f"[Model] Error: {e}")
        return

    p_book = american_to_prob(odds)
    ev = ev_sportsbook(p_model, odds)

    print("\n==============================")
    print(f"📊 {player} | {stat} Line {line}")
    print(f"Games Analyzed: {n_games}")
    print(f"Model Prob:  {p_model*100:.1f}%")
    print(f"Book Prob:   {p_book*100:.1f}%")
    print(f"Model Projection: {proj_stat:.1f} {stat}")
    print(f"EV:          {ev*100:.1f}¢ per $1 | {'🔥 Positive' if ev > 0 else '⚠️ Negative'}")
    if proj_stat > line:
        print("🟢 Over Value")
    else:
        print("🔴 Under Value")
    print("==============================\n")


# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    main()
