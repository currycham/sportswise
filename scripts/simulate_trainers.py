"""Synthetic two-week plan audit. No model calls or database/network access.
Run: PYTHONPATH=. .venv/bin/python scripts/simulate_trainers.py
"""
import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app import engine

START = date(2026, 11, 9)
CASES = [
    ('beginner', '成人新手，每周三次', dict(level='beginner',goal='habit',days=[0,2,5],minutes=30)),
    ('returning', '中断半年后恢复体能', dict(level='returning',goal='energy',days=[0,2,5],minutes=40)),
    ('advanced_muscle', '训练三年的进阶增肌者', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell','band'],days=[0,1,2,3,4],minutes=45,current='规律力量训练三年，每周五练，想增加背部与肩部肌肉，熟悉深蹲、硬拉、卧推和划船。')),
    ('regular_muscle', '刚建立规律的增肌者', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell','band'],days=[0,1,2,3,4],minutes=45,current='刚保持两个月规律，每周两次轻力量。')),
    ('advanced_bodyweight', '资深徒手训练者', dict(level='regular',goal='muscle',likes=['strength'],equipment=['bodyweight'],place='home',days=[0,2,4,6],minutes=45,current='已规律徒手训练四年，标准俯卧撑可连续三十次，想进阶练背和肩。')),
    ('runner', '已规律跑步的耐力者', dict(level='regular',goal='endurance',likes=['running','strength'],equipment=['dumbbell'],days=[0,1,2,3,4],minutes=45,current='规律跑步三年，目前每周三十公里，十公里跑接近五十分钟。')),
    ('cyclist', '规律骑行者', dict(level='regular',goal='endurance',likes=['cycling'],equipment=['bodyweight'],days=[0,2,5],minutes=45,current='周末通常骑行两小时，平日骑行四十分钟。')),
    ('menstrual_normal', '经期状态如常，规律增肌', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell'],days=[0,2,4],minutes=40)),
    ('menstrual_ease', '经期希望减量，规律增肌', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell'],days=[0,2,4],minutes=40)),
    ('localized_pain', '进阶增肌，局部膝部和腰背限制', dict(level='regular',goal='muscle',likes=['strength','walking'],equipment=['dumbbell','band'],days=[0,1,2,4,6],minutes=45,limitations='近期膝盖偶尔不适，腰部有旧伤')),
    ('limited_time', '只有十分钟的规律增肌者', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell'],days=[0,2,4],minutes=10)),
    ('multi_sport', '多种偏好，改善体能', dict(level='regular',goal='energy',likes=['walking','running','cycling','badminton','dance','strength'],equipment=['dumbbell'],days=[0,1,2,4,6],minutes=40)),
    ('older_bone', '七十岁希望维护骨骼与平衡的规律步行者', dict(level='regular',goal='bone',likes=['walking'],equipment=['bodyweight'],days=[0,2,5],minutes=30,current='七十岁，每天规律散步，想维护骨骼与上下楼能力，目前没有报告不适。')),
    ('explicit_advanced', '明确进阶、三年训练基线、六十分钟', dict(level='advanced',training_months=36,routine_detail='过去六周每周三次抗阻，杯式深蹲20kg×12，单臂划船每侧16kg×10，地板卧推每手12kg×10，组末约2次余力，隔日恢复良好。',goal='muscle',likes=['strength'],equipment=['dumbbell','band'],days=[0,2,4],minutes=60,current='熟悉基本动作，希望兼顾背部和肩部。')),
    ('healthy_negation', '明确说没有疼痛的进阶增肌者', dict(level='regular',goal='muscle',likes=['strength'],equipment=['dumbbell'],days=[0,2,4],minutes=40,limitations='目前无膝伤，腰背无不适')),
]


def canonical(plan):
    return [{k: copy.deepcopy(s.get(k)) for k in ('kind','minutes','intensity','title','steps')} for s in plan['sessions']]


def summarize(plan):
    active=[s for s in plan['sessions'] if s['kind']!='rest']
    strength=[s for s in active if s['kind']=='strength']
    return {'minutes':sum(s['minutes'] for s in active), 'kinds':dict(Counter(s['kind'] for s in active)),
            'strength_sets':sum(x.get('sets',0) for s in strength for x in s['steps']),
            'titles':[s['title'] for s in active],
            'movements':{s['title']:[{'title':x['title'],'sets':x.get('sets'),'reps':x.get('reps'),
                                       'rest_seconds':x.get('rest_seconds'),'minutes':x['minutes']} for x in s['steps'] if x['kind']=='move'] for s in active},
            'movement_sessions':[{'date':s['date'],'title':s['title'],'minutes':s['minutes'],'steps':[x for x in s['steps'] if x['kind']=='move']} for s in active],
            'programming':plan.get('programming'),
            'time_sums_match':all(sum(x['minutes'] for x in s['steps'])==s['minutes'] for s in active)}


def run():
    # Keep caution validation deterministic, including menstrual windows.
    old_today=engine.today
    engine.today=lambda state=None: START
    output={'policy':engine.PLAN_POLICY,'executed_at_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path('app/engine.py'),Path('app/workouts.py'),Path('app/programming.py'),Path('app/movements.py'))},'cases':[]}
    plans={}
    try:
        for key,label,patch in CASES:
            p=engine.sample_profile();p.update(patch)
            first=engine.generate(p,START)
            second=engine.generate(p,START+timedelta(days=7),first)
            if key.startswith('menstrual_'):
                state=engine.empty();state.update(profile=p,plan=first,upcoming=second,
                    period={'start':START.isoformat(),'end':(START+timedelta(days=4)).isoformat(),
                            'mode':'ease' if key.endswith('ease') else 'normal'})
                first=engine.effective_plan(state,first)
            plans[key]=(first,second)
            output['cases'].append({'id':key,'label':label,'profile':p,'risk':engine.health_risk(p),'week1':summarize(first),'week2':summarize(second),'same_training_two_weeks':canonical(first)==canonical(second)})
        output['advanced_vs_new_regular_identical']=canonical(plans['advanced_muscle'][0])==canonical(plans['regular_muscle'][0])
    finally:
        engine.today=old_today
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='docs/训练者模拟新版结果-2026-11-06.json')
    target=Path(parser.parse_args().output)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2))
    print(json.dumps({'policy':output['policy'],'advanced_vs_new_regular_identical':output['advanced_vs_new_regular_identical'],'cases':[{k:c[k] for k in ('id','risk','same_training_two_weeks')}|{'week1':{k:c['week1'][k] for k in ('minutes','kinds','strength_sets')}} for c in output['cases']]},ensure_ascii=False,indent=2))


if __name__=='__main__':
    run()
