"""Offline checks for the real model orchestration contract; no provider calls."""
import copy
import json
from datetime import date, timedelta

import pytest

from app import ai_planning, engine


@pytest.fixture
def inputs():
    profile={**engine.sample_profile(),'goal':'muscle','level':'regular','days':[0,1],
             'minutes':30,'routine_detail':'熟悉抗阻动作，每周两次，按余力与恢复调整'}
    start=date(2026,11,16)
    draft={'week':str(start),'phase':'个性化校准','scope':'personalized','rationale':'与已有训练、器械和时间匹配',
           'assumptions':[],'questions':[],'source_ids':['ace_ift'],
           'programming':{'progression':'完成上限并保留余力，恢复良好时再选小幅增重',
                          'deload':'恢复变差先少一组','review':'对比同动作实际完成与恢复'},
           'sessions':[{'date':str(start+timedelta(days=i)),'kind':'rest','title':'恢复休息',
                        'purpose':'保留恢复时间','minutes':0,'intensity':'休息','steps':[]} for i in range(7)]}
    for i,muscle in ((0,'chest'),(1,'quadriceps')):
        draft['sessions'][i]={'date':str(start+timedelta(days=i)),'kind':'strength',
            'title':'上肢抗阻' if i==0 else '下肢抗阻','minutes':30,'purpose':'练习目标动作','intensity':'留2次余力',
            'steps':[{'title':'专项热身','kind':'warmup','minutes':5,'detail':'先轻活动，再逐渐进入动作'},
                     {'title':'俯卧撑' if i==0 else '徒手深蹲','kind':'move','minutes':20,
                      'detail':'稳定控制动作','sets':2,'reps':8,'rep_max':10,'rest_seconds':60,'rir':2,
                      'intensity':'留2次余力','benefit':'训练目标肌群','caution':'疼痛时停止',
                      'muscle_groups':[muscle],'equipment_required':['bodyweight'],
                      'alternatives':['更容易且符合相同目标的动作']},
                     {'title':'放松记录','kind':'cooldown','minutes':5,'detail':'恢复呼吸，记录感受'}]}
    state={'planning_today':'2026-11-07','planning_week':str(start),'records':[],'plan':None}
    return profile,state,draft


def approved():
    return {'score':85,'passed':True,'issues':[],'must_fix':[]}


def test_first_pass_uses_separate_author_and_reviewer_contexts(inputs):
    profile,state,draft=inputs
    calls=[];events=[]
    before=copy.deepcopy((profile,state,draft))
    def model(messages,task):
        calls.append((task,messages))
        return approved() if task=='plan_review' else copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,events.append)
    assert result['ok'] and result['plan']['source']=='ai_reviewed'
    assert [c[0] for c in calls]==['plan_generate','plan_review']
    assert '独立' in calls[1][1][0]['content']
    assert json.loads(calls[1][1][1]['content'])['draft']==draft
    assert [e['stage'] for e in events]==['generating','reviewing','complete']
    assert (profile,state,draft)==before
    assert result['plan']['generator']['model_generated'] is True


def test_redundant_total_is_derived_before_review_without_changing_dose(inputs):
    profile,state,draft=inputs
    draft['sessions'][0]['minutes']=29
    original=copy.deepcopy(draft)
    def model(messages,task):
        if task!='plan_review':return copy.deepcopy(draft)
        payload=json.loads(messages[1]['content'])
        assert payload['draft']['sessions'][0]['minutes']==30
        assert payload['draft']['sessions'][0]['steps']==original['sessions'][0]['steps']
        assert payload['normalizations'][0]['before']==29
        return approved()
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and result['plan']['sessions'][0]['minutes']==30
    assert draft==original


def test_truncated_review_does_not_trigger_an_unnecessary_author_rewrite(inputs):
    profile,state,draft=inputs;calls=[]
    def model(messages,task):
        calls.append(task)
        if task=='plan_review':raise ValueError('模型输出不完整，未采用，请稍后重试')
        return copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,None)
    assert not result['ok']
    assert calls==['plan_generate','plan_review']
    assert '输出不完整' in result['error']


def test_normalization_cannot_shrink_work_or_hide_over_budget(inputs):
    profile,state,draft=inputs
    step=draft['sessions'][0]['steps'][1]
    step['minutes']=35
    fixed,changes=ai_planning.normalize_authored(draft,profile)
    assert fixed==draft and not changes
    with pytest.raises(ai_planning.PlanValidationError,match='时长'):
        ai_planning.validate(fixed,profile)


