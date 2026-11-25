import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime, time, timedelta

st.set_page_config(
    page_title="꾸브라꼬 매장 영업현황",
    page_icon="🍗",
    layout="wide",
)

# -----------------------------
# 공통 함수
# -----------------------------
REQUIRED_COLUMNS = [
    "영업일", "매장코드", "매장명", "지사명", "지역",
    "개점시간", "마감시간", "총운영시간"
]

def to_datetime(series):
    """엑셀 날짜/시간 값을 datetime으로 통일."""
    return pd.to_datetime(series, errors="coerce")

def circular_average_time(series):
    """
    자정을 넘는 마감시간도 고려한 평균 시각.
    예: 23:50과 00:10의 평균을 정오가 아닌 00:00에 가깝게 계산.
    """
    values = pd.to_datetime(series, errors="coerce").dropna()
    if values.empty:
        return None

    seconds = (
        values.dt.hour * 3600
        + values.dt.minute * 60
        + values.dt.second
    ).to_numpy()

    angles = 2 * np.pi * seconds / 86400
    sin_mean = np.sin(angles).mean()
    cos_mean = np.cos(angles).mean()

    angle = np.arctan2(sin_mean, cos_mean)
    if angle < 0:
        angle += 2 * np.pi

    avg_seconds = int(round(angle * 86400 / (2 * np.pi))) % 86400
    return time(
        hour=avg_seconds // 3600,
        minute=(avg_seconds % 3600) // 60,
    )

def format_time(value):
    return value.strftime("%H:%M") if value is not None else "-"

def format_duration(hours):
    if pd.isna(hours):
        return "-"
    total_minutes = int(round(float(hours) * 60))
    return f"{total_minutes // 60}시간 {total_minutes % 60:02d}분"

