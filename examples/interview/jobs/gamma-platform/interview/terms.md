# 감마클라우드 면접: 꼬리 질문, 용어 (가상의 예제)

## Q. 꼬리 질문: 줄임말과 용어

### Q1. 멱등 키가 뭐야 / What is an idempotency key?

**핵심** 같은 요청을 여러 번 받아도 한 번만 처리되게 요청마다 붙이는 고유 키

**면접관** You mentioned idempotency keys. What are they?
**해석** 멱등 키를 말씀하셨는데요. 그게 뭔가요?
**나** An **idempotency key** / is a unique key / that the client sends / **with each request**. // If the same request arrives **twice**, / for example after a **retry**, / the server sees the same key / and returns the **first result** / instead of ==processing it again==.
**해석** 멱등 키는 클라이언트가 요청마다 함께 보내는 고유한 키입니다. 같은 요청이 재시도 등으로 두 번 오면, 서버는 같은 키를 보고 다시 처리하는 대신 첫 결과를 돌려줍니다.
**면접관** Where did you use it?
**해석** 어디에 쓰셨나요?
**나** On every **payment approval** request / at Alpha Pay, / together with **retries** limited / by **exponential backoff** and a **cap**. // That way ==a retry never charges twice==.
**해석** 알파페이의 모든 결제 승인 요청에, 지수 간격과 상한으로 제한한 재시도와 함께 썼습니다. 그래서 재시도가 두 번 결제되는 일이 없습니다.

**상세**
- **동작**: 서버는 키와 첫 처리 결과를 함께 저장하고, 같은 키가 다시 오면 저장한 결과를 돌려준다.
- **흔한 문제**: 키를 저장하기 전에 처리가 끝나면 중복이 생길 수 있어 저장과 처리를 한 단위로 묶는다(일반 설명).

### Q2. GitOps 가 뭐야 / What is GitOps?

**핵심** 저장소의 선언을 기준으로 도구가 클러스터 상태를 맞추는 배포 방식

**면접관** What does GitOps mean to you?
**해석** GitOps는 어떤 의미인가요?
**나** In general, / **GitOps** means / the **repository** holds the desired state / of what runs in the cluster, / and a tool such as **Argo CD** / keeps the cluster **in sync** with it. // A change is a **pull request**, / so every change is **reviewed** / and ==the history is the audit trail==.
**해석** 일반적으로 GitOps는 클러스터에서 돌아야 할 상태를 저장소가 갖고, Argo CD 같은 도구가 클러스터를 그 상태에 계속 맞추는 방식입니다. 변경은 Pull Request라서 모든 변경이 검토되고, 이력이 그대로 감사 기록이 됩니다.
**면접관** And in your own work?
**해석** 직접 하신 일에서는요?
**나** At Alpha Pay / the **Helm values** for each environment / sit in **one repository**, / and **two approvals** come before merge. // Argo CD syncs **staging** first, / and only an ==approved version== / reaches **production**.
**해석** 알파페이에서는 환경별 Helm values가 저장소 한 곳에 있고, 병합 전에 두 사람이 승인합니다. Argo CD가 스테이징에 먼저 동기화하고, 승인된 버전만 운영에 갑니다.
