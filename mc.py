import os
import re
import logging
import json

import pandas as pd
from mcp.server.fastmcp import FastMCP

# =========================
# LOGGING
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# MCP SERVER
# =========================
PORT = int(os.environ.get("PORT", 8000))

mcp = FastMCP(
    "North Korean Dictionary Matcher",
    host="0.0.0.0",
    port=PORT,
)

DEFAULT_CSV_PATH = "북한용어사전.csv"

_cache = {
    "df": None,
    "path": None,
}


# =========================
# CSV 생성 (없을 때만 학습용 임시 더미 생성)
# =========================
def create_default_csv_if_missing():
    logger.info(f"DEFAULT_CSV_PATH = {DEFAULT_CSV_PATH}")
    exists = os.path.exists(DEFAULT_CSV_PATH)
    logger.info(f"exists? = {exists}")

    if not exists:
        logger.warning("사전 파일이 발견되지 않아 예시 데이터를 생성합니다.")
        # 용어, 설명, 분야(옵션) 형식의 예시 구조
        df = pd.DataFrame({
            "용어": ["살결물", "얼음보숭이", "락화생", "곽밥", "단물", "손전화"],
            "설명": [
                "스킨로션을 의미하며 피부를 정돈하는 화장수입니다.",
                "아이스크림을 의미하는 북한 고유의 말입니다.",
                "땅콩을 의미하는 북한의 한자어 어휘입니다.",
                "도시락을 의미하는 북한 식생활 용어입니다.",
                "주스 혹은 단 액체 음료를 가리키는 말입니다.",
                "휴대전화(핸드폰)를 뜻하는 무선 통신기기 용어입니다."
            ],
            "분야": ["생활", "음식", "음식", "음식", "음식", "생활"]
        })
        df.to_csv(DEFAULT_CSV_PATH, index=False, encoding="utf-8-sig")
    else:
        logger.info("기존 북한 용어 사전 파일을 발견했습니다.")


# =========================
# 데이터 로드 및 캐싱
# =========================
def get_dictionary(csv_path: str):
    if _cache["df"] is not None and _cache["path"] == csv_path:
        return _cache["df"]

    if csv_path == DEFAULT_CSV_PATH:
        create_default_csv_if_missing()

    logger.info(f"사전 데이터 불러오는 중: {os.path.abspath(csv_path)}")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 필수 컬럼 검증
    if "용어" not in df.columns or "설명" not in df.columns:
        raise ValueError("사전 CSV에는 최소한 '용어'와 '설명' 컬럼이 포함되어 있어야 합니다.")

    _cache.update({
        "df": df,
        "path": csv_path,
    })
    return df


# =========================
# TOOL 1: extract_and_define (본문 내 일괄 용어 추출 및 정의)
# =========================
@mcp.tool()
def extract_and_define(
    text: str,
    field: str = None,
    csv_path: str = DEFAULT_CSV_PATH,
) -> dict:
    """텍스트 본문에서 북한 용어를 자동으로 추출하고 그 뜻을 사전에서 매칭하여 반환합니다.

    Args:
        text: 북한 용어를 식별할 본문 원문 텍스트
        field: 필터링할 용어 분야 (옵션, 예: '음식', '생활' 등)
        csv_path: 사전 csv 파일 경로 (기본값: 북한용어사전.csv)

    Returns:
        {용어: 설명} 형식의 파이썬 딕셔너리
    """
    try:
        df = get_dictionary(csv_path)
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}")
        return {"오류": f"사전 데이터를 로드하지 못했습니다: {e}"}

    # 결측 행 제외
    valid_df = df.dropna(subset=["용어", "설명"])

    # 분야별 필터링이 설정되어 있고 CSV 파일에 '분야' 컬럼이 있는 경우 적용
    if field and "분야" in valid_df.columns:
        valid_df = valid_df[valid_df["분야"].astype(str).str.strip() == field.strip()]

    matched_results = {}

    # 긴 어휘부터 매칭하여 부분 일치 오류를 최소화하도록 정렬
    sorted_df = valid_df.iloc[valid_df["용어"].astype(str).str.len().argsort()[::-1]]

    # 본문 내 어휘 매칭 여부 전수 검사
    for _, row in sorted_df.iterrows():
        term = str(row["용어"]).strip()
        definition = str(row["설명"]).strip()
        
        # 본문에 용어가 포함되어 있으면 딕셔너리에 매핑 추가
        if term and term in text:
            matched_results[term] = definition

    return matched_results


# =========================
# TOOL 2: search_term (특정 단어 개별 검색)
# =========================
@mcp.tool()
def search_term(
    query: str,
    csv_path: str = DEFAULT_CSV_PATH,
) -> dict:
    """특정 어휘를 지정하여 북한 용어사전에서 개별적으로 검색합니다.

    Args:
        query: 검색할 북한 용어 (부분 일치 지원)
        csv_path: 사전 csv 파일 경로

    Returns:
        {용어: 설명} 형식의 파이썬 딕셔너리
    """
    try:
        df = get_dictionary(csv_path)
    except Exception as e:
        return {"오류": f"사전 데이터를 로드하지 못했습니다: {e}"}

    valid_df = df.dropna(subset=["용어", "설명"])
    matched_results = {}

    for _, row in valid_df.iterrows():
        term = str(row["용어"]).strip()
        definition = str(row["설명"]).strip()

        if query.strip() in term or term in query.strip():
            matched_results[term] = definition

    return matched_results


# =========================
# RUN
# =========================
if __name__ == "__main__":
    # 단일 엔드포인트 스트리밍 처리에 유리한 streamable-http 방식으로 호스팅합니다.
    mcp.run(transport="streamable-http")