# -*- coding: utf-8 -*-
"""
東京都大学サッカー連盟 出場時間・スタッツ 自動集計スクリプト (未来日スキップ高速化対応版)
====================================================================
・学年データの自動紐づけ
・前後半シュート数、合計シュート数の取得
・得点(ゴール数)の自動紐づけ
・ゴール率(決定率)の自動計算
・未実施・未来日試合の自動スキップ機能
"""

import csv
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ============================================================
# 設定
# ============================================================

TEAM_LIST_URL = "https://www.f-togakuren.com/league-teams"

TARGET_LEAGUES = {
    "1部": "https://www.f-togakuren.com/match?fy=2026&srys=698c64e733ddad528a1e0452",
    "2部": "https://www.f-togakuren.com/match?fy=2026&srys=6996c3afc7491b5ed023c7e2",
    "3部": "https://www.f-togakuren.com/match?fy=2026&srys=6996c3ff51e0ba56891423b2"
}

MATCH_ROW_SELECTOR = "div.columns.is-multiline.is-gapless.is-mobile:has(.match-result)"
HEADLESS = True


# ============================================================
# 名簿データ(学年)の事前取得ロジック
# ============================================================

def build_player_grade_db(browser):
    print("\n=== 名簿データ(学年)の事前取得を開始します ===")
    page = browser.new_page()
    page.goto(TEAM_LIST_URL, wait_until="networkidle")
    
    team_links = page.locator("a[href*='/teams/']").all()
    teams_info = []
    for link in team_links:
        url = link.get_attribute("href")
        name = link.inner_text().strip()
        if url and url.startswith("/"):
            url = "https://www.f-togakuren.com" + url
        if name and url:
            teams_info.append({"name": name, "url": url})
    
    unique_teams = []
    seen_urls = set()
    for t in teams_info:
        if t["url"] not in seen_urls:
            seen_urls.add(t["url"])
            unique_teams.append(t)

    player_db = {}
    for idx, team in enumerate(unique_teams):
        print(f"  [{idx+1}/{len(unique_teams)}] {team['name']} の名簿を取得中...")
        page.goto(team["url"], wait_until="networkidle")
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        tables = soup.select("table.members-table")
        if not tables:
            continue
            
        player_table = tables[0]
        rows = player_table.select("tbody tr")
        
        clean_team = team["name"].replace("大学", "").replace("大", "").strip()
        
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                number = cols[0].get_text(strip=True)
                raw_name = cols[2].get_text(strip=True)
                clean_name = raw_name.replace(" ", "").replace(" ", "")
                grade = cols[4].get_text(strip=True)
                
                key = (clean_team, number, clean_name)
                player_db[key] = grade
                
    page.close()
    print(f"=== 名簿データの取得が完了しました（計 {len(player_db)} 選手） ===\n")
    return player_db


# ============================================================
# 日付判定ロジック（未来日・未定のスキップ判定）
# ============================================================

def is_match_finished(row_element) -> bool:
    """
    試合行のHTMLから日付を抽出し、未来の日付または「未定」であればFalseを返す
    """
    text = row_element.inner_text()
    
    # 「未定」の文字が含まれている場合はまだ実施されていないと判断
    if "未定" in text:
        return False
        
    # 日付の形式（例: "8/14(金)" や "2026/8/14" など）を探すための簡易パース
    # ここでは、行テキスト内に含まれる日付情報を解析する
    try:
        # 現在の日付（2026年8月15日を基準）を今天として取得
        today = datetime(2026, 8, 15)
        
        # テキスト中から "M/D" のようなパターンを探して比較する（例: "8/15" など）
        import re
        match = re.search(r'(\d{1,2})/(\d{1,2})', text)
        if match:
            m = int(match.group(1))
            d = int(match.group(2))
            # 年は2026年として日付オブジェクトを作成
            match_date = datetime(2026, m, d)
            
            # 試合日が今日より未来の場合はスキップ対象とする
            if match_date > today:
                return False
    except Exception:
        pass
        
    return True


# ============================================================
# 出場時間・スタッツの取得ロジック
# ============================================================

def parse_time(time_str: str, entry_type: str) -> int:
    time_str = time_str.replace("⁺", "+").replace("＋", "+")

    if time_str == "HT" or time_str == "HF":
        base = 45
    elif "+" in time_str:
        base = 90
    else:
        base = int(time_str)

    if entry_type == "out":
        return base
    else:
        return max(90 - base, 0)


