"""memmachine_workload.pptx(3장)에 이어지는 추가 9장(4~12장)을 만든다.

구성 의도
  4장  배경      — 세션·인스턴스·캐시가 무엇이고 요청 1건이 겪는 세 상황
  5장  선택      — 사용자를 나누는 두 방식(세션 분리 / 이름표 분리)과 현재 상태
  6장  실측      — 상태별 저장소 질의 배수
  7장  실측 상세 — 신규 등록 18회의 내역
  8장  실측 상세 — worker를 늘렸을 때
  9장  구조      — 컬렉션 둘, 세션은 payload 한 칸
  10장 인접 비용 — 임베딩 호출 분할
  11장 접점      — 1장 파이프라인 위에 Qdrant 접점과 요청별 실측 시간
  12장 요약      — 파이프라인을 걷어낸 세 접점과 시간 비교 막대

기준 커밋 a8322a7. 수치는 docs/msr/qdrant_requests/ 의 보고서와 상세 문서에서만 가져왔다.
11~12장의 밀리초는 qdrant_request_trace.json 의 요청별 ms 를 구간별로 합산한 값이다.
시각 체계는 deck_style.py가 원본 덱에서 추출한 토큰 그대로다.
"""

from pptx.enum.text import PP_ALIGN
from pptx.util import Pt

import deck_style as S

OUT = "memmachine_qdrant_requests.pptx"
M = 0.45          # 좌우 여백
FULL = 12.43      # 전폭 콘텐츠


def _labeled_box(sl, x, y, w, h, kind, title, lines, *, badge=None,
                 title_size=11, line_size=9, gap=0.20, dashed=False):
    """색 박스 + 제목 + 본문 줄. box()는 가운데 정렬이라 직접 얹는다."""
    S.box(sl, x, y, w, h, [""], kind=kind, dashed=dashed)
    if badge:
        S.badge(sl, x + w - 0.30, y - 0.06, badge)
    S.text(sl, x + 0.15, y + 0.08, w - 0.45, 0.22, title, size=title_size, bold=True)
    for i, line in enumerate(lines):
        S.text(sl, x + 0.15, y + 0.32 + i * gap, w - 0.25, 0.18, line, size=line_size)


def _dim(sl, x, y, w, h, lines, *, size=9):
    """Qdrant를 건드리지 않는 단계. 회색으로 눌러 둔다."""
    shp = S.box(sl, x, y, w, h, lines, kind="self", size=size)
    shp.fill.fore_color.rgb = S._rgb("F4F4F4")
    shp.line.color.rgb = S._rgb("C4C4C4")
    for para in shp.text_frame.paragraphs:
        for run in para.runs:
            run.font.color.rgb = S._rgb("8A8A8A")
    return shp


def _hit(sl, x, y, w, h, lines, *, size=9):
    """Qdrant 요청이 나가는 단계. 초록 + 네이비 굵은 테두리."""
    shp = S.box(sl, x, y, w, h, lines, kind="store", size=size, bold=True)
    shp.line.color.rgb = S._rgb(S.NAVY)
    shp.line.width = Pt(2.25)
    return shp


def _flow(sl, y, stages, x0, w, pitch, aw):
    """가로 흐름 한 줄. stages = [(윗줄, 아랫줄, Qdrant닿음), ...]"""
    for i, (top, bottom, hit) in enumerate(stages):
        x = x0 + i * pitch
        (_hit if hit else _dim)(sl, x, y, w, 0.66, [top, bottom])
        if i < len(stages) - 1:
            S.arrow(sl, x + w + 0.01, y + 0.275, w=aw, h=0.11)


def _bar(sl, lx, lw, bx, bw, y, frac, label, value, *, fill=None):
    """가로 막대 한 줄. frac은 0~1로 미리 환산해 넘긴다."""
    S.text(sl, lx, y + 0.03, lw, 0.18, label, size=9)
    S.rect(sl, bx, y, bw, 0.20, "ECECEC")
    S.rect(sl, bx, y, max(0.05, bw * frac), 0.20, fill or S.STORE_L)
    S.text(sl, bx + bw + 0.12, y + 0.02, 1.20, 0.20, value,
           size=9.5, bold=True, font=S.MONO, color=S.CODE)


# ---------------------------------------------------------------- 4장 배경

def slide4(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "먼저 용어 셋 — 세션, 인스턴스, 캐시",
        "이 세 가지를 구분해야 뒤의 숫자가 읽힌다  ·  기준 upstream/speedkick a8322a7",
    )

    S.section(sl, M, 1.14, "은행 창구에 비유하면", w=6.0)

    for i, (kind, title, lines) in enumerate([
        ("store", "세션 = 고객의 계좌",
         ["기억을 담는 칸. 고객사와 프로젝트 조합으로 하나씩 만들어진다",
          "내용은 데이터베이스에 영구 보관된다"]),
        ("self", "인스턴스 = 창구 직원의 업무 세팅",
         ["그 계좌를 다루려고 서버 메모리에 올려둔 준비물",
          "금고 번호를 적은 메모와 열쇠이지, 돈이 아니다"]),
        ("opt", "캐시 = 책상 위 세팅 100칸",
         ["자주 쓰는 준비물만 올려둔다",
          "10분 안 쓰면 치우고, 자리가 모자라면 오래된 것부터 치운다"]),
    ]):
        _labeled_box(sl, M, 1.48 + i * 0.78, 6.05, 0.70, kind, title, lines,
                     line_size=8.5)

    S.rect(sl, M, 3.86, 6.05, 0.92, S.WHITE, S.API_L, 1.5)
    S.text(sl, M + 0.15, 3.94, 5.7, 0.22, "인스턴스에는 기억이 들어 있지 않다",
           size=11, bold=True, color=S.API_L)
    S.text(sl, M + 0.15, 4.18, 5.85, 0.40,
           "한 세션에 기억이 수백만 건 쌓여도 인스턴스 크기는 거의 변하지 않는다. "
           "그래서 100칸을 채워도 메모리를 크게 쓰지 않는다.", size=9, wrap=True)

    S.text(sl, 6.60, 1.14, 6.28, 0.28, "인스턴스 안에 무엇이 있나",
           size=14, bold=True, color=S.NAVY)
    S.table(
        sl, 6.60, 1.48, 6.28, [3.14, 3.14],
        [
            ["저장소의 어느 칸인지 가리키는 주소", "기억 본문"],
            ["데이터베이스 연결 통로", "기억을 숫자로 바꾼 값"],
            ["쪼개고 변환하는 방식 설정", "검색 결과"],
        ],
        header=["들어 있는 것 (도구)", "없는 것 (항상 저장소에서)"],
        header_size=9, body_size=8.5, row_h=0.28,
    )

    S.text(sl, 6.60, 3.10, 6.28, 0.28, "요청 1건이 겪는 세 가지 상황",
           size=14, bold=True, color=S.NAVY)
    S.table(
        sl, 6.60, 3.44, 6.28, [2.38, 1.20, 1.10, 1.60],
        [
            ["바로 처리 — 세팅이 책상에 있다", "0", "1", "1회"],
            ["재준비 — 계좌는 있고 세팅만 없다", "1", "1", "2회"],
            ["신규 등록 — 계좌 자체가 없다", "17", "1", "18회"],
        ],
        header=["상황", "준비 질의", "본래 일", "합계"],
        header_size=9, body_size=8.5, row_h=0.30,
        mono_cols={1, 2, 3}, emphasis_rows={2},
    )

    S.conclusion(sl, M, 5.15, FULL, 1.55, [
        ("계좌는 영구히 남지만 업무 세팅은 수시로 치워진다.", " 치워졌다고 기억이 사라지는 것은 아니다."),
        ("인스턴스가 있어도 검색은 반드시 저장소에 한 번 간다.", " 캐시가 아끼는 것은 검색이 아니라 그 앞의 준비 동작이다."),
        ("따라서 요청 1건의 비용은", " 요청 종류가 아니라 그 순간의 준비 상태로 정해진다."),
        ("이 세 상황의 이름을 뒤에서 계속 쓴다.", " 바로 처리, 재준비, 신규 등록."),
    ])
    S.footer(sl, "근거: 보고서 2부(이 문서에서 쓰는 말) — 캐시 용량 100과 유휴 600초는 "
                 "episodic_memory_manager.py:43, :48. 이 파일은 작업 브랜치와 speedkick이 동일하다.",
             y=6.82)


