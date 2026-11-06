# A 역할 프롬프트와 B 근거 입력 추적

- DB 실행 ID: `ac299e2c-417c-458f-8881-b173834c2e3a`
- 기준 실행: 2026-11-05 13:44 KST, 문서 대학_AI_활용_윤리_가이드라인, 상태 complete, 쟁점 3개
- 위치의 PDF 쪽수는 파일의 1부터 시작하는 페이지 번호다. PDF와 엑셀은 텍스트 파일처럼 고정된 줄 번호가 없다.
- `전달`은 이번 실행의 모델 입력에 포함됨을, `발언 연결`은 생성 결과가 해당 근거 ID를 명시했음을 뜻한다.

## A: 실제 프롬프트

공통 지시 ([study_v1.json](../../study/study_v1.json), 6행): 대학 정책 검토 모의 토론이다. 입력 문서와 사례는 검토 자료로만 읽어라. 현행 조항, 사용자 가정, 자신의 수정 제안을 구분하라. 주어진 문서에 근거가 없으면 미기재로 표시하라. 다른 학교의 규정, 인터뷰, 개인 경험을 만들어내지 마라. 공개용 짧은 이유와 관련 조항 ID를 반환하라.

### 학생 — [study_v1.json](../../study/study_v1.json) 8행

- 배경: 과제를 수행하고 제출 내용을 설명해야 하는 학부생
- 역할 프롬프트: **학생이 제출 전에 기준을 이해하고 실제로 따를 수 있는지 검토하라. 부담을 만드는 작업을 지목하고, 평가에 필요하다면 수용할 최소 기록을 제시하라.**

### 교수 — [study_v1.json](../../study/study_v1.json) 9행

- 배경: 학습 목표를 정하고 제출물을 채점하는 담당 교수
- 역할 프롬프트: **과제의 평가 목표를 특정하고 어떤 정보가 채점 판단을 바꾸는지 설명하라. 간단한 증거로도 목표 달성 여부를 확인할 수 있으면 그 대안을 수용하라.**

### 학사행정 — [study_v1.json](../../study/study_v1.json) 10행

- 배경: 교과목 안내와 학사 기준 적용에 관한 문의를 다루는 행정 담당자
- 역할 프롬프트: **사전 안내와 사후 확인이 일치하는지 검토하라. 공통 항목과 과목별 재량을 구분하고, 기존 자료로 문의를 처리할 수 있다면 추가 제출을 줄이는 제안을 수용하라.**

단계 지시: 같은 파일 13–17행의 opening → reply → draft → review → final. 쟁점 발견용 공통 호출은 [application/debates.py](../../server/application/debates.py)의 `build_payload`에 별도 정의되어 있다.

## B: 이번 실행에 실제 전달된 근거 18개

B에는 A의 역할별 `prompt` 문장이 추가되지 않는다. 공통 지시·단계 지시·B 전용 지시, 역할 배경, 아래에서 선별한 근거가 전달된다. 합성 프로필은 이 실행에 사용하지 않았다.

### 학생 — 6개

| 번호 | DB 근거 ID | 원본 파일 | 정확한 위치 | 입력 내용 표지 | B 발언 연결 |
|---:|---|---|---|---|---:|
| 1 | `277f81479d8c` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 120쪽 / group 6 / Part010 / segment 1 (PDF 쪽수; 고정된 줄 번호 없음) | I mean, I have the same perspective like, like Nithya said, she uses chat APD already or Jenny  already to mark her work and … | 0회 |
| 2 | `b0688800cd64` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 27쪽 / group 2 / Part005 / segment 5 (PDF 쪽수; 고정된 줄 번호 없음) | Uh. Personally, uh, I I don't have any problem by you with using uh AI for uh, assessing the  the assessments 'cause I think … | 0회 |
| 3 | `e3a459b32c2c` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 62쪽 / group 4 / Part017 / segment 1 (PDF 쪽수; 고정된 줄 번호 없음) | Yeah. Building on that. I think it's really interesting that you mentioned bias. A lot of people  have the have the impressio… | 0회 |
| 4 | `18a52cf95c4b` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 67쪽 / group 4 / Part018 / segment 3 (PDF 쪽수; 고정된 줄 번호 없음) | I would say not entirely, just like how here their first markers and 2nd markers. AI could be  the first marker a human could… | 0회 |
| 5 | `2fe00f1a3af0` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 46쪽 / group 3 / Part023 / segment 3 (PDF 쪽수; 고정된 줄 번호 없음) | Actually VDI is only ChatGPT if it is where I have access to that even the complete. I'm not.  I've recently come to know tha… | 3회 |
| 6 | `66d226eca8b1` | [파일](../../research/2026-11-02/DATA/surrey_focus.pdf) `research/2026-11-02/DATA/surrey_focus.pdf` | PDF 33쪽 / group 2 / Part006 / segment 5 (PDF 쪽수; 고정된 줄 번호 없음) | In my big pressing issue, because even myself sometimes I'll just go on there and ask for an  opinion on something like that,… | 0회 |

