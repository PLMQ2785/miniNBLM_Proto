"""Generate a Korean multi-page PDF for upload and RAG citation testing."""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz


PAGE = fitz.paper_rect("a4")
INK = (0.11, 0.16, 0.23)
MUTED = (0.36, 0.42, 0.49)
NAVY = (0.06, 0.22, 0.36)
TEAL = (0.04, 0.53, 0.50)
PALE = (0.92, 0.97, 0.96)
WHITE = (1, 1, 1)


PAGES = [
    {
        "section": "교육 개요",
        "title": "병동 낙상 예방 간호 가이드",
        "lead": "이 문서는 신규 간호사의 교육과 RAG 검색 기능 점검을 위해 만든 가상의 학습 자료입니다.",
        "blocks": [
            (
                "학습 목표",
                "낙상 위험요인을 구분하고, 입원 시 위험도를 평가하며, 환자별 예방 중재와 사고 후 보고 절차를 설명할 수 있다.",
            ),
            (
                "핵심 원칙",
                "낙상 예방은 환경 정비만으로 끝나지 않는다. 위험도 평가, 환자·보호자 교육, 교대 간 인계, 상태 변화 시 재평가가 하나의 과정으로 연결되어야 한다.",
            ),
            (
                "가상 병동 기준",
                "이 자료에서 고위험군 식별 표시는 청록색 삼각 스티커로 통일한다. 이 표시는 실제 의료기관 지침이 아니라 검색 테스트를 위한 가상 규칙이다.",
            ),
        ],
        "check": "확인 질문: 고위험군을 나타내는 가상의 표식은 무엇인가?",
    },
    {
        "section": "1. 위험도 평가",
        "title": "언제, 무엇을 평가할까요?",
        "lead": "위험도 평가는 입원 직후뿐 아니라 환자의 상태와 치료 환경이 달라질 때 반복해야 합니다.",
        "blocks": [
            (
                "평가 시점",
                "입원 후 2시간 이내에 최초 평가를 시행한다. 이후 매일 오전 근무 시작 시, 병실 이동 후, 진정제 투여 후, 수술·시술 후 보행을 재개할 때 다시 평가한다.",
            ),
            (
                "주요 위험요인",
                "최근 3개월 이내 낙상 경험, 보행 불안정, 어지럼, 인지 저하, 시력 저하, 잦은 배뇨, 수면제·진정제·혈압강하제 사용 여부를 확인한다.",
            ),
            (
                "기록 원칙",
                "점수만 입력하지 말고 관찰된 위험요인과 필요한 도움 수준을 간호기록에 함께 남긴다. 상태 변화로 재평가했다면 변화 원인도 기록한다.",
            ),
        ],
        "check": "확인 질문: 최초 낙상 위험도 평가는 입원 후 몇 시간 이내에 시행하는가?",
    },
    {
        "section": "2. 예방 중재",
        "title": "위험 수준에 맞춘 행동",
        "lead": "모든 환자에게 기본 중재를 적용하고, 고위험 환자에게는 관찰과 이동 보조를 강화합니다.",
        "blocks": [
            (
                "모든 환자",
                "침상은 가장 낮은 위치에 두고 바퀴를 잠근다. 호출벨과 자주 쓰는 물건은 손이 닿는 곳에 둔다. 바닥의 물기와 이동 동선을 확인하고 미끄럼 방지 신발을 안내한다.",
            ),
            (
                "고위험 환자",
                "첫 보행 전 담당 간호사가 기립성 어지럼 여부를 확인한다. 야간에는 2시간 간격으로 필요를 확인하며, 화장실 이동 시 반드시 직원에게 도움을 요청하도록 설명한다.",
            ),
            (
                "교육 확인",
                "환자에게 설명한 뒤 환자 자신의 말로 주의사항을 다시 말하게 하는 되말하기 방식으로 이해도를 확인한다. 보호자가 있으면 동일한 내용을 함께 교육한다.",
            ),
        ],
        "check": "확인 질문: 야간 고위험 환자의 필요는 몇 시간 간격으로 확인하는가?",
    },
    {
        "section": "3. 사고 후 대응",
        "title": "낙상 발생 시 대응 순서",
        "lead": "환자를 바로 일으키기 전에 손상 가능성을 먼저 확인하고, 평가·보고·재발 방지를 순서대로 수행합니다.",
        "blocks": [
            (
                "즉시 조치",
                "환자를 임의로 이동시키지 말고 의식, 호흡, 통증, 출혈과 사지 변형을 확인한다. 필요한 응급 도움을 요청하고 활력징후를 측정한다.",
            ),
            (
                "보고와 관찰",
                "담당 의사와 책임 간호사에게 즉시 알리고 기관 절차에 따라 사고 보고서를 작성한다. 머리 충격이 의심되면 의식 수준과 신경학적 상태를 처방 및 병동 기준에 따라 관찰한다.",
            ),
            (
                "재발 방지",
                "사고 발생 후 30분 이내에 낙상 위험도를 재평가한다. 발생 장소, 시간, 당시 활동, 환경 요인을 팀과 공유하고 예방 계획을 수정한다.",
            ),
        ],
        "check": "확인 질문: 사고 후 위험도 재평가는 몇 분 이내에 시행하는가?",
    },
]