# ---------------------------------------------------------------- 5장 두 방식

def slide5(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "사용자를 나누는 두 가지 방법 — 먼저 고르고 나서 측정해야 한다",
        "두 방식은 서로 다른 병목을 드러낸다  ·  지금 평가 코드는 둘 중 어느 쪽도 아니다",
    )

    S.box(sl, M, 1.14, 6.05, 2.52, [""], kind="store")
    S.text(sl, M + 0.15, 1.22, 5.7, 0.24, "A. 세션 분리 — 사용자마다 방 하나",
           size=12, bold=True)
    S.text(sl, M + 0.15, 1.50, 5.85, 0.18,
           "사용자 한 명에게 계좌 하나. 공간이 쪼개지는 게 아니라 표시로 갈린다", size=9)
    S.rect(sl, M + 0.15, 1.74, 5.75, 0.30, S.WHITE, S.STORE_L, 1.0)
    S.text(sl, M + 0.24, 1.80, 5.6, 0.18,
           "sys-partition_key = 사용자마다 다른 값", size=8.5, font=S.MONO, color=S.CODE)
    S.text(sl, M + 0.15, 2.14, 5.7, 0.2, "좋은 점", size=10, bold=True, color=S.STORE_L)
    for i, line in enumerate([
        "자기 방만 보는 것이 기본 동작이다. 조건을 빠뜨려도 안전하다",
        "사용자 한 명을 지우려면 방을 통째로 지우면 된다",
    ]):
        S.text(sl, M + 0.15, 2.36 + i * 0.19, 5.85, 0.18, line, size=8.5)
    S.text(sl, M + 0.15, 2.82, 5.7, 0.2, "비용", size=10, bold=True, color=S.API_L)
    for i, line in enumerate([
        "사용자마다 신규 등록 17회. 500명이면 8,500회",
        "동시 활동 사용자가 100명을 넘고 일부가 쉬면 재준비가 반복된다",
        "데이터베이스에도 사용자 수만큼 구획이 생긴다. 테이블이 늘지는 않는다",
    ]):
        S.text(sl, M + 0.15, 3.04 + i * 0.19, 5.85, 0.18, line, size=8.5)

    S.box(sl, 6.83, 1.14, 6.05, 2.52, [""], kind="opt")
    S.text(sl, 6.98, 1.22, 5.7, 0.24, "B. 이름표 분리 — 한 방을 같이 쓰기",
           size=12, bold=True)
    S.text(sl, 6.98, 1.50, 5.85, 0.18,
           "모두 한 계좌를 쓰고, 기억마다 누구 것인지 표시한다", size=9)
    S.rect(sl, 6.98, 1.74, 5.75, 0.30, S.WHITE, S.OPT_L, 1.0)
    S.text(sl, 7.07, 1.80, 5.6, 0.18,
           "producer_id = 'userA' OR produced_for_id = 'userA'",
           size=8.5, font=S.MONO, color=S.CODE)
    S.text(sl, 6.98, 2.14, 5.7, 0.2, "좋은 점", size=10, bold=True, color=S.STORE_L)
    for i, line in enumerate([
        "방을 만드는 등록 절차가 전체를 통틀어 한 번이다",
        "책상도 한 칸만 쓴다. 100칸 한도 문제가 생기지 않는다",
    ]):
        S.text(sl, 6.98, 2.36 + i * 0.19, 5.85, 0.18, line, size=8.5)
    S.text(sl, 6.98, 2.82, 5.7, 0.2, "비용과 위험", size=10, bold=True, color=S.API_L)
    for i, line in enumerate([
        "검색마다 조건을 붙여야 한다. 빠뜨리면 남의 기억이 나온다",
        "말한 사람만으로 걸면 상대 답변이 빠진다. 두 조건이 필요하다",
        "사용자 한 명만 지우려면 기억을 하나씩 찾아 지워야 한다",
    ]):
        S.text(sl, 6.98, 3.04 + i * 0.19, 5.85, 0.18, line, size=8.5)

    S.table(
        sl, M, 3.78, FULL, [4.00, 4.20, 4.23],
        [
            ["신규 등록 비용", "사용자 수 × 17회", "전체 1회"],
            ["캐시 100칸 한도", "일부가 쉴 때 재준비 반복", "문제 없음"],
            ["격리 방식", "구조적 — 조건을 빠뜨려도 안전", "정책적 — 조건을 붙여야 안전"],
        ],
        header=["갈리는 지점", "A. 세션 분리", "B. 이름표 분리"],
        header_size=9, body_size=9, row_h=0.26,
    )

    S.rect(sl, M, 4.90, FULL, 0.60, S.WHITE, S.API_L, 1.5)
    S.badge(sl, M + FULL - 0.32, 4.84, "yes")
    S.text(sl, M + 0.15, 4.97, 7.0, 0.22, "지금 평가 코드는 둘 중 어느 쪽도 아니다",
           size=11, bold=True, color=S.API_L)
    S.text(sl, M + 0.15, 5.20, 12.0, 0.2,
           "방을 나누지 않아 모든 사용자가 기본 세션 하나로 합쳐지고, 검색에 조건을 걸지 않는다. "
           "이름표(화자)는 붙지만 격리에 쓰이지 않는다", size=9)

    S.conclusion(sl, M, 5.58, FULL, 1.28, [
        ("둘 중 하나가 정답인 것은 아니다.", " 격리가 중요하면 A, 사용자 수가 많고 운영 비용이 중요하면 B다."),
        ("다만 먼저 고르지 않으면 측정 설계가 서지 않는다.", " A는 칸이 늘 때를, B는 한 칸이 커질 때를 본다."),
        ("현재 상태로는 사용자를 500명까지 늘려도", " 두 방식의 비용 차이가 드러나지 않는다."),
    ], gap=0.25, size=10)
    S.footer(sl, "근거: 보고서 7부(두 방식)·8부(현재 평가) — 세션 키는 service.py:44, 기본값 universal은 spec.py:29. "
                 "필터 회수율은 사용자 3명 12건 적재로 실측했다.", y=6.94)


