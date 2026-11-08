import copy
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import config, db, engine, services
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'test.db')
    monkeypatch.setattr(config,'API_KEY','')
    monkeypatch.setattr(config,'SMTP_HOST','')
    monkeypatch.setattr(config,'ENV','development')
    # Scheduler is tested explicitly with a fixed clock.
    with patch.object(services,'worker',lambda stop:None):
        with TestClient(app) as c:
            yield c


def demo(c):
    r=c.post('/api/demo')
    assert r.status_code==200,r.text
    return r.json()


def login(c,email='test@example.com'):
    r=c.post('/api/auth/code',json={'email':email})
    assert r.status_code==200,r.text
    r=c.post('/api/auth/verify',json={'email':email,'code':r.json()['dev_code']})
    assert r.status_code==200,r.text
    return r.json()


def new_profile(c, p=None):
    d=login(c)
    p=p or engine.sample_profile()
    p['days']=[0,2,6]
    r=c.put('/api/profile',json={'revision':d['revision'],'profile':p})
    assert r.status_code==200,r.text
    return r.json()


def pending(d):
    return next(s for s in d['state']['plan']['sessions'] if s['date']>=d['today'] and s['kind']!='rest')


def test_demo_isolation_and_persistence(client):
    a=demo(client)
    b=client.get('/api/state').json()
    assert a['user']['id']==b['user']['id']
    other=TestClient(app)
    assert other.get('/api/state').status_code==401
    c=demo(other)
    assert c['user']['id']!=a['user']['id']
    assert a['state']['records']


def test_login_wrong_attempts_and_single_use(client):
    r=client.post('/api/auth/code',json={'email':'a@example.com'}).json()
    for _ in range(5):
        assert client.post('/api/auth/verify',json={'email':'a@example.com','code':'wrong!'}).status_code==400
    assert client.post('/api/auth/verify',json={'email':'a@example.com','code':r['dev_code']}).status_code==400
    d=login(client)
    assert not d['user']['demo']
    assert client.post('/api/demo').json()['user']['id']==d['user']['id']


def test_production_never_exposes_code(client,monkeypatch):
    monkeypatch.setattr(config,'ENV','production')
    r=client.post('/api/auth/code',json={'email':'a@example.com'})
    assert r.status_code==503


def test_onboarding_duration_and_safety(client):
    p=engine.sample_profile();p['minutes']=45;p['level']='beginner'
    d=new_profile(client,p)
    assert max(s['minutes'] for s in d['state']['plan']['sessions'])<=20
    for s in d['state']['plan']['sessions']:
        assert sum(x['minutes'] for x in s['steps'])==s['minutes']
    p['limitations']='膝盖疼'
    r=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    assert not r['state']['blocked']
    assert r['state']['risk']['level']=='caution'
    s=pending(r)
    r=client.post('/api/coach',json={'revision':r['revision'],'text':'今天只有十分钟','session_id':s['id']}).json()
    assert r['result']['proposal_id'] is not None


def test_preview_apply_undo_and_original_metrics(client):
    d=demo(client);session=pending(d)
    r=client.post('/api/coach',json={'revision':d['revision'],'text':'今天只有十分钟','session_id':session['id']})
    assert r.status_code==200,r.text
    d=r.json();pid=d['result']['proposal_id']
    assert pid
    assert next(x for x in d['state']['plan']['sessions'] if x['id']==session['id'])['minutes']==session['minutes']
    old_records=copy.deepcopy(d['state']['records']);original=d['stats']['original_minutes']
    r=client.post(f'/api/proposals/{pid}/apply',json={'revision':d['revision']})
    assert r.status_code==200,r.text
    d=r.json()
    assert next(x for x in d['state']['plan']['sessions'] if x['id']==session['id'])['minutes']==10
    assert d['state']['records']==old_records
    assert d['stats']['original_minutes']==original
    assert d['stats']['planned']==3
    d=client.post('/api/plan/undo',json={'revision':d['revision']}).json()
    assert next(x for x in d['state']['plan']['sessions'] if x['id']==session['id'])['minutes']==session['minutes']


def test_stale_revision_and_private_proposal(client):
    d=demo(client)
    r=client.post('/api/coach',json={'revision':d['revision'],'text':'只有十分钟'}).json()
    assert client.post('/api/reviews',json={'revision':d['revision'],'cadence':'week'}).status_code==409
    other=TestClient(app);demo(other)
    assert other.get('/api/proposals/'+r['result']['proposal_id']).status_code==404


def test_record_upsert_and_discomfort(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,4))
    d=demo(client);s=pending(d)
    record={'revision':d['revision'],'session_id':s['id'],'date':s['date'],'status':'partial','minutes':10,'effort':'hard','pain':False,'note':'太累'}
    d=client.post('/api/records',json=record).json()
    n=len(d['state']['records'])
    record.update(revision=d['revision'],pain=True,note='不适')
    d=client.post('/api/records',json=record).json()
    assert len(d['state']['records'])==n
    assert not d['state']['blocked']
    assert d['state']['risk']['level']=='caution'
    assert client.post('/api/plan/next',json={'revision':d['revision']}).status_code==200


def test_future_record_rejected(client):
    d=demo(client)
    r=client.post('/api/records',json={'revision':d['revision'],'date':(engine.today()+timedelta(days=1)).isoformat(),'status':'completed','minutes':20})
    assert r.status_code==422


def test_next_week_is_queued_not_activated(client):
    d=demo(client);old=copy.deepcopy(d['state']['plan'])
    d=client.post('/api/plan/next',json={'revision':d['revision']}).json()
    pid=d['result']['proposal_id']
    r=client.post(f'/api/proposals/{pid}/apply',json={'revision':d['revision']})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['state']['plan']==old
    assert d['state']['upcoming']['week']>old['week']
    st=d['state'];future=date.fromisoformat(st['upcoming']['week'])
    assert engine.activate_due(st,future)
    assert st['plan']['week']==future.isoformat()
    assert st['upcoming'] is None


