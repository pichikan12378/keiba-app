import streamlit as st
import streamlit.components.v1 as components
import itertools
import datetime
import json
import math
import uuid
from pathlib import Path

# ページ基本設定（スマホ表示向け最適化）
st.set_page_config(
    page_title="共同馬券・複数レース集約アプリ",
    page_icon="🏇",
    layout="centered"
)

# ============================================================
# 【修正1・3】UI調整
#   ・プルダウン(selectbox/multiselect)をタップしても文字入力できないようにする
#   ・Streamlit標準の英語メッセージを日本語に置き換える
# ============================================================
st.markdown(
    """
    <style>
    /* プルダウン内の検索入力欄を「文字入力できない」状態にする
       - pointer-events:none でタップが親のコントロールに透過し、
         入力欄自体はフォーカスされない（＝キーボードが出ない）
       - クリックはプルダウンの開閉として機能する */
    div[data-baseweb="select"] input {
        pointer-events: none !important;
        caret-color: transparent !important;
        user-select: none !important;
        -webkit-user-select: none !important;
        width: 0 !important;
        min-width: 0 !important;
        opacity: 0 !important;
    }
    /* コントロール全体をタップ領域にし、指カーソルにする */
    div[data-baseweb="select"] > div {
        cursor: pointer !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

def apply_ui_patch():
    """プルダウンを読み取り専用にし、英語表記を日本語へ置換する。"""
    components.html(
        """
        <script>
        const doc = window.parent.document;
        // 完全一致で置換するもの
        const DICT = {
            "Choose an option": "タップして選択",
            "Choose options": "タップして選択",
            "No options to select.": "選択できる項目がありません",
            "No options.": "選択できる項目がありません",
            "No results": "該当する項目がありません",
            "No results found": "該当する項目がありません",
            "You have reached the maximum number of allowed selections.":
                "選択できる上限に達しました",
            "Press Enter to apply": "",
            "Press Enter to submit form": "",
            "Deselect all": "すべて解除",
            "Clear all": "すべて解除"
        };

        // 数字などが変化する英語メッセージ用（正規表現で置換）
        const RULES = [
            [/^You can only select 1 option\\..*$/i,
             "選択できるのは1頭までです。変更する場合は選択済みの馬番を外してください。"],
            [/^You can only select (\\d+) options?\\..*$/i,
             "選択できるのは$1頭までです。変更する場合は選択済みの馬番を外してください。"],
            [/^You have reached the maximum number of allowed selections\\.?.*$/i,
             "選択できる上限に達しました。変更する場合は選択済みの馬番を外してください。"]
        ];

        function fixText(raw) {
            const t = raw.trim();
            if (!t) return null;
            if (t in DICT && DICT[t] !== t) return DICT[t];
            for (const [re, rep] of RULES) {
                if (re.test(t)) return t.replace(re, rep);
            }
            return null;
        }

        function patch() {
            // 1) 入力欄を読み取り専用にしてスマホのキーボードを出さない
            doc.querySelectorAll('div[data-baseweb="select"] input').forEach(function (el) {
                el.readOnly = true;
                el.setAttribute('readonly', 'readonly');
                el.setAttribute('inputmode', 'none');
                el.setAttribute('autocomplete', 'off');
                el.setAttribute('tabindex', '-1');
            });

            // 2) 画面上のテキストノードを走査して英語メッセージを日本語に置換
            const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null);
            const nodes = [];
            while (walker.nextNode()) nodes.push(walker.currentNode);
            nodes.forEach(function (node) {
                const jp = fixText(node.nodeValue);
                if (jp !== null) node.nodeValue = jp;
            });
        }

        // 3) 万一フォーカスされても文字が入らないよう、キー入力を無効化
        //    （↑↓・Enter・Esc・Tab などの操作系キーだけ通す）
        const ALLOW_KEYS = [
            'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
            'Enter', 'Escape', 'Tab', 'Backspace', 'Delete'
        ];
        function isSelectInput(el) {
            return el && el.tagName === 'INPUT' && el.closest &&
                   el.closest('div[data-baseweb="select"]') !== null;
        }
        ['keydown', 'keypress', 'beforeinput', 'input', 'paste', 'compositionstart'
        ].forEach(function (type) {
            doc.addEventListener(type, function (e) {
                if (!isSelectInput(e.target)) return;
                if (type === 'keydown' || type === 'keypress') {
                    if (ALLOW_KEYS.indexOf(e.key) !== -1) return;
                }
                e.preventDefault();
                e.stopPropagation();
                if (e.target.value) e.target.value = '';
            }, true);
        });

        patch();
        new MutationObserver(patch).observe(doc.body, { childList: true, subtree: true });
        setInterval(patch, 300);
        </script>
        """,
        height=0,
    )

# ============================================================
# 合言葉による簡易アクセス制限
# ============================================================
PASSWORD = st.secrets.get("app_password", "")

if PASSWORD and not st.session_state.get("authed"):
    st.title("🏇 共同馬券アプリ")
    pw = st.text_input("合言葉を入力してください", type="password")
    if pw == PASSWORD:
        st.session_state.authed = True
        st.rerun()
    elif pw:
        st.error("合言葉が違います。")
    st.stop()

# 競馬場マスターデータ
JYO_CHUO = ["東京", "中山", "阪神", "京都", "札幌", "函館", "福島", "新潟", "中京", "小倉"]
JYO_CHIHO = ["帯広ば", "門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢",
             "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"]

# 賭け式マスター: (必要頭数, 着順を区別するか)
TICKETS = {
    "馬連": (2, False),
    "馬単": (2, True),
    "3連複": (3, False),
    "3連単": (3, True),
}

DATA_FILE = Path("races_data.json")

# ============================================================
# 保存・読込
# ============================================================
def load_races():
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []

def save_races():
    try:
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(st.session_state.races, f, ensure_ascii=False, indent=2)
    except OSError as e:
        st.error(f"データを保存できませんでした: {e}")

# ============================================================
# セッション状態の初期化
# ============================================================
if "races" not in st.session_state:
    st.session_state.races = load_races()

for key, default in {
    "current_page": "main",
    "active_race_id": None,
    "active_member_id": None,
}.items():
    st.session_state.setdefault(key, default)

# ============================================================
# 共通ヘルパー
# ============================================================
def find_race(race_id):
    return next((r for r in st.session_state.races if r["id"] == race_id), None)

def get_active_race():
    race = find_race(st.session_state.active_race_id)
    if race is None:
        st.session_state.active_race_id = None
        st.session_state.active_member_id = None
        st.session_state.current_page = "main"
        st.rerun()
    return race

def goto(page, race_id=None, member_id=None):
    st.session_state.current_page = page
    if race_id is not None:
        st.session_state.active_race_id = race_id
    if member_id is not None:
        st.session_state.active_member_id = member_id
    st.rerun()

def count_points(n, ticket_type):
    r, ordered = TICKETS[ticket_type]
    if n < r:
        return 0
    return math.perm(n, r) if ordered else math.comb(n, r)

def build_combinations(horses, ticket_type):
    r, ordered = TICKETS[ticket_type]
    if len(horses) < r:
        return []
    maker = itertools.permutations if ordered else itertools.combinations
    return list(maker(horses, r))

def get_formation_combos(ticket_type, l1, l2, l3=None):
    combos = []
    l3 = l3 or []
    if ticket_type in ["馬連", "馬単"]:
        for a in l1:
            for b in l2:
                if a != b:
                    if ticket_type == "馬連":
                        combos.append(tuple(sorted((a, b))))
                    else:
                        combos.append((a, b))
    elif ticket_type in ["3連複", "3連単"]:
        for a in l1:
            for b in l2:
                for c in l3:
                    if len({a, b, c}) == 3:
                        if ticket_type == "3連複":
                            combos.append(tuple(sorted((a, b, c))))
                        else:
                            combos.append((a, b, c))
    return sorted(list(set(combos)))

def entered_count(race):
    member_ids = {m["id"] for m in race["members"]}
    return sum(1 for mid in race["choices"] if mid in member_ids)

@st.dialog("⚠️ レースの削除")
def delete_confirm_dialog(race_id, race_title):
    st.write(f"「**{race_title}**」を削除しますか？\n\n入力済みの馬番データもすべて消去されます。")
    c1, c2 = st.columns(2)
    if c1.button("削除する", type="primary", use_container_width=True):
        st.session_state.races = [r for r in st.session_state.races if r["id"] != race_id]
        save_races()
        st.rerun()
    if c2.button("キャンセル", use_container_width=True):
        st.rerun()

# ============================================================
# 画面1: メイン画面（レース一覧）
# ============================================================
if st.session_state.current_page == "main":
    st.title("🏇 共同馬券 メイン画面")
    st.write("複数のレースとメンバーの選択馬を集約し、BOX買いの点数・予算を計算します。")

    if st.button("➕ 新しいレースを設定する", type="primary", use_container_width=True):
        goto("create")

    st.divider()
    st.subheader("📋 設定済みレース一覧")

    if not st.session_state.races:
        st.info("登録されたレースはまだありません。上のボタンから作成してください。")
    else:
        for race in list(st.session_state.races):
            rid = race["id"]
            input_count = entered_count(race)
            total_people = len(race["members"])
            is_completed = (total_people > 0 and input_count == total_people)

            with st.container(border=True):
                # 本命ありの場合はタイトル横にアイコンを表示
                fav_icon = "🎯(本命あり)" if race.get("use_favorite") else ""
                st.markdown(
                    f"**{race['title']}** {fav_icon}\n\n"
                    f"（全{race['total_horses']}頭立 / 各{race['target_count']}頭選択）"
                )

                if is_completed:
                    st.markdown(f"ステータス: :green[全メンバー入力完了 ({input_count}/{total_people}人)]")
                else:
                    st.markdown(f"ステータス: :orange[入力中 ({input_count}/{total_people}人)]")

                col_a, col_b, col_c = st.columns(3)

                if is_completed:
                    if col_a.button("📊 集約結果", key=f"res_{rid}", use_container_width=True):
                        goto("result", race_id=rid)
                else:
                    if col_a.button("✏️ 馬番入力", key=f"inp_{rid}", use_container_width=True):
                        goto("member_select", race_id=rid)

                if col_b.button("👤 参加者", key=f"edit_{rid}", use_container_width=True):
                    goto("member_select", race_id=rid)

                if col_c.button("🗑️ 削除", key=f"del_{rid}", use_container_width=True):
                    delete_confirm_dialog(rid, race["title"])

# ============================================================
# 画面2: 新規レース作成画面
# ============================================================
elif st.session_state.current_page == "create":
    st.title("⚙️ レース設定")

    today = datetime.date.today()
    selected_date = st.date_input("開催日付", value=today, format="YYYY/MM/DD")

    cat = st.selectbox("開催区分", ["中央", "地方"])
    jyo_list = JYO_CHUO if cat == "中央" else JYO_CHIHO
    jyo = st.selectbox("競馬場", jyo_list)
    r_num = st.selectbox("レース番号", [f"{i}R" for i in range(1, 13)], index=10)

    total_horses = st.selectbox("出走頭数", list(range(4, 19)), index=14)
    target_count = st.selectbox("1人あたりの選択頭数", [2, 3, 4, 5], index=0)

    # 🌟 本命指定の有無を設定（【修正2】初期値はチェックなし）
    st.markdown("##### 🎯 本命の設定")
    use_favorite = st.checkbox("各メンバーに「本命馬(◎)」を1頭指定させる", value=False)

    st.markdown("##### 👤 参加メンバー")
    members_input = st.text_input("参加者名（カンマ区切り）", value="Aさん, Bさん")
    members = [m.strip() for m in members_input.replace("、", ",").split(",") if m.strip()]

    if st.button("設定を保存して次へ", type="primary", use_container_width=True):
        if not members:
            st.error("参加者名を1名以上入力してください。")
        elif target_count > total_horses:
            st.error(f"出走{total_horses}頭に対して1人{target_count}頭は選べません。")
        else:
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            date_str = f"{selected_date.month}/{selected_date.day}({weekdays[selected_date.weekday()]})"
            new_race = {
                "id": uuid.uuid4().hex,
                "title": f"{date_str} {jyo} {r_num}",
                "total_horses": total_horses,
                "target_count": target_count,
                "use_favorite": use_favorite,  # 設定を保存
                "members": [{"id": uuid.uuid4().hex, "name": name} for name in members],
                "choices": {},
                "favorites": {},  # 本命馬保存用
            }
            st.session_state.races.append(new_race)
            save_races()
            goto("member_select", race_id=new_race["id"])

    if st.button("← メイン画面に戻る", use_container_width=True):
        goto("main")

    apply_ui_patch()

# ============================================================
# 画面3: 参加者選択画面
# ============================================================
elif st.session_state.current_page == "member_select":
    race = get_active_race()
    st.title("👤 参加者を選択")
    st.write(f"**{race['title']}** （各{race['target_count']}頭選択）")

    for member in race["members"]:
        mid = member["id"]
        is_entered = mid in race["choices"]

        col1, col2 = st.columns([2, 1])
        status = "✅ 入力済み" if is_entered else "⏳ 未入力"
        col1.write(f"**{member['name']}**\n\n{status}")

        if col2.button("修正する" if is_entered else "入力する",
                       key=f"mem_{mid}", use_container_width=True):
            goto("input_choices", member_id=mid)

    st.divider()
    if entered_count(race) == len(race["members"]):
        if st.button("🎉 全員の集約・BOX計算を見る", type="primary", use_container_width=True):
            goto("result")

    if st.button("← レース一覧に戻る", use_container_width=True):
        goto("main")

# ============================================================
# 画面4: 馬番入力画面（各メンバー）
# ============================================================
elif st.session_state.current_page == "input_choices":
    race = get_active_race()
    member = next(
        (m for m in race["members"] if m["id"] == st.session_state.active_member_id), None
    )
    if member is None:
        goto("member_select")

    target = race["target_count"]
    st.title(f"🏇 {member['name']} さんの馬番入力")
    st.write(f"{race['title']} （{race['total_horses']}頭立から**ちょうど{target}頭**）")

    current_choices = race["choices"].get(member["id"], [])
    horse_options = list(range(1, race["total_horses"] + 1))
    default_horses = [h for h in current_choices if h <= race["total_horses"]]

    # 🌟 プルダウンを使わず、タップで選ぶボタン形式（st.pills）を優先して使用
    if hasattr(st, "pills"):
        selected_horses = st.pills(
            "馬番を選択してください（タップで選択／再タップで解除）",
            options=horse_options,
            selection_mode="multi",
            default=default_horses,
            key=f"pl_{race['id']}_{member['id']}",
        ) or []
    else:
        selected_horses = st.multiselect(
            "馬番を選択してください",
            options=horse_options,
            default=default_horses,
            max_selections=target,
            placeholder="タップして馬番を選択",
            key=f"ms_{race['id']}_{member['id']}",
        )

    if len(selected_horses) == target:
        st.success(f"選択数: {len(selected_horses)} / {target} 頭")
    elif len(selected_horses) > target:
        st.error(f"選択数: {len(selected_horses)} / {target} 頭（{len(selected_horses) - target}頭 多すぎます）")
    else:
        st.warning(f"選択数: {len(selected_horses)} / {target} 頭（あと{target - len(selected_horses)}頭）")

    # 🌟 本命設定がONの場合のみ、本命選択ラジオボタンを表示
    favorite_horse = None
    if race.get("use_favorite", False) and selected_horses:
        st.markdown("##### 🎯 本命馬の選択")
        current_favorite = race.get("favorites", {}).get(member["id"])

        # 以前の本命がまだ選択肢に含まれていればそれをデフォルトに
        if current_favorite in selected_horses:
            default_index = selected_horses.index(current_favorite)
        else:
            default_index = 0

        favorite_horse = st.radio(
            "あなたの本命馬（軸）を1頭選んでください",
            options=selected_horses,
            index=default_index,
            horizontal=True
        )

    if st.button("この内容で保存する", type="primary", use_container_width=True):
        if len(selected_horses) != target:
            st.error(f"ちょうど {target} 頭選択してください。")
        else:
            race["choices"][member["id"]] = sorted(selected_horses)

            # 本命ありの場合はデータも保存
            if race.get("use_favorite", False):
                if "favorites" not in race:
                    race["favorites"] = {}
                race["favorites"][member["id"]] = favorite_horse

            save_races()
            goto("member_select")

    if st.button("← 参加者選択に戻る", use_container_width=True):
        goto("member_select")

    apply_ui_patch()

# ============================================================
# 画面5: 集約＆計算結果画面
# ============================================================
elif st.session_state.current_page == "result":
    race = get_active_race()

    st.title("📊 集約＆買い目計算")
    st.subheader(f"【 {race['title']} 】")

    member_ids = [m["id"] for m in race["members"]]
    all_selected = [h for mid in member_ids for h in race["choices"].get(mid, [])]
    unique_horses = sorted(set(all_selected))
    n = len(unique_horses)

    st.metric("集約対象馬", f"計 {n} 頭")

    counts = {h: all_selected.count(h) for h in unique_horses}
    multi_picked = sorted([h for h, c in counts.items() if c > 1])

    st.info(f"📍 **馬番:** {', '.join(map(str, unique_horses)) if unique_horses else 'なし'}")

    with st.expander("🔍 各人の選択内訳・重複状況", expanded=False):
        st.markdown("**【各人の選択】**")
        for m in race["members"]:
            mid = m["id"]
            picked = sorted(race["choices"].get(mid, []))

            # 本命ありの場合は「◎」をつけて表示
            if race.get("use_favorite", False):
                fav = race.get("favorites", {}).get(mid)
                display_picked = [f"◎{h}" if h == fav else str(h) for h in picked]
                st.write(f"- {m['name']}: {', '.join(display_picked) if display_picked else '未入力'}")
            else:
                st.write(f"- {m['name']}: {picked if picked else '未入力'}")

        st.markdown("**【重複した馬番（軸候補）】**")
        dup_text = [f"{h}番 ({c}人被り)"
                    for h, c in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if c > 1]
        if dup_text:
            st.markdown(f":red[{', '.join(dup_text)}]")
        else:
            st.write("被りなし（全員バラバラの選択です）")

    st.divider()
    st.subheader("⚙️ 買い目計算と予算配分")

    ticket_type = st.selectbox("賭け式", list(TICKETS), index=2, key=f"tk_{race['id']}")
    buy_mode = st.radio("購入方式", ["BOX買い", "フォーメーション"], horizontal=True)

    if buy_mode == "BOX買い":
        st.caption(f"全 {n} 頭のBOX買いを計算します。")
        combos = build_combinations(unique_horses, ticket_type)
        total_points = len(combos)
    else:
        st.markdown("##### 🛠 フォーメーション設定")

        # 本命あり/なしで1列目の初期値を切り替え
        if race.get("use_favorite", False):
            st.caption("💡 *初期値として「誰かの本命馬(◎)」を1列目にセットしています。*")
            all_favorites = [race.get("favorites", {}).get(mid) for mid in member_ids]
            unique_favorites = sorted(list(set([f for f in all_favorites if f is not None])))
            default_core = unique_favorites if unique_favorites else unique_horses
        else:
            st.caption("💡 *初期値として「複数人が被って選んだ馬」を1列目にセットしています。*")
            default_core = multi_picked if multi_picked else unique_horses

        col_f1, col_f2 = st.columns(2)
        f1 = col_f1.multiselect("1列目", unique_horses, default=default_core,
                                placeholder="タップして選択")
        f2 = col_f2.multiselect("2列目", unique_horses, default=unique_horses,
                                placeholder="タップして選択")

        f3 = []
        if ticket_type in ["3連複", "3連単"]:
            f3 = st.multiselect("3列目", unique_horses, default=unique_horses,
                                placeholder="タップして選択")

        combos = get_formation_combos(ticket_type, f1, f2, f3)
        total_points = len(combos)

    total_budget = st.number_input("総予算 (円)", min_value=100, value=2000, step=100, key=f"bg_{race['id']}")

    col1, col2 = st.columns(2)
    col1.metric("購入点数", f"{total_points:,}点")

    if total_points == 0:
        need = TICKETS[ticket_type][0]
        col2.metric("1点あたり", "—")
        if buy_mode == "BOX買い":
            st.warning(f"⚠️ {ticket_type}には{need}頭以上必要です（現在{n}頭）。")
        else:
            st.warning("⚠️ 買い目が0点です。各列に正しく馬番を配置してください。")
    else:
        per_ticket_amount = (total_budget // total_points // 100) * 100
        actual_total = per_ticket_amount * total_points

        if per_ticket_amount >= 100:
            col2.metric("1点あたり", f"{per_ticket_amount:,}円")
            st.success(f"💡 **購入合計:** {actual_total:,}円 （残り: {total_budget - actual_total:,}円）")
            with st.expander(f"📋 {ticket_type} 買い目・金額一覧（全{total_points}点）"):
                st.dataframe(
                    [{"買い目": " - ".join(map(str, c)),
                      "購入金額": f"{per_ticket_amount:,}円"} for c in combos],
                    use_container_width=True, hide_index=True,
                )
        else:
            col2.metric("1点あたり", "予算不足", delta="-不足", delta_color="inverse")
            need_budget = total_points * 100
            st.error(
                f"⚠️ 全{total_points:,}点あり、"
                f"全点100円で最低 **{need_budget:,}円** 必要です（予算: {total_budget:,}円 / 不足: {need_budget - total_budget:,}円）。\n\n"
                f"予算を増やすか、フォーメーションで点数を絞ってください。"
            )

    st.divider()
    if st.button("← レース一覧に戻る", use_container_width=True):
        goto("main")

    apply_ui_patch()
