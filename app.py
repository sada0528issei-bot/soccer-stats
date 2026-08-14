import streamlit as st
import pandas as pd

# アプリのタイトル
st.title("出場時間ランキング・データベース")

# リーグ選択のプルダウン
league = st.selectbox("リーグを選択してください", ["1部", "2部", "3部"])

# 選択されたリーグのCSVを読み込む
filename = f"playing_time_ranking_{league}.csv"

try:
    # データの読み込み
    df = pd.read_csv(filename)
    
    # 大学名で絞り込むためのプルダウン
    teams = df['team'].unique()
    selected_team = st.selectbox("大学で絞り込む", ["すべて"] + list(teams))
    
    # 「すべて」以外が選ばれたら、その大学のデータだけに絞る
    if selected_team != "すべて":
        df = df[df['team'] == selected_team]

    # インタラクティブな表として画面に表示
    st.write(f"### {league} - {selected_team}のデータ")
    st.dataframe(df)

except FileNotFoundError:
    st.warning(f"まだ {league} のデータ（{filename}）がありません。先にスクレイピングを実行してください。")