def test_rebuild_does_not_double_count_latest_schedule(client):
    d=demo(client);p=d['state']['profile'];n=len(d['state']['records'])
    p['minutes']=20
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    assert d['stats']['planned']==3
    assert len(d['state']['records'])==n


def test_review_uses_actual_records_and_does_not_invent(client):
    d=demo(client)
    r=client.post('/api/reviews',json={'revision':d['revision'],'cadence':'month'})
    assert r.status_code==200,r.text
    review=r.json()['result']
    assert review['stats']['minutes']==sum(x['minutes'] for x in review['stats']['records'] if x['status'] in ('completed','partial'))


def test_progress_requires_evidence(client):
    d=new_profile(client)
    r=client.post('/api/plan/next',json={'revision':d['revision'],'progress':True,'recovered':True})
    assert r.status_code==422


def test_scheduler_quiet_dedupe_cancel_and_no_demo_email(client):
    d=demo(client);uid=d['user']['id'];st=d['state']
    fixed=datetime(2026,11,1,10,30,tzinfo=timezone.utc) # local Sunday 18:30
    st['plan']=engine.generate(st['profile'],date(2026,10,26))
    st['records']=[]
    st['settings']['email']=True
    with db.connect() as c:
        c.execute('UPDATE users SET state=?,last_seen_at=? WHERE id=?',(json.dumps(st),'2026-11-01T10:00:00',uid))
    with patch.object(services,'send_mail') as send:
        services.tick(fixed);services.tick(fixed)
        send.assert_not_called()
    with db.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM notices WHERE user_id=? AND kind='daily'",(uid,)).fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0]==0
    st['settings']['quiet_start']='18:00';st['settings']['quiet_end']='20:00'
    with db.connect() as c:
        c.execute('DELETE FROM notices')
        c.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(st),uid))
    services.tick(fixed)
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM notices').fetchone()[0]==0


def test_export_delete_and_csrf(client):
    d=demo(client)
    assert client.post('/api/plan/undo',json={'revision':d['revision']},headers={'origin':'https://evil.example'}).status_code==403
    assert client.get('/api/export').json()['state']['records']
    assert client.delete('/api/account').status_code==200
    assert client.get('/api/state').status_code==401
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0


def test_recovery_and_no_calendar_auto_increase():
    st=engine.demo();st['records']=[]
    for i in range(2):
        st['records'].append({'date':engine.today().isoformat(),'status':'completed','minutes':20,'effort':'hard','pain':False})
    assert engine.next_direction(st)[0]=='ease'
    st['records'][0]['date']=(engine.today()-timedelta(days=30)).isoformat()
    st['records'][1]['date']=(engine.today()-timedelta(days=29)).isoformat()
    assert engine.next_direction(st)[0]=='restart'


def test_intake_is_a_draft_and_unknown_not_guessed(client):
    d=demo(client)
    r=client.post('/api/intake',json={'text':'半年没运动，想改善体力。周一周三每次20分钟。'})
    assert r.status_code==200,r.text
    out=r.json()
    assert out['patch']['minutes']==20
    assert out['patch']['days']==[0,2]
    assert out['patch']['goal']=='energy'
    assert client.get('/api/state').json()['revision']==d['revision']


def test_date_parser_and_scope():
    out=engine.local_intent('改到 2026-11-05')
    assert out['intent']=='move'
    assert out['target_date']=='2026-11-05'
    assert engine.local_intent('这周轻一点')['scope']=='week'


def test_new_profile_does_not_create_past_missed_workouts(client):
    d=new_profile(client)
    assert d['stats']['unknown']==0
    assert all(s['kind']=='rest' for s in d['state']['plan']['sessions'] if s['date']<d['today'])


def test_week_rollover_preserves_history_and_never_auto_progresses():
    st=engine.demo();old=copy.deepcopy(st['plan'])
    future=date.fromisoformat(old['week'])+timedelta(days=9)
    assert engine.activate_due(st,future)
    assert old in st['history']
    assert st['plan']['week']==engine.monday(future).isoformat()
    assert max(s['minutes'] for s in st['plan']['sessions'])<=max(s['minutes'] for s in old['sessions'])
    assert all(s['kind']=='rest' for s in st['plan']['sessions'] if s['date']<future.isoformat())


def test_all_supported_weekday_combinations_respect_recovery():
    from itertools import combinations
    p=engine.sample_profile()
    for n in range(1,6):
        for days in combinations(range(7),n):
            p['days']=list(days)
            p['likes']=['strength']
            plan=engine.generate(p,date(2026,11,2))
            strength=[i for i,s in enumerate(plan['sessions']) if s['kind']=='strength']
            assert all(min(abs(a-b),7-abs(a-b))>=2 for a,b in combinations(strength,2))
            assert all(sum(x['minutes'] for x in s['steps'])==s['minutes'] for s in plan['sessions'])


def test_reducing_available_time_keeps_completed_history_editable(client):
    d=demo(client)
    p=d['state']['profile'];p['minutes']=10
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    s=pending(d)
    r=client.post('/api/coach',json={'revision':d['revision'],'text':'今天换成室内活动','session_id':s['id']})
    assert r.status_code==200,r.text
    d=r.json();pid=d['result']['proposal_id']
    assert pid,d['result']
    assert client.post('/api/proposals/'+pid+'/apply',json={'revision':d['revision']}).status_code==200


