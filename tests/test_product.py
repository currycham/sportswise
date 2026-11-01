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


def test_record_upsert_and_discomfort(client):
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


def test_brief_attempt_is_partial_and_never_full_completion(client):
    d=demo(client);s=pending(d)
    body={'revision':d['revision'],'session_id':s['id'],'date':s['date'],'status':'partial','minutes':0,'effort':'okay'}
    r=client.post('/api/records',json=body)
    assert r.status_code==200,r.text
    d=r.json()
    assert d['stats']['full']==2
    assert d['stats']['minutes']==44
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
