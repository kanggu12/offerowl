# -*- coding: utf-8 -*-
"""A stand-in model for the drafting tests: canned answers per task for the fictional ledger in fixtures/ledger_ko.json.

The first answers plant the problems the checks must catch: a claim stronger than its evidence ("designed and led" where the
ledger says the person proposed a design and did the move with the team; "built" where a colleague built it and the person
helped), a counted amount ("half") under a style pack that forbids numbers, and a client name that no evidence holds. The
repair answer reads the request it gets and rewrites the texts it knows, as a model would.
"""
import copy  # every call gets its own copy of an answer
import re  # the repair request is read line by line

ITEMS = {"roles": [  # the work-history items of both roles
    {"key": "nara", "desc": {"ko": "금융권 고객의 데이터 플랫폼을 운영하는 클라우드 회사의 가상은행 사업 플랫폼 담당",
                             "en": "Platform owner for the Gasang Bank account at a cloud company that runs data platforms for financial clients",
                             "ev": ["nara#c1.1", "nara#c1.2"]},
     "items": [
         {"project": "nara-1", "title": {"ko": "가상은행 결제 데이터 플랫폼 이관", "en": "Gasang Bank payment data platform migration"},  # planted: an overclaim, a scope sentence, a counted amount
          "short": {"ko": "가상은행 플랫폼 이관", "en": "Gasang Bank migration"},
          "sentences": [
              {"part": "decision", "ko": "분석 플랫폼을 Kubernetes로 옮기는 이관을 설계하고 주도",
               "en": "Designed and led the move of the analytics platform to Kubernetes", "ev": ["nara-1#2", "nara-1#3"]},
              {"part": "scope", "ko": "한 서버에 몰려 있던 가상은행 분석 플랫폼의 이관 과제",
               "en": "Took on the analytics platform of Gasang Bank, which ran on a single server", "ev": ["nara-1#1"]},
              {"part": "result", "ko": "이관 뒤 ==쿼리 지연을 절반으로 줄임==", "en": "After the move, ==cut query latency in half==", "ev": ["nara-1#5"]}]},
         {"project": "nara-2", "title": {"ko": "온콜 체계 수립", "en": "On-call process setup"}, "short": {"ko": "온콜 체계", "en": "On-call process"},  # a clean item
          "sentences": [
              {"part": "scope", "ko": "장애 등급별 대응 절차와 온콜 로테이션 정립", "en": "Set the on-call rotation and severity-based response steps",
               "ev": ["nara-2#1"]},
              {"part": "decision", "ko": "하노이 지사와의 주간 회의를 영어로 운영", "en": "Ran a weekly meeting in English with the Hanoi office",
               "ev": ["nara-2#2"]},
              {"part": "result", "ko": "장애 뒤 ==재발 방지 항목까지 추적==", "en": "After each incident, ==tracked prevention items to closure==",
               "ev": ["nara-2#3"]}]},
         {"project": "nara-3", "title": {"ko": "Grafana 대시보드 구축", "en": "Grafana dashboard build"}, "short": {"ko": "대시보드", "en": "Dashboards"},  # planted: a claim over 'helped' and a client no evidence names
          "sentences": [{"part": "decision", "ko": "Grafana 대시보드 구축", "en": "Built the Grafana dashboards for Delta Bank", "ev": ["nara-3#1"]}]}]},
    {"key": "dasom", "items": [  # the second role
        {"project": "dasom-1", "title": {"ko": "사내 배포 파이프라인 구축", "en": "In-house deployment pipeline build"},  # a clean item
         "short": {"ko": "배포 파이프라인", "en": "Deployment pipeline"},
         "sentences": [
             {"part": "decision", "ko": "GitLab과 Jenkins로 배포 파이프라인 구축", "en": "Built a deployment pipeline on GitLab and Jenkins", "ev": ["dasom-1#1"]},
             {"part": "result", "ko": "Ansible 플레이북을 가상 시험장에서 먼저 검증해 ==검증한 변경만 운영에 반영==",
              "en": "Checked Ansible playbooks on a test bed first, so ==only tested changes reached production==", "ev": ["dasom-1#2"]}]}]}]}