def test_next_week_respects_reduced_time_even_if_past_sessions_longer(client):
    d=demo(client)
    p=d['state']['profile'];p['minutes']=10
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    d=client.post('/api/plan/next',json={'revision':d['revision']}).json()
    pid=d['result']['proposal_id']
    preview=client.get('/api/proposals/'+pid).json()
    assert max(s['minutes'] for s in preview['plan']['sessions'])<=10
    r=client.post('/api/proposals/'+pid+'/apply',json={'revision':d['revision']})
    assert r.status_code==200,r.text


def test_health_notes_generate_plan_with_cautions(client):
    p=engine.sample_profile()
    p['limitations']='体检血脂、肝脏功能等指标异常'
    d=new_profile(client,p)
    assert d['state']['plan']
    assert not d['state']['blocked']
    assert d['state']['risk']['level']=='caution'
    assert '医嘱' in d['state']['risk']['message']
    assert any(s['kind']!='rest' for s in d['state']['plan']['sessions'])
    assert all(s['minutes']<=15 for s in d['state']['plan']['sessions'])
    upcoming=client.post('/api/plan/next',json={'revision':d['revision']}).json()
    pid=upcoming['result']['proposal_id']
    preview=client.get('/api/proposals/'+pid).json()
    assert preview['plan']['risk']['level']=='caution'
    assert client.post('/api/proposals/'+pid+'/apply',json={'revision':upcoming['revision']}).status_code==200


def test_legacy_blocked_profile_gets_plan_without_reentering(client):
    d=login(client)
    p=engine.sample_profile();p['limitations']='有需留意的体检指标'
    st=engine.empty();st['profile']=p;st['blocked']=True
    with db.connect() as c:
        c.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(st),d['user']['id']))
    result=client.get('/api/state')
    assert result.status_code==200,result.text
    st=result.json()['state']
    assert st['plan']
    assert st['profile']==p
    assert not st['blocked']
    assert st['risk']['level']=='caution'
    # No regeneration every time the page opens.
    assert client.get('/api/state').json()['state']['plan']['id']==st['plan']['id']


@pytest.mark.parametrize('note',['今天胸痛、头晕','医生要求暂停运动','禁止负重，需卧床'])
def test_acute_or_explicit_restrictions_still_have_recovery_plan(client,note):
    p=engine.sample_profile();p['limitations']=note
    d=new_profile(client,p)
    assert not d['state']['blocked']
    assert d['state']['risk']['level']=='hold'
    assert d['state']['plan']
    assert len(d['state']['plan']['sessions'])==7
    assert all(s['kind']=='rest' and s['minutes']==0 for s in d['state']['plan']['sessions'])
    r=client.post('/api/plan/next',json={'revision':d['revision']})
    assert r.status_code==200,r.text


def test_current_symptoms_preserve_profile_and_completed_records(client):
    d=demo(client);records=copy.deepcopy(d['state']['records'])
    p=d['state']['profile'];p['limitations']='需要留意体检指标'
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    r=client.post('/api/coach',json={'revision':d['revision'],'text':'今天胸痛和头晕'})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['state']['risk']['level']=='hold'
    assert '需要留意体检指标' in d['state']['profile']['limitations']
    assert d['state']['records']==records
    assert all(s['kind']=='rest' for s in d['state']['plan']['sessions'] if s['date']>=d['today'])


def test_no_symptoms_does_not_trigger_recovery_only():
    p=engine.sample_profile();p['limitations']='血脂异常，没有胸痛，没有头晕'
    assert engine.health_risk(p)['level']=='caution'


def test_age_applicability_still_checked(client):
    d=login(client);p=engine.sample_profile();p['adult']=False
    r=client.put('/api/profile',json={'revision':d['revision'],'profile':p})
    assert r.status_code==200
    assert r.json()['state']['blocked']
    assert r.json()['state']['plan'] is None


def test_legacy_normal_profile_does_not_lose_queued_plan(client):
    d=demo(client);st=d['state'];st.pop('risk',None)
    st['upcoming']=engine.generate(st['profile'],engine.monday(engine.today())+timedelta(days=7))
    plan=copy.deepcopy(st['plan']);upcoming=copy.deepcopy(st['upcoming'])
    with db.connect() as c:
        c.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(st),d['user']['id']))
    d=client.get('/api/state').json()
    assert d['state']['plan']==plan
    assert d['state']['upcoming']==upcoming


def test_first_plan_at_week_end_includes_upcoming_training(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,1))
    d=login(client)
    p=engine.sample_profile();p['days']=[0,2,5]
    r=client.put('/api/profile',json={'revision':d['revision'],'profile':p})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['state']['upcoming']
    assert d['state']['upcoming']['week']=='2026-11-02'
    assert any(s['kind']!='rest' for s in d['state']['upcoming']['sessions'])
    assert d['stats']['unknown']==0


def test_demo_creation_is_limited_without_affecting_existing_session(client):
    d=demo(client)
    with db.connect() as c:
        c.execute('UPDATE auth_limits SET count=30 WHERE ip=?',('demo:testclient',))
    assert client.post('/api/demo').status_code==200
    client.cookies.clear()
    assert client.post('/api/demo').status_code==429


def test_main_goal_changes_training_emphasis_within_preferences():
    p=engine.sample_profile();p['days']=[0,2,5];p['limitations']=''
    p['goal']='strength';strength=engine.generate(p,date(2026,11,2))
    p['goal']='endurance';endurance=engine.generate(p,date(2026,11,2))
    assert sum(s['kind']=='strength' for s in strength['sessions'])>sum(s['kind']=='strength' for s in endurance['sessions'])
    assert endurance['rationale']
    p['likes']=['walking'];walk_only=engine.generate(p,date(2026,11,2))
    assert all(s['kind']!='strength' for s in walk_only['sessions'])


