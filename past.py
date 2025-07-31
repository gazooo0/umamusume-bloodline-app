import pandas as pd
import datetime
import requests
import re
import gspread
import unicodedata
import time
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup

# 定数定義
SCHEDULE_CSV_PATH = 'jra_2025_keibabook_schedule.csv'
UMAMUSUME_BLOODLINE_CSV = 'umamusume.csv'
SPREADSHEET_ID = '1wMkpbOvqveVBkJSR85mpZcnKThYSEmusmsl710SaRKw'
SHEET_NAME = 'cache'
HEADERS = {"User-Agent": "Mozilla/5.0"}

def connect_to_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def get_place_code(place_name):
    place_dict = {
        '札幌': '01', '函館': '02', '福島': '03', '新潟': '04',
        '東京': '05', '中山': '06', '中京': '07', '京都': '08', '阪神': '09', '小倉': '10'
    }
    return place_dict.get(place_name, '00')

def generate_race_ids_between(start_date, end_date):
    start_date = pd.Timestamp(start_date)
    end_date = pd.Timestamp(end_date)

    df = pd.read_csv(SCHEDULE_CSV_PATH)
    df["日付"] = pd.to_datetime(df["年"].astype(str) + "-" + df["月日(曜日)"], errors='coerce')
    df = df[df["日付"].notnull()]
    df = df[df['日付'].between(start_date, end_date)]  

    race_ids = []
    for _, row in df.iterrows():
        year = f"{int(row['年']):04d}"
        place_code = get_place_code(row['競馬場'])
        kai = f"{int(row['開催回']):02d}"
        nichi = f"{int(row['日目']):02d}"
        for race_num in range(1, 13):
            num = f"{race_num:02d}"
            race_id = f"{year}{place_code}{kai}{nichi}{num}"
            race_ids.append(race_id)
    return race_ids

def get_past_31_days_race_ids():
    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=31)
    end_date = today
    return generate_race_ids_between(start_date, end_date)

def get_horse_links(race_id):
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    res = requests.get(url, headers=HEADERS)
    res.encoding = "EUC-JP"
    soup = BeautifulSoup(res.text, "html.parser")
    horse_links = {}
    tables = soup.find_all("table", class_="RaceTable01")
    for table in tables:
        for a in table.find_all("a", href=True):
            if "/horse/" in a["href"]:
                name = a.get_text(strip=True)
                full_url = "https://db.netkeiba.com" + a["href"]
                if len(name) >= 2 and name not in horse_links:
                    horse_links[name] = full_url
    return horse_links

def get_pedigree_with_positions(horse_url, position_labels):
    horse_id = horse_url.rstrip("/").split("/")[-1]
    ped_url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    res = requests.get(ped_url, headers=HEADERS)
    res.encoding = "EUC-JP"
    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.find("table", class_="blood_table")
    if not table:
        return {}
    names = {}
    td_list = table.find_all("td")
    for i, td in enumerate(td_list[:len(position_labels)]):
        label = position_labels[i]
        a = td.find("a")
        if a and a.text.strip():
            names[label] = a.text.strip()
    return names

def match_umamusume(pedigree_dict, image_dict, keyword_set):
    matched_blocks = []
    for pos, name in pedigree_dict.items():
        key = unicodedata.normalize("NFKC", name).strip().lower()
        if key in keyword_set:
            img_url = image_dict.get(name, "")
            label = pos
            if img_url:
                block = f"""
<div style='display: flex; align-items: center; margin-bottom: 8px;'>
  <img src="{img_url}" width="80" style="margin-right: 12px; border-radius: 4px;">
  <div style="line-height: 1;">
    <div style="font-size: 0.9em; font-weight: bold;">{label}</div>
    <div style="font-size: 0.95em;">{name}</div>
  </div>
</div>
"""
                matched_blocks.append(block)
    return matched_blocks

def generate_position_labels():
    def dfs(pos, depth, max_depth):
        if depth > max_depth:
            return []
        result = [pos]
        result += dfs(pos + "父", depth + 1, max_depth)
        result += dfs(pos + "母", depth + 1, max_depth)
        return result
    return dfs("", 0, 5)[1:]

def delete_old_entries(ws, race_id):
    all_data = ws.get_all_values()
    header = all_data[0]
    data = all_data[1:]
    race_id_col = header.index("race_id")
    rows_to_delete = [i + 2 for i, row in enumerate(data) if row[race_id_col] == race_id]
    for i in reversed(rows_to_delete):
        ws.delete_rows(i)
    time.sleep(3)

def main():
    ws = connect_to_gspread()
    bloodline_df = pd.read_csv(UMAMUSUME_BLOODLINE_CSV)
    keyword_set = set(bloodline_df['kettou'].dropna().str.lower().str.strip())
    image_dict = dict(zip(bloodline_df['kettou'], bloodline_df['url']))
    position_labels = generate_position_labels()

    race_ids = get_past_31_days_race_ids()

    for race_id in race_ids:
        print(f"\n🏇 race_id: {race_id}")
        horse_links = get_horse_links(race_id)
        results = []
        for horse_name, horse_url in horse_links.items():
            try:
                pedigree = get_pedigree_with_positions(horse_url, position_labels)
                matched_html_blocks = match_umamusume(pedigree, image_dict, keyword_set)
                if matched_html_blocks:
                    html_result = '<br>'.join(matched_html_blocks)
                    row = [horse_name, len(matched_html_blocks), html_result, race_id]
                else:
                    row = [horse_name, 0, '該当なし', race_id]
                results.append(row)
            except Exception as e:
                print(f"⚠️ {horse_name} error: {e}")
            time.sleep(1.5)

        # race_id 単位でまとめて書き込み
        for row in results:
            ws.append_row(row)
            print(f"✅ {row[0]} 登録完了")
        time.sleep(2)

        # race_id 単位で重複削除
        delete_old_entries(ws, race_id)

if __name__ == '__main__':
    main()