def test_explicit_two_phase_tempo_cannot_hide_work_time(inputs):
    profile,state,draft=inputs
    step=draft['sessions'][0]['steps'][1]
    step.update(tempo='3秒推出，3秒返回',tempo_seconds=3,each_side=True,sets=2,reps=10,
                rep_max=None,minutes=4,rest_seconds=45)
    draft['sessions'][0]['minutes']=14
    fixed,changes=ai_planning.normalize_authored(draft,profile)
    assert fixed['sessions'][0]['steps'][1]['tempo_seconds']==6
    assert any(c['field']=='tempo_seconds' for c in changes)
    with pytest.raises(ai_planning.PlanValidationError,match='装不进'):
        ai_planning.validate(fixed,profile)


def test_secondary_core_support_does_not_equal_direct_core_work(inputs):
    profile,state,draft=inputs
    for s in draft['sessions'][:2]:
        s['steps'][1]['secondary_muscle_groups']=['core']
    assert ai_planning.validate(draft,profile)
    for s in draft['sessions'][:2]:
        s['steps'][1]['muscle_groups'].append('core')
    with pytest.raises(ai_planning.PlanValidationError,match='相邻日'):
        ai_planning.validate(draft,profile)


def test_existing_structure_is_a_baseline_and_power_doses_stay_distinct(inputs):
    profile,state,draft=inputs
    profile.pop('routine_detail')
    profile['training_structure']='每周上下肢分化，已持续两年，按余力选择负荷'
    step=draft['sessions'][0]['steps'][1]
    step.update(block_type='power',stop_rule='动作速度明显下降就停止本组',rir=None)
    normalized=ai_planning.validate(draft,profile)
    doses=next(x for x in normalized['programming']['direct_sets'] if x['muscle']=='chest')
    assert doses['power_sets']==2 and doses['strength_sets']==0


def test_revision_must_be_reviewed_again_and_gets_complete_original_draft(inputs):
    profile,state,draft=inputs
    calls=[]
    def model(messages,task):
        calls.append(task)
        if task=='plan_review':
            return approved() if calls.count('plan_review')==2 else {
                'score':60,'passed':False,'issues':['目标训练量需要解释'], 'must_fix':['补充剂量选择依据']}
        if task=='plan_revise':
            payload=json.loads(messages[1]['content'])
            assert payload['previous_draft']==draft
            assert payload['required_fixes']['independent_review']['must_fix']==['补充剂量选择依据']
        return copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok']
    assert calls==['plan_generate','plan_review','plan_revise','plan_review']
    assert [t['passed'] for t in result['review_trace'] if t['stage']=='independent_review']==[False,True]


@pytest.mark.parametrize('review',[
    {'score':99,'passed':True,'issues':[],'must_fix':['仍有必须修复的问题']},
    {'score':79,'passed':True,'issues':[],'must_fix':[]},
    {'score':99,'passed':False,'issues':[],'must_fix':[]},
    {'score':99,'passed':True,'issues':[{'severity':'critical','message':'目标不符'}],'must_fix':[]},
    {'score':'99','passed':True,'issues':[],'must_fix':[]},
    {'score':99,'passed':'true','issues':[],'must_fix':[]},
])
def test_high_or_string_score_cannot_bypass_requirements(inputs,review):
    profile,state,draft=inputs
    calls=[]
    def model(messages,task):
        calls.append(task)
        return copy.deepcopy(review if task=='plan_review' else draft)
    result=ai_planning.pipeline(profile,state,model,None)
    assert not result['ok'] and result['plan'] is None
    assert calls.count('plan_review')==3 and calls.count('plan_revise')==2
    assert result['error']


def test_adjacent_upper_lower_is_valid_but_same_muscle_blocks_even_score100(inputs):
    profile,state,draft=inputs
    assert ai_planning.validate(draft,profile)['sessions'][1]['kind']=='strength'
    draft['sessions'][1]['steps'][1]['muscle_groups']=['chest']
    with pytest.raises(ai_planning.PlanValidationError,match='主要肌群'):
        ai_planning.validate(draft,profile)
    def model(messages,task):
        return {'score':100,'passed':True,'issues':[],'must_fix':[]} if task=='plan_review' else copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,None)
    assert not result['ok'] and result['plan'] is None
    assert all(not t['passed'] for t in result['review_trace'] if t['stage']=='structure')


