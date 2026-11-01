"""Constrained starter templates; all durations, history and changes are deterministic."""
import copy
import re
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SOURCES = [
    {'title': 'NIDDK · 从少量活动开始', 'url': 'https://www.niddk.nih.gov/health-information/weight-management/tips-get-active/tips-starting-physical-activity'},
    {'title': 'NHS · 基础力量动作说明', 'url': 'https://www.nhs.uk/live-well/exercise/strength-exercises/'},
    {'title': 'CDC · 成年人的身体活动', 'url': 'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html'},
]
GOALS = {'habit': '建立运动规律', 'energy': '改善日常体能', 'strength': '打好力量基础', 'endurance': '提升基础耐力'}
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


def step(title, minutes, detail, kind='move'):
    return {'title': title, 'minutes': minutes, 'detail': detail, 'kind': kind}


def make_session(d, kind, minutes, p):
    risk = health_risk(p)
    if risk['level'] == 'hold':
        return {'id': uid(), 'date': d.isoformat(), 'kind': 'rest', 'title': '恢复与确认 · 暂停主动训练',
                'minutes': 0, 'original_minutes': 0, 'original_kind': 'rest', 'purpose': risk['message'],
                'steps': [], 'status': 'rest', 'intensity': '以医嘱和当前身体情况为准'}
    if risk['level'] == 'caution' and kind != 'rest':
        minutes = min(int(minutes),15)
        if kind == 'strength' and any(x in p.get('limitations','') for x in ('膝','关节','腰','疼','受伤','手术','避免力量','不做力量','禁止力量')):
            kind = 'indoor'
    if kind == 'rest':
        return {'id': uid(), 'date': d.isoformat(), 'kind': kind, 'title': '留一点空间，给恢复',
                'minutes': 0, 'original_minutes': 0, 'original_kind': kind,
                'purpose': '休息也是安排的一部分，今天不需要补课。', 'steps': [], 'status': 'rest', 'intensity': '自由安排'}
    minutes = max(10, min(int(minutes), 45))
    warm, cool = (2, 2) if minutes <= 15 else (3, 3)
    main = minutes - warm - cool
    strength = kind == 'strength'
    title = '基础力量 · 稳稳开始' if strength else '轻松步行 · 找到节奏'
    if kind == 'indoor':
        title = '室内活动 · 小空间也可以'
    pieces = [step('慢慢进入状态', warm, '轻松走动、活动肩臂。保持自然呼吸，先找舒服的节奏。', 'warmup')]
    if strength:
        # Timeboxes include rest, setup, and optional pauses; no fabricated precision in weights.
        a = main // 3
        pieces += [step('椅子坐站', a, '用稳定、靠墙的椅子。双脚踩稳，缓慢起立再坐下；先尝试 5 次，充分休息后再决定是否继续。'),
                   step('墙面俯卧撑', a, '双手扶墙，身体保持自然直线，缓慢屈伸手臂。先尝试 5 次；轻松呼吸，不憋气。'),
                   step('扶稳提踵', main - 2*a, '扶稳椅背或墙，缓慢抬起脚跟再放下。先尝试 5 次；本段时间包含休息，不必一直做。')]
    else:
        detail = '选择平整熟悉的路线，保持可以完整说话的轻松节奏。累了就放慢或停下，不追求距离。'
        if kind == 'indoor':
            detail = '在无障碍物的空间轻松走动或原地踏步，保持可以完整说话的节奏，随时休息。'
        pieces.append(step('轻松走一段', main, detail))
    pieces.append(step('慢下来，结束训练', cool, '逐渐放慢，轻松走动，呼吸恢复后结束。', 'cooldown'))
    if risk['level'] == 'caution':
        for item in pieces:
            item['detail'] = item['detail']+'有不适立即停止。'
    return {'id': uid(), 'date': d.isoformat(), 'kind': kind, 'title': title, 'minutes': minutes,
            'original_minutes': minutes, 'original_kind': kind, 'purpose': '建立动作熟悉度，为日常活动打基础。' if strength else '积累轻松活动，找到可以持续的运动节奏。',
            'intensity': '轻松 · 可以完整说话', 'steps': pieces, 'status': 'planned'}


def health_risk(p):
    """Product routing, not a medical assessment. Health notes never suppress plan output."""
    text = (p or {}).get('limitations', '').strip().strip('。.!！')
    if not (p or {}).get('adult', False):
        return {'level': 'age', 'message': '当前训练模板面向成年人，请先确认年龄适用范围。'}
    if not text or text in ('无','没有','暂无','无特殊限制','没有不适','无伤病'):
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


