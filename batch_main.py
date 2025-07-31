import pandas as pd
import datetime
import requests
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup

SCHEDULE_CSV_PATH = 'jra_2025_keibabook_schedule.csv'
UMAMUSUME_BLOODLINE_CSV = 'umamusume.csv'
SPREADSHEET_ID = '1wMkpbOvqveVBkJSR85mpZcnKThYSEmusmsl710SaRKw'
SHEET_NAME = 'cache'

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
    df = df[df['日付'].between(base_date, base_date + datetime.timedelta(days=6))]

    race_ids = []
    for _, row in df.iterrows():
        year = f"{int(row['年']):04d}"
        place_code = get_place_code(row['競馬場'])
        kai = f"{int(row['開催回']):02d}"
        nichi = f"{int(row['日目']):02d}"
        for race_num in range(1, 13):
            num = f"{race_num:02d}"
            # 正しいフォーマット YYYYJJKKDDNN（12桁）
            race_id = f"{year}{place_code}{kai}{nichi}{num}"
            race_ids.append(race_id)

    print(f"📅 対象race_id数: {len(race_ids)}")
    return race_ids

# netkeibaから出走馬の血統ページリンクを取得
def get_horse_links(race_id):
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, 'html.parser')
    links = soup.select('a[href*="/horse/"]')
    horse_links = list(set([l['href'] for l in links if '/horse/' in l['href']]))
    return horse_links

# 血統ページから5代血統を取得
def get_pedigree_names(horse_url):
    url = f"https://db.netkeiba.com{horse_url}ped/"
    res = requests.get(url)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, 'html.parser')
    return [td.text.strip() for td in soup.select('table.blood_table td') if td.text.strip()]

# メイン処理
def main():
    today = datetime.date.today()
    print(f"🔁 実行日: {today}")

    race_ids = generate_future_race_ids(today)
    print(f"📌 処理対象のrace_id: {race_ids[:5]} ...")

    bloodline_df = pd.read_csv(UMAMUSUME_BLOODLINE_CSV)
    bloodline_keywords = set(bloodline_df['血統名'].dropna().tolist())
    print(f"🧬 照合対象ウマ娘血統数: {len(bloodline_keywords)}")

    ws = connect_to_gspread()
    print("✅ Google Sheets 接続成功")

    for race_id in race_ids:
        print(f"🔍 処理中: {race_id}")
        horse_links = get_horse_links(race_id)
        print(f"🐎 出走馬数（血統リンク取得）: {len(horse_links)}")

        for link in horse_links:
            horse_id = link.split('/')[-2]
            horse_url = f"/horse/{horse_id}/"
            try:
                names = get_pedigree_names(horse_url)
            except Exception as e:
                print(f"⚠️ 血統取得エラー: {horse_url} → {e}")
                continue
            matches = [name for name in names if name in bloodline_keywords]
            if matches:
                horse_name = horse_id  # 馬名取得するなら別途実装
                row = [horse_name, len(matches), ', '.join(matches), race_id]
                ws.append_row(row)
                print(f"✅ 登録: {row}")

if __name__ == '__main__':
    main()
