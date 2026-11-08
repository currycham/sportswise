"""Compare recorded activity against the user's plan, not population safety limits."""
from datetime import timedelta
from .workouts import AEROBIC, LABELS

ADVICE = {
    'run':'先取消一次额外跑或减少一次节奏段；用轻松骑行或快走替换一堂跑课。保留熟悉的膝髋、小腿力量与恢复日。',
    'badminton':'先取消一次额外打球，下一次缩短回合、增加走动休息。用低冲击有氧替换一堂球课。',
    'dance':'少排一次额外舞蹈，降低跳跃和转向，或换成低冲击步伐与拉伸。',
    'bike':'先少骑一次额外长骑，把下一次改为轻阻力短骑，保留恢复日与原有力量训练。',
    'walk':'先把一次额外长距离拆短或取消，选择平路和舒适节奏。',
    'strength':'先取消额外抗阻课；下一次少做一组或用较轻阻力，给同一肌群留至少一天恢复。',
    'indoor':'先减少一次额外有氧，把一堂课换成恢复活动。',
    'aerobic':'先减少额外有氧或用低强度恢复替换一堂有氧课，保留已排的力量训练和休息日。',
}
RECOVERY = {'run':'bike','badminton':'walk','dance':'mobility','bike':'mobility',
            'walk':'mobility','strength':'mobility','indoor':'mobility','aerobic':'mobility'}


def alerts(state, day, plans, record_kind):
    end=day+timedelta(days=1)
    windows=[(end-timedelta(days=14),end-timedelta(days=7)),(end-timedelta(days=7),end)]
    actual=[r for r in state['records'] if r['status'] in ('completed','partial') and r['minutes']>0]
    sessions={s['id']:s for p in plans.values() for s in p['sessions']}
    result=[]
    for kind, advice in ADVICE.items():
        matches=AEROBIC if kind=='aerobic' else {kind}
        totals=[]
        for first,last in windows:
            a,b=first.isoformat(),last.isoformat()
            scheduled=[s for p in plans.values() for s in p['sessions'] if a<=s['date']<b]
            # Without a plan covering this interval there is no personal baseline to compare against.
            if len({s['date'] for s in scheduled})<7:
                break
            planned=sum(s['minutes'] for s in scheduled if s['kind'] in matches)
            relevant=[r for r in actual if a<=r['date']<b and record_kind(r,sessions) in matches]
            minutes=sum(r['minutes'] for r in relevant)
            days=len({r['date'] for r in relevant})
            # Product trigger only: substantial overage in each of two windows, with repeated activity.
            if days<2 or minutes-planned<max(20,(planned+3)//4) or (not planned and (days<3 or minutes<60)):
                break
            totals.append({'actual':minutes,'planned':planned,'start':a,'end':(last-timedelta(days=1)).isoformat()})
        if len(totals)==2 and (kind!='aerobic' or not any(x['kind'] in AEROBIC for x in result)):
            result.append({'kind':kind,'label':LABELS.get(kind,'有氧合计'),'windows':totals,'advice':advice})
    return result