# ---------------------------------------------------------------- 6장 실측 배수

def slide6(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "요청 1건이 저장소 질의 몇 건이 되는가 — 상태별 실측",
        "기준 acb4f9a → a8322a7 (speedkick, 2026-09-14) · qdrant 1.17.0 + postgres 16 · HTTP 전수 기록",
    )

    cols = [3.75, 0.95, 0.95, 0.95, 0.95]
    bottom = S.table(
        sl, M, 1.20, 7.55, cols,
        [
            ["바로 처리: 인스턴스가 캐시에 있음", "1", "1", "1", "3"],
            ["재준비: 캐시에서 빠짐, 세션은 등록됨", "2", "2", "2", "4"],
            ["신규 등록: 처음 보는 세션", "18", "18", "—", "—"],
        ],
        header=["상황", "저장 1건", "검색 1건", "에피소드 삭제", "세션 삭제"],
        header_size=9, body_size=9, mono_cols={1, 2, 3, 4}, emphasis_rows={2},
    )
    for i in range(3):
        S.badge(sl, 0.16, 1.51 + i * 0.30, "yes")

    S.rect(sl, M, bottom, 7.55, 0.30, S.SELF_F, S.WHITE, 1.0)
    S.text(sl, M + 0.07, bottom + 0.05, 3.61, 0.2, "프로세스(worker) 시작", size=9)
    S.text(sl, M + 3.82, bottom + 0.05, 3.66, 0.2,
           "연결 확인 1회 + 버전 확인 1회 (별도 스레드)", size=9)
    S.text(sl, M, bottom + 0.34, 7.55, 0.2,
           "GET /collections는 트레이스로, GET /는 클라이언트 버전 경고로 확인", size=8, color=S.FOOT)

    _labeled_box(sl, M, 3.15, 7.55, 1.30, "opt",
                 "설정에 따라서만 배수가 달라지는 셋 — 모두 코드 기준, 실행 미확인",
                 ["agent_mode=true → 검색 1건이 저장소 2~22회",
                  "시맨틱 vector_store 백엔드 → set_id마다 limit 10,000 검색 1회",
                  "분산 모드 → 세션 생성 때 샤드 키 1회 추가"],
                 badge="part", gap=0.26)

    S.section(sl, 8.25, 1.16, "배수를 정하는 것은 두 가지뿐", w=4.63)
    S.box(sl, 8.25, 1.50, 4.63, 0.44,
          ["① 인스턴스가 이 worker의 캐시에 있는가 (100칸 / 10분)"], kind="self", size=9)
    S.box(sl, 8.25, 1.98, 4.63, 0.44,
          ["② 그 세션이 저장소에 등록돼 있는가"], kind="self", size=9)
    S.text(sl, 8.25, 2.46, 4.63, 0.2, "둘 다 A1 / S1(세션 확보) 한 단계에서 갈린다",
           size=9, color=S.GRAY)

    S.box(sl, 8.25, 2.70, 4.63, 0.78, [""], kind="self")
    S.text(sl, 8.40, 2.78, 4.3, 0.22, "검색 옵션은 배수를 바꾸지 않는다", size=11, bold=True)
    S.text(sl, 8.40, 3.00, 4.35, 0.2,
           "top_k · filter · expand_context · score_threshold 모두 1회", size=9)
    S.text(sl, 8.40, 3.20, 4.35, 0.2, "바뀌는 것은 limit = top_k × 4 하나뿐",
           size=8.5, font=S.MONO, color=S.CODE)

    S.box(sl, 8.25, 3.56, 4.63, 0.60, [""], kind="opt")
    S.text(sl, 8.40, 3.63, 4.3, 0.22, "기준 커밋이 바뀌었다", size=11, bold=True)
    S.text(sl, 8.40, 3.85, 4.35, 0.2,
           "acb4f9a (1~3장) → a8322a7 · 캐시 코드는 작업 브랜치와 동일",
           size=8.5, font=S.MONO, color=S.CODE)

    S.panel(sl, 8.25, 4.24, 4.63, 0.86, radius=0.10)
    S.text(sl, 8.40, 4.31, 4.3, 0.2, "배지 뜻이 바뀐다 — 1~3장은 계측 유무, 4장부터는 근거 종류",
           size=9, bold=True)
    for i, (kind, label) in enumerate([("yes", "실행 트레이스로 실측"),
                                       ("part", "코드 기준, 실행 미확인"),
                                       ("no", "이번 회차 계측 밖")]):
        yy = 4.55 + i * 0.17
        S.badge(sl, 8.42, yy - 0.01, kind, d=0.15, size=7)
        S.text(sl, 8.62, yy, 4.1, 0.16, label, size=8.5)

    S.conclusion(sl, M, 5.18, FULL, 1.58, [
        ("평상시 배수는 1이다.", " 저장 1건도 검색 1건도 저장소 질의 1건이고, 검색 옵션은 이 수를 바꾸지 않는다."),
        ("배수를 키우는 것은 검색 옵션이 아니라 준비 상태다.", " 재준비 2배, 신규 등록 18배."),
        ("삭제는 값이 다르다.", " 에피소드 삭제 1회, 세션 삭제는 바로 처리 3회 재준비 4회다."),
        ("따라서 부하 산정은", " 요청 수가 아니라 요청 수 × 상태 분포 × worker 수로 해야 한다."),
    ])
    S.footer(sl, "근거: 보고서 6부(상태별 요청 수) — qdrant-client의 HTTP 전송 함수를 감싸 REST 요청을 전수 기록했고 "
                 "실제 EpisodicMemoryManager와 세션 DB를 그대로 썼다. 임베더만 64차원 해시.", y=6.86)


