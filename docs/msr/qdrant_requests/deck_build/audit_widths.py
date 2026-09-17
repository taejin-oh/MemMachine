"""덱의 텍스트가 도형 폭을 넘치는지 검사한다.

사용법: python audit_widths.py <파일.pptx> [경고기준]
- 실제 글꼴(Apple SD Gothic Neo / Menlo) 메트릭으로 줄 폭을 계산한다.
- 원본 덱 기준 비율 1.05까지는 정상 렌더되지만, 안전선은 0.95다.
- 비율 1.0을 넘는 줄이 있으면 종료 코드 1.
"""

import sys

from pptx import Presentation
from pptx.util import Emu
from PIL import ImageFont

KR_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
MONO_PATH = "/System/Library/Fonts/Menlo.ttc"
_cache = {}


def font(name, pt):
    key = (name, round(pt))
    if key not in _cache:
        path = MONO_PATH if (name or "").startswith("Menlo") else KR_PATH
        _cache[key] = ImageFont.truetype(path, max(6, round(pt)))
    return _cache[key]


def rows_for(path):
    prs = Presentation(path)
    out = []
    for si, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            if not sh.has_text_frame or not sh.text_frame.text.strip() or sh.width is None:
                continue
            tf = sh.text_frame
            ml = Emu(tf.margin_left).inches if tf.margin_left is not None else 0.1
            mr = Emu(tf.margin_right).inches if tf.margin_right is not None else 0.1
            avail = (Emu(sh.width).inches - ml - mr) * 72
            if avail <= 0:
                continue
            for para in tf.paragraphs:
                if not para.runs:
                    continue
                width = sum(
                    font(r.font.name, r.font.size.pt if r.font.size else 11).getlength(r.text)
                    for r in para.runs
                )
                txt = "".join(r.text for r in para.runs)
                out.append(
                    {
                        "slide": si,
                        "ratio": width / avail,
                        "wrap": tf.word_wrap,
                        "shape": sh.name,
                        "text": txt,
                        "w": round(width),
                        "avail": round(avail),
                    }
                )
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    warn = float(sys.argv[2]) if len(sys.argv) > 2 else 0.95
    rows = rows_for(path)
    rows.sort(key=lambda r: r["ratio"], reverse=True)

    flagged = [r for r in rows if r["ratio"] > warn]
    over = [r for r in rows if r["ratio"] > 1.0]

    print(f"{path}: 텍스트 {len(rows)}줄 검사")
    if not flagged:
        print(f"  모든 줄이 안전선 {warn} 이하")
    for r in flagged:
        mark = "넘침" if r["ratio"] > 1.0 else "빠듯"
        wrapped = " (자동줄바꿈)" if r["wrap"] is True else ""
        print(
            f"  s{r['slide']} {r['ratio']:5.2f} {mark}{wrapped} "
            f"{r['w']}/{r['avail']}pt [{r['shape']}] {r['text'][:60]}"
        )

    hard = [r for r in over if r["wrap"] is not True]
    print(f"  요약: 비율>1.0 {len(over)}줄, 그중 줄바꿈 없음 {len(hard)}줄")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
