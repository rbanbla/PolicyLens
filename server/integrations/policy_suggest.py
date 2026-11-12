import datetime
import html
import re
import xml.etree.ElementTree as ET
import zlib
from urllib.parse import urlencode
from urllib.request import urlopen
from django.utils.translation import gettext as _
from server.integrations.transport import setting


#####정책브리핑 에서 정책 불러오는 코드
NEWS_URL = 'https://apis.data.go.kr/1371000/policyNewsService2/policyNewsList2'
LOOKBACK = 10  


def news_window(start, end):
    query = urlencode({'serviceKey': setting('NEWEST_POLICY_KEY'), 'startDate': f'{start:%Y%m%d}',
                       'endDate': f'{end:%Y%m%d}', 'numOfRows': 100})
    with urlopen(f'{NEWS_URL}?{query}', timeout=10) as response:
        try:
            root = ET.fromstring(response.read())
        except ET.ParseError as exc:
            raise ValueError(_('정책브리핑 응답을 읽을 수 없습니다.')) from exc
    if root.findtext('header/resultCode') != '0':
        raise ValueError(_('정책브리핑 조회에 실패했습니다: %(reason)s') % {
            'reason': root.findtext('header/resultMsg') or root.findtext('cmmMsgHeader/returnAuthMsg') or ''})
    return root.findall('body/NewsItem')


def plain(markup):
    text = re.sub(r'<br\s*/?>|</p>', '\n', markup or '', flags=re.I)
    text = html.unescape(re.sub(r'<[^>]+>', '', text))
    return re.sub(r'\n\s*\n+', '\n\n', text).strip()


def newest_youth_policies(k=3, today=None):

    end, found = today or datetime.date.today(), {}
    for _window in range(LOOKBACK):
        start = end - datetime.timedelta(days=2)
        for item in news_window(start, end):
            title = plain(item.findtext('Title'))
            if '청년' not in title:
                continue
            category = item.findtext('MinisterCode') or ''
            found[item.findtext('NewsItemId')] = {
                'id': item.findtext('NewsItemId'), 'title': title, 'category': category,
                'hue': zlib.crc32(category.encode()) % 360,  # Same ministry, same color.
                'approved': datetime.datetime.strptime(item.findtext('ApproveDate'), '%m/%d/%Y %H:%M:%S'),
                'text': '\n\n'.join(filter(None, [title, plain(item.findtext('SubTitle1')), plain(item.findtext('DataContents'))])),
            }
        if len(found) >= k:
            break
        end = start - datetime.timedelta(days=1)
    return sorted(found.values(), key=lambda policy: policy['approved'], reverse=True)[:k]