SUMMARY = {  # the top of the resume
    "headline": {"ko": "금융권 데이터 플랫폼의 Kubernetes 이관과 온콜 운영", "en": "Kubernetes moves and on-call operations for financial data platforms",
                 "ev": ["nara-1#2", "nara-2#1", "nara#c1.1"]},
    "intro": {"ko": "가상은행의 분석 플랫폼 이관을 제안하고 팀과 함께 옮겼으며, ==온콜 체계를 문서로 고정==했습니다.",
              "en": "I proposed the move of Gasang Bank's analytics platform, carried it out with the team, and ==fixed the on-call process in writing==.",
              "ev": ["nara-1#1", "nara-1#2", "nara-1#3", "nara-2#1"]},
    "cards": [
        {"key": "target", "ko": "금융권 고객 플랫폼의 SRE", "en": "SRE for financial client platforms", "ev": ["nara#c1.1"]},
        {"key": "focus", "ko": "Kubernetes, Prometheus, GitLab, Jenkins, Ansible", "en": "Kubernetes, Prometheus, GitLab, Jenkins, Ansible",
         "ev": ["nara-1#2", "nara-1#4", "dasom-1#1", "dasom-1#2"]},
        {"key": "strengths", "ko": "장애 대응 절차의 문서화, 운영 반영 전 검증", "en": "Written incident procedures, changes tested before production",
         "ev": ["nara-2#1", "dasom-1#2"]},
        {"key": "industries", "ko": "금융권 고객의 데이터 플랫폼", "en": "Data platforms for financial clients", "ev": ["nara#c1.1"]}],
    "highlights": [
        {"project": "nara-1", "title": {"ko": "가상은행 플랫폼 이관", "en": "Gasang Bank platform move"},
         "rows": [{"key": "challenge", "ko": "한 서버에 몰린 분석 플랫폼", "en": "An analytics platform on a single server", "ev": ["nara-1#1"]},
                  {"key": "action", "ko": "Kubernetes 이관 설계안을 제안하고 팀과 함께 이관", "en": "Proposed a Kubernetes design and moved it with the team",
                   "ev": ["nara-1#2", "nara-1#3"]},
                  {"key": "result", "ko": "이관 뒤 ==Prometheus 지표로 지연 확인==", "en": "==Checked latency on Prometheus metrics== after the move",
                   "ev": ["nara-1#4"]}]},
        {"project": "nara-2", "title": {"ko": "온콜 체계", "en": "On-call process"},
         "rows": [{"key": "challenge", "ko": "사람마다 다르던 장애 대응", "en": "Incident response that varied by person", "ev": ["nara-2#1"]},
                  {"key": "action", "ko": "온콜 로테이션과 등급별 절차를 문서화", "en": "Wrote down the rotation and severity steps", "ev": ["nara-2#1"]},
                  {"key": "result", "ko": "장애마다 ==재발 방지 항목 추적==", "en": "==Prevention items tracked== after each incident", "ev": ["nara-2#3"]}]}]}

COMPETENCIES = {"competencies": [  # four competencies
    {"name": {"ko": "Kubernetes 이관", "en": "Kubernetes migration"}, "ko": "한 서버에 몰린 분석 플랫폼의 Kubernetes 이관 설계안 제안과 팀 단위 이관",
     "en": "Proposed a Kubernetes design for a single-server analytics platform and moved it with the team", "ev": ["nara-1#1", "nara-1#2", "nara-1#3"]},
    {"name": {"ko": "온콜과 장애 대응", "en": "On-call and incidents"}, "ko": "온콜 로테이션, 등급별 절차, 재발 방지 항목 추적",
     "en": "On-call rotation, severity steps and prevention items tracked to closure", "ev": ["nara-2#1", "nara-2#3"]},
    {"name": {"ko": "CI/CD", "en": "CI/CD"}, "ko": "GitLab과 Jenkins 배포 파이프라인과 가상 시험장 검증",
     "en": "Deployment pipeline on GitLab and Jenkins with checks on a test bed", "ev": ["dasom-1#1", "dasom-1#2"]},
    {"name": {"ko": "관측", "en": "Observability"}, "ko": "Prometheus 지표로 이관 뒤 쿼리 지연 확인",
     "en": "Query latency checked on Prometheus metrics after a move", "ev": ["nara-1#4"]}]}

ABOUT = {  # two sections and the motivation
    "about": [
        {"title": {"ko": "제안하고 함께 옮기기", "en": "Propose, then move together"},
         "sentences": [{"ko": "가상은행의 분석 플랫폼이 한 서버에 몰려 있었습니다.", "en": "Gasang Bank's analytics platform ran on a single server.", "ev": ["nara-1#1"]},
                       {"ko": "Kubernetes로 옮기는 설계안을 만들어 제안하고 팀과 함께 옮겼습니다.", "en": "I proposed a design for the move to Kubernetes and carried it out with the team.",
                        "ev": ["nara-1#2", "nara-1#3"]}]},
        {"title": {"ko": "먼저 시험하기", "en": "Test first"},
         "sentences": [{"ko": "Ansible 플레이북은 가상 시험장에서 먼저 검증한 뒤 운영에 반영했습니다.", "en": "I checked Ansible playbooks on a test bed before they reached production.",
                        "ev": ["dasom-1#2"]}]}],
    "motivation": [
        {"ko": "Orion Data는 아시아의 은행을 위한 데이터 플랫폼을 운영합니다.", "en": "Orion Data runs data platforms for banks across Asia.", "frame": True},  # a framing sentence about the posting's company
        {"ko": "저는 금융권 고객의 데이터 플랫폼을 맡아 왔고 하노이 지사와 영어로 일했습니다.",
         "en": "I have looked after data platforms for financial clients and worked in English with the Hanoi office.", "ev": ["nara#c1.1", "nara-2#2"]}]}

