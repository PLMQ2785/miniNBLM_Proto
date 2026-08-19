"""Generate compact work and education PDFs for retrieval regression evaluation."""

from pathlib import Path

import fitz


DOCUMENTS = {
    "evaluation/retrieval_work_incident_response.pdf": (
        (
            "SEV-1 분류와 접수",
            "고객 대상 서비스의 30% 이상이 중단되거나 데이터 유출이 확인되면 SEV-1으로 분류한다. "
            "당직 담당자는 경보를 받은 뒤 10분 안에 ACK를 남기고 전용 incident channel을 개설한다. "
            "단순 지연이나 내부 개발 환경 장애는 같은 기준을 자동으로 충족하지 않는다.",
        ),
        (
            "격리와 증거 보존",
            "침해가 의심되는 호스트는 먼저 네트워크에서 격리한다. 재설치나 초기화 전에 메모리, 디스크, "
            "감사 로그를 보존해야 한다. 증거 수집이 끝나기 전에 로그를 삭제하거나 장비를 reimage하면 원인 "
            "분석이 불가능해질 수 있다. 자격 증명 회전은 증거 보존과 영향 범위 확인을 조정해 수행한다.",
        ),
        (
            "복구 승인 기준",
            "변경 담당자와 incident commander가 함께 승인한 경우에만 rollback 또는 정상 트래픽 복귀를 "
            "진행한다. 복귀 후 오류율이 30분 연속 1% 미만이어야 복구 완료로 판정한다. 30분 중 한 번이라도 "
            "1% 이상이면 관찰 시간을 처음부터 다시 계산한다.",
        ),
        (
            "사후 검토",
            "SEV-1 종료 후 2영업일 안에 비난 없는 post-incident review 초안을 작성한다. 각 개선 항목에는 "
            "한 명의 owner와 완료 기한을 기록한다. 원인 설명만 있고 담당자나 기한이 없는 항목은 완료된 "
            "action item으로 인정하지 않는다.",
        ),
    ),
    "evaluation/retrieval_work_procurement.pdf": (
        (
            "견적 비교 기준",
            "부가세를 제외한 구매 예정 금액이 100만원 미만이면 한 개의 가격 근거로 소액 구매할 수 있다. "
            "100만원 이상 500만원 미만은 세 곳의 서면 견적을 비교한다. 500만원 이상은 구매위원회 사전 "
            "승인이 필요하다. 주문을 나누어 기준을 피하는 행위는 금지한다.",
        ),
        (
            "이해충돌 회피",
            "요청자나 평가자가 공급업체와 가족, 투자 또는 최근 고용 관계가 있으면 평가 전에 서면으로 "
            "공개해야 한다. 이해충돌 당사자는 점수 부여와 업체 선정에서 빠지고 독립된 대체 평가자가 "
            "검토한다. 공개만 하고 평가를 계속하는 것은 충분하지 않다.",
        ),
        (
            "단독 공급 예외",
            "대체 공급자가 없는 단독 구매는 기술적 사유, 시장 조사 기록과 재무 책임자의 사전 승인을 "
            "남겨야 한다. 일정이 촉박하다는 사정만으로 단독 공급 예외가 자동 승인되지는 않는다. 승인과 "
            "근거는 발주서를 보내기 전에 완료해야 한다.",
        ),
        (
            "3-way match 지급 통제",
            "대금 지급 전 구매 주문서(PO), 검수 또는 입고 기록, 공급업체 invoice의 품목과 수량, 금액을 "
            "3-way match로 대조한다. 세 자료가 일치하지 않으면 지급을 보류하고 차이를 해결한다. invoice만 "
            "도착한 상태에서는 지급 승인할 수 없다.",
        ),
    ),
    "evaluation/retrieval_education_course_policy.pdf": (
        (
            "출석과 공결",
            "수료하려면 실시간 수업의 80% 이상에 출석해야 한다. 질병이나 공적 행사로 결석한 학습자는 "
            "결석일로부터 7일 안에 증빙을 제출해야 공결 심사를 받을 수 있다. 공결 승인은 출석률 계산에서 "
            "해당 시간을 제외하지만 과제 제출 의무까지 없애지는 않는다.",
        ),
        (
            "지각 제출과 연장",
            "사전 승인 없이 늦은 과제는 달력일 기준 하루마다 10%를 감점하고 3일이 지나면 접수하지 않는다. "
            "마감 전에 승인된 extension에는 승인된 새 마감일까지 감점을 적용하지 않는다. 마감 후 요청은 "
            "문서화된 긴급 사유가 있을 때만 별도 심사한다.",
        ),
        (
            "동료 검토 수정",
            "프로젝트 초안은 서로 다른 동료 두 명의 peer review를 받아야 한다. 학습자는 피드백별 반영 또는 "
            "미반영 이유를 revision note에 기록하고 마지막 검토를 받은 뒤 48시간 안에 수정본을 제출한다. "
            "댓글 수만 채우고 revision note가 없으면 검토 절차를 완료한 것으로 보지 않는다.",
        ),
        (
            "대체 시험",
            "make-up exam은 문서로 확인되는 질병, 가족상 또는 시스템 장애로 정규 시험에 참여하지 못한 "
            "경우에만 허용한다. 학습자는 정규 시험일로부터 5영업일 안에 신청해야 하며 담당 교원이 별도 "
            "시간과 동등한 난이도의 시험을 지정한다. 단순한 일정 착오는 허용 사유가 아니다.",
        ),
    ),
    "evaluation/retrieval_work_data_governance.pdf": (
        (
            "정보 분류",
            "정보는 Public, Internal, Confidential, Restricted 네 등급으로 분류한다. 공개된 홍보물은 Public, "
            "일반 사내 절차는 Internal, 계약과 미공개 재무 정보는 Confidential이다. 인증 정보, 정부 식별번호, "
            "원본 고객 녹취는 가장 높은 Restricted 등급으로 취급한다.",
        ),
        (
            "Restricted 자료 공유",
            "Restricted 자료는 이름이 지정된 수신자에게만 MFA가 적용된 암호화 링크로 공유한다. 링크 만료 "
            "시간은 최대 24시간이다. 전자우편 첨부나 공개 링크는 허용하지 않는다. 외부 수신자가 필요하면 "
            "자료 소유자의 승인도 공유 전에 받아야 한다.",
        ),
        (
            "고객 녹취 보존",
            "고객 지원 원본 녹취의 기본 보존 기간은 생성일부터 90일이며 이후 자동 삭제한다. 법무 부서가 "
            "legal hold를 발행하면 보존 기간이 지나도 삭제하지 않고 해제 통지를 받을 때까지 보존한다. "
            "분석용 익명 통계에는 원본 녹취 보존 기간을 그대로 적용하지 않는다.",
        ),
        (
            "노출 의심 신고",
            "Restricted 정보 노출이 의심되면 확정 여부를 기다리지 말고 발견 후 15분 안에 SOC에 신고한다. "
            "신고자는 관련 시스템과 시간을 기록하되 자체 조사 목적으로 로그를 삭제하거나 파일을 수정하지 "
            "않는다. SOC가 incident commander와 증거 수집 절차를 지정한다.",
        ),
    ),
    "evaluation/retrieval_work_hard_negatives.pdf": (
        (
            "SEV-2 성능 저하 훈련 예시",
            "고객 요청의 30%가 평소보다 느리지만 중단이나 데이터 유출이 없는 성능 저하는 SEV-2 훈련 "
            "사례로 분류한다. 교육용 연습에서는 당직자가 30분 안에 ACK하고 일반 support channel을 "
            "사용한다. 이 수치는 실제 SEV-1 중단 기준과 접수 시한을 대체하지 않는다.",
        ),
        (
            "정기 점검 reimage 절차",
            "보안 침해 징후가 없는 개발용 장비의 정기 점검에서는 설정 파일을 백업한 뒤 즉시 reimage할 "
            "수 있다. 메모리와 디스크 포렌식 보존은 요구하지 않는다. 침해가 의심되는 운영 호스트에는 "
            "이 간소화 절차를 적용하지 않는다.",
        ),
        (
            "Staging 복구 관찰",
            "staging 환경 배포는 담당 개발자 한 명의 승인으로 rollback할 수 있다. 오류율이 10분 연속 "
            "1% 미만이면 staging 검증을 완료한다. 운영 트래픽 복귀에 필요한 공동 승인과 30분 관찰에는 "
            "이 짧은 기준을 사용할 수 없다.",
        ),
        (
            "폐기된 구매 교육 예제",
            "과거 교육 자료는 320만원 구매에 두 곳의 견적만 받는 예시를 사용했다. 이 예시는 폐기되었고 "
            "현행 구매 정책이 아니다. 실제 발주에서는 현재 승인된 견적 구간과 필요한 서면 견적 수를 "
            "확인해야 한다.",
        ),
        (
            "커뮤니티 출석 배지",
            "선택형 학습 커뮤니티는 참여율 80%와 가입 후 7일 이내 프로필 작성을 배지 조건으로 사용한다. "
            "이 배지는 정규 과정 수료 출석률, 질병 공결 증빙, 과제 제출 의무와 관계가 없다.",
        ),
        (
            "Confidential 공유 링크",
            "Confidential 자료는 승인된 사내 구성원에게 최대 72시간 유효한 암호화 링크로 공유할 수 있다. "
            "Restricted 자료는 더 엄격한 별도 정책을 따르므로 이 72시간 기준을 적용하면 안 된다.",
        ),
        (
            "익명 분석 통계 보존",
            "고객 녹취에서 개인 식별 정보와 원본 음성을 제거한 익명 집계 통계는 365일 보존할 수 있다. "
            "이 기간은 Restricted 등급의 원본 고객 녹취 90일 보존이나 legal hold 예외를 변경하지 않는다.",
        ),
        (
            "보안 모의훈련 보고",
            "사전 공지된 모의훈련 이벤트는 연습 시작 후 60분 안에 training desk로 결과를 보고한다. 실제 "
            "Restricted 정보 노출 의심은 이 연습 시한을 사용하지 않고 운영 SOC 신고 정책을 따른다.",
        ),
    ),
}


def generate_document(output: Path, pages: tuple[tuple[str, str], ...]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for page_number, (title, body) in enumerate(pages, start=1):
        page = document.new_page(width=595, height=842)
        page.insert_text(
            (48, 62),
            f"업무·교육 retrieval fixture {page_number}",
            fontname="korea",
            fontsize=11,
        )
        page.insert_text((48, 105), title, fontname="korea", fontsize=22)
        remaining = page.insert_textbox(
            fitz.Rect(48, 145, 547, 760),
            body,
            fontname="korea",
            fontsize=12,
            lineheight=1.5,
        )
        if remaining < 0:
            raise RuntimeError(f"Fixture text did not fit: {title}")
    document.set_metadata(
        {
            "title": output.stem,
            "author": "miniNBLM evaluation generator",
        }
    )
    document.save(output, garbage=4, deflate=True)
    document.close()


if __name__ == "__main__":
    for path, pages in DOCUMENTS.items():
        generate_document(Path(path), pages)
