import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from . import config, db, engine, growth, plan_quality, planning_jobs, programming, services, workouts, coaching

COOKIE = 'sw_session'


@asynccontextmanager
async def lifespan(app):
    db.init()
    with db.connect() as c:
        c.execute("UPDATE planning_jobs SET status='failed',message='服务已重启，原计划保留，请重新生成' WHERE status IN ('running','queued')")
    stop = threading.Event()
    thread = threading.Thread(target=services.worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=2)


app = FastAPI(title='SportsWise', lifespan=lifespan, docs_url='/api/docs' if config.ENV!='production' else None, redoc_url=None)


@app.middleware('http')
async def protections(request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        allowed = {f'{request.url.scheme}://{request.url.netloc}', config.SITE_URL}
        if (origin and origin not in allowed) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'请求来源不匹配，请从本站重新打开'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def actor(request):
    token = request.cookies.get(COOKIE, '')
    with db.connect() as c:
        row = c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>?',
                        (hashlib.sha256(token.encode()).hexdigest(), datetime.now(timezone.utc).isoformat())).fetchone()
    if not row:
        raise HTTPException(401, '请先登录，或开启独立的演示体验')
    return dict(row)


def issue(c, uid, response):
    token = secrets.token_urlsafe(32)
    c.execute('INSERT INTO sessions VALUES (?,?,?)', (hashlib.sha256(token.encode()).hexdigest(),uid,(datetime.now(timezone.utc)+timedelta(days=30)).isoformat()))
    response.set_cookie(COOKIE,token,httponly=True,samesite='lax',secure=config.ENV=='production',max_age=30*86400)


