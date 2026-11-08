"""Owner-scoped generation, model escalation and honest waiting estimates."""
import copy
import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
import re
from . import config,db,engine,services,planning_policy

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='sportswise-planning')

def signature(state):
    return hashlib.sha256(json.dumps({k:state.get(k) for k in ('profile','plan','upcoming','records','period')},sort_keys=True).encode()).hexdigest()


def baseline_for(state,week=None,request_detail='',explicit_session=False):
    """Only reuse an adopted, reviewed and still-compatible framework; never its score."""
    try:target=date.fromisoformat(week) if week else engine.monday(engine.today(state))+timedelta(days=7)
    except (ValueError,TypeError):return None
    profile=state.get('profile') or {};upcoming=state.get('upcoming') or {}
    old=upcoming if upcoming.get('source')=='ai_reviewed' and upcoming.get('week')==target.isoformat() else (state.get('plan') or {})
    if ((profile.get('planning_style')!='preserve_structure' and not explicit_session) or old.get('source')!='ai_reviewed' or
        old.get('policy')!='ai-reviewed-v1' or old.get('goal')!=profile.get('goal') or
        old.get('quality',{}).get('status')!='reviewed' or engine.health_risk(profile)['level']!='none' or
        re.search(r'从头|全新|重新制定|换.{0,3}框架|不保留',request_detail)):
        return None
    reviews=[x for x in old.get('review_trace',[]) if x.get('stage')=='independent_review']
    if not reviews or not reviews[-1].get('passed'):return None
    try:
        if date.fromisoformat(old['week'])>target:return None
        active=[s for s in old['sessions'] if s['kind']!='rest']
        if any(date.fromisoformat(s['date']).weekday() not in profile['days'] or s['minutes']>profile['minutes'] for s in active):return None
        from . import ai_planning
        draft=ai_planning._draft_data(old);draft['week']=target.isoformat()
        for session in draft['sessions']:
            session['date']=(target+timedelta(days=date.fromisoformat(session['date']).weekday())).isoformat()
        return draft
    except (ValueError,KeyError,TypeError):return None


def estimate_for(uid):
    with db.connect() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row:raise ValueError('账号不存在')
        state=db.decode(row);profile=state.get('profile')
        if not profile:raise ValueError('请先建立运动档案')
        pending=c.execute("SELECT count(*) FROM planning_jobs WHERE status IN ('queued','running')").fetchone()[0]
    return planning_policy.estimate(profile,pending=pending,first_task='plan_revise' if baseline_for(state) else None)


def public_job(row):
    payload=json.loads(row['result'] or '{}')
    timing=payload.get('timing',{})
    terminal=row['status'] not in ('queued','running')
    elapsed=max(0,round((row['updated_at'] if terminal else time.time())-row['created_at']))
    estimate=copy.deepcopy(timing.get('estimate'))
    return {k:row[k] for k in ('id','status','stage','message')}|{
        k:v for k,v in payload.items() if k in ('proposal_id','model','review_model','review_trace')
    }|{'elapsed_seconds':elapsed,'estimate':estimate,
       'over_estimate':bool(estimate and not terminal and elapsed>estimate['max_seconds']),
       'estimate_extension':timing.get('extension',''),
       'error':row['message'] if row['status']=='failed' else None}