# ---------------------------------------------------------------- 7장 신규 등록

def slide7(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "신규 등록 18회의 내역 — 인덱스 11회는 낭비가 아니라 의도된 동작",
        "PUT /collections ×2 + PUT …/index ×11 + registry 왕복 ×4 = 17  (+ 본 요청 1 = 18)",
    )

    cx = M + 5.45 / 2 - 0.055
    S.box(sl, M, 1.20, 5.45, 0.58,
          [("1~3  registry 확인과 생성", True), "포인트 조회 → registry 컬렉션 PUT → 포인트 재조회"],
          kind="self", size=9)
    S.arrow_down(sl, cx, 1.81)
    S.box(sl, M, 1.99, 5.45, 0.50,
          [("4  native 컬렉션 생성 PUT", True), "hnsw m=0, payload_m=16"], kind="store", size=9)
    S.arrow_down(sl, cx, 2.52)

    S.rect(sl, M, 2.70, 5.45, 1.72, S.WHITE, S.API_L, 2.0)
    S.text(sl, M + 0.15, 2.78, 5.15, 0.22,
           "5~15  payload 인덱스 생성 11회 — 이미 있어도 매번 나간다",
           size=10.5, bold=True, color=S.API_L)
    idx = ["sys-partition_key (is_tenant)", "_timestamp (datetime)", "_episode_uid",
           "_session_key", "_producer_id", "_producer_role", "_produced_for_id",
           "_sequence_num (integer)", "_episode_type", "_content_type",
           "_created_at (datetime)"]
    for i, name in enumerate(idx):
        col, row = divmod(i, 6)
        S.text(sl, M + 0.17 + col * 2.65, 3.06 + row * 0.21, 2.55, 0.18, name,
               size=8, font=S.MONO, color=S.CODE)

    S.arrow_down(sl, cx, 4.45)
    S.box(sl, M, 4.63, 5.45, 0.46, ["16~17  registry 포인트 upsert → 최종 조회"],
          kind="self", size=9)

    S.table(
        sl, 6.20, 1.20, 6.68, [3.28, 1.70, 1.70],
        [
            ["1  registry 포인트 조회", "404", "200, 빈 결과"],
            ["2  registry 컬렉션 생성", "200", "409"],
            ["3  registry 포인트 조회", "200, 빈 결과", "200, 빈 결과"],
            ["4  native 컬렉션 생성", "200", "409"],
            ["5~15  payload 인덱스 11회", "200", "200"],
            ["16  registry 포인트 등록", "200", "200"],
            ["17  registry 포인트 조회", "200", "200"],
            ["합계", "17회", "17회"],
        ],
        header=["요청", "첫 세션", "두 번째 새 세션"],
        header_size=9, body_size=8.5, row_h=0.28, center_cols={1, 2},
        emphasis_rows={7}, emphasis_color=S.NAVY,
    )
    S.badge(sl, 12.52, 3.46, "yes")

    _labeled_box(sl, 6.20, 3.88, 6.68, 1.05, "store",
                 "인덱스 11회를 매번 보내는 이유",
                 ["예전에는 컬렉션이 이미 있으면 payload 인덱스가 하나도 만들어지지 않았다",
                  "그 결함을 고치면서 컬렉션 생성과 인덱스 생성을 분리해 개별로 보낸다",
                  "커밋 a2a1754 · 첫 세션 각 32~88ms, 두 번째부터 각 3ms (로컬 Docker)"],
                 gap=0.21)

    S.conclusion(sl, M, 5.15, FULL, 1.55, [
        ("17회 중 11회는 인덱스 생성이지만 낭비가 아니다.", " 인덱스가 하나도 만들어지지 않던 결함을 막기 위한 의도된 동작이다."),
        ("두 번째 새 세션부터는", " 컬렉션 생성 2회가 409로 돌아온다. 총 요청 수는 17회로 같다."),
        ("검색도 같은 경로를 쓴다.", " 처음 보는 세션으로 검색만 해도 17회 + 검색 1회가 나간다."),
        ("방식 A를 고르면", " 이 17회가 사용자 수만큼 그대로 누적된다."),
    ])
    S.footer(sl, "근거: 보고서 4.3~4.4(요청 상세) · 트레이스 원본 trace_output.txt — 코드는 a8322a7 기준 "
                 "service_locator.py:106·118·123, qdrant_vector_store.py:649-704.", y=6.82)


# ---------------------------------------------------------------- 8장 worker