def parse_team_order_table(table_div):
    rows = table_div.find_all("div", recursive=False)
    left, right = [], []
    for row in rows:
        cols = row.find_all("div", recursive=False)
        if len(cols) != 2:
            continue
        for side, col in zip((left, right), cols):
            cells = col.find_all("div", recursive=False)
            if len(cells) < 3:
                continue
            pos = cells[0].get_text(strip=True)
            if pos not in ("GK", "DF", "MF", "FW"):
                continue

            name_cell = cells[1]
            num_span = name_cell.find("span")
            number = num_span.get_text(strip=True) if num_span else ""
            full_text = name_cell.get_text(strip=True)
            name = full_text[len(number):].strip() if number and full_text.startswith(number) else full_text

            change_span = cells[2].find("span", class_="change")
            change_mark, change_time = None, None
            if change_span:
                mark_tag = change_span.find("span", class_="has-text-danger")
                change_mark = mark_tag.get_text(strip=True) if mark_tag else None
                time_spans = change_span.find_all("span")
                change_time = time_spans[-1].get_text(strip=True) if time_spans else None

            shoot_spans = col.find_all("span", class_="shoot")
            shoot_1st = 0
            shoot_2nd = 0
            
            if len(shoot_spans) >= 2:
                s1 = shoot_spans[0].get_text(strip=True)
                s2 = shoot_spans[1].get_text(strip=True)
                shoot_1st = int(s1) if s1.isdigit() else 0
                shoot_2nd = int(s2) if s2.isdigit() else 0
            
            shoot_total = shoot_1st + shoot_2nd

            side.append({
                "number": number,
                "name": name,
                "position": pos,
                "change_mark": change_mark,
                "change_time": change_time,
                "shoot_1st": shoot_1st,
                "shoot_2nd": shoot_2nd,
                "shoot_total": shoot_total,
            })
    return left, right


def build_playing_time(starters_pair, bench_pair):
    results = []
    for team_starters, team_bench in zip(starters_pair, bench_pair):
        team_players = []
        for p in team_starters:
            if p["change_mark"] == "▼" and p["change_time"]:
                minutes = parse_time(p["change_time"], "out")
            else:
                minutes = 90
            team_players.append({**p, "minutes_played": minutes, "status": "先発"})
        for p in team_bench:
            if p["change_mark"] == "▲" and p["change_time"]:
                minutes = parse_time(p["change_time"], "in")
            else:
                minutes = 0
            team_players.append({**p, "minutes_played": minutes, "status": "控え"})
        results.append(team_players)
    return results


def parse_game_detail(html: str):
    soup = BeautifulSoup(html, "html.parser")
    team_names = [d.get_text(strip=True) for d in soup.select(".team-name-score .team-name")]
    tables = soup.select(".team-order-table")
    if len(team_names) != 2 or len(tables) < 2:
        return None

    goal_counts = {}
    goal_section = soup.find(string=lambda text: text and "〔得点〕" in text)
    if goal_section:
        scoring_div = goal_section.parent.parent
        scorers = scoring_div.find_all("div", class_="player")
        for scorer in scorers:
            name = scorer.get_text(strip=True)
            if name != "OG":
                clean_name = name.replace(" ", "").replace(" ", "")
                if clean_name not in goal_counts:
                    goal_counts[clean_name] = 0
                goal_counts[clean_name] += 1

    starter_left, starter_right = parse_team_order_table(tables[0])
    bench_left, bench_right = parse_team_order_table(tables[1])
    teams = build_playing_time((starter_left, starter_right), (bench_left, bench_right))

    date_el = soup.select_one(".mx-2")
    match_date = date_el.get_text(strip=True) if date_el else ""

    records = []
    for team_name, players in zip(team_names, teams):
        for p in players:
            clean_name = p["name"].replace(" ", "").replace(" ", "")
            goals = goal_counts.get(clean_name, 0)
            
            shoot_total = p.get("shoot_total", 0)
            if shoot_total > 0:
                goal_rate = round((goals / shoot_total) * 100, 1)
            else:
                goal_rate = 0.0
            
            records.append({
                "date": match_date,
                "team": team_name,
                "number": p["number"],
                "name": p["name"],
                "position": p["position"],
                "minutes_played": p["minutes_played"],
                "status": p["status"],
                "shoot_1st": p.get("shoot_1st", 0),
                "shoot_2nd": p.get("shoot_2nd", 0),
                "shoot_total": shoot_total,
                "goals": goals,
                "goal_rate": goal_rate
            })
    return records


# ============================================================
# ブラウザ自動操作・データマージ
# ============================================================

def close_modal(page):
    try:
        modal = page.locator(".modal.is-active")
        if modal.count() == 0:
            return
        close_btn = modal.locator(".delete")
        if close_btn.count() > 0:
            close_btn.first.click(force=True)
        else:
            page.locator(".modal-background").first.click(force=True)
        modal.wait_for(state="hidden", timeout=5000)
    except Exception:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
    page.wait_for_timeout(200)