def generate(p, start=None, previous=None, reason='根据你的时间与目标制定试行安排', duration=None):
    start = start or monday(date.today())
    days = sorted(set(p['days']))
    sessions = []
    strength_days = []
    for index in range(7):
        kind = 'rest'
        if index in days:
            wants_strength = 'strength' in p['likes']
            wants_walk = 'walking' in p['likes']
            # Whole-body strength sessions always have an intervening day, including week boundaries.
            distances_ok = all(min(abs(index-x), 7-abs(index-x)) >= 2 for x in strength_days)
            active_index = len([s for s in sessions if s['kind'] != 'rest'])
            # Respect interests first; within those choices the main goal changes the emphasis.
            prefer_strength = (not wants_walk or p['goal']=='strength' or
                               (p['goal']=='endurance' and active_index % 3 == 2) or
                               (p['goal'] not in ('strength','endurance') and active_index % 2 == 0))
            if wants_strength and distances_ok and prefer_strength:
                kind = 'strength'
                strength_days.append(index)
            else:
                kind = 'walk' if wants_walk and p['place'] != 'home' else 'indoor'
        starter_cap = {'beginner': 20, 'returning': 25, 'regular': 30}[p['level']]
        sessions.append(make_session(start + timedelta(days=index), kind, duration or min(p['minutes'], starter_cap), p))
    plan = {'id': uid(), 'version': (previous or {}).get('version', 0) + 1,
            'week': start.isoformat(), 'created': datetime.now().isoformat(timespec='seconds'),
            'reason': reason, 'goal': p['goal'], 'goal_label': GOALS[p['goal']],
            'rationale': f"围绕{GOALS[p['goal']]}，结合你选择的运动方式、每周 {len(days)} 个可用日和单次最多 {p['minutes']} 分钟安排；先适应，再根据反馈调整。",
            'phase': '适应与校准', 'sessions': sessions,
            'baseline': sum(s['minutes'] for s in sessions), 'source': 'template', 'risk': health_risk(p)}
    validate_plan(plan, p)
    return plan


def validate_plan(plan, p, locked_ids=()):
    risk = health_risk(p)
    seen = set()
    for s in plan['sessions']:
        d = date.fromisoformat(s['date'])
        if s['date'] in seen:
            raise ValueError('同一天已有安排，请选择其他日期')
        seen.add(s['date'])
        if s['kind'] not in ('rest', 'walk', 'indoor', 'strength'):
            raise ValueError('训练类型不在已支持的内容中')
        if s['kind'] != 'rest':
            pending = s['id'] not in locked_ids and s['date'] >= today().isoformat()
            if pending and risk['level'] in ('hold','age'):
                raise ValueError('当前安排应以恢复与确认情况为主，不增加主动训练')
            if pending and risk['level'] == 'caution' and s['minutes'] > 15:
                raise ValueError('当前身体情况先采用较轻量安排，单次不超过 15 分钟')
            if not 10 <= s['minutes'] <= 45 or sum(x['minutes'] for x in s['steps']) != s['minutes']:
                raise ValueError('训练时长与动作安排不一致')
            if s['minutes'] > p['minutes'] and s['id'] not in locked_ids and s['date'] >= today().isoformat():
                raise ValueError('安排超过了你的单次可用时间')
    strength_dates = sorted(date.fromisoformat(s['date']) for s in plan['sessions'] if s['kind'] == 'strength')
    if any((b-a).days < 2 for a, b in zip(strength_dates, strength_dates[1:])):
        raise ValueError('基础力量训练之间至少留出一天恢复，请改到其他日期')


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


def next_direction(state):
    recent = [r for r in state['records'] if r['date'] >= (today(state)-timedelta(days=14)).isoformat()]
    active = [r for r in recent if r['status'] in ('completed', 'partial')]
    last = max((r['date'] for r in state['records']), default='')
    risk = health_risk(state['profile']) if state.get('profile') else {'level':'none'}
    if state.get('blocked') or risk['level'] == 'hold':
        return ('hold', risk.get('message') or '先确认年龄适用范围。')
    if risk['level'] == 'caution' or any(r.get('pain') for r in recent):
        return ('ease', '本周先保持轻量，不增加强度；下一步根据完成记录与身体感受再调整。')
    if last and (today(state)-date.fromisoformat(last)).days >= 14:
        return ('restart', '已经中断一段时间，下周从更短的安排重新适应，不补欠课。')
    if sum(r['effort'] == 'hard' for r in active) >= 2:
        return ('ease', '最近至少两次反馈吃力，下周先缩短时长，不增加训练天数。')
    if len(active) >= 4 and all(r['effort'] == 'easy' and r['status'] == 'completed' for r in active[-4:]):
        return ('consider', '最近四次完整训练都反馈轻松，可以在你确认恢复良好后，小幅增加单次时长。')
    return ('maintain', '先保持当前安排，积累更多完成和恢复反馈，再决定是否进阶。')


