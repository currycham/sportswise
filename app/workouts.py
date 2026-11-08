"""Reusable workout blocks. Prescriptions fit the user's time and familiar activities."""

from itertools import combinations
from .movements import prescribe
from . import programming

ACTIVITIES = {'walking': '步行', 'strength': '力量', 'running': '跑步',
              'cycling': '骑行', 'mobility': '灵活性', 'badminton':'羽毛球', 'dance':'有氧舞蹈','sport':'专项运动'}
LABELS = {'rest':'休息','walk':'快走','indoor':'室内低冲击有氧','strength':'力量训练',
          'run':'跑步','bike':'骑行','mobility':'拉伸与灵活性','badminton':'羽毛球','dance':'有氧舞蹈','sport':'专项运动'}
TYPES = set(LABELS)
AEROBIC = {'walk','indoor','run','bike','badminton','dance'}
WEIGHT_BEARING = {'walk','run','badminton','dance'}
IMPACT = {'run','badminton'}
STRENGTH_GOALS = {'muscle','strength','shape'}
KINDS = {'walking':'walk','strength':'strength','running':'run','cycling':'bike',
         'mobility':'mobility','badminton':'badminton','dance':'dance'}


def feasible(kind,p):
    if p['place']!='home':
        return kind
    if kind=='badminton' or (kind=='run' and 'treadmill' not in p['equipment']) or (
            kind=='bike' and 'stationary_bike' not in p['equipment']):
        return 'indoor'
    return 'indoor' if kind=='walk' else kind
EASY = '轻松 · 能完整交谈'
MODERATE = '中等 · 能说话但不太能唱歌'
RESISTANCE = '中等 · 每组留约 2–3 次余力'


def step(title, minutes, detail, kind='move'):
    return {'title': title, 'minutes': minutes, 'detail': detail, 'kind': kind}


def strength_days(days, limit=2):
    """Reserve as many spaced dates as fit, preferring the earliest available pair."""
    for count in range(min(limit,len(days)),0,-1):
        for group in combinations(sorted(days),count):
            if all(min(abs(a-b),7-abs(a-b))>=2 for a,b in combinations(group,2)):
                return set(group)
    return set()