def slide8(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "worker를 늘리면 요청은 몇 배가 되는가 — 캐시는 worker마다 따로 있다",
        "MemoryInstanceCache  capacity=100  idle=600s  sweep=2s  ·  MEMMACHINE_WORKERS 기본값 1",
    )

    S.table(
        sl, M, 1.20, 6.15, [1.75, 2.20, 2.20],
        [
            ["Qdrant 클라이언트", "프로세스 수명, 시작 시 예열", "GET /collections 1회"],
            ["인스턴스 캐시", "worker별, 100칸 · 유휴 600초", "조회 1회, 없으면 생성 17회"],
            ["registry 엔트리", "캐시하지 않는다", "열 때마다 조회 1회"],
            ["시맨틱 컬렉션 핸들", "서비스 시작 시 1회", "있으면 1회, 없으면 16회"],
        ],
        header=["캐시 층", "범위와 수명", "미스일 때 저장소 질의"],
        header_size=9, body_size=8.5, row_h=0.32,
        emphasis_rows={1}, emphasis_color=S.NAVY,
    )
    S.badge(sl, 0.16, 1.51, "yes")
    S.badge(sl, 0.16, 2.47, "part")

    _labeled_box(sl, M, 2.92, 6.15, 0.75, "self",
                 "캐시에서 빠지는 경우는 셋뿐",
                 ["worker 재시작 · 10분 넘게 쉰 세션 · 100칸이 찼고 유휴 인스턴스가 있을 때",
                  "100칸 · 600초 · 2초는 설정으로 바꿀 수 없다"],
                 gap=0.24)

    S.table(
        sl, 6.78, 1.20, 6.10, [2.90, 1.30, 1.90],
        [
            ["worker N개 동시 재시작 직후", "2 × N", "연결 + 버전 확인"],
            ["기존 세션이 각 worker에 처음 닿음", "+1 × N", "조회가 worker마다"],
            ["새 세션이 M개 생김", "17 × M", "worker 수와 무관"],
            ["같은 새 세션을 두 worker가 동시에", "17 × 2", "잠금이 프로세스 안"],
            ["worker당 동시 처리 세션 100개 초과", "그대로", "축출 대상이 없어 칸만 는다"],
            ["활성 세션 100개 초과 · 일부는 유휴", "일부 2배", "유휴 인스턴스가 밀려남"],
            ["10분 유휴 뒤 첫 요청", "세션당 +1", "유휴 600초 제거"],
        ],
        header=["운영 시나리오", "저장소 질의", "근거"],
        header_size=9, body_size=8.5, row_h=0.30, mono_cols={1}, emphasis_rows={2},
    )

    _labeled_box(sl, M, 4.00, FULL, 0.75, "opt",
                 "로드밸런서는 있지만 사용자를 같은 worker로 보내는 설정은 없다",
                 ["그래서 같은 세션이 여러 worker에 중복으로 올라가고, 처음 받는 worker마다 재준비가 한 번씩 발생한다. "
                  "기본값이 worker 1개라 이 문제는 2개 이상으로 올렸을 때만 생긴다"],
                 gap=0.22)

    S.conclusion(sl, M, 4.95, FULL, 1.72, [
        ("캐시는 worker마다 따로 있다.", " worker가 N개면 같은 세션이라도 worker마다 각각 재준비 비용을 낸다."),
        ("다만 신규 등록 17회는 worker 수가 아니라 새 세션 수에 비례한다.", " 먼저 연 worker가 등록하면 나머지는 조회 1회로 끝난다."),
        ("100칸을 넘길 때 무엇이 늘어나는지는 유휴 세션 유무로 갈린다.", " 전부 쓰는 중이면 캐시가 그냥 커지고, 유휴 세션이 섞였을 때만 밀려나 재준비가 반복된다."),
        ("부하 시험은 worker 수와 세션 수를 함께 변수로 잡아야 한다.", " 하나만 바꾸면 이 배수가 드러나지 않는다."),
    ])
    S.footer(sl, "근거: 보고서 10부(캐시 리뷰) — episodic_memory_manager.py:43-52·103-106, "
                 "instance_lru_cache.py:174-185·206-219, docker-compose.yml:87. "
                 "캐시 잠금 자체는 병목이 아니다(요청당 마이크로초).", y=6.80)


# ---------------------------------------------------------------- 9장 구조

def slide9(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "컬렉션은 둘, 세션은 payload 한 칸 — 세션이 늘어도 컬렉션은 늘지 않는다",
        "long_term_memory__registry  ·  long_term_memory__<sha256(config)>",
    )

    S.box(sl, M, 1.20, 5.75, 1.05, [""], kind="store")
    S.text(sl, M + 0.15, 1.28, 5.4, 0.22, "registry 컬렉션", size=11, bold=True)
    S.text(sl, M + 0.15, 1.50, 5.4, 0.2, "long_term_memory__registry",
           size=9.5, font=S.MONO, color=S.CODE)
    S.text(sl, M + 0.15, 1.70, 5.45, 0.2,
           "세션 하나당 포인트 1개. 벡터는 1차원 더미, payload에 이름과 스키마", size=9)
    S.text(sl, M + 0.15, 1.90, 5.45, 0.2,
           "포인트 id = uuid5(네임스페이스, 파티션 키) — 계산해 바로 조회", size=9)

    S.box(sl, M, 2.35, 5.75, 1.60, [""], kind="store")
    S.text(sl, M + 0.15, 2.43, 5.4, 0.22, "native 컬렉션", size=11, bold=True)
    S.text(sl, M + 0.15, 2.65, 5.4, 0.2, "long_term_memory__<sha256(config)>",
           size=9.5, font=S.MONO, color=S.CODE)
    S.text(sl, M + 0.15, 2.85, 5.45, 0.2,
           "이름이 설정 해시라서 같은 설정을 쓰는 모든 세션이 하나를 공유한다", size=9)
    for i, val in enumerate(["sys-partition_key=bd36…", "…=a1f2…", "…=7c04…"]):
        x = M + 0.17 + i * 1.85
        S.rect(sl, x, 3.10, 1.75, 0.22, S.WHITE, S.STORE_L, 1.0)
        S.text(sl, x + 0.06, 3.13, 1.65, 0.16, val, size=7.5, font=S.MONO, color=S.CODE)
    S.text(sl, M + 0.15, 3.42, 5.45, 0.2,
           "포인트에는 벡터와 payload 11키 + 사용자 metadata만 들어간다", size=9, bold=True)
    S.text(sl, M + 0.15, 3.62, 5.45, 0.2, "본문 텍스트는 저장소에 저장하지 않는다", size=9)

    _labeled_box(sl, M, 4.05, 5.75, 0.88, "self", "파티션 키 규칙",
                 ["세션 키가 규칙에 맞으면 그대로, 아니면 sha256[:32]",
                  "orga/prja → bd36dbe5eef78ec754963d978108ef7b"], gap=0.20)

    S.box(sl, 6.45, 1.20, 6.43, 1.30, [""], kind="store")
    S.badge(sl, 12.58, 1.14, "yes")
    S.text(sl, 6.60, 1.28, 5.6, 0.22, "검색에 실제로 나가는 요청", size=10.5, bold=True)
    for i, line in enumerate([
        "POST /collections/long_term_memory__<hash>/points/query/batch",
        "searches=1  limit=80  with_payload=false  with_vector=false",
        'filter={"must":[{"key":"sys-partition_key","match":{"value":"bd36…"}}]}',
    ]):
        S.text(sl, 6.60, 1.52 + i * 0.19, 6.15, 0.18, line, size=8.5,
               font=S.MONO, color=S.CODE)
    S.text(sl, 6.60, 2.13, 6.15, 0.2,
           "방식 B의 사용자 조건은 이 파티션 조건과 AND로 묶인다", size=9)

    S.rect(sl, 6.45, 2.60, 6.43, 1.35, S.WHITE, S.API_L, 1.5)
    S.badge(sl, 12.58, 2.54, "no")
    S.text(sl, 6.60, 2.68, 5.6, 0.22, "한 칸에 약 1,667건 전까지는 그래프가 없다",
           size=11.5, bold=True, color=S.API_L)
    S.text(sl, 6.60, 2.94, 6.15, 0.60,
           "m=0이라 전역 그래프는 없고, payload_m=16으로 파티션 값마다 하위 그래프가 생긴다. "
           "임계값은 1536차원 약 1,667개다. 방식 A는 사용자당, 방식 B는 프로젝트 전체가 기준이 된다.",
           size=9, wrap=True)
    S.text(sl, 6.60, 3.66, 6.15, 0.18,
           "이전 Qdrant 서버 소스 분석(v1.19.1) 인용 — 이번 회차에 재계측하지 않았다",
           size=8, color=S.FOOT)

    _labeled_box(sl, 6.45, 4.05, 6.43, 0.88, "self", "탐색 폭과 점수 컷",
                 ["한 번에 훑는 후보는 기본 100개다. top_k 25(=limit 100)를 넘으면 넓어진다",
                  "score_threshold는 요청에 실리지 않는다 (long_term_memory.py:340)"], gap=0.20)

    S.conclusion(sl, M, 5.10, FULL, 1.58, [
        ("세션이 늘어도 컬렉션은 늘지 않는다.", " 늘어나는 것은 registry 포인트 1개와 파티션 값 하나다."),
        ("세션 분리는 컬렉션이 아니라 payload 필드 하나로 한다.", " sys-partition_key에 걸린 테넌트 인덱스가 그 경계다."),
        ("방식 A는 사용자 대부분이 임계값에 못 미쳐", " 그래프 없이 필터 후 순차 비교로 검색된다. 소규모에서는 이 편이 빠르다."),
        ("방식 B는 그래프가 일찍 생기지만", " 사용자 조건의 선택도에 따라 탐색 경로가 갈린다."),
    ], size=10)
    S.footer(sl, "근거: 보고서 3.1(구조)·4.6(검색 요청)·7.3(임계값) — qdrant_vector_store.py:64·87·550·669-672, "
                 "service_locator.py:158-182, long_term_memory.py:310·340.", y=6.80)


