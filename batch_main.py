import os
import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
import base64

# ===============================
# GitHub Actions 対応: Secretsから認証情報復元
# ===============================
if "GOOGLE_CREDS_JSON" in os.environ:
    decoded = base64.b64decode(os.environ["GOOGLE_CREDS_JSON"])
    with open("service_account.json", "wb") as f:
        f.write(decoded)

# ===============================
# 設定
# ===============================
SCHEDULE_CSV_PATH = "data/jra_2025_keibabook_schedule.csv"
UMAMUSUME_CSV_PATH = "data/umamusume.csv"
GOOGLE_SHEET_NAME = "umamusume_cache"
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

# ===============================
# Google Sheets クライアント取得
# ===============================
def get_gspread_client():
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )
    gc = gspread.authorize(credentials)
    return gc

# ===============================
# race_id生成（未来7日間）
# ===============================
def generate_future_race_ids(base_date):
    df = pd.read_csv(SCHEDULE_CSV_PATH)
    df['日付'] = pd.to_datetime(df['月日(曜日)'], format='%m月%d日', errors='coerce')
    df['日付'] = df['日付'].apply(lambda d: d.replace(year=base_date.year) if pd.notnull(d) else d)
    df = df[df['日付'].notnull()]
    df = df[df['日付'].between(base_date, base_date + datetime.timedelta(days=6))]

    race_ids = []
    for _, row in df.iterrows():
        date_str = row['日付'].strftime('%Y%m%d')
        place_code = get_place_code(row['競馬場'])
        kai = f"{int(row['開催回']):02d}"
        nichi = f"{int(row['日目']):02d}"
        for race_num in range(1, 13):
            num = f"{race_num:02d}"
            race_id = f"{date_str}{place_code}{kai}{nichi}{num}"
            race_ids.append(race_id)
    return race_ids

def get_place_code(place_name):
    place_dict = {
        "札幌": "01", "函館": "02", "福島": "03", "新潟": "04",
        "東京": "05", "中山": "06", "中京": "07", "京都": "08",
        "阪神": "09", "小倉": "10"
    }
    return place_dict.get(place_name, "00")

# ===============================
# 出走馬と血統情報を取得
# ===============================
def scrape_pedigree_info(race_id):
    url = f"https://db.netkeiba.com/race/{race_id}/"
    print(f"🌐 アクセス中: {url}")
    res = requests.get(url)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")
    horse_links = soup.select("td.horse a")

    horses = []
    for a in horse_links:
        name = a.text.strip()
        href = a.get("href")
        if not href:
            continue
        horse_id = href.split("/")[-2]
        horse_url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
        horses.append({
            "name": name,
            "url": horse_url
        })
    print(f"🐎 出走馬数: {len(horses)}")
    return horses

# ===============================
# 血統照合（ウマ娘と比較）
# ===============================
def check_umamusume_bloodline(horse):
    res = requests.get(horse["url"])
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.select_one("table.db_parent_table")
    if not table:
        return {"該当数": 0, "該当箇所": "", "name": horse["name"]}

    with open(UMAMUSUME_CSV_PATH, encoding='utf-8') as f:
        umamusume_list = [line.strip() for line in f if line.strip()]

    matches = []
    for td in table.select("td"):
        if td.text.strip() in umamusume_list:
            matches.append(f"<div>{td.text.strip()}</div>")

    if matches:
        print(f"🧬 {horse['name']} 該当: {len(matches)} → {matches}")
    return {
        "name": horse["name"],
        "該当数": len(matches),
        "該当箇所": "".join(matches)
    }

# ===============================
# Google Sheetsへ保存
# ===============================
def save_to_sheets(results):
    gc = get_gspread_client()
    sh = gc.open(GOOGLE_SHEET_NAME)
    try:
        worksheet = sh.worksheet("cache")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sh.add_worksheet(title="cache", rows="1000", cols="10")

    existing = worksheet.get_all_values()
    headers = ["馬名", "該当数", "該当箇所", "race_id"]
    if not existing:
        worksheet.append_row(headers)

    for row in results:
        worksheet.append_row([
            row["馬名"],
            row["該当数"],
            row["該当箇所"],
            row["race_id"]
        ])
    print(f"✅ Google Sheets へ {len(results)} 件保存しました")

# ===============================
# メイン処理
# ===============================
def main():
    today = pd.Timestamp.today().normalize()
    race_ids = generate_future_race_ids(today)
    print(f"📅 対象race_id数: {len(race_ids)}")

    for race_id in race_ids:
        print(f"\n🔍 処理中: {race_id}")
        try:
            horses = scrape_pedigree_info(race_id)
            results = []
            for horse in horses:
                result = check_umamusume_bloodline(horse)
                if result["該当数"] > 0:
                    results.append({
                        "馬名": horse["name"],
                        "該当数": result["該当数"],
                        "該当箇所": result["該当箇所"],
                        "race_id": race_id
                    })
            if results:
                print(f"📋 {race_id} に該当馬あり → {len(results)}件")
                save_to_sheets(results)
            else:
                print(f"⚠️ {race_id} は該当馬なし")
        except Exception as e:
            print(f"❌ エラー発生: {e}")

if __name__ == "__main__":
    main()
