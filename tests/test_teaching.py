import copy,json
from datetime import date,timedelta
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import config,db,engine,coaching,services,planning_jobs,ai_planning
from app.main import app

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'teaching.db')
    monkeypatch.setattr(config,'API_KEY','');monkeypatch.setattr(config,'SMTP_HOST','')
    monkeypatch.setattr(config,'ENV','development')
    with patch.object(services,'worker',lambda stop:None):
        with TestClient(app) as c:yield c


def scenario(c):
    data=c.post('/api/demo').json();uid=data['user']['id']
    state=db.decode(db.read_user(uid));p=state['profile']
    p.update(goal='muscle',level='regular',routine_detail='每周三次规范力量训练两年',days=[0,2,4],minutes=30,limitations='',planning_style='preserve_structure')
    start=engine.monday(engine.today(state))+timedelta(days=7)
    draft={'week':str(start),'rationale':'保持已有规律，在恢复间隔中练推拉与下肢。','phase':'校准','scope':'personalized',
           'source_ids':['ace_ift'],'programming':{'progression':'两次达到上限且恢复良好，再加小幅负荷','deload':'恢复差先少一组','review':'记录重量与余力'},
           'sessions':[{'date':str(start+timedelta(days=i)),'kind':'rest','title':'恢复','minutes':0,'purpose':'恢复','intensity':'休息','steps':[]} for i in range(7)]}
    for day,muscle in [(0,'chest'),(2,'quadriceps'),(4,'back')]:
        draft['sessions'][day]={'date':str(start+timedelta(days=day)),'kind':'strength','title':'力量课','minutes':30,'purpose':'训练推拉或下肢能力',
         'intensity':'RIR2','rationale':'工作组与可用时间匹配，隔日恢复。','progression_rule':'两次完成上限且次日恢复良好再最小增重',
         'steps':[{'title':'热身','kind':'warmup','minutes':5,'detail':'逐渐进入动作'},
                  {'title':'目标力量动作','minutes':20,'sets':2,'reps':8,'rest_seconds':60,'rir':2,'intensity':'RIR2','detail':'控制动作，不憋气','benefit':'训练主要肌群','caution':'新发疼痛时停止','muscle_groups':[muscle]},
                  {'title':'收尾','kind':'cooldown','minutes':5,'detail':'恢复呼吸'}]}
    plan=ai_planning.validate(draft,p);plan['quality']={'status':'reviewed','score':90}
    plan['review_trace']=[{'stage':'independent_review','passed':True,'review':{'score':90,'must_fix':[]}}]
    state['plan']=None;state['upcoming']=plan;state['records']=[];state['history']=[]
    with db.connect() as con:con.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(state,ensure_ascii=False),uid))
    return c.get('/api/state').json(),state,plan


def test_discussing_why_keeps_plan_and_does_not_create_a_proposal(client):
    data,before,plan=scenario(client)
    result=client.post('/api/coach',json={'revision':data['revision'],'text':'为什么这堂课这样安排？','session_id':plan['sessions'][0]['id']})
    assert result.status_code==200,result.text
    out=result.json();assert out['result']['proposal_id'] is None
    assert '工作组与可用时间匹配' in out['result']['reply']
    assert db.decode(db.read_user(data['user']['id']))['upcoming']==before['upcoming']
    with db.connect() as con:assert con.execute('SELECT count(*) FROM proposals').fetchone()[0]==0


def test_discussion_saves_a_request_and_correct_session_not_a_plan(client,monkeypatch):
    data,before,plan=scenario(client)
    monkeypatch.setattr(config,'API_KEY','test')
    def answer(messages,*args):
        text=json.dumps(messages,ensure_ascii=False)
        assert 'avg_heart_rate' not in text and 'secret-sex' not in text
        assert 'RIR2' in text
        return {'reply':'换动作时保留水平推目标；可以用熟悉的替代。','can_plan':True,'plan_request':'保留其它内容，把指定动作替换为同目标熟悉动作；原因为偏好。'}
    with patch.object(services,'model_json',side_effect=answer):
        out=client.post('/api/coach',json={'revision':data['revision'],'text':'我不想做这个，想换一个','session_id':plan['sessions'][0]['id']}).json()
    assert out['result']['can_plan'] and out['state']['coach_plan_session_id']==plan['sessions'][0]['id']
    assert out['state']['upcoming']['id']==plan['id']
    assert out['state']['coach_plan_request'].startswith('保留其它')


