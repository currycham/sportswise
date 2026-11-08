"""Curated primary-source principles shared by programming, explanations and QA.

These are adaptations for SportsWise, not reproduced certification curricula.
"""
VERSION='professional-basis-2026-11-08-sport'
SOURCES={
'fiba_physical':{'title':'FIBA/WABC · Level 2 体能准备与赛季编排','url':'https://assets.fiba.basketball/image/upload/documents-corporate-wabc-coaching-manual-level-2-eng.pdf','kind':'sport_coaching_framework','checked':'2026-11-08','access':'official_pdf_indexed_section_3.1.1_p161; full_pdf_exceeds_fetch_limit','scope':'篮球运动效率、体能与年度赛季安排；不是个体负荷处方。'},
'usab_youth':{'title':'USA Basketball · 青少年篮球训练与恢复建议','url':'https://www.usab.com/play/youth-basketball-guidelines','kind':'youth_sport_guidance','checked':'2026-11-08','scope':'仅青少年；不能把年龄分档的时长或休息规定直接用于成年竞技运动员。'},
'bwf_pathway':{'title':'BWF · 教练路径、技术战术体能与年度赛训规划','url':'https://system.bwfbadminton.com/documents/folder_1_81/Announcements/1.%20Programme%20-%20BWF%20World%20Coaching%20Conference%202017.pdf','kind':'sport_coaching_framework','checked':'2026-11-08','access':'official_pdf_indexed_excerpt; direct_fetch_402','scope':'核对官方2017路径文件可检索段落；支持分层与年度赛训整合，不代表已读当前完整Level 2教材，不提供个体间歇或杀球剂量。'},
'wa_javelin':{'title':'World Athletics · 标枪运动需求、技术阶段与安全','url':'https://worldathletics.org/disciplines/throws/javelin-throw','kind':'sport_event_overview','checked':'2026-11-08','scope':'项目概览；可说明速度、力量、时序协调及安全要求，不能推出个人投掷次数、强度、器械重量或技术诊断。'},
'nsca_needs':{'title':'NSCA · 运动需求分析、监测与跨专业协作职责','url':'https://www.nsca.com/certification/cpss/scope-of-practice/','kind':'professional_scope','checked':'2026-11-08','scope':'支持个体需求分析、评估、监测与教练沟通，不是专项训练处方。'},
'crossfit_scaling':{'title':'CrossFit · 动作质量、一致性与强度','url':'https://www.crossfit.com/essentials/mechanics-consistency-intensity-part-1-what-does-it-mean','kind':'professional_framework'},
'hyrox_hybrid':{'title':'HYROX · 混合训练结构说明','url':'https://hyrox.com/training-partner/hwpo-training/','kind':'sport_framework_not_prescription'},

'ace_ift':{'title':'ACE · IFT 训练框架（当前三阶段）','url':'https://www.acefitness.org/about-ace/ace-ift-model/','kind':'professional_framework'},
'ace_bodyweight':{'title':'ACE · 按目标编排徒手训练','url':'https://www.acefitness.org/continuing-education/certified/september-2026/9193/body-weight-training-by-design-programming-for-every-fitness-goal/','kind':'professional_education'},
'acsm_resistance':{'title':'ACSM · 2026 成人抗阻训练立场文件','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC12965823/','kind':'evidence_review'},
'nsca_periodization':{'title':'NSCA · 体能训练周期化与编排','url':'https://www.nsca.com/certification/cpss/essentials-of-sport-science','kind':'professional_framework'},
'cdc_activity':{'title':'CDC · 成年人有氧与抗阻活动建议','url':'https://www.cdc.gov/physical-activity-basics/guidelines/adults.html','kind':'public_health_guidance'},
'nhs_run':{'title':'NHS · 新手跑走与恢复日','url':'https://www.nhs.uk/better-health/get-active/get-running-with-couch-to-5k/couch-to-5k-running-plan/','kind':'beginner_programme'},
'nhs_strength':{'title':'NHS · 基础抗阻动作与坐姿变式','url':'https://www.nhs.uk/live-well/exercise/strength-exercises/','kind':'public_health_guidance'},
}
RULES=[
{'id':'sport_needs_and_coach','sources':['nsca_needs'],'principle':'专项运动者先说明项目/位置/单打双打/主侧、专项训练年龄、目标短板、赛季和比赛日期、主教练已有技术课与体能安排；分清专项技术、战术、辅助体能和恢复。用户给的已有赛训必须计入总负荷，不得叠加一套独立通用增肌周。未知信息列具体questions/assumptions并给可执行的有边界辅助方案，不能编造1RM、阈值心率、出场分钟或高强度基线。'},
{'id':'sport_season_load','sources':['nsca_needs'],'principle':'竞技期优先比赛准备与维护能力；协调专项主教练，说明本计划替代还是补充现有内容、每周总赛训时长和高负荷分布。观察实际课时×课后RPE、局部不适、睡眠与表现变化，不能用单一负荷比值或通用48小时规则宣称安全；临赛不自动安排新刺激或疲劳性测试。'},
{'id':'basketball_specificity','sources':['fiba_physical','nsca_needs'],'principle':'篮球需要考虑反复加减速、变向与落地控制、弹跳及对抗相关力量；已存在的球场冲刺跳跃也计入负荷。赛季、位置、出场时间未知先问，不以连续慢跑或通用大肌群增肌代替所有篮球准备，也不因专项性而一律添加最大冲刺与跳深；技术战术由篮球教练协调。'},
{'id':'badminton_specificity','sources':['bwf_pathway','nsca_needs'],'principle':'羽毛球应区分单打/双打、步法制动与回位、弓步及反复起动、肩带和持拍侧负荷，技术战术与辅助体能分开。把多球、跳杀、比赛和场外力量合并考虑；不能由爱好推断连续跳跃或高密度多球已适应，年度赛训安排需与教练对齐。上述需求为产品需求分析，BWF路径本身没有给个体剂量。'},
{'id':'javelin_not_hypertrophy','sources':['wa_javelin','nsca_needs'],'principle':'标枪以助跑到投掷的时序协调、速度/爆发、单侧制动与力量传递为需求，不复制通用增肌计划。药球可作经确认熟悉的辅助爆发练习，但不得冒充标枪技术课。投掷基线/强度/器械/赛季未知时，不自行规定全助跑、高强度投掷次数或百分比，不拿比赛试投次数当训练量；先问主教练处方，保留由教练管理的技术课位置，未确认前提供可执行的熟悉动作辅助体能，明确不是完整专项处方。'},
{'id':'javelin_coaching_safety','sources':['wa_javelin'],'principle':'实际投掷须合适场地、清空落地区及现场专项教练/场地管理，协调肩肘与躯干负荷；新手无现场条件不安排真枪独自全力投掷。不得凭文字诊断投掷技术，疼痛/明显速度与动作质量下降需停止当前刺激并核对；未知项目不等于整个人体能退回新手。'},
{'id':'preserve_athlete_structure','sources':['crossfit_scaling','hyrox_hybrid'],'principle':'已有训练框架的运动者，优先保留有氧、力量与混合体能结构；缩放保持训练刺激，按技术熟练度和恢复调整，不机械复制比赛负重或每日极限测试。'},

{'id':'individual_entry','sources':['ace_ift'],'principle':'按具体运动基础分别选择肌力与有氧起点；规律运动不等于所有领域都进阶。'},
{'id':'dose_by_goal','sources':['acsm_resistance'],'principle':'区分最大力量、增肌和一般体能；明确肌群工作组与余力，不用课名替代剂量。'},
{'id':'recover_progress','sources':['nsca_periodization','acsm_resistance'],'principle':'保持可比较动作，结合恢复安排维持、回退或渐进；不因日期或分数自动加量。'},
{'id':'bodyweight_leverage','sources':['ace_bodyweight'],'principle':'徒手用杠杆、支撑与动作幅度调节负荷；缺少拉力条件要说明，不把低负荷活动冒充充分抗阻。'},
{'id':'aerobic_intensity','sources':['ace_ift','cdc_activity'],'principle':'有氧按谈话测试与体感区分，未测阈值不推算精确心率区间，公共健康推荐不是首周强制配额。'},
{'id':'beginner_run_recovery','sources':['nhs_run'],'principle':'新手以跑走和间隔恢复起步；该起点不能机械套用到已有训练量的跑者。'},
{'id':'restricted_scope','sources':['nhs_strength','ace_ift'],'principle':'有未确认限制时明示过渡与待核对项，不把轻量备选称为完整增肌或康复处方。'},
]
def select(profile):
    keys=['ace_ift','cdc_activity']
    if profile.get('goal') in ('strength','muscle','shape','bone') or 'strength' in profile.get('likes',[]):
        keys+=['acsm_resistance','nhs_strength']
    if 'bodyweight' in profile.get('equipment',[]) or not {'dumbbell','band','gym','full_gym'}.intersection(profile.get('equipment',[])):
        keys+=['ace_bodyweight']
    if profile.get('level') in ('regular','advanced','competitive'):
        keys+=['nsca_periodization']
    if 'running' in profile.get('likes',[]) and profile.get('level') in ('beginner','returning'):
        keys+=['nhs_run']
    text=' '.join(str(profile.get(k,'')) for k in ('sport','sports','likes','current','training_background','training_structure','activity_detail','goal_detail','routine_detail','motivation')).lower()
    if any(word in text for word in ('crossfit','hyrox','综合体能','混合体能')):
        keys+=['crossfit_scaling','hyrox_hybrid']
    sports=[]
    for sport,words,source in (
        ('basketball',('basketball','篮球'),'fiba_physical'),
        ('badminton',('badminton','羽毛球'),'bwf_pathway'),
        ('javelin',('javelin','标枪'),'wa_javelin')):
        if any(word in text for word in words):
            sports.append(sport);keys+=['nsca_needs',source]
    if 'basketball' in sports and profile.get('adult') is False:
        keys+=['usab_youth']
    keys=list(dict.fromkeys(keys))
    sources=[{'id':k,'checked':'2026-11-07',**SOURCES[k]} for k in keys]
    rules=[r for r in RULES if all(s in keys for s in r['sources'])]
    return {'version':VERSION,'sources':sources,'rules':rules,'sports':sports,
            'limits':'来源支持一般原则，不证明本计划已获认证；专项竞技、疾病康复及未知训练基线仍需独立评估。'}