def schedule(p, week):
    """Choose a primary session and rotate secondary sessions around recovery days."""
    preferences = p['likes']
    rank = {
        'habit': ['walking','mobility','strength','cycling','running'],
        'energy': ['strength','cycling','walking','running','mobility'],
        'strength': ['strength','mobility','walking','cycling','running'],
        'endurance': ['running','cycling','walking','strength','mobility'],
        'muscle': ['strength','walking','mobility','cycling','dance','running','badminton'],
        'bone': ['strength','walking','dance','running','badminton','mobility','cycling'],
        'shape': ['strength','walking','dance','cycling','running','badminton','mobility'],
    }[p['goal']]
    rank = [*rank, *(a for a in ACTIVITIES if a not in rank)]
    chosen = [a for a in rank if a in preferences]
    primary = chosen[0]
    secondary = [a for a in chosen if a != primary]
    # Change which supporting activity appears first on a new week if there are several.
    offset = (week.toordinal() // 7) % max(1, len(secondary))
    secondary = secondary[offset:] + secondary[:offset]
    days = sorted(set(p['days']))
    sequence = ([primary] + secondary) if p['goal'] == 'habit' else (
        [primary, secondary[0], primary, *secondary[1:]] if secondary else [primary])
    if p.get('support_training',True):
        if p['goal'] in ('strength','muscle','shape','bone') and 'strength' not in sequence:
            sequence=[*sequence[:1],'strength',*sequence[1:]]
            if len(days)==1 or p['goal'] in ('muscle','shape'):
                sequence=['strength',*sequence[:1],*sequence[2:]]
        cardio_only=all(KINDS[a] in AEROBIC for a in sequence)
        if ('strength' not in sequence and ((len(days)>=3 and primary in ('running','badminton')) or
                                             (len(days)>=4 and cardio_only))):
            sequence=[primary,'strength',*secondary,primary]
        if p['goal']=='bone' and len(days)>=2 and not any(feasible(KINDS[a],p) in WEIGHT_BEARING | {'indoor'} for a in sequence[:len(days)]):
            sequence.insert(1,'walking')
        if p['goal'] in ('muscle','shape','strength') and len(days)>=3 and sequence.count('strength')==1:
            sequence.insert(2,'strength')
    priority = strength_days(days,3 if p['level']=='advanced' else 2) if p['goal'] in STRENGTH_GOALS else None
    other = [a for a in chosen if a!='strength'] or ['mobility']
    assigned_strength = []
    counts = {}
    output = {}
    for i, day in enumerate(days):
        activity = ('strength' if day in priority else other[i % len(other)]) if priority is not None else sequence[i % len(sequence)]
        # Repeating the same weekly pattern also needs a gap across Sunday/Monday.
        if activity == 'strength' and any(min(abs(day-x), 7-abs(day-x)) < 2 for x in assigned_strength):
            activity = next((a for a in secondary + [primary] if a != 'strength'), 'mobility')
        if activity == 'strength':
            assigned_strength.append(day)
        kind = feasible(KINDS[activity],p)
        n = counts.get(kind,0)
        counts[kind] = n+1
        output[day] = (kind,n)
    return output


def supported_upper_workout(minutes,p,variant,warm,cool):
    moves = ['坐姿轻阻力弯举','坐姿轻弹力带拉开'] if variant%2==0 else ['坐姿轻弹力带拉开','坐姿轻阻力弯举']
    if not {'dumbbell','band'}.intersection(p['equipment']):
        moves=['坐姿徒手弯举','坐姿肩胛后收']
    elif 'band' not in p['equipment']:
        moves=[m if m!='坐姿轻弹力带拉开' else '坐姿肩胛后收' for m in moves]
    from .movements import DETAILS
    main=minutes-warm-cool
    intensity='轻抗阻 · 组末至少留 4 次余力'
    steps=[step('坐姿热身',warm,'在有靠背的稳固椅子上坐稳，放松肩膀，轻轻屈伸手肘。','warmup')]
    for i,name in enumerate(moves):
        n=main//2+(i<main%2)
        steps.append(prescribe(name,n,DETAILS[name][1],1,8,75,intensity,alternatives=False))
    steps.append(step('坐姿收尾',cool,'放下器械，坐稳放松肩和手臂，不做牵扯不适部位的动作。','cooldown'))
    return {'title':'坐姿上肢轻抗阻','purpose':'避开受限部位，先保留可耐受的上肢训练。仅在已有医嘱允许且动作不诱发症状时进行；否则选择休息。','intensity':intensity,
            'steps':steps,'variant':variant,'outcomes':['保留上肢抗阻习惯'],'runner_support':False,'supported_upper':True}


def workout(kind, minutes, p, variant=0, easy_only=False, runner_support=False, supported_upper=False):
    regular = p['level'] in ('regular','advanced') and not easy_only
    moderate = regular and p['goal'] != 'habit' and minutes >= 15
    warm, cool = (2, 2) if minutes <= 15 else (4, 3)
    main = minutes - warm - cool
    routine=p.get('current','')+' '+p.get('routine_detail','')
    easy_running=(kind=='run' and p['goal']!='endurance' and any(
        word in routine.lower() for word in ('二区','zone 2','zone2','轻松跑','低强度慢跑')))
    if easy_running:
        moderate=False
    steps = [step('热身', warm, '轻松走动，活动肩、髋和脚踝。前几分钟逐渐进入状态。', 'warmup')]
    intensity = EASY
    if kind == 'strength':
        load = regular and ('dumbbell' in p['equipment'] or 'band' in p['equipment'])
        if supported_upper:
            return supported_upper_workout(minutes,p,variant,warm,cool)
        if not runner_support and programming.eligible(p,easy_only) and (p['level']=='advanced' or p['goal'] in ('muscle','bone')):
            built=programming.build(minutes,p,variant)
            if built:
                return built
        variant %= 2
        if 'dumbbell' in p['equipment'] and load:
            moves = [
                [('哑铃杯式深蹲', '双手把一只熟悉的哑铃抱在胸前，向后下方坐，膝盖和脚尖同向。'),
                 ('单臂哑铃划船', '一手扶稳桌面，另一手把哑铃拉向髋部，左右交替。'),
                 ('地板哑铃卧推', '仰卧屈膝，手肘慢慢落至上臂轻触地，再推起。')],
                [('哑铃罗马尼亚硬拉', '膝微屈，髋向后移，哑铃贴腿下放到能控制的位置。'),
                 ('上斜俯卧撑', '双手撑稳固台面，收紧躯干，下放再推起。'),
                 ('扶稳反向弓步', '一脚向后迈，前脚踩稳；左右交替，按可控幅度下蹲。')],
            ][variant]
        elif load:
            moves = [
                [('椅前深蹲', '双脚踩稳，臀部向后靠近椅面，再站直。'),
                 ('坐姿弹力带划船', '弹力带绕在穿鞋的双脚中部，保持背部挺直，把手肘拉向身后。'),
                 ('上斜俯卧撑', '双手撑在不会移动的台面上，身体保持直线。')],
                [('臀桥', '仰卧屈膝，脚踩稳，抬髋至肩、髋、膝接近一线。'),
                 ('弹力带拉开', '双手握带，抬至胸前，手肘微屈，缓慢向两侧拉开再回位。'),
                 ('扶稳分腿蹲', '前后站稳，轻扶固定支撑，垂直降低重心，左右交替。')],
            ][variant]
        elif regular:
            moves=[
                [('徒手慢速深蹲','脚踩稳，数三拍下蹲，再平稳站起。'),
                 ('上斜俯卧撑','用不会移动的台面，身体保持直线，缓慢屈伸手臂。'),
                 ('扶稳提踵','扶墙抬脚跟，停一拍再控制下放。')],
                [('扶稳反向弓步','扶住固定支撑，向后迈步并轻屈膝，左右交替。'),
                 ('臀桥','仰卧屈膝，呼气抬髋，停一拍再放下。'),
                 ('四点支撑伸展','手膝撑稳，伸手或伸腿，左右交替。')],
            ][variant]
        else:
            moves = [
                [('椅子坐站', '用靠墙的稳固椅子，缓慢站起再坐下。'),
                 ('墙面俯卧撑', '双手扶墙，身体保持直线，缓慢屈伸手臂。'),
                 ('扶稳提踵', '扶墙缓慢抬脚跟，再控制下放。')],
                [('臀桥', '仰卧屈膝，脚踩稳，缓慢抬起和放下髋部。'),
                 ('四点支撑伸展', '手膝撑稳，单独伸一只手或一条腿，左右交替。'),
                 ('扶稳浅分腿蹲', '前后站立并扶墙，按舒服的幅度微屈双膝，再站直。')],
            ][variant]
        if runner_support:
            first = ('哑铃杯式深蹲','哑铃抱在胸前，缓慢屈髋屈膝，踩稳后站起。') if load and 'dumbbell' in p['equipment'] else ('椅子坐站','用靠墙的椅子练习缓慢站起、坐下。')
            second = ('哑铃罗马尼亚硬拉','膝微屈、臀部向后，哑铃贴腿移动。') if load and 'dumbbell' in p['equipment'] else ('臀桥','仰卧屈膝，呼气抬髋，缓慢回落。')
            moves = [first,second,('扶稳提踵','扶墙抬起脚跟，停一拍再缓慢放下。')]
            if variant:
                moves[0]=('扶稳反向弓步' if regular else '扶稳浅分腿蹲','扶住固定支撑，按可控幅度下降、站起，左右交替。')
        if main < 12:
            moves = moves[:2]
        for i,(name,detail) in enumerate(moves):
            n=main//len(moves)+(i<main%len(moves))
            sets=3 if moderate and p['goal']=='muscle' and n>=10 else 2 if n>=5 and not easy_only else 1
            reps=10 if p['goal']=='muscle' and moderate else 8 if moderate else 6
            intensity=RESISTANCE if moderate else '轻松 · 组末至少留 4 次余力'
            steps.append(prescribe(name,n,detail,sets,reps,75 if moderate else 60,intensity,alternatives=not easy_only))
        title = ('跑步配套力量 · 膝髋与小腿' if not variant else '跑步配套力量 · 单腿稳定与髋') if runner_support else (
            ('全身力量 A · 蹲、推与拉' if load else '全身力量 A · 蹲、推与小腿') if not variant else '全身力量 B · 髋、躯干与单侧')
        purpose = ('训练大腿、臀部和小腿，支持跑步时的下肢控制与承载。'
                   if runner_support else '通过可控制的阻力和重复练习，积累力量并支持肌肉。')
        intensity = RESISTANCE if moderate else '轻松 · 动作稳定，保持余力'
    elif kind == 'mobility':
        title = '关节活动 · 髋、肩与踝' if variant % 2 == 0 else '恢复活动 · 胸椎、髋与小腿'
        purpose = '给训练之间留出恢复空间，保持活动幅度和控制。'
        blocks = [
            [('站姿髋部活动','扶稳后轻抬膝并缓慢放下，每侧做 5–8 次，循环时可休息。'),
             ('肩胛绕环','肩膀放松，缓慢向前和向后绕环，各做 5–8 次。'),
             ('扶墙踝关节活动','脚跟着地，膝盖缓缓向脚尖方向移动，每侧 5–8 次。')],
            [('坐姿胸椎转动','坐稳，手抱胸，小幅向左右轮流转动，骨盆保持稳定。'),
             ('站姿髋折叠','膝微屈，髋缓慢后移再站起，每次 5–8 个，留出休息。'),
             ('扶墙小腿拉伸','一脚在后，脚跟轻踩地；每侧 20 秒 × 2 轮，每轮间走动 20 秒。只到轻微牵拉，不弹震。')],
        ][variant % 2]
        for i, (name, detail) in enumerate(blocks):
            steps.append(step(name, main // 3 + (i < main % 3), detail+' 全程保持在舒服的范围。'))
    elif kind in ('badminton','dance'):
        is_ball=kind=='badminton'
        title='羽毛球 · 控制回合与移动' if is_ball else '低冲击有氧舞 · 步伐与节奏'
        purpose=('用你选的球类练心肺和移动协调；按回合休息，给小腿和膝髋留恢复。' if is_ball else
                 '用你喜欢的舞步积累心肺训练时间；从低冲击步伐开始，兼顾节奏和协调。')
        pace=MODERATE if moderate else EASY
        intensity=pace
        steps[0]['detail']='先快走，再用小步移动并做轻量挥拍。' if is_ball else '从原地踏步开始，再加侧步和轻松摆臂。'
        active,rest=(3,1) if moderate else (2,1)
        rounds,left=divmod(main,active+rest)
        steps.append({**step('对拉与走动恢复' if is_ball else '组合步与踏步恢复',main,
                             '和同伴轻量对拉，留出停顿；避免追远球、突然变向或跳杀。' if is_ball else
                             '左右并步、前后点步交替；保持至少一脚着地，避免急转。'),
                      'dose':f'{rounds} 轮 ×（{active} 分钟练习 + {rest} 分钟走动恢复）'+(f'，余下 {left} 分钟轻松走动' if left else ''),
                      'intensity':pace,'benefit':'积累有氧训练刺激，支持心肺耐力。'})
    else:
        mode = {'walk':'快走' if moderate and variant%3!=1 else '步行','indoor':'室内踏步','run':'跑步','bike':'骑行'}[kind]
        location = {'walk':'选平坦、熟悉的路线。','indoor':'清出空间，在室内走动或低冲击踏步。',
                    'run':'选平坦路线或使用熟悉的跑步机。','bike':'选熟悉的低车流路线或使用健身车。'}[kind]
        if kind in ('run','bike'):
            steps[0]['detail'] = '先走动，再用很轻松的速度跑走交替。' if kind=='run' else '以轻阻力慢踩，逐渐找到顺畅的踏频。'
        if kind == 'run' and not regular:
            title, purpose = '跑走交替 · 建立耐力', '先熟悉跑步节奏，用步行间隔控制负担。'
            steps.append(step('慢跑与步行交替', main, location+f' 做 {main//2} 轮，每轮慢跑 30 秒、步行 90 秒'+('，最后再步行 1 分钟。' if main%2 else '。')+' 跑时仍能说完整句子。'))
        elif moderate and variant % 3 == 0 and main >= 12:
            title, purpose = f'{mode}节奏练习 · 快慢交替', '用短节奏段练心肺，恢复段放慢，避免冲刺。'
            steps.append(step('节奏段与恢复段', main, location+f' 做 {main//4} 轮，每轮 2 分钟中等节奏、2 分钟轻松'+(f'，余下 {main%4} 分钟保持轻松。' if main%4 else '。')))
            intensity = MODERATE
        elif moderate and variant % 3 != 1:
            title, purpose = f'持续{mode} · 稳定有氧', '在可控制的强度下积累持续运动时间。'
            steps.append(step('持续有氧', main, location+' 匀速活动，保持能说话但不太能唱歌的节奏；觉得吃力就放慢。'))
            intensity = MODERATE
        else:
            title = f'{mode} · '+('轻松恢复' if variant % 3 == 1 else '舒适有氧')
            purpose = '延续你已有的舒适慢跑，给力量训练和恢复留有余力；未测阈值时不推断具体心率区间。' if easy_running else '保持舒适的节奏，积累活动时间，给下一次训练留有余力。'
            steps.append(step('舒适节奏', main, location+' 保持能完整交谈，累了就放慢或停下来。'))
    finish='减慢速度，轻松走动或慢踩，呼吸恢复后结束。'
    if kind in ('run','strength') and (kind=='run' or runner_support):
        finish='先走动 1 分钟；小腿和髋前侧轻拉各 20 秒 × 每侧 1 次。只拉到轻微牵拉感，余下时间自然走动。'
        if cool==2:
            finish='先慢走；可扶墙轻拉小腿，每侧 20 秒 × 1 次，余下时间慢走。'
    steps.append(step('放松收尾',cool,finish,'cooldown'))
    outcomes = (['肌力与肌肉','骨骼负荷'] if kind=='strength' else
                ['心肺与有氧代谢']+(['负重活动'] if kind in WEIGHT_BEARING else []) if kind in AEROBIC else ['活动度与恢复'])
    return {'title':title, 'purpose':purpose, 'intensity':intensity, 'steps':steps, 'variant':variant,'outcomes':outcomes,'runner_support':runner_support}
