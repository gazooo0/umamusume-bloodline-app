import streamlit as st
import pandas as pd
import unicodedata
import re
import time
from bs4 import BeautifulSoup
import requests

# === 設定 ===
HEADERS = {"User-Agent": "Mozilla/5.0"}

# === ウマ娘血統 ===
umamusume_bloodlines = {
    "アーモンドアイ", "アイネスフウジン", "アグネスタキオン", "アグネスデジタル", "アストンマーチャン",
    "アドマイヤベガ", "アドマイヤボス", "アドマイヤムーン", "イナリワン", "ウイニングチケット",
    "ヴィルシーナ", "ウオッカ", "エアグルーヴ", "エイシンフラッシュ", "エイシンヒカリ", "エイシンワシントン",
    "エルコンドルパサー", "オグリキャップ", "カレンチャン", "カワカミプリンセス", "カワヒメ", "カワヒメ", "キングカメハメハ",
    "グラスワンダー", "ケイエスミラクル", "ゴールドシップ", "サイレンススズカ", "サクラバクシンオー", "サトノクラウン",
    "サトノダイヤモンド", "シーキングザパール", "シンボリクリスエス", "シンボリルドルフ", "スイープトウショウ", "スペシャルウィーク",
    "セイウンスカイ", "ゼンノロブロイ", "タイキシャトル", "タニノギムレット", "タップダンスシチー", "ダイワスカーレット",
    "ダイワメジャー", "ダンツフレーム", "チェリーコウマン", "ツインターボ", "テイエムオペラオー", "テイエムプリキュア",
    "ナイスネイチャ", "ナリタタイシン", "ナリタブライアン", "ニシノフラワー", "ニホンピロウイナー", "ネオユニヴァース",
    "ノーザンテースト", "ノースフライト", "ハーツクライ", "バンブーメモリー", "ヒシアマゾン", "ビワハヤヒデ",
    "ファインモーション", "フジキセキ", "フラワーパーク", "ブエナビスタ", "ホッコータルマエ", "マーベラスサンデー",
    "マチカネフクキタル", "マヤノトップガン", "ミスターシービー", "ミホノブルボン", "メイショウドトウ", "メジロアルダン",
    "メジロドーベル", "メジロパーマー", "メジロマックイーン", "ライスシャワー", "ラッキーライラック", "ロイスアンドロイス",
    "ワンダーアキュート"
}
normalized_umamusume = {unicodedata.normalize("NFKC", n).strip().lower() for n in umamusume_bloodlines}

def generate_position_labels():
    def dfs(pos, depth, max_depth):
        if depth > max_depth: return []
        result = [pos]
        result += dfs(pos + "父", depth + 1, max_depth)
        result += dfs(pos + "母", depth + 1, max_depth)
        return result
    return dfs("", 0, 5)[1:]
POSITION_LABELS = generate_position_labels()

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
        label = POSITION_LABELS[i]
        a = td.find("a")
        if a and a.text.strip():
            names[label] = a.text.strip()
    return names

def match_umamusume(pedigree_dict):
    return [f"【{pos}】{name}" for pos, name in pedigree_dict.items()
            if unicodedata.normalize("NFKC", name).strip().lower() in normalized_umamusume]

def analyze_race(race_id):
    horse_links = get_horse_links(race_id)
    st.text(f"🐎 出走馬数: {len(horse_links)}頭")

    result = []
    for idx, (name, link) in enumerate(horse_links.items(), 1):
        with st.spinner(f"{idx}頭目：{name} を照合中..."):
            try:
                pedigree = get_pedigree_with_positions(link)
                matches = match_umamusume(pedigree)
                result.append({
                    "馬名": name,
                    "該当血統数": len(matches),
                    "ウマ娘血統": "\n".join(matches)
                })
            except Exception as e:
                result.append({
                    "馬名": name,
                    "該当血統数": "取得失敗",
                    "ウマ娘血統": str(e)
                })
            time.sleep(1.5)
    return result

# === UI ===
st.title("🏇ウマ娘血統サーチ")
st.markdown("### （最新1か月間対応）")

schedule_df = pd.read_csv("jra_2025_keibabook_schedule.csv")

# ✅ 日付整形の修正ポイント（ここ）
schedule_df["日付"] = pd.to_datetime(
    schedule_df["年"].astype(str) + "/" + schedule_df["月日(曜日)"].str.extract(r"(\d{2}/\d{2})")[0],
    format="%Y/%m/%d"
)

today = pd.Timestamp.today()
past_31 = today - pd.Timedelta(days=31)
schedule_df = schedule_df[schedule_df["日付"].between(past_31, today)]

# 📅 日付選択（最新が上）
dates = sorted(schedule_df["日付"].dt.strftime("%Y-%m-%d").unique(), reverse=True)
st.markdown("### 📅 競馬開催日を選択")
selected_date = st.selectbox("（過去31日まで遡れます。）", dates)
data_filtered = schedule_df[schedule_df["日付"].dt.strftime("%Y-%m-%d") == selected_date]

# 🏇 競馬場選択（ボタン形式）
st.markdown("### 🏟️ 競馬場を選択。")
place_codes = {"札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
               "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10"}
available_places = sorted(data_filtered["競馬場"].unique())
cols = st.columns(5)
if "place" not in st.session_state:
    st.session_state.place = None
for i, p in enumerate(available_places):
    if cols[i % 5].button(p):
        st.session_state.place = p
place = st.session_state.place
if not place:
    st.stop()

# 🏁 レース番号を選択（プルダウン形式）
st.markdown("### 🏁 レース番号を選択。")
race_num_int = st.selectbox("レース番号を選んでください", list(range(1, 13)), format_func=lambda x: f"{x}R")

if not race_num_int:
    st.stop()

selected_row = data_filtered[data_filtered["競馬場"] == place].iloc[0]
jj = place_codes[place]
kk = f"{int(selected_row['開催回']):02d}"
dd = f"{int(selected_row['日目']):02d}"
race_id = f"{selected_row['年']}{jj}{kk}{dd}{race_num_int:02d}"
st.markdown(f"🔢 **race_id**: `{race_id}`")

# 実行ボタン
if st.button("🏇 ウマ娘血統のお馬さんサーチ開始！"):
    with st.spinner("照合中..."):
        results = analyze_race(race_id)
        st.success("照合完了！")

        if not results:
            st.warning("出走馬が見つかりませんでした。")
        else:
            st.markdown("### 🧬 ウマ娘血統サーチ結果")
            for idx, row in enumerate(results):
                st.markdown(f"""
<div style='font-size:20px; font-weight:bold;'>{idx+1}. {row['馬名']}</div>

該当血統数：{row['該当血統数']}  
{row['ウマ娘血統']}
""", unsafe_allow_html=True)
                if idx < len(results) - 1:
                    st.markdown("<hr style='border:1px solid #ccc;'>", unsafe_allow_html=True)