def prepare_data(raw):
    # 컬럼명 공백 제거
    raw.columns = [str(c).strip() for c in raw.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(
            "필수 컬럼을 찾을 수 없습니다: " + ", ".join(missing)
        )

    df = raw[REQUIRED_COLUMNS].copy()
    df["영업일"] = to_datetime(df["영업일"]).dt.normalize()
    df["개점시간"] = to_datetime(df["개점시간"])
    df["마감시간"] = to_datetime(df["마감시간"])

    # 날짜 또는 시간 데이터가 없는 행은 집계에서 제외
    df = df.dropna(subset=["영업일", "매장명", "개점시간", "마감시간"]).copy()

    # 원본 시간 차이를 기준으로 운영시간 계산
    duration = (df["마감시간"] - df["개점시간"]).dt.total_seconds() / 3600
    # 날짜 정보가 잘못 입력된 경우를 대비한 보정
    duration = duration.where(duration >= 0, duration + 24)
    df["운영시간_시간"] = duration

    df["요일"] = df["영업일"].dt.day_name().map({
        "Monday": "월", "Tuesday": "화", "Wednesday": "수",
        "Thursday": "목", "Friday": "금", "Saturday": "토",
        "Sunday": "일"
    })
    df["개점시각"] = df["개점시간"].dt.strftime("%H:%M")
    df["마감시각"] = df["마감시간"].dt.strftime("%H:%M")
    df["운영시간"] = df["운영시간_시간"].apply(format_duration)
    return df

def make_summary(data, start_date, end_date):
    period_days = (end_date - start_date).days + 1
    rows = []

    for (store_code, store_name), group in data.groupby(
        ["매장코드", "매장명"], dropna=False
    ):
        operating_days = group["영업일"].nunique()
        missing_days = max(period_days - operating_days, 0)

        rows.append({
            "매장코드": str(store_code),
            "매장명": store_name,
            "지사명": group["지사명"].mode().iloc[0] if not group["지사명"].mode().empty else "-",
            "지역": group["지역"].mode().iloc[0] if not group["지역"].mode().empty else "-",
            "영업일수": operating_days,
            "휴무/미기록일": missing_days,
            "평균 개점시간": format_time(circular_average_time(group["개점시간"])),
            "평균 마감시간": format_time(circular_average_time(group["마감시간"])),
            "평균 운영시간": format_duration(group["운영시간_시간"].mean()),
        })

    return pd.DataFrame(rows).sort_values(["지역", "매장명"]).reset_index(drop=True)


# -----------------------------
# 화면
# -----------------------------
st.title("🍗 꾸브라꼬 매장 영업현황")
st.caption("매장별 영업일, 휴무/미기록일, 평균 개점·마감시간 및 일자별 상세 내역")

uploaded_file = st.sidebar.file_uploader(
    "개점·마감현황 엑셀 파일 업로드",
    type=["xlsx", "xls"]
)

if uploaded_file is None:
    st.info("왼쪽 메뉴에서 개점·마감현황 엑셀 파일을 업로드해 주세요.")
    st.markdown(
        """
        **사용 방법**
        1. `개점_마감현황` 시트가 포함된 엑셀 파일을 업로드합니다.
        2. 조회 기간과 지역을 선택합니다.
        3. 전체 현황에서 매장을 선택하거나 상세 조회 메뉴에서 매장을 선택합니다.
        """
    )
    st.stop()

try:
    excel = pd.ExcelFile(uploaded_file)
    preferred_sheet = "개점_마감현황"
    sheet_name = preferred_sheet if preferred_sheet in excel.sheet_names else excel.sheet_names[0]
    raw = pd.read_excel(uploaded_file, sheet_name=sheet_name)
    df = prepare_data(raw)
except Exception as e:
    st.error(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {e}")
    st.stop()

if df.empty:
    st.warning("분석할 수 있는 영업 데이터가 없습니다.")
    st.stop()

data_min = df["영업일"].min().date()
data_max = df["영업일"].max().date()

st.sidebar.subheader("조회 조건")
date_range = st.sidebar.date_input(
    "조회 기간",
    value=(data_min, data_max),
    min_value=data_min,
    max_value=data_max,
)

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
elif isinstance(date_range, (tuple, list)) and len(date_range) == 1:
    start_date = end_date = date_range[0]
else:
    start_date = end_date = date_range

if start_date > end_date:
    st.error("조회 시작일이 종료일보다 늦습니다.")
    st.stop()

regions = sorted(df["지역"].dropna().astype(str).unique().tolist())
selected_regions = st.sidebar.multiselect(
    "지역 선택",
    options=regions,
    default=regions,
)

filtered = df[
    (df["영업일"].dt.date >= start_date)
    & (df["영업일"].dt.date <= end_date)
    & (df["지역"].astype(str).isin(selected_regions))
].copy()

if filtered.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
    st.stop()

summary = make_summary(filtered, start_date, end_date)
period_days = (end_date - start_date).days + 1

tab_overview, tab_detail = st.tabs(["📊 전체 매장 요약", "🔎 매장별 상세 조회"])

with tab_overview:
    st.subheader("전체 매장 영업현황")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("조회 매장 수", f"{len(summary):,}개")
    c2.metric("조회 기간", f"{period_days:,}일")
    c3.metric("총 영업 기록", f"{len(filtered):,}건")
    c4.metric(
        "매장당 평균 운영시간",
        format_duration(filtered["운영시간_시간"].mean())
    )

    st.markdown("#### 매장별 영업 요약")
    st.caption(
        "휴무/미기록일은 조회 기간 중 해당 매장의 영업 기록이 없는 날짜입니다. "
        "실제 휴무인지 데이터 누락인지는 원본 자료만으로 구분할 수 없습니다."
    )

    # 표의 행을 클릭하면 아래 상세 화면에 해당 매장을 표시
    display_cols = [
        "매장명", "지역", "영업일수", "휴무/미기록일",
        "평균 개점시간", "평균 마감시간", "평균 운영시간"
    ]
    event = st.dataframe(
        summary[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="summary_table",
    )

    selected_store = None
    try:
        selected_rows = event.selection.rows
        if selected_rows:
            selected_store = summary.iloc[selected_rows[0]]["매장명"]
    except Exception:
        pass

    store_options = summary["매장명"].tolist()
    default_index = store_options.index(selected_store) if selected_store in store_options else 0
    chosen_store = st.selectbox(
        "상세 내용을 확인할 매장",
        options=store_options,
        index=default_index,
        key="overview_store_select",
    )

    if st.button("선택 매장 상세 보기", type="primary", key="go_detail"):
        st.session_state["detail_store"] = chosen_store
        st.session_state["open_detail_tab"] = True
        st.info("상단의 '매장별 상세 조회' 탭에서 상세 내용을 확인해 주세요.")

with tab_detail:
    st.subheader("매장별 상세 영업현황")

    all_store_options = summary["매장명"].tolist()
    default_detail = st.session_state.get("detail_store", all_store_options[0])
    if default_detail not in all_store_options:
        default_detail = all_store_options[0]

    detail_store = st.selectbox(
        "매장 선택",
        options=all_store_options,
        index=all_store_options.index(default_detail),
        key="detail_store_select",
    )

    detail = filtered[filtered["매장명"] == detail_store].sort_values("영업일").copy()
    store_summary = summary[summary["매장명"] == detail_store].iloc[0]

    a, b, c, d_col = st.columns(4)
    a.metric("영업일수", f"{int(store_summary['영업일수'])}일")
    b.metric("휴무/미기록일", f"{int(store_summary['휴무/미기록일'])}일")
    c.metric("평균 개점", store_summary["평균 개점시간"])
    d_col.metric("평균 마감", store_summary["평균 마감시간"])

    st.markdown("#### 일자별 영업시간")
    detail_table = detail[[
        "영업일", "요일", "개점시각", "마감시각", "운영시간"
    ]].copy()
    detail_table["영업일"] = detail_table["영업일"].dt.strftime("%Y-%m-%d")
    detail_table.columns = ["영업일", "요일", "개점시간", "마감시간", "총운영시간"]
    st.dataframe(
        detail_table,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 날짜별 영업 기록 달력")
    calendar_start = pd.Timestamp(start_date)
    calendar_end = pd.Timestamp(end_date)
    records_by_day = {
        row["영업일"].date(): row
        for _, row in detail.iterrows()
    }

    calendar_days = pd.date_range(calendar_start, calendar_end, freq="D")
    calendar_rows = []
    for day in calendar_days:
        record = records_by_day.get(day.date())
        if record is None:
            status = "휴무/미기록"
            opening = "-"
            closing = "-"
        else:
            status = "영업"
            opening = record["개점시각"]
            closing = record["마감시각"]

        calendar_rows.append({
            "날짜": day.strftime("%m/%d"),
            "요일": ["월", "화", "수", "목", "금", "토", "일"][day.weekday()],
            "상태": status,
            "개점": opening,
            "마감": closing,
        })

    calendar_df = pd.DataFrame(calendar_rows)
    st.dataframe(calendar_df, use_container_width=True, hide_index=True)

    st.markdown("#### 일별 운영시간 추이")
    chart_data = detail.set_index("영업일")["운영시간_시간"].sort_index()
    st.bar_chart(chart_data, y_label="운영시간(시간)")

    st.download_button(
        "상세 내역 CSV 다운로드",
        data=detail_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
        file_name=f"{detail_store}_영업현황.csv",
        mime="text/csv",
    )

st.sidebar.divider()
st.sidebar.caption(
    "※ 평균 개점·마감시간은 시각의 원형 평균으로 계산하며, "
    "평균 운영시간은 개점부터 마감까지의 시간 차이를 기준으로 계산합니다."
)
