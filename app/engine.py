"""Constrained starter templates; all durations, history and changes are deterministic."""
import copy
import re
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from . import growth, load, plan_quality, programming, training_knowledge, workouts

PLAN_POLICY = "evidence-v6.1"

SOURCES = [
    {'title': 'NIDDK · 从少量活动开始', 'url': 'https://www.niddk.nih.gov/health-information/weight-management/tips-get-active/tips-starting-physical-activity'},
    {'title': 'NHS · 基础力量动作说明', 'url': 'https://www.nhs.uk/live-well/exercise/strength-exercises/'},
    {'title': 'ACOG · 经期不适与活动', 'url': 'https://www.acog.org/womens-health/faqs/dysmenorrhea-painful-periods'},
    {'title': '运动表现与月经周期 · 系统综述', 'url': 'https://doi.org/10.1007/s40279-020-01319-3'},
    {'title':'ACSM · 成人抗阻训练立场文件','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC12965823/'},
    {'title':'有氧训练与线粒体适应 · 系统综述','url':'https://pubmed.ncbi.nlm.nih.gov/39390310/'},
    {'title':'跑步相关膝前疼痛 · 最佳实践指南','url':'https://bjsm.bmj.com/content/58/24/1486'},
    {'title': 'CDC · 成年人的身体活动', 'url': 'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html'},
]
GOALS = {'habit': '建立运动规律', 'energy': '改善日常体能', 'strength': '提升力量', 'endurance': '提升耐力', 'muscle':'增加肌肉', 'shape':'体态与力量', 'bone':'骨骼与力量'}
DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def uid():
    return uuid.uuid4().hex


def today(state=None):
    return datetime.now(ZoneInfo((state or {}).get('settings', {}).get('timezone', 'Asia/Shanghai'))).date()


def monday(d):
    return d - timedelta(days=d.weekday())


def empty():
    return {'profile': None, 'plan': None, 'upcoming': None, 'history': [], 'records': [], 'reviews': [],
            'chat': [], 'blocked': False,
            'settings': {'timezone': 'Asia/Shanghai', 'daily': True, 'weekly': True, 'monthly': True,
                         'followup': False, 'email': False, 'time': '18:30', 'quiet_start': '22:00',
                         'quiet_end': '08:00', 'tone': 'gentle', 'paused_until': ''}}


def sample_profile():
    return {'name': '运动者', 'goal': 'energy', 'motivation': '让运动成为生活的一部分，周末走远一点也不累。',
            'current': '偶尔散步，正在找回运动节奏', 'level': 'returning', 'days': [0, 2, 6],
            'minutes': 25, 'equipment': ['bodyweight'], 'place': 'mixed', 'likes': ['walking', 'strength'],
            'limitations': '', 'adult': True, 'consent': True}


def limitation_residual(text):
    """Remove explicit absence statements, not affirmative symptoms or ambiguous free text."""
    text=re.sub(r'(?:目前|现在|近期)?(?:无|没有)(?:疼痛|不适|伤病)(?:或|和|及)(?:明确的?|任何)?运动限制','',text)
    body=r'(?:膝(?:盖)?(?:伤|痛|疼痛)|腰(?:背)?(?:伤|痛|疼痛)|伤病|旧伤|疼痛|不适|胸痛|胸闷|头晕|呼吸困难|晕厥|受伤|运动限制|健康问题)'
    text=re.sub(r'(?:目前|现在|近期)?(?:膝(?:盖)?|腰背|腰部|背部|肩部|身体)(?:目前)?(?:无|没有|未见)(?:疼痛|不适|伤病|旧伤|异常)','',text)
    text=re.sub(r'(?:目前|现在|近期)?(?:没有出现|没有任何|没有|未出现|未见|无)'+body,'',text)
    return text.strip('，,。.;；、 !！')


def posture_advisory(text):
    """Recognize a narrow posture/tightness note; never waive injury or medical restrictions."""
    if not re.search(r'紧张|紧绷|僵硬',text):
        return False
    allowed=r'久坐|久站|腰背|背部|腰部|竖脊肌|腰方肌|肌肉|比较|有些|有点|紧张|紧绷|僵硬|容易|感觉|日常|平时|轻微|偶尔|因为|导致|造成|和|与|及|的'
    return not re.sub(allowed,'',text).strip('，,、。；; !！')


def resistance_route(p):
    """Return the resistance option consistent with disclosed restrictions."""
    note=limitation_residual(p.get('limitations',''))
    if posture_advisory(note):
        return 'standard'
    if re.search(r'(?:避免|不得|不可|不宜|不要|不能|不做|暂停|禁止|暂缓|限制)[^。；，、]{0,5}(?:抗阻|力量|负重|举重|器械)',note):
        return 'avoid'
    if not any(w in note for w in ('膝','关节','腰','背','疼','痛','伤','手术')):
        return 'standard'
    lower_or_back=re.search(r'膝|腿|髋|踝|脚|足|腰|背|脊柱',note)
    other=re.search(r'肩|颈|手腕|手臂|手肘|肘|上肢|术后|手术|急性|严重|麻木|放射|肿胀|骨质疏松|妊娠|怀孕|产后|康复中|半月板|韧带|椎间盘|突出|训练反馈中报告不适',note)
    if p.get('level') in ('regular','advanced') and p.get('goal') in workouts.STRENGTH_GOALS and lower_or_back and not other:
        return 'supported_upper'
    return 'avoid'


