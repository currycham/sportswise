"""Model routing and measured, non-guaranteed waiting ranges."""
import math
from . import config,db,engine


def complex_profile(profile):
    return (profile.get('level') in ('advanced','competitive') or
            engine.health_risk(profile)['level'] in ('caution','hold') or
            profile.get('goal') not in ('habit','energy') or
            len(profile.get('days',[]))>4 or
            profile.get('planning_style')=='preserve_structure')


def route(profile,task,repairs=0):
    expert=repairs>0 or complex_profile(profile)
    model=config.PLANNER_EXPERT_MODEL if expert else (config.PLANNER_REVIEW_MODEL if task=='plan_review' else config.PLANNER_MODEL)
    effort='high' if repairs>=2 else (config.PLANNER_AUTHOR_EFFORT if task=='plan_generate' else config.PLANNER_EFFORT)
    return {'model':model,'effort':effort,'expert':expert}


def call_range(task,model,effort):
    expert=model==config.PLANNER_EXPERT_MODEL
    cold=(60,180) if expert or (task!='plan_review' and effort!='none') else (30,90)
    if task=='plan_revise' and effort=='low':cold=(15,120)
    if effort in ('high','max'):cold=(120,360)
    with db.connect() as c:
        rows=c.execute("SELECT duration_ms FROM llm_usage WHERE task=? AND model=? AND effort=? AND status='ok' AND duration_ms>0 AND COALESCE(actor,'') NOT LIKE 'sportswise-%eval-%' ORDER BY id DESC LIMIT 40",(task,model,effort)).fetchall()
    samples=sorted(r['duration_ms']/1000 for r in rows)
    if not samples:return (*cold,0)
    if len(samples)<3:
        return (max(10,round(min(cold[0],samples[0]*.65))),
                max(cold[1],math.ceil(samples[-1]*1.5)),len(samples))
    lo=samples[int((len(samples)-1)*.25)]*.8
    hi=samples[math.ceil((len(samples)-1)*.9)]*1.25
    return max(10,round(lo)),max(20,math.ceil(hi)),len(samples)


def estimate(profile,*,pending=0,repairs=0,first_task=None):
    tasks=(first_task or ('plan_generate' if repairs==0 else 'plan_revise'),'plan_review')
    values=[call_range(task,**{k:v for k,v in route(profile,task,repairs).items() if k!='expert'}) for task in tasks]
    low=sum(x[0] for x in values);high=sum(x[1] for x in values)
    batches=math.floor(pending/2)
    return {'min_seconds':low+batches*low,'max_seconds':high+batches*high,
            'sample_count':min(x[2] for x in values),'basis':'history' if min(x[2] for x in values)>=3 else 'preliminary',
            'queue_included':batches>0,'route':'expert_review' if complex_profile(profile) or repairs else 'balanced'}