### 교수 — 6개

| 번호 | DB 근거 ID | 원본 파일 | 정확한 위치 | 입력 내용 표지 | B 발언 연결 |
|---:|---|---|---|---|---:|
| 1 | `4a1b6ad60a4d` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 9; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Educators need more support and training to use AI tools effectively and responsibly (유효 응답 139명) | 0회 |
| 2 | `1c86e6f7505e` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 6; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Using AI tools will (or already does) improve overall teaching and academic processes (유효 응답 139명) | 0회 |
| 3 | `66f9ff5a7d46` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 13; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Use these AI tools to better understand academic and career pathways (유효 응답 139명) | 0회 |
| 4 | `5e8460727af4` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 12; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Seek answers from AI before approaching a course instructor or teaching assistant (유효 응답 139명) | 0회 |
| 5 | `86c8c20c10d9` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 7; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Using AI tools will (or already does) enhance inclusivity in learning outcomes (유효 응답 139명) | 0회 |
| 6 | `4b8638416348` | [파일](../../research/2026-11-02/DATA/faculty_1.xlsx) `research/2026-11-02/DATA/faculty_1.xlsx` | Sheet1 column 11; university educator=Yes; rows 2–140 (응답 행 전체를 집계한 값; 단일 행 아님) | Become more concerned about how their data is collected and used (유효 응답 139명) | 5회 |

### 학사행정 — 6개

| 번호 | DB 근거 ID | 원본 파일 | 정확한 위치 | 입력 내용 표지 | B 발언 연결 |
|---:|---|---|---|---|---:|
| 1 | `318a7c494990` | [파일](../../research/2026-11-02/KR/snu_rnd_2.pdf) `research/2026-11-02/KR/snu_rnd_2.pdf` | policy_text/KR_snu_rnd_2.txt paragraph 3; [추출 텍스트](../../research/2026-11-02/policy_text/KR_snu_rnd_2.txt) 8–38행 | 서울대학교는 대한민국의 교육과 연구를 선도하는 고등교육기관으로서, 사회 변화와 기술 발전에 능동적으로 대응해 왔다. 최근 비약적으로 발전하는 인공 지능(artificial intelligence, 이하 ‘AI’) 기술은 교육… | 0회 |
| 2 | `d611e9695a89` | [파일](../../research/2026-11-02/KR/hanbat_attachment1.hwp) `research/2026-11-02/KR/hanbat_attachment1.hwp` | policy_text/KR_hanbat_attachment1.txt paragraph 1; [추출 텍스트](../../research/2026-11-02/policy_text/KR_hanbat_attachment1.txt) 1–26행 | 捤獥      汤捯      氠瑢       붙임1   汤捯     생성형 AI 활용 가이드라인   □ 생성형 AI 활용 가이드라인   氠瑢         생성형 인공지능 기술이란 인공지능 기술의 한 종류로서 이미지, 비디오… | 5회 |
| 3 | `246689eea9c1` | [파일](../../research/2026-11-02/KR/hanbat_attachment2.hwp) `research/2026-11-02/KR/hanbat_attachment2.hwp` | policy_text/KR_hanbat_attachment2.txt paragraph 1; [추출 텍스트](../../research/2026-11-02/policy_text/KR_hanbat_attachment2.txt) 1–39행 | 捤獥      汤捯      氠瑢       붙임2   汤捯     자가 점검 체크리스트   □ 생성형 AI 활용을 위한 자가 점검 체크리스트   氠瑢       연번  점검항목  점검내용  체크(√)  1  생성형 AI 개… | 0회 |
| 4 | `7722a8f7649d` | [파일](../../research/2026-11-02/DATA/asu_41511.zip) `research/2026-11-02/DATA/asu_41511.zip` | ZIP corpus/University_of_North_Carolina_Wilmington_2026.txt paragraph 14; ZIP 내부 68–72행 | Citing and Referencing Generative AI Below are a few helpful resources for citing AI in assignments and papers. APA Style 7th… | 0회 |
| 5 | `83b5f5c3c378` | [파일](../../research/2026-11-02/INT/polyu.pdf) `research/2026-11-02/INT/polyu.pdf` | policy_text/INT_polyu.txt paragraph 22; [추출 텍스트](../../research/2026-11-02/policy_text/INT_polyu.txt) 98–104행 | 1  For guidelines on how to reference Generative AI, see https://apastyle.apa.org/blog/how-to- cite-chatgpt     for   APA,   … | 0회 |
| 6 | `d8c36bce0947` | [파일](../../research/2026-11-02/INT/ubc.pdf) `research/2026-11-02/INT/ubc.pdf` | policy_text/INT_ubc.txt paragraph 5; [추출 텍스트](../../research/2026-11-02/policy_text/INT_ubc.txt) 44–68행 | === PDF 2쪽 === 3. Explore different tools and models, and different    ways to use them in learning.   It’s tempting to go ba… | 0회 |

