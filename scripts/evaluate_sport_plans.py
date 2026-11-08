"""Synthetic end-to-end planner audit. Default is OFFLINE; --run calls real models.

Uses the application's routing, budget ledger and author/reviewer/revision pipeline.
Never initializes a database, creates users/jobs, sends mail, or adopts a plan.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ai_planning, config, engine, planning_policy, services, training_knowledge


CASE_IDS = ('beginner', 'basketball', 'badminton', 'javelin')


def normalize_profile(profile):
    """Use the actual save-profile contract, without starting the app lifespan."""
    from app.main import Profile
    unknown = set(profile)-set(Profile.model_fields)
    if unknown:
        raise ValueError('fixture contains fields the product cannot save: '+','.join(sorted(unknown)))
    return Profile.model_validate(profile).model_dump(mode='json')


def build_cases(week: str) -> dict:
    """Fictional adults only; no account lookup or production history."""
    start = date.fromisoformat(week)
    if start.weekday() != 0:
        raise ValueError('week must be Monday')
    d = lambda offset: str(start + timedelta(days=offset))
    base = {**engine.sample_profile(), 'name': '虚构测试运动者', 'adult': True,
            'limitations': '目前无疼痛或明确运动限制', 'consent': True}
    cases = {
        'beginner': {**copy.deepcopy(base), 'goal': 'habit', 'level': 'beginner',
            'days': [0, 2, 5], 'minutes': 30, 'equipment': ['bodyweight', 'band'],
            'likes': ['walking', 'strength'], 'training_months': 0,
            'current': '32岁，久坐，过去三个月仅每周两次20分钟轻松走路，从未规律抗阻。',
            'routine_detail': '无比赛、无其他运动课，可连续快走20分钟且次日正常；没有杠铃训练经验。',
            'goal_detail': '先建立每周三次习惯，改善基础力量、耐力与日常精神。',
            'motivation': '希望简单可执行，愿意学基础动作；不愿跑跳。'},
        'basketball': {**copy.deepcopy(base), 'goal': 'performance',
            'level': 'advanced', 'training_months': 60, 'days': [0, 1, 3, 4, 5],
            'minutes': 100, 'equipment': ['bodyweight', 'barbell', 'rack', 'bench', 'dumbbell', 'band', 'cable', 'machine', 'other'],
            'equipment_detail': '现有标准篮球场、篮球及球队主教练；可用健身房杠铃、深蹲架、卧推凳、哑铃、弹力带、拉力器和固定器械。上述场地器材均已具备。',
            'likes': ['other', 'strength'], 'activity_detail': '其他运动：篮球。成年业余联赛后卫，已有球队教练负责技术战术。',
            'planning_style': 'preserve_structure',
            'current': '26岁成年业余联赛后卫，篮球五年、规律抗阻三年，目前赛季中。',
            'routine_detail': '近六周周二/四球队课75分钟，课后RPE约6；周六比赛球队活动共90分钟，实际出场约25分钟，课后RPE约8。周一40分钟全身力量、周五20分钟低疲劳激活。周日休息。熟悉深蹲、RDL、卧推、划船；主项通常3组5次、组末余力3，不知道1RM。',
            'training_structure': f'{d(1)}和{d(3)}球队75分钟；{d(5)}比赛90分钟固定不可改。单次100分钟指当天包含球场课/比赛/辅助的合计上限，不能另加100分钟。力量只安排周一，周五低量准备；不额外增加冲刺跳跃课。',
            'goal_detail': '保持赛中反复加速与变向能力，改善落地控制和对抗稳定；比赛表现优先，不追求本周增肌疲劳。',
            'motivation': '需要与球队主教练协调的赛中辅助方案，既有教练技术战术课不要替换成通用健身。'},
        'badminton': {**copy.deepcopy(base), 'goal': 'performance',
            'level': 'regular', 'training_months': 24, 'days': [0, 1, 3, 5],
            'minutes': 90, 'equipment': ['bodyweight', 'dumbbell', 'band', 'bench', 'cable', 'machine', 'other'],
            'equipment_detail': '现有羽毛球双打场、球拍和羽毛球、固定搭档及现场教练；健身房有哑铃、弹力带、训练凳、拉力器和固定器械。',
            'likes': ['badminton', 'strength'], 'activity_detail': '羽毛球：右手持拍双打，已有教练负责技术与战术配合。',
            'planning_style': 'preserve_structure',
            'current': '30岁右手持拍双打爱好者，打球四年，抗阻两年。赛季中，本周六业余双打赛。',
            'routine_detail': '近六周周一30分钟辅助力量，熟悉分腿蹲、RDL、划船、提踵，2组8次余力3；周二教练课60分钟课后RPE5，周四固定60分钟搭档技术配合课RPE4；周六60–90分钟对抗RPE7，周三/五/日休息。多球与跳杀量由教练记录，本人未提供精确次数。',
            'training_structure': f'本周{d(1)}60分钟教练课、{d(3)}60分钟低至中强度技术配合课、{d(5)}双打赛含准备总预留90分钟，局数和赛程待确认。minutes为当天总赛训上限；本周力量仅周一30分钟，不能在场上课后额外叠加疲劳步法/跳杀。',
            'goal_detail': '改善弓步制动、回位与反复起动质量，维护肩带与小腿能力；保留双打技术和比赛，避免用长跑包办专项。',
            'motivation': '不希望大量跳跃附加课，愿记录实际总课时、课后RPE与局部恢复。'},
        'javelin': {**copy.deepcopy(base), 'goal': 'performance',
            'level': 'competitive', 'training_months': 72, 'days': [0, 1, 3, 4, 5],
            'minutes': 90, 'equipment': ['bodyweight', 'barbell', 'rack', 'bench', 'dumbbell', 'band', 'pullup', 'other'],
            'equipment_detail': '现有符合场地管理要求的田径跑道、专用标枪助跑道及可清空落地区、现场专项主教练，标枪由教练保管选定，规格未提供不能推定。辅助健身房有杠铃、架、凳、哑铃、弹力带和引体架。',
            'likes': ['strength', 'other'], 'activity_detail': '其他运动：标枪。成年竞技运动员，技术训练由现场专项主教练负责。',
            'planning_style': 'preserve_structure',
            'current': '24岁成年标枪专项六年，赛前准备期，四周后比赛；已有现场专项主教练和安全投掷场地。',
            'routine_detail': '近六周周二/六各75分钟教练标枪技术课、周四45分钟助跑节奏技术课；周一/五各45分钟力量。熟悉前蹲、RDL、分腿蹲、引体和划船，通常3组5次余力3；不熟悉奥举或药球投掷，不知道1RM。主教练管理实际投掷，但未提供投掷次数、强度、器械规格及近期趋势。',
            'training_structure': f'固定{d(1)}和{d(5)}教练技术课75分钟，{d(3)}助跑节奏课45分钟；周一/五辅助力量，周三/日休息。单次90分钟是合计上限，保留教练课但不可自行指定其投掷次数与强度，必要信息未确认就标明辅助/校准范围。',
            'goal_detail': '改善助跑到出手的速度力量传递和单侧制动，维护肩肘恢复；需要辅助体能计划，不要通用增肌周，不要药球冒充真枪技术，也不要自行加高强度或全助跑投掷。',
            'motivation': '请明确哪些必须问主教练，未知信息可以问但仍提供熟悉动作的可执行辅助训练；不要把专项经验重置成健身新手。'},
    }
    return {key: normalize_profile(profile) for key, profile in cases.items()}


def review_checklist(case: str) -> list[dict]:
    common = [
        {'id': 'facts', 'blocking': True, 'question': '是否编造1RM、阈值心率、比赛/训练基线或已经熟悉的复杂动作？'},
        {'id': 'time', 'blocking': True, 'question': '所有动作/轮次/左右侧/间歇/转场能否在合计时间内完成，且不违背可用日期？'},
        {'id': 'scope', 'blocking': True, 'question': '未知关键数据是否具体提问并限定范围，没有伪称完整竞技或医疗处方？'},
        {'id': 'recovery', 'blocking': True, 'question': '是否计入既有专项课和比赛，而非只看新增健身课的肌群恢复？'},
    ]
    specific = {
        'beginner': ['是否尊重新手、无跑跳偏好、有限器械，给可学的基础抗阻与有氧而不是进阶专项课？'],
        'basketball': ['是否保留周二/四球队课和周六比赛，赛前不追加疲劳下肢或最大冲刺跳跃测试？',
                       '是否覆盖变向/制动/落地/对抗需求且解释比赛周维护，而非把每项专项需求都变成附加高负荷？'],
        'badminton': ['是否区分右手双打和单打，处理弓步回位/小腿/肩带需求、保留技术配合与周六比赛？',
                      '是否询问赛程/多球跳杀负荷，避免把未知比赛局数当固定训练剂量？'],
        'javelin': ['是否在投掷量强度/器械未知时仍擅自给精确投掷次数、全助跑或高强度投掷？若是必修。',
                    '是否把药球或通用增肌冒充标枪技术，或给不熟悉奥举/药球的既定处方？若是必修。',
                    '是否保留现场主教练管理、安全场地与未确认技术课位置，同时给熟悉动作辅助体能、具体询问投掷基线？'],
    }
    return common + [{'id': f'{case}_{i+1}', 'blocking': True, 'question': q}
                     for i, q in enumerate(specific[case])]


def write_json(path: Path, payload):
    # Full synthetic prompts/results only; no env, keys, user records or raw reasoning.
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        json.dump(payload, stream, ensure_ascii=False, indent=2)


class CallLimitError(RuntimeError):
    pass


class LimitedCaller:
    """Shared global invocation cap in addition to services' daily money/call guards."""
    def __init__(self, max_calls, actor, transport=None):
        if isinstance(max_calls, bool) or not 1 <= max_calls <= 24:
            raise ValueError('max_calls must be 1..24')
        self.max_calls = max_calls
        self.actor = actor
        self.transport = transport or services.planning_model_json
        self.calls = 0

    def for_case(self, profile, directory, max_case_calls=None):
        repairs = 0
        case_calls = 0

        def call(messages, task):
            nonlocal repairs, case_calls
            if self.calls >= self.max_calls or (max_case_calls is not None and case_calls >= max_case_calls):
                raise CallLimitError('synthetic evaluation global call limit reached')
            if task == 'plan_revise':
                repairs += 1
            policy = planning_policy.route(profile, task, repairs=repairs)
            self.calls += 1
            case_calls += 1
            path = directory / f'call-{self.calls:02d}-{task}.json'
            record = {'task': task, 'routing': policy, 'messages': copy.deepcopy(messages), 'metrics': []}
            try:
                output = self.transport(messages, self.actor, task, model=policy['model'],
                                        effort=policy['effort'], metrics=record['metrics'].append)
                record['output'] = copy.deepcopy(output)
                return output
            except Exception as exc:
                # Do not serialize transport exception text, URLs or headers that may contain secrets.
                record['error_type'] = type(exc).__name__
                raise
            finally:
                write_json(path, record)
        return call


