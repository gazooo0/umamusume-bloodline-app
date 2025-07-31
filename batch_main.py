import pandas as pd
import datetime
import requests
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

def generate_position_labels():
    def dfs(pos, depth, max_depth):
        if depth > max_depth:
            return []
        result = [pos]
        result += dfs(pos + "父", depth + 1, max_depth)
        result += dfs(pos + "母", depth + 1, max_depth)
        return result
    return dfs("", 0, 5)[1:]

POSITION_LABELS = generate_position_labels()

def connect_to_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def get_place_code(place_name):
    place_dict = {
        '札幌': '01', '函館': '02', '福島': '03', '新潟': '04',
        '東京': '05', '中山': '06', '中京': '07', '京都': '08',
        '阪神': '09', '小倉': '10'
    }
    return place_dict.get(place_name, '00')

def generate_future_race_ids(base_date):
    df = pd.read_csv(SCHEDULE_CSV_PATH)
    df['日付'] = pd.to_datetime(df['年'].astype(str) + '/' + df['月日(曜日)'].str.extract(r'(\d+/\d+)')[0], errors='coerce')
    df = df[df['日付'].notnull()]
    df = df[df['日付'].between(base_date, base_date + datetime.timedelta(days=6))]

    race_ids = []
    for _, row in df.iterrows():
        year = f"{int(row['年']):04d}"
        place_code = get_place_code(row['競馬場'])
        kai = f"{int(row['開催回']):02d}"
        nichi = f"{int(row['日目']):02d}"
        for num in range(1, 13):
            race_ids.append(f"{year}{place_code}{kai}{nichi}{num:02d}")
    return race_ids

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
                if len(name) >= 2 and name not in horse_links:
                    horse_links[name] = "https://db.netkeiba.com" + a["href"]
    return horse_links

def get_pedigree_with_positions(horse_url):
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
    for i, td in enumerate(td_list[:len(POSITION_LABELS)]):
        a = td.find("a")
        if a and a.text.strip():
            names[POSITION_LABELS[i]] = a.text.strip()
    return names

def main():
    today = datetime.date.today()
    race_ids = generate_future_race_ids(pd.Timestamp(today))
    bloodline_df = pd.read_csv(UMAMUSUME_BLOODLINE_CSV)
    bloodline_keywords = {unicodedata.normalize("NFKC", k).strip().lower() for k in bloodline_df['kettou'].dropna()}
    ws = connect_to_gspread()

    for race_id in race_ids:
        print(f"📌 処理中: {race_id}")
        horse_links = get_horse_links(race_id)
        print(f"🐎 出走馬数: {len(horse_links)}")

        race_rows = []  # raceごとの書き込みバッファ

        for horse_name, horse_url in horse_links.items():
            try:
                pedigree = get_pedigree_with_positions(horse_url)
            except Exception as e:
                print(f"⚠️ 血統取得エラー: {horse_url} → {e}")
                continue

            matches = []
            for label, name in pedigree.items():
                key = unicodedata.normalize("NFKC", name).strip().lower()
                if key in bloodline_keywords:
                    matches.append(f"{label}：{name}")

            if matches:
                row = [horse_name, len(matches), '<br>'.join(matches), race_id]
                race_rows.append(row)

        if race_rows:
            try:
                ws.append_rows(race_rows)
                print(f"✅ 書き込み完了: {len(race_rows)}件")
            except Exception as e:
                print(f"❌ 書き込みエラー: {e}")

        # 🔁 バッチ遅延（2秒）
        time.sleep(2)

if __name__ == '__main__':
    main()