def start(uid,revision,request_detail="",session_id=None,proposal_id=None):
    with db.transaction() as c:
        row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if row['revision']!=revision:raise ValueError('档案已更新，请刷新后重试')
        state=db.decode(row)
        if not state.get('profile') or engine.safety(state['profile']):raise ValueError('请先确认成人运动档案')
        if not config.API_KEY:raise ValueError('当前未连接生成模型，原计划保留')
        target_plan=None;target_session=None;seed=None
        if proposal_id:
            proposal=c.execute('SELECT * FROM proposals WHERE id=? AND user_id=?',(proposal_id,uid)).fetchone()
            if not proposal:raise ValueError('草案不存在')
            payload=json.loads(proposal['payload'])
            if proposal['revision']!=revision and payload.get('source_signature')!=signature(state):raise ValueError('训练基线已变化，请重新生成草案')
            target_plan=payload['plan']
        elif session_id:
            from .coaching import find_session
            target_plan,target_session=find_session(state,session_id)
            if target_plan and target_plan not in (state.get('plan'),state.get('upcoming')):raise ValueError('历史版本只作回顾，请选择当前安排')
        if session_id:
            target_session=next((s for s in (target_plan or {}).get('sessions',[]) if s['id']==session_id),None)
            if not target_session:raise ValueError('当前账号中找不到这堂课')
            if target_session['date']<engine.today(state).isoformat() or any(r.get('session_id')==session_id for r in state['records']):
                raise ValueError('过去或已记录的训练保持不变，请选择未来课程')
        if target_plan and target_plan.get('policy')=='ai-reviewed-v1':
            target_week=target_plan['week']
            if date.fromisoformat(target_week)+timedelta(days=6)<engine.today(state):raise ValueError('过去的周保持不变，请生成未来安排')
            from .ai_planning import _draft_data
            seed=_draft_data(target_plan)
        else:target_week=None
        existing=c.execute("SELECT id FROM planning_jobs WHERE user_id=? AND status IN ('queued','running')",(uid,)).fetchone()
        if existing:return existing['id']
        pending=c.execute("SELECT count(*) FROM planning_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if pending>=4:raise ValueError('生成任务较多，请稍后重试')
        # Estimate is captured once for this request; subsequent polls don't reset its clock.
        estimate=planning_policy.estimate(state['profile'],pending=pending,first_task='plan_revise' if seed or baseline_for(state,request_detail=request_detail) else None)
        c.execute("DELETE FROM planning_jobs WHERE user_id=? AND status IN ('done','failed') AND updated_at<?",(uid,time.time()-30*86400))
        jid=engine.uid();now=time.time()
        payload={'timing':{'estimate':estimate}}
        c.execute('INSERT INTO planning_jobs VALUES (?,?,?,?,?,?,?,?)',(jid,uid,'queued','queued','等待生成模型处理',json.dumps(payload),now,now))
    snapshot=copy.deepcopy(state);snapshot['planning_request']=request_detail
    if seed:
        snapshot['seed_draft']=seed;snapshot['planning_baseline']=copy.deepcopy(target_plan)
        snapshot['target_week']=target_week
        snapshot['seed_feedback']={'user_request':request_detail,'instruction':'根据已讨论的原因和要求定点修订当前草案，未涉及的训练尽量保留；历史/已记录课程不能改变，旧评分不沿用。'}
    POOL.submit(run,jid,uid,snapshot)
    return jid


def run(jid,uid,state):
    from . import ai_planning
    artifacts=[];calls=[];repairs=0
    with db.connect() as c:
        job=c.execute('SELECT * FROM planning_jobs WHERE id=? AND user_id=?',(jid,uid)).fetchone()
    if not job:return
    started=job['created_at']
    timing=json.loads(job['result'] or '{}').get('timing') or {'estimate':planning_policy.estimate(state['profile'])}
    def stored(extra=None):
        return json.dumps({'timing':timing,'calls':calls,'artifacts':artifacts,**(extra or {})},ensure_ascii=False)
    def progress(event):
        # A repair genuinely adds work. Extend once for that round and explain why.
        repair_round=event.get('round',0)
        if event['stage']=='revising' and repair_round>timing.get('repair_round',0):
            remaining=planning_policy.estimate(state['profile'],repairs=max(repair_round,repairs+1))
            elapsed=max(0,time.time()-started)
            timing['estimate']['max_seconds']=max(timing['estimate']['max_seconds'],math.ceil(elapsed+remaining['max_seconds']))
            timing['repair_round']=repair_round
            timing['extension']='评审发现需要修正的内容，已延长预估并升级复核。'
        with db.connect() as c:
            c.execute("UPDATE planning_jobs SET status='running',stage=?,message=?,result=?,updated_at=? WHERE id=? AND user_id=?",
                      (event['stage'],event.get('message',''),stored(),time.time(),jid,uid))
    try:
        progress({'stage':'analyse','message':'读取运动基线、目标与适用知识'})
        state['planning_today']=engine.today(state).isoformat()
        state['planning_week']=state.get('target_week') or (engine.monday(engine.today(state))+timedelta(days=7)).isoformat()
        if not state.get('seed_draft'):
            baseline=baseline_for(state,state['planning_week'],state.get('planning_request',''))
            if baseline:
                state['seed_draft']=baseline
                state['seed_feedback']={'instruction':'这是一份用户已采用的训练结构。按完整档案、近期实际记录与本次要求定点校准；不按日期自动加量，不为改变而换动作。若无需改变剂量，仅更新本周理由及待确认项。旧评分不沿用，整周会重新评审。','user_request':state.get('planning_request','')}
        def model_call(messages,task):
            nonlocal repairs
            if task=='plan_revise':repairs+=1
            selected=planning_policy.route(state['profile'],task,repairs)
            output=services.planning_model_json(messages,uid,task,model=selected['model'],effort=selected['effort'],metrics=calls.append)
            artifacts.append({'task':task,'model':selected['model'],'effort':selected['effort'],'output':output})
            with db.connect() as c:
                c.execute('UPDATE planning_jobs SET result=?,updated_at=? WHERE id=? AND user_id=?',
                          (stored(),time.time(),jid,uid))
            return output
        state['compact_revisions']=True
        state['explanation_policy']=True
        result=ai_planning.pipeline(state['profile'],state,model_call,progress)
        trace=result.get('review_trace',[])
        reviews=iter(x for x in calls if x['task']=='plan_review' and x['status']=='ok')
        for item in trace:
            if item['stage']=='independent_review':
                metric=next(reviews,None)
                if metric:item.update(model=metric['model'],effort=metric['effort'])
        if not result.get('ok'):
            with db.connect() as c:c.execute('UPDATE planning_jobs SET result=? WHERE id=? AND user_id=?',(stored({'review_trace':trace}),jid,uid))
            raise ValueError(result.get('error') or '模型评审未通过，未替换原计划')
        with db.transaction() as c:
            row=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not row:return
            if signature(db.decode(row))!=signature(state):raise ValueError('生成期间档案或训练记录发生变化，请重新生成')
            pid=engine.uid();plan=result['plan']
            author=next((x for x in reversed(calls) if x['task']!='plan_review'),None)
            reviewer=next((x for x in reversed(calls) if x['task']=='plan_review'),None)
            plan['generator'].update(model=author['model'] if author else plan['generator'].get('model',config.PLANNER_MODEL),
                                     thinking=author['effort'] if author else 'unknown',
                                     review_model=reviewer['model'] if reviewer else '',routing='balanced-v1',
                                     calls=[{k:v for k,v in x.items() if k!='prompt_tokens'} for x in calls])
            plan['review_trace']=trace
            c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',
                      (pid,uid,row['revision'],json.dumps({'plan':plan,'review_trace':trace,
                       'summary':plan.get('rationale') or plan.get('reason','模型生成并独立评审后的新方案，采用前请核对。'),'request':state.get('planning_request') or 'AI生成与评审','source_signature':signature(state)},ensure_ascii=False)))
            saved={'proposal_id':pid,'model':plan['generator']['model'],'review_model':plan['generator']['review_model']}
            c.execute("UPDATE planning_jobs SET status='done',stage='done',message='生成与评审完成，请核对后采用',result=?,updated_at=? WHERE id=? AND user_id=?",
                      (stored(saved),time.time(),jid,uid))
    except Exception as e:
        message=str(e) if isinstance(e,ValueError) else '模型服务未完成请求，原计划保留，请稍后重试'
        with db.connect() as c:
            c.execute("UPDATE planning_jobs SET status='failed',stage='failed',message=?,updated_at=? WHERE id=? AND user_id=?",
                      (message[:600],time.time(),jid,uid))
