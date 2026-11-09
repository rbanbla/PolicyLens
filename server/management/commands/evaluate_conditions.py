import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from server.agents.tools.policy_facts import evaluate_condition


class Command(BaseCommand):
    help = '모델 호출 없이 조건 평가 사례의 예상 결과를 확인한다. 합성 사례는 정책 정확도 평가가 아니다.'

    def add_arguments(self, parser):
        parser.add_argument('--cases', required=True)

    def handle(self, *args, cases, **options):
        try:
            rows = [json.loads(line) for line in Path(cases).read_text(encoding='utf-8').splitlines() if line.strip()]
            if not rows:
                raise ValueError('평가 사례가 없습니다.')
            passed, synthetic, ids = 0, 0, set()
            for row in rows:
                if row['case_id'] in ids or row['expected'] not in ('met', 'not_met', 'unknown'):
                    raise ValueError('중복 사례 ID 또는 잘못된 예상 결과입니다.')
                ids.add(row['case_id'])
                if row['kind'] == 'synthetic':
                    synthetic += 1
                elif row['kind'] != 'reviewed' or not row.get('reviewed_by') or not row.get('evidence'):
                    raise ValueError('실제 정책 평가에는 검수자·근거가 필요합니다.')
                status = evaluate_condition(row['condition'], row['context'])['status']
                passed += status == row['expected']
                if status != row['expected']:
                    self.stdout.write(f"{row['case_id']}: expected={row['expected']} actual={status}")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError(f'조건 평가 실패: {exc}') from exc
        self.stdout.write(f'{passed}/{len(rows)} 통과 (합성 {synthetic}, 검수 표기 {len(rows)-synthetic}). 정책 정답 검수는 별도입니다.')
        if passed != len(rows):
            raise CommandError('예상 결과와 다른 조건이 있습니다.')