def test_cross_week_recovery_is_checked(inputs):
    profile,state,draft=inputs
    sunday={'date':'2026-11-15','kind':'strength','steps':[{'sets':2,'muscles':['chest']}]}
    with pytest.raises(ai_planning.PlanValidationError,match='主要肌群'):
        ai_planning.validate(draft,profile,previous={'sessions':[sunday]})


def test_dose_must_fit_allocated_time_and_can_use_real_profile_budget(inputs):
    profile,state,draft=inputs
    bad=copy.deepcopy(draft)
    bad['sessions'][0]['steps'][1].update(sets=8,reps=15,rep_max=15,each_side=True,rest_seconds=180)
    with pytest.raises(ai_planning.PlanValidationError,match='装不进'):
        ai_planning.validate(bad,profile)
    profile['minutes']=120
    draft['sessions'][0]['minutes']=120
    draft['sessions'][0]['steps'][1]['minutes']=110
    assert ai_planning.validate(draft,profile)['sessions'][0]['minutes']==120


def test_unknown_baseline_needs_honest_scope_and_questions(inputs):
    profile,state,draft=inputs
    profile.pop('routine_detail')
    with pytest.raises(ai_planning.PlanValidationError,match='基线未知'):
        ai_planning.validate(draft,profile)
    draft.update(scope='calibration',assumptions=['近期工作组和余力未知'],questions=['最近每个动作实际重量与次数是多少？'])
    assert ai_planning.validate(draft,profile)['scope']=='calibration'


def test_apply_revalidation_preserves_trace_ids_and_alternative_suggestions(inputs):
    profile,state,draft=inputs
    def model(messages,task):
        return approved() if task=='plan_review' else copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,None)
    plan=result['plan']
    plan['generator']['model']='test-model'
    normalized=ai_planning.validate(plan,profile)
    assert normalized['quality']==plan['quality'] and normalized['review_trace']==plan['review_trace']
    assert normalized['sessions'][0]['id']==plan['sessions'][0]['id']
    assert normalized['sessions'][0]['steps'][1]['suggested_alternatives']==['更容易且符合相同目标的动作']
    assert normalized['generator']['model']=='test-model'


def test_model_failure_is_explicit_and_never_exposes_provider_secret(inputs):
    profile,state,draft=inputs
    def model(messages,task):
        raise RuntimeError('Authorization Bearer PRIVATE-TEST-SECRET')
    result=ai_planning.pipeline(profile,state,model,None)
    assert not result['ok'] and result['plan'] is None
    assert 'PRIVATE-TEST-SECRET' not in json.dumps(result)


def test_wrong_week_or_unavailable_equipment_cannot_be_reviewed_away(inputs):
    profile,state,draft=inputs
    bad=copy.deepcopy(draft)
    bad['sessions'][0]['steps'][1]['equipment_required']=['barbell']
    with pytest.raises(ai_planning.PlanValidationError,match='器械'):
        ai_planning.validate(bad,profile)
    with pytest.raises(ai_planning.PlanValidationError,match='请求周'):
        ai_planning.validate(draft,profile,week='2026-11-23')


def test_twenty_round_emom_uses_rounds_and_not_resistance_rir(inputs):
    profile,state,draft=inputs
    session=draft['sessions'][0]
    session['kind']='run'
    step=session['steps'][1]
    step.update(title='20轮跑走EMOM',block_type='interval',rounds=20,sets=None,reps=None,rep_max=None,
                work_seconds=20,rest_seconds=40,rest_after_last=True,rir=None,muscle_groups=[],
                minutes=20,setup_seconds=0,setup_in_warmup=True,intensity='舒适有氧',dose='每分钟跑20秒、走40秒')
    plan=ai_planning.validate(draft,profile)
    assert plan['sessions'][0]['steps'][1]['rounds']==20
    step['work_seconds']=30
    with pytest.raises(ai_planning.PlanValidationError,match='装不进'):
        ai_planning.validate(draft,profile)


