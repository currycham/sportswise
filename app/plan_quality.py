"""Explainable screening of a training draft; not medical approval or an LLM judge.

Public API: evaluate(plan, profile, previous=None). Does not mutate its inputs.
Unknown exercise names produce unknown coverage, never invented anatomical precision.
"""
from collections import Counter
from datetime import date
from . import training_knowledge
import re

VERSION = 'quality-rubric-v1'
WEIGHTS = {'goal':20, 'dose_coverage':20, 'experience':15, 'instructions':15,
           'recovery':10, 'feasibility':10, 'progression':5, 'transparency':5}
SOURCES = [
    {'title':'ACSM 2026 成人抗阻训练立场文件','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC12965823/'},
    {'title':'CDC 成年人活动建议','url':'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html'},
]
# Only prime movers count as direct sets; secondary involvement is not double-counted.
MOVEMENTS = {
    '哑铃臀桥':('hinge',('glutes',)), '站姿哑铃推举':('vertical_push',('shoulders',)),
    '哑铃侧平举':('shoulder_abduction',('shoulders',)), '哑铃弯举':('curl',('biceps',)),
    '俯卧撑':('push',('chest',)), '弹力带俯身划船':('pull',('back',)),
    '弹力带胸前推':('push',('chest',)), '弹力带髋折叠':('hinge',('hamstrings','glutes')),
    '单腿臀桥':('hinge',('hamstrings','glutes')), '徒手反向飞鸟':('shoulder_abduction',('shoulders',)),
    '死虫式':('core',('core',)),
    '哑铃杯式深蹲':('squat',('quads','glutes')), '徒手慢速深蹲':('squat',('quads','glutes')),
    '椅前深蹲':('squat',('quads','glutes')), '椅子坐站':('squat',('quads','glutes')),
    '扶稳浅蹲':('squat',('quads','glutes')), '扶稳反向弓步':('lunge',('quads','glutes')),
    '扶稳分腿蹲':('lunge',('quads','glutes')), '扶稳浅分腿蹲':('lunge',('quads','glutes')),
    '哑铃罗马尼亚硬拉':('hinge',('hamstrings','glutes')), '徒手髋折叠':('hinge',('glutes',)),
    '臀桥':('hinge',('glutes',)), '单臂哑铃划船':('pull',('back',)),
    '坐姿弹力带划船':('pull',('back',)), '俯身无负重划船':('pull',('back',)),
    '上斜俯卧撑':('push',('chest',)), '墙面俯卧撑':('push',('chest',)),
    '地板哑铃卧推':('push',('chest',)), '弹力带拉开':('pull',('upper_back',)),
    '四点支撑伸展':('core',('core',)), '扶墙站姿提膝':('core',('core',)),
    '扶稳提踵':('calf',('calves',)), '坐姿提踵':('calf',('calves',)),
    '坐姿轻阻力弯举':('curl',('biceps',)), '坐姿徒手弯举':('curl',('biceps',)),
    '坐姿肩胛后收':('pull',('upper_back',)), '坐姿轻弹力带拉开':('pull',('upper_back',)),
}
AEROBIC = {'walk','run','bike','indoor','dance','badminton','swim'}
MUSCLES = {'quads':'大腿前侧','glutes':'臀部','hamstrings':'大腿后侧','back':'背部',
           'chest':'胸部','upper_back':'上背','core':'躯干','calves':'小腿','biceps':'肱二头肌'}


def _num(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) else None


def _movement(step):
    pattern, fallback = MOVEMENTS.get(step.get('title'), ('unknown',()))
    raw = step.get('muscle_groups',step.get('muscles',step.get('primary_muscles',fallback)))
    muscles = [raw] if isinstance(raw,str) else list(raw or [])
    return step.get('movement_pattern',step.get('pattern',pattern)), ['quads' if m=='quadriceps' else m for m in muscles]


def _reps(step):
    value = step.get('rep_max',step.get('reps_max',step.get('reps',step.get('reps_min'))))
    if _num(value) is not None:
        return float(value)
    if isinstance(value,str):
        found = re.findall(r'\d+',value)
        return float(found[-1]) if found else None
    return None


def _effort(step, session):
    if step.get('rir') is not None or step.get('rpe') is not None:
        return True
    return any(x in str(step.get('intensity') or session.get('intensity','')) for x in ('余力','说话','交谈','RIR','RPE','休息','医嘱'))