def state_result(row):
    state = db.decode(row)
    d = engine.today(state)
    displayed = engine.present(state)
    for slot in ('plan','upcoming'):
        if displayed.get(slot) and state.get('profile') and displayed[slot].get('policy')!='ai-reviewed-v1':
            displayed[slot]['programming']=programming.analyse(displayed[slot],state['profile'])
            displayed[slot]['quality']=plan_quality.evaluate(displayed[slot],state['profile'])
    flags=engine.load_flags(state)
    direction=engine.next_direction(state)
    growth_view={'garden':growth.garden(state,engine.record_kind),
                 **{c:engine.review(state,c,include_records=False,direction=direction) for c in ('week','month')}}
    recorded={r.get('session_id') for r in state['records']}
    options={s['id']:engine.session_options(state,s,flags)
             for plan in (displayed['plan'],displayed['upcoming']) if plan for s in plan['sessions']
             if s['date']>=d.isoformat() and s['id'] not in recorded}
    with db.connect() as c:
        notices = [dict(x) for x in c.execute('SELECT * FROM notices WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(row['id'],))]
        deliveries = [dict(x) for x in c.execute('SELECT status,COUNT(*) AS count FROM deliveries WHERE user_id=? GROUP BY status',(row['id'],))]
        latest_job=c.execute("SELECT * FROM planning_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 1",(row['id'],)).fetchone()
        planning_job=planning_jobs.public_job(latest_job) if latest_job and latest_job['status']!='adopted' else None

    return {'user':{'id':row['id'],'email':row['email'] if not row['demo'] else '', 'demo':bool(row['demo'])},
            'revision':row['revision'], 'state':displayed, 'today':d.isoformat(), 'stats':engine.progress(displayed),
            'growth':growth_view,'planning_job':planning_job,'session_options':options,'load_flags':flags,'direction':direction, 'notices':notices, 'deliveries':deliveries,
            'capabilities': {'ai':bool(config.API_KEY), 'mail':bool(config.SMTP_HOST), 'development':config.ENV!='production'},
            'sources':engine.SOURCES}


def change(request, revision, fn, *, cancel_deliveries=True):
    user = actor(request)
    with db.transaction() as c:
        row = c.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
        if row['revision'] != revision:
            raise HTTPException(409, '另一个页面已更新了数据，已为你刷新，请重试')
        state = db.decode(row)
        try:
            result = fn(state, c, row)
        except (ValueError, TypeError) as e:
            raise HTTPException(422, str(e)) from e
        db.save(c,user['id'],state,revision)
        if cancel_deliveries:c.execute("UPDATE deliveries SET status='cancelled' WHERE user_id=? AND status='pending'",(user['id'],))
    return {'ok':True, 'result':result, **state_result(db.read_user(user['id']))}


class Revision(BaseModel):
    revision: int = Field(ge=0)


class Profile(BaseModel):
    name: str = Field(default='运动者', max_length=30)
    sex: Literal['undisclosed','female','male'] = 'undisclosed'
    goal: Literal['habit','energy','strength','endurance','muscle','bone','shape','performance','race','sport','custom'] = 'habit'
    motivation: str = Field(default='', max_length=1000)
    current: str = Field(default='', max_length=1000)
    level: Literal['beginner','returning','regular','advanced','competitive'] = 'beginner'
    days: list[int] = Field(min_length=1,max_length=7)
    minutes: int = Field(ge=10,le=240)
    training_months: int|None = Field(default=None,ge=0,le=720)
    routine_detail: str = Field(default='',max_length=1500)
    usual_minutes: int|None = Field(default=None,ge=10,le=240)
    equipment: list[Literal['bodyweight','dumbbell','band','treadmill','stationary_bike','barbell','rack','bench','cable','machine','pullup','kettlebell','rower','ski_erg','sled','medicine_ball','box','suspension','other']] = ['bodyweight']
    place: Literal['home','outdoor','mixed','gym'] = 'mixed'
    likes: list[Literal['walking','strength','running','cycling','mobility','badminton','dance','swimming','hiking','rowing','hiit','yoga','pilates','other']] = Field(min_length=1,max_length=20)
    planning_style: Literal['fresh_start','preserve_structure','adaptive'] = 'adaptive'
    training_structure: str = Field(default='',max_length=2000)
    goal_detail: str = Field(default='',max_length=2000)
    training_background: str = Field(default='',max_length=2000)
    activity_detail: str = Field(default='',max_length=1000)
    equipment_detail: str = Field(default='',max_length=1000)
    support_training: bool = True
    limitations: str = Field(default='',max_length=1000)
    adult: bool
    consent: bool

    @field_validator('days')
    @classmethod
    def valid_days(cls, v):
        if len(set(v)) != len(v) or any(x<0 or x>6 for x in v):
            raise ValueError('训练日必须是不同的星期')
        return sorted(v)


class ProfileRequest(Revision):
    profile: Profile
    ai_first: bool = False


@app.get('/api/state')
def get_state(request:Request):
    row=actor(request)
    with db.transaction() as c:
        current=c.execute('SELECT * FROM users WHERE id=?',(row['id'],)).fetchone()
        current_state=db.decode(current)
        if engine.activate_due(current_state):
            db.save(c,row['id'],current_state,current['revision'])
        c.execute('UPDATE users SET last_seen_at=? WHERE id=?',(datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),row['id']))
    return state_result(db.read_user(row['id']))


@app.get('/api/config')
def public_config():
    return {'ai':bool(config.API_KEY), 'mail':bool(config.SMTP_HOST), 'development':config.ENV!='production'}


class DemoRequest(BaseModel):
    mode: Literal['example','empty'] = 'example'


@app.post('/api/demo')
def demo(request:Request,response:Response,body:DemoRequest|None=None):
    # One isolated demo per browser session. Never allow this to overwrite a signed-in account.
    if request.cookies.get(COOKIE):
        try:
            row = actor(request)
            if not body or body.mode!='empty' or not row['demo']:
                return state_result(row)
        except HTTPException:
            pass
    with db.transaction() as c:
        ip='demo:'+request.client.host
        now=time.time()
        limit=c.execute('SELECT * FROM auth_limits WHERE ip=?',(ip,)).fetchone()
        if limit and now-limit['at']<3600 and limit['count']>=30:
            raise HTTPException(429,'演示空间创建较多，请继续使用已有空间，或稍后再试')
        if not limit or now-limit['at']>=3600:
            c.execute('INSERT OR REPLACE INTO auth_limits VALUES (?,?,1)',(ip,now))
        else:
            c.execute('UPDATE auth_limits SET count=count+1 WHERE ip=?',(ip,))
        uid = engine.uid()
        mode = body.mode if body else 'example'
        demo_state = engine.empty() if mode=='empty' else engine.demo()
        demo_state['demo_mode'] = mode
        c.execute('INSERT INTO users(id,email,demo,state,last_seen_at) VALUES (?,?,1,?,?)',
                  (uid,f'demo-{uid}@example.invalid',json.dumps(demo_state,ensure_ascii=False),datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
        issue(c,uid,response)
    return state_result(db.read_user(uid))


class LoginCode(BaseModel):
    email: str = Field(max_length=254)
    invite: str = Field(default='',max_length=100)

    @field_validator('email')
    @classmethod
    def valid_email(cls,v):
        v=v.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v):
            raise ValueError('请输入有效邮箱')
        return v


class Verify(LoginCode):
    code: str = Field(min_length=6,max_length=6)
    import_trial: bool = False


@app.post('/api/auth/code')
def login_code(body:LoginCode,request:Request):
    dev_local = config.ENV!='production' and request.client.host in ('127.0.0.1','::1','testclient')
    if not config.SMTP_HOST and not dev_local:
        raise HTTPException(503,'邮件服务尚未配置，请先使用演示体验')
    now=time.time()
    code=f'{secrets.randbelow(1000000):06d}'
    salt=secrets.token_hex(16)
    hashed=salt+':'+hashlib.sha256((salt+code).encode()).hexdigest()
    with db.transaction() as c:
        ip=request.client.host
        limit=c.execute('SELECT * FROM auth_limits WHERE ip=?',(ip,)).fetchone()
        if limit and now-limit['at']<3600 and limit['count']>=15:
            raise HTTPException(429,'请求较多，请稍后再试')
        if not limit or now-limit['at']>=3600:
            c.execute('INSERT OR REPLACE INTO auth_limits VALUES (?,?,1)',(ip,now))
        else:
            c.execute('UPDATE auth_limits SET count=count+1 WHERE ip=?',(ip,))
        existing=c.execute('SELECT id FROM users WHERE email=?',(body.email,)).fetchone()
        if not existing and config.INVITE_CODE and not hmac.compare_digest(body.invite,config.INVITE_CODE) and body.email not in config.ADMIN_EMAILS:
            raise HTTPException(403,'内测期间需要邀请码')
        last=c.execute('SELECT sent_at FROM login_codes WHERE email=?',(body.email,)).fetchone()
        if last and now-last['sent_at']<60:
            raise HTTPException(429,'验证码刚刚发过，请一分钟后重试')
        c.execute('INSERT OR REPLACE INTO login_codes VALUES (?,?,?,?,0)',(body.email,hashed,now+600,now))
    if config.SMTP_HOST:
        try:
            services.send_mail(body.email,'SportsWise 登录验证码',f'验证码 {code}，10 分钟内有效。不是你操作请忽略。')
        except Exception:
            with db.connect() as c:
                c.execute('DELETE FROM login_codes WHERE email=? AND hash=?',(body.email,hashed))
            raise HTTPException(503,'验证码暂未发送成功，请稍后重试')
    return {'ok':True,'dev_code':code if dev_local and not config.SMTP_HOST else None}


@app.post('/api/auth/verify')
def verify(body:Verify,request:Request,response:Response):
    error=None
    with db.transaction() as c:
        row=c.execute('SELECT * FROM login_codes WHERE email=?',(body.email,)).fetchone()
        if not row or row['expires_at']<time.time() or row['tries']>=5:
            error='验证码已过期或尝试次数过多，请重新获取'
        else:
            salt,hashed=row['hash'].split(':')
            if not hmac.compare_digest(hashlib.sha256((salt+body.code).encode()).hexdigest(),hashed):
                c.execute('UPDATE login_codes SET tries=tries+1 WHERE email=?',(body.email,))
                error='验证码不正确'
        if not error:
            c.execute('DELETE FROM login_codes WHERE email=?',(body.email,))
            user=c.execute('SELECT id FROM users WHERE email=?',(body.email,)).fetchone()
            uid=user['id'] if user else engine.uid()
            old=request.cookies.get(COOKIE,'')
            if not user:
                initial=engine.empty()
                # Only explicitly requested, from-zero trial data can enter a first registration.
                # Example records and existing formal accounts are never merged or overwritten.
                if body.import_trial:
                    trial=c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires_at>? AND u.demo=1',
                        (hashlib.sha256(old.encode()).hexdigest(),datetime.now(timezone.utc).isoformat())).fetchone()
                    if trial:
                        candidate=db.decode(trial)
                        if candidate.get('demo_mode')=='empty' and (candidate.get('profile') or {}).get('consent'):
                            initial=copy.deepcopy(candidate)
                            initial.pop('demo_mode',None)
                c.execute('INSERT INTO users(id,email,role,state) VALUES (?,?,?,?)',(uid,body.email,'admin' if body.email in config.ADMIN_EMAILS else 'user',json.dumps(initial)))
            # Revoke this browser's old session after verification, retaining the trial data itself.
            c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(old.encode()).hexdigest(),))
            issue(c,uid,response)
    if error:
        raise HTTPException(400,error)
    return state_result(db.read_user(uid))