def test_setup_zero_must_be_explicit_and_prepared_in_prior_warmup(inputs):
    profile,state,draft=inputs
    step=draft['sessions'][0]['steps'][1]
    step.update(setup_seconds=0)
    with pytest.raises(ai_planning.PlanValidationError,match='准备时间'):
        ai_planning.validate(draft,profile)
    step['setup_in_warmup']=True
    assert ai_planning.validate(draft,profile)
    # A boolean alone cannot claim a later warmup prepared an earlier main block.
    draft['sessions'][0]['steps'][0],draft['sessions'][0]['steps'][1]=draft['sessions'][0]['steps'][1],draft['sessions'][0]['steps'][0]
    with pytest.raises(ai_planning.PlanValidationError,match='此前热身'):
        ai_planning.validate(draft,profile)


def test_prepared_fourteen_minute_interval_fits_exact_work_and_recovery(inputs):
    profile,state,draft=inputs
    draft['sessions'][0].update(kind='sport',minutes=24)
    step=draft['sessions'][0]['steps'][1]
    step.update(title='三轮4分钟训练加1分钟恢复',block_type='interval',sets=None,rounds=3,reps=None,rep_max=None,
                work_seconds=240,rest_seconds=60,minutes=14,setup_seconds=0,setup_in_warmup=True,rir=None)
    assert ai_planning.validate(draft,profile)['sessions'][0]['minutes']==24
    # Real clock overflow remains a hard failure; no free preparation is inferred.
    step['setup_seconds']=30
    with pytest.raises(ai_planning.PlanValidationError,match='装不进'):
        ai_planning.validate(draft,profile)


def test_power_uses_speed_quality_stop_instead_of_fabricated_rir(inputs):
    profile,state,draft=inputs
    step=draft['sessions'][0]['steps'][1]
    step.update(title='低次数爆发动作',block_type='power',sets=3,reps=3,rep_max=3,tempo_seconds=1,
                rest_seconds=120,rir=None,stop_rule='动作速度明显下降或落地质量变差时立即停止本组')
    assert ai_planning.validate(draft,profile)
    step['stop_rule']='量力而行'
    with pytest.raises(ai_planning.PlanValidationError,match='爆发力动作'):
        ai_planning.validate(draft,profile)


def test_low_effort_and_skill_are_not_automatically_heavy_muscle_exposures(inputs):
    profile,state,draft=inputs
    first=draft['sessions'][0]['steps'][1]
    draft['sessions'][1]['steps'][1]['muscle_groups']=['chest']
    first['rir']=5
    assert ai_planning.validate(draft,profile)
    first.update(block_type='skill',rir=None,intensity='低负荷技术练习',
                 stop_rule='动作轨迹或控制质量变差时停止，保持轻负荷')
    assert ai_planning.validate(draft,profile)
    first['rir']=2
    with pytest.raises(ai_planning.PlanValidationError,match='技术课'):
        ai_planning.validate(draft,profile)


def test_previous_warmup_is_not_counted_as_working_set_overlap(inputs):
    profile,state,draft=inputs
    previous={'sessions':[{'date':'2026-11-15','kind':'strength','steps':[
        {'kind':'warmup','sets':2,'muscle_groups':['chest']},
        {'kind':'move','sets':2,'rir':2,'muscle_groups':['quadriceps']}]}]}
    assert ai_planning.validate(draft,profile,previous=previous)
    previous['sessions'][0]['steps'][1]['muscle_groups']=['chest']
    with pytest.raises(ai_planning.PlanValidationError,match='主要肌群'):
        ai_planning.validate(draft,profile,previous=previous)


def test_heavy_loaded_interval_is_not_an_escape_hatch_for_recovery(inputs):
    profile,state,draft=inputs
    profile['equipment']=['dumbbell']
    draft['sessions'][0]['kind']='sport'
    draft['sessions'][1]['steps'][1]['muscle_groups']=['chest']
    step=draft['sessions'][0]['steps'][1]
    step.update(title='负重混合间歇',block_type='interval',rounds=4,sets=None,reps=None,rep_max=None,
                work_seconds=90,rest_seconds=60,rir=None,rpe=8,equipment_required=['dumbbell'])
    with pytest.raises(ai_planning.PlanValidationError,match='主要肌群'):
        ai_planning.validate(draft,profile)
    step['rpe']=None
    with pytest.raises(ai_planning.PlanValidationError,match='RPE'):
        ai_planning.validate(draft,profile)
    step['rpe']=5
    assert ai_planning.validate(draft,profile)