def test_from_zero_demo_does_not_mix_example_history(client):
    original=demo(client)
    d=client.post('/api/demo',json={'mode':'empty'}).json()
    assert d['user']['id']!=original['user']['id']
    assert d['state']['profile'] is None
    assert d['state']['plan'] is None
    assert d['state']['records']==[]
    assert d['state']['demo_mode']=='empty'
    assert db.read_user(original['user']['id']) is not None
    assert db.decode(db.read_user(original['user']['id']))['records']


def test_demo_mode_never_replaces_real_account(client):
    original=login(client)
    d=client.post('/api/demo',json={'mode':'empty'}).json()
    assert d['user']['id']==original['user']['id']
    assert not d['user']['demo']


def test_brief_attempt_is_partial_and_never_full_completion(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,1))
    d=demo(client);s=pending(d);before=d['stats']
    body={'revision':d['revision'],'session_id':s['id'],'date':s['date'],'status':'partial','minutes':0,'effort':'okay'}
    r=client.post('/api/records',json=body)
    assert r.status_code==200,r.text
    d=r.json()
    assert d['stats']['full']==before['full']
    assert d['stats']['minutes']==before['minutes']
    body.update(revision=d['revision'],status='completed')
    assert client.post('/api/records',json=body).status_code==422


def test_first_registration_can_keep_explicitly_approved_blank_trial(client):
    d=client.post('/api/demo',json={'mode':'empty'}).json()
    p=engine.sample_profile();p['name']='虚构试用'
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    code=client.post('/api/auth/code',json={'email':'new-trial@example.com'}).json()['dev_code']
    r=client.post('/api/auth/verify',json={'email':'new-trial@example.com','code':code,'import_trial':True})
    assert r.status_code==200,r.text
    d=r.json()
    assert not d['user']['demo']
    assert d['state']['profile']['name']=='虚构试用'
    assert d['state']['plan']
    assert 'demo_mode' not in d['state']


def test_example_records_are_never_imported_even_if_requested(client):
    demo(client)
    code=client.post('/api/auth/code',json={'email':'no-example@example.com'}).json()['dev_code']
    d=client.post('/api/auth/verify',json={'email':'no-example@example.com','code':code,'import_trial':True}).json()
    assert d['state']['profile'] is None
    assert d['state']['records']==[]


def test_regular_runner_gets_three_distinct_sessions_at_familiar_volume():
    p=engine.sample_profile()
    p.update(level='regular',goal='endurance',likes=['running'],minutes=45,usual_minutes=35,
             days=[0,2,5],limitations='身体健康，没有任何运动限制',support_training=False)
    start=date(2026,11,2)
    active=[s for s in engine.generate(p,start)['sessions'] if s['kind']!='rest']
    assert [s['kind'] for s in active]==['run']*3
    assert len({s['steps'][1]['title'] for s in active})==3
    assert [s['minutes'] for s in active]==[35,30,35]
    assert [s['intensity'].startswith('中等') for s in active]==[True,False,True]
    p['level']='beginner'
    sessions=[s for s in engine.generate(p,start)['sessions'] if s['kind']=='run']
    assert all(s['minutes']<=20 and '慢跑与步行交替' in {x['title'] for x in s['steps']} for s in sessions)


def test_strength_uses_familiar_gear_and_alternates_workouts():
    p=engine.sample_profile()
    p.update(level='regular',goal='strength',likes=['strength'],equipment=['dumbbell'],days=[0,1,3],minutes=40)
    plan=engine.generate(p,date(2026,11,2))
    a, recovery, b=[s for s in plan['sessions'] if s['kind']!='rest']
    assert recovery['kind']=='mobility'
    assert any(x['title']=='哑铃杯式深蹲' and x['sets']==2 and x['reps']==8 and x['rest_seconds']==75 for x in a['steps'])
    assert any(x['title']=='哑铃罗马尼亚硬拉' for x in b['steps'])
    assert all(sum(x['minutes'] for x in s['steps'])==s['minutes'] for s in (a,b))


def test_intake_can_extract_an_existing_routine_without_ai(client):
    d=demo(client)
    out=client.post('/api/intake',json={'text':'我每周跑步和训练。每周 3 次规律训练，平时跑步每次35分钟，在家有哑铃。'}).json()
    assert out['patch']['level']=='regular'
    assert 'running' in out['patch']['likes']
    assert out['patch']['equipment']==['dumbbell']
    assert out['patch']['usual_minutes']==35


def runner_account(client, monkeypatch, day=date(2026,11,2)):
    now=[day]
    monkeypatch.setattr(engine,'today',lambda state=None:now[0])
    d=login(client)
    p=engine.sample_profile()
    p.update(level='regular',goal='endurance',likes=['running'],days=[0,2,4,6],minutes=40,limitations='身体健康',support_training=False)
    out=client.put('/api/profile',json={'revision':d['revision'],'profile':p})
    assert out.status_code==200,out.text
    return now,out.json()


def test_period_is_opt_in_adjusts_only_window_and_preserves_record(client,monkeypatch):
    now,d=runner_account(client,monkeypatch)
    orig=d['state']['plan']['sessions']
    assert d['state']['period'] is None
    d=client.put('/api/period',json={'revision':d['revision'],'mode':'normal','days':3}).json()
    assert d['state']['plan']['sessions']==orig
    d=client.put('/api/period',json={'revision':d['revision'],'mode':'ease','days':3}).json()
    shown=d['state']['plan']['sessions']
    assert shown[0]['kind']=='indoor' and shown[0]['minutes']<orig[0]['minutes']
    assert shown[2]['period_adjusted'] and shown[4]==orig[4]
    assert db.decode(db.read_user(d['user']['id']))['plan']['sessions']==orig
    session=shown[0]
    d=client.post('/api/records',json={'revision':d['revision'],'session_id':session['id'],'date':session['date'],
                                       'status':'completed','minutes':session['minutes']}).json()
    assert d['state']['records'][0]['prescription']['kind']=='indoor'
    d=client.request('DELETE','/api/period',json={'revision':d['revision']}).json()
    assert d['state']['period'] is None
    assert d['state']['plan']['sessions'][2]==orig[2]
    assert d['state']['plan']['sessions'][0]['kind']=='indoor'
    assert d['state']['records'][0]['minutes']==session['minutes']