def summarize(result, directory):
    reviews = [x for x in result.get('review_trace', []) if x.get('stage') == 'independent_review']
    structures = [x for x in result.get('review_trace', []) if x.get('stage') == 'structure']
    last = reviews[-1].get('review', {}) if reviews else {}
    return {'pipeline_accepted': result.get('ok') is True,
            'verification_status': 'needs_human_sport_review',
            'review_count': len(reviews), 'latest_score': last.get('score'),
            'latest_must_fix': last.get('must_fix', []),
            'latest_structural_issues': structures[-1].get('issues', []) if structures else [],
            'error': result.get('error'), 'artifact_directory': str(directory),
            'limits': '模型分数与程序通过不代表专项效果或安全已获独立认证；按checklist逐条核对完整原稿。'}


def run_evaluation(cases, output, week, max_calls=8, *, run=False, transport=None):
    root = Path(output).expanduser().resolve()
    # Refuse reuse to prevent mixing prior results or overwriting another test.
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    fixtures = build_cases(week)
    if not cases or any(case not in CASE_IDS for case in cases) or len(set(cases)) != len(cases):
        raise ValueError('cases must be unique known case IDs')
    actor = 'sportswise-sport-eval-' + uuid.uuid4().hex[:12]
    caller = LimitedCaller(max_calls, actor, transport)
    summary = {'executed_at_utc': datetime.now(timezone.utc).isoformat(),
               'synthetic': True, 'mode': 'real_pipeline' if run else 'offline_fixtures_only',
               'knowledge_version': training_knowledge.VERSION, 'week': week,
               'max_calls': max_calls, 'calls': 0, 'cases': [],
               'source_hashes': {str(p.relative_to(Path(__file__).resolve().parents[1])):
                   hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                       Path(ai_planning.__file__), Path(planning_policy.__file__),
                       Path(services.__file__), Path(training_knowledge.__file__), Path(__file__))}}
    write_json(root / 'manifest.json', {'actor': actor, 'cases': cases, 'week': week,
                                     'max_calls': max_calls, 'budget_enforced_by': 'services.planning_model_json'})
    for index, case in enumerate(cases):
        directory = root / case
        directory.mkdir(mode=0o700)
        profile = normalize_profile(copy.deepcopy(fixtures[case]))
        write_json(directory / 'input.json', {'profile': profile, 'knowledge': training_knowledge.select(profile),
                                            'manual_review_checklist': review_checklist(case)})
        remaining = max_calls-caller.calls
        # Reserve an author+review pair for later cases before spending on repairs.
        case_allowance = min(6, max(2, remaining-2*(len(cases)-index-1)))
        if not run or remaining < 2:
            summary['cases'].append({'case': case, 'verification_status': 'not_run',
                'reason': 'offline' if not run else 'global_call_limit', 'pipeline_accepted': False})
            continue
        state = {'profile': profile, 'planning_today': str(date.fromisoformat(week)-timedelta(days=1)),
                 'planning_week': week, 'records': [], 'history': [], 'plan': None,
                 'settings': {'email': False, 'followup': False}, 'compact_revisions': True,
                 'explanation_policy': True}
        events = []
        try:
            result = ai_planning.pipeline(profile, state, caller.for_case(profile, directory, case_allowance), events.append)
        except Exception as exc:
            result = {'ok': False, 'plan': None, 'review_trace': [], 'error': type(exc).__name__}
        write_json(directory / 'result.json', result)
        write_json(directory / 'events.json', events)
        summary['cases'].append({'case': case, 'case_call_allowance': case_allowance,
                                 **summarize(result, directory)})
    summary['calls'] = caller.calls
    write_json(root / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', choices=CASE_IDS, default=list(CASE_IDS))
    parser.add_argument('--output', default='/tmp/sportswise-sport-eval-' + uuid.uuid4().hex[:12])
    parser.add_argument('--max-calls', type=int, default=8, help='global cap across all cases, 1..24; reserve one author/review pair per case')
    parser.add_argument('--week', help='Monday YYYY-MM-DD; defaults to next complete week')
    parser.add_argument('--run', action='store_true', help='explicitly call real budgeted model services')
    args = parser.parse_args()
    today = date.today()
    week = args.week or str(today-timedelta(days=today.weekday())+timedelta(days=7))
    if args.run:
        if not config.API_KEY or not config.DB_PATH.is_file():
            parser.error('--run requires configured API key and an existing app llm_usage budget ledger; no db is initialized')
        # Daily yuan/call limits are enforced by the existing shared ledger in services.
        # Do not copy/reset the ledger or override DAILY_BUDGET/USER_DAILY_CALLS for this audit.
    summary = run_evaluation(args.cases, args.output, week, args.max_calls, run=args.run)
    print(json.dumps({'summary': str(Path(args.output).resolve()/'summary.json'),
                      'calls': summary['calls'], 'mode': summary['mode'], 'cases': summary['cases']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