def review(state, cadence, anchor=None):
    d = anchor or today(state)
    if cadence == 'week':
        start = monday(d)
        end = start + timedelta(days=7)
    else:
        start = d.replace(day=1)
        end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    stats = progress(state, start, end)
    direction, explanation = next_direction(state)
    missing = f"还有 {stats['unknown']} 次过去的安排没有记录，情况暂时未知。" if stats['unknown'] else '已有记录会帮助下一次安排更贴近你。'
    result = {'id': f'{cadence}:{start}', 'cadence': cadence, 'start': start.isoformat(),
              'end': end.isoformat(), 'headline': '找到适合自己的节奏，就是进步', 'stats': stats,
              'summary': f"这段时间记录了 {stats['completed']} 次活动，共 {stats['minutes']} 分钟。{missing}",
              'direction': direction, 'next': explanation,
              'question': '这一段最影响你运动的，是时间、强度，还是兴趣？下一周只试着改变一件事。',
              'created': datetime.now().isoformat(timespec='seconds')}
    return result


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
    if not state['plan']:
        raise ValueError('先建立运动档案，生成你的第一周安排')
    if state.get('blocked') and intent['intent'] not in ('safety', 'question', 'rest'):
        raise ValueError('训练建议已暂停。请先在运动档案确认身体情况')
    plan = copy.deepcopy(state['plan'])
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
        plan = generate(state['profile'], monday(d), state['plan'], '重新开始：从较短安排找回节奏', duration=min(15, state['profile']['minutes']))
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
                replacement = make_session(date.fromisoformat(target['date']), target['kind'], min(n, target['minutes']), state['profile'])
                target.update({k: v for k, v in replacement.items() if k not in ('id', 'original_minutes', 'original_kind')})
            summary = f"将{'本周剩余训练' if len(targets)>1 else '本次训练'}缩短到最多 {n} 分钟，保留热身和收尾，训练量如实记录。"
        elif action == 'rest':
            s.update(kind='rest', title='今天休息，留点空间', minutes=0, steps=[], status='rest', purpose='主动调整为休息，不在后面补课。')
            summary = '本次改为休息，不把它堆到后面的训练日。'
        elif action == 'replace':
            replacement = make_session(date.fromisoformat(s['date']), 'indoor', s['minutes'], state['profile'])
            s.update({k:v for k,v in replacement.items() if k not in ('id', 'original_minutes', 'original_kind')})
            summary = '仅将本次训练换为室内轻松活动，长期偏好保持原样。'
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
    plan['version'] = state['plan']['version'] + 1
    plan['reason'] = summary
    plan['risk'] = health_risk(state['profile'])
    validate_plan(plan, state['profile'], recorded)
    return {'plan': plan, 'summary': summary, 'request': text}


def activate_due(state, day=None):
    if state.get('profile') and (state.get('risk') != health_risk(state['profile']) or (state.get('blocked') and not safety(state['profile']))):
        return reconcile_health(state)
    upcoming = state.get('upcoming')
    day = day or today(state)
    if upcoming and upcoming['week'] <= day.isoformat():
        archive(state)
        state['plan'] = upcoming
        state['upcoming'] = None
        return True
    current = state.get('plan')
    if current and current['week'] < monday(day).isoformat() and not state.get('blocked'):
        direction, explanation = next_direction(state)
        duration = min(state['profile']['minutes'], max((s['minutes'] for s in current['sessions'] if s['kind']!='rest'), default=15))
        if direction in ('ease','restart'):
            duration = min(15,duration)
        plan = generate(state['profile'],monday(day),current,'新的一周先延续可接受的安排。'+explanation,duration=duration)
        # When returning midweek, never backfill missed appointments before today.
        plan['sessions']=[make_session(date.fromisoformat(s['date']),'rest',0,state['profile']) if s['date']<day.isoformat() else s for s in plan['sessions']]
        plan['baseline']=sum(s['minutes'] for s in plan['sessions'])
        archive(state)
        state['plan']=plan
        return True
    return False