def test_period_rest_suppresses_reminder_and_expires_without_catchup(client,monkeypatch):
    now,d=runner_account(client,monkeypatch,date(2026,11,4))
    orig=d['state']['plan']['sessions']
    when=datetime(2026,11,4,10,31,tzinfo=timezone.utc)
    services._tick_user(d['user']['id'],when)
    d=client.get('/api/state').json()
    assert any(n['kind']=='daily' and not n['read'] for n in d['notices'])
    d=client.put('/api/period',json={'revision':d['revision'],'mode':'rest','days':1}).json()
    assert d['state']['plan']['sessions'][2]['kind']=='rest'
    assert all(n['read'] for n in d['notices'] if n['kind']=='daily')
    services._tick_user(d['user']['id'],when+timedelta(minutes=20))
    assert len([n for n in client.get('/api/state').json()['notices'] if n['kind']=='daily'])==1
    now[0]+=timedelta(days=1)
    d=client.get('/api/state').json()
    assert d['state']['period'] is None
    assert 'period' not in db.decode(db.read_user(d['user']['id']))
    assert d['state']['plan']['sessions'][2]['kind']=='rest'
    assert d['state']['plan']['sessions'][4]==orig[4]
    assert d['stats']['unknown']==0


def test_period_applies_to_queued_and_activated_week(client,monkeypatch):
    now,d=runner_account(client,monkeypatch,date(2026,11,8))
    d=client.post('/api/plan/next',json={'revision':d['revision']}).json()
    d=client.post('/api/proposals/'+d['result']['proposal_id']+'/apply',json={'revision':d['revision']}).json()
    d=client.put('/api/period',json={'revision':d['revision'],'mode':'rest','days':2}).json()
    assert d['state']['upcoming']['sessions'][0]['kind']=='rest'
    assert d['state']['upcoming']['sessions'][2]['kind']=='run'
    now[0]+=timedelta(days=1)
    d=client.get('/api/state').json()
    assert d['state']['plan']['week']=='2026-11-09'
    assert d['state']['plan']['sessions'][0]['kind']=='rest'
    assert d['state']['upcoming'] is None


def test_legacy_plan_migrates_pending_slots_without_rewriting_history(client,monkeypatch):
    now,d=runner_account(client,monkeypatch,date(2026,11,4))
    st=db.decode(db.read_user(d['user']['id']))
    plan=st['plan']
    for i in (0,2,4):
        day=date.fromisoformat(plan['sessions'][i]['date'])
        plan['sessions'][i]=engine.make_session(day,'walk',25,st['profile'],easy_only=True)
    plan['sessions'][4].update(minutes=10,steps=engine.make_session(now[0],'walk',10,st['profile'])['steps'])
    st['records'].append({'session_id':plan['sessions'][0]['id'],'date':'2026-11-02','status':'completed','minutes':25,'effort':'okay','pain':False})
    plan.pop('policy')
    with db.transaction() as c:
        db.save(c,d['user']['id'],st,d['revision'])
    result=client.get('/api/state').json()['state']
    assert result['plan']['sessions'][0]==plan['sessions'][0]
    assert result['plan']['sessions'][2]['kind']=='run'
    assert result['plan']['sessions'][2]['id']==plan['sessions'][2]['id']
    assert result['plan']['sessions'][4]==plan['sessions'][4]
    assert result['records']==st['records']


def test_week_pairs_running_with_dosed_lower_body_and_preferred_sports():
    p=engine.sample_profile()
    p.update(level='regular',goal='endurance',likes=['running','badminton','dance'],days=[0,2,4,5,6],
             equipment=['dumbbell'],minutes=35)
    plan=engine.generate(p,date(2026,11,2))
    kinds={s['kind'] for s in plan['sessions']}
    assert {'run','strength','dance','badminton'}<=kinds
    strength=next(s for s in plan['sessions'] if s.get('runner_support'))
    assert {'哑铃杯式深蹲','哑铃罗马尼亚硬拉','扶稳提踵'}<={s['title'] for s in strength['steps']}
    for s in strength['steps'][1:-1]:
        assert s['sets']==2 and s['reps']==8 and s['rest_seconds']==75
        assert s['caution'] and s['benefit'] and s['alternatives']
    assert '小腿' in strength['steps'][-1]['detail']
    for session in plan['sessions']:
        assert session['minutes']==sum(x['minutes'] for x in session['steps'])
    p.update(place='home')
    assert not {'run','badminton'}&{s['kind'] for s in engine.generate(p,date(2026,11,2))['sessions']}


def test_bone_goal_pairs_familiar_cycling_with_resistance_and_weight_bearing():
    p=engine.sample_profile()
    p.update(goal='bone',likes=['cycling'],days=[0,2,4],level='regular')
    plan=engine.generate(p,date(2026,11,2))
    assert {'strength','walk'}<={s['kind'] for s in plan['sessions']}
    assert '不能据此测得骨密度' in plan['rationale']


