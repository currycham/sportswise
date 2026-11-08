"""Goal-led resistance programmes; stable movement selection, explicit workload estimates."""
from .movements import DETAILS, prescribe

CATALOG = {
    '哑铃杯式深蹲': ('quadriceps','glutes'),
    '哑铃罗马尼亚硬拉': ('hamstrings','glutes'),
    '单臂哑铃划船': ('back',),
    '地板哑铃卧推': ('chest',),
    '哑铃臀桥': ('glutes',),
    '站姿哑铃推举': ('shoulders',),
    '哑铃侧平举': ('shoulders',),
    '哑铃弯举': ('biceps',),
    '俯卧撑': ('chest',),
    '徒手慢速深蹲': ('quadriceps','glutes'),
    '扶稳反向弓步': ('quadriceps','glutes'),
    '臀桥': ('glutes',),
    '弹力带俯身划船': ('back',),
    '弹力带胸前推': ('chest',),
    '弹力带髋折叠': ('hamstrings','glutes'),
    '坐姿弹力带划船': ('back',),
    '上斜俯卧撑': ('chest',),
    '单腿臀桥': ('glutes','hamstrings'),
    '徒手反向飞鸟': ('shoulders',),
    '死虫式': ('core',),
    '扶稳提踵': ('calves',),
}
LABELS={'quadriceps':'大腿前侧','glutes':'臀部','hamstrings':'大腿后侧','back':'背部',
        'chest':'胸部','shoulders':'肩部','biceps':'肱二头肌','core':'躯干','calves':'小腿'}

EXTRA = {
'哑铃臀桥':('训练臀部伸髋。','哑铃垫毛巾置于髋前并握稳，双脚踩地，抬髋时不拱腰。','臀桥'),
'站姿哑铃推举':('训练肩部推举力量。','用能稳定控制的重量，肋骨下收，哑铃从肩旁推起；肩部不适时停止。','上斜俯卧撑'),
'哑铃侧平举':('训练三角肌。','手肘微屈，手臂向侧方抬到舒服高度，避免耸肩甩动。',None),
'哑铃弯举':('训练上臂屈肘力量。','上臂贴身，控制回落，不用躯干借力。',None),
'俯卧撑':('训练胸与肱三头肌。','双手略宽于肩，保持身体直线，按可控幅度下降、推起。','上斜俯卧撑'),
'弹力带俯身划船':('训练背部拉的动作。','穿鞋踩稳完好的带子，屈髋保持躯干稳定，向髋侧拉肘。','俯身无负重划船'),
'弹力带胸前推':('训练胸部推的动作。','带子绕上背、避开颈部，双手向前推；检查弹力带无裂口，避免朝脸回弹。','墙面俯卧撑'),
'弹力带髋折叠':('训练臀部与大腿后侧。','踩稳轻阻力带，膝微屈，髋后移后站起，避免下背代偿。','徒手髋折叠'),
'单腿臀桥':('训练臀部与单侧控制。','仰卧，一脚踩地，一腿抬离地，缓慢抬髋，骨盆不旋转。','臀桥'),
'徒手反向飞鸟':('低负荷练习肩胛与肩后侧控制，不能替代充分负荷的背部训练。','屈髋保持背部自然，手臂小幅向两侧展开；不耸肩。',None),
'死虫式':('练习躯干抗伸展控制。','仰卧屈髋屈膝，对侧手脚缓慢伸出，腰背姿势保持稳定。',None),
}
DETAILS.update(EXTRA)
UNILATERAL={'单臂哑铃划船','扶稳反向弓步','单腿臀桥','死虫式'}

def eligible(p,easy_only):
    return (p['level'] in ('regular','advanced') and p['goal'] in ('muscle','strength','shape','bone')
            and not easy_only)