FIXES = {  # what the repair answer writes for each text the checks reject, keyed by the rejected text
    "Designed and led the move of the analytics platform to Kubernetes":
        ("Proposed a design for the move of the analytics platform to Kubernetes and carried it out with the team", ["nara-1#2", "nara-1#3"]),
    "분석 플랫폼을 Kubernetes로 옮기는 이관을 설계하고 주도": ("분석 플랫폼의 Kubernetes 이관 설계안을 제안하고 팀과 함께 이관", ["nara-1#2", "nara-1#3"]),
    "After the move, ==cut query latency in half==": ("After the move, ==checked query latency on Prometheus metrics==", ["nara-1#4"]),
    "이관 뒤 ==쿼리 지연을 절반으로 줄임==": ("이관 뒤 ==Prometheus 지표로 쿼리 지연 확인==", ["nara-1#4"]),
}


DECK = {  # the deck's opening slides, every text from the ledger's own words
    "stats": [{"value": {"ko": "플랫폼 이관", "en": "Platform move"}, "ko": "한 서버에 몰린 분석 플랫폼을 팀과 함께 이관", "en": "Moved a single-server analytics platform with the team",
               "ev": ["nara-1#1", "nara-1#2", "nara-1#3"]},
              {"value": {"ko": "온콜 절차", "en": "On-call steps"}, "ko": "온콜 로테이션과 장애 등급별 대응 절차를 문서로 고정", "en": "Wrote down the on-call rotation and severity steps",
               "ev": ["nara-2#1"]},
              {"value": {"ko": "검증한 변경", "en": "Tested changes"}, "ko": "Ansible 플레이북을 가상 시험장에서 먼저 검증", "en": "Checked Ansible playbooks on a test bed first",
               "ev": ["dasom-1#2"]}],
    "focus": [{"title": {"ko": "플랫폼 이관", "en": "Platform moves"}, "ko": "Kubernetes 이관 설계안 제안과 팀 이관", "en": "Kubernetes design proposals and moves with the team",
               "ev": ["nara-1#2", "nara-1#3"]},
              {"title": {"ko": "배포 경로", "en": "Deployment"}, "ko": "GitLab과 Jenkins 배포 파이프라인", "en": "Deployment pipelines on GitLab and Jenkins", "ev": ["dasom-1#1"]},
              {"title": {"ko": "온콜 운영", "en": "On-call"}, "ko": "온콜 로테이션과 장애 등급별 대응 절차 문서화", "en": "On-call rotation and severity steps in writing", "ev": ["nara-2#1"]}],
    "journey": [{"role": "nara", "phase": {"ko": "플랫폼", "en": "Platform"}, "ko": "분석 플랫폼 이관과 온콜", "en": "Analytics platform moves and on-call",
                 "key": {"ko": "가상은행 결제 데이터 플랫폼", "en": "Gasang Bank payment data platform"}, "ev": ["role:nara", "nara-1#1", "nara-2#1"]},
                {"role": "dasom", "phase": {"ko": "배포", "en": "Deployment"}, "ko": "GitLab과 Jenkins 배포 파이프라인", "en": "Pipelines on GitLab and Jenkins",
                 "key": {"ko": "Ansible 플레이북 검증", "en": "Ansible playbook checks"}, "ev": ["role:dasom", "dasom-1#1", "dasom-1#2"]},
                {"role": "nowhere", "phase": {"ko": "없는 회사", "en": "No such role"}, "ko": "없는 경력", "en": "A role that is not there", "key": {"ko": "없음", "en": "None"}, "ev": ["nara-1#1"]}],
    "contents": {"ko": "최근 경력부터: 나라클라우드, 다솜소프트", "en": "Most recent first: Nara Cloud, then Dasom Soft", "ev": ["role:nara", "role:dasom"]},
}


class StandIn:
    """Answers llm.run(task, prompt, ...) from the tables above and records every call (task, prompt)."""

    def __init__(self, **over):  # a test may override answers per task
        self.calls = []  # (task, prompt) of every call, in order
        self.table = {"write-items": ITEMS, "write-summary": SUMMARY, "write-competencies": COMPETENCIES, "write-about": ABOUT, "write-deck": DECK, **over}  # the answers by task

    def __call__(self, task, prompt, **kw):  # the signature of llm.run
        self.calls.append((task, prompt))  # a test reads the prompts
        if task == "write-repair":  # the repair answer depends on what was rejected
            return self.repair(prompt)
        if task not in self.table:  # a task without an answer: the model is not there
            import llm  # the exception the real backend raises
            raise llm.LLMUnavailable("stand-in has no answer for " + task)  # the model is not there
        return copy.deepcopy(self.table[task])  # a fresh copy, so a run never changes the table

    def repair(self, prompt):
        """Rewrite the texts this stand-in knows; leave the others out, as a model that cannot fix them would."""
        parts = []  # the rewritten texts
        for line in prompt.splitlines():  # rows look like: r1 | en | what | text | why | ids
            m = re.match(r"^(r[0-9a-f]+) \| (ko|en) \| [^|]* \| (.*?) \| .* \| [^|]*$", line)  # a rejected text in the request
            if m and m.group(3) in FIXES:  # a text with a known fix
                text, ev = FIXES[m.group(3)]  # its fix
                parts.append({"id": m.group(1), "text": text, "ev": ev})  # with the evidence it cites
        return {"parts": parts}  # the parts the stand-in can fix
