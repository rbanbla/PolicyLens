import json
import random
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from django.core.management.base import BaseCommand
from server.models import Persona

ROWS_URL = 'https://datasets-server.huggingface.co/rows'
DATASET = 'nvidia/Nemotron-Personas-Korea'
TOTAL = 1_000_000
PAGE = 100  # The rows API returns at most 100 rows a request.
FIELDS = [field.name for field in Persona._meta.fields if field.name != 'id']


class Command(BaseCommand):
    help = 'NVIDIA Nemotron-Personas-Korea(CC BY 4.0)에서 무작위 표본을 받아 Persona 테이블에 적재한다.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=3000, help='받을 인물 수(100 단위)')
        parser.add_argument('--seed', type=int, default=0)

    def handle(self, count, seed, **options):
        offsets = random.Random(seed).sample(range(0, TOTAL, PAGE), max(1, count // PAGE))
        skipped = 0
        for offset in offsets:
            query = urlencode({'dataset': DATASET, 'config': 'default', 'split': 'train', 'offset': offset, 'length': PAGE})
            rows = None
            for attempt in range(4):  # The rows API returns 502, 503 or 429 now and then; the same request works again after a pause.
                try:
                    with urlopen(Request(f'{ROWS_URL}?{query}', headers={'User-Agent': 'policylens-loader'}), timeout=60) as response:
                        rows = json.load(response)['rows']
                    break
                except URLError:
                    time.sleep(5 * 2 ** attempt)
            time.sleep(1)
            if rows is None:
                skipped += 1  # Run again later: rows already stored are kept and not duplicated.
                continue
            Persona.objects.bulk_create([Persona(**{field: row['row'][field] for field in FIELDS}) for row in rows], ignore_conflicts=True)
        self.stdout.write(f'전체 {Persona.objects.count()}명, 받지 못한 구간 {skipped}개')