@app.post('/api/auth/logout')
def logout(request:Request,response:Response):
    with db.connect() as c:
        c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),))
    response.delete_cookie(COOKIE)
    return {'ok':True}


class IntakeRequest(BaseModel):
    text: str = Field(min_length=3,max_length=1500)


@app.post('/api/intake')
def intake(body:IntakeRequest,request:Request):
    user=actor(request)
    patch,mode=services.intake(body.text,user['id'])
    # Validate any model field against the same schema used for confirmed profiles.
    candidate=engine.sample_profile()
    candidate.update(patch)
    try:
        validated=Profile.model_validate(candidate).model_dump()
        patch={k:validated[k] for k in patch if k in validated}
    except ValueError:
        patch={'current':body.text[:1000]}
        mode='rules_fallback'
    return {'patch':patch,'mode':mode,'reply':'我把明确提到的信息整理好了。请继续核对目标、身体情况和可用时间，确认后才建立正式计划。'}


@app.put('/api/profile')
def update_profile(body:ProfileRequest,request:Request):
    if not body.profile.consent:
        raise HTTPException(422,'需要同意保存必要训练数据，才能建立计划')
    def update(state,c,row):
        p=body.profile.model_dump()
        if p.get('sex')=='male':state.pop('period',None)
        if body.ai_first or p['goal'] not in engine.GOALS or p['level']=='competitive' or any(x not in workouts.ACTIVITIES for x in p['likes']):
            state['profile']=p
            state['risk']=engine.health_risk(p)
            state['blocked']=engine.safety(p)
            return '档案已保存；原有计划保留，接下来由生成与评审模型制定新方案。'
        return legacy_profile_update(state,p)
    return change(request,body.revision,update)


