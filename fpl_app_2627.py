import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="FPL 2026-27 GW Explorer", layout="wide")

DATA_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2026-27/gws/merged_gw.csv"
BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
LIVE_URL = "https://fantasy.premierleague.com/api/event/{gw}/live/"
UNDERSTAT_SEASON = "2026"  # Understat labels seasons by their start year, so 2026-27 -> "2026"

# Friendly label -> actual column name
STAT_OPTIONS = {
    "Total Points": "total_points",
    "Minutes": "minutes",
    "Goals": "goals_scored",
    "Assists": "assists",
    "Clean Sheets": "clean_sheets",
    "Goals Conceded": "goals_conceded",
    "xG": "expected_goals",
    "xA": "expected_assists",
    "xGI": "expected_goal_involvements",
    "xGC": "expected_goals_conceded",
    "Defensive Contribution": "defensive_contribution",
    "Tackles": "tackles",
    "Recoveries": "recoveries",
    "Clearances/Blocks/Interceptions": "clearances_blocks_interceptions",
    "Bonus": "bonus",
    "BPS": "bps",
    "ICT Index": "ict_index",
    "Influence": "influence",
    "Creativity": "creativity",
    "Threat": "threat",
    "Saves": "saves",
    "Yellow Cards": "yellow_cards",
    "Red Cards": "red_cards",
    "Starts": "starts",
    "xP": "xP",
}

POSITION_ORDER = ["GK", "DEF", "MID", "FWD"]

# Friendly label -> (source column, aggregation function) for team-level rollups.
# "sum" for stats that add up across a team's players (goals, xG, cards, bonus).
# "max" for stats that are shared/duplicated across the team for a fixture
# (goals conceded, clean sheets, xGC are the same team-wide value per player).
TEAM_STAT_OPTIONS = {
    "Goals Scored": ("goals_scored", "sum"),
    "Goals Conceded": ("goals_conceded", "max"),
    "Clean Sheets": ("clean_sheets", "max"),
    "xG": ("expected_goals", "sum"),
    "xGA": ("expected_goals_conceded", "max"),
    "Assists": ("assists", "sum"),
    "Bonus": ("bonus", "sum"),
    "Yellow Cards": ("yellow_cards", "sum"),
    "Red Cards": ("red_cards", "sum"),
    "Saves": ("saves", "sum"),
    "Total Points": ("total_points", "sum"),
}

# Stats shown by default in the Compare table (subset of STAT_OPTIONS, in display order)
COMPARE_DEFAULT_STATS = [
    "Total Points", "Minutes", "Goals", "Assists", "Clean Sheets",
    "xG", "xA", "Defensive Contribution", "Bonus", "BPS",
]

# Friendly label -> Understat field name (season-total shot/xG data, not per-GW)
UNDERSTAT_STAT_OPTIONS = {
    "npxG": "npxG",
    "xG": "xG",
    "xA": "xA",
    "Shots": "shots",
    "Key Passes": "key_passes",
    "Non-Penalty Goals": "npg",
    "Goals": "goals",
    "Assists": "assists",
    "Minutes": "time",
}

# Stats rounded to 2 decimal places for display (Understat returns long floats)
UNDERSTAT_DECIMAL_STATS = {"npxG", "xG", "xA"}


@st.cache_data(ttl=3600)
def load_data():
    df = pd.read_csv(DATA_URL)
    return df


@st.cache_data(ttl=1800)
def load_bootstrap():
    r = requests.get(BOOTSTRAP_URL, timeout=15)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def load_live(gw):
    r = requests.get(LIVE_URL.format(gw=gw), timeout=15)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600)
