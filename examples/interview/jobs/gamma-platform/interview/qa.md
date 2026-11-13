# 감마클라우드 Platform Engineer 면접 문답 (가상의 예제)

## O. 시작: 인사와 연결 확인

### O1. 입장 인사 / Opening greeting

**핵심** 이름과 감사 인사만 짧게, 웃는 얼굴로

**면접관** Hi, Gildong. Thanks for joining us today.
**해석** 안녕하세요, 길동 님. 오늘 와 주셔서 감사합니다.
**나** (웃으며) Hi, / thank you for having me. // I'm **Hong Gildong**, / and I'm ==glad to meet you== today.
**해석** (웃으며) 안녕하세요, 불러 주셔서 감사합니다. 홍길동이고, 오늘 뵙게 되어 반갑습니다.

### O2. 소리와 화면 공유 확인 / Audio check and screen share

**핵심** 들리는지 먼저 답하고, 포트폴리오 공유는 내가 먼저 제안한다

**면접관** Can you hear me okay?
**해석** 제 목소리 잘 들리세요?
**나** Yes, / I can hear you **clearly**. // Please tell me / if my voice **breaks up** at any point.
**해석** 네, 잘 들립니다. 혹시 제 목소리가 끊기면 언제든 말씀해 주세요.
**면접관** Would you like to share your portfolio on screen?
**해석** 포트폴리오를 화면에 띄워 주시겠어요?
**나** Sure, / I'll share my screen **now**. // Please let me know / when you can ==see the first page==.
**해석** 네, 지금 화면을 공유하겠습니다. 첫 장이 보이시면 말씀해 주세요.

## A. 소개와 지원 동기

### A1. 1분 자기소개 / Tell me about yourself

**핵심** 주문에서 결제로, 결제에서 배포 플랫폼으로 온 길을 1분에

**면접관** Could you start by introducing yourself?
**해석** 먼저 자기소개 부탁드립니다.
**나** I'm a **backend platform engineer**, / and I've worked on **payments** / and the **deploy platform** / that teams share. // At **Beta Commerce** / I published order status changes / as **Kafka** events, / so settlement and notifications / stopped depending on the order service. // At **Alpha Pay** / I split payment approval / into its **own deploy unit**, / and then I moved every team / to ==one shared deploy path== / on **Argo CD** and **Helm**. // I'd like to bring that work / to your **payment platform**.
**해석** 저는 백엔드 플랫폼 엔지니어이고, 결제와 팀들이 함께 쓰는 배포 플랫폼을 맡아 왔습니다. 베타커머스에서는 주문 상태 변경을 Kafka 이벤트로 내보내 정산과 알림이 주문 서비스에 기대지 않게 했습니다. 알파페이에서는 결제 승인을 독립 배포 단위로 나눈 뒤, 모든 팀을 Argo CD와 Helm 위의 공용 배포 경로 하나로 옮겼습니다. 그 경험을 감마클라우드의 결제 플랫폼에 가져오고 싶습니다.

**주의** 1분을 넘기지 않는다. 숫자는 묻기 전에는 꺼내지 않는다.

### A2. 왜 감마클라우드인가 / Why Gamma Cloud?

**핵심** 결제처럼 멈추면 바로 손실이 나는 서비스를 받치는 플랫폼을 만들고 싶다

**면접관** Why do you want to join Gamma Cloud?
**해석** 감마클라우드에 왜 지원하셨나요?
**나** I want to build the platform / under services where **downtime** / turns into a **loss** right away, / like **payments** and **orders**. // Your posting says / the platform team owns the **deploy path** / and the **event pipelines**, / and those are ==the two things I've built== / at Alpha Pay and Beta Commerce. // I'd like to do that work / for **several stores** at once.
**해석** 저는 결제와 주문처럼 멈추면 바로 손실이 되는 서비스 밑의 플랫폼을 만들고 싶습니다. 공고를 보면 플랫폼 팀이 배포 경로와 이벤트 파이프라인을 맡는데, 둘 다 제가 알파페이와 베타커머스에서 만들어 본 것입니다. 그 일을 여러 쇼핑몰을 위해 한 번에 해 보고 싶습니다.

### A3. 강점과 약점 / Strength and weakness

**핵심** 강점은 원인을 계층별로 좁혀 고치는 것, 약점은 문서화를 늦게 시작하던 버릇

**면접관** What is your biggest strength, and your biggest weakness?
**해석** 가장 큰 강점과 약점은 무엇인가요?
**나** My strength is that I **narrow down** a failure / **one layer at a time** / before I change anything. // My weakness was that I used to write the **procedure** / only after the work was done, / so other people **could not follow** it / while it was still changing. // Now I write the **runbook** / ==while I build the system==, / and I ask a teammate / to try it **before release**.
**해석** 제 강점은 무엇이든 바꾸기 전에 장애를 한 계층씩 좁혀 가는 것입니다. 약점은 일이 끝난 뒤에야 절차를 쓰던 버릇이라서, 바뀌는 동안에는 다른 사람이 따라오지 못했습니다. 지금은 시스템을 만드는 동안 런북을 같이 쓰고, 출시 전에 동료에게 직접 따라 해 보게 합니다.

## D. 인성과 협업

### D1. 실수와 배운 점 / A mistake and what you learned

**핵심** 재시도가 상한 없이 몰려 승인 경로를 더 눌렀다, 그 뒤로 재시도에는 늘 간격과 상한을 둔다