def legacy_profile_update(state,p):
    old=state['plan']
    state['profile']=p;state['risk']=engine.health_risk(p);state['blocked']=engine.safety(p)
    if state['blocked']: return state['risk']['message']
    d=engine.today(state)
    plan=engine.generate(p,engine.monday(d),old,'根据更新的目标与时间制定基础安排')
    recorded={r.get('session_id') for r in state['records']}
    by={s['date']:s for s in (old or {}).get('sessions',[])}
    plan['sessions']=[by[s['date']] if s['date'] in by and (s['date']<d.isoformat() or by[s['date']]['id'] in recorded)
                      else engine.make_session(date.fromisoformat(s['date']),'rest',0,p) if s['date']<d.isoformat() else s for s in plan['sessions']]
    plan['baseline']=old['baseline'] if old and old['week']==plan['week'] else sum(s['minutes'] for s in plan['sessions'])
    engine.preserve_recovery(plan,p,recorded|{s['id'] for s in plan['sessions'] if s['date']<d.isoformat()})
    engine.restore_strength_priority(plan,p,d,recorded|{s['id'] for s in plan['sessions'] if s['date']<d.isoformat()})
    engine.archive(state);state['plan']=plan;state['upcoming']=None
    if state['risk']['level'] not in ('age','hold') and not any(s['kind']!='rest' and s['date']>=d.isoformat() for s in plan['sessions']):
        state['upcoming']=engine.generate(p,engine.monday(d)+timedelta(days=7),plan)
    return '运动档案和基础安排已更新。'+state['risk']['message']


class PlanningRequest(Revision):
    request_detail: str = Field(default='',max_length=2000)
    session_id: str|None = Field(default=None,max_length=100)
    proposal_id: str|None = Field(default=None,max_length=100)


@app.post('/api/planning')
def start_planning(body:PlanningRequest,request:Request):
    user=actor(request)
    try: jid=planning_jobs.start(user['id'],body.revision,body.request_detail,body.session_id,body.proposal_id)
    except ValueError as e: raise HTTPException(422,str(e))
    with db.connect() as c:
        job=c.execute('SELECT * FROM planning_jobs WHERE id=? AND user_id=?',(jid,user['id'])).fetchone()
    return {'job_id':jid,**planning_jobs.public_job(job)}


@app.get('/api/planning/estimate')
def planning_estimate(request:Request):
    user=actor(request)
    try:return planning_jobs.estimate_for(user['id'])
    except ValueError as e:raise HTTPException(422,str(e))


@app.get('/api/planning/{job_id}')
def planning_status(job_id:str,request:Request):
    user=actor(request)
    with db.connect() as c:
        row=c.execute('SELECT * FROM planning_jobs WHERE id=? AND user_id=?',(job_id,user['id'])).fetchone()
    if not row: raise HTTPException(404,'生成任务不存在')
    return planning_jobs.public_job(row)


class PeriodRequest(Revision):
    mode: Literal['normal','ease','rest']
    days: int = Field(ge=1,le=10)


@app.put('/api/period')
def set_period(body:PeriodRequest,request:Request):
    def update(state,c,row):
        if not state['profile'] or state.get('blocked'):
            raise ValueError('请先建立适用的运动档案')
        if state['profile'].get('sex')=='male':raise ValueError('此档案未启用经期功能')
        day=engine.today(state)
        state['period']={'start':day.isoformat(),'end':(day+timedelta(days=body.days-1)).isoformat(),'mode':body.mode}
        if body.mode=='rest':
            c.execute("UPDATE notices SET read=1 WHERE user_id=? AND kind IN ('daily','followup') AND period LIKE ?",
                      (row['id'],day.isoformat()+':%'))
        return '已保存：'+engine.PERIOD_MODES[body.mode]+'。到期后恢复原安排。'
    return change(request,body.revision,update)


@app.delete('/api/period')
def end_period(body:Revision,request:Request):
    def update(state,c,row):
        state.pop('period',None)
        return '已结束经期调整，未完成的课程恢复原安排。'
    return change(request,body.revision,update)


class CoachRequest(Revision):
    text: str = Field(min_length=1,max_length=1500)
    session_id: str|None = Field(default=None,max_length=100)
    proposal_id: str|None = Field(default=None,max_length=100)