def evaluate(plan, profile, previous=None):
    """Return score, hard failures, findings, dimensions and auditable dose facts.

    A score is a product QA result, not evidence of efficacy or individual safety.
    `previous` can be a prior plan or a list of prior plans; stable workouts are fine.
    """
    findings=[]
    factors={k:1.0 for k in WEIGHTS}
    def issue(code,dimension,message,penalty=.2,hard=False,evidence=None):
        findings.append({'code':code,'dimension':dimension,'severity':'hard_fail' if hard else 'review',
                         'message':message,'evidence':evidence or {}})
        factors[dimension]=max(0.,factors[dimension]-penalty)
    sessions=plan.get('sessions') or []
    active=[s for s in sessions if s.get('kind')!='rest' and s.get('minutes',0)>0]
    strength=[s for s in active if s.get('kind')=='strength']
    risk=(plan.get('risk') or {}).get('level','unknown')
    programming=plan.get('programming') or {}
    calibration=bool(plan.get('calibration') or plan.get('calibration_note') or programming.get('review') or programming.get('missing'))
    restricted=risk in ('caution','hold','age') or any(s.get('supported_upper') for s in strength)
    is_muscle=profile.get('goal') in ('muscle','strength','shape')
    advanced=profile.get('level')=='advanced' or profile.get('training_experience')=='advanced'
    available=profile.get('days') or []
    expected=2 if len(available)>=2 and any(min(abs(a-b),7-abs(a-b))>=2 for a in available for b in available) else 1
    if profile.get('adult') is False and active:
        issue('OUTSIDE_ADULT_SCOPE','recovery','用户未确认成人适用范围，仍安排成人主动训练。',1,True)
    if strength and re.search(r'(?:禁止|暂停|暂缓|不能|不做|不宜)[^。；，]{0,5}(?:力量|抗阻|负重)',profile.get('limitations','')):
        issue('EXPLICIT_RESISTANCE_CONFLICT','recovery','计划与用户明确的抗阻/负重限制冲突。',1,True)
    if not sessions:
        issue('EMPTY_PLAN','goal','计划没有任何逐日安排。',1,True)
    if risk in ('hold','age') and active:
        issue('ACTIVE_DURING_HOLD','recovery','不适用或明确暂停主动训练的计划仍含主动训练。',1,True)
    if risk in ('hold','age') and not active:
        # No pressure to add workouts to a hold plan.
        is_muscle=False
    elif not active:
        issue('NO_ACTIVE_TRAINING','goal','没有可执行的训练；需要明确说明适用性和原因。',1,True)
    if is_muscle and not restricted and not strength:
        issue('MUSCLE_WITHOUT_RESISTANCE','goal','力量/增肌目标却没有任何抗阻课。',1,True)
    elif is_muscle and not restricted and len(strength)<expected:
        issue('RESISTANCE_FREQUENCY','goal','可用日允许更多抗阻安排，但目标所需课次未体现。',.5,
              evidence={'actual':len(strength),'feasible_target':expected})
    if restricted and is_muscle:
        issue('RESTRICTED_NOT_FULL_PROGRAM','goal','这是受限或过渡安排，不能作为已满足进阶增肌目标的完整训练。',.2)
    if profile.get('goal')=='endurance' and not any(s.get('kind') in AEROBIC for s in active) and not restricted:
        issue('ENDURANCE_WITHOUT_AEROBIC','goal','耐力目标未包含匹配的有氧训练。',.8,True)
    dates=[]; sets_by_muscle=Counter(); patterns=Counter(); dose_steps=[]; unknown=[]
    if not plan.get('rationale'):
        issue('NO_RATIONALE','goal','没有解释档案如何影响训练内容。',.2)
    for session in sessions:
        key=session.get('date')
        try:
            dt=date.fromisoformat(key); dates.append(key)
        except (TypeError,ValueError):
            issue('BAD_DATE','feasibility','课程日期无效。',1,True); continue
        steps=session.get('steps') or []
        minutes=session.get('minutes',0)
        if _num(minutes) is None or minutes<0 or any(_num(s.get('minutes')) is None or s['minutes']<0 for s in steps):
            issue('BAD_DURATION','feasibility','时长缺失、为负或不是数字。',1,True);continue
        if abs(sum(s['minutes'] for s in steps)-minutes)>.01:
            issue('TIME_SUM','feasibility','步骤时间之和与课程总时长不符。',1,True,evidence={'date':key})
        if minutes>profile.get('minutes',minutes):
            issue('TIME_BUDGET','feasibility','课程超出用户单次可用时间。',1,True,evidence={'date':key})
        if session.get('kind')!='rest' and available and dt.weekday() not in available:
            issue('UNAVAILABLE_DAY','feasibility','在用户未选择的日期安排主动训练。',.5,evidence={'date':key})
        if minutes and (not steps or not session.get('purpose') or not session.get('intensity')):
            issue('SESSION_INSTRUCTIONS','instructions','训练缺少目的、强度或步骤。',.25,evidence={'date':key})
        if session.get('kind')!='strength':
            continue
        counted=Counter()
        for step in steps:
            if step.get('kind') in ('warmup','cooldown'):
                continue
            sets=_num(step.get('sets')); reps=_reps(step); rest=_num(step.get('rest_seconds'))
            pattern,muscles=_movement(step)
            if sets is None or sets<1 or reps is None or reps<1 or rest is None or rest<0:
                issue('MISSING_DOSE','instructions','抗阻动作缺少可用的组数、次数或休息秒数。',.2,evidence={'exercise':step.get('title')});continue
            if not all(step.get(k) for k in ('detail','caution','benefit')) or not _effort(step,session):
                issue('MISSING_CUES','instructions','动作缺少要领、注意事项、目的或可执行的强度标准。',.15,evidence={'exercise':step.get('title')})
            if not muscles:
                unknown.append(step.get('title'))
            patterns[pattern]+=sets
            for muscle in muscles:
                sets_by_muscle[muscle]+=sets
                counted[muscle]+=sets
            # Conservative check: 3 s/rep, each_side if specified, only between-set rests.
            needed=sets*reps*(2 if step.get('each_side') else 1)*3+max(0,sets-1)*rest
            if needed>step['minutes']*60+30:
                issue('DOSE_DOES_NOT_FIT','feasibility','按组次、每侧次数及组间休息估算，动作装不进时间框。',.6,True,
                      {'exercise':step.get('title'),'minimum_estimated_seconds':needed,'budget_seconds':step['minutes']*60})
            dose_steps.append(step)
    if len(dates)!=len(set(dates)):
        issue('DUPLICATE_DATE','feasibility','同一天重复排课。',1,True)
    if unknown:
        issue('UNKNOWN_MUSCLES','dose_coverage','有动作无法确认主要肌群，不能给出完整覆盖结论。',.2,evidence={'exercises':unknown})
    if is_muscle and strength and not restricted:
        missing=[p for p in ('squat','hinge','push','pull') if not patterns[p]]
        if missing:
            issue('MISSING_MOVEMENT_PATTERNS','dose_coverage','全身目标缺少关键动作模式。',min(.7,.2*len(missing)),evidence={'missing':missing})
        if profile.get('goal')=='muscle' and (advanced or profile.get('level')=='regular'):
            # ~10 sets is an evidence-informed reference, not a mandatory personal threshold.
            low={k:v for k,v in sets_by_muscle.items() if k in ('quads','hamstrings','chest','back') and v<10}
            if low:
                issue('LOW_TARGET_DOSE','dose_coverage','主要肌群周直接组数偏少；需说明时间约束/校准，并依历史表现设定剂量，不能仅靠增肌标签。',.4,evidence={'direct_sets':low,'reference':'ACSM 2026: higher volumes ≥10 sets/muscle/week enhanced hypertrophy; not a universal minimum'})
    # Recovery uses overlap, so upper/lower splits are not rejected for adjacent dates.
    previous_plans=previous if isinstance(previous,list) else [previous] if previous else []
    prior=[s for p in previous_plans if p for s in p.get('sessions',[]) if s.get('kind')=='strength' and s.get('date','')<plan.get('week','')]
    resistance=sorted([*prior,*strength],key=lambda x:x.get('date',''))
    for a,b in zip(resistance,resistance[1:]):
        try: gap=(date.fromisoformat(b['date'])-date.fromisoformat(a['date'])).days
        except (KeyError,ValueError): continue
        left={m for s in a.get('steps',[]) if (_num(s.get('sets')) or 0)>=2 for m in _movement(s)[1]}
        right={m for s in b.get('steps',[]) if (_num(s.get('sets')) or 0)>=2 for m in _movement(s)[1]}
        if gap<2 and left & right:
            issue('RECOVERY_OVERLAP','recovery','相邻日重复负荷同一主要肌群，需解释拆分、减量或恢复依据。',.5,evidence={'dates':[a['date'],b['date']],'overlap':sorted(left&right)})
    if profile.get('level') in ('regular','advanced') and not restricted:
        known_history=bool(profile.get('routine_detail') or profile.get('familiar_exercises') or profile.get('known_exercises'))
        if not known_history:
            issue('UNVERIFIED_TRAINING_BASELINE','experience','规律/进阶标签不能代替最近实际训练量；需要记录基线或明确试行范围。',.4)
    if advanced and not restricted:
        baseline=profile.get('training_months') is not None and bool(profile.get('familiar_exercises') or profile.get('known_exercises') or profile.get('routine_detail'))
        if not baseline and not calibration:
            issue('ADVANCED_WITHOUT_BASELINE','experience','标记进阶但缺少训练月数/熟悉动作，也没有明确校准说明。',.6)
        if strength and not any(s.get('rir') is not None or '余力' in str(s.get('intensity','')) for s in dose_steps):
            issue('NO_EFFORT_TARGET','experience','进阶抗阻未给出余力或RIR目标。',.4)
    if profile.get('level')=='beginner' and any((_num(s.get('sets')) or 0)>4 for s in dose_steps) and not restricted:
        issue('BEGINNER_HIGH_VOLUME','experience','新手单动作组数偏高，需提供校准依据。',.5)
    if not (plan.get('progression') or plan.get('progression_rule') or plan.get('calibration') or programming.get('progression')):
        issue('NO_PROGRESSION','progression','没有计划内的维持、回退和进阶决策条件。',1)
    if not any(s.get('alternatives') for s in dose_steps) and strength and not restricted:
        issue('NO_SUBSTITUTIONS','feasibility','抗阻动作没有替代选择。',.15)
    if not (plan.get('source') or plan.get('sources')):
        issue('NO_PROVENANCE','transparency','没有标明计划内容来源。',1)
    elif not plan.get('sources'):
        issue('NO_PLAN_CITATIONS','transparency','仅标记来源类型，尚不能把具体处方追溯到依据。',.4)
    dimensions={k:{'score':round(WEIGHTS[k]*factors[k],1),'maximum':WEIGHTS[k]} for k in WEIGHTS}
    raw=round(sum(x['score'] for x in dimensions.values()),1)
    hard=[f for f in findings if f['severity']=='hard_fail']
    score=min(raw,49) if hard else raw
    target_limited=restricted and profile.get('goal') in ('muscle','strength','shape')
    low_target=any(f['code']=='LOW_TARGET_DOSE' for f in findings)
    if not hard and target_limited:
        score=min(score,69)
    elif not hard and low_target:
        score=min(score,79)
    elif not hard and any(f['code']=='UNVERIFIED_TRAINING_BASELINE' for f in findings):
        score=min(score,79)
    fulfillment=('not_applicable_or_hold' if risk in ('age','hold') else
                 'restricted_transition_only' if target_limited else
                 'dose_needs_calibration' if low_target else
                 'baseline_unverified' if any(f['code']=='UNVERIFIED_TRAINING_BASELINE' for f in findings) else 'screened_with_limits')
    return {'version':VERSION,'score':score,'raw_score':raw,'status':'blocked' if hard else 'revise' if score<80 else 'screened',
            'goal_fulfillment':fulfillment,
            'hard_failures':hard,'findings':findings,'dimensions':dimensions,
            'scope':'restricted_transition' if restricted else 'calibration' if calibration else 'general_program',
            'facts':{'strength_sessions':len(strength),'active_sessions':len(active),
                     'direct_sets_by_muscle':dict(sets_by_muscle),'movement_pattern_sets':dict(patterns),
                     'restricted_plan':restricted,'advanced_profile':advanced},
            'limits':['规则评分不是医学许可，也不是训练效果保证。','肌群组数只计主要肌群；未知动作不推断。','稳定重复的有效训练不因缺少花样而扣分。'],
            'reference_sources':training_knowledge.select(profile)['sources'],
            'knowledge_version':training_knowledge.VERSION}


score_plan = evaluate
