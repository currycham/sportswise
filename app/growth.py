"""Record-driven garden and period insights. No rewards depend on intensity or volume."""
from collections import Counter
from datetime import date, timedelta
from .workouts import AEROBIC, LABELS

GROWTH_LABELS = {**LABELS,'walk':'步行 / 快走'}

PLOTS = {
    'walk': ('🌼','步行花'), 'run': ('🪨','跑步石径'), 'bike': ('🎐','骑行风铃'),
    'strength': ('🌳','力量树'), 'mobility': ('🌿','舒展蕨'), 'indoor': ('🪴','室内香草'),
    'badminton': ('🐦','球场小鸟'), 'dance': ('🦋','舞步蝴蝶'), 'other': ('🌱','探索芽'),
}


def session_index(state):
    return {s['id']:s for p in [*state['history'],state['plan']] if p for s in p['sessions']}


def credited(record):
    return record['status'] in ('completed','partial')


def garden(state, record_kind):
    sessions=session_index(state)
    counts=Counter()
    for r in state['records']:
        if credited(r):
            kind=record_kind(r,sessions)
            counts[kind if kind in PLOTS else 'other']+=1
    plots=[{'kind':k,'icon':icon,'name':name,'count':counts[k],
            'activity':GROWTH_LABELS.get(k,'其他运动')} for k,(icon,name) in PLOTS.items()]
    variety=len(counts)
    return {'plots':plots,'total':sum(counts.values()),'variety':variety,
            'stage':'百花园' if variety>=6 else '多彩花园' if variety>=3 else '初绿花园' if variety else '待播种的小花园',
            'milestone':'已点亮全部九种景物' if variety==9 else
                '下次想换个项目时，可以点亮新的景物。' if variety else '记录第一项运动，点亮你的第一处景物。'}


def next_month(start):
    return (start.replace(day=28)+timedelta(days=4)).replace(day=1)


def compare(state, cadence, start, cutoff, selected):
    prev_start=start-timedelta(days=7) if cadence=='week' else (start-timedelta(days=1)).replace(day=1)
    elapsed=(cutoff-start).days
    days=min(elapsed,(start-prev_start).days)
    current_until=(start+timedelta(days=days)).isoformat()
    prev_until=(prev_start+timedelta(days=days)).isoformat()
    current=[r for r in selected if r['date']<current_until]
    previous=[r for r in state['records'] if prev_start.isoformat()<=r['date']<prev_until and credited(r)]
    if not previous or not selected:
        return None
    before=sum(r['minutes'] for r in previous)
    after=sum(r['minutes'] for r in current)
    return {'days':days,'scope':'上周' if cadence=='week' else '上月',
            'actual_minutes':after,'previous_minutes':before,'delta':after-before,
            'active_days':len({r['date'] for r in current}),'previous_active_days':len({r['date'] for r in previous})}


def insights(state, cadence, start, end, today, stats, record_kind, direction, explanation):
    cutoff=min(today+timedelta(days=1),end)
    rows=[r for r in stats['records'] if r['date']<cutoff.isoformat()]
    active=[r for r in rows if credited(r)]
    sessions=session_index(state)
    types={}
    for r in active:
        kind=record_kind(r,sessions)
        kind=kind if kind in PLOTS else 'other'
        item=types.setdefault(kind,{'kind':kind,'label':GROWTH_LABELS.get(kind,'其他运动'),'minutes':0,'sessions':0})
        item['sessions']+=1
        item['minutes']+=r['minutes']
    breakdown=sorted(types.values(),key=lambda x:(-x['minutes'],-x['sessions'],x['kind']))
    days=len({r['date'] for r in active})
    partial=sum(r['status']=='partial' for r in active)
    easy=sum(r.get('effort')=='easy' for r in active)
    hard=sum(r.get('effort')=='hard' for r in active)
    heart=sum(r.get('avg_heart_rate') is not None for r in active)
    duration=sum(r['minutes'] for r in active)
    previous=compare(state,cadence,start,cutoff,active)
    praise=[]
    if days:
        praise.append(f'你在 {days} 天里为运动留出了时间。' if days>1 else
                      f'你给自己留出了运动时间，并记下了 {len(active)} 次活动。')
        if previous and previous['active_days']>previous['previous_active_days']:
            praise.append(f'和{previous["scope"]}同期相比，你多在 {previous["active_days"]-previous["previous_active_days"]} 天安排了实际活动。')
        if len(breakdown)>1:
            praise.append(f'你尝试了 {len(breakdown)} 类活动，正在找到适合自己的运动组合。')
        if partial:
            praise.append(f'你如实记录了 {partial} 次部分完成；把做过的一部分也留下，能帮你找到下次更合适的安排。')
        if easy and not hard:
            praise.append(f'有 {easy} 次活动感觉轻松，说明你记录下了哪些节奏容易坚持。')
        if cadence=='month' and len({date.fromisoformat(r['date']).isocalendar()[:2] for r in active})>=2:
            praise.append('运动分布在不止一周，已经开始形成可以延续的节奏。')
    rest=sum(r['status']=='rest' for r in rows)
    if rest and len(praise)<3:
        praise.append(f'你也主动记录了 {rest} 次休息，恢复同样是计划的一部分。')
    profile=state.get('profile') or {}
    focus=profile.get('goal')
    period_name=('这周' if end<=today else '本周') if cadence=='week' else ('这个月' if end<=today else '本月')
    timeframe='下一周' if cadence=='week' else '下个月'
    if direction in ('hold','ease','rebalance','restart'):
        advice=explanation
    elif not active:
        advice='下次运动后，先记下项目、实际时长和感受。哪怕只完成一小段，也能帮助找到合适的起点。'
    elif focus in ('muscle','strength','shape','bone') and 'strength' not in types:
        advice=f'{timeframe}先为一节符合身体情况的力量课留出固定时段。把有氧保留在其他日，先观察完成和恢复感受。'
    elif focus=='endurance' and not AEROBIC.intersection(types):
        advice=f'{timeframe}选一项你熟悉的有氧，安排在容易坚持的一天，记录时长与体感。'
    elif hard>=2:
        advice='下一次先降低强度或缩短时长，给自己留出恢复空间，再观察感受。'
    elif direction=='consider':
        advice='先确认恢复良好。若要进阶，只改一项：选择一堂熟悉的课略增时长，其他安排先保持。'
    else:
        advice=f'{timeframe}先把一次感觉合适的活动放到固定日期；如果忙，就预先准备一节更短的版本。'
    largest=f'分钟数最多的是{breakdown[0]["label"]}（{breakdown[0]["minutes"]} 分钟）。' if breakdown and duration else ''
    headline='这些努力值得留下' if active else '从一条记录开始'
    summary=(f'{period_name}记录了 {len(active)} 次运动，分布在 {days} 天，累计 {duration} 分钟。{largest}'
             if active else f'{period_name}还没有运动记录。完成、做了一部分，或主动休息，都可以如实记下来。')
    missing=stats['unknown']
    if missing:
        summary+=f' 还有 {missing} 次已过的计划课没有记录，实际情况未知。'
    return {'headline':headline,'summary':summary,'praise':praise[:3],'next':advice,
            'analysis':{'active_days':days,'minutes':duration,'sessions':len(active),'partial':partial,
                        'easy':easy,'hard':hard,'okay':sum(r.get('effort')=='okay' for r in active),
                        'heart_rate_count':heart,'breakdown':breakdown,'comparison':previous}}