@app.post('/api/coach')
def coach(body:CoachRequest,request:Request):
    user=actor(request)
    if user['revision']!=body.revision:
        raise HTTPException(409,'数据已更新，请刷新后重试')
    state=db.decode(user)
    local=engine.local_intent(body.text)
    modern=any((state.get(k) or {}).get('policy')=='ai-reviewed-v1' for k in ('plan','upcoming')) or (state.get('profile') or {}).get('goal') in ('performance','race','sport','custom')
    dialogue=local['intent']!='safety' and (modern or body.proposal_id is not None or local['intent']=='question' or bool(re.search('为什么|原因|原理|逻辑|怎么理解',body.text)))
    if dialogue:
        discussion_state=copy.deepcopy(state);discussion_payload=None;discussion_revision=None
        if body.proposal_id:
            with db.connect() as c:p=c.execute('SELECT * FROM proposals WHERE id=? AND user_id=?',(body.proposal_id,user['id'])).fetchone()
            if not p:raise HTTPException(404,'草案不存在')
            discussion_payload=json.loads(p['payload']);discussion_revision=p['revision']
            discussion_state['upcoming']=discussion_payload['plan']
        if body.session_id and coaching.find_session(discussion_state,body.session_id)[1] is None:
            raise HTTPException(404,'当前账号中找不到这堂课')
        answer=coaching.discuss(body.text,discussion_state,user['id'],body.session_id)
        selected_plan,selected_session=coaching.find_session(discussion_state,body.session_id)
        target_is_ai=selected_plan and selected_plan.get('policy')=='ai-reviewed-v1'
        past=selected_session and (selected_session['date']<engine.today(state).isoformat() or any(r.get('session_id')==selected_session['id'] for r in state['records']))
        if answer['can_plan'] and selected_session and (not target_is_ai or past):
            answer['reply']+='\n已有历史和记录保留；这次讨论会用于未来一周的新草案。'
            answer['plan_request']=('保留已经发生的训练，本次要求用于下一完整周。'+answer['plan_request'])[:1500]
        def save_dialogue(current,c,row):
            if discussion_payload and discussion_payload['plan'].get('policy')=='ai-reviewed-v1' and discussion_revision==row['revision'] and not discussion_payload.get('source_signature'):
                discussion_payload['source_signature']=planning_jobs.signature(current)
                c.execute('UPDATE proposals SET payload=? WHERE id=? AND user_id=?',(json.dumps(discussion_payload,ensure_ascii=False),body.proposal_id,row['id']))
            current['chat'].extend([{'role':'user','text':body.text},{'role':'assistant','text':answer['reply']}]);current['chat']=current['chat'][-60:]
            if answer['can_plan']:
                current['coach_plan_request']=answer['plan_request']
                current['coach_plan_session_id']=body.session_id if target_is_ai and not past else None
                current['coach_plan_proposal_id']=body.proposal_id if (not body.session_id or target_is_ai) and not past else None
            else:
                for key in ('coach_plan_request','coach_plan_session_id','coach_plan_proposal_id'):current.pop(key,None)
            return {'proposal_id':None,**answer}
        return change(request,body.revision,save_dialogue,cancel_deliveries=False)
    intent,mode=services.interpret(body.text,state,user['id'])
    proposal_id=None
    reply=intent.get('reply') or ''
    def update(state,c,row):
        nonlocal proposal_id,reply
        if intent['intent']=='safety':
            if state['profile']:
                old_note=state['profile'].get('limitations','')
                state['profile']['limitations']=(old_note+'；'+body.text).strip('；')[-1000:]
                engine.reconcile_health(state)
                reply=state['risk']['message']
            else:
                reply='先停止当前不适时的运动；建立档案后仍可生成包含注意事项的安排。'
        else:
            try:
                draft=engine.propose(state,intent,body.text,body.session_id)
                if draft:
                    proposal_id=engine.uid()
                    reply=draft['summary']+'\n先看看变更，采用后再更新你的正式安排。'
                    # change() increments revision; bind proposal to that resulting state.
                    c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',(proposal_id,row['id'],row['revision']+1,json.dumps(draft,ensure_ascii=False)))
            except (ValueError,TypeError) as e:
                reply=str(e)
        state['chat'].extend([{'role':'user','text':body.text},{'role':'assistant','text':reply}])
        state['chat']=state['chat'][-60:]
        return {'reply':reply,'proposal_id':proposal_id,'mode':mode}
    return change(request,body.revision,update,cancel_deliveries=intent['intent']=='safety')


class SwapRequest(Revision):
    session_id: str
    kind: Literal['walk','indoor','run','bike','mobility','badminton','dance']|None = None
    step_index: int|None = Field(default=None,ge=0,le=20)