def test_block_types_do_not_bypass_explicit_no_resistance_instruction(inputs):
    profile,state,draft=inputs
    profile.update(limitations='医生要求暂缓抗阻训练',equipment=['dumbbell'])
    draft.update(scope='restricted',assumptions=['遵循抗阻限制'],questions=['何时可以恢复负重？'])
    draft['sessions'][0]['kind']='sport'
    step=draft['sessions'][0]['steps'][1]
    step.update(block_type='interval',rounds=4,sets=None,reps=None,rep_max=None,
                work_seconds=90,rest_seconds=60,rir=None,rpe=5,equipment_required=['dumbbell'])
    with pytest.raises(ai_planning.PlanValidationError,match='限制冲突'):
        ai_planning.validate(draft,profile)


def test_seed_draft_is_revalidated_and_independently_reviewed_without_new_author(inputs):
    profile,state,draft=inputs
    state['seed_draft']=copy.deepcopy(draft)
    calls=[]
    def model(messages,task):
        calls.append(task)
        assert task=='plan_review'
        return approved()
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and calls==['plan_review']
    assert result['review_trace'][0]['stage']=='seed_reused'
    assert result['review_trace'][1]['stage']=='structure'


def test_seed_old_score_does_not_bypass_new_review_and_failed_seed_is_revised(inputs):
    profile,state,draft=inputs
    normalized=ai_planning.validate(draft,profile)
    normalized['quality']={'score':100,'status':'reviewed'}
    state['seed_draft']=normalized
    calls=[]
    def model(messages,task):
        calls.append(task)
        if task=='plan_review':
            return approved() if calls.count('plan_review')==2 else {
                'score':50,'passed':False,'issues':['旧草案有问题'],'must_fix':['重新调整']}
        assert task=='plan_revise'
        return copy.deepcopy(draft)
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and calls==['plan_review','plan_revise','plan_review']
    assert [t['passed'] for t in result['review_trace'] if t['stage']=='independent_review']==[False,True]


def test_skill_label_cannot_hide_load_against_explicit_restriction(inputs):
    profile,state,draft=inputs
    profile.update(limitations='医嘱暂缓负重训练',equipment=['dumbbell'])
    draft.update(scope='restricted',assumptions=['遵循负重限制'],questions=['何时可恢复？'])
    draft['sessions'][0]['kind']='sport'
    step=draft['sessions'][0]['steps'][1]
    step.update(block_type='skill',sets=None,reps=None,rep_max=None,rir=None,
                equipment_required=['dumbbell'],dose='低负荷练习2分钟',
                intensity='低负荷技术练习',stop_rule='动作控制质量下降时停止')
    with pytest.raises(ai_planning.PlanValidationError,match='限制冲突'):
        ai_planning.validate(draft,profile)


def test_seed_feedback_directly_revises_then_runs_new_review(inputs):
    profile,state,draft=inputs
    state['seed_draft']=copy.deepcopy(draft)
    state['seed_feedback']={'structural_findings':['计时与标题须一致'],
                            'independent_review':{'score':89,'passed':False,
                            'issues':['连续重刺激需要调整'],'must_fix':['修正计时及恢复']}}
    calls=[]
    def model(messages,task):
        calls.append(task)
        payload=json.loads(messages[1]['content'])
        if task=='plan_revise':
            assert payload['previous_draft']==draft
            assert payload['required_fixes']==state['seed_feedback']
            return copy.deepcopy(draft)
        assert task=='plan_review'
        assert payload['draft']==draft
        return approved()
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and calls==['plan_revise','plan_review']
    assert result['plan']['quality']['score']==85
    assert len([x for x in result['review_trace'] if x['stage']=='independent_review'])==1


def test_rest_day_may_omit_default_empty_steps(inputs):
    profile,state,draft=inputs
    draft['sessions'][-1].pop('steps')
    candidate,changes=ai_planning.normalize_authored(draft,profile)
    plan=ai_planning.validate(candidate,profile)
    assert plan['sessions'][-1]['steps']==[]


def test_timed_hold_requires_effort_and_a_posture_stop(inputs):
    profile,state,draft=inputs;step=draft['sessions'][0]['steps'][1]
    step.update(reps=None,rep_max=None,work_seconds=30,rir=None,rpe=7,stop_rule='姿势质量下降立即停止',intensity='RPE7，不憋气')
    assert ai_planning.validate(draft,profile)
    step['stop_rule']=''
    with pytest.raises(ai_planning.PlanValidationError,match='RIR'):ai_planning.validate(draft,profile)


