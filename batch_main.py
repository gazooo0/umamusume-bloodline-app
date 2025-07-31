import pandas as pd
import datetime
import requests
import re
import gspread
import unicodedata
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup

SCHEDULE_CSV_PATH = 'jra_2025_keibabook_schedule.csv'
UMAMUSUME_BLOODLINE_CSV = 'umamusume.csv'
SPREADSHEET_ID = '1wMkpbOvqveVBkJSR85mpZcnKThYSEmusmsl710SaRKw'
SHEET_NAME = 'cache'

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Google Sheets 接続
def connect_to_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('service_account.json', scope)
    gc = gspread.authorize(credentials)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# 開催地コード取得
def get_place_code(place_name):
    place_dict = {
        '札幌': '01', '函館': '02', '福島': '03', '新潟': '04',
        '東京': '05', '中山': '06', '中京': '07', '京都': '08', '阪神': '09', '小倉': '10'
    }
    return place_dict.get(place_name, '00')

# 開催日から7日間分のrace_id生成
def generate_future_race_ids(base_date):
    df = pd.read_csv(SCHEDULE_CSV_PATH)

    print("📝 CSV読み込み成功。先頭5行:\n", df.head())

    # 日付列を構築して変換
    df['日付'] = pd.to_datetime(df['年'].astype(str) + '/' + df['月日(曜日)'].str.extract(r'(\d+/\d+)')[0], errors='coerce')
    print("📆 日付変換後の先頭:\n", df[['年', '月日(曜日)', '日付']].head())

    df = df[df['日付'].notnull()]

    # 型を揃えて比較
    start_date = pd.to_datetime(base_date)
    end_date = pd.to_datetime(base_date + datetime.timedelta(days=6))
    df = df[df['日付'].between(start_date, end_date)]

    race_ids = []
    for _, row in df.iterrows():
        year = f"{int(row['年']):04d}"
        place_code = get_place_code(row['競馬場'])
        kai = f"{int(row['開催回']):02d}"
        nichi = f"{int(row['日目']):02d}"
        for race_num in range(1, 13):
            num = f"{race_num:02d}"
            # YYYYJJKKDDNN 形式の12桁
            race_id = f"{year}{place_code}{kai}{nichi}{num}"
            race_ids.append(race_id)

    print(f"📅 対象race_id数: {len(race_ids)}")
    return race_ids

# netkeibaから出走馬の血統ページリンクを取得
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

# 血統ページから5代血統を取得
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

# メイン処理
def main():
    today = datetime.date.today()
    print(f"🔁 実行日: {today}")

    race_ids = generate_future_race_ids(today)
    print(f"📌 処理対象のrace_id: {race_ids[:5]} ...")

    bloodline_df = pd.read_csv(UMAMUSUME_BLOODLINE_CSV)
    bloodline_keywords = set(bloodline_df['kettou'].dropna().tolist())
    print(f"🧬 照合対象ウマ娘血統数: {len(bloodline_keywords)}")

    ws = connect_to_gspread()
    print("✅ Google Sheets 接続成功")

    for race_id in race_ids:
        print(f"🔍 処理中: {race_id}")
        horse_links = get_horse_links(race_id)
        print(f"🐎 出走馬数（血統リンク取得）: {len(horse_links)}")

        for link in horse_links:
            horse_name = link
            horse_url = horse_links[link]
        try:
            names_dict = get_pedigree_with_positions(horse_url, position_labels=[
                "父", "母", "母父", "父母", "父父", "母母", "母母父", "母父母"
            ])
        except Exception as e:
            print(f"⚠️ 血統取得エラー: {horse_url} → {e}")
            continue

        matches = [name for name in names_dict.values() if name in bloodline_keywords]
        if matches:
            row = [horse_name, len(matches), ', '.join(matches), race_id]
            ws.append_row(row)
            print(f"✅ 登録: {row}")

if __name__ == '__main__':
    main()