@app.post('/api/plan/swap')
def swap(body:SwapRequest,request:Request):
    if (body.kind is None)==(body.step_index is None):
        raise HTTPException(422,'请选择一个项目或动作')
    def update(state,c,row):
        intent={'intent':'swap_kind' if body.kind else 'swap_move','kind':body.kind,'step_index':body.step_index}
        draft=engine.propose(state,intent,'替换课程或动作',body.session_id)
        proposal_id=engine.uid()
        c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',
                  (proposal_id,row['id'],row['revision']+1,json.dumps(draft,ensure_ascii=False)))
        return {'proposal_id':proposal_id}
    return change(request,body.revision,update)


@app.get('/api/proposals/{proposal_id}')
def proposal(proposal_id:str,request:Request):
    user=actor(request)
    with db.connect() as c:
        row=c.execute('SELECT * FROM proposals WHERE id=? AND user_id=?',(proposal_id,user['id'])).fetchone()
    if not row:
        raise HTTPException(404,'调整草案不存在')
    payload=json.loads(row['payload'])
    payload['plan']=engine.effective_plan(db.decode(user),payload['plan'])
    payload.pop('source_signature',None)
    return {'revision':row['revision'],**payload}


@app.post('/api/proposals/{proposal_id}/apply')
def apply_proposal(proposal_id:str,body:Revision,request:Request):
    def update(state,c,row):
        p=c.execute("SELECT * FROM proposals WHERE id=? AND user_id=? AND created_at>datetime('now','-1 day')",(proposal_id,row['id'])).fetchone()
        if not p:raise ValueError('草案已过期或数据已变化，请重新提出调整')
        payload=json.loads(p['payload'])
        if p['revision']!=row['revision'] and not (payload['plan'].get('policy')=='ai-reviewed-v1' and payload.get('source_signature')==planning_jobs.signature(state)):
            raise ValueError('训练基线已变化，请重新生成草案')
        ai=payload['plan'].get('policy')=='ai-reviewed-v1'
        if not ai and payload['plan'].get('policy')!=engine.PLAN_POLICY:
            raise ValueError('排课规则已更新，请重新预览调整')
        if state.get('blocked'):
            raise ValueError('训练建议已暂停，请先确认身体情况')
        existing_plan=state['plan']
        if existing_plan and payload['plan']['week']==existing_plan['week']:
            today=engine.today(state).isoformat()
            recorded={r.get('session_id') for r in state['records']}
            past={s['date']:s for s in existing_plan['sessions'] if s['date']<today or s['id'] in recorded}
            sessions=[past.get(s['date'],s) for s in payload['plan']['sessions']]
            if len({s['id'] for s in sessions}) != len(sessions):
                raise ValueError('草案涉及已经过去的课程，请重新提出调整')
            payload['plan']['sessions']=sessions
        if ai:
            from .ai_planning import validate,locked_sessions
            validate(payload['plan'],state['profile'],locked=locked_sessions(state,payload['plan']['week'],engine.today(state).isoformat()))
        else:
            engine.validate_plan(payload['plan'],state['profile'],{r.get('session_id') for r in state['records']})
        if payload['plan']['week']>engine.monday(engine.today(state)).isoformat():
            state['upcoming']=payload['plan']
        else:
            engine.archive(state)
            state['plan']=payload['plan']
        c.execute('DELETE FROM proposals WHERE user_id=?',(row['id'],))
        c.execute("UPDATE planning_jobs SET status='adopted' WHERE user_id=? AND result LIKE ?",(row['id'],'%'+proposal_id+'%'))
        if state.get('upcoming') and state['upcoming']['id']==payload['plan']['id']:
            return f"{payload['plan']['week']} 起的下一周已安排，届时自动接上；本周安排保留。"
        return '已采用调整，提醒会跟随新安排。'
    return change(request,body.revision,update)


@app.post('/api/plan/undo')
def undo(body:Revision,request:Request):
    def update(state,c,row):
        if not state['history']:
            raise ValueError('没有可撤回的计划调整')
        old=state['history'][-1]
        if old['week']!=state['plan']['week']:
            raise ValueError('只能撤回当前周的调整')
        # New records after an edit must never become attached to unrelated or missing sessions.
        current_ids={s['id'] for s in state['plan']['sessions']}
        old_ids={s['id'] for s in old['sessions']}
        if any(r.get('session_id') in current_ids-old_ids for r in state['records']):
            raise ValueError('新安排已有训练记录，不能撤回；请调整后续训练')
        restored=copy.deepcopy(old)
        restored['version']=state['plan']['version']+1
        restored['reason']='撤回上一次调整，保留训练记录'
        # Undo cannot rewrite historical days, or undo the current content policy.
        if old.get('policy') != engine.PLAN_POLICY:
            raise ValueError('上个版本是旧版计划，请修改当前训练偏好')
        past = {s['date']:s for s in state['plan']['sessions'] if s['date']<engine.today(state).isoformat()}
        restored['sessions']=[past.get(s['date'],s) for s in restored['sessions']]
        engine.validate_plan(restored,state['profile'],{r.get('session_id') for r in state['records']})
        engine.archive(state)
        state['plan']=restored
        return '已撤回上一次调整'
    return change(request,body.revision,update)