def load_understat():
    from understatapi import UnderstatClient
    with UnderstatClient() as understat:
        data = understat.league(league="EPL").get_player_data(season=UNDERSTAT_SEASON)
    df = pd.DataFrame(data)
    numeric_cols = [
        "games", "time", "goals", "xG", "assists", "xA", "shots",
        "key_passes", "yellow_cards", "red_cards", "npg", "npxG",
        "xGChain", "xGBuildup",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def build_lookups(bootstrap):
    team_names = {t["id"]: t["name"] for t in bootstrap["teams"]}
    player_names = {p["id"]: f"{p['first_name']} {p['second_name']}" for p in bootstrap["elements"]}
    player_web_names = {p["id"]: p["web_name"] for p in bootstrap["elements"]}
    return team_names, player_names, player_web_names


def render_gw_summary():
    st.title("Gameweek Summary")

    bootstrap = load_bootstrap()
    team_names, player_names, player_web_names = build_lookups(bootstrap)

    events = bootstrap["events"]
    gw_options = [e["id"] for e in events]
    current_gw = next((e["id"] for e in events if e.get("is_current")), gw_options[0])

    gw = st.selectbox("Gameweek", gw_options, index=gw_options.index(current_gw), key="gw_summary_select")
    event_meta = next(e for e in events if e["id"] == gw)

    if not event_meta.get("finished") and event_meta.get("average_entry_score", 0) == 0:
        st.info("This gameweek hasn't started or finished yet — some overview stats may be blank.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Average Score", event_meta.get("average_entry_score", "—"))
    col2.metric("Highest Score", event_meta.get("highest_score", "—"))
    most_captained_id = event_meta.get("most_captained")
    most_vice_captained_id = event_meta.get("most_vice_captained")
    col3.metric("Most Captained", player_web_names.get(most_captained_id, "—"))
    col4.metric("Most Vice-Captained", player_web_names.get(most_vice_captained_id, "—"))

    # Price and ownership lookups from bootstrap-static
    price_lookup = {p["id"]: p["now_cost"] / 10 for p in bootstrap["elements"]}
    ownership_lookup = {p["id"]: float(p["selected_by_percent"]) for p in bootstrap["elements"]}

    live = load_live(gw)
    rows = []
    for el in live["elements"]:
        s = el["stats"]
        if s["minutes"] == 0:
            continue
        price = price_lookup.get(el["id"], 0)
        points = s["total_points"]
        rows.append({
            "Player": player_web_names.get(el["id"], el["id"]),
            "Team": team_names.get(
                next((p["team"] for p in bootstrap["elements"] if p["id"] == el["id"]), None), "—"
            ),
            "Points": points,
            "Minutes": s["minutes"],
            "Goals": s["goals_scored"],
            "Assists": s["assists"],
            "Clean Sheets": s["clean_sheets"],
            "Bonus": s["bonus"],
            "BPS": s["bps"],
            "xG": s.get("expected_goals", 0),
            "xA": s.get("expected_assists", 0),
            "Defensive Contribution": s.get("defensive_contribution", 0),
            "Saves": s.get("saves", 0),
            "Price": price,
            "Points per Million": round(points / price, 2) if price else 0,
            "Ownership %": ownership_lookup.get(el["id"], 0),
        })

    if not rows:
        st.info("No player data yet for this gameweek.")
        return

    gw_df = pd.DataFrame(rows).reset_index(drop=True)

    leaderboard_categories = [
        "Points", "Goals", "Assists",
        "BPS", "xG", "xA", "Defensive Contribution", "Saves",
        "Points per Million",
    ]

    st.subheader("Top 5 by Category")

    low_owned = gw_df[gw_df["Ownership %"] < 5].sort_values("Points", ascending=False).head(5)
    low_owned = low_owned[["Player", "Team", "Points"]].reset_index(drop=True)
    low_owned.index = low_owned.index + 1

    def render_leaderboard_col(col, label, table):
        with col:
            st.markdown(f"**{label}**")
            if table.empty:
                st.write("No qualifying players this gameweek.")
            else:
                st.dataframe(table, use_container_width=True)

    cols_per_row = 2
    low_owned_rendered = False
    for i in range(0, len(leaderboard_categories), cols_per_row):
        row_categories = leaderboard_categories[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, category in zip(cols, row_categories):
            top5 = gw_df.sort_values(category, ascending=False).head(5)
            top5 = top5[["Player", "Team", category]].reset_index(drop=True)
            top5.index = top5.index + 1
            render_leaderboard_col(col, category, top5)
        # Slot the low-ownership leaderboard into any free spot in this row
        if len(row_categories) < cols_per_row:
            render_leaderboard_col(cols[len(row_categories)], "Highest Points (< 5% Owned)", low_owned)
            low_owned_rendered = True

    if not low_owned_rendered:
        render_leaderboard_col(st.container(), "Highest Points (< 5% Owned)", low_owned)


def render_player_explorer():
    st.title("FPL 2026-27 Gameweek Explorer")

    df = load_data()

    # Latest known price/position/team per player (most recent GW row)
    latest = df.sort_values("GW").groupby("name").last().reset_index()
    latest = latest[["name", "position", "team", "value"]]
    latest["price"] = latest["value"] / 10

    # Sidebar filters
    st.sidebar.header("Filters")

    teams = sorted(latest["team"].unique())
    selected_teams = st.sidebar.multiselect("Team", teams, default=[], key="player_team_filter")

    selected_positions = st.sidebar.multiselect(
        "Position", POSITION_ORDER, default=[], key="player_position_filter"
    )

    price_min, price_max = float(latest["price"].min()), float(latest["price"].max())
    price_range = st.sidebar.slider(
        "Price range (£m)", price_min, price_max, (price_min, price_max), step=0.1, key="player_price_range"
    )

    st.sidebar.header("Stat & Sort")
    stat_label = st.sidebar.selectbox(
        "Stat to display per GW", list(STAT_OPTIONS.keys()), index=0, key="player_stat_select"
    )
    stat_col = STAT_OPTIONS[stat_label]

    sort_by = st.sidebar.selectbox(
        "Sort players by", ["Price", "Position", "Team", "Total (selected stat)"], key="player_sort_by"
    )
    sort_desc = st.sidebar.checkbox("Descending", value=True, key="player_sort_desc")

    # Apply filters to player list
    filtered_players = latest.copy()
    if selected_teams:
        filtered_players = filtered_players[filtered_players["team"].isin(selected_teams)]
    if selected_positions:
        filtered_players = filtered_players[filtered_players["position"].isin(selected_positions)]
    filtered_players = filtered_players[
        (filtered_players["price"] >= price_range[0]) & (filtered_players["price"] <= price_range[1])
    ]

    # Pivot: rows = players, columns = GW, values = selected stat
    pivot_source = df[df["name"].isin(filtered_players["name"])]
    pivot = pivot_source.pivot_table(
        index="name", columns="GW", values=stat_col, aggfunc="sum", fill_value=0
    )
    pivot.columns = [f"GW{int(c)}" for c in pivot.columns]
    pivot = pivot.sort_index(axis=1, key=lambda idx: [int(c[2:]) for c in idx])

    # Merge player meta back in
    result = filtered_players.set_index("name").join(pivot)
    gw_cols = [c for c in result.columns if c.startswith("GW")]
    result["Total"] = result[gw_cols].sum(axis=1)
    result["Avg"] = result[gw_cols].mean(axis=1).round(2)

    # Sorting
    sort_map = {
        "Price": "price",
        "Position": "position",
        "Team": "team",
        "Total (selected stat)": "Total",
    }
    sort_col = sort_map[sort_by]
    if sort_col == "position":
        result["_pos_order"] = result["position"].apply(lambda p: POSITION_ORDER.index(p))
        result = result.sort_values("_pos_order", ascending=not sort_desc).drop(columns="_pos_order")
    else:
        result = result.sort_values(sort_col, ascending=not sort_desc)

    # Drop the Team column when the view is already filtered down to one team
    base_cols = ["position", "team", "price"]
    if len(selected_teams) == 1:
        base_cols = ["position", "price"]

    display_cols = base_cols + gw_cols + ["Total", "Avg"]
    result = result[display_cols].rename(columns={"position": "Pos", "team": "Team", "price": "Price"})

    st.caption(f"Showing **{stat_label}** per gameweek · {len(result)} players")
    st.dataframe(result, use_container_width=True, height=700)


def render_team_stats():
    st.title("Team Stats by Gameweek")

    df = load_data()
    bootstrap = load_bootstrap()

    # Use bootstrap-static for current team assignment rather than the CSV's own
    # "team" column, which can be stale/wrong early in the season for transferred players.
    element_team_map = {p["id"]: p["team"] for p in bootstrap["elements"]}
    team_name_map = {t["id"]: t["name"] for t in bootstrap["teams"]}

    df = df.copy()
    df["team_id"] = df["element"].map(element_team_map)
    df["team_name"] = df["team_id"].map(team_name_map)
    df = df.dropna(subset=["team_name"])

    all_teams = sorted(df["team_name"].unique())

    st.sidebar.header("Team Filter")
    selected_teams = st.sidebar.multiselect("Team", all_teams, default=[], key="team_stats_team_filter")

    st.sidebar.header("Stat")
    stat_label = st.sidebar.selectbox(
        "Stat to display per GW", list(TEAM_STAT_OPTIONS.keys()), index=0, key="team_stats_stat_select"
    )
    stat_col, agg_func = TEAM_STAT_OPTIONS[stat_label]

    view_df = df if not selected_teams else df[df["team_name"].isin(selected_teams)]

    pivot = view_df.pivot_table(
        index="team_name", columns="GW", values=stat_col, aggfunc=agg_func, fill_value=0
    )
    pivot.columns = [f"GW{int(c)}" for c in pivot.columns]
    pivot = pivot.sort_index(axis=1, key=lambda idx: [int(c[2:]) for c in idx])

    gw_cols = list(pivot.columns)
    if agg_func == "sum":
        pivot["Total"] = pivot[gw_cols].sum(axis=1)
    else:
        pivot["Total"] = pivot[gw_cols].sum(axis=1)  # e.g. total clean sheets, total conceded across GWs
    pivot["Avg"] = pivot[gw_cols].mean(axis=1).round(2)

    pivot = pivot.sort_values("Total", ascending=False)
    pivot = pivot.reset_index().rename(columns={"team_name": "Team"})
    pivot.index = pivot.index + 1

    st.caption(f"Showing **{stat_label}** per gameweek · {len(pivot)} teams")
    st.dataframe(pivot, use_container_width=True, height=700)

    # Cumulative running-total chart, growing gameweek by gameweek
    chart_teams = selected_teams if selected_teams else pivot.sort_values("Total", ascending=False)["Team"].head(8).tolist()
    chart_source = pivot.set_index("Team")[gw_cols].loc[chart_teams].T
    chart_source = chart_source.cumsum()
    chart_source.index = [int(c[2:]) for c in chart_source.index]
    chart_source.index.name = "GW"

    st.subheader(f"Cumulative {stat_label} by Gameweek")
    if not selected_teams:
        st.caption("Showing top 8 teams by total — use the Team filter to compare specific teams.")
    st.line_chart(chart_source)


def render_compare():
    st.title("Compare Players")

    df = load_data()
    bootstrap = load_bootstrap()
    ownership_lookup = {p["id"]: float(p["selected_by_percent"]) for p in bootstrap["elements"]}

    all_names = sorted(df["name"].unique())

    st.sidebar.header("Players")
    preferred_defaults = ["Rayan Cherki", "Antoine Semenyo", "Phil Foden"]
    default_players = [p for p in preferred_defaults if p in all_names]
    if not default_players:
        default_players = all_names[:2] if len(all_names) >= 2 else all_names
    selected_players = st.sidebar.multiselect(
        "Select players to compare", all_names, default=default_players, key="compare_player_select"
    )

    st.sidebar.header("Stats")
    per_90 = st.sidebar.checkbox("Show per 90 minutes", value=False, key="compare_per90")
    selected_stats = st.sidebar.multiselect(
        "Stats to include",
        list(STAT_OPTIONS.keys()),
        default=COMPARE_DEFAULT_STATS,
        key="compare_stat_select",
    )

    chart_stat_label = st.sidebar.selectbox(
        "Stat to chart per GW", list(STAT_OPTIONS.keys()), index=0, key="compare_chart_stat"
    )

    if len(selected_players) < 2:
        st.info("Pick at least 2 players in the sidebar to compare.")
        return

    if not selected_stats:
        st.info("Pick at least 1 stat in the sidebar to compare.")
        return

    player_df = df[df["name"].isin(selected_players)]

    # Basic info row (position, team, price, ownership) from each player's latest GW entry
    latest = player_df.sort_values("GW").groupby("name").last().reset_index()
    latest["price"] = latest["value"] / 10
    latest["ownership"] = latest["element"].map(ownership_lookup).fillna(0)
    info_table = latest.set_index("name")[["position", "team", "price", "ownership"]].T
    info_table = info_table[selected_players]
    info_table.index = ["Position", "Team", "Price (£m)", "Ownership %"]

    st.subheader("Overview")
    st.dataframe(info_table, use_container_width=True)

    # Totals table: rows = stats, columns = players
    minutes_by_player = player_df.groupby("name")["minutes"].sum()
    totals = {}
    for label in selected_stats:
        col = STAT_OPTIONS[label]
        raw_totals = player_df.groupby("name")[col].sum()
        if per_90 and label != "Minutes":
            nineties = (minutes_by_player / 90).replace(0, pd.NA)
            totals[label] = (raw_totals / nineties).round(2).fillna(0)
        else:
            totals[label] = raw_totals
    totals_df = pd.DataFrame(totals).T
    totals_df = totals_df[selected_players]

    st.subheader("Season Totals" if not per_90 else "Per 90 Minutes")
    st.dataframe(totals_df, use_container_width=True)

    # Per-GW chart for the selected stat
    chart_col = STAT_OPTIONS[chart_stat_label]
    chart_stat_pivot = player_df.pivot_table(
        index="GW", columns="name", values=chart_col, aggfunc="sum", fill_value=0
    )
    if per_90 and chart_stat_label != "Minutes":
        chart_minutes_pivot = player_df.pivot_table(
            index="GW", columns="name", values="minutes", aggfunc="sum", fill_value=0
        )
        nineties_pivot = (chart_minutes_pivot / 90).replace(0, pd.NA)
        chart_data = (chart_stat_pivot / nineties_pivot).fillna(0)
    else:
        chart_data = chart_stat_pivot
    chart_data = chart_data[selected_players]

    st.subheader(f"{chart_stat_label} per Gameweek" + (" (per 90)" if per_90 and chart_stat_label != "Minutes" else ""))
    st.line_chart(chart_data)


def render_understat():
    st.title("Understat — Shot & xG Data")
    st.caption("Season totals from Understat.com — shots, non-penalty xG, key passes.")

    try:
        df = load_understat()
    except ImportError:
        st.error(
            "This page needs the `understatapi` package. Install it with:\n\n"
            "`pip install understatapi`\n\nthen rerun the app."
        )
        return
    except Exception as e:
        st.error(f"Couldn't load Understat data: {e}")
        return

    if df.empty or "player_name" not in df.columns:
        st.info("No Understat data returned yet for this season.")
        return

    all_teams = sorted(df["team_title"].unique())
    all_players = sorted(df["player_name"].unique())

    st.sidebar.header("Filters")
    selected_teams = st.sidebar.multiselect("Team", all_teams, default=[], key="understat_team_filter")
    selected_players = st.sidebar.multiselect("Player", all_players, default=[], key="understat_player_filter")

    st.sidebar.header("Stat & Sort")
    per_90 = st.sidebar.checkbox("Show per 90 minutes", value=False, key="understat_per90")
    sort_label = st.sidebar.selectbox(
        "Sort by", list(UNDERSTAT_STAT_OPTIONS.keys()), index=0, key="understat_sort_select"
    )
    sort_desc = st.sidebar.checkbox("Descending", value=True, key="understat_sort_desc")

    view_df = df if not selected_teams else df[df["team_title"].isin(selected_teams)]
    if selected_players:
        view_df = view_df[view_df["player_name"].isin(selected_players)]
    view_df = view_df.copy()

    display_cols = {}
    for label, col in UNDERSTAT_STAT_OPTIONS.items():
        if per_90 and label != "Minutes":
            nineties = (view_df["time"] / 90).replace(0, pd.NA)
            values = (view_df[col] / nineties).fillna(0)
        else:
            values = view_df[col]
        if label in UNDERSTAT_DECIMAL_STATS or per_90:
            values = values.round(2)
        display_cols[label] = values

    result = pd.DataFrame(display_cols)
    result.insert(0, "Player", view_df["player_name"].values)
    result.insert(1, "Team", view_df["team_title"].values)

    sort_col = sort_label
    result = result.sort_values(sort_col, ascending=not sort_desc).reset_index(drop=True)
    result.index = result.index + 1

    st.caption(f"Showing **{len(result)} players**" + (" · per 90 minutes" if per_90 else ""))
    st.dataframe(result, use_container_width=True, height=700)


def main():
    page = st.radio(
        "Page",
        ["📊 Players", "🏟️ Teams", "🆚 Compare", "🎯 Understat", "📅 GW Summary"],
        horizontal=True,
        label_visibility="collapsed",
        key="page_select",
    )
    st.divider()

    if page == "📊 Players":
        render_player_explorer()
    elif page == "🏟️ Teams":
        render_team_stats()
    elif page == "🆚 Compare":
        render_compare()
    elif page == "🎯 Understat":
        render_understat()
    else:
        render_gw_summary()


if __name__ == "__main__":
    main()