**면접관** Tell me about a mistake you made and what you learned.
**해석** 실수했던 경험과 배운 점을 말씀해 주세요.
**나** Before the redesign, / our approval calls retried **right away** / and **without a limit**, / so when the approval path slowed down, / the retries **piled up** / and made it slower. // I had copied that retry setting / from another service / **without checking it**. // In the redesign / I limited retries / with **exponential backoff** and a **cap**, / and I put an **idempotency key** on every request, / so ==a retry never charges twice==.
**해석** 재설계 전에는 승인 호출이 상한 없이 바로 재시도해서, 승인 경로가 느려지면 재시도가 쌓여 더 느려졌습니다. 제가 그 재시도 설정을 다른 서비스에서 확인 없이 가져왔던 것입니다. 재설계에서는 재시도를 지수 간격과 상한으로 제한하고 모든 요청에 멱등 키를 두어, 재시도가 두 번 결제되는 일이 없게 했습니다.

**주의** 사고 규모나 금액은 자료에 없다. 물으면 규모는 기억하는 숫자가 없다고 답한다. 이야기 근거는 S1.

### D2. 동료와 의견이 다를 때 / Disagreeing with a colleague

**핵심** 각 팀 스크립트를 지키자는 의견과 부딪혔다, 한 팀 먼저 옮겨 보고 이력 화면으로 보여 줬다

**면접관** Tell me about a time you disagreed with a colleague.
**해석** 동료와 의견이 달랐던 경험을 말씀해 주세요.
**나** When I proposed **one shared deploy path**, / a colleague wanted to keep / each team's **own scripts**, / because they already worked. // Instead of arguing, / I moved **one team first** / to the **Argo CD** pattern / and showed the **deploy history** / and the **one-step rollback** on the screen. // After that / the other teams / ==asked to move on their own==.
**해석** 제가 공용 배포 경로 하나를 제안했을 때, 한 동료는 이미 잘 돌아가는 각 팀 스크립트를 그대로 두자고 했습니다. 저는 논쟁하는 대신 한 팀을 먼저 Argo CD 방식으로 옮기고, 배포 이력과 한 번에 되돌리기를 화면으로 보여 줬습니다. 그 뒤로는 다른 팀들이 먼저 옮기겠다고 했습니다.

## E. 상황 질문

### E1. 밤에 결제 승인이 느려졌다 / Payment approvals slow down at night

**핵심** 범위 확인, 최근 변경 확인, 되돌리기, 원인은 그다음

**면접관** Payment approvals got slow tonight. What do you do first?
**해석** 오늘 밤 결제 승인이 느려졌습니다. 무엇부터 하시겠어요?
**나** First, / I check **how wide** it is: / all approvals or one store, / and **when** it started, / on the **Grafana** dashboards. // Then I look for the **latest change**, / because a **deploy** or a **config change** / is the most common cause. // If a recent version is suspect, / I **roll back** first / through the **deploy history**, / and I ==find the cause after the service is stable==.
**해석** 먼저 Grafana 대시보드로 범위를 봅니다. 전체 승인인지 한 쇼핑몰인지, 언제 시작됐는지입니다. 다음으로 가장 최근 변경을 찾습니다. 배포나 설정 변경이 가장 흔한 원인이기 때문입니다. 최근 버전이 의심되면 배포 이력에서 먼저 되돌리고, 원인은 서비스가 안정된 뒤에 찾습니다.
**면접관** And after that?
**해석** 그다음에는요?
**나** I write down **what happened** / in the incident procedure / while it is fresh, / and I add a **step** / if the procedure missed this case. // At **Beta Commerce** / I trained the **on-duty rotation** / with these procedures, / so ==the next person== does not start from zero.
**해석** 기억이 생생할 때 무슨 일이 있었는지 장애 절차에 적고, 절차가 이 경우를 놓쳤다면 단계를 더합니다. 베타커머스에서는 이 절차로 당번 교육을 해서, 다음 사람이 처음부터 시작하지 않게 했습니다.

## K. 모를 때, 마무리

### K1. 모르는 질문을 받았을 때 / When you don't know the answer

**핵심** 모른다고 먼저 말하고, 가장 가까운 경험과 확인 순서를 댄다

**면접관** How would you tune the database for a much larger load?
**해석** 훨씬 큰 부하에 맞춰 데이터베이스를 어떻게 튜닝하시겠어요?
**나** I **haven't done** that at a much larger scale, / so I don't want to **guess**. // The closest thing I've done / is a **Redis cache** / for frequent order lookups, / with rules for **invalidation**. // To check, / I would start with ==the slowest queries== / and measure **before** I change anything.
**해석** 그렇게 큰 규모에서는 해 본 적이 없어서 추측하고 싶지 않습니다. 가장 가까운 경험은 자주 읽는 주문 조회에 Redis 캐시를 두고 무효화 규칙을 정한 것입니다. 확인한다면 가장 느린 쿼리부터 보고, 바꾸기 전에 먼저 재겠습니다.

### K2. 역질문 / Your questions for us

**핵심** 팀의 배포 경로와 장애 대응 방식을 묻는다

**면접관** Do you have any questions for us?
**해석** 저희에게 궁금한 점이 있으신가요?
**나** Yes, / two questions. // How do the payment teams **release** today, / and what part of it / would you like this role / to **change first**? // And when an incident happens at night, / ==who responds==, / and how is the **runbook** kept up to date?
**해석** 네, 두 가지입니다. 지금 결제 팀들은 어떻게 배포하고 있고, 이 자리에서 무엇을 먼저 바꾸길 바라시나요? 그리고 밤에 장애가 나면 누가 대응하고, 런북은 어떻게 최신으로 유지하나요?
