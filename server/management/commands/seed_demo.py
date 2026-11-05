from django.core.management.base import BaseCommand
from django.db import transaction
from server.models import MockTurn, MockRevision
from server.application.cases import register


class Command(BaseCommand):
    help = "공개용 모의 정책과 쟁점 해설을 등록합니다."

    @transaction.atomic
    def handle(self, *args, **options):
        quote = "과제에 사용한 AI 도구를 공개한다."
        document = "\n\n".join(["제1조 목적\n이 지침은 글쓰기 수업의 AI 사용 기준을 정한다.",
                                 "제2조 공개\n" + quote,
                                 "제3조 평가\n담당 교수는 학생이 구성한 논거의 배열과 타당성을 평가한다."])
        issue = {
            "question":"맞춤법 교정과 문단 재배열을 똑같이 기록해야 할까?",
            "interpretation_one":"도구 이름을 적으면 공개 의무를 충족한다. 두 작업에 같은 도구를 쓴 학생은 한 줄만 제출하면 된다.",
            "interpretation_two":"도구 이름만으로는 논리 구성을 누가 했는지 알 수 없다. 평가 대상인 문단 순서를 바꿨다면 그 부분까지 표시해야 한다.",
            "consequence":"첫 해석은 제출 부담을 줄이지만 채점자가 학생의 기여를 구별하기 어렵다. 두 번째 해석을 사후에 적용하면, 공지에 없던 기록을 빠뜨렸다는 이유로 학생이 불이익을 받을 수 있다.",
        }
        case, _ = register(document, {"title":"글쓰기 과제 AI 사용 지침", "source":"PolicyLens 모의 정책",
            "situation":"학생은 AI로 맞춤법을 고친 뒤, 같은 도구가 제안한 문단 순서까지 반영했다. 제출물에는 도구 이름을 적었다.",
            "learning_goal":"학생이 직접 구성한 논거의 배열과 타당성", "question":issue["question"],
            "clauses":[{"location":"제2조 · 공개","quote":quote,"issue":issue}]})
        clause = case.clauses.get(key="C1")
        for role, statement in [("student","허용 범위를 미리 알려 주면 교정은 체크하고, 논리 구조를 바꾼 부분만 따로 표시할 수 있다."),
                                ("administration","수업마다 사후 기준이 달라지면 문의를 처리하기 어렵다. 필요한 기록은 과제 안내에 먼저 명시해야 한다."),
                                ("faculty","도구명만으로는 문단 순서를 학생이 결정했는지 확인하기 어렵다.")]:
            MockTurn.objects.get_or_create(clause=clause, role=role, defaults={"statement":statement})
        MockRevision.objects.get_or_create(turn=clause.mock_turns.get(role="faculty"), defaults={
            "wording":"사용한 AI 도구를 밝힌다. 논거 또는 문단 배열을 변경했다면 반영한 부분을 함께 표시한다.",
            "reason":"단순 교정의 기록 부담을 낮추고, 평가 대상인 논리 구성에 AI가 기여한 범위를 확인할 수 있다."})
        case.published = True
        case.save(update_fields=["published"])
        self.stdout.write(f"공개 모의 정책 ID {case.pk}")