def test_replacements_preview_then_apply_without_touching_other_steps(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,2))
    d=login(client)
    p=engine.sample_profile()
    p.update(level='regular',goal='muscle',likes=['strength','dance'],days=[0,2,4],
             equipment=['dumbbell'],minutes=40)
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    before=d['state']['plan']['sessions'][0]
    assert before['steps'][1]['title']=='哑铃杯式深蹲'
    d=client.post('/api/plan/swap',json={'revision':d['revision'],'session_id':before['id'],'step_index':1}).json()
    assert d['state']['plan']['sessions'][0]==before
    pid=d['result']['proposal_id']
    preview=client.get('/api/proposals/'+pid).json()['plan']['sessions'][0]
    assert preview['steps'][1]['title']=='椅子坐站'
    assert preview['steps'][2:]==before['steps'][2:]
    d=client.post('/api/proposals/'+pid+'/apply',json={'revision':d['revision']}).json()
    assert d['state']['plan']['sessions'][0]==preview
    dance=next(s for s in d['state']['plan']['sessions'] if s['kind']=='dance')
    assert 'indoor' in d['session_options'][dance['id']]
    d=client.post('/api/plan/swap',json={'revision':d['revision'],'session_id':dance['id'],'kind':'indoor'}).json()
    sessions=client.get('/api/proposals/'+d['result']['proposal_id']).json()['plan']['sessions']
    assert next(s for s in sessions if s['id']==dance['id'])['kind']=='indoor'


def test_repeated_recorded_overage_flags_the_sport_and_changes_next_week(monkeypatch):
    d=date(2026,11,15)
    monkeypatch.setattr(engine,'today',lambda state=None:d)
    p=engine.sample_profile()
    p.update(level='regular',goal='endurance',likes=['running'],days=[0,2,5],minutes=35)
    state=engine.empty()
    state['profile']=p
    state['plan']=engine.generate(p,date(2026,11,9))
    state['history']=[engine.generate(p,date(2026,11,2))]
    for day in (2,5,9,12):
        state['records'].append({'date':f'2026-11-{day:02d}','status':'completed','activity_kind':'run',
                                 'minutes':65,'effort':'okay','pain':False})
    flags=engine.load_flags(state)
    assert [f['kind'] for f in flags]==['run']
    assert [w['actual'] for w in flags[0]['windows']]==[130,130]
    assert engine.next_direction(state)[0]=='rebalance'
    next_plan=engine.generate(p,date(2026,11,16),load_flags=flags)
    assert next_plan['sessions'][0]['kind']=='walk'
    assert any(s.get('runner_support') for s in next_plan['sessions'])
    state['records']=state['records'][2:]
    assert engine.load_flags(state)==[]


def test_regular_muscle_goal_reserves_strength_even_if_optional_support_is_off():
    p=engine.sample_profile()
    p.update(level='regular',goal='muscle',likes=['walking'],support_training=False,
             equipment=['dumbbell'],days=[0,1,3,4,6],minutes=40)
    a=engine.generate(p,date(2026,11,2))
    b=engine.generate(p,date(2026,11,9),a)
    for plan in (a,b):
        sessions=[s for s in plan['sessions'] if s['kind']=='strength']
        assert len(sessions)==2
        assert sessions[0]['steps'][1]['title']=='哑铃杯式深蹲'
        assert sessions[0]['steps'][1]['reps']==8 and sessions[0]['steps'][1]['rep_max']==12
        assert sessions[1]['steps'][1]['title']=='哑铃罗马尼亚硬拉'


def test_localized_limit_restricts_the_exercises_not_the_entire_strength_goal(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,4))
    d=login(client)
    p=engine.sample_profile()
    p.update(level='regular',goal='muscle',likes=['walking','strength'],equipment=['dumbbell','band'],
             days=[0,1,2,4,6],minutes=40,limitations='近期跑步后膝盖有点疼，腰部有旧伤')
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    planned=[s for s in d['state']['plan']['sessions'] if s['kind']=='strength']
    assert planned and all(s['supported_upper'] and s['minutes']<=15 for s in planned)
    assert all(x['title'].startswith('坐姿') for s in planned for x in s['steps'])
    d=client.put('/api/period',json={'revision':d['revision'],'mode':'ease','days':10}).json()
    assert all(s['kind']=='strength' and s['minutes']==10 for s in d['state']['plan']['sessions'] if s['id'] in {x['id'] for x in planned})
    d=client.post('/api/plan/next',json={'revision':d['revision']}).json()
    preview=client.get('/api/proposals/'+d['result']['proposal_id']).json()['plan']
    assert sum(s['kind']=='strength' and s['supported_upper'] for s in preview['sessions'])==2
    p['limitations']='膝盖疼，医嘱暂缓抗阻训练'
    d=client.put('/api/profile',json={'revision':d['revision'],'profile':p}).json()
    assert not any(s['kind']=='strength' and s['date']>=d['today'] for s in d['state']['plan']['sessions'])


def test_migration_repairs_current_and_queued_cardio_only_plans(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,5))
    d=login(client)
    p=engine.sample_profile()
    p.update(level='regular',goal='muscle',likes=['strength','walking'],days=[0,2,4,6],minutes=40)
    old_p={**p,'goal':'habit','likes':['walking'],'support_training':False}
    st=engine.empty()
    st.update(profile=p,risk=engine.health_risk(p),plan=engine.generate(old_p,date(2026,11,2)),
              upcoming=engine.generate(old_p,date(2026,11,9)))
    st['plan']['policy']=st['upcoming']['policy']='targeted-v4'
    past=copy.deepcopy(st['plan']['sessions'][0])
    st['records']=[{'session_id':past['id'],'date':past['date'],'status':'completed','minutes':20,'effort':'okay'}]
    with db.transaction() as c:
        db.save(c,d['user']['id'],st,d['revision'])
    result=client.get('/api/state').json()['state']
    assert result['plan']['sessions'][0]==past and result['records']==st['records']
    assert sum(s['kind']=='strength' and s['date']>='2026-11-05' for s in result['plan']['sessions'])==2
    assert sum(s['kind']=='strength' for s in result['upcoming']['sessions'])==2


