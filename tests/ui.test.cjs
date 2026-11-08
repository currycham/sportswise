const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function setup(){
 const elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',hidden:true,open:false,addEventListener(){},showModal(){this.open=true},close(){this.open=false},classList:{add(){},remove(){}},querySelector(){return null},querySelectorAll(){return []},focus(){}});return elements.get(id)};
 const ctx={document:{querySelector:el,addEventListener(){}},navigator:{},window:{addEventListener(){}},setTimeout,clearTimeout,setInterval,clearInterval,console,structuredClone,Date,Map,FormData:class{}};
 vm.runInNewContext(fs.readFileSync('static/movement-guides.js','utf8'),ctx);
 const source=fs.readFileSync('static/app.js','utf8').replace(/\nload\(\);\s*$/,'');
 vm.runInNewContext(source+'\nglobalThis.ui={set(v){data=v},timer(id){timerSession=id;timerStart=Date.now()-3000},todayPage,growthPage,trainingDetail,feedback,landing,accountEntry,accountCard,accountMenu,mePage,workoutStep,showMovementGuide,periodButton,renderCoach,guide:SportsWiseMovementGuides};',ctx);
 return {ui:ctx.ui,elements};
}
function fixture(){
 const session={id:'today-session',date:'2026-11-01',kind:'walk',title:'轻松步行',minutes:10,purpose:'找到节奏',steps:[],status:'planned'};
 return {today:'2026-11-01',revision:1,user:{demo:true},capabilities:{ai:true,mail:false},direction:['maintain','先保持当前安排'],notices:[],deliveries:[],stats:{completed:1,planned:1,minutes:8,unknown:0,original_minutes:10,planned_minutes:10},state:{profile:{name:'虚构用户',goal:'habit',days:[6],minutes:15},plan:{week:'2026-10-26',phase:'适应与校准',sessions:[session]},upcoming:null,history:[],records:[],chat:[],reviews:[],settings:{},risk:{level:'none',message:''}}};
}
test('completed card separates actual minutes and planned minutes',()=>{
 const {ui}=setup(),d=fixture();
 d.state.records=[{session_id:'today-session',date:'2026-11-01',status:'partial',minutes:8,effort:'okay'}];ui.set(d);
 const html=ui.todayPage();assert.match(html,/实际 8 分钟/);assert.match(html,/原安排 10 分钟/);assert.match(html,/完成一点/);
});
test('a future first plan does not mark today as prescribed rest',()=>{
 const {ui}=setup(),d=fixture();
 d.state.upcoming={week:'2026-11-02',sessions:[]};d.state.plan=null;ui.set(d);
 const html=ui.todayPage();
 assert.match(html,/今天尚未安排训练/);assert.match(html,/新计划从/);
 assert.doesNotMatch(html,/今天的安排是恢复休息/);
});
test('ending timer after seconds defaults to partial, not full completion',()=>{
 const {ui,elements}=setup(),d=fixture();ui.set(d);ui.timer('today-session');ui.feedback('today-session');
 const html=elements.get('#modal').innerHTML;
 assert.match(html,/name="status" value="partial" checked/);
 assert.doesNotMatch(html,/name="status" value="completed" checked/);
 assert.match(html,/name="minutes" value="0"/);
});
test('first visit offers from-zero planning separately from example',()=>{
 const {ui,elements}=setup();ui.landing();const html=elements.get('#app').innerHTML;
 assert.match(html,/data-action="new-demo">先为我制定计划/);
 assert.match(html,/data-action="demo">看看示例计划/);
 assert.match(html,/预览调整/);
});
test('resistance details show dosage, technique and an actionable replacement',()=>{
 const {ui}=setup(),d=fixture();const s=d.state.plan.sessions[0];s.kind='strength';
 s.steps=[{title:'哑铃杯式深蹲',minutes:5,sets:2,reps:8,rest_seconds:75,detail:'全脚掌踩稳',
           caution:'膝盖随脚尖方向',benefit:'训练大腿和臀部',alternatives:[{title:'椅子坐站'}]}];
 d.session_options={[s.id]:['mobility']};ui.set(d);
 const html=ui.trainingDetail(s);
 for(const re of [/2 组 × 8 次/,/休息 75 秒/,/全脚掌踩稳/,/训练大腿和臀部/,/预览替代：椅子坐站/]) assert.match(html,re);
});
test('growth prioritizes recording, shows live praise and heart rate, and unlocks its garden',()=>{
 const {ui,elements}=setup(),d=fixture();
 d.growth={week:{id:'week:2026-10-26',start:'2026-10-26',headline:'值得肯定',summary:'散步 20 分钟',
   praise:['你为自己留出了时间。'],next:'固定下一次散步',analysis:{sessions:1,breakdown:[{label:'快走',sessions:1,minutes:20}]}},
   garden:{plots:[{kind:'walk',icon:'🌼',name:'步行花',count:1,activity:'快走'}],total:1,variety:1,stage:'初绿花园'}};
 d.state.records=[{id:'walk-1',status:'completed',minutes:20,date:d.today,activity:'快走',avg_heart_rate:126}];ui.set(d);
 const html=ui.growthPage();
 assert.ok(html.indexOf('记录一次运动')<html.indexOf('运动回顾'));
 assert.match(html,/你为自己留出了时间/);assert.match(html,/步行花，1 次/);assert.match(html,/平均心率 126 次\/分/);
 ui.feedback(null,'walk-1');assert.match(elements.get('#modal').innerHTML,/name="avg_heart_rate"[^>]*value="126"/);
});

