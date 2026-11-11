# 감마클라우드 면접: 이력서와 포트폴리오 상세 (가상의 예제)

## R. 이력 상세: 알파페이

### R1. 결제 승인 서비스 재설계 / Walk me through the payment approval redesign

- **핵심**: 단일 애플리케이션에서 승인 기능을 떼어 독립 배포 단위로 만들고, 멱등 키와 재시도 정책을 정했다
- **면접관**: Walk me through the payment approval redesign.
- **해석**: 결제 승인 서비스 재설계를 설명해 주세요.
- **나**: Approval used to live / inside a **single application**, / so when requests piled up, / **every deploy** of that application / stopped the **approval path** as well. // I split the approval function / into its **own service**, / so ==approvals deploy and roll back on their own==. // I also set an **idempotency key** / on every approval request / and limited retries / with **exponential backoff** and a **cap**.
- **해석**: 승인 기능이 단일 애플리케이션 안에 있어서, 요청이 몰릴 때 그 애플리케이션을 배포할 때마다 승인 경로도 같이 멈췄습니다. 저는 승인 기능을 별도 서비스로 떼어 승인 경로만 따로 배포하고 되돌릴 수 있게 했습니다. 또 모든 승인 요청에 멱등 키를 두고, 재시도는 지수 간격과 상한으로 제한했습니다.
- **면접관**: What changed after the split?
- **해석**: 분리하고 나서 무엇이 달라졌나요?
- **나**: In our example numbers, / a deploy of the approval path / went from **42 minutes** to **9**, / and a rollback / from **30 minutes** to about **5**. // More important for the team, / an approval release / no longer waits / for the **rest of the application**.
- **해석**: 예제 수치로는 승인 경로 배포가 42분에서 9분으로, 되돌리기가 30분에서 5분 정도로 줄었습니다. 팀에게 더 중요한 것은 승인 배포가 이제 애플리케이션의 나머지를 기다리지 않는다는 점입니다.
- **주의**: 수치는 포트폴리오의 가상 예제 값이다(2023.01 ~ 2023.09). 기간을 물으면 2023년 1월부터 9월까지라고 답한다.

### R2. 사내 배포 플랫폼 / Walk me through the internal deploy platform

- **핵심**: 팀마다 다르던 배포 스크립트를 Argo CD 애플리케이션 하나의 꼴로 모으고, 환경별 Helm values 는 한 저장소에서 검토한다
- **면접관**: Tell me about the deploy platform you built.
- **해석**: 만드신 배포 플랫폼에 대해 말씀해 주세요.
- **나**: Every team at Alpha Pay / had its **own deploy scripts**, / so I moved them all / to **one Argo CD application** pattern. // The **Helm values** for each environment / now sit in **one repository**, / and a change starts / as a **pull request**. // ==Two people approve== / before merge, / then Argo CD syncs **staging** first / and checks its state.
- **해석**: 알파페이에서는 팀마다 배포 스크립트가 달라서, 모두 Argo CD 애플리케이션 하나의 꼴로 옮겼습니다. 이제 환경별 Helm values가 저장소 한 곳에 있고, 변경은 Pull Request로 시작합니다. 병합 전에 두 사람이 승인하고, 그다음 Argo CD가 스테이징에 먼저 동기화하고 상태를 확인합니다.
- **면접관**: How does a change reach production?
- **해석**: 변경은 운영까지 어떻게 가나요?
- **나**: Only an **approved version** / is synced to **production**. // The **deploy history** and the rollback / are on **one screen**, / so anyone on the team / can see what changed / and ==go back in one step==.
- **해석**: 승인된 버전만 운영에 동기화됩니다. 배포 이력과 되돌리기가 화면 하나에 있어서, 팀의 누구든 무엇이 바뀌었는지 보고 한 번에 되돌릴 수 있습니다.

## U. 이력 상세: 베타커머스

### U1. 주문 이벤트 파이프라인 / Walk me through the order event pipeline

- **핵심**: 주문 상태 변경을 Kafka 이벤트로 내보내 정산과 알림이 같은 흐름을 따로 읽게 했다
- **면접관**: How did you use Kafka at Beta Commerce?
- **해석**: 베타커머스에서 Kafka를 어떻게 쓰셨나요?
- **나**: Settlement and notifications / used to **call the order service** directly, / so a failure in one / **spread** to the others. // I published every **order status change** / as a **Kafka event**, / and settlement and notifications / now ==consume the same events on their own==. // The order service / no longer **waits** for them.
- **해석**: 정산과 알림이 주문 서비스를 직접 불러서, 한쪽 장애가 다른 쪽으로 번졌습니다. 저는 모든 주문 상태 변경을 Kafka 이벤트로 내보냈고, 이제 정산과 알림이 같은 이벤트를 각자 소비합니다. 주문 서비스는 더 이상 그들을 기다리지 않습니다.
- **주의**: 2020.03 ~ 2021.04 과제. 처리량 같은 수치는 자료에 없다.
