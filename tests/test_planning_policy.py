import copy,json,sqlite3
from unittest.mock import patch
import pytest
from app import config,db,engine,planning_policy,planning_jobs,services

@pytest.fixture
def storage(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DB_PATH',tmp_path/'routing.db')
    monkeypatch.setattr(config,'PLANNER_MODEL','deepseek-flash')
    monkeypatch.setattr(config,'PLANNER_REVIEW_MODEL','deepseek-flash')
    monkeypatch.setattr(config,'PLANNER_EXPERT_MODEL','deepseek-v4-pro')
    monkeypatch.setattr(config,'PLANNER_EFFORT','low')
    monkeypatch.setattr(config,'PLANNER_AUTHOR_EFFORT','low')
    db.init()


def test_routing_uses_light_models_for_simple_goals_and_experts_for_complex_plans(storage):
    p=engine.sample_profile();p.update(level='beginner',goal='habit',limitations='')
    assert planning_policy.route(p,'plan_generate')['model']=='deepseek-flash'
    assert planning_policy.route(p,'plan_review')['model']=='deepseek-flash'
    p['level']='advanced'
    assert planning_policy.route(p,'plan_generate')['model']=='deepseek-v4-pro'
    assert planning_policy.route(p,'plan_review')=={'model':'deepseek-v4-pro','effort':'low','expert':True}
    assert planning_policy.route(p,'plan_revise',1)['effort']=='low'
    assert planning_policy.route(p,'plan_revise',2)['effort']=='high'


def test_actual_call_telemetry_and_model_specific_budget(storage,monkeypatch):
    responses=[];metrics=[]
    def post(url,**kw):
        responses.append(kw['json'])
        class Reply:
            def raise_for_status(self):pass
            def json(self):return {'usage':{'prompt_tokens':100,'completion_tokens':200},'choices':[{'finish_reason':'stop','message':{'content':'{"valid":true}','reasoning_content':'DO_NOT_STORE'}}]}
        return Reply()
    monkeypatch.setattr(services.httpx,'post',post)
    assert services.planning_model_json([], 'synthetic','plan_review',model='deepseek-flash',effort='low',metrics=metrics.append)=={'valid':True}
    assert responses[0]['reasoning_effort']=='low'
    assert metrics[0]['status']=='ok' and metrics[0]['completion_tokens']==200
    assert 'DO_NOT_STORE' not in json.dumps(metrics)
    with db.connect() as c:
        row=c.execute('SELECT * FROM llm_usage').fetchone()
        assert row['model']=='deepseek-flash' and row['effort']=='low' and row['status']=='ok'
        assert row['cost']==pytest.approx((100*config.PLANNER_PRICE_IN+200*config.PLANNER_PRICE_OUT)/1e6)


def test_truncated_call_is_measured_as_failure(storage,monkeypatch):
    class Reply:
        def raise_for_status(self):pass
        def json(self):return {'usage':{'prompt_tokens':100,'completion_tokens':32768},'choices':[{'finish_reason':'length'}]}
    monkeypatch.setattr(services.httpx,'post',lambda *a,**kw:Reply())
    with pytest.raises(ValueError,match='不完整'):services.planning_model_json([],'synthetic','plan_review')
    with db.connect() as c:assert c.execute('SELECT status FROM llm_usage').fetchone()[0]=='truncated'


def test_usage_migration_preserves_existing_budget(storage):
    with db.connect() as c:c.execute("INSERT INTO llm_usage(task,actor,cost) VALUES ('old','actor',2.5)")
    db.init();db.init()
    with db.connect() as c:assert c.execute('SELECT sum(cost) FROM llm_usage').fetchone()[0]==2.5


def test_estimate_uses_matching_measurements_and_includes_queue(storage):
    p=engine.sample_profile();p.update(level='beginner',goal='habit',limitations='')
    cold=planning_policy.estimate(p)
    assert cold['basis']=='preliminary' and cold['max_seconds']>=cold['min_seconds']
    for task in ('plan_generate','plan_review'):
        with db.connect() as c:
            for duration in (20000,30000,40000):c.execute("INSERT INTO llm_usage(task,model,effort,duration_ms,status) VALUES (?,?,?,?,'ok')",(task,'deepseek-flash',planning_policy.route(p,task)['effort'],duration))
    measured=planning_policy.estimate(p);queued=planning_policy.estimate(p,pending=2)
    assert measured['basis']=='history' and measured['sample_count']==3
    assert queued['queue_included'] and queued['max_seconds']==2*measured['max_seconds']
    assert measured['max_seconds']<cold['max_seconds']


def test_poll_elapsed_does_not_reset_estimate_or_expose_artifacts(storage,monkeypatch):
    monkeypatch.setattr(planning_jobs.time,'time',lambda:200)
    row={'id':'j','status':'running','stage':'reviewing','message':'review','created_at':100,'updated_at':140,
         'result':json.dumps({'timing':{'estimate':{'min_seconds':30,'max_seconds':80}},'artifacts':[{'secret':'raw'}]})}
    first=planning_jobs.public_job(row);second=planning_jobs.public_job(row)
    assert first['elapsed_seconds']==100 and first['over_estimate']
    assert second['estimate']==first['estimate'] and 'artifacts' not in first
    row['status']='done'
    assert planning_jobs.public_job(row)['elapsed_seconds']==40


def test_job_persists_actual_model_roles_without_replacing_plan(storage,monkeypatch):
    state=engine.empty();state['profile']=engine.sample_profile();before=copy.deepcopy(state)
    with db.connect() as c:
        c.execute('INSERT INTO users(id,email,state) VALUES (?,?,?)',('synthetic','fake@example.invalid',json.dumps(state)))
        c.execute('INSERT INTO planning_jobs VALUES (?,?,?,?,?,?,?,?)',('job','synthetic','queued','queued','queued',None,100,100))
    def call(messages,actor,task,**kw):
        kw['metrics']({'task':task,'model':kw['model'],'effort':kw['effort'],'duration_ms':100,'status':'ok','prompt_tokens':1,'completion_tokens':1,'estimated_cost_yuan':.0001})
        return {}
    def pipeline(profile,snapshot,model_call,progress):
        model_call([],'plan_generate');model_call([],'plan_review')
        return {'ok':True,'plan':{'generator':{}},'review_trace':[{'stage':'independent_review','passed':True}]}
    monkeypatch.setattr(services,'planning_model_json',call)
    from app import ai_planning
    monkeypatch.setattr(ai_planning,'pipeline',pipeline)
    planning_jobs.run('job','synthetic',state)
    with db.connect() as c:
        job=c.execute('SELECT * FROM planning_jobs').fetchone();assert job['status']=='done'
        proposal=json.loads(c.execute('SELECT payload FROM proposals').fetchone()[0])
        assert proposal['plan']['generator']['model']=='deepseek-flash'
        assert 'review_model' in proposal['plan']['generator']
        assert db.decode(c.execute('SELECT * FROM users').fetchone())==before