def make_session(d, kind, minutes, p, variant=0, easy_only=False, runner_support=False):
    risk = health_risk(p)
    if risk['level'] in ('hold', 'age') or kind == 'rest':
        hold = risk['level'] in ('hold', 'age')
        return {'id':uid(), 'date':d.isoformat(), 'kind':'rest',
                'title':'恢复与确认 · 暂停主动训练' if hold else '恢复休息',
                'minutes':0, 'original_minutes':0, 'original_kind':'rest',
                'purpose':risk['message'] if hold else '留出恢复时间，不需要补课。',
                'steps':[], 'status':'rest', 'intensity':'休息'}
    route='standard'
    if risk['level'] == 'caution':
        minutes = min(int(minutes),15)
        route=resistance_route(p)
        if kind in ('run','bike','badminton','dance') or (kind=='strength' and route=='avoid') or (
                kind=='mobility' and route!='standard'):
            kind='indoor'
        easy_only=True
    minutes = max(10, min(int(minutes), 90))
    content=workouts.workout(kind,minutes,p,variant,easy_only,runner_support and kind=='strength',route=='supported_upper')
    actual=sum(x['minutes'] for x in content['steps'])
    return {'id':uid(),'date':d.isoformat(),'kind':kind,'minutes':actual,'original_minutes':actual,
            'original_kind':kind,'status':'planned',**content}


def health_risk(p):
    """Product routing, not a medical assessment. Health notes never suppress plan output."""
    text = limitation_residual((p or {}).get('limitations', '').strip().strip('。.!！'))
    if not (p or {}).get('adult', False):
        return {'level': 'age', 'message': '当前训练模板面向成年人，请先确认年龄适用范围。'}
    if posture_advisory(text):
        return {'level':'none','message':'已把久坐与肌肉紧张纳入热身和恢复关注点。先用熟悉的阻力校准；若活动引起疼痛或不适加重，停止并确认原因。'}
    no_issue = r'(?:无|没有|暂无|健康|身体健康|身体状况良好|身体正常|无特殊情况|(?:无|没有|目前没有|暂无)(?:任何|特殊)?(?:身体|健康|运动)?(?:限制|不适|伤病|疾病|问题|异常|禁忌))'
    if not text or all(re.fullmatch(no_issue, part.strip()) for part in re.split(r'[，、,；;。]+', text) if part.strip()):
        return {'level': 'none', 'message': ''}
    # Ignore explicitly negated symptoms; this is a routing aid, never medical clearance.
    symptoms = re.sub(r'(?:没有|无|不伴有|没有出现)(?:任何)?(?:胸痛|胸闷|头晕|呼吸困难|晕厥|不适|疼痛)', '', text)
    urgent = ('胸痛','胸闷','呼吸困难','晕厥','晕倒','头晕','急性发作','医生禁止运动','禁止运动','暂停运动','停止运动','卧床','禁止负重','不能行走','骨折')
    if any(word in symptoms for word in urgent):
        return {'level': 'hold', 'message': '已生成恢复与确认安排：目前先暂停主动训练，及时确认不适或遵循已有医嘱；症状严重或持续时及时就医，确认可以活动后再恢复训练。'}
    return {'level': 'caution', 'message': '已结合身体情况生成较轻量安排。活动类型与强度请遵医嘱；出现不适时停止，医嘱有冲突时以医嘱为准。'}


def safety(p):
    # Only age applicability blocks these adult templates. Other risks produce a plan with guidance.
    return health_risk(p)['level'] == 'age'


def reconcile_health(state):
    """Upgrade legacy blanket blocks without discarding profile, history or actual records."""
    p = state.get('profile')
    if not p:
        return False
    risk = health_risk(p)
    old_risk = state.get('risk')
    was_blocked = state.get('blocked', False)
    changed = old_risk != risk or was_blocked != safety(p)
    state['risk'] = risk
    state['blocked'] = safety(p)
    if state['blocked']:
        return changed
    if p['goal'] not in GOALS or p['level']=='competitive' or any(x not in workouts.ACTIVITIES for x in p['likes']) or (state.get('plan') or {}).get('policy')=='ai-reviewed-v1':
        if changed and risk['level'] in ('caution','hold','age'):
            recorded={r.get('session_id') for r in state['records']}
            for slot in ('plan','upcoming'):
                plan=state.get(slot)
                if plan:
                    plan['sessions']=[make_session(date.fromisoformat(x['date']),'rest',0,p)
                                      if x['date']>=today(state).isoformat() and x['id'] not in recorded else x for x in plan['sessions']]
                    plan['reason']='身体反馈发生变化，请重新生成并核对适用方案；已记录内容保留。'
        return changed
    if not state.get('plan') or was_blocked or (changed and (risk['level'] != 'none' or old_risk)):
        d = today(state)
        previous = state.get('plan')
        plan = generate(p, monday(d), previous, '根据你的身体情况和可用时间更新安排；具体执行结合医嘱')
        recorded = {r.get('session_id') for r in state['records']}
        old_by = {x['date']:x for x in (previous or {}).get('sessions',[])}
        plan['sessions'] = [old_by[x['date']] if x['date'] in old_by and (x['date']<d.isoformat() or old_by[x['date']]['id'] in recorded)
                            else make_session(date.fromisoformat(x['date']),'rest',0,p) if x['date']<d.isoformat() else x
                            for x in plan['sessions']]
        plan['baseline'] = previous['baseline'] if previous and previous['week']==plan['week'] else sum(x['minutes'] for x in plan['sessions'])
        archive(state)
        state['plan'] = plan
        state['upcoming'] = None
        return True
    return changed


