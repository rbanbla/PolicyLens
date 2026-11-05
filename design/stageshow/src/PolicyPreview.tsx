import { Row, Stage, Text, Window } from '../kit'
import './policy-preview.css'

const perspectives = [
  { role: '학생', note: '안내가 없으면 허용 범위를 알기 어려워요.' },
  { role: '교수', note: '평가 목표에 맞는 기준이 필요해요.' },
  { role: '학사행정', note: '과목별 공지 시점을 정해야 해요.' },
]

/** An authored product still. It never reads the uploaded policy or calls the model. */
export default function PolicyPreview() {
  return (
    <Stage width={500} height={380} compact={{ below: 400, width: 358, height: 360 }} theme="light" fidelity="realistic" className="pl-stage" tokens={{
      '--ss-accent': '#3f6a52',
      '--ss-accent-soft': '#e4eee5',
      '--ss-text-strong': '#233b2e',
      '--ss-text': '#52645a',
      '--ss-surface': '#fffefa',
      '--ss-canvas': '#f6f7f2',
      '--ss-well': '#dbe8dc',
      '--ss-line': '#dce5da',
      '--ss-radius-window': '14px',
    }}>
      {(_state, _rect, layout) => (
        <>
          <Window title="PolicyLens" className="pl-window">
            <div className="pl-page">
              <Text className="pl-eyebrow">생성형 AI 활용 지침 · 제4조</Text>
              <Text className="pl-title">과제에 AI를 사용할 수 있나요?</Text>
              <Text className="pl-quote">“사용 여부와 범위는 담당 교원의 안내에 따른다.”</Text>
              <div className="pl-issue"><Text className="pl-issue-index">쟁점 01</Text><Text className="pl-issue-title">안내가 없을 때 적용 기준은?</Text></div>
              <div className="pl-roles">
                {perspectives.map(({ role, note }) => (
                  <Row key={role} pad={6} title={<Text className="pl-role-name">{role}</Text>} meta={<Text className="pl-role-note">{layout === 'compact' && role === '학사행정' ? '공지 시점을 정해야 해요.' : note}</Text>} />
                ))}
              </div>
            </div>
          </Window>
          <div className="pl-result">
            <Text className="pl-result-label">수정 가이드라인</Text>
            <Text className="pl-result-title">사전 공지 시점과 기본 원칙 명시</Text>
            <Text className="pl-result-foot">쟁점과 원문 근거를 함께 확인</Text>
          </div>
        </>
      )}
    </Stage>
  )
}