test('account access stays explicit for trial and signed-in users',()=>{
 const {ui,elements}=setup(),d=fixture();ui.set(d);
 assert.match(ui.accountEntry(),/data-action="login"/);
 assert.match(ui.accountEntry(),/登录 \/ 注册/);
 assert.match(ui.accountCard(),/登录后保存你的运动旅程/);
 d.user={demo:false,email:'qa@example.invalid'};ui.set(d);
 assert.match(ui.accountEntry(),/data-action="account"/);
 assert.match(ui.accountCard(),/管理账号/);
 ui.accountMenu();assert.match(elements.get('#modal').innerHTML,/进入个人管理/);
 assert.match(elements.get('#modal').innerHTML,/退出登录 \/ 切换账号/);
});

// Small DOM harness for async planning: replacing the app root clears unsaved
// input just as a browser would, while a banner replacement leaves it intact.
function planningSetup(respond){
 const elements=new Map(),requests=[],storage=new Map(),timers=new Map();let timerId=0,rootWrites=0;
 const make=(selector)=>{
  let html='';const element={value:'',hidden:true,open:false,textContent:'',outerHTML:'',
   addEventListener(){},showModal(){this.open=true},close(){this.open=false},
   classList:{add(){},remove(){}},querySelector(query){if(selector==='#modal'&&query==='[data-action="apply-proposal"]'){const hit=html.match(/data-action="apply-proposal" data-id="([^"]+)"/);return hit?{dataset:{id:hit[1]}}:null}return null},querySelectorAll(){return []},focus(){}};
  Object.defineProperty(element,'innerHTML',{get(){return html},set(value){html=value;if(selector==='#app'){rootWrites++;const dirty=elements.get('#unsaved-reminder');if(dirty)dirty.value='18:30'}}});
  return element;
 };
 const el=(selector)=>{
  if(['#planning-stage','#planning-submit','#proposal-error','#timer-value'].includes(selector)){
   const id=selector.slice(1);if(!elements.get('#modal')?.innerHTML.includes(`id="${id}"`))return null;
  }
  if(selector==='#planning-banner'&&!elements.get('#app')?.innerHTML.includes('id="planning-banner"'))return null;
  if(!elements.has(selector))elements.set(selector,make(selector));return elements.get(selector);
 };
 const ctx={document:{querySelector:el,addEventListener(){}},navigator:{},window:{addEventListener(){},scrollTo(){}},
  console,structuredClone,Date,Map,FormData:class{},
  localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id),
  setInterval(){return ++timerId},clearInterval(){},
  fetch:async(url,init={})=>{const request={url,method:init.method||'GET',body:init.body?JSON.parse(init.body):null};requests.push(request);const response=await respond(request);return {ok:response.status==null||response.status<400,status:response.status||200,json:async()=>response.body};}
 };
 const source=fs.readFileSync('static/app.js','utf8').replace(/\nload\(\);\s*$/,'');
 vm.runInNewContext(source+'\nglobalThis.ui={set(v){data=v},getData(){return data},getJob(){return planningJob},setJob(v){planningJob=v},timer(id){timerSession=id;timerStart=Date.now()-3000},getTimer(){return timerStart},training,showMovementGuide,restorePlanning,startPlanning,pollPlanning,planningModal,planningTime,estimateText,closeModal,action};',ctx);
 const d=fixture();d.user={id:'account-a',email:'a@example.invalid',demo:false};
 Object.assign(d.state.profile,{likes:['walking','strength'],equipment:['dumbbell'],place:'gym',level:'regular'});
 d.planning_job={id:'job-a',status:'queued',stage:'queued',message:'已排队'};
 ctx.ui.set(d);ctx.ui.restorePlanning();
 el('#app').innerHTML='<section id="planning-banner"></section><form>尚未保存的提醒</form>';
 el('#unsaved-reminder').value='19:45';
 return {ui:ctx.ui,d,el,requests,storage,timers,rootWrites:()=>rootWrites,async advancePoll(){const scheduled=[...timers.entries()].find(([id,t])=>t.ms===2500);if(scheduled){timers.delete(scheduled[0]);await scheduled[1].fn()}else await ctx.ui.pollPlanning('job-a')}};
}

function planningDraft(){
 return {summary:'虚构训练草案',plan:{id:'new-plan',week:'2026-11-02',policy:'ai-reviewed',source:'ai_reviewed',
  rationale:'按现有资料生成',sessions:[{id:'new-session',date:'2026-11-02',kind:'strength',title:'虚构上肢训练',
   minutes:30,purpose:'核对操作流程',intensity:'组末保留余力',steps:[{title:'虚构划船',minutes:30,sets:2,reps:8,rest_seconds:90,detail:'虚构动作说明'}]}],
  assumptions:['使用熟悉的轻阻力'],questions:['确认可用器械'],quality:{type:'independent_model_review',score:85,status:'reviewed'},review_trace:[]}};
}

test('queued, running and background completion preserve another page’s unsaved input',async()=>{
 const updates=[{status:'queued',stage:'queued',message:'已排队'},
  {status:'running',stage:'reviewing',message:'独立评分进行中'},
  {status:'done',stage:'done',message:'草案已完成',proposal_id:'proposal-a'}];
 const h=planningSetup(async request=>{assert.equal(request.url,'/api/planning/job-a');return {body:updates.shift()}});
 const root=h.rootWrites(),originalPlan=structuredClone(h.d.state.plan);
 for(const expected of ['queued','running','done']){
  await h.advancePoll();
  assert.equal(h.ui.getJob().status,expected);
  assert.equal(h.rootWrites(),root,'polling must not replace the app root');
  assert.equal(h.el('#unsaved-reminder').value,'19:45');
  assert.equal(h.el('#modal').open,false,'background completion must not interrupt the user');
 }
 assert.deepEqual(h.ui.getData().state.plan,originalPlan,'generation cannot adopt its own result');
 assert.match(h.el('#planning-banner').outerHTML,/查看计划草案/);
 assert.match(h.storage.get('sportswise-planning:account-a'),/proposal-a/);
 assert.ok(h.requests.every(x=>x.method==='GET'),'polling must neither reload state nor adopt');
 assert.ok(![...h.timers.values()].some(t=>t.ms===2500),'terminal completion stops polling');
});

test('visible completion opens detailed preview and adopts only after the explicit action',async()=>{
 const draft=planningDraft();let h;
 h=planningSetup(async request=>{
  if(request.url==='/api/planning/job-a')return {body:{status:'done',stage:'done',message:'已完成',proposal_id:'proposal-a'}};
  if(request.url==='/api/proposals/proposal-a')return {body:draft};
  if(request.url==='/api/proposals/proposal-a/apply'){
   assert.equal(request.method,'POST');assert.equal(request.body.revision,1);
   return {body:{...h.d,revision:2,result:'下一周已安排',planning_job:null,
    state:{...h.d.state,upcoming:draft.plan}}};
  }
  throw new Error('Unexpected request '+request.url);
 });
 h.ui.planningModal();const root=h.rootWrites();
 await h.ui.pollPlanning('job-a');
 assert.equal(h.rootWrites(),root);
 const preview=h.el('#modal').innerHTML;
 for(const text of ['虚构上肢训练','虚构划船','2 组','90 秒','使用熟悉的轻阻力','确认可用器械'])assert.ok(preview.includes(text),text);
 assert.match(preview,/data-action="apply-proposal" data-id="proposal-a"/);
 assert.equal(h.ui.getData().state.upcoming,null);
 assert.equal(h.requests.length,2,'completion opens a preview without automatically applying it');
 await h.ui.action('apply-proposal',{dataset:{id:'proposal-a'},disabled:false});
 assert.equal(h.ui.getData().state.upcoming.id,'new-plan');
 assert.equal(h.el('#modal').open,false);
 assert.equal(h.ui.getJob(),null);
 assert.equal(h.storage.has('sportswise-planning:account-a'),false);
});

test('failed planning keeps unsaved input and the current plan, with a clear retry path',async()=>{
 const h=planningSetup(async request=>({body:{status:'failed',stage:'failed',message:'独立评分未通过',error:'仍有待修正的问题',
  review_trace:[{round:1,stage:'independent_review',review:{score:72,must_fix:['减少冲突的训练量'],issues:[]}}]}}));
 h.ui.planningModal();const root=h.rootWrites(),original=structuredClone(h.d.state.plan);
 await h.ui.pollPlanning('job-a');
 assert.equal(h.rootWrites(),root);assert.equal(h.el('#unsaved-reminder').value,'19:45');
 assert.deepEqual(h.ui.getData().state.plan,original);
 const html=h.el('#modal').innerHTML;
 assert.match(html,/独立评分未通过/);assert.match(html,/减少冲突的训练量/);
 assert.match(html,/data-action="ai-plan">重新生成/);assert.match(html,/已有计划继续保留/);
 assert.ok(![...h.timers.values()].some(t=>t.ms===2500));
});

test('an in-flight response for another account cannot show or store its proposal',async()=>{
 let resolve;
 const h=planningSetup(()=>new Promise(r=>{resolve=r}));
 const pending=h.ui.pollPlanning('job-a');
 const b=structuredClone(h.d);b.user={id:'account-b',email:'b@example.invalid',demo:false};b.planning_job=null;
 h.ui.set(b);h.ui.restorePlanning();
 resolve({body:{status:'done',proposal_id:'private-proposal-a'}});await pending;
 assert.equal(h.ui.getJob(),null);
 assert.ok(!h.el('#modal').innerHTML.includes('private-proposal-a'));
 assert.ok(!h.storage.has('sportswise-planning:account-b'));
 assert.ok(!h.storage.get('sportswise-planning:account-a').includes('private-proposal-a'));
 const requests=h.requests.length;
 await h.ui.pollPlanning('job-a');assert.equal(h.requests.length,requests,'old account cannot keep polling');
});


test('retry starts the new job instead of restoring the previous failed snapshot',async()=>{
 const h=planningSetup(async request=>{
  if(request.url==='/api/planning'&&request.method==='POST')return {body:{job_id:'job-retry'}};
  if(request.url==='/api/planning/job-retry')return {body:{status:'running',stage:'generating',message:'新任务'}};
  throw new Error('Unexpected old-job request '+request.url);
 });
 const failed={...h.d,planning_job:{id:'job-old',status:'failed',stage:'failed'}};
 h.ui.set(failed);h.ui.restorePlanning();
 await h.ui.startPlanning('保留我的进阶结构');
 await Promise.resolve();await Promise.resolve();
 assert.equal(h.ui.getJob().id,'job-retry');
 assert.ok(h.requests.some(x=>x.url==='/api/planning/job-retry'));
 assert.ok(!h.requests.some(x=>x.url==='/api/planning/job-old'));
});

test('a refreshed state clears a draft adopted on another device',()=>{
 const h=planningSetup(async()=>{throw new Error('No request expected')});
 h.ui.set({...h.d,planning_job:null});h.ui.restorePlanning();
 assert.equal(h.ui.getJob(),null);
 assert.equal(h.storage.has('sportswise-planning:account-a'),false);
});


test('a new account’s active job resumes after an older account’s in-flight query',async()=>{
 let resolveA;
 const h=planningSetup(request=>request.url==='/api/planning/job-a'?new Promise(r=>{resolveA=r}):
  Promise.resolve({body:{status:'running',stage:'reviewing',message:'B的任务'}}));
 const pending=h.ui.pollPlanning('job-a');
 const b={...h.d,user:{id:'account-b',email:'b@example.invalid',demo:false},planning_job:{id:'job-b',status:'running'}};
 h.ui.set(b);h.ui.restorePlanning();await h.ui.pollPlanning('job-b');
 assert.ok([...h.timers.values()].some(t=>t.ms===2500));
 resolveA({body:{status:'done',proposal_id:'private-a'}});await pending;
 await h.advancePoll();assert.equal(h.ui.getJob().id,'job-b');
 assert.ok(h.requests.some(x=>x.url==='/api/planning/job-b'));
 assert.ok(!JSON.stringify(h.ui.getJob()).includes('private-a'));
});


test('waiting UI shows estimate basis, elapsed time and an honest overrun without a fake countdown',()=>{
 const h=planningSetup(async()=>{throw new Error('No requests')});
 const text=h.ui.planningTime({status:'running',elapsed_seconds:185,over_estimate:true,
  estimate:{min_seconds:60,max_seconds:180,basis:'preliminary',queue_included:true},estimate_extension:'评审需要修正'});
 for(const expected of ['1–3 分钟','初步估计','含排队','已用 3 分 5 秒','超过预估','评审需要修正'])assert.ok(text.includes(expected),expected);
 assert.equal(h.ui.planningTime({status:'done'}),'');
 assert.ok(!text.includes('%'));
});

test('period controls are female-only and tucked into a closed body-feedback section',()=>{
 const {ui}=setup(),d=fixture();Object.assign(d.state.profile,{likes:['strength'],equipment:['dumbbell']});
 for(const sex of ['male','undisclosed',undefined]){
  d.state.profile.sex=sex;ui.set(d);
  assert.doesNotMatch(ui.todayPage(),/data-action="period"/);
  assert.doesNotMatch(ui.mePage(),/data-action="period"/);
 }
 d.state.profile.sex='female';ui.set(d);
 assert.doesNotMatch(ui.todayPage(),/data-action="period"/,'even women should not get a prominent daily-period button');
 const html=ui.mePage();assert.match(html,/<details><summary>身体反馈与临时调整<\/summary>/);
 assert.match(html,/data-action="period"/);assert.doesNotMatch(html,/<details open><summary>身体反馈/);
});

test('movement rows keep dosage visible but reveal guidance and rationale only on request',()=>{
 const {ui,elements}=setup(),d=fixture(),session=d.state.plan.sessions[0];session.kind='strength';
 session.steps=[{title:'单臂哑铃划船',minutes:6,sets:3,reps:8,each_side:true,rest_seconds:75,
  intensity:'组末保留2次余力',detail:'支撑手撑凳，控制拉起和下放',caution:'保持腰背中立',benefit:'训练背部拉力'}];ui.set(d);
 const html=ui.workoutStep(session,session.steps[0],0);
 assert.match(html,/3 组 × 8 次 \/ 每侧 · 组间休息 75 秒/);assert.match(html,/data-action="movement-guide"/);
 assert.match(html,/<details class="step-explanation"><summary>为什么这样练<\/summary>/);
 assert.doesNotMatch(html,/<details[^>]* open/);
 assert.ok(html.indexOf('动作要领')>html.indexOf('<details class="step-explanation">'));
 ui.showMovementGuide(session.id,0);const guide=elements.get('#modal').innerHTML;
 assert.match(guide,/<svg/);assert.match(guide,/拉类 · 动作方向简图，以本次文字要领为准/);
 assert.match(guide,/支撑手撑凳，控制拉起和下放/);assert.match(guide,/保持腰背中立/);
});

test('complex or unknown skills never get a misleading generic action picture',()=>{
 const {ui}=setup();
 for(const title of ['杠铃抓举','HYROX站点循环','双力臂','陌生专项动作']){
  const guide=ui.guide.render(title,'');assert.doesNotMatch(guide,/<svg/);assert.match(guide,/暂未提供配图/);
 }
 const expected=[['高脚杯深蹲','squat'],['单腿RDL','hinge'],['哑铃卧推','push'],['辅助引体向上','pull'],
  ['后脚抬高分腿蹲','lunge'],['Pallof抗旋','core'],['慢跑','run'],['箱跳','jump'],['药球胸前传球','throw']];
 for(const [name,category] of expected){assert.equal(ui.guide.classify(name),category,name);assert.match(ui.guide.render(name),/<svg/,name+' must have an actual illustration, not just a classification');}
});

test('the coach offers generation only after an actionable discussion summary exists',()=>{
 const {ui,elements}=setup(),d=fixture();ui.set(d);ui.renderCoach();
 assert.doesNotMatch(elements.get('#coach').innerHTML,/data-action="coach-plan"/);
 d.state.coach_plan_request='保留周结构，减少周二的同肌群负荷';ui.set(d);ui.renderCoach();
 const html=elements.get('#coach').innerHTML;assert.match(html,/data-action="coach-plan"/);assert.match(html,/按讨论生成草案/);
 assert.doesNotMatch(html,/自动采用/);
});

test('opening a movement guide and returning preserves the running timer and feedback action',async()=>{
 const h=planningSetup(async()=>{throw new Error('No request expected')});
 const session=h.d.state.plan.sessions[0];session.steps=[{title:'轻松走动',minutes:10,detail:'保持自然呼吸'}];
 h.ui.timer(session.id);const start=h.ui.getTimer();h.ui.training(session.id);
 assert.match(h.el('#modal').innerHTML,/结束并记录/);
 h.ui.showMovementGuide(session.id,0);assert.match(h.el('#modal').innerHTML,/返回训练计时/);
 await h.ui.action('guide-back',{dataset:{}});
 assert.equal(h.ui.getTimer(),start,'reading guidance must not restart or erase elapsed activity');
 assert.match(h.el('#modal').innerHTML,/结束并记录/);
});

test('asking why discusses the identified movement, and only an explicit summary action starts planning',async()=>{
 let h;const summary='保留上肢训练，下一次只降低划船负荷并重新评价';
 h=planningSetup(async request=>{
  if(request.url==='/api/coach')return {body:{...h.d,state:{...h.d.state,coach_plan_request:summary,coach_plan_session_id:request.body.session_id,coach_plan_proposal_id:null,
   chat:[{role:'user',text:request.body.text},{role:'assistant',text:'先解释原先安排及可调整的信号。'}]},
   result:{reply:'先解释原先安排及可调整的信号。',proposal_id:null,mode:'ai_dialogue',can_plan:true,plan_request:summary}}};
  if(request.url==='/api/planning')return {body:{job_id:'job-discussion'}};
  if(request.url==='/api/planning/job-discussion')return {body:{status:'queued',stage:'queued',message:'已排队'}};
  throw new Error('Unexpected request '+request.url);
 });
 h.d.planning_job=null;h.ui.setJob(null);h.storage.clear();
 const session=h.d.state.plan.sessions[0];session.title='上肢表现';session.steps=[{title:'单臂哑铃划船',minutes:10,detail:'虚构说明'}];
 await h.ui.action('ask-step-why',{dataset:{id:session.id,step:'0'}});
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/coach');
 assert.equal(h.requests[0].body.session_id,session.id);
 assert.match(h.requests[0].body.text,/课程ID：today-session/);assert.match(h.requests[0].body.text,/单臂哑铃划船/);
 assert.match(h.el('#coach').innerHTML,/按讨论生成草案/);
 await h.ui.action('coach-plan',{dataset:{}});
 const planning=h.requests.find(r=>r.url==='/api/planning');assert.ok(planning);
 assert.equal(planning.body.request_detail,summary,'use the actionable server summary, not a clipped chat transcript');
 assert.equal(planning.body.session_id,session.id,'an adopted session keeps its discussion target instead of silently planning next week');
 assert.equal(planning.body.proposal_id,undefined);
 assert.ok(!h.requests.some(r=>r.url.includes('/apply')));
});

test('a not-yet-adopted draft can open its own movement guide and return to the same preview',async()=>{
 const draft=planningDraft();const h=planningSetup(async request=>{
  assert.equal(request.url,'/api/proposals/proposal-unadopted');return {body:draft};
 });
 assert.ok(!h.d.state.plan.sessions.some(s=>s.id==='new-session'));
 await h.ui.action('view-proposal',{dataset:{id:'proposal-unadopted'}});
 h.ui.showMovementGuide('new-session',0);
 assert.match(h.el('#modal').innerHTML,/虚构动作说明/);
 await h.ui.action('guide-back',{dataset:{}});
 assert.match(h.el('#modal').innerHTML,/data-action="apply-proposal" data-id="proposal-unadopted"/);
 assert.equal(h.ui.getData().state.upcoming,null,'viewing guidance must not adopt a draft');
 assert.ok(h.requests.every(r=>r.method==='GET'));
});

test('discussing an unadopted draft passes its proposal and session into explicit regeneration',async()=>{
 let h;const draft=planningDraft(),summary='仅将草案中的划船改成支持式划船，其余结构保留';
 h=planningSetup(async request=>{
  if(request.url==='/api/proposals/proposal-draft-context')return {body:draft};
  if(request.url==='/api/coach')return {body:{...h.d,state:{...h.d.state,
   coach_plan_request:summary,coach_plan_session_id:request.body.session_id,coach_plan_proposal_id:request.body.proposal_id,
   chat:[{role:'assistant',text:'先解释草案中的训练取舍。'}]},
   result:{reply:'先解释草案中的训练取舍。',can_plan:true,plan_request:summary,proposal_id:null}}};
  if(request.url==='/api/planning')return {body:{job_id:'job-draft-context'}};
  if(request.url==='/api/planning/job-draft-context')return {body:{status:'queued',stage:'queued',message:'已排队'}};
  throw new Error('Unexpected request '+request.url);
 });
 h.d.planning_job=null;h.ui.setJob(null);h.storage.clear();
 await h.ui.action('view-proposal',{dataset:{id:'proposal-draft-context'}});
 assert.equal(h.el('#modal').open,true);
 await h.ui.action('ask-step-why',{dataset:{id:'new-session',step:'0'}});
 const discussion=h.requests.find(r=>r.url==='/api/coach');
 assert.equal(discussion.body.proposal_id,'proposal-draft-context');assert.equal(discussion.body.session_id,'new-session');
 assert.match(discussion.body.text,/虚构划船/);
 assert.equal(h.el('#modal').open,false,'close the top-layer dialog before showing the coach drawer');
 assert.equal(h.el('#coach').hidden,false);
 assert.ok(!h.requests.some(r=>r.url==='/api/planning'),'a why question must not start generation');
 await h.ui.action('coach-plan',{dataset:{}});
 const generation=h.requests.find(r=>r.url==='/api/planning');
 assert.equal(generation.body.session_id,'new-session');assert.equal(generation.body.proposal_id,'proposal-draft-context');
 assert.equal(generation.body.request_detail,summary);
 assert.equal(h.ui.getData().state.upcoming,null);assert.ok(!h.requests.some(r=>r.url.includes('/apply')));
});

test('adopted sessions never borrow a preview proposal context, even when ids coincide',async()=>{
 let h;const draft=planningDraft();draft.plan.sessions[0].id='today-session';
 h=planningSetup(async request=>{
  if(request.url==='/api/proposals/proposal-collision')return {body:draft};
  if(request.url==='/api/coach')return {body:{...h.d,result:{reply:'解释当前安排。',proposal_id:null,can_plan:false}}};
  throw new Error('Unexpected request '+request.url);
 });
 await h.ui.action('view-proposal',{dataset:{id:'proposal-collision'}});
 await h.ui.action('ask-session-why',{dataset:{id:'today-session'}});
 const request=h.requests.find(r=>r.url==='/api/coach');assert.equal(request.body.session_id,'today-session');
 assert.equal(request.body.proposal_id,undefined,'an adopted session resolves against actual state, not a draft');
 assert.equal(h.el('#modal').open,false);assert.equal(h.el('#coach').hidden,false);
});

test('common chair sit-to-stand and supported heel raises show their real support props',()=>{
 const {ui}=setup();
 const sit=ui.guide.render('椅子坐站');assert.equal(ui.guide.classify('椅子坐站'),'chair_stand');
 assert.match(sit,/<svg/);assert.match(sit,/data-guide-prop="chair"/);assert.match(sit,/坐稳脚踩地/);assert.match(sit,/站起后再坐回/);
 const heel=ui.guide.render('扶稳提踵');assert.equal(ui.guide.classify('扶稳提踵'),'heel_raise');
 assert.match(heel,/<svg/);assert.match(heel,/data-guide-prop="wall"/);assert.match(heel,/脚跟缓慢抬起/);
 assert.equal(ui.guide.classify('坐姿提踵'),null,'a seated heel raise must not get the standing illustration');
 assert.doesNotMatch(sit+heel,/专业核对|专业认证|精准动作示范|经过核对/);
});