def generate(p, start=None, previous=None, reason='根据你的时间与目标制定训练计划', duration=None, easy_only=False, load_flags=()):
    start = start or monday(date.today())
    days = sorted(set(p['days']))
    split = workouts.schedule(p, start)
    cap = {'beginner':20, 'returning':25, 'regular':90,'advanced':90}[p['level']]
    if p['level'] in ('regular','advanced') and p.get('usual_minutes') and duration is None:
        cap = min(cap,p['usual_minutes'])
    budget = min(p['minutes'], cap, duration if duration is not None else 90)
    sessions = []
    runner_support=p['goal'] not in ('muscle','shape','bone') and any(k=='run' for k,v in split.values()) and (
        p['goal']=='endurance' or sum(k=='run' for k,v in split.values())>=2)
    recovery_used=set()
    for i in range(7):
        kind, variant = split.get(i, ('rest', 0))
        minutes = budget
        if kind in ('walk','indoor','run','bike') and variant % 3 == 1:
            minutes = max(10, budget - 5)
        if kind == 'mobility':
            minutes = min(20, budget)
        recovery=next((f['kind'] for f in load_flags if f['kind'] not in recovery_used
                       and (kind==f['kind'] or (f['kind']=='aerobic' and kind in workouts.AEROBIC))),None)
        if recovery:
            recovery_used.add(recovery)
            chosen=load.RECOVERY[recovery]
            if chosen=='bike' and 'cycling' not in p['likes']:
                chosen='walk'
            sessions.append(make_session(start+timedelta(days=i),workouts.feasible(chosen,p),min(20,minutes),p,easy_only=True))
        else:
            sessions.append(make_session(start+timedelta(days=i),kind,minutes,p,variant,easy_only,runner_support))
    risk = health_risk(p)
    focus = '、'.join(dict.fromkeys(workouts.LABELS[s['kind']] for s in sessions if s['kind']!='rest'))
    level = {'beginner':'刚起步','returning':'恢复训练','regular':'已有规律训练','advanced':'进阶训练，按工作组与恢复校准'}[p['level']]
    extra=''
    if any(s.get('supported_upper') for s in sessions):
        extra+=' 根据身体限制改用坐姿上肢轻抗阻，暂不安排会牵扯受限部位的负重动作。'
    if any(s.get('runner_support') for s in sessions):
        extra+=' 跑步搭配下肢抗阻与小腿放松，练习承载和动作控制。'
    if p['goal']=='bone':
        extra+=' 优先安排熟悉的抗阻和负重活动；记录训练量，不能据此测得骨密度。'
    if recovery_used:
        extra+=' 针对'+ '、'.join(workouts.LABELS.get(k,'有氧合计') for k in sorted(recovery_used))+'，各换一节轻量活动，保留恢复时间。'
    elif load_flags:
        extra+=' 下周未排入超量项目，优先减少计划外的同类运动。'
    plan = {'id':uid(), 'version':(previous or {}).get('version',0)+1,
            'week':start.isoformat(), 'created':datetime.now().isoformat(timespec='seconds'),
            'reason':reason, 'goal':p['goal'], 'goal_label':GOALS[p['goal']],
            'rationale':(f'你选择了「{GOALS[p["goal"]]}」，目前{level}。本周以{focus}为主，'
                         f'使用每周 {len(days)} 个可用日，单次不超过 {budget} 分钟。{extra}') if focus else risk['message'],
            'phase':'恢复与确认' if not focus else '轻量恢复' if easy_only or risk['level']=='caution' else '巩固与提升' if p['level'] in ('regular','advanced') else '适应与校准',
            'sessions':sessions, 'baseline':sum(s['minutes'] for s in sessions),
            'source':'template', 'sources':SOURCES, 'risk':risk, 'policy':PLAN_POLICY, 'easy_only':easy_only}
    plan['knowledge']=training_knowledge.select(p)
    plan['sources']=plan['knowledge']['sources']
    plan['programming']=programming.analyse(plan,p)
    plan['generator']={'type':'constrained_programming','policy':PLAN_POLICY,
                       'model_generated':False,'description':'目标排课 → 器械动作库 → 时间/恢复约束 → 剂量汇总与校准'}
    validate_plan(plan,p)
    plan['quality']=plan_quality.evaluate(plan,p,previous)
    return plan


def validate_plan(plan, p, locked_ids=()):
    risk = health_risk(p)
    seen = set()
    for s in plan['sessions']:
        d = date.fromisoformat(s['date'])
        if s['date'] in seen:
            raise ValueError('同一天已有安排，请选择其他日期')
        seen.add(s['date'])
        if s['kind'] not in workouts.TYPES:
            raise ValueError('训练类型不在已支持的内容中')
        if s['kind'] != 'rest':
            pending = s['id'] not in locked_ids and s['date'] >= today().isoformat()
            if pending and risk['level'] in ('hold','age'):
                raise ValueError('当前安排应以恢复与确认情况为主，不增加主动训练')
            if pending and risk['level']=='caution':
                if s['minutes']>15:
                    raise ValueError('当前身体情况先采用较轻量安排，单次不超过 15 分钟')
                if s['kind']=='strength':
                    route=resistance_route(p)
                    if route=='avoid' or (route=='supported_upper' and not s.get('supported_upper')):
                        raise ValueError('此力量安排不符合档案中的身体限制，请重新生成计划')
            if not 10 <= s['minutes'] <= 90 or sum(x['minutes'] for x in s['steps']) != s['minutes']:
                raise ValueError('训练时长与动作安排不一致')
            if s['minutes'] > p['minutes'] and s['id'] not in locked_ids and s['date'] >= today().isoformat():
                raise ValueError('安排超过了你的单次可用时间')
    strength_dates = sorted(date.fromisoformat(s['date']) for s in plan['sessions'] if s['kind'] == 'strength')
    if any((b-a).days < 2 for a, b in zip(strength_dates, strength_dates[1:])):
        raise ValueError('基础力量训练之间至少留出一天恢复，请改到其他日期')


PERIOD_MODES = {'normal':'照常训练', 'ease':'减量训练', 'rest':'休息恢复'}


def period_view(state):
    period = state.get('period')
    if period and period['start'] <= today(state).isoformat() <= period['end']:
        return {k:period[k] for k in ('start','end','mode')}
    return None