def test_structured_effort_does_not_need_a_model_rewrite_for_duplicate_text(inputs):
    profile,state,draft=inputs
    draft['sessions'][0]['steps'][1].pop('intensity')
    before=copy.deepcopy(draft)
    fixed,changes=ai_planning.normalize_authored(draft,profile)
    assert fixed['sessions'][0]['steps'][1]['intensity'].startswith('RIR 2')
    assert fixed['sessions'][0]['steps'][1]['sets']==before['sessions'][0]['steps'][1]['sets']
    assert ai_planning.validate(fixed,profile)


def test_compact_revision_reviews_the_complete_changed_plan(inputs):
    profile,state,draft=inputs;state['compact_revisions']=True;calls=[]
    def model(messages,task):
        calls.append(task)
        if task=='plan_generate':return copy.deepcopy(draft)
        if task=='plan_revise':
            request=json.loads(messages[1]['content'])
            assert 'changes' in request['required_schema']['properties']
            return {'changes':[{'path':['sessions',0,'purpose'],'value':'按反馈说明上肢训练目的','reason':'说明主目标'}]}
        if calls.count('plan_review')==1:return {'score':70,'passed':False,'issues':[],'must_fix':['明确训练目的']}
        reviewed=json.loads(messages[1]['content'])['draft']
        assert reviewed['sessions'][0]['purpose']=='按反馈说明上肢训练目的'
        assert reviewed['sessions'][1:]==ai_planning.Draft.model_validate(draft).model_dump(mode='json')['sessions'][1:]
        return approved()
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and any(x['stage']=='revision_patch' for x in result['review_trace'])
    assert calls==['plan_generate','plan_review','plan_revise','plan_review']


@pytest.mark.parametrize('path',[['quality','score'],['generator','model'],['sessions']])
def test_compact_revision_cannot_edit_quality_metadata_or_replace_entire_week(inputs,path):
    profile,state,draft=inputs
    with pytest.raises(ValueError):ai_planning.apply_changes(draft,{'changes':[{'path':path,'value':100,'reason':'不得绕过审查'}]})


def test_adopted_framework_can_roll_forward_without_reusing_old_scores(inputs):
    from app import planning_jobs
    profile,state,draft=inputs
    profile.update(planning_style='preserve_structure',limitations='')
    old=ai_planning.validate(draft,profile)
    old['quality']={'status':'reviewed','score':90}
    old['review_trace']=[{'stage':'independent_review','passed':True}]
    state.update(profile=profile,plan=old)
    before=copy.deepcopy(old)
    baseline=planning_jobs.baseline_for(state,'2026-11-23')
    assert baseline['week']=='2026-11-23'
    assert baseline['sessions'][0]['date']=='2026-11-23'
    assert 'quality' not in baseline and 'review_trace' not in baseline
    assert old==before
    state['upcoming']=copy.deepcopy(old);state['upcoming']['week']='2026-11-23'
    state['plan']=None
    assert planning_jobs.baseline_for(state,'2026-11-23') is not None
    assert planning_jobs.baseline_for(state,'2026-11-23','不保留，换个框架') is None
    profile['minutes']=20
    assert planning_jobs.baseline_for(state,'2026-11-23') is None


def test_full_revision_fallback_is_still_independently_reviewed(inputs):
    profile,state,draft=inputs;state['compact_revisions']=True;calls=[]
    def model(messages,task):
        calls.append(task)
        if task!='plan_review':return copy.deepcopy(draft)
        return approved() if calls.count('plan_review')==2 else {'score':70,'passed':False,'issues':[],'must_fix':['解释目标剂量']}
    result=ai_planning.pipeline(profile,state,model,None)
    assert result['ok'] and calls.count('plan_review')==2
    assert any(x['stage']=='revision_full_fallback' for x in result['review_trace'])


def test_patch_can_append_to_a_default_empty_field_with_standard_replace_op(inputs):
    profile,state,draft=inputs
    draft['sessions'][0]['steps'][1].pop('alternatives')
    repaired,_=ai_planning.apply_changes(draft,{'changes':[{'op':'add','path':['sessions',0,'steps',1,'alternatives',0],'value':'同目标替代动作','reason':'可选偏好'}]})
    assert repaired['sessions'][0]['steps'][1]['alternatives']==['同目标替代动作']