# ---------------------------------------------------------------- 10장 임베딩

def slide10(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "저장이 느려지면 저장소가 아닐 수 있다 — 임베딩 호출의 분할",
        "한 요청 상한 inputs ≤ 2048, chars ≤ 75000  ·  max_attempts=1  ·  재시도 없음",
    )

    S.box(sl, M, 1.20, FULL, 0.95, [""], kind="api")
    S.text(sl, M + 0.15, 1.27, 4.0, 0.22, "분할 규칙", size=11, bold=True)
    for i, line in enumerate([
        "① batch_size가 설정되면 그 크기로 먼저 나눠 동시에 부른다 (기본 미설정)",
        "② 입력 하나가 75,000자를 넘으면 그 길이로 자른다",
        "③ 한 요청은 입력 2,048개 이하, 총 75,000자 이하로 묶는다",
        "④ 묶음마다 HTTP 요청을 만들어 동시에 보낸다",
    ]):
        col, row = divmod(i, 2)
        S.text(sl, M + 0.15 + col * 6.15, 1.52 + row * 0.20, 6.0, 0.18, line, size=8.5)
    S.text(sl, M + 0.15, 1.93, 12.1, 0.18,
           "조각은 길이 가중 평균으로 합쳐 벡터 1개가 되므로 저장소 포인트 수는 변하지 않는다",
           size=9, color=S.GRAY)

    S.table(
        sl, M, 2.30, 7.15, [3.25, 1.70, 1.00, 1.20],
        [
            ["저장, 에피소드 4건", "4개 336자", "1", "1"],
            ["검색 1건", "1개 16자", "1", "1"],
            ["저장, 16만 자 1건", "1개 160,039자", "1", "3"],
            ["저장, 에피소드 2,100건", "2,100개 186,780자", "1", "3"],
            ["저장, batch_size=2로 5건", "5개", "1", "3"],
            ["저장, sentence_text 2건×3문장", "6개", "1", "1"],
            ["임베더 최초 생성 (프로세스당 1회)", "1개", "1", "1"],
        ],
        header=["구간", "입력", "논리 호출", "HTTP 요청"],
        header_size=9, body_size=8.5, row_h=0.28, mono_cols={2, 3}, center_cols={1},
    )
    S.badge(sl, 0.16, 2.61, "yes")
    S.text(sl, M, 4.58, 7.15, 0.18,
           "HTTP 3건인 경우의 분할: 75,000+75,000+10,039자 · 854+836+410개 · 2+2+1개",
           size=8, color=S.FOOT)

    _labeled_box(sl, 7.75, 2.30, 5.13, 0.95, "opt", "운영값으로 환산하면",
                 ["메시지 평균 400자일 때 한 저장 요청에 약 187건이 넘어가면",
                  "HTTP 요청이 하나 더 생긴다. 2,048개 제한은 짧을 때만 먼저 걸린다"],
                 gap=0.21)

    S.box(sl, 7.75, 3.40, 5.13, 1.36, [""], kind="self")
    S.text(sl, 7.90, 3.48, 4.8, 0.22, "바로 처리 상태의 외부 호출", size=11, bold=True)
    S.text(sl, 7.90, 3.72, 4.85, 0.18, "검색 = 임베딩 1 · 저장소 1 · PostgreSQL 다수",
           size=9, font=S.MONO, color=S.CODE)
    S.text(sl, 7.90, 3.91, 4.85, 0.18, "저장 = 임베딩 1+ · 저장소 1 · PostgreSQL 다수",
           size=9, font=S.MONO, color=S.CODE)
    S.text(sl, 7.90, 4.14, 4.85, 0.35,
           "임베딩과 저장소 검색은 직렬이라 임베딩 왕복이 검색 지연에 그대로 더해진다",
           size=9, wrap=True)
    S.text(sl, 7.90, 4.53, 4.85, 0.18,
           "PostgreSQL 호출 수는 이번 회차에서 세지 않았다 (보고서 0부)",
           size=8, color=S.FOOT)

    S.rect(sl, M, 4.85, FULL, 0.60, S.WHITE, S.API_L, 1.5)
    S.text(sl, M + 0.15, 4.92, 6.0, 0.22, "임베딩 호출에는 재시도가 없다",
           size=11, bold=True, color=S.API_L)
    S.text(sl, M + 0.15, 5.15, 12.1, 0.2,
           "모든 호출부가 max_attempts 기본값 1을 쓴다. 429나 5xx를 받으면 재시도 없이 저장 또는 검색이 그대로 실패한다. "
           "임베더 안의 백오프 루프는 한 번도 돌지 않는다", size=9)

    S.conclusion(sl, M, 5.55, FULL, 1.45, [
        ("저장소 질의가 1회로 고정이어도 임베딩 HTTP는 1건 이상일 수 있다.", " 저장 요청이 커질 때 갈라지는 쪽은 임베딩이다."),
        ("병목 측정에서 임베딩 왕복과 저장소 왕복을 나눠 재야 한다.", " 검색에서 둘은 직렬이다."),
        ("임베딩 호출 수는 준비 상태와 무관하다.", " 신규 등록이어도 저장 1회, 검색 1회다."),
        ("주기적으로 도는 임베딩은 시맨틱 특징 임베딩뿐이고,", " 기본값은 꺼짐이다."),
    ], size=10, gap=0.25)
    S.footer(sl, "근거: 보고서 9부(임베딩) · 측정 기록 3부(E1~E11) — OpenAI 호환 스텁 서버로 실제 HTTP 요청의 "
                 "입력 개수와 총 길이를 셌고, 임베더 구현은 운영과 같은 OpenAIEmbedder다.", y=7.06)