def test_existing_draft_can_be_discussed_then_adopted_without_stale_chat_revision(client):
    data,state,plan=scenario(client);uid=data['user']['id'];state['upcoming']=None
    with db.connect() as c:
        c.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(state),uid))
        c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',('draft',uid,data['revision'],json.dumps({'plan':plan,'summary':'草案'})))
    out=client.post('/api/coach',json={'revision':data['revision'],'text':'为什么这堂课要留余力？','proposal_id':'draft','session_id':plan['sessions'][0]['id']})
    assert out.status_code==200,out.text
    response=client.post('/api/proposals/draft/apply',json={'revision':out.json()['revision']})
    assert response.status_code==200,response.text
    assert response.json()['state']['upcoming']['id']==plan['id']


def test_training_change_still_invalidates_a_draft(client):
    data,state,plan=scenario(client);uid=data['user']['id'];state['upcoming']=None
    with db.connect() as c:
        c.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(state),uid))
        c.execute('INSERT INTO proposals(id,user_id,revision,payload) VALUES (?,?,?,?)',('draft',uid,data['revision'],json.dumps({'plan':plan,'source_signature':planning_jobs.signature(state)})))
    out=client.post('/api/records',json={'revision':data['revision'],'date':data['today'],'status':'completed','minutes':15,'activity':'自主步行','activity_kind':'walk'}).json()
    response=client.post('/api/proposals/draft/apply',json={'revision':out['revision']})
    assert response.status_code==422


def test_targeted_generation_keeps_the_selected_week_and_draft(client,monkeypatch):
    data,state,plan=scenario(client)
    monkeypatch.setattr(engine,'today',lambda state=None:date.fromisoformat(plan['week'])+timedelta(days=1))
    monkeypatch.setattr(config,'API_KEY','test')
    with patch.object(planning_jobs.POOL,'submit') as submit:
        out=client.post('/api/planning',json={'revision':data['revision'],'session_id':plan['sessions'][2]['id'],'request_detail':'保留结构，只换这堂课的一个动作'})
        assert out.status_code==200,out.text
        snapshot=submit.call_args.args[3]
        assert snapshot['target_week']==plan['week']
        assert snapshot['seed_draft']['sessions'][2]['date']==plan['sessions'][2]['date']
        assert state['upcoming']==plan


def test_only_explicit_female_profile_offers_period_activation(client):
    data=client.post('/api/demo').json();p=data['state']['profile'];p['sex']='male'
    data=client.put('/api/profile',json={'revision':data['revision'],'profile':p,'ai_first':True}).json()
    denied=client.put('/api/period',json={'revision':data['revision'],'mode':'ease','days':2})
    assert denied.status_code==422
    p['sex']='female';data=client.put('/api/profile',json={'revision':data['revision'],'profile':p,'ai_first':True}).json()
    enabled=client.put('/api/period',json={'revision':data['revision'],'mode':'ease','days':2})
    assert enabled.status_code==200
    p['sex']='male';data=client.put('/api/profile',json={'revision':enabled.json()['revision'],'profile':p,'ai_first':True}).json()
    assert data['state']['period'] is None


def test_discussion_can_withdraw_a_previous_change_request(client,monkeypatch):
    data,state,plan=scenario(client)
    with db.connect() as con:
        state['coach_plan_request']='把深蹲换成弓步'
        state['coach_plan_session_id']=plan['sessions'][0]['id']
        con.execute('UPDATE users SET state=? WHERE id=?',(json.dumps(state,ensure_ascii=False),data['user']['id']))
    monkeypatch.setattr(coaching,'discuss',lambda *args:{'reply':'保持现有安排，先解释逻辑。','can_plan':False,'plan_request':'','mode':'test'})
    out=client.post('/api/coach',json={'revision':data['revision'],'text':'先不修改，解释一下即可','session_id':plan['sessions'][0]['id']})
    assert out.status_code==200,out.text
    assert not out.json()['state'].get('coach_plan_request')
    assert out.json()['state']['upcoming']==plan
    context=coaching.context(state,plan['sessions'][0]['id'])
    assert context['selected_session']==context['plan']['sessions'][0]['id']


