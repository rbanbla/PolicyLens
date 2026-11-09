import json
import re
from django.conf import settings
from django.core.management.base import BaseCommand


def near(text, first, second, reach=300):
    return re.search(f'(?s)(?:{first}).{{0,{reach}}}(?:{second})|(?:{second}).{{0,{reach}}}(?:{first})', text) is not None


def final_text(run):
    return json.dumps(run['steps'][-1]['result']['items'], ensure_ascii=False)


class Command(BaseCommand):
    help = '평가 결과가 정답 초안의 쟁점을 언급하는지 키워드로 센다. 사람 채점을 대신하지 않는다.'

    def handle(self, *args, **options):
        reviewed = settings.BASE_DIR / 'data' / 'reviewed'
        gold = [json.loads(line) for line in (reviewed / 'annotations.jsonl').read_text(encoding='utf-8').splitlines()]
        for doc in gold:
            for path in sorted((reviewed / 'runs').glob(f'{doc["doc_id"]}-*.json')):
                run = json.loads(path.read_text(encoding='utf-8'))
                roles = json.dumps(run['analysis'], ensure_ascii=False)
                people = [item['group'] for item in doc['stakeholders'] if re.search(item['match'], roles)]
                for name, text in ((run['arm'], final_text(run)), ('단일 프롬프트', run['baseline'])):
                    found = [item['issue_id'] for item in doc['issues'] if near(text, *item['match'])]
                    self.stdout.write(f'{doc["doc_id"]}\t{name}\t{len(found)}/{len(doc["issues"])}\t{",".join(found)}')
                self.stdout.write(f'{doc["doc_id"]}\t{run["arm"]} 이해관계자\t{len(people)}/{len(doc["stakeholders"])}\t호출 {len(run["calls"])}회')