def add_text(page: fitz.Page, rect: fitz.Rect, text: str, size: float, color=INK) -> None:
    remaining = page.insert_textbox(
        rect,
        text,
        fontname="korea",
        fontsize=size,
        lineheight=1.35,
        color=color,
    )
    if remaining < 0:
        raise RuntimeError(f"Text did not fit on page {page.number + 1}: {text[:30]}")


def render_page(doc: fitz.Document, content: dict[str, object], page_number: int) -> None:
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    page.draw_rect(page.rect, color=WHITE, fill=WHITE)
    page.draw_rect(fitz.Rect(0, 0, PAGE.width, 118), color=NAVY, fill=NAVY)
    page.draw_rect(fitz.Rect(0, 0, 12, PAGE.height), color=TEAL, fill=TEAL)

    add_text(page, fitz.Rect(42, 28, 550, 54), str(content["section"]), 10.5, TEAL)
    add_text(page, fitz.Rect(42, 57, 550, 100), str(content["title"]), 24, WHITE)
    add_text(page, fitz.Rect(42, 140, 550, 190), str(content["lead"]), 11.5, MUTED)

    y = 210
    for heading, body in content["blocks"]:  # type: ignore[union-attr]
        box = fitz.Rect(42, y, 553, y + 118)
        page.draw_rect(box, color=(0.82, 0.87, 0.89), fill=(0.98, 0.99, 0.99), radius=0.08)
        page.draw_rect(fitz.Rect(42, y, 49, y + 118), color=TEAL, fill=TEAL)
        add_text(page, fitz.Rect(66, y + 16, 530, y + 42), heading, 13, NAVY)
        add_text(page, fitz.Rect(66, y + 49, 530, y + 103), body, 10.5, INK)
        y += 134

    check_rect = fitz.Rect(42, 626, 553, 687)
    page.draw_rect(check_rect, color=TEAL, fill=PALE, radius=0.08)
    add_text(page, fitz.Rect(61, 645, 534, 675), str(content["check"]), 10.5, NAVY)

    disclaimer = "교육·검색 테스트용 가상 자료이며 실제 의료기관 지침을 대체하지 않습니다."
    add_text(page, fitz.Rect(42, 756, 500, 780), disclaimer, 8.5, MUTED)
    add_text(page, fitz.Rect(485, 756, 553, 780), f"{page_number} / {len(PAGES)}", 8.5, MUTED)


def generate(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for number, content in enumerate(PAGES, start=1):
        render_page(doc, content, number)
    doc.set_metadata(
        {
            "title": "병동 낙상 예방 간호 가이드",
            "author": "miniNBLM sample generator",
            "subject": "RAG upload and page citation test fixture",
            "keywords": "간호, 낙상 예방, 샘플, RAG",
        }
    )
    doc.save(output, garbage=4, deflate=True)
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("sample_fall_prevention.pdf"),
    )
    args = parser.parse_args()
    generate(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