def test_teaching_contract_requires_personal_decisions_and_feedback_conditions(client):
    _,state,plan=scenario(client)
    raw=ai_planning._draft_data(plan)
    assert ai_planning.teaching_findings(raw)
    raw['learning_focus']=['用余力记录负荷']
    raw['decisions']=[{'topic':x,'reason':'依据两年基线与三日时间','evidence':'ACE IFT与个人训练记录','tradeoff':'先保证核心工作组','change_signal':'两次完成上限且恢复良好'} for x in ('训练量','恢复')]
    assert ai_planning.teaching_findings(raw)==[]


def test_sex_and_heart_rate_are_not_model_inputs(client):
    _,state,plan=scenario(client)
    state['profile']['sex']='secret-sex'
    state['records']=[{'date':'2026-11-08','minutes':20,'avg_heart_rate':142}]
    state['period']={'mode':'ease'}
    serialized=json.dumps(coaching.context(state),ensure_ascii=False)
    assert 'secret-sex' not in serialized and 'avg_heart_rate' not in serialized and '"period":' not in serialized


def test_high_score_cannot_rewrite_recorded_sessions(client,monkeypatch):
    _,state,plan=scenario(client)
    state.update(plan=plan,upcoming=None,planning_today=str(date.fromisoformat(plan['week'])+timedelta(days=1)),planning_week=plan['week'])
    state['records']=[{'session_id':plan['sessions'][0]['id'],'date':plan['sessions'][0]['date'],'minutes':30,'status':'completed'}]
    raw=ai_planning._draft_data(plan);raw['sessions'][0]['title']='篡改已发生训练'
    monkeypatch.setattr(ai_planning,'MAX_REVISIONS',0)
    result=ai_planning.pipeline(state['profile'],state,lambda messages,task: {'score':99,'passed':True,'must_fix':[],'issues':[]} if task=='plan_review' else raw,None)
    assert not result['ok']
    assert any('不可改写' in issue for x in result['review_trace'] if x['stage']=='structure' for issue in x['issues'])


def test_healthy_training_goal_cannot_be_all_rest_calibration(client):
    _,state,plan=scenario(client);raw=ai_planning._draft_data(plan)
    raw.update(scope='calibration',assumptions=['工作重量尚未知'],questions=['最近训练重量是多少？'])
    for s in raw['sessions']:s.update(kind='rest',minutes=0,steps=[])
    with pytest.raises(ai_planning.PlanValidationError,match='全周休息'):ai_planning.validate(raw,state['profile'])


def test_historical_dose_does_not_have_to_fit_new_availability(client):
    _,state,plan=scenario(client)
    state.update(plan=plan,upcoming=None)
    locked=ai_planning.locked_sessions(state,plan['week'],str(date.fromisoformat(plan['week'])+timedelta(days=1)))
    profile=copy.deepcopy(state['profile']);profile['days']=[2,4];profile['minutes']=20
    raw=ai_planning._draft_data(plan)
    for s in raw['sessions'][1:]:
        if s['kind']!='rest':
            s['minutes']=20;s['steps'][1]['minutes']=10
    normalized=ai_planning.validate(raw,profile,locked=locked)
    assert normalized['sessions'][0]['minutes']==30
    raw['sessions'][2]['minutes']=30;raw['sessions'][2]['steps'][1]['minutes']=20
    with pytest.raises(ai_planning.PlanValidationError,match='单次时间预算'):ai_planning.validate(raw,profile,locked=locked)


def test_sport_audit_tempo_and_explicit_absence_regressions(client):
    _,state,plan=scenario(client)
    profile=copy.deepcopy(state['profile']);profile['limitations']='目前无疼痛或明确运动限制'
    assert engine.health_risk(profile)['level']=='none'
    profile['limitations']+='，但今天头晕'
    assert engine.health_risk(profile)['level']=='hold'
    assert ai_planning._tempo_lower_bound('2-1-1')==4
    assert ai_planning._tempo_lower_bound('3秒下、1秒上')==4
    assert ai_planning._tempo_lower_bound('20-30次')==0
    assert ai_planning._quality_stop('速度下降即停，不追求疲劳')
    raw=ai_planning._draft_data(plan);step=raw['sessions'][0]['steps'][1]
    step.update(tempo='2-1-1',tempo_seconds=3,sets=3,reps=15,minutes=4)
    with pytest.raises(ai_planning.PlanValidationError,match='装不进'):ai_planning.validate(raw,state['profile'])