def build(minutes,p,variant):
    advanced=p['level']=='advanced'
    dumbbell='dumbbell' in p['equipment']
    band='band' in p['equipment']
    if dumbbell:
        blocks=[
            ['哑铃杯式深蹲','单臂哑铃划船','地板哑铃卧推','哑铃罗马尼亚硬拉','哑铃侧平举'],
            ['哑铃罗马尼亚硬拉','地板哑铃卧推','单臂哑铃划船','扶稳反向弓步','哑铃弯举'],
            ['扶稳反向弓步','站姿哑铃推举','单臂哑铃划船','哑铃臀桥','扶稳提踵'],
        ]
    elif band:
        blocks=[
            ['徒手慢速深蹲','坐姿弹力带划船','弹力带胸前推','弹力带髋折叠','死虫式'],
            ['弹力带髋折叠','上斜俯卧撑','坐姿弹力带划船','扶稳反向弓步','弹力带拉开'],
            ['扶稳反向弓步','弹力带胸前推','坐姿弹力带划船','臀桥','扶稳提踵'],
        ]
    else:
        blocks=[
            ['徒手慢速深蹲','俯卧撑','单腿臀桥','徒手反向飞鸟','死虫式'],
            ['扶稳反向弓步','俯卧撑','臀桥','徒手反向飞鸟','扶稳提踵'],
            ['徒手慢速深蹲','俯卧撑','单腿臀桥','死虫式','扶稳提踵'],
        ]
    # Keep the A/B baseline with two days; introduce C only if the programme has three dates.
    names=blocks[variant%3]
    warm=5 if minutes>=30 else 3 if minutes>=15 else 2
    cool=3 if minutes>=20 else 2
    remaining=minutes-warm-cool
    # With little time, cover one lower, one push and one pull first, never squeeze prescribed sets.
    target=5 if minutes>=60 else 4 if minutes>=30 else 3 if minutes>=20 else 2
    names=names[:target]
    entries=[]
    for i,name in enumerate(names):
        side=2 if name in UNILATERAL else 1
        reps=6 if p['goal']=='strength' and advanced else 8
        maximum=8 if reps==6 else 12
        rest=120 if advanced and i<3 else 90 if i<3 else 60
        per_set=maximum*3*side
        # Work duration + full recovery + setup; minute allocation is an estimate, never a countdown race.
        desired=3 if advanced and minutes>=45 else 2
        minimum=int((per_set+60+59)//60)
        later=len(names)-i-1
        reserve=later*3
        chosen=None
        for sets in range(desired,0,-1):
            seconds=sets*per_set+max(0,sets-1)*rest+60
            needed=(seconds+59)//60
            if needed<=remaining-reserve:
                chosen=(sets,needed);break
        if not chosen:
            if entries: break
            chosen=(1,minimum)
        sets,needed=chosen
        if needed>remaining: break
        item=prescribe(name,needed,DETAILS[name][1],sets,reps,rest,
                       '组末保留 2–3 次余力；最后一组也不要求力竭')
        item.update(rep_max=maximum,rir=2,each_side=side==2,
                    muscles=list(CATALOG.get(name,('shoulders',))),estimated_seconds=sets*per_set+max(0,sets-1)*rest+60)
        item['detail']+=f' 每组 {reps}–{maximum} 次。先用能留出余力的熟悉阻力，不猜测公斤数。'
        entries.append(item)
        remaining-=needed
    if not entries: return None
    steps=[{'title':'专项热身','minutes':warm,'kind':'warmup','detail':'先轻活动，再给第一个复合动作做 1–2 组很轻的热身；热身组不计入工作组。'}]
    steps+=entries
    steps.append({'title':'放松与记录','minutes':cool,'kind':'cooldown','detail':'放下器械，恢复呼吸；记下每个动作的重量、实际次数和余力，观察第二天恢复。'})
    total=sum(x['minutes'] for x in steps)
    if total<10:
        steps[-1]['minutes']+=10-total
    return {'title':f'全身抗阻 {chr(65+variant%3)} · '+('进阶校准' if advanced else '巩固训练'),
            'purpose':'围绕蹲/髋主导、推与拉配置可完成的工作组，用反馈校准阻力。',
            'intensity':'工作组保留 2–3 次余力','steps':steps,'variant':variant,
            'outcomes':['肌力与肌肉','骨骼负荷'],'runner_support':False,
            'program':'fullbody-abc' if advanced else 'fullbody-ab'}

def analyse(plan,p):
    totals={}
    for s in plan['sessions']:
        for x in s['steps']:
            for muscle in x.get('muscles',[]):
                totals[muscle]=totals.get(muscle,0)+x.get('sets',0)
    missing=[]
    if p['level']=='advanced' and p.get('training_months') is None: missing.append('抗阻训练年限')
    if p['level'] in ('regular','advanced') and not p.get('routine_detail'): missing.append('最近常练动作、工作重量/次数与恢复')
    if p['goal']=='muscle' and not {'dumbbell','band'}.intersection(p['equipment']):
        missing.append('背部可用阻力；徒手低负荷动作不能替代有足够负荷的拉力训练')
    return {'direct_sets':[{'muscle':LABELS[k],'sets':v} for k,v in totals.items()],
            'missing':missing,'scope':'各动作主肌群工作组，非生理效果测量；复合动作可能涉及多个主肌群。',
            'progression':'连续两次同动作所有工作组达到次数上限，且仍留至少 2 次余力、无异常不适并恢复良好，再选最小可用增重，次数回到下限。一次只改一个变量。',
            'deload':'连续两次明显吃力或恢复变差：先少一组或降低阻力，不补课；异常疼痛停止并确认原因。',
            'review':'可用时长是上限，不为填满时间补额外训练。本周是基线校准。下周优先保留动作便于比较，不因日期自动加重；充分恢复后再按记录调整。'}