# ---------------------------------------------------------------- 11장 접점

INGEST = [
    ("세션 확보", "LRU · RW 락", True),
    ("원문 INSERT", "… RETURNING", False),
    ("세그먼트화", "기본 passthrough", False),
    ("파생 생성", "임베딩할 텍스트", False),
    ("임베딩", "외부 API", False),
    ("세그먼트 쓰기", "segment_store", False),
    ("벡터 upsert", "Qdrant", True),
]

SEARCH = [
    ("세션 확보", "LRU · RW 락", True),
    ("필터 파싱", "검증 · 번역", False),
    ("쿼리 임베딩", "외부 API", False),
    ("ANN 탐색", "+ payload 필터", True),
    ("문맥 walk", "PostgreSQL", False),
    ("리랭킹", "기본 없음", False),
    ("결과 조립", "프로세스 내", False),
    ("원문 복원", "PK 조회 · PG", False),
]


def slide11(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "Qdrant는 언제 불리고 얼마나 걸리는가 — 파이프라인 위의 세 접점",
        "1장의 두 흐름 그대로 · 초록 굵은 테두리만 Qdrant 요청 · 시간은 같은 장비 Docker 실측",
    )

    S.chip(sl, M, 1.02, "store", w=0.26, h=0.17)
    S.text(sl, M + 0.33, 1.02, 2.40, 0.2, "Qdrant 요청 발생", size=11)
    c = S.chip(sl, 3.30, 1.02, "self", w=0.26, h=0.17)
    c.fill.fore_color.rgb = S._rgb("F4F4F4")
    c.line.color.rgb = S._rgb("C4C4C4")
    S.text(sl, 3.63, 1.02, 6.00, 0.2,
           "Qdrant 요청 없음 — PostgreSQL 또는 프로세스 안", size=11)

    S.section(sl, M, 1.34, "① 적재   POST /memories", w=6.0)
    _flow(sl, 1.68, INGEST, M, 1.52, 1.72, 0.17)
    S.text(sl, M, 2.38, 1.52, 0.18, "0 · 1 · 17회", size=9, bold=True,
           color=S.NAVY, align=PP_ALIGN.CENTER)
    S.text(sl, 10.77, 2.38, 1.52, 0.18, "1회 · 3.0 ms", size=9, bold=True,
           color=S.NAVY, align=PP_ALIGN.CENTER)
    S.text(sl, 2.30, 2.38, 8.30, 0.18,
           "원문과 세그먼트는 PostgreSQL, 임베딩은 외부 API — 여기서는 Qdrant 요청이 없다",
           size=8.5, color=S.FOOT, align=PP_ALIGN.CENTER)

    S.section(sl, M, 2.86, "② 검색   POST /memories/search", w=6.0)
    _flow(sl, 3.20, SEARCH, M, 1.38, 1.535, 0.14)
    S.text(sl, M, 3.90, 1.38, 0.18, "0 · 1 · 17회", size=9, bold=True,
           color=S.NAVY, align=PP_ALIGN.CENTER)
    S.text(sl, 5.055, 3.90, 1.38, 0.18, "1회 · 1.6~2.5 ms", size=9, bold=True,
           color=S.NAVY, align=PP_ALIGN.CENTER)
    S.text(sl, 6.59, 3.90, 5.98, 0.18,
           "이 뒤로 Qdrant 요청은 0회 — 문맥 walk와 원문 복원은 PostgreSQL이다",
           size=8.5, color=S.FOOT, align=PP_ALIGN.CENTER)

    S.table(
        sl, M, 4.22, FULL, [2.55, 0.85, 1.30, 4.60, 3.13],
        [
            ["바로 처리 — 캐시에 있음", "0회", "0 ms",
             "준비 요청 없이 곧바로 본래 일로 간다", "대부분의 요청"],
            ["재준비 — 캐시에서 빠짐", "1회", "1.5 ms",
             "registry에서 그 세션 포인트 1개를 조회한다", "유휴 10분 · 재시작 · 100칸 축출 시"],
            ["신규 등록 — 처음 보는 세션", "17회", "850 → 47 ms",
             "컬렉션 2개 165ms · 색인 11개 667ms · registry 4회 18ms",
             "그 세션의 첫 요청 한 번 (내역은 7장)"],
        ],
        header=["세션 확보의 상태", "요청", "실측 시간", "무슨 호출이 왜 나가는가", "언제 생기나"],
        header_size=9, body_size=8.5, row_h=0.30,
        mono_cols={1, 2}, emphasis_rows={2},
    )
    S.badge(sl, 0.16, 4.53, "yes")

    S.conclusion(sl, M, 5.50, FULL, 1.52, [
        ("Qdrant가 닿는 곳은 파이프라인 전체에서 세 군데뿐이다.",
         " 문맥 walk와 리랭킹, 원문 복원은 Qdrant 요청이 0회다."),
        ("평상시 Qdrant가 쓰는 시간은 저장 3.0ms, 검색 2ms 안팎이다.",
         " 검색 옵션을 바꿔도 요청은 1회로 고정이다."),
        ("신규 등록 17회는 첫 세션만 850ms이고 두 번째 새 세션부터 47ms다.",
         " 컬렉션과 색인을 실제로 만드는 것이 첫 한 번뿐이기 때문이다."),
        ("이 시간은 같은 장비 기준이다.",
         " Qdrant를 다른 노드에 두면 요청마다 네트워크 왕복이 그대로 더해진다."),
    ], size=10, gap=0.26)
    S.footer(sl, "근거: 측정 기록 2부(S1~S13)와 qdrant_request_trace.json. "
                 "요청별 ms는 qdrant-client의 HTTP 전송 함수에서 직접 쟀다.", y=7.10)


