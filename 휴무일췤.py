from datetime import time
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="꾸브라꼬 매장 영업현황",
    page_icon="🍗",
    layout="wide",
)

REQUIRED_COLUMNS = [
    "영업일",
    "매장코드",
    "매장명",
    "지사명",
    "지역",
    "개점시간",
    "마감시간",
    "총운영시간",
]

AREA_ORDER = ["수도권", "영남권", "호남권", "제주권", "기타"]


# =========================================================
# 데이터 처리 함수
# =========================================================
def parse_datetime(series):
  """엑셀의 날짜/시간 값을 datetime으로 변환."""
  return pd.to_datetime(series, errors="coerce")


def time_minutes(value):
  """Timestamp 또는 time을 자정 기준 분으로 변환."""
  if pd.isna(value):
    return np.nan
  return int(value.hour) * 60 + int(value.minute) + int(value.second) / 60


def circular_average_time(series):
  """24시간 시계 기준 원형 평균.

  23:50과 00:10의 평균이 12:00으로 계산되는 문제를 방지.
  """
  values = pd.to_datetime(series, errors="coerce").dropna()
  if values.empty:
    return None

  minutes = (
      values.dt.hour * 60 + values.dt.minute + values.dt.second / 60
  ).to_numpy()

  angles = 2 * np.pi * minutes / 1440
  sin_mean = np.sin(angles).mean()
  cos_mean = np.cos(angles).mean()

  angle = np.arctan2(sin_mean, cos_mean)
  if angle < 0:
    angle += 2 * np.pi

  avg_minutes = int(round(angle * 1440 / (2 * np.pi))) % 1440
  return time(hour=avg_minutes // 60, minute=avg_minutes % 60)


def circular_difference_minutes(actual, baseline):
  """실제 시각 - 평균 시각.

  결과 범위는 -720분~+720분.
  예: 평균 00:30, 실제 23:30 -> -60분.
  """
  if (
      actual is None
      or baseline is None
      or pd.isna(actual)
      or pd.isna(baseline)
  ):
    return np.nan
  diff = time_minutes(actual) - time_minutes(baseline)
  return (diff + 720) % 1440 - 720


def format_time(value):
  return value.strftime("%H:%M") if value is not None else "-"


def format_duration(hours):
  if pd.isna(hours):
    return "-"
  total_minutes = int(round(float(hours) * 60))
  sign = "-" if total_minutes < 0 else ""
  total_minutes = abs(total_minutes)
  return f"{sign}{total_minutes // 60}시간 {total_minutes % 60:02d}분"


def format_deviation(minutes):
  if pd.isna(minutes):
    return "-"
  rounded = int(round(minutes))
  if rounded == 0:
    return "평균과 동일"
  direction = "늦음" if rounded > 0 else "빠름"
  value = abs(rounded)
  return f"{value // 60}시간 {value % 60:02d}분 {direction}"


def map_region_to_area(region_val):
  """지역 값을 요청된 권역(수도권, 영남권, 호남권)으로 매핑."""
  r = "" if pd.isna(region_val) else str(region_val).strip()
  if r in [
      "중부권",
      "강원권",
      "경기권",
      "수도권",
      "서울",
      "경기",
      "인천",
      "대전",
      "충청(충남/충북)",
      "충남",
      "충북",
  ]:
    return "수도권"
  if r in ["경상", "경북", "부산", "경상(경남/경북)", "경남", "울산", "대구"]:
    return "영남권"
  if r in ["전남", "전북", "광주", "전라(전남/전북)"]:
    return "호남권"
  if r == "제주":
    return "제주권"
  return "기타"


def prepare_data(raw):
  raw = raw.copy()
  raw.columns = [str(c).strip() for c in raw.columns]

  missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
  if missing:
    raise ValueError("필수 컬럼을 찾을 수 없습니다: " + ", ".join(missing))

  df = raw[REQUIRED_COLUMNS].copy()
  df["영업일"] = parse_datetime(df["영업일"]).dt.normalize()
  df["개점시간"] = parse_datetime(df["개점시간"])
  df["마감시간"] = parse_datetime(df["마감시간"])

  # 매장코드는 문자열로 통일해 엑셀 숫자/문자 혼용에 대응
  df["매장코드"] = (
      df["매장코드"].astype("string").str.replace(r"\.0$", "", regex=True)
  )
  df["매장명"] = df["매장명"].astype("string").str.strip()
  df["지역"] = df["지역"].astype("string").str.strip().fillna("기타")
  df["권역"] = df["지역"].apply(map_region_to_area)

  # 날짜와 매장 식별정보가 없는 행만 제외.
  # 개점/마감시간이 비어 있는 행은 기록 누락으로 남겨 달력에서 확인.
  df = df.dropna(subset=["영업일", "매장코드", "매장명"]).copy()

  # 영업일 기준으로 다음 날 마감하는 경우도 실제 datetime 차이를 사용
  df["운영시간_시간"] = (df["마감시간"] - df["개점시간"]).dt.total_seconds() / 3600

  # 날짜값이 역전된 행은 24시간을 더해 임의 보정하지 않고 데이터 오류로 제외
  invalid_duration = df["운영시간_시간"] < 0
  df.loc[invalid_duration, "운영시간_시간"] = np.nan

  weekday_map = {
      "Monday": "월",
      "Tuesday": "화",
      "Wednesday": "수",
      "Thursday": "목",
      "Friday": "금",
      "Saturday": "토",
      "Sunday": "일",
  }
  df["요일"] = df["영업일"].dt.day_name().map(weekday_map)
  df["개점시각"] = df["개점시간"].dt.strftime("%H:%M").fillna("-")
  df["마감시각"] = df["마감시간"].dt.strftime("%H:%M").fillna("-")
  df["운영시간"] = df["운영시간_시간"].apply(format_duration)

  # 매장명이 같더라도 매장코드가 다르면 별도 매장으로 구분
  df["매장키"] = df["매장코드"].astype(str) + " | " + df["매장명"].astype(str)
  return df


def add_anomaly_flags(data, threshold_minutes):
  """매장별 평균 개점/마감 시각과 비교해 이상 영업 패턴 표시.

  - 평균보다 threshold 이상 늦게 개점 - 평균보다 threshold 이상 일찍 마감
  최소 3일의 정상적인 시간 기록이 있는 매장만 기준 평균 산출.
  """
  result = data.copy()
  result["개점편차_분"] = np.nan
  result["마감편차_분"] = np.nan
  result["이상유형"] = ""
  result["이상상세"] = ""

  for store_key, indexes in result.groupby("매장키").groups.items():
    store_rows = result.loc[indexes]
    valid = store_rows.dropna(subset=["개점시간", "마감시간"])

    if len(valid) < 3:
      continue

    avg_open = circular_average_time(valid["개점시간"])
    avg_close = circular_average_time(valid["마감시간"])

    for idx, row in valid.iterrows():
      open_diff = circular_difference_minutes(row["개점시간"], avg_open)
      close_diff = circular_difference_minutes(row["마감시간"], avg_close)

      result.at[idx, "개점편차_분"] = open_diff
      result.at[idx, "마감편차_분"] = close_diff

      flags = []
      details = []

      if open_diff >= threshold_minutes:
        flags.append("늦은 개점")
        details.append(f"평균보다 {format_deviation(open_diff)}")

      if close_diff <= -threshold_minutes:
        flags.append("이른 마감")
        details.append(f"평균보다 {format_deviation(close_diff)}")

      result.at[idx, "이상유형"] = ", ".join(flags)
      result.at[idx, "이상상세"] = " / ".join(details)

  # 24시간을 초과하는 운영시간은 입력 오류 또는 장시간 영업 가능성이 있어 별도 확인
  long_duration_rows = result.index[result["운영시간_시간"] > 24]
  for idx in long_duration_rows:
    existing_type = result.at[idx, "이상유형"]
    existing_detail = result.at[idx, "이상상세"]

    result.at[idx, "이상유형"] = (
        f"{existing_type}, 운영시간 24시간 초과"
        if existing_type
        else "운영시간 24시간 초과"
    )
    result.at[idx, "이상상세"] = (
        f"{existing_detail} / 총운영시간 24시간 초과"
        if existing_detail
        else "총운영시간 24시간 초과"
    )

  result["개점편차"] = result["개점편차_분"].apply(format_deviation)
  result["마감편차"] = result["마감편차_분"].apply(format_deviation)
  result["이상 여부"] = np.where(result["이상유형"] != "", "확인 필요", "-")
  return result


def make_summary(data, start_date, end_date):
  period_days = (end_date - start_date).days + 1
  rows = []

  for store_key, group in data.groupby("매장키", dropna=False):
    valid = group.dropna(subset=["개점시간", "마감시간"])
    operating_days = valid["영업일"].nunique()
    recorded_days = group["영업일"].nunique()
    missing_days = max(period_days - recorded_days, 0)

    avg_open = circular_average_time(valid["개점시간"])
    avg_close = circular_average_time(valid["마감시간"])

    rows.append({
        "매장키": store_key,
        "매장코드": group["매장코드"].iloc[0],
        "매장명": group["매장명"].iloc[0],
        "지사명": (
            group["지사명"].mode().iloc[0]
            if not group["지사명"].mode().empty
            else "-"
        ),
        "권역": (
            group["권역"].mode().iloc[0]
            if not group["권역"].mode().empty
            else "-"
        ),
        "지역": (
            group["지역"].mode().iloc[0]
            if not group["지역"].mode().empty
            else "-"
        ),
        "영업일수": operating_days,
        "휴무/미기록일": missing_days,
        "평균 개점시간": format_time(avg_open),
        "평균 마감시간": format_time(avg_close),
        "평균 운영시간": format_duration(valid["운영시간_시간"].mean()),
        "이상 영업 건수": int((group["이상유형"] != "").sum()),
        "기록일수": recorded_days,
    })

  return (
      pd.DataFrame(rows)
      .sort_values(["권역", "지역", "매장명"])
      .reset_index(drop=True)
  )


def make_time_by_group(data, group_cols):
  """권역 또는 지역별 평균 개점시간, 평균 마감시간, 평균 운영시간 집계."""
  rows = []
  for keys, group in data.groupby(group_cols, dropna=False):
    if not isinstance(keys, tuple):
      keys = (keys,)
    valid = group.dropna(subset=["개점시간", "마감시간"])
    avg_open = circular_average_time(valid["개점시간"])
    avg_close = circular_average_time(valid["마감시간"])

    row = dict(zip(group_cols, keys))
    row.update({
        "매장수": group["매장키"].nunique(),
        "유효 기록건수": len(valid),
        "평균 개점시간": format_time(avg_open),
        "평균 마감시간": format_time(avg_close),
        "평균 운영시간": format_duration(valid["운영시간_시간"].mean()),
        "_개점_분": time_minutes(avg_open) if avg_open is not None else np.nan,
        "_마감_분": time_minutes(avg_close) if avg_close is not None else np.nan,
    })
    rows.append(row)

  df_out = pd.DataFrame(rows)
  if df_out.empty:
    return df_out
  return df_out.sort_values(group_cols).reset_index(drop=True)


# =========================================================
# 화면 구성
# =========================================================
st.title("🍗 꾸브라꼬 매장 영업현황")
st.caption("매장별·지역별·권역별 영업일, 평균 개점/마감시간 및 이상 영업 패턴 대시보드")

uploaded_file = st.sidebar.file_uploader(
    "개점·마감현황 엑셀 파일 업로드", type=["xlsx", "xls"]
)

if uploaded_file is None:
  st.info("왼쪽 메뉴에서 개점·마감현황 엑셀 파일을 업로드해 주세요.")
  st.markdown(
      """
        **사용 방법**
1. `개점_마감현황` 시트가 포함된 엑셀 파일을 업로드합니다.
2. 조회 기간, 권역 및 지역을 선택합니다.
3. 탭에서 전체 요약, 지역별 평균 개점·마감시간, 매장별 상세, 이상 영업을 확인합니다.
        """
  )
  st.stop()

try:
  excel = pd.ExcelFile(uploaded_file)
  preferred_sheet = "개점_마감현황"
  sheet_name = (
      preferred_sheet if preferred_sheet in excel.sheet_names else excel.sheet_names[0]
  )
  raw = pd.read_excel(uploaded_file, sheet_name=sheet_name)
  df = prepare_data(raw)
except Exception as exc:
  st.error(f"엑셀 파일을 읽는 중 오류가 발생했습니다: {exc}")
  st.stop()

if df.empty:
  st.warning("분석할 수 있는 매장 데이터가 없습니다.")
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

if isinstance(date_range, (tuple, list)):
  if len(date_range) == 2:
    start_date, end_date = date_range
  else:
    start_date = end_date = date_range[0]
else:
  start_date = end_date = date_range

if start_date > end_date:
  st.error("조회 시작일이 종료일보다 늦습니다.")
  st.stop()

available_areas = [a for a in AREA_ORDER if a in df["권역"].unique()] + sorted(
    [a for a in df["권역"].unique() if a not in AREA_ORDER]
)
selected_areas = st.sidebar.multiselect(
    "권역 선택", available_areas, default=available_areas
)

region_candidates = sorted(
    df[df["권역"].isin(selected_areas)]["지역"].dropna().astype(str).unique().tolist()
)
selected_regions = st.sidebar.multiselect(
    "지역 선택", region_candidates, default=region_candidates
)

threshold_hours = st.sidebar.slider(
    "이상 영업 판단 기준",
    min_value=0.5,
    max_value=4.0,
    value=2.0,
    step=0.5,
    help="매장별 평균 개점/마감 시각에서 설정한 시간 이상 차이가 나면 확인 대상으로 표시합니다.",
)
threshold_minutes = int(threshold_hours * 60)

filtered = df[
    (df["영업일"].dt.date >= start_date)
    & (df["영업일"].dt.date <= end_date)
    & (df["권역"].isin(selected_areas))
    & (df["지역"].astype(str).isin(selected_regions))
].copy()

if filtered.empty:
  st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
  st.stop()

filtered = add_anomaly_flags(filtered, threshold_minutes)
summary = make_summary(filtered, start_date, end_date)
period_days = (end_date - start_date).days + 1

tab_overview, tab_region_time, tab_detail, tab_alerts = st.tabs([
    "📊 전체 매장 요약",
    "⏰ 지역별 개점·마감시간",
    "🔎 매장별 상세 조회",
    "🚨 이상 영업 확인",
])


# ---------------------------------------------------------
# 전체 매장 요약
# ---------------------------------------------------------
with tab_overview:
  st.subheader("전체 매장 영업현황")

  c1, c2, c3, c4 = st.columns(4)
  c1.metric("조회 매장 수", f"{len(summary):,}개")
  c2.metric("조회 기간", f"{period_days:,}일")
  c3.metric(
      "정상 시간 기록",
      f"{len(filtered.dropna(subset=['개점시간', '마감시간'])):,}건",
  )
  c4.metric("이상 영업 건수", f"{int((filtered['이상유형'] != '').sum()):,}건")

  st.markdown("#### 매장별 영업 요약")
  st.caption(
      "휴무/미기록일은 조회 기간 중 매장 기록이 없는 날짜입니다. "
      "실제 휴무와 데이터 누락은 원본 자료만으로 구분할 수 없습니다. "
      f"이상 영업은 매장별 평균 시각에서 {threshold_hours:.1f}시간 이상 차이가 난 경우입니다."
  )

  display_cols = [
      "매장명",
      "권역",
      "지역",
      "영업일수",
      "휴무/미기록일",
      "평균 개점시간",
      "평균 마감시간",
      "평균 운영시간",
      "이상 영업 건수",
  ]
  selection = st.dataframe(
      summary[display_cols],
      use_container_width=True,
      hide_index=True,
      on_select="rerun",
      selection_mode="single-row",
      key="summary_table",
  )

  chosen_key = None
  try:
    selected_rows = selection.selection.rows
    if selected_rows:
      chosen_key = summary.iloc[selected_rows[0]]["매장키"]
  except Exception:
    pass

  store_keys = summary["매장키"].tolist()
  default_idx = store_keys.index(chosen_key) if chosen_key in store_keys else 0
  chosen_key = st.selectbox(
      "상세 내용을 확인할 매장",
      options=store_keys,
      index=default_idx,
      format_func=lambda key: summary.loc[
          summary["매장키"] == key, "매장명"
      ].iloc[0],
      key="overview_store_select",
  )

  if st.button("선택 매장 상세 보기", type="primary"):
    st.session_state["detail_store_key"] = chosen_key
    st.success(
        "상단의 '매장별 상세 조회' 탭에서 선택 매장의 내역을 확인해 주세요."
    )

  st.markdown("#### 매장별 이상 영업 건수")
  anomaly_summary = summary[summary["이상 영업 건수"] > 0].sort_values(
      "이상 영업 건수", ascending=False
  )
  if anomaly_summary.empty:
    st.success("현재 설정한 기준에 해당하는 이상 영업 기록이 없습니다.")
  else:
    st.dataframe(
        anomaly_summary[["매장명", "권역", "지역", "이상 영업 건수"]],
        use_container_width=True,
        hide_index=True,
    )


# ---------------------------------------------------------
# 지역별/권역별 평균 개점·마감시간
# ---------------------------------------------------------
with tab_region_time:
  st.subheader("권역별·지역별 평균 개점시간 및 마감시간")
  st.caption(
      "권역 구분 — 수도권: 중부권, 강원권, 경기권, 수도권 / 영남권: 경상,"
      " 경북, 부산 / 호남권: 전남, 전북, 광주"
  )

  area_df = make_time_by_group(filtered, ["권역"])
  region_df = make_time_by_group(filtered, ["권역", "지역"])

  st.markdown("#### 📌 권역별 평균 개점·마감시간")
  if area_df.empty:
    st.info("표시할 권역 데이터가 없습니다.")
  else:
    st.dataframe(
        area_df[[
            "권역",
            "매장수",
            "유효 기록건수",
            "평균 개점시간",
            "평균 마감시간",
            "평균 운영시간",
        ]],
        use_container_width=True,
        hide_index=True,
    )

  st.markdown("#### 📍 지역별 평균 개점·마감시간")
  if region_df.empty:
    st.info("표