def effective_plan(state, plan, day=None):
    if not plan:
        return None
    period = state.get('period')
    day_key = (day or today(state)).isoformat()
    records = {r['session_id']:r for r in state['records'] if r.get('session_id')}
    sessions = []
    for s in plan['sessions']:
        r = records.get(s['id'])
        if r and r.get('prescription'):
            sessions.append(r['prescription'])
        elif (not r and period and period['mode'] != 'normal' and s['kind'] != 'rest'
              and period['start'] <= s['date'] <= period['end'] and s['date'] >= day_key):
            mode = period['mode']
            light_kind = 'strength' if s['kind']=='strength' and state['profile']['goal'] in workouts.STRENGTH_GOALS else 'mobility' if s['kind'] in ('strength','mobility') else ('walk' if s['kind']=='walk' else 'indoor')
            replacement = make_session(date.fromisoformat(s['date']), 'rest' if mode=='rest' else light_kind,
                                       max(10, min(20, (s['minutes']+1)//2)), state['profile'],
                                       s.get('variant',0), easy_only=True)
            sessions.append({**replacement, 'id':s['id'], 'original_minutes':s['original_minutes'],
                             'original_kind':s['original_kind'], 'period_adjusted':True,
                             'title':'今天休息 · 留出恢复时间' if mode=='rest' else replacement['title'],
                             'purpose':'按当前感受休息，之后不补课。' if mode=='rest' else replacement['purpose']+' 有不适就停下或改为休息。'})
        else:
            sessions.append(s)
    return {**plan, 'sessions':sessions}


def settle_period_days(state, day):
    """Keep the lighter prescription for past dates; retain no cycle history or symptoms."""
    period = state.get('period')
    if not period:
        return False
    cutoff = min((day-timedelta(days=1)).isoformat(), period['end'])
    lower = max(period['start'],period.get('settled_until',''))
    if cutoff < lower or cutoff <= period.get('settled_until',''):
        return False
    for slot in ('plan','upcoming'):
        plan = state.get(slot)
        if plan and period['mode'] != 'normal':
            past = effective_plan(state,plan,date.fromisoformat(lower))
            plan['sessions'] = [{k:v for k,v in display.items() if k!='period_adjusted'}
                                if lower <= s['date'] <= cutoff and s['date'] != period.get('settled_until')
                                and display.get('period_adjusted') else s
                                for s,display in zip(plan['sessions'],past['sessions'])]
    period['settled_until'] = cutoff
    return True


def present(state):
    return {**state, 'period':period_view(state), 'plan':effective_plan(state,state['plan']),
            'upcoming':effective_plan(state,state.get('upcoming'))}


def preserve_recovery(plan, p, locked, before=()):
    """Keep actual/past sessions; make a conflicting new strength day a recovery session."""
    strength = [date.fromisoformat(s['date']) for s in (*plan['sessions'], *before)
                if s['kind']=='strength' and s['id'] in locked]
    for i, s in enumerate(plan['sessions']):
        if s['kind'] != 'strength' or s['id'] in locked:
            continue
        d = date.fromisoformat(s['date'])
        if any(abs((d-x).days) <= 1 for x in strength):
            plan['sessions'][i] = {**make_session(d,'mobility',min(20,s['minutes']),p,easy_only=True), 'id':s['id']}
        else:
            strength.append(d)
    return plan


def restore_strength_priority(plan,p,day,locked,before=()):
    """A midweek rebuild must not spend all its remaining usable days on accessories."""
    if p['goal'] not in workouts.STRENGTH_GOALS or health_risk(p)['level'] in ('age','hold'):
        return plan
    if health_risk(p)['level']=='caution' and resistance_route(p)=='avoid':
        return plan
    fixed=[date.fromisoformat(s['date']) for s in (*plan['sessions'],*before) if s['kind']=='strength']
    kept=[s for s in plan['sessions'] if s['kind']=='strength' and (s['date']>=day.isoformat() or s['id'] in locked)]
    have=len(kept)
    variants={s.get('variant',0)%2 for s in kept}
    budget=max((s['minutes'] for s in plan['sessions']),default=0)
    for i,s in enumerate(plan['sessions']):
        if have>=2:
            break
        if (s['id'] in locked or s['date']<day.isoformat() or s['kind'] in ('strength','rest')
                or date.fromisoformat(s['date']).weekday() not in p['days']):
            continue
        d=date.fromisoformat(s['date'])
        if any(abs((d-x).days)<2 for x in fixed):
            continue
        variant=0 if 0 not in variants else 1
        plan['sessions'][i]={**make_session(d,'strength',min(p['minutes'],max(s['minutes'],budget)),p,
                                          variant=variant,easy_only=plan.get('easy_only',False)), 'id':s['id']}
        variants.add(variant)
        fixed.append(d)
        have+=1
    return plan


def upgrade_plan(state, plan, day):
    p = state['profile']
    flags=load_flags(state)
    revised = generate(p,date.fromisoformat(plan['week']),plan,'已按你的运动水平、目标和身体限制更新后续训练',
                       load_flags=flags)
    recorded = {r.get('session_id') for r in state['records']}
    old = {s['date']:s for s in plan['sessions']}
    original_dates = {}
    for version in state['history']:
        if version['week'] == plan['week']:
            for s in version['sessions']:
                original_dates.setdefault(s['id'],s['date'])
    locked = set()
    for i, fresh in enumerate(revised['sessions']):
        s = old.get(fresh['date'])
        if not s:
            continue
        moved = s['id'] in original_dates and s['date'] != original_dates[s['id']]
        edited = (moved or s['kind']!=s.get('original_kind') or s['minutes']!=s.get('original_minutes') or s.get('customized'))
        if s['date'] < day.isoformat() or s['id'] in recorded or edited:
            revised['sessions'][i] = s
            locked.add(s['id'])
        else:
            revised['sessions'][i]['id'] = s['id']
    revised['baseline'] = plan['baseline']
    current=state.get('plan')
    previous=[*state['history'],*([current] if current else [])]
    prev_week=(date.fromisoformat(plan['week'])-timedelta(days=7)).isoformat()
    before=next((x['sessions'] for x in reversed(previous) if x['week']==prev_week),[])
    locked.update(s['id'] for s in before)
    preserve_recovery(revised,p,locked,before)
    return restore_strength_priority(revised,p,day,locked,before) if not any(f['kind']=='strength' for f in flags) else revised


def regenerate_current_and_next(state,reason):
    p=state.get('profile')
    if not p or safety(p):
        raise ValueError('需要已确认的成人运动档案')
    d=today(state)
    old=state.get('plan')
    recorded={r.get('session_id') for r in state['records']}
    current=generate(p,monday(d),old,reason,load_flags=load_flags(state))
    by_date={s['date']:s for s in (old or {}).get('sessions',[])}
    for i,s in enumerate(current['sessions']):
        prior=by_date.get(s['date'])
        if prior and (s['date']<d.isoformat() or prior['id'] in recorded):
            current['sessions'][i]=copy.deepcopy(prior)
        elif s['date']<d.isoformat():
            current['sessions'][i]=make_session(date.fromisoformat(s['date']),'rest',0,p)
    locked=recorded|{s['id'] for s in current['sessions'] if s['date']<d.isoformat()}
    preserve_recovery(current,p,locked)
    restore_strength_priority(current,p,d,locked)
    current['baseline']=old['baseline'] if old and old['week']==current['week'] else sum(s['minutes'] for s in current['sessions'])
    archive(state)
    state['plan']=current
    state['risk']=health_risk(p)
    state['blocked']=False
    upcoming=generate(p,monday(d)+timedelta(days=7),state.get('upcoming') or current,reason,load_flags=load_flags(state))
    before=current['sessions'];locked={s['id'] for s in before}
    preserve_recovery(upcoming,p,locked,before)
    restore_strength_priority(upcoming,p,date.fromisoformat(upcoming['week']),locked,before)
    for plan in (current,upcoming):
        plan['programming']=programming.analyse(plan,p)
        plan['quality']=plan_quality.evaluate(plan,p,current if plan is upcoming else old)
        validate_plan(plan,p,recorded)
    state['upcoming']=upcoming
    return state


def archive(state):
    if state['plan']:
        state['history'].append(copy.deepcopy(state['plan']))


def progress(state, start=None, end=None):
    start = start or monday(today(state))
    end = end or start + timedelta(days=7)
    records = [r for r in state['records'] if start.isoformat() <= r['date'] < end.isoformat()]
    sessions = {}
    versions = state['history'] + ([state['plan']] if state['plan'] else [])
    originals, latest = {}, {}
    for plan in versions:
        if start.isoformat() <= plan['week'] < end.isoformat():
            originals.setdefault(plan['week'], plan['baseline'])
        latest[plan['week']] = plan
    for plan in latest.values():
        for session in plan['sessions']:
            if start.isoformat() <= session['date'] < end.isoformat():
                sessions[session['id']] = session
    planned = [s for s in sessions.values() if s['kind'] != 'rest']
    completed = [r for r in records if r['status'] in ('completed', 'partial')]
    recorded_ids = {r.get('session_id') for r in records}
    return {'minutes': sum(r['minutes'] for r in completed), 'completed': len(completed),
            'full': sum(r['status'] == 'completed' for r in records), 'planned': len(planned),
            'unknown': sum(s['date'] < today(state).isoformat() and s['id'] not in recorded_ids for s in planned),
            'planned_minutes': sum(s['minutes'] for s in planned), 'original_minutes': sum(originals.values()),
            'records': records}


def record_kind(record,sessions):
    planned=record.get('prescription') or sessions.get(record.get('session_id')) or {}
    kind=record.get('activity_kind') or (planned.get('kind') if record.get('session_id') else None)
    if kind in workouts.TYPES or kind=='other':
        return kind
    # Legacy free records: only recognizable names count toward a specific category.
    label=record.get('activity','')
    categories={'run':('跑步','慢跑','节奏跑','跑走'), 'badminton':('羽毛球',), 'bike':('骑车','骑行','单车'),
                'dance':('跳舞','有氧舞','舞蹈'), 'walk':('散步','快走','步行'),
                'strength':('抗阻','力量','哑铃','深蹲','举铁'), 'mobility':('拉伸','活动度')}
    return next((k for k,terms in categories.items() if any(t in label for t in terms)),None)


def load_flags(state):
    plans={p['week']:p for p in [*state['history'],state['plan']] if p}
    if not state.get('profile') or not plans:
        return []
    day=today(state)
    # Before Monday's plan is installed, compare the 14 days ending Sunday.
    if monday(day).isoformat() not in plans:
        day-=timedelta(days=1)
    return load.alerts(state,day,plans,record_kind)


def session_options(state,session,flags=None):
    p=state['profile']
    if any(x not in workouts.KINDS for x in p['likes']) or any(
            (state.get(slot) or {}).get('policy')=='ai-reviewed-v1' and any(s['id']==session['id'] for s in state[slot]['sessions'])
            for slot in ('plan','upcoming')):
        return []
    if health_risk(p)['level'] in ('age','hold') or session['kind']=='rest':
        return []
    kind=session['kind']
    kinds = ([workouts.feasible(workouts.KINDS[x],p) for x in p['likes'] if workouts.KINDS[x] in workouts.AEROBIC]
             + ['indoor','mobility']) if kind in workouts.AEROBIC else ['mobility','indoor']
    if health_risk(p)['level']=='caution':
        kinds=['indoor']
    if (period:=period_view(state)) and period['mode']!='normal' and period['start']<=session['date']<=period['end']:
        return []
    flags={f['kind'] for f in (load_flags(state) if flags is None else flags)}
    kinds=[k for k in kinds if k not in flags and not ('aerobic' in flags and k in workouts.IMPACT)]
    return [k for k in dict.fromkeys(kinds) if k!=kind]


def next_direction(state, include_period=True):
    recent = [r for r in state['records'] if r['date'] >= (today(state)-timedelta(days=14)).isoformat()]
    active = [r for r in recent if r['status'] in ('completed', 'partial')]
    last = max((r['date'] for r in state['records']), default='')
    risk = health_risk(state['profile']) if state.get('profile') else {'level':'none'}
    if state.get('blocked') or risk['level'] == 'hold':
        return ('hold', risk.get('message') or '先确认年龄适用范围。')
    if include_period and (period := period_view(state)) and period['mode'] != 'normal':
        return ('ease', '当前使用临时身体状态调整；结束后接回原计划，再根据恢复反馈考虑进阶。')
    if risk['level'] == 'caution' or any(r.get('pain') for r in recent):
        return ('ease', '本周先保持轻量，不增加强度；下一步根据完成记录与身体感受再调整。')
    if last and (today(state)-date.fromisoformat(last)).days >= 14:
        return ('restart', '已经中断一段时间，下周从更短的安排重新适应，不补欠课。')
    if flags:=load_flags(state):
        return ('rebalance', flags[0]['label']+'连续两段超出个人计划。'+flags[0]['advice'])
    if sum(r['effort'] == 'hard' for r in active) >= 2:
        return ('ease', '最近至少两次反馈吃力，下周先缩短时长，不增加训练天数。')
    if len(active) >= 4 and all(r['effort'] == 'easy' and r['status'] == 'completed' for r in active[-4:]):
        return ('consider', '最近四次完整训练都反馈轻松，可以在你确认恢复良好后，小幅增加单次时长。')
    return ('maintain', '先保持当前安排，积累更多完成和恢复反馈，再决定是否进阶。')


def review(state, cadence, anchor=None, *, include_records=True, direction=None):
    now=today(state)
    d = anchor or now
    start = monday(d) if cadence=='week' else d.replace(day=1)
    end = start+timedelta(days=7) if cadence=='week' else growth.next_month(start)
    stats = progress(present(state), start, end)
    flag, explanation = direction or next_direction(state)
    report=growth.insights(state,cadence,start,end,now,stats,record_kind,flag,explanation)
    if not include_records:
        stats.pop('records')
    return {'id':f'{cadence}:{start}','cadence':cadence,'start':start.isoformat(),'end':end.isoformat(),
            'stats':stats,'direction':flag,'question':'下一次，你最想保留哪一种适合自己的节奏？',
            'created':datetime.now().isoformat(timespec='seconds'),**report}


def demo():
    state = empty()
    p = sample_profile()
    state['profile'] = p
    state['risk'] = health_risk(p)
    this_week = monday(today(state))
    for w in range(3, -1, -1):
        start = this_week - timedelta(weeks=w)
        plan = generate(p, start, reason='演示安排 · 从每周几次轻松活动开始')
        for i, s in enumerate(plan['sessions']):
            if s['kind'] != 'rest' and s['date'] < today(state).isoformat():
                state['records'].append({'id': uid(), 'session_id': s['id'], 'date': s['date'],
                    'status': 'completed', 'minutes': max(10, s['minutes'] - (3-w)),
                    'effort': 'okay' if w else 'easy', 'pain': False, 'note': '演示记录 · 运动后感觉不错',
                    'source': 'demo', 'created': datetime.now().isoformat(timespec='seconds')})
        if w:
            state['history'].append(plan)
        else:
            state['plan'] = plan
    state['chat'] = [{'role': 'assistant', 'text': '你好，欢迎来到 SportsWise。今天的安排已经准备好了。时间紧、想换一种练法，随时告诉我。'}]
    return state


def local_intent(text):
    """Explicitly limited local parser. Never imply arbitrary conversation is understood."""
    text = text.strip()
    out = {'intent': 'question', 'reply': '', 'minutes': None, 'target_date': None, 'kind': None, 'scope': 'session'}
    safety_text = re.sub(r'(?:没有|无)(?:任何)?(?:疼痛|不适|头晕|受伤)', '', text)
    if any(x in safety_text for x in ('疼', '胸闷', '头晕', '受伤', '不适', '生病')):
        out.update(intent='safety', reply='先停止本次训练。当前不适需要先确认，不要通过换动作或补课继续。若症状严重或持续，请及时寻求医疗帮助。')
    elif any(x in text for x in ('重新开始', '中断', '好久没练')):
        out.update(intent='restart')
    elif any(x in text for x in ('休息', '不练', '取消今天')):
        out.update(intent='rest')
    elif any(x in text for x in ('太累', '太难', '轻一点', '降低', '轻松一点')):
        out.update(intent='shorten', scope='week' if '这周' in text else 'session', minutes=15)
    elif any(x in text for x in ('分钟', '十分钟', '一刻钟')):
        match = re.search(r'(\d+)\s*分钟', text)
        amount = int(match.group(1)) if match else (15 if '一刻钟' in text else 10)
        out.update(intent='shorten', minutes=amount)
    elif re.search(r'\d{4}-\d{2}-\d{2}', text) or any(x in text for x in ('明天', '后天', '改期', '挪到', '周末', '周一', '周二', '周三', '周四', '周五', '周六', '周日')):
        match = re.search(r'\d{4}-\d{2}-\d{2}', text)
        out.update(intent='move', target_date=match.group(0) if match else None)
    elif any(x in text for x in ('室内', '出差', '换一种', '不跑', '不想跑', '没器械')):
        out.update(intent='replace', kind='indoor')
    else:
        out['reply'] = '我会结合你的目标和记录来安排。当前使用基础教练模式，可以帮你缩短训练、换成室内、改期、休息，或重新开始。你也可以在「我的」修改长期偏好。'
    return out


def propose(state, intent, text, session_id=None):
    base=state.get('plan')
    if intent['intent'] in ('swap_kind','swap_move') and any(
            s['id']==session_id for s in (state.get('upcoming') or {}).get('sessions',[])):
        base=state['upcoming']
    if not base:
        raise ValueError('先建立运动档案，生成你的第一周安排')
    if state.get('blocked') and intent['intent'] not in ('safety', 'question', 'rest'):
        raise ValueError('训练建议已暂停。请先在运动档案确认身体情况')
    if intent['intent']=='question':return None
    if base.get('policy')=='ai-reviewed-v1':
        raise ValueError('这份方案需要经过模型重新评审，请在计划页使用「AI生成并评审」，填写本次调整要求。')
    plan = copy.deepcopy(base)
    d = today(state)
    recorded = {r.get('session_id') for r in state['records']}
    if health_risk(state['profile'])['level'] == 'hold' and intent['intent'] not in ('safety','question','rest'):
        raise ValueError('恢复与确认安排已生成；当前不增加主动训练，先按医嘱或确认身体情况后再调整')
    candidates = [s for s in plan['sessions'] if s['kind'] != 'rest' and s['date'] >= d.isoformat() and s['id'] not in recorded]
    s = next((x for x in plan['sessions'] if x['id'] == session_id), None) if session_id else (candidates[0] if candidates else None)
    action = intent['intent']
    if action in ('question', 'safety'):
        return None
    if action == 'restart':
        plan = generate(state['profile'], monday(d), state['plan'], '重新开始：从较短安排找回节奏', duration=min(15, state['profile']['minutes']), easy_only=True)
        # Preserve completed and past sessions when rebuilding this week.
        old_by_date = {x['date']: x for x in state['plan']['sessions']}
        plan['sessions'] = [old_by_date[x['date']] if x['date'] < d.isoformat() or old_by_date[x['date']]['id'] in recorded else x for x in plan['sessions']]
        plan['baseline'] = state['plan']['baseline']
        summary = '保留已经发生的训练，将剩余安排缩短，从适应开始。'
    else:
        if not s or s['kind'] == 'rest':
            raise ValueError('没有可调整的待训练安排。可以先生成下一周计划')
        if s['date'] < d.isoformat() or s['id'] in recorded:
            raise ValueError('已经记录或过去的训练不能改写，请调整未来安排')
        targets = candidates if intent.get('scope') == 'week' and action == 'shorten' else [s]
        if action == 'shorten':
            n = int(intent.get('minutes') or 15)
            if n < 10:
                raise ValueError('当前简化训练最短为 10 分钟；时间更少时，可以选择休息或自行活动并记录')
            if n > s['minutes']:
                raise ValueError('这个操作用于缩短训练。增加时长请在周复盘后确认进阶')
            for target in targets:
                replacement = make_session(date.fromisoformat(target['date']), target['kind'], min(n, target['minutes']), state['profile'], target.get('variant',0), plan.get('easy_only',False),target.get('runner_support',False))
                target.update({k: v for k, v in replacement.items() if k not in ('id', 'original_minutes', 'original_kind')})
            summary = f"将{'本周剩余训练' if len(targets)>1 else '本次训练'}缩短到最多 {n} 分钟，保留热身和收尾，训练量如实记录。"
        elif action == 'rest':
            s.update(kind='rest', outcomes=[], runner_support=False, intensity='休息', title='今天休息，留点空间', minutes=0, steps=[], status='rest', purpose='主动调整为休息，不在后面补课。')
            summary = '本次改为休息，不把它堆到后面的训练日。'
        elif action == 'replace':
            replacement = make_session(date.fromisoformat(s['date']), 'indoor', s['minutes'], state['profile'], easy_only=True)
            s.update({k:v for k,v in replacement.items() if k not in ('id', 'original_minutes', 'original_kind')})
            summary = '仅将本次训练换为室内轻松活动，长期偏好保持原样。'
        elif action in ('swap_kind','swap_move'):
            options=session_options(state,s)
            if action=='swap_kind':
                kind=intent['kind']
                if kind not in options:
                    raise ValueError('当前课程不能换成这个项目，请选择可用选项')
                replacement=make_session(date.fromisoformat(s['date']),kind,min(s['minutes'],20) if kind=='mobility' else s['minutes'],
                                         state['profile'],easy_only=True)
                s.update({k:v for k,v in replacement.items() if k not in ('id','original_minutes','original_kind')})
                summary='将这堂课换成'+workouts.LABELS[kind]+'，从轻松强度开始。'
            else:
                if not options or s['kind']!='strength':
                    raise ValueError('当前课程不可替换动作')
                index=intent['step_index']
                if index>=len(s['steps']) or not s['steps'][index].get('alternatives'):
                    raise ValueError('该动作暂时没有可用替代')
                old=s['steps'][index]['title']
                s['steps'][index]=s['steps'][index]['alternatives'][0]
                s['customized']=True
                summary='将'+old+'替换为'+s['steps'][index]['title']+'，保留其他动作。'
        elif action == 'move':
            dest = intent.get('target_date')
            if dest:
                target_date = date.fromisoformat(dest)
            elif '后天' in text:
                target_date = d + timedelta(days=2)
            elif '明天' in text:
                target_date = d + timedelta(days=1)
            else:
                wanted = next((i for i, label in enumerate(DAYS) if label in text), 5 if '周末' in text else None)
                if wanted is None:
                    raise ValueError('请指定日期，例如“改到明天”或“改到 2026-11-05”')
                target_date = d + timedelta(days=(wanted-d.weekday()) % 7)
            if target_date < d or not date.fromisoformat(plan['week']) <= target_date <= date.fromisoformat(plan['week'])+timedelta(days=6):
                raise ValueError('请选择这份周计划内尚未过去的日期；跨周安排请在下一周计划中调整')
            dest_session = next((x for x in plan['sessions'] if x['date'] == target_date.isoformat() and x['id'] != s['id']), None)
            if dest_session and (dest_session['kind'] != 'rest' or dest_session['id'] in recorded):
                raise ValueError('那天已有训练或记录，请换一个日期')
            if target_date.isoformat() == s['date']:
                raise ValueError('训练已经安排在这一天')
            old = s['date']
            if dest_session:
                dest_session['date'] = old
            s['date'] = target_date.isoformat()
            summary = f'将训练从 {old} 移到 {s["date"]}，保留其他安排；不会在同一天叠加训练。'
        else:
            raise ValueError('当前不支持这项调整，请修改档案或选择快捷操作')
    plan['sessions'].sort(key=lambda x:x['date'])
    plan['version'] = base['version'] + 1
    plan['reason'] = summary
    plan['risk'] = health_risk(state['profile'])
    plan['policy'] = PLAN_POLICY
    plan['programming']=programming.analyse(plan,state['profile'])
    validate_plan(plan, state['profile'], recorded)
    plan['quality']=plan_quality.evaluate(plan,state['profile'],base)
    return {'plan': plan, 'summary': summary, 'request': text}


def activate_due(state, day=None):
    day = day or today(state)
    changed = settle_period_days(state,day)
    if state.get('period') and state['period']['end'] < day.isoformat():
        state.pop('period')
        changed = True
    if state.get('profile') and (state.get('risk') != health_risk(state['profile']) or (state.get('blocked') and not safety(state['profile']))):
        changed = reconcile_health(state) or changed
    if state.get('blocked') or not state.get('profile'):
        return changed
    prior=state.get('plan')
    needs_followup=prior and prior.get('policy')!=PLAN_POLICY and not state.get('upcoming') and (
        state['profile']['goal']=='muscle' and state['profile']['level']=='regular'
        and prior['week']==monday(day).isoformat() and any(
            x['week']==prior['week'] and x.get('policy') not in ('strength-first-v5',PLAN_POLICY)
            and not any(s['kind']=='strength' for s in x['sessions']) for x in [prior,*state['history']]))
    modern_profile=(state['profile']['goal'] not in GOALS or state['profile']['level']=='competitive'
                    or any(x not in workouts.ACTIVITIES for x in state['profile']['likes']))
    for slot in ('plan','upcoming'):
        plan = state.get(slot)
        if not modern_profile and plan and plan.get('policy') not in (PLAN_POLICY,'ai-reviewed-v1') and plan['week'] >= monday(day).isoformat():
            revised = upgrade_plan(state,plan,day)
            if slot == 'plan':
                archive(state)
            state[slot] = revised
            changed = True
    if needs_followup:
        p=state['profile']
        direction,_=next_direction(state,include_period=False)
        flags=load_flags(state)
        limit=15 if direction in ('ease','restart') else None
        start=monday(day)+timedelta(days=7)
        current=state['plan']
        next_plan=generate(p,start,current,'增肌计划修复：下周接续符合身体限制的力量安排',
                           duration=limit,easy_only=limit is not None,load_flags=flags)
        before=current['sessions']
        locked={s['id'] for s in before}
        preserve_recovery(next_plan,p,locked,before)
        if not any(f['kind']=='strength' for f in flags):
            restore_strength_priority(next_plan,p,start,locked,before)
        if any(s['kind']=='strength' for s in next_plan['sessions']):
            next_plan['baseline']=sum(s['minutes'] for s in next_plan['sessions'])
            state['upcoming']=next_plan
            changed=True
    upcoming = state.get('upcoming')
    if upcoming and upcoming['week'] <= day.isoformat():
        archive(state)
        state['plan'] = upcoming
        state['upcoming'] = None
        return True
    current = state.get('plan')
    modern_profile=(state['profile']['goal'] not in GOALS or state['profile']['level']=='competitive'
                    or any(x not in workouts.ACTIVITIES for x in state['profile']['likes']))
    if current and (current.get('policy')=='ai-reviewed-v1' or modern_profile):
        return changed
    if modern_profile: return changed
    if current and current['week'] < monday(day).isoformat():
        direction, explanation = next_direction(state, include_period=False)
        legacy = current.get('policy') != PLAN_POLICY
        duration = None if legacy else min(state['profile']['minutes'],max((s['minutes'] for s in current['sessions'] if s['kind']!='rest'),default=15))
        if direction in ('ease','restart'):
            duration = min(15,duration or 15)
        flags=load_flags(state)
        plan = generate(state['profile'],monday(day),current,'新的一周：'+explanation,duration=duration,easy_only=direction in ('ease','restart'),load_flags=flags)
        plan['sessions']=[make_session(date.fromisoformat(s['date']),'rest',0,state['profile']) if s['date']<day.isoformat() else s for s in plan['sessions']]
        previous = current['sessions'] if current['week']==(monday(day)-timedelta(days=7)).isoformat() else []
        locked={s['id'] for s in previous}
        preserve_recovery(plan,state['profile'],locked,previous)
        if not any(f['kind']=='strength' for f in flags):
            restore_strength_priority(plan,state['profile'],day,locked,previous)
        plan['baseline']=sum(s['minutes'] for s in plan['sessions'])
        archive(state)
        state['plan']=plan
        return True
    return changed