# ---------------------------------------------------------------- 12장 요약

def slide12(prs):
    sl = S.add_slide(prs)
    S.header(
        sl,
        "요약 — Qdrant를 건드리는 곳은 세 군데뿐",
        "파이프라인을 걷어내고 접점만 남긴 그림 · 아래 두 막대는 눈금이 서로 다르다",
    )

    cards = [
        ("① 세션 확보", "0 · 1 · 17회",
         ["캐시에 있으면 0회 — 준비 요청 자체가 없다",
          "빠지면 1회 — registry 포인트 1개를 조회한다",
          "처음이면 17회 — 컬렉션 2개와 색인 11개를 만든다"]),
        ("② 벡터 upsert", "1회",
         ["저장 요청 1건당 항상 1회",
          "에피소드를 몇 건 담아 보내든 1회로 고정된다",
          "PUT …/points — 벡터와 payload를 써 넣는다"]),
        ("③ ANN 탐색", "1회",
         ["검색 요청 1건당 항상 1회",
          "top_k와 필터, 문맥 확장을 바꿔도 1회다",
          "POST …/points/query/batch — 유사도 탐색"]),
    ]
    for i, (title, big, lines) in enumerate(cards):
        x = 0.45 + i * 4.24
        S.box(sl, x, 1.15, 3.95, 2.25, [""], kind="store")
        S.badge(sl, x + 3.95 - 0.30, 1.09, "yes")
        S.text(sl, x + 0.18, 1.26, 3.4, 0.26, title, size=13, bold=True)
        S.text(sl, x + 0.18, 1.62, 3.6, 0.50, big, size=27, bold=True, color=S.NAVY)
        for j, line in enumerate(lines):
            S.text(sl, x + 0.18, 2.30 + j * 0.24, 3.65, 0.20, line, size=9, wrap=True)
        S.rect(sl, x + 0.18, 3.06, 3.60, 0.01, S.STORE_L)
        S.text(sl, x + 0.18, 3.14, 3.60, 0.20,
               ["저장 · 검색 공통", "저장 경로", "검색 경로"][i],
               size=8.5, color=S.FOOT)

    S.text(sl, M, 3.52, FULL, 0.20,
           "나머지 단계는 Qdrant를 부르지 않는다. 원문 저장과 문맥 walk, 원문 복원은 PostgreSQL이고 "
           "세그먼트화와 필터 파싱, 리랭킹, 결과 조립은 프로세스 안에서 끝나며 임베딩은 별도 API다.",
           size=9, color=S.GRAY)

    S.panel(sl, M, 3.80, 5.95, 1.55, style="info", radius=0.08)
    S.text(sl, 0.60, 3.88, 5.6, 0.22, "평상시   눈금 0~4 ms", size=11, bold=True)
    for i, (label, ms, frac) in enumerate([
        ("벡터 upsert — 저장 1건", "3.0 ms", 3.0 / 4.0),
        ("ANN 탐색 — 검색 1건", "2.0 ms", 2.0 / 4.0),
        ("재준비 1회 — registry 조회", "1.5 ms", 1.5 / 4.0),
    ]):
        _bar(sl, 0.60, 1.85, 2.55, 2.45, 4.22 + i * 0.35, frac, label, ms)

    S.panel(sl, 6.93, 3.80, 5.95, 1.55, style="info", radius=0.08)
    S.text(sl, 7.08, 3.88, 5.6, 0.22, "세션 등록   눈금 0~900 ms", size=11, bold=True)
    _bar(sl, 7.08, 1.85, 9.03, 2.45, 4.22, 850 / 900,
         "첫 세션 17회", "850 ms", fill=S.API_L)
    _bar(sl, 7.08, 1.85, 9.03, 2.45, 4.57, 47 / 900,
         "두 번째 세션부터 17회", "47 ms")
    S.text(sl, 7.08, 4.98, 5.70, 0.20,
           "850ms의 78%는 색인 생성 11회(667ms), 19%는 컬렉션 생성 2회(165ms)다",
           size=8.5, color=S.FOOT)

    S.conclusion(sl, M, 5.45, FULL, 1.55, [
        ("평상시 Qdrant 부담은 요청당 2~3ms다.",
         " 저장도 검색도 요청 1회로 고정이고, 옵션을 바꿔도 늘지 않는다."),
        ("17회라는 숫자는 크지만 시간은 두 번째 세션부터 47ms다.",
         " 850ms는 컬렉션과 색인을 실제로 만드는 첫 한 번뿐이다."),
        ("그래서 세션이 늘 때 걱정할 곳은 등록 시간이 아니라",
         " 캐시 100칸이 찬 뒤 유휴 세션이 밀려나 재준비가 상시화되는 쪽이다."),
        ("다만 이 값은 같은 장비 기준이다.",
         " Qdrant를 다른 노드에 두면 요청마다 네트워크 왕복이 그대로 더해진다."),
    ], size=10, gap=0.26)
    S.footer(sl, "근거: 측정 기록 2부(S1~S13) · qdrant_request_trace.json · 보고서 6부. "
                 "기준 커밋 a8322a7, qdrant 1.17.0 + postgres 16.", y=7.10)


def main():
    prs = S.new_deck()
    for fn in (slide4, slide5, slide6, slide7, slide8, slide9, slide10,
               slide11, slide12):
        fn(prs)
    prs.save(OUT)
    print(f"saved {OUT}: {len(prs.slides._sldIdLst)} slides")


if __name__ == "__main__":
    main()