def test_cross_week_recovery_keeps_a_and_b_and_repairs_missing_followup(monkeypatch):
    day=date(2026,11,5)
    monkeypatch.setattr(engine,'today',lambda state=None:day)
    p=engine.sample_profile()
    p.update(goal='muscle',level='regular',likes=['strength','walking'],equipment=['dumbbell'],
             days=[0,1,2,4,6],minutes=40)
    old_p={**p,'goal':'habit','support_training':False,'likes':['walking']}
    state=engine.empty()
    state.update(profile=p,risk=engine.health_risk(p),plan=engine.generate(old_p,date(2026,11,2)))
    state['plan']['policy']='targeted-v4'
    assert engine.activate_due(state)
    assert state['upcoming'] is not None
    strength=[s for s in state['upcoming']['sessions'] if s['kind']=='strength']
    assert len(strength)==2 and {s['variant'] for s in strength}=={0,1}
    assert any(any(x['title']=='哑铃杯式深蹲' for x in s['steps']) for s in strength)


def test_self_record_heart_rate_edit_and_garden_rewards(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,5))
    d=client.post('/api/demo',json={'mode':'empty'}).json()
    body={'date':d['today'],'status':'completed','minutes':24,'avg_heart_rate':126,
          'activity':'午后快走','activity_kind':'walk','revision':d['revision']}
    response=client.post('/api/records',json=body)
    assert response.status_code==200,response.text
    d=response.json()
    record=d['state']['records'][0]
    assert record['avg_heart_rate']==126
    assert d['growth']['week']['analysis']['heart_rate_count']==1
    assert d['growth']['garden']['total']==1
    body.update(revision=d['revision'],record_id=record['id'],activity='哑铃练习',activity_kind='strength',
                avg_heart_rate=112,status='partial')
    d=client.post('/api/records',json=body).json()
    assert len(d['state']['records'])==1 and d['state']['records'][0]['avg_heart_rate']==112
    assert d['growth']['garden']['total']==1
    plots={p['kind']:p['count'] for p in d['growth']['garden']['plots']}
    assert plots['strength']==1 and plots['walk']==0
    assert d['growth']['week']['analysis']['partial']==1
    assert any('部分完成' in x for x in d['growth']['week']['praise'])
    body.update(revision=d['revision'],status='rest',minutes=0)
    assert client.post('/api/records',json=body).status_code==422
    body.update(status='partial',minutes=24,avg_heart_rate=312)
    assert client.post('/api/records',json=body).status_code==422
    body.update(avg_heart_rate=None,status='rest',minutes=0)
    d=client.post('/api/records',json=body).json()
    assert d['growth']['garden']['total']==0
    assert any('主动记录' in x for x in d['growth']['week']['praise'])


def test_live_week_and_month_reports_have_real_breakdowns_and_equal_windows(client,monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,5))
    d=client.post('/api/demo',json={'mode':'empty'}).json()
    rows=[('2026-11-02','walk',20,'completed'),('2026-11-05','badminton',35,'partial'),
          ('2026-10-29','walk',10,'completed'),('2026-10-31','bike',60,'completed'),
          ('2026-10-03','strength',15,'completed')]
    for day,kind,n,status in rows:
        d=client.post('/api/records',json={'revision':d['revision'],'date':day,'status':status,'minutes':n,
                                          'activity_kind':kind}).json()
    week=d['growth']['week']
    assert week['analysis']['minutes']==55 and week['analysis']['active_days']==2
    assert [(x['kind'],x['minutes']) for x in week['analysis']['breakdown']]==[('badminton',35),('walk',20)]
    assert week['analysis']['comparison']['days']==4 and week['analysis']['comparison']['previous_minutes']==10
    assert 'records' not in week['stats']
    month=d['growth']['month']
    assert month['analysis']['comparison']['days']==5 and month['analysis']['comparison']['previous_minutes']==15
    assert month['praise'] and month['next']
    assert d['growth']['garden']['variety']==4 and d['growth']['garden']['total']==5


def test_average_heart_rate_not_shared_with_coach(client,monkeypatch):
    d=demo(client)
    d=client.post('/api/records',json={'revision':d['revision'],'date':d['today'],'status':'completed',
                                      'minutes':25,'avg_heart_rate':136,'activity_kind':'walk'}).json()
    monkeypatch.setattr(config,'API_KEY','test-model')
    with patch.object(services,'model_json',return_value={'intent':'question','reply':'根据记录保持节奏。'}) as model:
        r=client.post('/api/coach',json={'revision':d['revision'],'text':'接下来练什么'})
        assert r.status_code==200
    assert 'avg_heart_rate' not in json.dumps(model.call_args.args[0])


def test_advanced_programme_calibrates_volume_time_and_coverage():
    p=engine.sample_profile()
    p.update(level='advanced',goal='muscle',training_months=36,routine_detail='每周三次抗阻，哑铃卧推和划船各三组',
             days=[0,2,4],likes=['strength'],equipment=['dumbbell'],minutes=60)
    plan=engine.generate(p,date(2026,11,2))
    active=[s for s in plan['sessions'] if s['kind']=='strength']
    assert len(active)==3
    assert {s['program'] for s in active}=={'fullbody-abc'}
    for s in active:
        assert len(s['steps'])>=6
        assert 10<=sum(x['minutes'] for x in s['steps'])<=60
        assert s['minutes']==sum(x['minutes'] for x in s['steps'])
        for x in s['steps']:
            if x.get('sets'):
                assert x['minutes']*60>=x['estimated_seconds']
                assert x['rir']==2 and x['rep_max']>=x['reps']
    muscles={m for s in active for x in s['steps'] for m in x.get('muscles',[])}
    assert {'back','chest','hamstrings','quadriceps','shoulders'}<=muscles
    assert plan['programming']['missing']==[]
    assert not plan['generator']['model_generated']
    p.update(minutes=10)
    short=engine.generate(p,date(2026,11,2))
    assert all(x['minutes']*60>=x['estimated_seconds'] for s in short['sessions'] for x in s['steps'] if x.get('sets'))


