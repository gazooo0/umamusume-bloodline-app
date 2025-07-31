import pandas as pd
import datetime
import requests
import re
import gspread
import unicodedata
import time
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup

SCHEDULE_CSV_PATH = 'jra_2025_keibabook_schedule.csv'
UMAMUSUME_BLOODLINE_CSV = 'umamusume.csv'
SPREADSHEET_ID = '1wMkpbOvqveVBkJSR85mpZcnKThYSEmusmsl710SaRKw'
SHEET_NAME = 'cache'
HEADERS = {"User-Agent": "Mozilla/5.0"}

# === Google Sheets 接続 ===
def connect_to_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# === race_idに一致する行を削除 ===
def delete_rows_by_race_id(ws, race_id):
    values = ws.get_all_values()
    rows_to_delete = [i+1 for i, row in enumerate(values) if len(row) >= 4 and row[3] == race_id]
    for i in reversed(rows_to_delete):
        ws.delete_rows(i)
    if rows_to_delete:
        print(f"🗑️ 既存 {race_id} の {len(rows_to_delete)} 行を削除")

# === 開催地コード取得 ===
def get_place_code(place_name):
    place_dict = {
        '札幌': '01', '函館': '02', '福島': '03', '新潟': '04',
        '東京': '05', '中山': '06', '中京': '07', '京都': '08', '阪神': '09', '小倉': '10'
    }
    return place_dict.get(place_name, '00')

# === race_id生成 ===
def generate_future_race_ids(base_date):
    df = pd.read_csv(SCHEDULE_CSV_PATH)
    df['日付'] = pd.to_datetime(df['年'].astype(str) + '/' + df['月日(曜日)'].str.extract(r'(\d+/\d+)')[0], errors='coerce')
    df = df[df['日付'].notnull()]
    start_date = pd.to_datetime(base_date)
    end_date = start_date + pd.Timedelta(days=6)
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

# === 出走馬リンク取得 ===
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

# === 血統情報取得 ===
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

# === 該当血統のHTMLブロック生成 ===
def match_umamusume(pedigree_dict, image_dict, keyword_set):
    matched_blocks = []
    for pos, name in pedigree_dict.items():
        key = unicodedata.normalize("NFKC", name).strip().lower()
        if key in keyword_set:
            img_url = image_dict.get(name, "")
            block = f'''
<div style='display: flex; align-items: center; margin-bottom: 8px;'>
  <img src="{img_url}" width="80" style="margin-right: 12px; border-radius: 4px;">
  <div style="line-height: 1;">
    <div style="font-size: 0.9em; font-weight: bold;">{pos}</div>
    <div style="font-size: 0.95em;">{name}</div>
  </div>
</div>
'''
            matched_blocks.append(block)
    return matched_blocks

# === 血統位置ラベル生成 ===
def generate_position_labels():
    def dfs(pos, depth, max_depth):
        if depth > max_depth:
            return []
        result = [pos]
        result += dfs(pos + "父", depth + 1, max_depth)
        result += dfs(pos + "母", depth + 1, max_depth)
        return result
    return dfs("", 0, 5)[1:]

# === メイン処理 ===
def main():
    today = datetime.date.today()
    race_ids = generate_future_race_ids(today)
    bloodline_df = pd.read_csv(UMAMUSUME_BLOODLINE_CSV)
    keyword_set = set(bloodline_df['kettou'].dropna().str.lower().str.strip())
    image_dict = dict(zip(bloodline_df['kettou'], bloodline_df['url']))
    ws = connect_to_gspread()
    position_labels = generate_position_labels()

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
                continue
            time.sleep(1.5)  # 個別遅延

        if results:
            ws.append_rows(results)
            print(f"✅ {len(results)}頭 登録完了（{race_id}）")
            time.sleep(3)  # レース間の間引き
            delete_rows_by_race_id(ws, race_id)

if __name__ == '__main__':
    main()