class Feedback(Revision):
    session_id: str|None = None
    date: date
    status: Literal['completed','partial','skipped','rest']
    minutes: int = Field(ge=0,le=300)
    effort: Literal['easy','okay','hard'] = 'okay'
    pain: bool = False
    note: str = Field(default='',max_length=1000)
    activity: str = Field(default='自主活动',max_length=80)
    avg_heart_rate: int|None = Field(default=None,ge=1,le=300,strict=True)
    record_id: str|None = None
    activity_kind: Literal['walk','indoor','run','bike','strength','mobility','badminton','dance','sport','other']|None = None


@app.post('/api/records')
def record(body:Feedback,request:Request):
    def update(state,c,row):
        if body.date>engine.today(state):
            raise ValueError('不能记录未来的训练')
        if body.status == 'completed' and body.minutes==0:
            raise ValueError('请填写实际活动时长')
        if body.status in ('rest','skipped') and body.minutes!=0:
            raise ValueError('休息或未完成的活动时长应为 0')
        if body.avg_heart_rate is not None and body.status in ('rest','skipped'):
            raise ValueError('只有实际活动记录可以填写平均心率')
        if body.record_id and body.session_id:
            raise ValueError('请按原记录类型修改')
        prescription=None
        if body.session_id:
            effective=engine.effective_plan(state,state['plan'],engine.today(state))
            prescription=next((s for s in (effective or {}).get('sessions',[]) if s['id']==body.session_id),None)
            if prescription and prescription.get('period_adjusted'):
                if prescription['kind']=='rest' and body.status not in ('rest','skipped'):
                    raise ValueError('这一天已调整为休息；如有自主活动，请单独记录')
                prescription={k:v for k,v in prescription.items() if k!='period_adjusted'}
            else:
                prescription=None
            session=next((s for p in ([state['plan']] if state['plan'] else [])+state['history'][::-1]
                          for s in p['sessions'] if s['id']==body.session_id and s['date']==body.date.isoformat()),None)
            if not session:
                raise ValueError('训练日期不匹配，请刷新后重新记录')
            existing=next((r for r in state['records'] if r.get('session_id')==body.session_id),None)
        elif body.record_id:
            existing=next((r for r in state['records'] if r['id']==body.record_id and not r.get('session_id') and r.get('source')!='demo'),None)
            if not existing:
                raise ValueError('没有找到可编辑的自主运动记录')
        else:
            existing=None
        r={**body.model_dump(exclude={'revision','record_id'},mode='json'),'id':existing['id'] if existing else engine.uid(),
           'source':'self','created':existing['created'] if existing else datetime.now().isoformat(timespec='seconds')}
        if existing and body.status in ('completed','partial') and 'avg_heart_rate' not in body.model_fields_set:
            r['avg_heart_rate']=existing.get('avg_heart_rate')
        if body.session_id:
            r['activity_kind']=(prescription or (existing or {}).get('prescription') or session)['kind']
        if body.session_id and existing and existing.get('prescription',{}).get('kind')=='rest' and body.status not in ('rest','skipped'):
            raise ValueError('这一天已调整为休息；如有自主活动，请单独记录')
        if prescription or (existing and existing.get('prescription')):
            r['prescription']=prescription or existing['prescription']
        if existing:
            state['records'][state['records'].index(existing)]=r
        else:
            state['records'].append(r)
        state['records'].sort(key=lambda r:(r['date'],r['created']))
        if body.pain and state['profile']:
            old_note=state['profile'].get('limitations','')
            state['profile']['limitations']=(old_note+'；训练反馈中报告不适：'+(body.note or '请结合医嘱确认活动范围')).strip('；')[-1000:]
            engine.reconcile_health(state)
        flags=engine.load_flags(state)
        return '已记录。'+(flags[0]['label']+'连续超出计划，可在「成长」查看如何调整。' if flags and not body.pain else engine.next_direction(state)[1])
    return change(request,body.revision,update)


class ReviewRequest(Revision):
    cadence: Literal['week','month']
    anchor: date|None = None


@app.post('/api/reviews')
def review(body:ReviewRequest,request:Request):
    def update(state,c,row):
        if body.anchor and body.anchor>engine.today(state):
            raise ValueError('不能生成未来的复盘')
        result=engine.review(state,body.cadence,body.anchor)
        state['reviews']=[x for x in state['reviews'] if x['id']!=result['id']]+[result]
        return result
    return change(request,body.revision,update)


class NextWeek(Revision):
    progress: bool = False
    recovered: bool = False