def test_negated_local_injury_is_not_a_restriction():
    p=engine.sample_profile()
    p.update(level='advanced',goal='muscle',limitations='目前无膝伤，腰背无不适')
    assert engine.health_risk(p)['level']=='none'
    assert engine.resistance_route(p)=='standard'
    p['limitations']='无膝伤，但现在头晕'
    assert engine.health_risk(p)['level']=='hold'
    p['limitations']='目前无膝伤，但腰背疼痛'
    assert engine.health_risk(p)['level']=='caution'


def test_quality_rejects_wrong_goal_and_impossible_time():
    from app.plan_quality import evaluate
    p=engine.sample_profile()
    p.update(goal='muscle',level='advanced',days=[0,2,4],minutes=60,equipment=['dumbbell'],
             training_months=36,routine_detail='三年抗阻，每周三练，恢复正常')
    plan=engine.generate(p,date(2026,11,9))
    assert not evaluate(plan,p)['hard_failures']
    wrong=copy.deepcopy(plan)
    wrong['sessions']=[engine.make_session(date.fromisoformat(s['date']),'walk',20,p) if s['kind']=='strength' else s for s in wrong['sessions']]
    assert evaluate(wrong,p)['status']=='blocked'
    broken=copy.deepcopy(plan);broken['sessions'][0]['steps'][1]['minutes']=1
    assert evaluate(broken,p)['hard_failures']


def test_postural_tightness_preserves_existing_training_but_not_pain_or_restrictions():
    p=engine.sample_profile()
    p.update(goal='bone',level='regular',days=[1,2,3,4,6],minutes=30,
             likes=['strength','running'],equipment=['dumbbell','treadmill','bodyweight'],
             limitations='久坐，竖脊肌、腰方肌比较紧张')
    assert engine.health_risk(p)['level']=='none'
    plan=engine.generate(p,date(2026,11,9))
    strength=[s for s in plan['sessions'] if s['kind']=='strength']
    assert len(strength)==2 and all(s.get('program') for s in strength)
    assert all(s['minutes']<=30 for s in strength)
    assert plan['knowledge']['version']==engine.training_knowledge.VERSION
    assert 'acsm_resistance' in {x['id'] for x in plan['sources']}
    for danger in ('，有疼痛','，医嘱限制负重','，伴头晕'):
        p['limitations']='久坐，腰背紧张'+danger
        assert engine.health_risk(p)['level']!='none'


def test_regenerate_keeps_profile_actual_records_and_past_sessions(monkeypatch):
    monkeypatch.setattr(engine,'today',lambda state=None:date(2026,11,7))
    st=engine.demo();p=copy.deepcopy(st['profile']);records=copy.deepcopy(st['records'])
    old=copy.deepcopy(st['plan'])
    engine.regenerate_current_and_next(st,'测试重新规划')
    assert st['profile']==p and st['records']==records
    for s in st['plan']['sessions']:
        if s['date']<'2026-11-07':
            assert s==next(x for x in old['sessions'] if x['date']==s['date'])
    assert st['upcoming']['week']=='2026-11-09'


def test_existing_easy_aerobic_routine_does_not_become_unrequested_intervals():
    p=engine.sample_profile()
    p.update(goal='bone',level='regular',days=[1,2,3,4,6],minutes=30,usual_minutes=30,
             likes=['strength','running'],equipment=['dumbbell','treadmill'],
             current='每周上下肢力量和二区心率慢跑')
    plan=engine.generate(p,date(2026,11,9))
    runs=[s for s in plan['sessions'] if s['kind']=='run']
    assert runs and all('节奏段与恢复段' not in {x['title'] for x in s['steps']} for s in runs)
    assert plan['quality']['goal_fulfillment']=='baseline_unverified'


def test_open_profile_preserves_old_plan_then_launches_owner_scoped_job(client,monkeypatch):
    from app import planning_jobs
    d=demo(client);old=copy.deepcopy(d['state']['plan'])
    p=d['state']['profile']
    p.update(goal='performance',goal_detail='力量和专项体能同时提高',level='competitive',
             training_background='多年分化训练',days=list(range(7)),minutes=120,
             place='gym',equipment=['barbell','rack','bench','cable','kettlebell','other'],
             equipment_detail='完整健身房，另有雪橇',likes=['rowing','hiit','other'],activity_detail='综合体能')
    r=client.put('/api/profile',json={'revision':d['revision'],'profile':p,'ai_first':True})
    assert r.status_code==200,r.text
    d=r.json()
    assert d['state']['plan']['sessions']==old['sessions']
    monkeypatch.setattr(config,'API_KEY','test')
    with patch.object(planning_jobs.POOL,'submit') as submit:
        response=client.post('/api/planning',json={'revision':d['revision']})
        assert response.status_code==200,response.text
        jid=response.json()['job_id']
        assert submit.call_count==1
        assert client.post('/api/planning',json={'revision':d['revision']}).json()['job_id']==jid
        assert submit.call_count==1
    status=client.get('/api/planning/'+jid).json()
    assert status['status']=='queued'
    assert status['estimate']['max_seconds']>=status['estimate']['min_seconds']>0
    assert status['elapsed_seconds']>=0 and 'artifacts' not in status
    preview=client.get('/api/planning/estimate')
    assert preview.status_code==200 and preview.json()['basis']=='preliminary'
    with TestClient(app) as other:
        demo(other)
        assert other.get('/api/planning/'+jid).status_code==404
    assert client.get('/api/state').json()['state']['plan']['sessions']==old['sessions']