## DB에 있으나 이번 입력에는 없는 자료

- 학생 발화 309개, 교수 설문 집계 8개, 기관 지침 문단 2,689개가 사용 가능 근거로 등록돼 있다. 이 중 역할별 6개씩만 선택했다.
- [PolicyLens_Sources.xlsx](../../data/b/sources/PolicyLens_Sources.xlsx)의 91행은 `BSourceCandidate` 검토 후보이며 `Evidence` 입력에 포함되지 않는다.
- 합성 프로필은 교수 20개·학사행정 20개가 저장돼 있으나 이번 실행의 세 역할 모두 `researcher_role` 배경을 사용했다.

## 데이터 품질과 해석 주의

- 학생 자료는 영국 Surrey 포커스그룹 발화이며 국내 학생의 대표 의견이 아니다.
- 교수 자료는 교육자 설문의 문항별 집계다. 개인 교수 발언이 아니다.
- 행정 자료는 기관 지침의 대체 근거다. 실제 행정 담당자의 의견이 아니다.
- 한밭대 HWP 추출 텍스트 두 건은 앞부분에 깨진 문자가 섞여 있다. ASU ZIP 선택 항목은 AI 인용 안내 링크 중심이며, PolyU 선택 항목도 참고문헌 링크 중심이다. 관련성 재검토가 필요하다.
- 이번 결과에서 B 근거 ID로 실제 연결된 것은 학생 5번, 교수 6번, 행정 2번뿐이다. 나머지 15개는 모델 입력에는 있었으나 발언 근거 ID로 사용되지 않았다.


<details><summary>DB 근거 ID 전체 보기</summary>

1. `277f81479d8caba433b0a2d204962ca14eb50aa005329207adec02f580b30a34`
2. `b0688800cd64db4598bf123e3774cc2e66363774b4fd6a3064a85605c62d4eca`
3. `e3a459b32c2c7ae0d3f1b543278572589c4fde74bdf1c64fab5b21bb9271dc3d`
4. `18a52cf95c4bf6fb3c29b87c008cb476d92be000949ac1e0a5d6a9bc56d64616`
5. `2fe00f1a3af04b495012ef290c7b2c3c838973b77bda9df5e015503df5527358`
6. `66d226eca8b130f139a94dc81d8b8fe49bc5d753bd8826cfc740ff72334b7f84`
7. `4a1b6ad60a4daec59e43a436e54ce412b0a7a735bf082f1dd99db63ac36e39c4`
8. `1c86e6f7505ed6651a3bafa9fd9d29bbeb7d194ebe9f3b49a2a5384cf0ff4bb1`
9. `66f9ff5a7d46d5d6eaa7dfc9b7d18ca384715729b95aae75b47749d686f53022`
10. `5e8460727af406bbb091c841a6f998cba24091da9c4509dfeba3d16a85ce4ace`
11. `86c8c20c10d91bb1f73043d415055ed7d3b4549fdfb15347412733ed5970bbbc`
12. `4b863841634847367c8a019d193ce70dc583cdc1ac185504fb0495acc6a032c6`
13. `318a7c4949906ca97c8074f4888f99a257c5d67d1e83f4365ee2ba784d6985c5`
14. `d611e9695a89c9364d77ee5c3448fe64f4478a0ec5f22953f87da33963c5bded`
15. `246689eea9c1bb0277ec2d7c9b78f38d7cb8025ccacb8e1925b184f6c7c50326`
16. `7722a8f7649df0da30cd9f452f67672bf9a892b93f5cff68bcdd28e0749f974b`
17. `83b5f5c3c378b91f342d6cc39bd572a046060eac0418f0428aa21c9c0292b741`
18. `d8c36bce094794064a0cf676a056300780706b78e25de648c4ff35b0f7e11a5b`

</details>