def scrape_all_data():
    league_records_dict = {}
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        
        player_db = build_player_grade_db(browser)
        
        page = browser.new_page()
        for league_name, target_url in TARGET_LEAGUES.items():
            all_records = []
            print(f"\n=== 【{league_name}】の試合記録取得を開始します ===")
            page.goto(target_url, wait_until="networkidle")
            
            try:
                page.wait_for_selector(".match-result", timeout=15000)
            except Exception:
                print(f"{league_name} の試合が見つかりませんでした。スキップします。")
                continue

            rows = page.locator(MATCH_ROW_SELECTOR)
            count = rows.count()
            print(f"{count} 件の試合カードを検出しました（未実施試合は自動スキップします）")

            for i in range(count):
                row = rows.nth(i)
                
                # 未実施または未来の試合であれば開かずにスキップ
                if not is_match_finished(row):
                    print(f"  [{i + 1}/{count}] 未実施または未来の試合のためスキップします")
                    continue

                row.scroll_into_view_if_needed()
                row.click()
                page.wait_for_timeout(400)

                detail = page.locator(".game-detail")
                try:
                    detail.wait_for(state="visible", timeout=5000)
                except Exception:
                    print(f"  [{i + 1}/{count}] 詳細が開けませんでした。スキップします")
                    close_modal(page)
                    continue

                html = detail.evaluate("el => el.outerHTML")
                records = parse_game_detail(html)
                if records:
                    all_records.extend(records)
                    print(f"  [{i + 1}/{count}] 取得完了({len(records)}名分)")
                else:
                    print(f"  [{i + 1}/{count}] 想定外の構造だったためスキップしました(要確認)")

                close_modal(page)
            
            league_records_dict[league_name] = all_records

        browser.close()

    return league_records_dict, player_db


# ============================================================
# 集計 & CSV出力
# ============================================================

def save_results(league_records_dict, player_db):
    for league_name, all_records in league_records_dict.items():
        if not all_records:
            continue
            
        for r in all_records:
            clean_team = r["team"].replace("大学", "").replace("大", "").strip()
            clean_name = r["name"].replace(" ", "").replace(" ", "")
            key = (clean_team, r["number"], clean_name)
            
            if key in player_db:
                r["grade"] = player_db[key]
            else:
                matched_grade = "不明"
                for db_key, db_grade in player_db.items():
                    if db_key[1] == r["number"] and db_key[2] == clean_name:
                        matched_grade = db_grade
                        break
                r["grade"] = matched_grade
                
        raw_filename = f"raw_playing_time_{league_name}.csv"
        ranking_filename = f"playing_time_ranking_{league_name}.csv"
        
        with open(raw_filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=[
                    "date", "team", "number", "name", "grade", "position", 
                    "minutes_played", "status", "shoot_1st", "shoot_2nd", 
                    "shoot_total", "goals", "goal_rate"
                ]
            )
            writer.writeheader()
            writer.writerows(all_records)

        summary = {}
        for r in all_records:
            key = (r["team"], r["number"], r["name"])
            if key not in summary:
                summary[key] = {
                    "team": r["team"], 
                    "number": r["number"], 
                    "name": r["name"],
                    "grade": r["grade"],
                    "total_minutes": 0, 
                    "appearances": 0,
                    "total_shoot_1st": 0,
                    "total_shoot_2nd": 0,
                    "total_shoot": 0,
                    "total_goals": 0
                }
            summary[key]["total_minutes"] += r["minutes_played"]
            summary[key]["total_shoot_1st"] += r["shoot_1st"]
            summary[key]["total_shoot_2nd"] += r["shoot_2nd"]
            summary[key]["total_shoot"] += r["shoot_total"]
            summary[key]["total_goals"] += r["goals"]
            
            if r["minutes_played"] > 0:
                summary[key]["appearances"] += 1

        for k in summary:
            if summary[k]["total_shoot"] > 0:
                summary[k]["goal_rate"] = round((summary[k]["total_goals"] / summary[k]["total_shoot"]) * 100, 1)
            else:
                summary[k]["goal_rate"] = 0.0

        ranking = sorted(summary.values(), key=lambda x: -x["total_minutes"])

        with open(ranking_filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f, fieldnames=[
                    "team", "number", "name", "grade", "total_minutes", 
                    "appearances", "total_shoot_1st", "total_shoot_2nd", 
                    "total_shoot", "total_goals", "goal_rate"
                ]
            )
            writer.writeheader()
            writer.writerows(ranking)

        print(f"\n完了: {raw_filename} / {ranking_filename} に書き出しました")
        print(f"{league_name} は合計 {len(all_records)} 件の選手×試合データを集計しました")


if __name__ == "__main__":
    records_dict, database = scrape_all_data()
    save_results(records_dict, database)