@app.post('/api/plan/next')
def next_week(body:NextWeek,request:Request):
    def update(state,c,row):
        if not state['profile'] or state.get('blocked'):
            raise ValueError('请先确认运动档案和身体情况')
        if state['profile']['goal'] not in engine.GOALS or state['profile']['level']=='competitive' or (state.get('plan') or {}).get('policy')=='ai-reviewed-v1':
            raise ValueError('请使用「AI生成并评审」制定下一周，原方案保留')
        d=engine.today(state)
        old=state['plan']
        next_start=engine.monday(d)+timedelta(days=7)
        if (state.get('upcoming') and not engine.load_flags(state)) or (old and old['week']>=next_start.isoformat()):
            raise ValueError('下一周已经安排好了，请到计划页查看')
        direction,reason=engine.next_direction(state,include_period=False)
        minutes=min(state['profile']['minutes'],max((x['minutes'] for x in (old or {}).get('sessions',[]) if x['kind']!='rest'),default=min(20,state['profile']['minutes'])))
        flags=engine.load_flags(state)
        if direction in ('ease','restart'):
            minutes=min(minutes,15)
        if body.progress:
            period=engine.period_view(state)
            if flags or direction!='consider' or not body.recovered or (period and period['mode']!='normal'):
                raise ValueError('进阶需要至少四次完整且轻松的近期训练，并确认恢复良好')
            minutes=min(state['profile']['minutes'],minutes+5)
        p=state['profile']
        plan=engine.generate(p,next_start,old,reason,duration=minutes,easy_only=direction in ('ease','restart'),load_flags=flags)
        if old:
            locked={s['id'] for s in old['sessions']}
            engine.preserve_recovery(plan,p,locked,old['sessions'])
            if not any(f['kind']=='strength' for f in flags):
                engine.restore_strength_priority(plan,p,next_start,locked,old['sessions'])
        # Draft only; future plan is not activated by preview.
        proposal_id=engine.uid()
        c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',
            (proposal_id,row['id'],row['revision']+1,json.dumps({'plan':plan,'summary':reason,'request':'制定下一周安排','profile_minutes':minutes},ensure_ascii=False)))
        return {'proposal_id':proposal_id,'summary':reason}
    return change(request,body.revision,update)


class Settings(Revision):
    timezone: str = 'Asia/Shanghai'
    daily: bool
    weekly: bool
    monthly: bool
    followup: bool
    email: bool
    time: str
    quiet_start: str
    quiet_end: str
    tone: Literal['gentle','standard','firm']
    paused_until: str = ''

    @field_validator('time','quiet_start','quiet_end')
    @classmethod
    def valid_time(cls,v):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',v):
            raise ValueError('时间格式应为 HH:MM')
        return v

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls,v):
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError,ValueError):
            raise ValueError('无效时区')
        return v

    @field_validator('paused_until')
    @classmethod
    def valid_pause(cls,v):
        if v:
            date.fromisoformat(v)
        return v


@app.put('/api/settings')
def settings(body:Settings,request:Request):
    def update(state,c,row):
        if body.email and (row['demo'] or not config.SMTP_HOST):
            raise ValueError('演示账号或未配置邮件服务时，仅支持站内提醒')
        state['settings']=body.model_dump(exclude={'revision'})
        return '提醒偏好已保存'
    return change(request,body.revision,update)


@app.post('/api/notices/read')
def notices_read(request:Request):
    row=actor(request)
    with db.connect() as c:
        c.execute('UPDATE notices SET read=1 WHERE user_id=?',(row['id'],))
    return {'ok':True}


@app.get('/api/export')
def export(request:Request):
    row=actor(request)
    payload={'product':'SportsWise','exported':datetime.now(timezone.utc).isoformat(),'state':db.decode(row)}
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="sportswise-backup.json"'})


@app.delete('/api/account')
def delete_account(request:Request,response:Response):
    row=actor(request)
    with db.transaction() as c:
        c.execute('DELETE FROM login_codes WHERE email=?',(row['email'],))
        c.execute('DELETE FROM llm_usage WHERE actor=?',(row['id'],))
        c.execute('DELETE FROM users WHERE id=?',(row['id'],))
    response.delete_cookie(COOKIE)
    return {'ok':True}


@app.get('/api/health')
def health():
    return {'ok':True,'product':'SportsWise','plan_policy':engine.PLAN_POLICY,'growth':'garden-v1'}


app.mount('/static',StaticFiles(directory=config.ROOT/'static'),name='static')


@app.get('/')
def index():
    return FileResponse(config.ROOT/'static/index.html',headers={'Cache-Control':'no-cache'})


@app.get('/sw.js')
def service_worker():
    return FileResponse(config.ROOT/'static/sw.js',media_type='application/javascript',headers={'Cache-Control':'no-cache'})
